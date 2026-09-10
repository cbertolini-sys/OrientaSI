"""Suíte que roda axe-core (WCAG 2.1 A/AA) contra cada rota da lista `ROTAS`
do conftest.py. Se uma página regredir aqui, o defeito está no template ou no
CSS — nunca afrouxe as regras ou a asserção para fazer o teste passar.

`test_pagina_nao_viola_wcag` é parametrizado também por `LARGURAS_TESTADAS`
(achado da revisão 1 da Tarefa 11): antes, o axe só rodava no viewport
padrão do Playwright (~1280px), enquanto `test_toque.py`/`test_responsivo.py`
já fixavam 360px — a régua mobile-first do CLAUDE.md (rolagem horizontal,
alvo de toque) tinha essas duas cobertas a 360px, mas nenhuma varredura de
WCAG cobria esse viewport em NENHUMA página do projeto. Uma violação que só
existe quando um elemento overflow-x:auto realmente estoura (como
scrollable-region-focusable, WCAG 2.1.1) nunca aparecia, porque a 1280px o
conteúdo cabe e o elemento nem chega a rolar de verdade."""

import pytest
from axe_playwright_python.sync_playwright import Axe

from conftest import LARGURAS_TESTADAS, REGRAS_AXE


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("largura", LARGURAS_TESTADAS)
def test_pagina_nao_viola_wcag(page, rota, largura):
    # `rota` já abriu a página (e autenticou, quando a rota exige) — só falta
    # medir na largura pedida. `page.reload()`, não um novo `goto`: a fixture
    # não recarrega sozinha por causa deste teste (ver docstring de `rota`).
    page.set_viewport_size({"width": largura, "height": 800})
    page.reload()
    resultados = Axe().run(page, options=REGRAS_AXE)
    assert resultados.violations_count == 0, (
        f"{rota.caminho} a {largura}px viola {resultados.violations_count} regra(s) WCAG 2.1 A/AA "
        f"(regra, seletor e trecho do HTML abaixo — corrija o template ou o CSS):\n"
        f"{resultados.generate_report()}"
    )


@pytest.mark.django_db(transaction=True)
def test_pagina_tem_exatamente_um_h1_visivel(page, rota):
    """page-has-heading-one, heading-order e empty-heading são regras
    `best-practice` do axe-core — fora das tags wcag2a/wcag2aa/wcag21aa que
    `REGRAS_AXE` declara (a régua global do projeto, em conftest.py, que não
    mexemos aqui). Sem esta asserção própria, remover o <h1> de uma página
    não seria pego por nenhum teste desta suíte."""
    h1s = [h for h in page.query_selector_all("h1") if h.is_visible()]
    assert len(h1s) == 1, (
        f"{rota.caminho} deveria ter exatamente um <h1> visível (estrutura de "
        f"cabeçalhos da página), e tem {len(h1s)}."
    )
