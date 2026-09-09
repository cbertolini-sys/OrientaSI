import pytest
from django.core.management import call_command

from apps.contas.models import Usuario

ARGUMENTOS = [
    "--email-coordenador",
    "coord@ufsm.br",
    "--nome-coordenador",
    "Coordenação do Curso",
    "--cpf-coordenador",
    "52998224725",
    "--email-sugrad",
    "sugrad@ufsm.br",
]


@pytest.mark.django_db
def test_semear_cria_sugrad_e_coordenador():
    call_command("semear_sistema", *ARGUMENTOS)

    coordenadora = Usuario.objects.get(email="coord@ufsm.br")
    assert coordenadora.is_coordenador is True
    assert coordenadora.is_staff is True
    assert coordenadora.papel == Usuario.PROFESSOR

    sugrad = Usuario.objects.get(email="sugrad@ufsm.br")
    assert sugrad.papel == Usuario.SUGRAD
    assert sugrad.cpf is None


@pytest.mark.django_db
def test_semear_e_idempotente():
    call_command("semear_sistema", *ARGUMENTOS)
    call_command("semear_sistema", *ARGUMENTOS)

    assert Usuario.objects.filter(email="coord@ufsm.br").count() == 1
    assert Usuario.objects.filter(papel=Usuario.SUGRAD).count() == 1


@pytest.mark.django_db
def test_semear_nao_rebaixa_quem_ja_e_coordenador():
    call_command("semear_sistema", *ARGUMENTOS)
    outra = Usuario.objects.create_user(
        email="outra@ufsm.br",
        password="x",
        nome_completo="Outra",
        cpf="16899535009",
        is_coordenador=True,
        is_staff=True,
    )

    call_command("semear_sistema", *ARGUMENTOS)

    outra.refresh_from_db()
    assert outra.is_coordenador is True
