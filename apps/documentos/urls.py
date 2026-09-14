from django.urls import path

from apps.documentos import views

app_name = "documentos"

urlpatterns = [
    path("painel/sugrad/", views.painel, name="painel"),
    path("painel/sugrad/<int:ata_id>/aprovar/", views.aprovar_ata_view, name="aprovar_ata"),
    path("painel/sugrad/<int:ata_id>/devolver/", views.devolver_ata_view, name="devolver_ata"),
]
