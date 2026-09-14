from django.core.files.base import ContentFile
from django.template.loader import render_to_string
from django.utils import timezone

from apps.bancas.models import Banca
from apps.documentos.models import Ata, RevisaoSUGRAD


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

    return ata
