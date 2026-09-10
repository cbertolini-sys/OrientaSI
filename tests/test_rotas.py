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
def test_pagina_responde_200_e_tem_o_seletor_esperado(page, rota):
    # `rota` já navegou uma vez (e conferiu a âncora de identidade quando a
    # rota exige autenticação); `page.reload()` repete a navegação para
    # capturar o `Response` e afirmar o status 200 aqui.
    resposta = page.reload()
    assert (
        resposta.status == 200
    ), f"{rota.caminho} deveria responder 200, respondeu {resposta.status}."
    assert page.query_selector(rota.seletor) is not None, (
        f"{rota.caminho} deveria conter o seletor {rota.seletor!r}, que não foi encontrado — "
        "a rota pode estar servindo a página errada (por exemplo, uma 404)."
    )


def test_rota_autenticada_e_medida_autenticada(page, live_server, db):
    """Uma rota com fábrica de usuário não pode acabar medindo a tela de login.

    Este projeto já teve duas vezes o defeito de a suíte passar medindo a página
    errada. A âncora de identidade é o que impede a terceira.
    """
    from conftest import ROTAS

    autenticadas = [r for r in ROTAS if r.fabrica_usuario is not None]
    assert autenticadas, "nenhuma rota autenticada registrada — a generalização não fez efeito"
    for rota in autenticadas:
        assert rota.h1, f"{rota.caminho} não declara o <h1> esperado (âncora de identidade)"
