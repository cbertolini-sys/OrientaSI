from django.contrib import admin

from apps.projetos.models import (
    Candidatura,
    LimiteOrientacao,
    OpcaoCandidatura,
    Projeto,
    Tema,
    TermoPublicacao,
)


@admin.register(Tema)
class TemaAdmin(admin.ModelAdmin):
    # `areas` é M2M — não cabe direto em `list_display` (o Django recusa um
    # ManyToManyField ali, `SystemCheckError`), daí o método
    # `areas_display` abaixo. `list_filter` aceita M2M normalmente.
    list_display = ["titulo", "professor", "areas_display", "ativo", "criado_em"]
    list_filter = ["ativo", "areas"]
    search_fields = ["titulo", "descricao", "professor__usuario__nome_completo"]
    readonly_fields = ["criado_em"]

    @admin.display(description="áreas")
    def areas_display(self, tema):
        return ", ".join(area.nome for area in tema.areas.all())

    def get_readonly_fields(self, request, obj=None):
        # Trocar o professor de um Tema já existente deixaria, em silêncio,
        # as OpcaoCandidatura antigas apontando para um tema cujo professor
        # já não bate mais com o `professor` gravado na opção — exatamente o
        # que a trigger `valida_tema_do_professor_da_opcao`
        # (migrations/0002_candidatura_opcaocandidatura.py) existe para
        # impedir, mas ela só dispara em INSERT/UPDATE de OpcaoCandidatura,
        # não de Tema. Isto fecha o caminho mais acessível para esse buraco
        # (o admin); LIMITE: um UPDATE direto por SQL ou shell em
        # `projetos_tema.professor_id` continua possível e não é observado
        # por nada — ver o comentário ao lado da trigger para o que fecharia
        # esse resíduo. `obj is None` é a tela de criação, onde o professor
        # ainda não tem opções dependentes para contradizer.
        if obj is not None:
            return [*self.readonly_fields, "professor"]
        return self.readonly_fields


@admin.register(Projeto)
class ProjetoAdmin(admin.ModelAdmin):
    """Achado L9 da auditoria (2026-09-22): antes, um staff com acesso a
    este modelo podia criar um `Projeto` direto (furando `LIMITE_PADRAO_VAGAS`
    — só `criar_projeto_sob_limite` conta vagas) ou editar `status`/`etapa`
    livremente (pulando toda a máquina de estados — banca, ata, checklist do
    TCC II). `has_add_permission=False` e `status`/`etapa` em
    `readonly_fields` fecham as duas portas: toda criação e toda transição
    de status passam a exigir a camada de serviço, o mesmo espírito de
    `TemaAdmin.get_readonly_fields` (que já tranca `Tema.professor` pós-
    criação). Alcançável hoje só por superusuário — `promover_a_coordenador`
    não concede permissão de modelo nenhuma —, então é defesa em
    profundidade, não uma trava contra um coordenador comum."""

    list_display = ["aluno", "orientador", "etapa", "status", "ano", "periodo", "criado_em"]
    list_filter = ["etapa", "status", "ano", "periodo"]
    search_fields = ["aluno__nome_completo", "orientador__nome_completo"]
    readonly_fields = ["criado_em", "etapa", "status"]

    def has_add_permission(self, request):
        return False


@admin.register(LimiteOrientacao)
class LimiteOrientacaoAdmin(admin.ModelAdmin):
    list_display = ["professor", "etapa", "ano", "periodo", "limite", "autorizado_por", "criado_em"]
    list_filter = ["etapa", "ano", "periodo"]
    search_fields = ["professor__usuario__nome_completo", "justificativa"]
    readonly_fields = ["criado_em"]


@admin.register(Candidatura)
class CandidaturaAdmin(admin.ModelAdmin):
    list_display = ["aluno", "status", "opcao_atual", "ano", "periodo", "criado_em"]
    list_filter = ["status", "ano", "periodo"]
    search_fields = ["aluno__usuario__nome_completo", "aluno__matricula"]
    readonly_fields = ["criado_em"]


@admin.register(OpcaoCandidatura)
class OpcaoCandidaturaAdmin(admin.ModelAdmin):
    list_display = ["candidatura", "ordem", "professor", "tema", "situacao", "prazo"]
    list_filter = ["situacao"]
    search_fields = [
        "professor__usuario__nome_completo",
        "candidatura__aluno__usuario__nome_completo",
    ]


@admin.register(TermoPublicacao)
class TermoPublicacaoAdmin(admin.ModelAdmin):
    """`has_add_permission=False` (achado L9 da auditoria, 2026-09-22): sem
    isto, um staff podia "assinar" o termo de publicação em nome do aluno
    pelo admin — inclusive de um TCC I, onde o termo nem deveria existir
    (achado H6). A assinatura é um ato do próprio aluno
    (`services.assinar_termo_publicacao`); o admin continua podendo
    CONSULTAR/apagar uma linha existente, só não criar uma nova."""

    list_display = ["projeto", "assinado_em"]
    readonly_fields = ["assinado_em"]

    def has_add_permission(self, request):
        return False
