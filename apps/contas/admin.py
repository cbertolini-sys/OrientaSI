from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario


class FormularioCriacaoUsuario(UserCreationForm):
    """Sem campo `username`: o e-mail já é o identificador (USERNAME_FIELD)."""

    class Meta(UserCreationForm.Meta):
        model = Usuario
        fields = ("email", "nome_completo", "cpf")


class FormularioEdicaoUsuario(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    """Estende o UserAdmin padrão: sem isto, o formulário exporia `password`
    como CharField comum, gravando a senha em texto puro em vez do hash."""

    add_form = FormularioCriacaoUsuario
    form = FormularioEdicaoUsuario
    model = Usuario

    ordering = ["nome_completo"]
    list_display = ["nome_completo", "email", "papel", "is_coordenador", "is_active"]
    list_filter = ["papel", "is_coordenador", "is_active"]
    search_fields = ["nome_completo", "email", "cpf"]
    readonly_fields = ["criado_em"]
    filter_horizontal = ["groups", "user_permissions"]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Dados pessoais", {"fields": ("nome_completo", "cpf", "telefone", "foto")}),
        (
            "Permissões",
            {
                "fields": (
                    "papel",
                    "is_coordenador",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Datas importantes", {"fields": ("last_login", "criado_em")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "nome_completo", "cpf", "papel", "password1", "password2"),
            },
        ),
    )


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ["nome"]
    search_fields = ["nome"]


admin.site.register(PerfilAluno)
admin.site.register(PerfilProfessor)
