"""Trava a lista `ROTAS` do conftest.py na página certa.

Sem este teste, as suítes de acessibilidade, toque, responsividade e teclado
não afirmam status HTTP nem a presença de nenhum conteúdo específico da
página esperada — elas só medem o que quer que o navegador tenha carregado.
Se uma rota quebrar (por exemplo, a fixture `convite_das_rotas` parar de
semear o convite, ou o token do convite mudar sem atualizar `ROTAS`), o
navegador carrega a página de erro (404) no lugar da página esperada, e as
quatro suítes continuam passando — porque a página de erro também tem exatamente
um <h1>, um botão de 44px e o link de pular para o conteúdo. Este teste é o
único desta suíte que de fato confirma que a página certa foi servida.
"""

import pytest


@pytest.mark.django_db(transaction=True)
def test_pagina_responde_200_e_tem_o_seletor_esperado(page, live_server, rota, seletor_da_rota):
    resposta = page.goto(f"{live_server.url}{rota}")
    assert resposta.status == 200, f"{rota} deveria responder 200, respondeu {resposta.status}."
    assert page.query_selector(seletor_da_rota) is not None, (
        f"{rota} deveria conter o seletor {seletor_da_rota!r}, que não foi encontrado — "
        "a rota pode estar servindo a página errada (por exemplo, uma 404)."
    )
