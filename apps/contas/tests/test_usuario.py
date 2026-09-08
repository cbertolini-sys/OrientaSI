import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.contas.models import Usuario
from apps.contas.validators import valida_cpf


def test_valida_cpf_aceita_valido():
    valida_cpf("52998224725")


@pytest.mark.parametrize("invalido", ["11111111111", "52998224726", "529982247", "abcdefghijk"])
def test_valida_cpf_recusa_invalido(invalido):
    with pytest.raises(ValidationError):
        valida_cpf(invalido)


@pytest.mark.django_db
def test_cria_usuario_com_email_como_identificador():
    usuario = Usuario.objects.create_user(
        email="ana@ufsm.br", password="senha-forte-123", nome_completo="Ana", cpf="52998224725"
    )
    assert usuario.get_username() == "ana@ufsm.br"
    assert usuario.check_password("senha-forte-123")
    assert usuario.papel == Usuario.PROFESSOR


@pytest.mark.django_db
def test_aluno_sem_cpf_e_recusado_pelo_banco():
    with pytest.raises(IntegrityError), transaction.atomic():
        Usuario.objects.create_user(
            email="joao@ufsm.br", password="x", nome_completo="João", papel=Usuario.ALUNO, cpf=None
        )


@pytest.mark.django_db
def test_aluno_com_cpf_vazio_e_recusado_pelo_banco():
    """cpf="" satisfaz cpf__isnull=False: sem o reforço extra, a constraint não pega isto."""
    with pytest.raises(IntegrityError), transaction.atomic():
        Usuario.objects.create_user(
            email="joao@ufsm.br", password="x", nome_completo="João", papel=Usuario.ALUNO, cpf=""
        )


@pytest.mark.django_db
def test_conta_sugrad_e_unica():
    Usuario.objects.create_user(
        email="sugrad@ufsm.br", password="x", nome_completo="SUGRAD", papel=Usuario.SUGRAD, cpf=None
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Usuario.objects.create_user(
            email="sugrad2@ufsm.br",
            password="x",
            nome_completo="SUGRAD 2",
            papel=Usuario.SUGRAD,
            cpf=None,
        )


@pytest.mark.django_db
def test_aluno_nao_pode_ser_coordenador():
    with pytest.raises(IntegrityError), transaction.atomic():
        Usuario.objects.create_user(
            email="ana@ufsm.br",
            password="x",
            nome_completo="Ana",
            papel=Usuario.ALUNO,
            cpf="52998224725",
            is_coordenador=True,
        )
