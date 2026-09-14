from apps.bancas.models import Banca
from apps.projetos.models import Projeto


def _projetos_catalogaveis():
    """Projetos elegíveis pro catálogo, sem os filtros de área/ano (Bloco
    G, spec §1): TCC_II, Concluído, termo de publicação assinado, com tema
    (fonte de Título/Resumo — um TCC_II herdado de um TCC_I de candidatura
    aberta pode não ter tema, e por isso fica de fora)."""
    return Projeto.objects.filter(
        etapa=Projeto.TCC_II,
        status=Projeto.CONCLUIDO,
        termo_publicacao__isnull=False,
        tema__isnull=False,
    )


def catalogo_publico(area_id=None, ano=None):
    """Lista pública de TCCs concluídos (Bloco G, spec §5). Mais recente
    primeiro — a data em que a SUGRAD aprovou a ata, não a de criação do
    projeto (`atas__revisao__decidida_em`: `Ata.projeto` tem
    `related_name="atas"`, `RevisaoSUGRAD.ata` tem `related_name="revisao"`
    — ambos de apps/documentos/models.py). `area_id` filtra pela área do
    ORIENTADOR (`PerfilProfessor.areas`, M2M), não por `tema.area`
    diretamente — mesma fonte usada em outros pontos do sistema, e não
    depende de `tema` estar presente (embora aqui sempre esteja, pelo
    filtro de `_projetos_catalogaveis`)."""
    qs = (
        _projetos_catalogaveis()
        .select_related("tema", "aluno", "orientador", "submissao")
        .order_by("-atas__revisao__decidida_em")
    )
    if area_id:
        qs = qs.filter(orientador__perfil_professor__areas=area_id)
    if ano:
        qs = qs.filter(ano=ano)
    return qs


def anos_do_catalogo():
    """Anos distintos entre os projetos elegíveis, mais recente primeiro —
    popula o `<select>` de filtro por ano em `/catalogo/`."""
    return _projetos_catalogaveis().order_by("-ano").values_list("ano", flat=True).distinct()


def calendario_publico():
    """Bancas ainda não realizadas, mais próxima primeiro (Bloco G, spec
    §5). Uma banca cuja `data_hora` já passou some da agenda mesmo que o
    orientador ainda não tenha registrado o resultado — calendário é
    agenda, não histórico."""
    from django.utils import timezone

    return (
        Banca.objects.filter(status=Banca.AGENDADA, data_hora__gte=timezone.now())
        .select_related("projeto__tema", "projeto__aluno", "projeto__orientador")
        .order_by("data_hora")
    )
