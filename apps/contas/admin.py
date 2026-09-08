from django.contrib import admin

from apps.contas.models import Usuario


@admin.register(Usuario)
class UsuarioAdmin(admin.ModelAdmin):
    list_display = ["nome_completo", "email", "papel", "is_coordenador", "is_active"]
    list_filter = ["papel", "is_coordenador", "is_active"]
    search_fields = ["nome_completo", "email", "cpf"]
