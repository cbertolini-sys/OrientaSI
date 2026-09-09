import hashlib

import pytest
from django.core.exceptions import ValidationError
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
    """Cria o convite direto no banco para termos o token em claro no teste.

    O token deriva do e-mail (e não é mais fixo) para permitir criar mais de um
    convite na mesma função de teste sem colidir em `token_hash`, que é
    `unique=True` (ex.: test_token_invalido_expirado_e_usado_dao_a_mesma_mensagem,
    que precisa de um convite usado E de um expirado).
    """
    token = f"token-de-teste-previsivel-{email}"
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
    _, token_usado = cria_convite(coordenadora, Usuario.ALUNO, "usado@ufsm.br")
    services.aceitar_convite(token_usado, DADOS_ALUNO)

    expirado, token_expirado = cria_convite(coordenadora, Usuario.ALUNO, "expirado@ufsm.br")
    expirado.expira_em = timezone.now() - timezone.timedelta(seconds=1)
    expirado.save(update_fields=["expira_em"])

    mensagens = []
    for tentativa in ["token-que-nao-existe", token_usado, token_expirado]:
        with pytest.raises(ValidationError) as erro:
            services.aceitar_convite(tentativa, DADOS_ALUNO)
        mensagens.append(str(erro.value))

    assert mensagens[0] == mensagens[1] == mensagens[2], (
        "Token inexistente, expirado e já usado devem produzir a mesma mensagem: "
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
    """A transação é atômica: matrícula duplicada não pode deixar um Usuario solto.

    `aceitar_convite` converte o IntegrityError da colisão em ValidationError
    (rede de segurança contra corrida — ver services.py), mas a garantia que
    este teste prova é outra: mesmo com a conversão, nenhum Usuario órfão
    sobra. Se alguém remover o `@transaction.atomic` de
    `_aceitar_convite_atomico` mas mantiver o try/except aqui, o Usuario da
    tentativa "dois@ufsm.br" seria criado e ficaria — o único jeito de este
    teste continuar verde é a transação de fato desfazer os dois passos.
    """
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

    with pytest.raises(ValidationError):
        services.aceitar_convite("outro-token", dados)

    assert not Usuario.objects.filter(email="dois@ufsm.br").exists()


@pytest.mark.django_db
def test_aceitar_convite_bloqueia_a_linha_do_convite(coordenadora):
    """`busca_convite_valido(..., para_atualizacao=True)` deve emitir SELECT ... FOR
    UPDATE: sem o bloqueio, dois aceites simultâneos do mesmo token passariam
    ambos pela checagem de validade antes que o primeiro gravasse `usado_em`."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    convite, token = cria_convite(coordenadora, Usuario.ALUNO)

    with CaptureQueriesContext(connection) as capturado:
        services.aceitar_convite(token, DADOS_ALUNO)

    assert any("FOR UPDATE" in query["sql"].upper() for query in capturado.captured_queries), (
        "Nenhuma consulta capturada usou SELECT ... FOR UPDATE — o convite não "
        "está sendo bloqueado durante o aceite."
    )
