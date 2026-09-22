"""Testes do Bloco H: schema OpenAPI e Swagger UI (`drf-spectacular`)."""

import pytest


@pytest.mark.django_db
def test_api_schema_responde_200(client):
    resposta = client.get("/api/schema/")
    assert resposta.status_code == 200


@pytest.mark.django_db
def test_api_docs_responde_200(client):
    resposta = client.get("/api/docs/")
    assert resposta.status_code == 200


@pytest.mark.django_db
def test_api_v1_raiz_responde_200_sem_login(client):
    """Achado da re-auditoria (2026-09-22): o `APIRootView` que o
    `DefaultRouter` gera não declara `permission_classes` próprio (ao
    contrário de `CatalogoViewSet`/`CalendarioViewSet`, que sempre tiveram
    `AllowAny` explícito) — quando o default global do DRF foi corrigido
    de `AllowAny` para `IsAuthenticated` (achado M13), a raiz de uma API
    deliberadamente pública passou a responder 403 sem login, sem que
    nenhum teste percebesse. Prova por mutação: remover
    `RaizPublicaAPIView`/`RouterPublico` de `apps/publico/api_urls.py`
    (voltando ao `DefaultRouter` puro) faz este teste reprovar com 403."""
    resposta = client.get("/api/v1/")
    assert resposta.status_code == 200
