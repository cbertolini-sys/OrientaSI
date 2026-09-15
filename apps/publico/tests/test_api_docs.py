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
