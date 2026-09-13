"""Testes de integração da view `aceitar_convite`: formulário certo por papel,
validação de senha, criação + login + redirecionamento e token inexistente.

Sem estes testes, uma renomeação de chave em `formulario.cleaned_data` (que
`services.aceitar_convite` espera encontrar em `dados[...]`) só quebraria em
produção — nenhum teste de serviço (que chama `services.aceitar_convite`
diretamente, com um dicionário escrito à mão) passa pela view nem pelo
formulário de verdade.
"""

import hashlib

import pytest
from django.utils import timezone

from apps.contas.models import Convite, Usuario


@pytest.fixture
def coordenadora(db):
    return Usuario.objects.create_user(
        email="coord-view@ufsm.br",
        password="x",
        nome_completo="Coordenadora",
        cpf="87721295037",
        is_coordenador=True,
        is_staff=True,
    )


def cria_convite(coordenadora, papel, email, token):
    return Convite.objects.create(
        email=email,
        papel=papel,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        criado_por=coordenadora,
        expira_em=timezone.now() + timezone.timedelta(days=7),
    )


DADOS_ALUNO = {
    "nome_completo": "Aluno View",
    "cpf": "111.444.777-35",
    "telefone": "",
    "senha": "senha-bem-forte-123",
    "senha_confirmacao": "senha-bem-forte-123",
    "matricula": "202099999",
}


@pytest.mark.django_db
def test_get_convite_de_aluno_mostra_campo_matricula(client, coordenadora):
    cria_convite(coordenadora, Usuario.ALUNO, "aluno-get@ufsm.br", "token-aluno-get")

    resposta = client.get("/convite/token-aluno-get/")

    assert resposta.status_code == 200
    assert b'name="matricula"' in resposta.content
    assert b'name="siape"' not in resposta.content


@pytest.mark.django_db
def test_get_convite_de_professor_mostra_campo_siape(client, coordenadora):
    cria_convite(coordenadora, Usuario.PROFESSOR, "professor-get@ufsm.br", "token-professor-get")

    resposta = client.get("/convite/token-professor-get/")

    assert resposta.status_code == 200
    assert b'name="siape"' in resposta.content
    assert b'name="matricula"' not in resposta.content


@pytest.mark.django_db
def test_post_com_senhas_divergentes_nao_cria_conta(client, coordenadora):
    cria_convite(coordenadora, Usuario.ALUNO, "diverge@ufsm.br", "token-diverge")

    dados = {**DADOS_ALUNO, "senha_confirmacao": "outra-coisa-qualquer"}
    resposta = client.post("/convite/token-diverge/", dados)

    assert resposta.status_code == 200
    assert "As senhas não conferem." in resposta.content.decode()
    assert not Usuario.objects.filter(email="diverge@ufsm.br").exists()


@pytest.mark.django_db
def test_post_valido_cria_conta_loga_e_redireciona(client, coordenadora):
    cria_convite(coordenadora, Usuario.ALUNO, "valido@ufsm.br", "token-valido")

    resposta = client.post("/convite/token-valido/", DADOS_ALUNO)

    assert resposta.status_code == 302
    assert resposta.url == "/"
    usuario = Usuario.objects.get(email="valido@ufsm.br")
    assert usuario.perfil_aluno.matricula == "202099999"

    resposta_inicio = client.get("/")
    assert resposta_inicio.wsgi_request.user.is_authenticated
    assert resposta_inicio.wsgi_request.user == usuario


@pytest.mark.django_db
def test_token_inexistente_devolve_404(client, coordenadora):
    resposta = client.get("/convite/nao-existe-de-verdade/")

    assert resposta.status_code == 404
    assert "Convite inválido" in resposta.content.decode()


@pytest.mark.django_db
def test_matricula_duplicada_via_view_nao_derruba_com_500(client, coordenadora):
    """Antes da correção, uma matrícula já usada chegava intacta até o serviço e
    o IntegrityError do banco escapava como erro 500. O formulário agora valida
    a unicidade antes de chamar o serviço (clean_matricula em forms.py)."""
    cria_convite(coordenadora, Usuario.ALUNO, "primeiro@ufsm.br", "token-primeiro")
    resposta_primeiro = client.post("/convite/token-primeiro/", DADOS_ALUNO)
    assert resposta_primeiro.status_code == 302  # sanidade: a primeira conta foi criada

    cria_convite(coordenadora, Usuario.ALUNO, "segundo@ufsm.br", "token-segundo")
    dados = {**DADOS_ALUNO, "cpf": "16899535009"}  # matrícula 202099999 já está em uso
    resposta = client.post("/convite/token-segundo/", dados)

    assert resposta.status_code == 200
    assert "matrícula" in resposta.content.decode().lower()
    assert not Usuario.objects.filter(email="segundo@ufsm.br").exists()


@pytest.mark.django_db(transaction=True)
def test_foco_vai_para_o_resumo_de_erros_apos_post_invalido(page, live_server, coordenadora):
    """Depois de um POST inválido a página inteira recarrega (não há HTMX aqui):
    sem mover o foco, quem navega só por teclado ou leitor de tela não recebe
    nenhum sinal de que algo deu errado além do role="alert", que só é ouvido
    por quem já estiver com o foco nele no instante em que a página carrega."""
    cria_convite(coordenadora, Usuario.ALUNO, "foco@ufsm.br", "token-foco")

    page.goto(f"{live_server.url}/convite/token-foco/")
    page.click("button[type=submit]")  # formulário vazio: dispara os erros obrigatórios

    # Corrida diagnosticada (instabilidade ~1 em 4, só na suíte inteira, nunca
    # isolado — reproduzida sob carga sintética de CPU, 23/80 falhas): o
    # `autofocus` do HTML só é aplicado pelo navegador numa "oportunidade de
    # renderização" (a rotina de flush de autofocus roda junto do pipeline de
    # pintura), um evento DIFERENTE — e mais tardio — do que o `load` que
    # `page.click()` já espera antes de devolver o controle. Sob contenção de
    # CPU (a suíte inteira aciona dezenas de páginas Playwright em sequência),
    # o documento pode terminar de carregar (`document.readyState ===
    # "complete"`) sem que o navegador ainda tenha tido a chance de pintar um
    # frame — e ler `activeElement` nesse intervalo pega o foco ainda em
    # <body>. Confirmado isolando a variável: sob a MESMA carga sintética (8
    # processos saturando CPU), sem este `evaluate` a falha ficou em 23/80;
    # com ele, 0/80 em três rodadas seguidas. Duas chamadas aninhadas de
    # `requestAnimationFrame` forçam o navegador a completar um ciclo de
    # renderização antes da leitura abaixo — sem inspecionar o próprio foco
    # (o valor de `ativo`), só garantindo que a rotina do navegador que o
    # move já teve a chance de rodar.
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")

    ativo = page.evaluate("document.activeElement.id")
    assert (
        ativo == "resumo-erros"
    ), f"Depois do POST inválido, o foco deveria estar em #resumo-erros, e está em {ativo!r}."
