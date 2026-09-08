from pathlib import Path

from django.conf import settings


def test_inicio_responde_com_marcos_semanticos(client):
    html = client.get("/").content.decode()
    assert '<html lang="pt-br"' in html
    assert "<main" in html and 'id="conteudo"' in html
    assert 'tabindex="-1"' in html, (
        "sem tabindex=-1 no <main>, Safari e Chrome rolam até a âncora mas não "
        "movem o foco do teclado para o conteúdo."
    )
    assert "<header" in html and "<nav" in html and "<footer" in html


def test_inicio_sobrescreve_o_titulo_do_bloco(client):
    html = client.get("/").content.decode()
    assert "<title>OrientaSI — Início</title>" in html


def test_base_tem_link_para_pular_o_conteudo(client):
    html = client.get("/").content.decode()
    assert 'href="#conteudo"' in html
    assert "Pular para o conteúdo" in html


def test_base_tem_regiao_de_anuncio_para_o_htmx(client):
    html = client.get("/").content.decode()
    assert 'id="anuncios"' in html
    assert 'aria-live="polite"' in html


def test_nao_carrega_recurso_de_cdn(client):
    html = client.get("/").content.decode()
    for proibido in ["unpkg.com", "cdn.jsdelivr", "cdnjs", "fonts.googleapis"]:
        assert proibido not in html, f"O projeto não carrega CDN, e encontrei {proibido}."


def test_base_nao_vaza_sintaxe_de_template_para_o_html(client):
    """Regressão: {# comentário #} de múltiplas linhas não é comentário válido
    em Django — o parser não reconhece o bloco e imprime o texto cru no HTML.
    Isto já aconteceu uma vez em base.html antes da revisão da Tarefa 4; os
    comentários agora usam {% comment %}...{% endcomment %}, que suporta
    múltiplas linhas de verdade. Nenhum teste anterior pegava a regressão."""
    html = client.get("/").content.decode()
    assert "{#" not in html, "sintaxe de comentário Django vazou para o HTML renderizado."
    assert "{%" not in html, "uma tag de template não foi processada e vazou para o HTML."


def test_css_compilado_existe_e_nao_esta_vazio():
    """Sem CSS gerado, `{% static %}` renderiza um href que dá 404 em silêncio
    (o StaticFilesStorage de dev não valida existência). Se este teste falhar,
    rode `docker compose up -d` (o serviço `tailwind` compila o CSS) ou, fora
    do Docker, `npm run build:css`."""
    caminho = Path(settings.BASE_DIR) / "static" / "css" / "orientasi.css"
    assert caminho.exists(), (
        "static/css/orientasi.css não existe. Rode `docker compose up -d` "
        "(o serviço `tailwind` compila o CSS) ou `npm run build:css`."
    )
    assert caminho.stat().st_size > 0, "static/css/orientasi.css existe mas está vazio."
