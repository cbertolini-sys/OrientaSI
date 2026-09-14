from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from apps.bancas.models import Banca
from apps.documentos import permissions
from apps.documentos.models import Ata, RevisaoSUGRAD
from apps.documentos.tasks import enviar_ata_para_sugrad, enviar_devolucao_para_orientador
from apps.projetos.models import Projeto


def gerar_ata(projeto):
    """Cria a `Ata` da defesa de `projeto`, numerada e com o PDF já
    renderizado — chamada por `apps.projetos.services.aprovar_projeto`
    (Bloco E, spec §3.2: aprovar e gerar a ata são o mesmo passo). Não checa
    permissão: quem decide SE o projeto pode ser aprovado é
    `aprovar_projeto`; esta função só produz o documento a partir de um
    projeto já aprovado."""
    banca = (
        Banca.objects.filter(projeto=projeto).exclude(status=Banca.CANCELADA).latest("criada_em")
    )

    ano_atual = timezone.localdate().year
    # Custo aceito (spec §4.1): condição de corrida sob criação concorrente
    # de atas no mesmo ano — aprovar um TCC I é uma ação humana de baixa
    # frequência, não um caminho de alto throughput.
    proximo = Ata.objects.filter(gerada_em__year=ano_atual).count() + 1
    numero = f"{proximo:03d}/{ano_atual}"

    corpo_html = render_to_string(
        "documentos/ata_pdf.html", {"projeto": projeto, "banca": banca, "numero": numero}
    )
    from weasyprint import HTML

    pdf_bytes = HTML(string=corpo_html).write_pdf()

    ata = Ata(projeto=projeto, banca=banca, numero=numero)
    ata.pdf.save(f"ata-{numero.replace('/', '-')}.pdf", ContentFile(pdf_bytes), save=False)
    ata.save()

    RevisaoSUGRAD.objects.create(ata=ata)

    transaction.on_commit(lambda: enviar_ata_para_sugrad.delay(ata.id))

    return ata


def aprovar_ata(ata, por):
    """A SUGRAD aprova a ata — fecha `Aprovado` → `Concluído` (Bloco E,
    spec §5.2). Permissão por papel (§3.5), não por posse do projeto."""
    if not permissions.pode_revisar_ata(por):
        raise PermissionDenied("Somente a SUGRAD revisa atas.")
    revisao = ata.revisao
    if revisao.status != RevisaoSUGRAD.PENDENTE:
        raise ValidationError("Esta ata já foi revisada.")

    revisao.status = RevisaoSUGRAD.APROVADA
    revisao.decidida_em = timezone.now()
    revisao.save(update_fields=["status", "decidida_em"])

    ata.projeto.status = Projeto.CONCLUIDO
    ata.projeto.save(update_fields=["status"])

    if ata.projeto.etapa == Projeto.TCC_I:
        from apps.projetos.services import criar_tcc_ii_automatico

        criar_tcc_ii_automatico(ata.projeto)


def devolver_ata(ata, por, comentario):
    """A SUGRAD devolve a ata com um comentário — não muda
    `Projeto.status` (§3.4): a devolução é sobre o documento, não sobre o
    mérito acadêmico já decidido pela banca."""
    if not permissions.pode_revisar_ata(por):
        raise PermissionDenied("Somente a SUGRAD revisa atas.")
    revisao = ata.revisao
    if revisao.status != RevisaoSUGRAD.PENDENTE:
        raise ValidationError("Esta ata já foi revisada.")

    revisao.status = RevisaoSUGRAD.DEVOLVIDA
    revisao.comentario = comentario
    revisao.decidida_em = timezone.now()
    revisao.save(update_fields=["status", "comentario", "decidida_em"])

    transaction.on_commit(lambda: enviar_devolucao_para_orientador.delay(ata.id))


def reenviar_a_sugrad(ata, por):
    """O orientador reenvia uma ata `DEVOLVIDA` — volta a `PENDENTE`
    (Bloco E, spec §5.2). Não gera um PDF novo nem uma `Ata` nova (§2 do
    spec: reabre a mesma revisão)."""
    if not permissions.pode_reenviar_ata(por, ata):
        raise PermissionDenied("Somente o orientador do projeto reenvia a ata.")
    revisao = ata.revisao
    if revisao.status != RevisaoSUGRAD.DEVOLVIDA:
        raise ValidationError("Só é possível reenviar uma ata devolvida.")

    revisao.status = RevisaoSUGRAD.PENDENTE
    revisao.save(update_fields=["status"])

    transaction.on_commit(lambda: enviar_ata_para_sugrad.delay(ata.id))
