"""Suíte de acessibilidade da tela de perfil (T10), que exige autenticação.

`/perfil/` fica de propósito FORA de `ROTAS` (conftest.py): as quatro suítes
transversais (`tests/test_acessibilidade.py`, `test_teclado.py`,
`test_toque.py`, `test_responsivo.py`) navegam sempre anônimas, e uma rota
atrás de `login_required` responde com um redirecionamento para
`/contas/login/` — acrescentar `/perfil/` a `ROTAS` faria essas quatro
suítes medirem a tela de login, não a tela de perfil (o mesmo defeito que a
Tarefa 8 corrigiu: suíte verde medindo a página errada, ver
`tests/test_rotas.py`).

Este arquivo repete, só para `/perfil/`, as mesmas verificações que as
quatro suítes fazem para as rotas anônimas, autenticando antes de navegar:
login via `django.test.Client` (que cria a sessão no banco de teste) e
injeção do cookie de sessão resultante no contexto do Playwright — a
navegação real do navegador chega com a sessão já aberta, sem precisar
preencher o formulário de login na tela.

Cobre as duas variantes do formulário (professor, com o campo de áreas
dentro do `<fieldset>`; aluno, sem ele) porque o achado mais provável desta
tarefa — o grupo de caixas de seleção sem `<legend>` — só existe na
variante do professor.
"""

import pytest
from axe_playwright_python.sync_playwright import Axe
from django.conf import settings
from django.test import Client

from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario

REGRAS = {"runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21aa"]}}
LARGURAS_TESTADAS = [1280, 360]

# Mesma lista de tests/test_toque.py: alvos interativos considerados pela
# verificação de tamanho mínimo de toque (WCAG 2.5.5).
INTERATIVOS = (
    "a, button, input:not([type=hidden]), select, textarea, summary, "
    "[tabindex]:not([tabindex='-1']), "
    "[role=button], [role=link], [role=checkbox], [role=tab], [role=menuitem]"
)


def _cria_professor():
    usuario = Usuario.objects.create_user(
        email="perfil-professor@ufsm.br",
        password="senha-bem-forte-123",
        nome_completo="Professora do Perfil",
        cpf="52998224725",
    )
    PerfilProfessor.objects.create(usuario=usuario, siape="7654321")
    Area.objects.create(nome="Engenharia de Software")
    return usuario


def _cria_aluno():
    usuario = Usuario.objects.create_user(
        email="perfil-aluno@ufsm.br",
        password="senha-bem-forte-123",
        nome_completo="Aluno do Perfil",
        cpf="16899535009",
        papel=Usuario.ALUNO,
    )
    PerfilAluno.objects.create(usuario=usuario, matricula="202100001")
    return usuario


@pytest.fixture(params=["professor", "aluno"])
def usuario_perfil(request, db):
    return _cria_professor() if request.param == "professor" else _cria_aluno()


@pytest.fixture
def pagina_autenticada(page, live_server, usuario_perfil):
    """Devolve `page` com a sessão de `usuario_perfil` já aberta.

    `Client.force_login` grava a sessão diretamente no banco (sem passar pelo
    formulário de login); o cookie de sessão resultante é injetado no
    contexto do Playwright antes de qualquer navegação, para que
    `page.goto("/perfil/")` chegue autenticada.
    """
    cliente = Client()
    cliente.force_login(usuario_perfil)
    cookie = cliente.cookies[settings.SESSION_COOKIE_NAME]
    page.context.add_cookies(
        [{"name": settings.SESSION_COOKIE_NAME, "value": cookie.value, "url": live_server.url}]
    )
    return page


@pytest.mark.django_db(transaction=True)
def test_perfil_responde_200_autenticado(pagina_autenticada, live_server):
    resposta = pagina_autenticada.goto(f"{live_server.url}/perfil/")
    assert resposta.status == 200
    assert pagina_autenticada.query_selector("form") is not None


@pytest.mark.django_db(transaction=True)
def test_perfil_nao_viola_wcag(pagina_autenticada, live_server):
    pagina_autenticada.goto(f"{live_server.url}/perfil/")
    resultados = Axe().run(pagina_autenticada, options=REGRAS)
    assert resultados.violations_count == 0, (
        f"/perfil/ viola {resultados.violations_count} regra(s) WCAG 2.1 A/AA "
        f"(regra, seletor e trecho do HTML abaixo — corrija o template ou o CSS):\n"
        f"{resultados.generate_report()}"
    )


@pytest.mark.django_db(transaction=True)
def test_perfil_tem_exatamente_um_h1_visivel(pagina_autenticada, live_server):
    pagina_autenticada.goto(f"{live_server.url}/perfil/")
    h1s = [h for h in pagina_autenticada.query_selector_all("h1") if h.is_visible()]
    assert len(h1s) == 1, f"/perfil/ deveria ter exatamente um <h1> visível, e tem {len(h1s)}."


@pytest.mark.django_db(transaction=True)
def test_primeira_tabulacao_alcanca_o_link_de_pular(pagina_autenticada, live_server):
    pagina_autenticada.goto(f"{live_server.url}/perfil/")
    pagina_autenticada.keyboard.press("Tab")
    focado = pagina_autenticada.evaluate("document.activeElement.getAttribute('href')")
    assert focado == "#conteudo", (
        f'Em /perfil/, a primeira tabulação deveria alcançar o link "Pular '
        f'para o conteúdo", e alcançou {focado!r}.'
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("largura", LARGURAS_TESTADAS)
def test_alvos_de_toque_tem_ao_menos_44px(pagina_autenticada, live_server, largura):
    pagina_autenticada.set_viewport_size({"width": largura, "height": 800})
    pagina_autenticada.goto(f"{live_server.url}/perfil/")
    pequenos = []
    for elemento in pagina_autenticada.query_selector_all(INTERATIVOS):
        if not elemento.is_visible():
            continue
        caixa = elemento.bounding_box()
        if caixa and (caixa["width"] < 44 or caixa["height"] < 44):
            pequenos.append(
                f'{elemento.evaluate("e => e.outerHTML.slice(0, 90)")} '
                f'({caixa["width"]:.0f}x{caixa["height"]:.0f})'
            )
    assert (
        not pequenos
    ), f"Alvos menores que 44x44px em /perfil/ a {largura}px de largura:\n" + "\n".join(pequenos)


@pytest.mark.django_db(transaction=True)
def test_sem_rolagem_horizontal_em_360px(pagina_autenticada, live_server):
    pagina_autenticada.set_viewport_size({"width": 360, "height": 800})
    pagina_autenticada.goto(f"{live_server.url}/perfil/")
    largura_conteudo = pagina_autenticada.evaluate("document.documentElement.scrollWidth")
    largura_janela = pagina_autenticada.evaluate("document.documentElement.clientWidth")
    assert largura_conteudo <= largura_janela + 1, (
        f"/perfil/ rola horizontalmente a 360px: conteúdo {largura_conteudo}px "
        f"em janela de {largura_janela}px."
    )
