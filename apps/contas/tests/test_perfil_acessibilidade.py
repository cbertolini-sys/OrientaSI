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
quatro suítes fazem para as rotas anônimas, autenticando antes de navegar
via `autentica_no_navegador` (conftest.py, extraída nesta revisão para que
qualquer rota autenticada futura reuse o mesmo mecanismo).

**Âncora de identidade (achado da revisão 1):** um probe anônimo contra
`/perfil/` mostrou que o Playwright segue o redirecionamento 302 para
`/contas/login/?next=/perfil/` e devolve `status == 200` — e a tela de login
já tem `form`, exatamente um `<h1>` e a primeira tabulação alcança
`#conteudo`. Ou seja: as seis verificações desta suíte passariam **mesmo
medindo a página errada**, exatamente como `tests/test_rotas.py` existe para
evitar na suíte anônima. Por isso `_confirma_que_esta_no_perfil` roda logo
após cada `goto`, antes de qualquer outra asserção: confirma a URL final
(`/perfil/`, não `/contas/login/...`) e o texto do `<h1>` (“Meu perfil”, que
não existe na tela de login). Na variante do professor, exige também um
`<legend>` na página — a tela de login nunca tem um.
"""

import pytest
from axe_playwright_python.sync_playwright import Axe

from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
from conftest import LARGURAS_TESTADAS, REGRAS_AXE, SELETOR_INTERATIVOS


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
def papel_usuario(request):
    return request.param


@pytest.fixture
def usuario_perfil(papel_usuario, db):
    return _cria_professor() if papel_usuario == "professor" else _cria_aluno()


@pytest.fixture
def pagina_autenticada(autentica_no_navegador, usuario_perfil):
    return autentica_no_navegador(usuario_perfil)


def _confirma_que_esta_no_perfil(page, papel_usuario):
    """Âncora de identidade: sem isto, um defeito no cookie de sessão, no
    nome da sessão, no `live_server.url` ou no próprio `login_required`
    deixaria esta suíte inteira verde medindo `/contas/login/` (ver
    docstring do módulo)."""
    assert page.url.endswith("/perfil/"), (
        f"esperava terminar navegação em /perfil/, e a URL final foi {page.url!r} "
        f"— provável redirecionamento para o login (autenticação não pegou)."
    )
    assert "Meu perfil" in page.inner_text(
        "h1"
    ), f"esperava <h1> com 'Meu perfil', e o texto foi {page.inner_text('h1')!r}."
    if papel_usuario == "professor":
        assert page.query_selector("legend") is not None, (
            "variante do professor deveria ter um <legend> (grupo de áreas), "
            "e nenhum foi encontrado — página errada ou fieldset ausente."
        )


@pytest.mark.django_db(transaction=True)
def test_perfil_responde_200_autenticado(pagina_autenticada, live_server, papel_usuario):
    resposta = pagina_autenticada.goto(f"{live_server.url}/perfil/")
    assert resposta.status == 200
    _confirma_que_esta_no_perfil(pagina_autenticada, papel_usuario)


@pytest.mark.django_db(transaction=True)
def test_perfil_nao_viola_wcag(pagina_autenticada, live_server, papel_usuario):
    pagina_autenticada.goto(f"{live_server.url}/perfil/")
    _confirma_que_esta_no_perfil(pagina_autenticada, papel_usuario)
    resultados = Axe().run(pagina_autenticada, options=REGRAS_AXE)
    assert resultados.violations_count == 0, (
        f"/perfil/ viola {resultados.violations_count} regra(s) WCAG 2.1 A/AA "
        f"(regra, seletor e trecho do HTML abaixo — corrija o template ou o CSS):\n"
        f"{resultados.generate_report()}"
    )


@pytest.mark.django_db(transaction=True)
def test_perfil_tem_exatamente_um_h1_visivel(pagina_autenticada, live_server, papel_usuario):
    pagina_autenticada.goto(f"{live_server.url}/perfil/")
    _confirma_que_esta_no_perfil(pagina_autenticada, papel_usuario)
    h1s = [h for h in pagina_autenticada.query_selector_all("h1") if h.is_visible()]
    assert len(h1s) == 1, f"/perfil/ deveria ter exatamente um <h1> visível, e tem {len(h1s)}."


@pytest.mark.django_db(transaction=True)
def test_primeira_tabulacao_alcanca_o_link_de_pular(pagina_autenticada, live_server, papel_usuario):
    pagina_autenticada.goto(f"{live_server.url}/perfil/")
    _confirma_que_esta_no_perfil(pagina_autenticada, papel_usuario)
    pagina_autenticada.keyboard.press("Tab")
    focado = pagina_autenticada.evaluate("document.activeElement.getAttribute('href')")
    assert focado == "#conteudo", (
        f'Em /perfil/, a primeira tabulação deveria alcançar o link "Pular '
        f'para o conteúdo", e alcançou {focado!r}.'
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("largura", LARGURAS_TESTADAS)
def test_alvos_de_toque_tem_ao_menos_44px(pagina_autenticada, live_server, papel_usuario, largura):
    pagina_autenticada.set_viewport_size({"width": largura, "height": 800})
    pagina_autenticada.goto(f"{live_server.url}/perfil/")
    _confirma_que_esta_no_perfil(pagina_autenticada, papel_usuario)
    pequenos = []
    for elemento in pagina_autenticada.query_selector_all(SELETOR_INTERATIVOS):
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
def test_sem_rolagem_horizontal_em_360px(pagina_autenticada, live_server, papel_usuario):
    pagina_autenticada.set_viewport_size({"width": 360, "height": 800})
    pagina_autenticada.goto(f"{live_server.url}/perfil/")
    _confirma_que_esta_no_perfil(pagina_autenticada, papel_usuario)
    largura_conteudo = pagina_autenticada.evaluate("document.documentElement.scrollWidth")
    largura_janela = pagina_autenticada.evaluate("document.documentElement.clientWidth")
    assert largura_conteudo <= largura_janela + 1, (
        f"/perfil/ rola horizontalmente a 360px: conteúdo {largura_conteudo}px "
        f"em janela de {largura_janela}px."
    )
