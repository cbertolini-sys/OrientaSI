from django.contrib import admin

from apps.projetos.models import LimiteOrientacao, Projeto, Tema


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
