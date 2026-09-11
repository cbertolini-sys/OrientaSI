from django.urls import path

from apps.projetos import views

app_name = "projetos"

urlpatterns = [
    path("temas/meus/", views.meus_temas, name="meus_temas"),
    path("temas/<int:tema_id>/desativar/", views.desativar_tema, name="desativar_tema"),
]
