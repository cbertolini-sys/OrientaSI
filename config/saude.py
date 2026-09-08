from django.db import connection
from django.http import JsonResponse


def saude(request):
    """Healthcheck consumido pelo docker compose e pelo monitoramento."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"estado": "ok"})
