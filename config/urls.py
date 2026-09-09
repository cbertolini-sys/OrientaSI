from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from config.saude import saude

urlpatterns = [
    path("", TemplateView.as_view(template_name="inicio.html"), name="inicio"),
    path("admin/", admin.site.urls),
    path("saude/", saude, name="saude"),
    path("", include("apps.contas.urls")),
]
