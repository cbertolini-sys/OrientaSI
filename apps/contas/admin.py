from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.core.exceptions import ValidationError

from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario


class FormularioCriacaoUsuario(UserCreationForm):
    """Sem campo `username`: o e-mail já é o identificador (USERNAME_FIELD)."""

    class Meta(UserCreationForm.Meta):
        model = Usuario
        fields = ("email", "nome_completo", "cpf")


class FormularioEdicaoUsuario(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = Usuario

    def clean(self):
        """Recusa mudar `papel` para algo diferente de PROFESSOR enquanto a
        conta ainda é coordenadora (achado F2 da re-auditoria, 2026-09-22 —
        bug introduzido pelo próprio achado H3 desta correção). Antes de
        H3, `is_coordenador` era um campo comum do formulário, então
        `Model.full_clean()` (chamado por `ModelForm._post_clean`) incluía
        a checagem do `CheckConstraint coordenador_e_professor` — trocar o
        papel de um coordenador para ALUNO/SUGRAD dava um erro de
        formulário legível. Depois de H3, `is_coordenador` virou
        `readonly_fields`, e o Django EXCLUI todo campo somente-leitura da
        validação de `full_clean()` (`_get_validation_exclusions`) — a
        checagem do `CheckConstraint` passou a ser pulada silenciosamente,
        e a mesma ação virou um `IntegrityError` cru na gravação, 500. Esta
        checagem em `clean()` roda ANTES de `_post_clean()`/`full_clean()`
        excluir o campo, usando `self.instance.is_coordenador` (o valor
        ATUAL do banco — `construct_instance` só roda depois deste método,
        então o campo somente-leitura ainda não foi tocado)."""
        limpos = super().clean()
        novo_papel = limpos.get("papel")
        if (
            self.instance.pk
            and self.instance.is_coordenador
            and novo_papel is not None
            and novo_papel != Usuario.PROFESSOR
        ):
            raise ValidationError(
                "Não é possível mudar o papel: esta conta ainda é coordenador(a). "
                "Revogue a coordenação pelo painel da coordenação antes de mudar o papel."
            )

        # Achado F1 da re-auditoria (2026-09-22): `services.revogar_coordenacao`
        # (achado H2) trava o piso de coordenadores contra a REVOGAÇÃO, mas
        # nada travava a DESATIVAÇÃO — `is_active` é um campo comum deste
        # formulário (não é `readonly_fields`), e desativar o último
        # coordenador ATIVO restante pelo admin deixava o painel da
        # coordenação inalcançável para qualquer pessoa, sem precisar de
        # corrida nenhuma: bastava desmarcar "ativo" nesta tela e salvar.
        # `ValidationError` aqui — dentro de `clean()`, não de
        # `save_model()` — porque o admin NÃO captura `ValidationError`
        # levantado em `save_model` (verificado na fonte do Django: viraria
        # 500, não um erro de formulário). Mesma contagem de
        # `revogar_coordenacao` (`is_coordenador=True, is_active=True`),
        # sem lock: o admin não tem o problema de concorrência real que o
        # serviço tem (um superusuário por vez nesta tela), só faltava a
        # checagem.
        novo_is_active = limpos.get("is_active")
        if (
            self.instance.pk
            and self.instance.is_coordenador
            and novo_is_active is False
            and Usuario.objects.filter(is_coordenador=True, is_active=True)
            .exclude(pk=self.instance.pk)
            .count()
            == 0
        ):
            raise ValidationError(
                f"{self.instance.nome_completo} é o último coordenador ativo do "
                "sistema — nomeie outro coordenador antes de desativar esta conta."
            )
        return limpos


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    """Estende o UserAdmin padrão: sem isto, o formulário exporia `password`
    como CharField comum, gravando a senha em texto puro em vez do hash.

    `is_coordenador` em `readonly_fields` (achado H3 da auditoria,
    2026-09-22): sem isto, um staff com acesso a este modelo podia marcar
    ou desmarcar `is_coordenador` direto no formulário, furando tanto o
    teto de `LIMITE_COORDENADORES` quanto a trava do último coordenador —
    as duas vivem só em `services.promover_a_coordenador`/
    `revogar_coordenacao`, nunca chamadas por este admin. Promover/revogar
    continuam existindo — pelo painel da coordenação, a porta certa.
    Alcançável hoje só por superusuário (`promover_a_coordenador` não
    concede nenhuma permissão de modelo a um coordenador comum), então é
    defesa em profundidade."""

    add_form = FormularioCriacaoUsuario
    form = FormularioEdicaoUsuario
    model = Usuario

    ordering = ["nome_completo"]
    list_display = ["nome_completo", "email", "papel", "is_coordenador", "is_active"]
    list_filter = ["papel", "is_coordenador", "is_active"]
    search_fields = ["nome_completo", "email", "cpf"]
    readonly_fields = ["criado_em", "is_coordenador"]
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
    list_display = ["nome", "area", "ordem"]
    list_filter = ["area"]
    search_fields = ["nome"]


admin.site.register(PerfilAluno)
admin.site.register(PerfilProfessor)
