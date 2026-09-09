import pytest
from django.core import mail
from django.urls import reverse

from apps.contas.models import Usuario


@pytest.fixture
def professora(db):
    return Usuario.objects.create_user(
        email="ana@ufsm.br",
        password="senha-bem-forte-123",
        nome_completo="Ana",
        cpf="52998224725",
    )


@pytest.mark.django_db
def test_login_com_email_e_senha(client, professora):
    resposta = client.post(
        reverse("login"), {"username": "ana@ufsm.br", "password": "senha-bem-forte-123"}
    )
    assert resposta.status_code == 302
    assert client.session.get("_auth_user_id") == str(professora.pk)


@pytest.mark.django_db
def test_login_recusa_senha_errada(client, professora):
    resposta = client.post(reverse("login"), {"username": "ana@ufsm.br", "password": "errada"})
    assert resposta.status_code == 200
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_logout_encerra_a_sessao(client, professora):
    client.force_login(professora)
    client.post(reverse("logout"))
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_recuperacao_de_senha_envia_email(client, professora):
    resposta = client.post(reverse("password_reset"), {"email": "ana@ufsm.br"})
    assert resposta.status_code == 302
    assert len(mail.outbox) == 1
    assert "ana@ufsm.br" in mail.outbox[0].to


@pytest.mark.django_db
def test_login_aceita_email_em_caixa_diferente_da_cadastrada(client):
    """T7 minusculiza o e-mail inteiro ao cadastrar (GerenciadorUsuario._criar), mas
    o `get_by_natural_key` padrão do Django faz busca exata (case-sensitive). Sem a
    correção em `GerenciadorUsuario.get_by_natural_key`, quem se cadastrou como
    "Ana@ufsm.br" (gravado como "ana@ufsm.br") e digitar o e-mail com maiúsculas no
    login teria acesso negado sem explicação possível."""
    Usuario.objects.create_user(
        email="Ana@UFSM.br",
        password="senha-bem-forte-123",
        nome_completo="Ana",
        cpf="52998224725",
    )
    resposta = client.post(
        reverse("login"), {"username": "ANA@ufsm.br", "password": "senha-bem-forte-123"}
    )
    assert resposta.status_code == 302
    assert client.session.get("_auth_user_id") is not None
