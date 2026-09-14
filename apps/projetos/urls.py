from django.urls import path

from apps.projetos import views

app_name = "projetos"

urlpatterns = [
    path("temas/", views.mural, name="mural"),
    path("temas/meus/", views.meus_temas, name="meus_temas"),
    path("temas/<int:tema_id>/editar/", views.editar_tema, name="editar_tema"),
    path("temas/<int:tema_id>/desativar/", views.desativar_tema, name="desativar_tema"),
    path("orientacoes/", views.orientacoes, name="orientacoes"),
    path("orientacoes/<int:opcao_id>/aceitar/", views.aceitar_opcao_view, name="aceitar_opcao"),
    path("orientacoes/<int:opcao_id>/recusar/", views.recusar_opcao_view, name="recusar_opcao"),
    path("candidatura/", views.candidatura, name="candidatura"),
    path(
        "candidatura/<int:candidatura_id>/cancelar/",
        views.cancelar_candidatura_view,
        name="cancelar_candidatura",
    ),
    path("meu-tcc/", views.meu_tcc, name="meu_tcc"),
    path("painel/orientacoes/", views.painel_orientacoes, name="painel_orientacoes"),
    path(
        "painel/orientacoes/<int:projeto_id>/trocar-orientador/",
        views.trocar_orientador_view,
        name="trocar_orientador",
    ),
    path(
        "painel/orientacoes/limites/<int:limite_id>/revogar/",
        views.revogar_limite_view,
        name="revogar_limite",
    ),
    path(
        "orientacoes/<int:projeto_id>/reabrir/",
        views.reabrir_projeto_view,
        name="reabrir_projeto",
    ),
    path(
        "orientacoes/<int:projeto_id>/cancelar/",
        views.cancelar_projeto_view,
        name="cancelar_projeto",
    ),
]
