"""Garante que nenhuma página exija rolagem horizontal na largura mínima
suportada (360px, um dos menores celulares em uso — spec §3, mobile first)."""

import pytest


@pytest.mark.django_db(transaction=True)
def test_sem_rolagem_horizontal_em_360px(page, live_server, rota):
    page.set_viewport_size({"width": 360, "height": 800})
    page.goto(f"{live_server.url}{rota}")
    largura_conteudo = page.evaluate("document.documentElement.scrollWidth")
    largura_janela = page.evaluate("document.documentElement.clientWidth")
    assert largura_conteudo <= largura_janela + 1, (
        f"{rota} rola horizontalmente a 360px: "
        f"conteúdo {largura_conteudo}px em janela de {largura_janela}px."
    )
