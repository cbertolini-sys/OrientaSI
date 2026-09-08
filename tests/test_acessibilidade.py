"""Suíte que roda axe-core (WCAG 2.1 A/AA) contra cada rota da lista `ROTAS`
do conftest.py. Se uma página regredir aqui, o defeito está no template ou no
CSS — nunca afrouxe as regras ou a asserção para fazer o teste passar."""

import pytest
from axe_playwright_python.sync_playwright import Axe

REGRAS = {"runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21aa"]}}


@pytest.mark.django_db(transaction=True)
def test_pagina_nao_viola_wcag(page, live_server, rota):
    page.goto(f"{live_server.url}{rota}")
    resultados = Axe().run(page, options=REGRAS)
    assert resultados.violations_count == 0, (
        f"{rota} viola {resultados.violations_count} regra(s) WCAG 2.1 A/AA "
        f"(regra, seletor e trecho do HTML abaixo — corrija o template ou o CSS):\n"
        f"{resultados.generate_report()}"
    )
