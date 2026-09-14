"""Testes do Bloco G: `calendario_publico` (`apps/publico/services.py`)."""

import pytest
from django.utils import timezone

from apps.bancas.models import Banca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto
from apps.publico import services


def _cpf(indice):
    base = f"{850000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _banca(indice, data_hora, status=Banca.AGENDADA):
    orientador = Usuario.objects.create_user(
        email=f"orientador.calendario.{indice}@ufsm.br",
        password="x",
        nome_completo=f"Orientador Calendário {indice}",
        cpf=_cpf(indice * 10 + 1),
    )
    PerfilProfessor.objects.create(usuario=orientador, siape=f"CAL{indice:03d}")
    aluno = Usuario.objects.create_user(
        email=f"aluno.calendario.{indice}@ufsm.br",
        password="x",
        nome_completo=f"Aluno Calendário {indice}",
        papel=Usuario.ALUNO,
        cpf=_cpf(indice * 10 + 2),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula=f"2026CAL{indice:03d}")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador,
        etapa=Projeto.TCC_I,
        status=Projeto.AGUARDANDO_DEFESA,
        ano=2026,
        periodo=1,
    )
    return Banca.objects.create(
        projeto=projeto, data_hora=data_hora, local=f"Sala {indice}", status=status
    )


@pytest.mark.django_db
def test_calendario_publico_mostra_banca_agendada_futura():
    futura = timezone.now() + timezone.timedelta(days=5)
    banca = _banca(1, futura)
    assert banca in services.calendario_publico()


@pytest.mark.django_db
def test_calendario_publico_esconde_banca_realizada():
    futura = timezone.now() + timezone.timedelta(days=5)
    banca = _banca(2, futura, status=Banca.REALIZADA)
    assert banca not in services.calendario_publico()


@pytest.mark.django_db
def test_calendario_publico_esconde_banca_cancelada():
    futura = timezone.now() + timezone.timedelta(days=5)
    banca = _banca(3, futura, status=Banca.CANCELADA)
    assert banca not in services.calendario_publico()


@pytest.mark.django_db
def test_calendario_publico_esconde_banca_com_data_passada():
    passada = timezone.now() - timezone.timedelta(days=1)
    banca = _banca(4, passada)
    assert banca not in services.calendario_publico()


@pytest.mark.django_db
def test_calendario_publico_ordena_mais_proxima_primeiro():
    mais_distante = _banca(5, timezone.now() + timezone.timedelta(days=10))
    mais_proxima = _banca(6, timezone.now() + timezone.timedelta(days=2))
    resultado = list(services.calendario_publico())
    assert resultado.index(mais_proxima) < resultado.index(mais_distante)
