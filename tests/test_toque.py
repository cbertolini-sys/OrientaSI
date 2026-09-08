"""Torna permanente a verificação de alvos de toque que a Tarefa 4 fez com
scripts temporários (já removidos). Valores medidos então: input.input 44px,
checkbox/radio 48px, textarea/select acima de 44px — este teste garante que
nenhuma página caia abaixo de 44x44px daqui para frente (spec §3, regra
de acessibilidade WCAG 2.5.5)."""

import pytest

INTERATIVOS = "a, button, input:not([type=hidden]), select, textarea, [role=button]"


@pytest.mark.django_db(transaction=True)
def test_alvos_de_toque_tem_ao_menos_44px(page, live_server, rota):
    page.goto(f"{live_server.url}{rota}")
    pequenos = []
    for elemento in page.query_selector_all(INTERATIVOS):
        if not elemento.is_visible():
            continue
        caixa = elemento.bounding_box()
        if caixa and (caixa["width"] < 44 or caixa["height"] < 44):
            pequenos.append(
                f'{elemento.evaluate("e => e.outerHTML.slice(0, 90)")} '
                f'({caixa["width"]:.0f}x{caixa["height"]:.0f})'
            )
    assert not pequenos, f"Alvos menores que 44x44px em {rota}:\n" + "\n".join(pequenos)
