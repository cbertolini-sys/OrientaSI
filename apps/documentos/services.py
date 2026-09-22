from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.template.loader import render_to_string
from django.utils import timezone

from apps.bancas.models import Banca
from apps.documentos import permissions
from apps.documentos.models import Ata, RevisaoSUGRAD
from apps.documentos.tasks import enviar_ata_para_sugrad, enviar_devolucao_para_orientador
from apps.projetos.models import Projeto


@transaction.atomic
def gerar_ata(projeto):
    """Cria a `Ata` da defesa de `projeto`, numerada e com o PDF já
    renderizado — chamada por `apps.projetos.services.aprovar_projeto`
    (Bloco E, spec §3.2: aprovar e gerar a ata são o mesmo passo). Não checa
    permissão: quem decide SE o projeto pode ser aprovado é
    `aprovar_projeto`; esta função só produz o documento a partir de um
    projeto já aprovado.

    `@transaction.atomic` (achado H8 da auditoria, 2026-09-22): a criação da
    `Ata` + da `RevisaoSUGRAD` associada agora commitam juntas — antes, uma
    falha entre as duas (rara, mas possível) deixava uma `Ata` sem
    `revisao`, e qualquer leitura futura de `ata.revisao` levantava
    `RelatedObjectDoesNotExist`."""
    banca = (
        Banca.objects.filter(projeto=projeto).exclude(status=Banca.CANCELADA).latest("criada_em")
    )

    ano_atual = timezone.localdate().year
    # Custo aceito (spec §4.1): condição de corrida sob criação concorrente
    # de atas no mesmo ano — aprovar um TCC I é uma ação humana de baixa
    # frequência, não um caminho de alto throughput. O que MUDOU (achado M1
    # da auditoria) é que `Ata.numero` agora tem `unique=True`: a colisão
    # deixou de ser gravada em silêncio (dois documentos oficiais com o
    # mesmo número) e passa a levantar um erro alto e traduzido abaixo.
    proximo = Ata.objects.filter(gerada_em__year=ano_atual).count() + 1
    numero = f"{proximo:03d}/{ano_atual}"

    corpo_html = render_to_string(
        "documentos/ata_pdf.html", {"projeto": projeto, "banca": banca, "numero": numero}
    )
    from weasyprint import HTML

    pdf_bytes = HTML(string=corpo_html).write_pdf()

    ata = Ata(projeto=projeto, banca=banca, numero=numero)
    ata.pdf.save(f"ata-{numero.replace('/', '-')}.pdf", ContentFile(pdf_bytes), save=False)
    try:
        ata.save()
    except IntegrityError as erro:
        # Inspeciona QUAL constraint disparou (achado M-2 da re-auditoria,
        # 2026-09-22 — consistência com o mesmo padrão já aplicado em
        # `agendar_banca` e `criar_tcc_ii_automatico` nesta correção): sem
        # isto, qualquer outro `IntegrityError` deste `save()` (o FK de
        # `projeto`/`banca`, por exemplo, se um dos dois tiver sido
        # apagado entre a leitura e aqui) seria mal atribuído a "já existe
        # uma ata com este número" — uma mensagem que convida a um reenvio
        # que falharia identicamente pra sempre.
        nome_da_constraint = getattr(getattr(erro, "__cause__", None), "diag", None)
        nome_da_constraint = getattr(nome_da_constraint, "constraint_name", None)
        if nome_da_constraint != "documentos_ata_numero_97046ab9_uniq":
            raise
        raise ValidationError(
            "Já existe uma ata com este número — tente aprovar de novo em um instante."
        ) from None

    RevisaoSUGRAD.objects.create(ata=ata)

    transaction.on_commit(lambda: enviar_ata_para_sugrad.delay(ata.id))

    return ata


