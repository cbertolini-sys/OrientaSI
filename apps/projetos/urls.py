from django.urls import path

from apps.projetos import views

app_name = "projetos"

urlpatterns = [
    path("temas/", views.mural, name="mural"),
    path("temas/meus/", views.meus_temas, name="meus_temas"),
    path("temas/<int:tema_id>/editar/", views.editar_tema, name="editar_tema"),
    path("temas/<int:tema_id>/desativar/", views.desativar_tema, name="desativar_tema"),
]
