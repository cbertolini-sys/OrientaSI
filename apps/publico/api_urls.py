from rest_framework.routers import DefaultRouter

from apps.publico.api_views import CalendarioViewSet, CatalogoViewSet

router = DefaultRouter()
router.register("catalogo", CatalogoViewSet, basename="catalogo")
router.register("calendario", CalendarioViewSet, basename="calendario")

urlpatterns = router.urls
