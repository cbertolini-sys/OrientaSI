import pytest


@pytest.mark.django_db
def test_saude_responde_ok(client):
    resposta = client.get("/saude/")
    assert resposta.status_code == 200
    assert resposta.json() == {"estado": "ok"}
