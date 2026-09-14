from django.contrib import admin

from apps.documentos.models import Ata, RevisaoSUGRAD


class RevisaoSUGRADInline(admin.StackedInline):
    model = RevisaoSUGRAD
    extra = 0


@admin.register(Ata)
class AtaAdmin(admin.ModelAdmin):
    list_display = ["numero", "projeto", "banca", "gerada_em"]
    search_fields = ["numero", "projeto__aluno__nome_completo"]
    readonly_fields = ["gerada_em"]
    inlines = [RevisaoSUGRADInline]
