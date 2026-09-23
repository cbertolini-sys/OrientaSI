import re

import pytest
from django.conf import settings
from django.core import mail
from django.urls import reverse

from apps.contas import tasks
from apps.contas.models import Usuario


@pytest.fixture(autouse=True)
def celery_sincrono(settings):
    """A recuperação de senha passou a enfileirar `enviar_recuperacao_senha`
    no Celery (spec §6 e §7.6) em vez de falar SMTP dentro da requisição.
    Sem modo síncrono, `.delay()` publicaria a mensagem no broker Redis de
    verdade e `mail.outbox` ficaria vazio — os testes de e-mail desta suíte
    dependem desta fixture desde a onda final. Mesmo mecanismo que a fixture
    `envia_convite` de test_convites.py já usava para o convite."""
    settings.CELERY_TASK_ALWAYS_EAGER = True


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
@pytest.mark.parametrize(
    "papel,is_coordenador",
    [
        (Usuario.ALUNO, False),
        (Usuario.PROFESSOR, False),
        (Usuario.PROFESSOR, True),
        (Usuario.SUGRAD, False),
    ],
    ids=["aluno", "professor", "coordenador", "sugrad"],
)
def test_recuperacao_de_senha_funciona_para_todos_os_perfis(client, papel, is_coordenador):
    """Pedido do usuário (2026-09-22): `password_reset` (Django puro, sem
    ramificação por `papel`/`is_coordenador` em `FormularioRecuperarSenha`
    nem em `PasswordResetForm.get_users()`) já deveria valer pra qualquer
    `Usuario` — este teste prova que não há nenhuma trava escondida contra
    aluno, coordenador ou a conta da SUGRAD."""
    usuario = Usuario.objects.create_user(
        email=f"recuperacao.{papel.lower()}.{is_coordenador}@ufsm.br",
        password="senha-bem-forte-123",
        nome_completo=f"Pessoa {papel}",
        # SUGRAD é um setor, não uma pessoa, e não tem CPF (models.py,
        # constraint `cpf_obrigatorio_para_pessoas`) — mesmo formato que
        # `semear_sistema._semear_sugrad` usa de verdade.
        cpf=None if papel == Usuario.SUGRAD else "52998224725",
        papel=papel,
        is_coordenador=is_coordenador,
        is_staff=is_coordenador,
    )
    resposta = client.post(reverse("password_reset"), {"email": usuario.email})
    assert resposta.status_code == 302
    assert len(mail.outbox) == 1
    assert usuario.email in mail.outbox[0].to


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
    # O link do e-mail agora é montado a partir de `settings.URL_BASE` (é a
    # tarefa Celery que monta o contexto, fora de qualquer requisição, como o
    # e-mail de convite já fazia) — não mais do `request.get_host()`, que
    # produzia "testserver" sob o cliente de teste.
    link = re.search(r"http://\S+", mail.outbox[0].body).group().replace(settings.URL_BASE, "")

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


# --- Resumo de erros das telas de autenticação (achado da revisão final) ----


def _link_de_recuperacao(client):
    client.post(reverse("password_reset"), {"email": "ana@ufsm.br"})
    link = re.search(r"http://\S+", mail.outbox[0].body).group().replace(settings.URL_BASE, "")
    return client.get(link).url


@pytest.mark.django_db
def test_post_invalido_na_recuperacao_mostra_resumo_de_erros(client):
    """A condição do resumo era `form.non_field_errors`, sempre vazia aqui: os
    erros de `PasswordResetForm` são erros DE CAMPO (`email`). O resumo nunca
    aparecia e o foco não se movia depois de um POST inválido — a correção
    feita na T10 (perfil.html) nunca voltou para as telas da T9. Nenhuma suíte
    fazia POST nestas rotas, que é exatamente por que o defeito sobreviveu."""
    resposta = client.post(reverse("password_reset"), {"email": "nao-e-email"})
    html = resposta.content.decode()

    assert resposta.status_code == 200
    assert 'id="resumo-erros"' in html
    assert 'id="erro-email"' in html


@pytest.mark.django_db
def test_post_invalido_na_definicao_de_nova_senha_mostra_resumo_de_erros(client, professora):
    """Mesmo defeito em password_reset_confirm.html: os erros de
    `SetPasswordForm` (senhas que não conferem, senha fraca) são erros do
    campo `new_password2`."""
    url_definicao = _link_de_recuperacao(client)

    resposta = client.post(
        url_definicao, {"new_password1": "uma-senha-boa-123", "new_password2": "outra-senha-456"}
    )
    html = resposta.content.decode()

    assert resposta.status_code == 200
    assert 'id="resumo-erros"' in html
    assert 'id="erro-new_password2"' in html


