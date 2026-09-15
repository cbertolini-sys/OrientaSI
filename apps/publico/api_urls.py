from rest_framework.routers import DefaultRouter

from apps.publico.api_views import CatalogoViewSet

router = DefaultRouter()
router.register("catalogo", CatalogoViewSet, basename="catalogo")

urlpatterns = router.urls
