from django.urls import path

from apps.publico import views

app_name = "publico"

urlpatterns = [
    path("catalogo/", views.catalogo, name="catalogo"),
    path("calendario/", views.calendario, name="calendario"),
]
