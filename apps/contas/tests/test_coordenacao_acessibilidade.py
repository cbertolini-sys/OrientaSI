"""`/painel/` entrou em `ROTAS` (conftest.py) como rota autenticada (T1 do
Bloco B) — a fixture `rota` autentica como coordenador(a) e confirma a âncora
de identidade (URL final + `<h1>` "Painel da coordenação") antes de medir, e
as quatro suítes transversais (`tests/test_acessibilidade.py`, `test_toque.py`,
`test_responsivo.py`, `test_teclado.py`) cobrem `/painel/` como qualquer outra
rota. Os seis corpos de teste que faziam essa mesma cobertura à mão foram
removidos daqui — eram cópias literais das quatro suítes (a de toque, em
particular, era mais estrita que a régua oficial: faltava a isenção de link
inline em prosa de `tests/test_toque.py::_eh_link_inline_em_prosa`).

O que fica aqui é o que a rota genérica de `ROTAS` não cobre: a tela em
repouso só mostra os `<details>/<summary>` de confirmação FECHADOS, e o
conteúdo de confirmação de promover/revogar (rótulo, contraste, alvo de
toque do botão "Confirmar...") só existe no DOM depois de um clique real via
Playwright. Uma varredura que só olhasse o estado fechado nunca chegaria a
ver esse conteúdo — por isso as duas variantes "aberta" continuam como
testes próprios, com sua própria âncora de identidade (mesmo risco de medir
a tela de login por engano, documentado no módulo antes desta revisão).
"""

import pytest
from axe_playwright_python.sync_playwright import Axe
from django.utils import timezone

from apps.contas.models import Convite, Usuario
from conftest import LARGURAS_TESTADAS, REGRAS_AXE

CPFS = ["52998224725", "16899535009", "11144477735", "12345678909", "98765432100"]


@pytest.fixture
def coordenadora(db):
    return Usuario.objects.create_user(
        email="coord-painel@ufsm.br",
        password="senha-bem-forte-123",
        nome_completo="Coordenadora do Painel",
        cpf=CPFS[0],
        is_coordenador=True,
        is_staff=True,
    )


@pytest.fixture
def cenario_do_painel(coordenadora):
    """Povoa o painel com um pouco de cada coisa que ele lista: um segundo
    coordenador (para a seção "Coordenadores" ter mais de uma linha), um
    professor promovível (seção "Promover") e um convite (seção "Convites
    enviados") — sem isso, as três listas ficariam sempre no `{% empty %}`,
    que é o caminho mais pobre para uma varredura de acessibilidade."""
    Usuario.objects.create_user(
        email="segunda-coord@ufsm.br",
        password="x",
        nome_completo="Segunda Coordenadora",
        cpf=CPFS[1],
        is_coordenador=True,
        is_staff=True,
    )
    professor = Usuario.objects.create_user(
        email="promovivel@ufsm.br",
        password="x",
        nome_completo="Professor Promovível",
        cpf=CPFS[2],
    )
    Convite.objects.create(
        email="convidado-painel@ufsm.br",
        papel=Usuario.ALUNO,
        token_hash="0" * 64,
        criado_por=coordenadora,
        expira_em=timezone.now() + timezone.timedelta(days=7),
    )
    return professor


@pytest.fixture
def pagina_autenticada(autentica_no_navegador, coordenadora, cenario_do_painel):
    return autentica_no_navegador(coordenadora)


def _confirma_que_esta_no_painel(page):
    """Âncora de identidade: sem isto, um defeito no cookie de sessão, no
    nome da sessão, no `live_server.url` ou no próprio `login_required`
    deixaria estes dois testes verdes medindo `/contas/login/` — o mesmo
    risco que a fixture `rota` (conftest.py) neutraliza para a rota genérica
    de `/painel/`."""
    assert page.url.endswith("/painel/"), (
        f"esperava terminar navegação em /painel/, e a URL final foi "
        f"{page.url!r} — provável redirecionamento para o login (autenticação não pegou)."
    )
    assert "Painel da coordenação" in page.inner_text("h1"), (
        f"esperava <h1> com 'Painel da coordenação', e o texto foi " f"{page.inner_text('h1')!r}."
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("largura", LARGURAS_TESTADAS)
def test_painel_nao_viola_wcag_com_confirmacao_de_revogar_aberta(
    pagina_autenticada, live_server, largura
):
    """A confirmação de revogar só existe no DOM revelado depois do clique no
    <summary> — uma varredura que só visse o estado fechado nunca chegaria a
    ver o texto de confirmação nem o botão "Confirmar revogação"."""
    pagina_autenticada.set_viewport_size({"width": largura, "height": 800})
    pagina_autenticada.goto(f"{live_server.url}/painel/")
    _confirma_que_esta_no_painel(pagina_autenticada)
    pagina_autenticada.click("summary:has-text('Revogar coordenação')")
    resultados = Axe().run(pagina_autenticada, options=REGRAS_AXE)
    assert resultados.violations_count == 0, (
        f"/painel/ a {largura}px (confirmação de revogar aberta) viola "
        f"{resultados.violations_count} regra(s) WCAG 2.1 A/AA:\n"
        f"{resultados.generate_report()}"
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("largura", LARGURAS_TESTADAS)
def test_painel_nao_viola_wcag_com_confirmacao_de_promover_aberta(
    pagina_autenticada, live_server, largura
):
    pagina_autenticada.set_viewport_size({"width": largura, "height": 800})
    pagina_autenticada.goto(f"{live_server.url}/painel/")
    _confirma_que_esta_no_painel(pagina_autenticada)
    pagina_autenticada.click("summary:has-text('Promover a coordenador')")
    resultados = Axe().run(pagina_autenticada, options=REGRAS_AXE)
    assert resultados.violations_count == 0, (
        f"/painel/ a {largura}px (confirmação de promover aberta) viola "
        f"{resultados.violations_count} regra(s) WCAG 2.1 A/AA:\n"
        f"{resultados.generate_report()}"
    )
