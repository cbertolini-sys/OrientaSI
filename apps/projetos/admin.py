from django.contrib import admin

from apps.projetos.models import (
    Candidatura,
    LimiteOrientacao,
    OpcaoCandidatura,
    Projeto,
    Tema,
)


@admin.register(Tema)
class TemaAdmin(admin.ModelAdmin):
    list_display = ["titulo", "professor", "area", "ativo", "criado_em"]
    list_filter = ["ativo", "area"]
    search_fields = ["titulo", "descricao", "professor__usuario__nome_completo"]
    readonly_fields = ["criado_em"]


@admin.register(Projeto)
class ProjetoAdmin(admin.ModelAdmin):
    list_display = ["aluno", "orientador", "etapa", "status", "ano", "periodo", "criado_em"]
    list_filter = ["etapa", "status", "ano", "periodo"]
    search_fields = ["aluno__nome_completo", "orientador__nome_completo"]
    readonly_fields = ["criado_em"]


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
