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

    # O link fica fora da viewport (deslocado via -translate-y) até receber
    # foco — ver comentário em base.html. Alcançar o link pelo Tab não basta:
    # se a classe que traz o link de volta para a tela ao focar (ex.:
    # focus:translate-y-0) for removida, o href continua sendo alcançado (o
    # teste acima continuaria verde) mas quem navega só por teclado nunca vê
    # onde o foco está — falha de WCAG 2.4.7 (Focus Visible) que nenhum outro
    # teste desta suíte pegaria: test_toque mede a caixa de qualquer forma
    # (dentro ou fora da tela) e o axe não inspeciona estado de foco.
    elemento_focado = page.query_selector(":focus")
    caixa = elemento_focado.bounding_box() if elemento_focado else None
    assert caixa is not None and caixa["x"] >= 0 and caixa["y"] >= 0, (
        f'Em {rota}, o link "Pular para o conteúdo" é alcançado pelo Tab, mas '
        f"não aparece dentro da viewport ao ganhar foco (caixa={caixa}). "
        f"Confira a classe que traz o link de volta para a tela ao focar "
        f"(ex.: focus:translate-y-0) em base.html."
    )
