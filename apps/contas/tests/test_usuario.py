import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.contas.admin import FormularioCriacaoUsuario
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
def test_email_e_normalizado_tambem_pelo_caminho_do_admin():
    """`GerenciadorUsuario._criar` (T7) só normaliza quem passa por
    `create_user`/`create_superuser`. O admin grava pelo `ModelForm.save()`,
    que chama `Usuario(...).save()` direto — sem esta cobertura, o sinal
    `normaliza_email_do_usuario` (apps/contas/signals.py) seria a única
    coisa evitando duas grafias da mesma conta (revisão 1 da T9)."""
    formulario = FormularioCriacaoUsuario(
        data={
            "email": "Ana@UFSM.br",
            "nome_completo": "Ana",
            "cpf": "52998224725",
            "password1": "senha-bem-forte-123",
            "password2": "senha-bem-forte-123",
        }
    )
    assert formulario.is_valid(), formulario.errors
    usuario = formulario.save()
    assert usuario.email == "ana@ufsm.br"


@pytest.mark.django_db
def test_grafia_diferente_do_mesmo_email_pelo_admin_e_recusada_pelo_banco():
    """Reproduz o bug real da revisão 1 da T9: a primeira conta é criada
    pelo caminho normal (`create_user`, já normalizava desde a T7); a
    segunda tenta entrar pelo caminho do admin (`ModelForm.save()`, que
    NÃO passa por `create_user`) com uma grafia em maiúsculas que a
    validação de unicidade do próprio formulário (comparação exata) não
    pega. Sem o sinal `normaliza_email_do_usuario`
    (apps/contas/signals.py), esta segunda gravação criava uma duplicata
    silenciosa e `get_by_natural_key` (busca `__iexact`) levantava
    `MultipleObjectsReturned` — 500 — ao autenticar qualquer uma das duas
    contas."""
    Usuario.objects.create_user(
        email="ana@ufsm.br",
        password="senha-bem-forte-123",
        nome_completo="Ana",
        cpf="52998224725",
    )
    formulario = FormularioCriacaoUsuario(
        data={
            "email": "ANA@UFSM.BR",
            "nome_completo": "Ana Outra",
            "cpf": "11144477735",
            "password1": "senha-bem-forte-456",
            "password2": "senha-bem-forte-456",
        }
    )
    # A validação de unicidade do form é exata: "ANA@UFSM.BR" não bate com o
    # "ana@ufsm.br" já gravado, então o form passa — é o banco, com o e-mail
    # já normalizado pelo sinal antes do INSERT, que precisa barrar isto.
    assert formulario.is_valid(), formulario.errors
    with pytest.raises(IntegrityError), transaction.atomic():
        formulario.save()
    assert Usuario.objects.filter(email__iexact="ana@ufsm.br").count() == 1


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
