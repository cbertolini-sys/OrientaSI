"""Garante que o link "Pular para o conteúdo" (base.html) é sempre o primeiro
elemento alcançado por Tab, em toda página da lista `ROTAS`: quem navega só
por teclado precisa poder pular o cabeçalho antes de qualquer outra coisa."""

import pytest


@pytest.mark.django_db(transaction=True)
def test_primeira_tabulacao_alcanca_o_link_de_pular(page, live_server, rota):
    page.goto(f"{live_server.url}{rota}")
    page.keyboard.press("Tab")
    focado = page.evaluate("document.activeElement.getAttribute('href')")
    assert focado == "#conteudo", (
        f"Em {rota}, a primeira tabulação deveria alcançar o link "
        f'"Pular para o conteúdo", e alcançou {focado!r}.'
    )