@transaction.atomic
def aprovar_ata(ata, por):
    """A SUGRAD aprova a ata — fecha `Aprovado` → `Concluído` (Bloco E,
    spec §5.2). Permissão por papel (§3.5), não por posse do projeto.

    `@transaction.atomic` (achado C3/H8 da auditoria, 2026-09-22): antes, a
    `RevisaoSUGRAD` virava `APROVADA` e o `Projeto` virava `CONCLUIDO` em
    dois `save()` já commitados quando `criar_tcc_ii_automatico` rodava — se
    essa chamada levantasse (por exemplo `IntegrityError`, quando um
    professor já tinha criado manualmente um TCC II para o mesmo aluno via
    `criar_tcc_ii_manual`), a ata ficava aprovada e o TCC I concluído SEM
    nenhum TCC II, e a SUGRAD via um 500 sem chance de repetir a ação
    (`aprovar_ata` já recusa uma revisão que não está mais `PENDENTE`).
    Agora as três gravações — revisão, projeto, TCC II novo — commitam
    juntas ou nenhuma commita.

    `select_for_update` na revisão (achado da revisão do código desta mesma
    correção, 2026-09-22): o `@transaction.atomic` sozinho evita o estado
    PARCIAL (o problema do C3 original), mas não evitava a CORRIDA em si —
    duas abas da SUGRAD clicando "Aprovar" quase ao mesmo tempo liam as
    duas `revisao.status == PENDENTE` antes de qualquer uma commitar, e a
    segunda só era barrada depois, dentro de `criar_tcc_ii_automatico`, com
    um `IntegrityError` cru que `aprovar_ata_view` não captura — 500. A
    trava abaixo faz a segunda transação esperar a primeira, reler
    `PENDENTE` já como `APROVADA` sob a trava, e recusar por
    `ValidationError` antes de chegar perto de `criar_tcc_ii_automatico` —
    o mesmo padrão de `Candidatura.objects.select_for_update()` em
    `apps.projetos.services.aceitar_opcao`. `criar_tcc_ii_automatico`
    ganhou, ainda assim, sua própria tradução de `IntegrityError` (abaixo,
    achado H5 revisitado) como segunda camada — não depende só desta
    trava para não vazar 500."""
    if not permissions.pode_revisar_ata(por):
        raise PermissionDenied("Somente a SUGRAD revisa atas.")
    revisao = RevisaoSUGRAD.objects.select_for_update().get(ata=ata)
    if revisao.status != RevisaoSUGRAD.PENDENTE:
        raise ValidationError("Esta ata já foi revisada.")

    revisao.status = RevisaoSUGRAD.APROVADA
    revisao.decidida_em = timezone.now()
    revisao.save(update_fields=["status", "decidida_em"])
    # Mantém `ata.revisao` (o cache da relação reversa) apontando para ESTA
    # instância recém-gravada (achado da revisão de código desta mesma
    # correção): `select_for_update().get(...)` busca uma instância NOVA,
    # separada da que `ata.revisao` já tivesse em cache — sem esta linha,
    # quem reusa o mesmo objeto `ata` depois desta chamada (o padrão mais
    # comum é `aprovar_ata(ata, ...)` seguido de outra leitura de
    # `ata.revisao` no mesmo processo) veria o status ANTIGO.
    ata.revisao = revisao

    ata.projeto.status = Projeto.CONCLUIDO
    ata.projeto.save(update_fields=["status"])

    if ata.projeto.etapa == Projeto.TCC_I:
        from apps.projetos.services import criar_tcc_ii_automatico

        criar_tcc_ii_automatico(ata.projeto)


@transaction.atomic
def devolver_ata(ata, por, comentario):
    """A SUGRAD devolve a ata com um comentário — não muda
    `Projeto.status` (§3.4): a devolução é sobre o documento, não sobre o
    mérito acadêmico já decidido pela banca.

    `@transaction.atomic` (achado H8): só uma gravação hoje, mas a mesma
    disciplina do resto do arquivo — e faz o `transaction.on_commit`
    abaixo se comportar como o nome promete (em autocommit puro, sem
    transação aberta, ele executava na hora, não "ao commitar").

    `select_for_update` (mesma correção de `aprovar_ata`, acima): sem isto,
    "Aprovar" e "Devolver" clicados quase ao mesmo tempo na mesma ata
    também corriam — a trava serializa os dois contra a MESMA linha de
    `RevisaoSUGRAD`, então qualquer que chegue primeiro decide, e o segundo
    lê o status já resolvido em vez de um `PENDENTE` desatualizado."""
    if not permissions.pode_revisar_ata(por):
        raise PermissionDenied("Somente a SUGRAD revisa atas.")
    revisao = RevisaoSUGRAD.objects.select_for_update().get(ata=ata)
    if revisao.status != RevisaoSUGRAD.PENDENTE:
        raise ValidationError("Esta ata já foi revisada.")

    revisao.status = RevisaoSUGRAD.DEVOLVIDA
    revisao.comentario = comentario
    revisao.decidida_em = timezone.now()
    revisao.save(update_fields=["status", "comentario", "decidida_em"])
    # Mesma razão de `aprovar_ata`, acima: mantém o cache `ata.revisao`
    # apontando para a instância recém-gravada.
    ata.revisao = revisao

    transaction.on_commit(lambda: enviar_devolucao_para_orientador.delay(ata.id))


@transaction.atomic
def reenviar_a_sugrad(ata, por):
    """O orientador reenvia uma ata `DEVOLVIDA` — volta a `PENDENTE`
    (Bloco E, spec §5.2). Não gera um PDF novo nem uma `Ata` nova (§2 do
    spec: reabre a mesma revisão).

    Limpa `comentario`/`decidida_em` da devolução anterior (achado M5 da
    auditoria, 2026-09-22): como `RevisaoSUGRAD` é uma linha só, sem
    histórico de rodadas, deixar o comentário antigo e o timestamp da
    devolução anterior pendurados numa revisão `PENDENTE` é um dado
    enganoso — qualquer leitura futura de `revisao.comentario` veria a
    rejeição antiga como se fosse atual.

    `select_for_update` (mesma correção de `aprovar_ata`/`devolver_ata`,
    acima): mesma disciplina contra dois reenvios quase simultâneos."""
    if not permissions.pode_reenviar_ata(por, ata):
        raise PermissionDenied("Somente o orientador do projeto reenvia a ata.")
    revisao = RevisaoSUGRAD.objects.select_for_update().get(ata=ata)
    if revisao.status != RevisaoSUGRAD.DEVOLVIDA:
        raise ValidationError("Só é possível reenviar uma ata devolvida.")

    revisao.status = RevisaoSUGRAD.PENDENTE
    revisao.comentario = ""
    revisao.decidida_em = None
    revisao.save(update_fields=["status", "comentario", "decidida_em"])
    ata.revisao = revisao

    transaction.on_commit(lambda: enviar_ata_para_sugrad.delay(ata.id))
