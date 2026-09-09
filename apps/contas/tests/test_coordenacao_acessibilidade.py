"""Suíte de acessibilidade do painel da coordenação (T11), que exige
autenticação como coordenador(a) — mesmo padrão de
`apps/contas/tests/test_perfil_acessibilidade.py` (T10), incluindo a âncora
de identidade.

`/painel/` fica de propósito FORA de `ROTAS` (conftest.py), pelo
mesmo motivo de `/perfil/`: é uma rota atrás de `login_required`, e uma
suíte anônima mediria só o redirecionamento para `/contas/login/`.

**Âncora de identidade:** cada teste confirma a URL final e o texto do
`<h1>` logo após o `goto`, antes de qualquer outra asserção — sem isso, a
suíte passaria inteira medindo a tela de login (já provado duas vezes neste
projeto, ver o histórico da T8 e a docstring de test_perfil_acessibilidade.py).

Duas variantes de estado são cobertas, não só a tela em repouso: com todo
<details>/<summary> de confirmação FECHADO (estado inicial da página) e com
um deles ABERTO (depois de um clique real via Playwright) — a confirmação
de promover/revogar só existe dentro desse conteúdo revelado, e uma
violação ali (rótulo, contraste, alvo de toque do botão "Confirmar...")
não apareceria numa varredura que só olhasse o estado fechado.
"""

import pytest
from axe_playwright_python.sync_playwright import Axe
from django.utils import timezone

from apps.contas.models import Convite, Usuario
from conftest import LARGURAS_TESTADAS, REGRAS_AXE, SELETOR_INTERATIVOS

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
    deixaria esta suíte inteira verde medindo `/contas/login/` (mesmo risco
    documentado em test_perfil_acessibilidade.py)."""
    assert page.url.endswith("/painel/"), (
        f"esperava terminar navegação em /painel/, e a URL final foi "
        f"{page.url!r} — provável redirecionamento para o login (autenticação não pegou)."
    )
    assert "Painel da coordenação" in page.inner_text("h1"), (
        f"esperava <h1> com 'Painel da coordenação', e o texto foi " f"{page.inner_text('h1')!r}."
    )


@pytest.mark.django_db(transaction=True)
def test_painel_responde_200_autenticado(pagina_autenticada, live_server):
    resposta = pagina_autenticada.goto(f"{live_server.url}/painel/")
    assert resposta.status == 200
    _confirma_que_esta_no_painel(pagina_autenticada)


@pytest.mark.django_db(transaction=True)
def test_painel_nao_viola_wcag_com_confirmacoes_fechadas(pagina_autenticada, live_server):
    pagina_autenticada.goto(f"{live_server.url}/painel/")
    _confirma_que_esta_no_painel(pagina_autenticada)
    resultados = Axe().run(pagina_autenticada, options=REGRAS_AXE)
    assert resultados.violations_count == 0, (
        f"/painel/ viola {resultados.violations_count} regra(s) WCAG 2.1 A/AA "
        f"(regra, seletor e trecho do HTML abaixo — corrija o template ou o CSS):\n"
        f"{resultados.generate_report()}"
    )


@pytest.mark.django_db(transaction=True)
def test_painel_nao_viola_wcag_com_confirmacao_de_revogar_aberta(pagina_autenticada, live_server):
    """A confirmação de revogar só existe no DOM revelado depois do clique no
    <summary> — uma varredura que só visse o estado fechado nunca chegaria a
    ver o texto de confirmação nem o botão "Confirmar revogação"."""
    pagina_autenticada.goto(f"{live_server.url}/painel/")
    _confirma_que_esta_no_painel(pagina_autenticada)
    pagina_autenticada.click("summary:has-text('Revogar coordenação')")
    resultados = Axe().run(pagina_autenticada, options=REGRAS_AXE)
    assert resultados.violations_count == 0, (
        f"/painel/ (confirmação de revogar aberta) viola "
        f"{resultados.violations_count} regra(s) WCAG 2.1 A/AA:\n"
        f"{resultados.generate_report()}"
    )


@pytest.mark.django_db(transaction=True)
def test_painel_nao_viola_wcag_com_confirmacao_de_promover_aberta(pagina_autenticada, live_server):
    pagina_autenticada.goto(f"{live_server.url}/painel/")
    _confirma_que_esta_no_painel(pagina_autenticada)
    pagina_autenticada.click("summary:has-text('Promover a coordenador')")
    resultados = Axe().run(pagina_autenticada, options=REGRAS_AXE)
    assert resultados.violations_count == 0, (
        f"/painel/ (confirmação de promover aberta) viola "
        f"{resultados.violations_count} regra(s) WCAG 2.1 A/AA:\n"
        f"{resultados.generate_report()}"
    )


@pytest.mark.django_db(transaction=True)
def test_painel_tem_exatamente_um_h1_visivel(pagina_autenticada, live_server):
    pagina_autenticada.goto(f"{live_server.url}/painel/")
    _confirma_que_esta_no_painel(pagina_autenticada)
    h1s = [h for h in pagina_autenticada.query_selector_all("h1") if h.is_visible()]
    assert len(h1s) == 1, f"/painel/ deveria ter exatamente um <h1> visível, e tem {len(h1s)}."


@pytest.mark.django_db(transaction=True)
def test_primeira_tabulacao_alcanca_o_link_de_pular(pagina_autenticada, live_server):
    pagina_autenticada.goto(f"{live_server.url}/painel/")
    _confirma_que_esta_no_painel(pagina_autenticada)
    pagina_autenticada.keyboard.press("Tab")
    focado = pagina_autenticada.evaluate("document.activeElement.getAttribute('href')")
    assert focado == "#conteudo", (
        f'Em /painel/, a primeira tabulação deveria alcançar o link "Pular '
        f'para o conteúdo", e alcançou {focado!r}.'
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("largura", LARGURAS_TESTADAS)
def test_alvos_de_toque_tem_ao_menos_44px(pagina_autenticada, live_server, largura):
    pagina_autenticada.set_viewport_size({"width": largura, "height": 800})
    pagina_autenticada.goto(f"{live_server.url}/painel/")
    _confirma_que_esta_no_painel(pagina_autenticada)
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
    ), f"Alvos menores que 44x44px em /painel/ a {largura}px de largura:\n" + "\n".join(pequenos)


@pytest.mark.django_db(transaction=True)
def test_sem_rolagem_horizontal_em_360px(pagina_autenticada, live_server):
    pagina_autenticada.set_viewport_size({"width": 360, "height": 800})
    pagina_autenticada.goto(f"{live_server.url}/painel/")
    _confirma_que_esta_no_painel(pagina_autenticada)
    largura_conteudo = pagina_autenticada.evaluate("document.documentElement.scrollWidth")
    largura_janela = pagina_autenticada.evaluate("document.documentElement.clientWidth")
    assert largura_conteudo <= largura_janela + 1, (
        f"/painel/ rola horizontalmente a 360px: conteúdo {largura_conteudo}px "
        f"em janela de {largura_janela}px."
    )
