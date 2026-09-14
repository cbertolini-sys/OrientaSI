from django.urls import path

from apps.bancas import views

app_name = "bancas"

urlpatterns = [
    path("bancas/agendar/<int:projeto_id>/", views.agendar, name="agendar"),
    path("bancas/<int:banca_id>/editar/", views.editar, name="editar"),
    path("bancas/<int:banca_id>/cancelar/", views.cancelar, name="cancelar"),
    path("bancas/<int:banca_id>/resultado/", views.resultado, name="resultado"),
]
