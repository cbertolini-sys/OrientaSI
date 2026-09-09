import re

import pytest
from django.conf import settings
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
    resposta = client.post(reverse("logout"))
    assert resposta.status_code == 302
    assert resposta.url == settings.LOGOUT_REDIRECT_URL
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_recuperacao_de_senha_envia_email(client, professora):
    resposta = client.post(reverse("password_reset"), {"email": "ana@ufsm.br"})
    assert resposta.status_code == 302
    assert len(mail.outbox) == 1
    assert "ana@ufsm.br" in mail.outbox[0].to


@pytest.mark.django_db
def test_fluxo_completo_de_recuperacao_de_senha_ate_novo_login(client, professora):
    """Cobertura ponta a ponta que faltava (revisão 1 da T9):
    `test_recuperacao_de_senha_envia_email` para no envio do e-mail e nunca
    exercita `password_reset_confirm`/`FormularioDefinirNovaSenha` — a perna
    mais sensível do fluxo (é ali que uma senha de verdade muda) ficava sem
    nenhuma trava contra regressão. Este teste extrai o link do e-mail,
    segue o redirecionamento que o Django faz para a URL "set-password/"
    (onde o token sai da URL e vai para a sessão), define a nova senha e
    confirma que ela — e só ela — autentica depois."""
    client.post(reverse("password_reset"), {"email": "ana@ufsm.br"})
    link = re.search(r"http://\S+", mail.outbox[0].body).group().replace("http://testserver", "")

    resposta_redirecionamento = client.get(link)
    assert resposta_redirecionamento.status_code == 302

    resposta_definicao = client.post(
        resposta_redirecionamento.url,
        {"new_password1": "nova-senha-bem-forte-456", "new_password2": "nova-senha-bem-forte-456"},
    )
    assert resposta_definicao.status_code == 302
    assert resposta_definicao.url == reverse("password_reset_complete")

    resposta_senha_antiga = client.post(
        reverse("login"), {"username": "ana@ufsm.br", "password": "senha-bem-forte-123"}
    )
    assert resposta_senha_antiga.status_code == 200
    assert "_auth_user_id" not in client.session

    resposta_senha_nova = client.post(
        reverse("login"), {"username": "ana@ufsm.br", "password": "nova-senha-bem-forte-456"}
    )
    assert resposta_senha_nova.status_code == 302
    assert client.session.get("_auth_user_id") == str(professora.pk)


@pytest.mark.django_db
def test_recuperacao_de_senha_com_email_inexistente_nao_revela_isso(client):
    """Não-enumeração de contas: e-mail sem conta segue o mesmo caminho
    (mesmo status, mesmo redirecionamento) de um e-mail com conta — só que
    sem enviar nada. Sem este teste, uma mudança futura em
    `FormularioRecuperarSenha` (que já é código nosso, não mais o padrão do
    Django) poderia diferenciar as duas respostas sem a suíte reclamar."""
    resposta = client.post(reverse("password_reset"), {"email": "naoexiste@ufsm.br"})
    assert resposta.status_code == 302
    assert resposta.url == reverse("password_reset_done")
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_login_com_email_inexistente_produz_mesma_mensagem_que_senha_errada(client, professora):
    """Mesma preocupação de não-enumeração, do lado do login:
    `FormularioLogin.error_messages` é código nosso (T9 sobrescreveu o
    padrão do Django), então precisa de um teste que trave a mensagem igual
    para "senha errada" e para "e-mail que não existe" — do contrário, dá
    para saber quem tem conta na instituição só tentando logar."""
    resposta_senha_errada = client.post(
        reverse("login"), {"username": "ana@ufsm.br", "password": "errada"}
    )
    resposta_email_inexistente = client.post(
        reverse("login"), {"username": "naoexiste@ufsm.br", "password": "qualquer-coisa"}
    )

    mensagens_senha_errada = [
        str(e) for e in resposta_senha_errada.context["form"].non_field_errors()
    ]
    mensagens_email_inexistente = [
        str(e) for e in resposta_email_inexistente.context["form"].non_field_errors()
    ]

    assert mensagens_senha_errada, "deveria haver uma mensagem de erro não ligada a nenhum campo"
    assert mensagens_senha_errada == mensagens_email_inexistente


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
