import pytest


@pytest.mark.django_db
def test_inicio_responde_com_marcos_semanticos(client):
    html = client.get("/").content.decode()
    assert '<html lang="pt-br"' in html
    assert "<main" in html and 'id="conteudo"' in html
    assert "<header" in html and "<nav" in html and "<footer" in html


@pytest.mark.django_db
def test_base_tem_link_para_pular_o_conteudo(client):
    html = client.get("/").content.decode()
    assert 'href="#conteudo"' in html
    assert "Pular para o conteúdo" in html


@pytest.mark.django_db
def test_base_tem_regiao_de_anuncio_para_o_htmx(client):
    html = client.get("/").content.decode()
    assert 'id="anuncios"' in html
    assert 'aria-live="polite"' in html


@pytest.mark.django_db
def test_nao_carrega_recurso_de_cdn(client):
    html = client.get("/").content.decode()
    for proibido in ["unpkg.com", "cdn.jsdelivr", "cdnjs", "fonts.googleapis"]:
        assert proibido not in html, f"O projeto não carrega CDN, e encontrei {proibido}."
