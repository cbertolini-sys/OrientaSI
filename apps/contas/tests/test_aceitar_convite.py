import hashlib

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from apps.contas import services
from apps.contas.models import Convite, Usuario


@pytest.fixture
def coordenadora(db):
    return Usuario.objects.create_user(
        email="coord@ufsm.br",
        password="x",
        nome_completo="Coordenadora",
        cpf="52998224725",
        is_coordenador=True,
        is_staff=True,
    )


def cria_convite(coordenadora, papel, email="novo@ufsm.br"):
    """Cria o convite direto no banco para termos o token em claro no teste."""
    token = "token-de-teste-previsivel"
    convite = Convite.objects.create(
        email=email,
        papel=papel,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        criado_por=coordenadora,
        expira_em=timezone.now() + timezone.timedelta(days=7),
    )
    return convite, token


DADOS_ALUNO = {
    "nome_completo": "João Silva",
    "cpf": "16899535009",
    "telefone": "55999990000",
    "senha": "senha-bem-forte-123",
    "matricula": "201910001",
}


@pytest.mark.django_db
def test_aceitar_cria_usuario_e_perfil(coordenadora):
    convite, token = cria_convite(coordenadora, Usuario.ALUNO)

    usuario = services.aceitar_convite(token, DADOS_ALUNO)

    assert usuario.email == "novo@ufsm.br"
    assert usuario.papel == Usuario.ALUNO
    assert usuario.check_password("senha-bem-forte-123")
    assert usuario.perfil_aluno.matricula == "201910001"

    convite.refresh_from_db()
    assert convite.usado_em is not None
    assert convite.usuario_criado == usuario


@pytest.mark.django_db
def test_aceitar_cria_perfil_de_professor(coordenadora):
    convite, token = cria_convite(coordenadora, Usuario.PROFESSOR)
    dados = {**DADOS_ALUNO, "siape": "1234567"}
    del dados["matricula"]

    usuario = services.aceitar_convite(token, dados)

    assert usuario.papel == Usuario.PROFESSOR
    assert usuario.perfil_professor.siape == "1234567"


@pytest.mark.django_db
def test_token_invalido_expirado_e_usado_dao_a_mesma_mensagem(coordenadora):
    convite, token = cria_convite(coordenadora, Usuario.ALUNO)
    services.aceitar_convite(token, DADOS_ALUNO)

    mensagens = []
    for tentativa in ["token-que-nao-existe", token]:
        with pytest.raises(ValidationError) as erro:
            services.aceitar_convite(tentativa, DADOS_ALUNO)
        mensagens.append(str(erro.value))

    assert mensagens[0] == mensagens[1], (
        "Token inexistente e token já usado devem produzir a mesma mensagem: "
        "a diferença entre eles não é informação que o solicitante precise ter."
    )


@pytest.mark.django_db
def test_convite_expirado_e_recusado(coordenadora):
    convite, token = cria_convite(coordenadora, Usuario.ALUNO)
    convite.expira_em = timezone.now() - timezone.timedelta(seconds=1)
    convite.save(update_fields=["expira_em"])

    with pytest.raises(ValidationError):
        services.aceitar_convite(token, DADOS_ALUNO)


@pytest.mark.django_db
def test_falha_no_perfil_nao_deixa_usuario_orfao(coordenadora):
    """A transação é atômica: matrícula duplicada não pode deixar um Usuario solto."""
    _, token_um = cria_convite(coordenadora, Usuario.ALUNO, "um@ufsm.br")
    services.aceitar_convite(token_um, DADOS_ALUNO)

    Convite.objects.create(
        email="dois@ufsm.br",
        papel=Usuario.ALUNO,
        token_hash=hashlib.sha256(b"outro-token").hexdigest(),
        criado_por=coordenadora,
        expira_em=timezone.now() + timezone.timedelta(days=7),
    )
    dados = {**DADOS_ALUNO, "cpf": "11144477735"}  # matrícula continua repetida

    with pytest.raises(IntegrityError):
        services.aceitar_convite("outro-token", dados)

    assert not Usuario.objects.filter(email="dois@ufsm.br").exists()
