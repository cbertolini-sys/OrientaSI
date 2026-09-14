from django.contrib import admin

from apps.bancas.models import Banca, MembroBanca


class MembroBancaInline(admin.TabularInline):
    model = MembroBanca
    extra = 0


@admin.register(Banca)
class BancaAdmin(admin.ModelAdmin):
    list_display = ["projeto", "data_hora", "local", "status", "resultado", "criada_em"]
    list_filter = ["status", "resultado"]
    search_fields = ["projeto__aluno__nome_completo", "local"]
    readonly_fields = ["criada_em"]
    inlines = [MembroBancaInline]
