from rest_framework import viewsets
from rest_framework.permissions import AllowAny

from apps.publico import services
from apps.publico.serializers import CalendarioSerializer, CatalogoSerializer


class CatalogoViewSet(viewsets.ReadOnlyModelViewSet):
    """`/api/v1/catalogo/` (Bloco H, spec §4) — list e retrieve, GET
    apenas. `get_queryset` reaproveita `services.catalogo_publico`
    (Bloco G): a elegibilidade nunca é reimplementada aqui."""

    serializer_class = CatalogoSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        area_id = self.request.query_params.get("area")
        area_id = int(area_id) if area_id and area_id.isdigit() else None
        ano = self.request.query_params.get("ano")
        ano = int(ano) if ano and ano.isdigit() else None
        return services.catalogo_publico(area_id=area_id, ano=ano)


class CalendarioViewSet(viewsets.ReadOnlyModelViewSet):
    """`/api/v1/calendario/` (Bloco H, spec §4) — list e retrieve, GET
    apenas."""

    serializer_class = CalendarioSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return services.calendario_publico()
