"""Testes de integração da view `contas:perfil`: exige autenticação, permite
que o professor escolha suas áreas de atuação e esconde esse campo do aluno
(que não tem `PerfilProfessor.areas`).
"""

import pytest
from django.urls import reverse

from apps.contas.models import Area, PerfilProfessor, Usuario


@pytest.fixture
def professora(db):
    usuario = Usuario.objects.create_user(
        email="ana@ufsm.br",
        password="senha-bem-forte-123",
        nome_completo="Ana",
        cpf="52998224725",
    )
    PerfilProfessor.objects.create(usuario=usuario, siape="1234567")
    return usuario


@pytest.mark.django_db
def test_perfil_exige_autenticacao(client):
    resposta = client.get(reverse("contas:perfil"))
    assert resposta.status_code == 302
    assert "/contas/login/" in resposta.url


@pytest.mark.django_db
def test_professor_seleciona_suas_areas(client, professora):
    ia = Area.objects.create(nome="Inteligência Artificial")
    redes = Area.objects.create(nome="Redes")
    client.force_login(professora)

    resposta = client.post(
        reverse("contas:perfil"),
        {"telefone": "55999990000", "areas": [ia.pk, redes.pk]},
    )

    assert resposta.status_code == 302
    professora.refresh_from_db()
    assert set(professora.perfil_professor.areas.all()) == {ia, redes}
    assert professora.telefone == "55999990000"


@pytest.mark.django_db
def test_aluno_nao_ve_campo_de_areas(client, db):
    aluno = Usuario.objects.create_user(
        email="joao@ufsm.br",
        password="senha-bem-forte-123",
        nome_completo="João",
        cpf="16899535009",
        papel=Usuario.ALUNO,
    )
    client.force_login(aluno)
    html = client.get(reverse("contas:perfil")).content.decode()
    assert "areas" not in html
