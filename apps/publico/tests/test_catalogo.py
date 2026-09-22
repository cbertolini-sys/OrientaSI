"""Testes do Bloco G: `catalogo_publico`/`anos_do_catalogo`
(`apps/publico/services.py`)."""

import pytest
from django.utils import timezone

from apps.bancas.models import Banca
from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.documentos.models import Ata, RevisaoSUGRAD
from apps.projetos.models import Projeto, Submissao, Tema, TermoPublicacao
from apps.publico import services


def _cpf(indice):
    base = f"{840000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _projeto_catalogavel(
    indice,
    *,
    area=None,
    ano=2026,
    decidida_em=None,
    com_tema=True,
    com_termo=True,
    etapa=Projeto.TCC_II,
    status=Projeto.CONCLUIDO,
):
    """Monta um `Projeto` diretamente no estado-alvo (não percorre o fluxo
    real de banca→ata→SUGRAD) — mesmo padrão já usado em
    `apps/documentos/tests/test_revisao.py` e `test_notificacoes.py` pra
    fixtures de "TCC II concluído". Os `*_kwargs` permitem cada teste
    desligar exatamente UMA das quatro condições de elegibilidade (spec
    §1) sem duplicar o resto da montagem."""
    orientador = Usuario.objects.create_user(
        email=f"orientador.catalogo.{indice}@ufsm.br",
        password="x",
        nome_completo=f"Orientador Catálogo {indice}",
        cpf=_cpf(indice * 10 + 1),
    )
    perfil_orientador = PerfilProfessor.objects.create(usuario=orientador, siape=f"CAT{indice:03d}")
    tema_area = area or Area.objects.create(nome=f"Área Catálogo {indice}")
    if area is not None:
        perfil_orientador.areas.add(area)
    aluno = Usuario.objects.create_user(
        email=f"aluno.catalogo.{indice}@ufsm.br",
        password="x",
        nome_completo=f"Aluno Catálogo {indice}",
        papel=Usuario.ALUNO,
        cpf=_cpf(indice * 10 + 2),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula=f"2026CAT{indice:03d}")
    tema = None
    if com_tema:
        tema = Tema.objects.create(
            professor=perfil_orientador,
            titulo=f"Título do TCC {indice}",
            descricao=f"Resumo do TCC {indice}.",
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
        pdf=f"submissoes/catalogo-{indice}.pdf",
        editavel=f"submissoes/catalogo-{indice}.docx",
    )
    if com_termo:
        TermoPublicacao.objects.create(projeto=projeto)
    banca = Banca.objects.create(
        projeto=projeto,
        data_hora=timezone.now(),
        local="Sala Catálogo",
        status=Banca.REALIZADA,
        nota=9.0,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
    )
    ata = Ata.objects.create(
        projeto=projeto, banca=banca, numero=f"{indice:03d}/2026", pdf="atas/catalogo.pdf"
    )
    RevisaoSUGRAD.objects.create(
        ata=ata, status=RevisaoSUGRAD.APROVADA, decidida_em=decidida_em or timezone.now()
    )
    return projeto


@pytest.mark.django_db
def test_catalogo_publico_mostra_tcc_ii_concluido_com_termo_e_tema():
    projeto = _projeto_catalogavel(1)
    assert projeto in services.catalogo_publico()


@pytest.mark.django_db
def test_catalogo_publico_esconde_tcc_i():
    projeto = _projeto_catalogavel(2, etapa=Projeto.TCC_I)
    assert projeto not in services.catalogo_publico()


@pytest.mark.django_db
def test_catalogo_publico_esconde_nao_concluido():
    projeto = _projeto_catalogavel(3, status=Projeto.APROVADO)
    assert projeto not in services.catalogo_publico()


@pytest.mark.django_db
def test_catalogo_publico_esconde_sem_termo():
    projeto = _projeto_catalogavel(4, com_termo=False)
    assert projeto not in services.catalogo_publico()


@pytest.mark.django_db
def test_catalogo_publico_esconde_sem_tema():
    projeto = _projeto_catalogavel(5, com_tema=False)
    assert projeto not in services.catalogo_publico()


@pytest.mark.django_db
def test_catalogo_publico_filtra_por_area():
    area = Area.objects.create(nome="Área Filtro Catálogo")
    outra_area = Area.objects.create(nome="Outra Área Filtro Catálogo")
    projeto_na_area = _projeto_catalogavel(6, area=area)
    projeto_fora = _projeto_catalogavel(7, area=outra_area)
    resultado = services.catalogo_publico(area_id=area.pk)
    assert projeto_na_area in resultado
    assert projeto_fora not in resultado


@pytest.mark.django_db
def test_catalogo_publico_filtra_por_ano():
    projeto_2025 = _projeto_catalogavel(8, ano=2025)
    projeto_2026 = _projeto_catalogavel(9, ano=2026)
    resultado = services.catalogo_publico(ano=2025)
    assert projeto_2025 in resultado
    assert projeto_2026 not in resultado


@pytest.mark.django_db
def test_catalogo_publico_ordena_mais_recente_primeiro():
    antigo = _projeto_catalogavel(10, decidida_em=timezone.now() - timezone.timedelta(days=30))
    recente = _projeto_catalogavel(11, decidida_em=timezone.now())
    resultado = list(services.catalogo_publico())
    assert resultado.index(recente) < resultado.index(antigo)


@pytest.mark.django_db
def test_anos_do_catalogo_lista_anos_distintos_mais_recente_primeiro():
    _projeto_catalogavel(13, ano=2024)
    _projeto_catalogavel(14, ano=2026)
    _projeto_catalogavel(15, ano=2024)
    assert list(services.anos_do_catalogo()) == [2026, 2024]


@pytest.mark.django_db
def test_catalogo_view_mostra_titulo_e_link_de_download(client):
    projeto = _projeto_catalogavel(12)
    resposta = client.get("/catalogo/")
    conteudo = resposta.content.decode()
    assert projeto.tema.titulo in conteudo
    assert projeto.aluno.nome_completo in conteudo


@pytest.mark.django_db
def test_catalogo_view_ignora_querystring_invalida_sem_500(client):
    resposta = client.get("/catalogo/?area=xyz&ano=abc")
    assert resposta.status_code == 200


@pytest.mark.django_db
def test_catalogo_view_sem_login_funciona(client):
    resposta = client.get("/catalogo/")
    assert resposta.status_code == 200


@pytest.mark.django_db
def test_catalogo_view_select_de_area_lista_so_subareas(client):
    """ACHADO da re-auditoria de `apps/publico` (2026-09-22): o `<select>`
    de área listava TODAS as `Area` — inclusive as 4 de topo do CNPq/CAPES
    — mas o filtro (`services.catalogo_publico` → `PerfilProfessor.areas`)
    só casa contra SUBÁREAS, o mesmo predicado que
    `FormularioPerfilProfessor.areas` já usa. Escolher uma área de topo
    devolvia "Nenhum TCC publicado ainda" sempre, por construção. Prova
    por mutação: voltar `views.catalogo` para `Area.objects.order_by("nome")`
    (sem o filtro) faz este teste reprovar — a área de topo apareceria."""
    area_de_topo = Area.objects.create(nome="Área De Topo Teste", area=None)
    Area.objects.create(nome="Subárea Teste", area=area_de_topo)

    resposta = client.get("/catalogo/")
    conteudo = resposta.content.decode()

    assert "Subárea Teste" in conteudo
    assert "Área De Topo Teste" not in conteudo