@pytest.mark.django_db(transaction=True)
def test_ajuda_de_nova_senha_nao_fica_dentro_de_p_quando_e_html(
    client, page, live_server, professora
):
    """password_reset_confirm.html não entra em nenhuma suíte de rotas
    autenticadas (o dataclass `Rota` de conftest.py não suporta caminho
    dinâmico com uid/token — pendência registrada, não remendada aqui), então
    nenhuma suíte de acessibilidade jamais renderiza esta tela. O `help_text`
    de `new_password1` (`password_validators_help_text_html()`) é HTML de
    verdade, com uma `<ul>` de requisitos — e `<ul>` não é conteúdo válido
    dentro de `<p>`: o parser HTML de um navegador fecha o `<p>` sozinho ao
    encontrar a `<ul>`, e a lista sai como elemento IRMÃO do bloco que o
    aria-describedby do campo aponta, não dentro dele (achado de revisão da
    T2 do Bloco B; `templates/contas/_campo.html` usa `<div>` por causa
    disso). Uma checagem de string no HTML servido pelo Django não pegaria
    essa reinterpretação — o servidor manda a `<ul>` aninhada dentro do
    `<p>` no texto puro, só um parser de verdade (o do navegador, aqui via
    Playwright) separa os dois. Por isso este teste navega de verdade, em
    vez de inspecionar `resposta.content`."""
    url_definicao = _link_de_recuperacao(client)

    # Transplanta a sessão do Client (onde password_reset_confirm guardou o
    # token) para o navegador real — mesmo mecanismo de
    # `autentica_no_navegador` em conftest.py.
    cookie = client.cookies[settings.SESSION_COOKIE_NAME]
    page.context.add_cookies(
        [{"name": settings.SESSION_COOKIE_NAME, "value": cookie.value, "url": live_server.url}]
    )
    page.goto(f"{live_server.url}{url_definicao}")

    ajuda = page.locator("#ajuda-new_password1")
    assert ajuda.evaluate("el => el.tagName") == "DIV", (
        "O contêiner do texto de ajuda de new_password1 precisa ser <div>: "
        "<p> fecha sozinho ao encontrar a <ul> de requisitos de senha, e a "
        "lista sai de dentro do que o aria-describedby aponta."
    )
    assert ajuda.locator("ul").count() == 1, (
        "A <ul> de requisitos de senha devia estar DENTRO do contêiner de "
        "ajuda — se não está, o parser HTML a expulsou para fora."
    )


@pytest.mark.django_db
def test_post_vazio_no_login_mostra_resumo_de_erros(client):
    """`login.html` escapava por acaso — credencial inválida É erro não ligado
    a campo. O formulário VAZIO produz só erros de campo, e ali o resumo
    também não aparecia."""
    resposta = client.post(reverse("login"), {"username": "", "password": ""})
    html = resposta.content.decode()

    assert resposta.status_code == 200
    assert 'id="resumo-erros"' in html


@pytest.mark.django_db
def test_recuperacao_de_senha_nao_fala_smtp_dentro_da_requisicao(client, professora, settings):
    """A prova de que o envio saiu da requisição (spec §6 e §7.6): com o modo
    síncrono DESLIGADO, a requisição só enfileira — nada é enviado enquanto o
    worker não roda. Antes, o `PasswordResetView` cru fazia o SMTP ali mesmo:
    servidor de e-mail lento ou fora do ar virava 500 na cara da pessoa, sem
    repetição nenhuma."""
    settings.CELERY_TASK_ALWAYS_EAGER = False
    enfileirados = []
    original = tasks.enviar_recuperacao_senha.delay
    tasks.enviar_recuperacao_senha.delay = lambda usuario_id: enfileirados.append(usuario_id)
    try:
        resposta = client.post(reverse("password_reset"), {"email": "ana@ufsm.br"})
    finally:
        tasks.enviar_recuperacao_senha.delay = original

    assert resposta.status_code == 302
    assert enfileirados == [professora.pk]
    assert mail.outbox == []


@pytest.mark.django_db
def test_email_de_recuperacao_usa_o_protocolo_e_o_dominio_de_url_base(client, professora, settings):
    """O `{{ protocol }}` do template vinha de `request.is_secure()`, que é
    False atrás de um proxy que termina o TLS: os e-mails de um sistema
    servido por HTTPS sairiam com link `http://`. A tarefa monta o contexto a
    partir de `URL_BASE`, a mesma origem do e-mail de convite."""
    settings.URL_BASE = "https://orientasi.ufsm.br"

    client.post(reverse("password_reset"), {"email": "ana@ufsm.br"})

    assert "https://orientasi.ufsm.br/contas/reset/" in mail.outbox[0].body
