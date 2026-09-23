"""Testes da página pública `/sobre/` — o que o sistema é, os quatro
fluxogramas de papel (Coordenação, Professor, Aluno, SUGRAD) e a ficha
técnica. Pública como o catálogo e o calendário: quem ainda não tem conta
precisa entender o sistema antes de ter uma, e a comunidade externa que só
consulta o catálogo pode nunca ter uma."""

import re

import django
import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_a_pagina_e_publica(client):
    assert client.get(reverse("publico:sobre")).status_code == 200


@pytest.mark.django_db
def test_traz_os_quatro_fluxogramas(client):
    """Coordenação, Professor, Aluno e SUGRAD — os quatro papéis que o
    sistema conhece. O fluxograma da Coordenação não leva modificador de
    classe (é o acento padrão do componente); os outros três levam."""
    conteudo = client.get(reverse("publico:sobre")).content.decode()
    assert 'class="fluxograma"' in conteudo
    for papel in ("professor", "aluno", "sugrad"):
        assert f'class="fluxograma {papel}"' in conteudo


@pytest.mark.django_db
def test_o_link_esta_na_barra_de_navegacao(client):
    conteudo = client.get(reverse("publico:catalogo")).content.decode()
    assert reverse("publico:sobre") in conteudo


@pytest.mark.django_db
def test_a_stack_cita_a_versao_real_do_django(client):
    """Lida do próprio Django, e não de um número escrito à mão — uma
    página pública com a versão errada é pior que uma sem versão nenhuma,
    e ninguém lembra de voltar aqui no dia da atualização. Só maior.menor:
    o patch muda toda hora e não é o que a frase promete."""
    maior_menor = ".".join(django.get_version().split(".")[:2])
    conteudo = client.get(reverse("publico:sobre")).content.decode()
    assert f"Django {maior_menor}" in conteudo


@pytest.mark.django_db
def test_a_stack_cita_a_versao_real_do_python(client):
    """Mesmo motivo do teste do Django, do outro lado da mesma frase."""
    import sys

    conteudo = client.get(reverse("publico:sobre")).content.decode()
    assert f"Python {sys.version_info.major}.{sys.version_info.minor}" in conteudo


@pytest.mark.django_db
def test_a_pagina_credita_a_equipe(client):
    conteudo = client.get(reverse("publico:sobre")).content.decode()
    for nome in ("Cristiano Bertolini", "Evandro Preuss"):
        assert nome in conteudo, nome


@pytest.mark.django_db
def test_as_voltas_do_fluxograma_apontam_para_passos_que_existem(client):
    """"volta ao passo N" é um número escrito à mão sobre uma lista
    numerada pelo `<ol>` — acrescentar ou remover um passo no meio desloca
    todos os seguintes, e a volta passa a apontar para o passo errado, em
    silêncio. Mesmo teste (e mesmo raciocínio) do sistema irmão IntegraSI,
    `apps/catalogo/tests/test_sobre.py`."""
    conteudo = client.get(reverse("publico:sobre")).content.decode()
    for fluxo in re.findall(r'<ol class="fluxograma[^"]*">(.*?)</ol>', conteudo, re.S):
        passos = re.findall(r"<h4>(.*?)</h4>", fluxo, re.S)
        for numero in re.findall(r"volta ao passo (\d+)", fluxo):
            assert 1 <= int(numero) <= len(passos), (
                f"volta ao passo {numero}, mas o fluxo tem {len(passos)} passos"
            )


@pytest.mark.django_db
def test_a_volta_do_professor_aponta_para_o_acompanhamento_do_envio(client):
    """Prova de conteúdo, não só de faixa: a volta do último passo do
    fluxo do Professor precisa apontar para "Acompanha o envio do
    trabalho" — não só para um número dentro do intervalo válido."""
    conteudo = client.get(reverse("publico:sobre")).content.decode()
    inicio = conteudo.index('<ol class="fluxograma professor">')
    fluxo = conteudo[inicio : conteudo.index("</ol>", inicio)]
    passos = re.findall(r"<h4>(.*?)</h4>", fluxo, re.S)
    voltas = re.findall(r"volta ao passo (\d+)", fluxo)
    assert voltas, "o fluxo do professor perdeu a volta"
    for numero in voltas:
        assert "envio do trabalho" in passos[int(numero) - 1].lower()


@pytest.mark.django_db
def test_a_volta_do_aluno_aponta_para_o_envio_do_texto(client):
    conteudo = client.get(reverse("publico:sobre")).content.decode()
    inicio = conteudo.index('<ol class="fluxograma aluno">')
    fluxo = conteudo[inicio : conteudo.index("</ol>", inicio)]
    passos = re.findall(r"<h4>(.*?)</h4>", fluxo, re.S)
    voltas = re.findall(r"volta ao passo (\d+)", fluxo)
    assert voltas, "o fluxo do aluno perdeu a volta"
    for numero in voltas:
        assert "trabalha e envia" in passos[int(numero) - 1].lower()


@pytest.mark.django_db
def test_o_fluxo_da_sugrad_nao_promete_um_tcc_iii(client):
    """CLAUDE.md, Bloco F: aprovar a ata de um TCC II termina o ciclo do
    aluno — nenhum "TCC III" é criado. A página pública não pode prometer
    o oposto."""
    conteudo = client.get(reverse("publico:sobre")).content.decode()
    inicio = conteudo.index('<ol class="fluxograma sugrad">')
    fluxo = conteudo[inicio : conteudo.index("</ol>", inicio)].lower()
    assert 'nenhum "tcc iii" é criado' in fluxo, fluxo
