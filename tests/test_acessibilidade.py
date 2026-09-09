"""Suíte que roda axe-core (WCAG 2.1 A/AA) contra cada rota da lista `ROTAS`
do conftest.py. Se uma página regredir aqui, o defeito está no template ou no
CSS — nunca afrouxe as regras ou a asserção para fazer o teste passar."""

import pytest
from axe_playwright_python.sync_playwright import Axe

from conftest import REGRAS_AXE


@pytest.mark.django_db(transaction=True)
def test_pagina_nao_viola_wcag(page, live_server, rota):
    page.goto(f"{live_server.url}{rota}")
    resultados = Axe().run(page, options=REGRAS_AXE)
    assert resultados.violations_count == 0, (
        f"{rota} viola {resultados.violations_count} regra(s) WCAG 2.1 A/AA "
        f"(regra, seletor e trecho do HTML abaixo — corrija o template ou o CSS):\n"
        f"{resultados.generate_report()}"
    )


@pytest.mark.django_db(transaction=True)
def test_pagina_tem_exatamente_um_h1_visivel(page, live_server, rota):
    """page-has-heading-one, heading-order e empty-heading são regras
    `best-practice` do axe-core — fora das tags wcag2a/wcag2aa/wcag21aa que
    `REGRAS_AXE` declara (a régua global do projeto, em conftest.py, que não
    mexemos aqui). Sem esta asserção própria, remover o <h1> de uma página
    não seria pego por nenhum teste desta suíte."""
    page.goto(f"{live_server.url}{rota}")
    h1s = [h for h in page.query_selector_all("h1") if h.is_visible()]
    assert len(h1s) == 1, (
        f"{rota} deveria ter exatamente um <h1> visível (estrutura de "
        f"cabeçalhos da página), e tem {len(h1s)}."
    )
