from django.urls import path

from apps.contas import views

app_name = "contas"

urlpatterns = [
    path("convite/<str:token>/", views.aceitar_convite, name="aceitar_convite"),
    path("perfil/", views.perfil, name="perfil"),
    path("painel/", views.painel, name="painel"),
    path("painel/promover/", views.promover, name="promover"),
    path("painel/revogar/", views.revogar, name="revogar"),
]
