from rest_framework.permissions import AllowAny
from rest_framework.routers import APIRootView, DefaultRouter

from apps.publico.api_views import CalendarioViewSet, CatalogoViewSet


class RaizPublicaAPIView(APIRootView):
    """A raiz do router (`/api/v1/`) com `AllowAny` explícito (achado da
    re-auditoria, 2026-09-22): o `APIRootView` que o `DefaultRouter` gera
    automaticamente não declara `permission_classes` próprio, então herdava
    o default GLOBAL de `REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]` —
    diferente de `CatalogoViewSet`/`CalendarioViewSet`, que sempre
    declararam `AllowAny` explicitamente (achado M13 confirma isso).
    Quando esse default global foi corrigido de `AllowAny` para
    `IsAuthenticated` (achado M13, defesa em profundidade contra um
    endpoint autenticado futuro nascer aberto por esquecimento), o índice
    da API — o ponto de entrada documentado de uma API deliberadamente
    pública e sem login, CLAUDE.md Bloco H — passou a responder 403 sem
    login, e nenhum teste do repositório notou (nada testava `/api/v1/`
    além dos dois endpoints que ele lista)."""

    permission_classes = [AllowAny]


class RouterPublico(DefaultRouter):
    APIRootView = RaizPublicaAPIView


router = RouterPublico()
router.register("catalogo", CatalogoViewSet, basename="catalogo")
router.register("calendario", CalendarioViewSet, basename="calendario")

urlpatterns = router.urls
