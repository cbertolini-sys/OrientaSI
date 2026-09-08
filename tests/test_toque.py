"""Torna permanente a verificação de alvos de toque que a Tarefa 4 fez com
scripts temporários (já removidos). Valores medidos então: input.input 44px,
checkbox/radio 48px, textarea/select acima de 44px — este teste garante que
nenhuma página caia abaixo de 44x44px daqui para frente (spec §3, regra
de acessibilidade WCAG 2.5.5)."""

import pytest

# [tabindex]:not([tabindex="-1"]) exclui alvos de foco puramente programático
# (ex.: <main tabindex="-1">, usado só para mover o foco do teclado após o
# link de pular — nunca um alvo de toque real) mas cobre widgets customizados
# com tabindex="0" (menus, abas, checklists — o formato que as Tarefas 8-11
# vão usar). summary e os role=* cobrem <details>/<summary> e os padrões ARIA
# de menu, aba e checkbox construídos sem elemento nativo.
INTERATIVOS = (
    "a, button, input:not([type=hidden]), select, textarea, summary, "
    "[tabindex]:not([tabindex='-1']), "
    "[role=button], [role=link], [role=checkbox], [role=tab], [role=menuitem]"
)

# Medir só no viewport padrão de testes (1280px) deixava passar um botão que
# encolhe no mobile: alvo de toque é uma exigência de tela pequena, e o
# projeto é mobile-first (spec: "Interface 100% responsiva"). 360px é o
# mesmo mínimo de tela usado por test_responsivo.py.
LARGURAS_TESTADAS = [1280, 360]


def _eh_link_inline_em_prosa(elemento):
    """WCAG 2.5.5 (Target Size) e 2.5.8 (Target Size Minimum) isentam
    explicitamente alvos que ficam *em linha* dentro de uma frase ou bloco de
    texto corrido ("Exception: ... Inline: The target is in a sentence or
    block of text"). Um link do tamanho de uma palavra dentro de um
    parágrafo não é uma falha de tamanho de alvo — inflar seu alvo ao
    tamanho de 44px quebraria a leitura do texto ao redor, e a própria norma
    reconhece isso.

    A isenção aqui é deliberadamente estreita: só <a> cujo ancestral mais
    próximo seja um <p> (ou prosa equivalente). Nenhum outro elemento
    interativo (botão, input, [role=...]) é isento, e um <a> fora de um
    bloco de texto (ex.: um botão estilizado como link, direto num
    <article> ou <nav>) continua sendo medido normalmente.
    """
    tag = elemento.evaluate("e => e.tagName.toLowerCase()")
    if tag != "a":
        return False
    return elemento.evaluate("e => e.closest('p') !== null")


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("largura", LARGURAS_TESTADAS)
def test_alvos_de_toque_tem_ao_menos_44px(page, live_server, rota, largura):
    page.set_viewport_size({"width": largura, "height": 800})
    page.goto(f"{live_server.url}{rota}")
    pequenos = []
    for elemento in page.query_selector_all(INTERATIVOS):
        if not elemento.is_visible():
            continue
        if _eh_link_inline_em_prosa(elemento):
            continue
        caixa = elemento.bounding_box()
        if caixa and (caixa["width"] < 44 or caixa["height"] < 44):
            pequenos.append(
                f'{elemento.evaluate("e => e.outerHTML.slice(0, 90)")} '
                f'({caixa["width"]:.0f}x{caixa["height"]:.0f})'
            )
    assert (
        not pequenos
    ), f"Alvos menores que 44x44px em {rota} a {largura}px de largura:\n" + "\n".join(pequenos)
