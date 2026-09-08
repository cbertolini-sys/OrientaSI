from django.contrib import admin
from django.urls import path

from config.saude import saude

urlpatterns = [
    path("admin/", admin.site.urls),
    path("saude/", saude, name="saude"),
]
