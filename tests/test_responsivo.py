"""Garante que nenhuma página exija rolagem horizontal na largura mínima
suportada (360px, um dos menores celulares em uso — spec §3, mobile first).

Cuidado ao "corrigir" uma falha aqui só com `overflow-x: hidden` no `body`
(ou no `html`): isso apaga o sintoma que este teste mede — o navegador para
de reportar a largura extra em `scrollWidth` — sem encolher o elemento que
realmente estoura. O teste passaria, mas o conteúdo continuaria cortado ou
sobreposto na tela real a 360px. A correção de verdade é sempre no elemento
apontado na mensagem de falha (largura fixa, imagem sem `max-width: 100%`,
`white-space: nowrap` num texto longo etc.), nunca esconder o overflow."""

import pytest


@pytest.mark.django_db(transaction=True)
def test_sem_rolagem_horizontal_em_360px(page, live_server, rota):
    page.set_viewport_size({"width": 360, "height": 800})
    page.goto(f"{live_server.url}{rota}")
    largura_conteudo = page.evaluate("document.documentElement.scrollWidth")
    largura_janela = page.evaluate("document.documentElement.clientWidth")

    if largura_conteudo <= largura_janela + 1:
        return

    # Nomeia quem estoura, não só o quanto: sem isto, uma tela futura com
    # dezenas de blocos vira uma busca manual por tentativa e erro. Reporta
    # os elementos cuja borda direita ultrapassa a janela, do que mais
    # estoura para o que menos estoura.
    culpados = page.evaluate("""
        () => {
            const largura = document.documentElement.clientWidth;
            const candidatos = [];
            document.querySelectorAll('body *').forEach((el) => {
                const r = el.getBoundingClientRect();
                const estourou = r.right - largura;
                if (estourou > 1) {
                    const classe = typeof el.className === 'string' && el.className.trim()
                        ? '.' + el.className.trim().replace(/\\s+/g, '.')
                        : '';
                    const id = el.id ? '#' + el.id : '';
                    candidatos.push({
                        estourou: Math.round(estourou),
                        desc: el.tagName.toLowerCase() + id + classe,
                    });
                }
            });
            candidatos.sort((a, b) => b.estourou - a.estourou);
            return candidatos.slice(0, 5).map(
                (c) => `${c.desc} (estoura ${c.estourou}px à direita)`
            );
        }
        """)
    pytest.fail(
        f"{rota} rola horizontalmente a 360px: conteúdo {largura_conteudo}px em "
        f"janela de {largura_janela}px. Elementos que mais estouram:\n" + "\n".join(culpados)
    )
