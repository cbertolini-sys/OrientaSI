"""Testes do Bloco H: `/api/v1/calendario/` (`apps/publico/api_views.py`)."""

import pytest
from django.utils import timezone

from apps.bancas.models import Banca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto


def _cpf(indice):
    base = f"{870000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _banca(indice, data_hora, status=Banca.AGENDADA):
    orientador = Usuario.objects.create_user(
        email=f"orientador.apicalendario.{indice}@ufsm.br",
        password="x",
        nome_completo=f"Orientador API Calendário {indice}",
        cpf=_cpf(indice * 10 + 1),
    )
    PerfilProfessor.objects.create(usuario=orientador, siape=f"APICAL{indice:03d}")
    aluno = Usuario.objects.create_user(
        email=f"aluno.apicalendario.{indice}@ufsm.br",
        password="x",
        nome_completo=f"Aluno API Calendário {indice}",
        papel=Usuario.ALUNO,
        cpf=_cpf(indice * 10 + 2),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula=f"2026APICAL{indice:03d}")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador,
        etapa=Projeto.TCC_I,
        status=Projeto.AGUARDANDO_DEFESA,
        ano=2026,
        periodo=1,
    )
    return Banca.objects.create(
        projeto=projeto, data_hora=data_hora, local=f"Sala API {indice}", status=status
    )


@pytest.mark.django_db
def test_api_calendario_lista_banca_agendada_futura(client):
    futura = timezone.now() + timezone.timedelta(days=5)
    banca = _banca(1, futura)
    resposta = client.get("/api/v1/calendario/")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["count"] == 1
    item = corpo["results"][0]
    assert item["aluno"] == banca.projeto.aluno.nome_completo
    assert item["orientador"] == banca.projeto.orientador.nome_completo
    assert item["titulo"] is None
    assert item["local"] == banca.local


@pytest.mark.django_db
def test_api_calendario_esconde_banca_realizada(client):
    futura = timezone.now() + timezone.timedelta(days=5)
    _banca(2, futura, status=Banca.REALIZADA)
    resposta = client.get("/api/v1/calendario/")
    assert resposta.json()["count"] == 0


@pytest.mark.django_db
def test_api_calendario_esconde_banca_com_data_passada(client):
    passada = timezone.now() - timezone.timedelta(days=1)
    _banca(3, passada)
    resposta = client.get("/api/v1/calendario/")
    assert resposta.json()["count"] == 0


@pytest.mark.django_db
def test_api_calendario_retrieve_funciona(client):
    futura = timezone.now() + timezone.timedelta(days=5)
    banca = _banca(4, futura)
    resposta = client.get(f"/api/v1/calendario/{banca.pk}/")
    assert resposta.status_code == 200
    assert resposta.json()["id"] == banca.pk


@pytest.mark.django_db
def test_api_calendario_retrieve_de_banca_passada_da_404(client):
    passada = timezone.now() - timezone.timedelta(days=1)
    banca = _banca(5, passada)
    resposta = client.get(f"/api/v1/calendario/{banca.pk}/")
    assert resposta.status_code == 404
