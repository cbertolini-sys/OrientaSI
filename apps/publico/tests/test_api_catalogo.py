"""Testes do Bloco H: `/api/v1/catalogo/` (`apps/publico/api_views.py`)."""

import pytest
from django.utils import timezone

from apps.bancas.models import Banca
from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.documentos.models import Ata, RevisaoSUGRAD
from apps.projetos.models import Projeto, Submissao, Tema, TermoPublicacao


def _cpf(indice):
    base = f"{860000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _projeto_catalogavel(
    indice,
    *,
    area=None,
    ano=2026,
    com_tema=True,
    com_termo=True,
    etapa=Projeto.TCC_II,
    status=Projeto.CONCLUIDO,
):
    """Mesma montagem de `apps/publico/tests/test_catalogo.py`
    (`_projeto_catalogavel`, Bloco G) — duplicada aqui com faixa de CPF
    própria (860000000+), mesmo padrão de arquivos de teste deste
    projeto: cada arquivo é autocontido, sem importar helpers de outro."""
    orientador = Usuario.objects.create_user(
        email=f"orientador.apicatalogo.{indice}@ufsm.br",
        password="x",
        nome_completo=f"Orientador API Catálogo {indice}",
        cpf=_cpf(indice * 10 + 1),
    )
    perfil_orientador = PerfilProfessor.objects.create(
        usuario=orientador, siape=f"APICAT{indice:03d}"
    )
    tema_area = area or Area.objects.create(nome=f"Área API Catálogo {indice}")
    if area is not None:
        perfil_orientador.areas.add(area)
    aluno = Usuario.objects.create_user(
        email=f"aluno.apicatalogo.{indice}@ufsm.br",
        password="x",
        nome_completo=f"Aluno API Catálogo {indice}",
        papel=Usuario.ALUNO,
        cpf=_cpf(indice * 10 + 2),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula=f"2026APICAT{indice:03d}")
    tema = None
    if com_tema:
        tema = Tema.objects.create(
            professor=perfil_orientador,
            titulo=f"Título API {indice}",
            descricao=f"Resumo API {indice}.",
        )
        tema.areas.set([tema_area])
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador,
        tema=tema,
        etapa=etapa,
        status=status,
        ano=ano,
        periodo=1,
    )
    Submissao.objects.create(
        projeto=projeto,
        pdf=f"submissoes/apicatalogo-{indice}.pdf",
        editavel=f"submissoes/apicatalogo-{indice}.docx",
    )
    if com_termo:
        TermoPublicacao.objects.create(projeto=projeto)
    banca = Banca.objects.create(
        projeto=projeto,
        data_hora=timezone.now(),
        local="Sala API Catálogo",
        status=Banca.REALIZADA,
        nota=9.0,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
    )
    ata = Ata.objects.create(
        projeto=projeto, banca=banca, numero=f"{indice:03d}/2026", pdf="atas/apicatalogo.pdf"
    )
    RevisaoSUGRAD.objects.create(ata=ata, status=RevisaoSUGRAD.APROVADA, decidida_em=timezone.now())
    return projeto


@pytest.mark.django_db
def test_api_catalogo_lista_projeto_elegivel(client):
    projeto = _projeto_catalogavel(1)
    resposta = client.get("/api/v1/catalogo/")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["count"] == 1
    item = corpo["results"][0]
    assert item["titulo"] == projeto.tema.titulo
    assert item["resumo"] == projeto.tema.descricao
    assert item["autor"] == projeto.aluno.nome_completo
    assert item["orientador"] == projeto.orientador.nome_completo
    assert item["pdf_url"]
    assert set(item.keys()) == {"id", "titulo", "resumo", "autor", "orientador", "pdf_url"}


@pytest.mark.django_db
def test_api_catalogo_esconde_tcc_i(client):
    _projeto_catalogavel(2, etapa=Projeto.TCC_I)
    resposta = client.get("/api/v1/catalogo/")
    assert resposta.json()["count"] == 0


@pytest.mark.django_db
def test_api_catalogo_retrieve_de_projeto_inelegivel_da_404(client):
    projeto = _projeto_catalogavel(3, etapa=Projeto.TCC_I)
    resposta = client.get(f"/api/v1/catalogo/{projeto.pk}/")
    assert resposta.status_code == 404


@pytest.mark.django_db
def test_api_catalogo_retrieve_de_projeto_elegivel_funciona(client):
    projeto = _projeto_catalogavel(4)
    resposta = client.get(f"/api/v1/catalogo/{projeto.pk}/")
    assert resposta.status_code == 200
    assert resposta.json()["id"] == projeto.pk


@pytest.mark.django_db
def test_api_catalogo_filtra_por_area(client):
    area = Area.objects.create(nome="Área API Filtro Catálogo")
    outra_area = Area.objects.create(nome="Outra Área API Filtro Catálogo")
    projeto_na_area = _projeto_catalogavel(5, area=area)
    _projeto_catalogavel(6, area=outra_area)
    resposta = client.get(f"/api/v1/catalogo/?area={area.pk}")
    corpo = resposta.json()
    assert corpo["count"] == 1
    assert corpo["results"][0]["id"] == projeto_na_area.pk


@pytest.mark.django_db
def test_api_catalogo_filtra_por_ano(client):
    projeto_2025 = _projeto_catalogavel(7, ano=2025)
    _projeto_catalogavel(8, ano=2026)
    resposta = client.get("/api/v1/catalogo/?ano=2025")
    corpo = resposta.json()
    assert corpo["count"] == 1
    assert corpo["results"][0]["id"] == projeto_2025.pk


@pytest.mark.django_db
def test_api_catalogo_ignora_querystring_invalida_sem_500(client):
    resposta = client.get("/api/v1/catalogo/?area=xyz&ano=abc")
    assert resposta.status_code == 200


@pytest.mark.django_db
def test_api_catalogo_paginado(client):
    _projeto_catalogavel(9)
    resposta = client.get("/api/v1/catalogo/")
    corpo = resposta.json()
    assert set(corpo.keys()) == {"count", "next", "previous", "results"}
