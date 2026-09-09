from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import TemplateView

from apps.contas.forms import FormularioDefinirNovaSenha, FormularioLogin, FormularioRecuperarSenha
from config.saude import saude

urlpatterns = [
    path("", TemplateView.as_view(template_name="inicio.html"), name="inicio"),
    path("admin/", admin.site.urls),
    path("saude/", saude, name="saude"),
    # Rotas de autenticação (T9). Registradas explicitamente (em vez de
    # `include("django.contrib.auth.urls")`) para injetar `form_class`: é
    # assim que login e recuperação de senha recebem as classes do DaisyUI
    # (`aplica_estilo`) e a ligação de aria-describedby/aria-invalid, iguais
    # às do formulário de aceite de convite (T7). Os `template_name`
    # continuam nos padrões do Django (`registration/*.html`), que já
    # apontam para os arquivos criados em templates/registration/.
    path(
        "contas/login/",
        auth_views.LoginView.as_view(form_class=FormularioLogin),
        name="login",
    ),
    path("contas/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "contas/password_reset/",
        auth_views.PasswordResetView.as_view(form_class=FormularioRecuperarSenha),
        name="password_reset",
    ),
    path(
        "contas/password_reset/concluido/",
        auth_views.PasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "contas/reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(form_class=FormularioDefinirNovaSenha),
        name="password_reset_confirm",
    ),
    path(
        "contas/reset/concluido/",
        auth_views.PasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    path("", include("apps.contas.urls")),
]
