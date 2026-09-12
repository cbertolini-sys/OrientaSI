"""Testes do mural de temas (T7): `apps/projetos/services.py::temas_do_mural`
e a view `projetos:mural` — a tela onde o aluno vê os temas ativos antes de
se candidatar (a candidatura em si é a T8).

Cobertura pedida pelo Passo 1 do brief: o mural exige autenticação (anônimo é
redirecionado); mostra só temas `ativo=True`; filtra por área; marca quais
professores ainda têm vaga (ambiguidade 1 do ruling do controlador: vaga é
contada em `Projeto.TCC_I`, porque é a etapa com que `criar_projeto_sob_limite`
grava o `Projeto` quando uma candidatura é aceita — spec §3.7, linha 147:
"quando o professor aceita, nasce um `Projeto` com `etapa=TCC_I`"; `Candidatura`
não tem campo `etapa`). Acrescenta a prova de ausência de N+1 (ambiguidade 2):
duas medições, uma com 3 temas/3 professores e outra com 6/6, comparando os
números de consulta entre si — não contra um teto fixo.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.comum.semestre import semestre_vigente
from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
from apps.projetos import services
from apps.projetos.models import Projeto, Tema

# CPFs válidos (dígito verificador de apps/contas/validators.py), gerados
# fora dos já usados pelas demais suítes, para esta não colidir em UNIQUE(cpf).
CPFS = [
    "10000000019",
    "10123456703",
    "10246913495",
    "10370370147",
    "10493826840",
    "10617283583",
    "10740740253",
    "10864196938",
    "10987653628",
    "11111110301",
    "11234567040",
    "11358023786",
]


def _cria_professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.mural{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=CPFS[indice],
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"300000{indice}")


def _cria_aluno(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"aluno.mural{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        papel=Usuario.ALUNO,
        cpf=CPFS[indice],
    )
    PerfilAluno.objects.create(usuario=usuario, matricula=f"20210001{indice:02d}")
    return usuario


def _cria_tema(professor, area, titulo, ativo=True):
    return Tema.objects.create(
        professor=professor,
        area=area,
        titulo=titulo,
        descricao=f"Descrição de {titulo}.",
        ativo=ativo,
    )


def _cria_projeto_tcc1(aluno_usuario, professor):
    """Projeto EM_ANDAMENTO em TCC_I, no semestre vigente — o que
    `vagas_ocupadas`/o mural contam (ambiguidade 1 do ruling)."""
    ano, periodo = semestre_vigente()
    return Projeto.objects.create(
        aluno=aluno_usuario,
        orientador=professor.usuario,
        etapa=Projeto.TCC_I,
        ano=ano,
        periodo=periodo,
    )


@pytest.fixture
def professor(db):
    return _cria_professor(0, "Professor Mural")


@pytest.fixture
def area(db):
    return Area.objects.create(nome="Engenharia de Software")


@pytest.fixture
def outra_area(db):
    return Area.objects.create(nome="Redes")


@pytest.fixture
def aluno(db):
    return _cria_aluno(1, "Aluno Mural")


# --- services.temas_do_mural -------------------------------------------------


@pytest.mark.django_db
def test_temas_do_mural_so_traz_temas_ativos(professor, area):
    professor.areas.add(area)
    ativo = _cria_tema(professor, area, "Tema ativo")
    _cria_tema(professor, area, "Tema inativo", ativo=False)

    resultado = list(services.temas_do_mural())

    assert [t.pk for t in resultado] == [ativo.pk]


@pytest.mark.django_db
def test_temas_do_mural_filtra_por_area(professor, area, outra_area):
    professor.areas.add(area)
    professor.areas.add(outra_area)
    da_area = _cria_tema(professor, area, "Tema da área")
    _cria_tema(professor, outra_area, "Tema de outra área")

    resultado = list(services.temas_do_mural(area=area))

    assert [t.pk for t in resultado] == [da_area.pk]


@pytest.mark.django_db
def test_temas_do_mural_marca_professor_com_vaga(professor, area):
    professor.areas.add(area)
    _cria_tema(professor, area, "Tema com vaga")

    resultado = list(services.temas_do_mural())

    assert len(resultado) == 1
    assert resultado[0].professor_tem_vaga is True


@pytest.mark.django_db
def test_temas_do_mural_marca_professor_sem_vaga_no_limite(professor, area):
    """3 projetos em TCC_I no semestre vigente esgotam o limite padrão
    (`LIMITE_PADRAO_VAGAS = 3`, apps/projetos/services.py) — a mesma
    constante que `criar_projeto_sob_limite` usa."""
    professor.areas.add(area)
    _cria_tema(professor, area, "Tema sem vaga")
    for indice in range(3):
        aluno_usuario = _cria_aluno(2 + indice, f"Aluno Limite {indice}")
        _cria_projeto_tcc1(aluno_usuario, professor)

    resultado = list(services.temas_do_mural())

    assert len(resultado) == 1
    assert resultado[0].professor_tem_vaga is False


@pytest.mark.django_db
def test_temas_do_mural_nao_conta_projeto_de_outro_professor(professor, area):
    """Prova que a anotação é por professor da LINHA, não uma contagem
    global: 3 projetos de OUTRO professor não derrubam a vaga deste."""
    professor.areas.add(area)
    _cria_tema(professor, area, "Tema com vaga")
    outro_professor = _cria_professor(1, "Outro Professor Mural")
    for indice in range(3):
        aluno_usuario = _cria_aluno(2 + indice, f"Aluno Outro {indice}")
        _cria_projeto_tcc1(aluno_usuario, outro_professor)

    resultado = list(services.temas_do_mural())

    assert len(resultado) == 1
    assert resultado[0].professor_tem_vaga is True


@pytest.mark.django_db
def test_temas_do_mural_sem_n_mais_um(django_assert_num_queries):
    """Ambiguidade 2 do ruling: mede o mural com 3 temas de 3 professores,
    depois com 6 de 6, e afirma que o SEGUNDO número de consultas não é
    maior que o primeiro — a comparação entre dois tamanhos, não um teto
    fixo, é o que prova ausência de N+1."""
    for indice in range(3):
        professor = _cria_professor(indice, f"Professor N+1 {indice}")
        area = Area.objects.create(nome=f"Área N+1 {indice}")
        professor.areas.add(area)
        _cria_tema(professor, area, f"Tema N+1 {indice}")

    with CaptureQueriesContext(connection) as captura:
        list(services.temas_do_mural())
    numero_de_consultas_com_tres_temas = len(captura.captured_queries)

    for indice in range(3, 6):
        professor = _cria_professor(indice, f"Professor N+1 {indice}")
        area = Area.objects.create(nome=f"Área N+1 {indice}")
        professor.areas.add(area)
        _cria_tema(professor, area, f"Tema N+1 {indice}")

    with django_assert_num_queries(numero_de_consultas_com_tres_temas):
        list(services.temas_do_mural())


# --- view projetos:mural ------------------------------------------------


@pytest.mark.django_db
def test_mural_exige_autenticacao(client):
    resposta = client.get(reverse("projetos:mural"))
    assert resposta.status_code == 302
    assert resposta.url == f"/contas/login/?next={reverse('projetos:mural')}"


@pytest.mark.django_db
def test_mural_lista_apenas_temas_ativos(client, aluno, professor, area):
    professor.areas.add(area)
    ativo = _cria_tema(professor, area, "Tema Visível no Mural")
    _cria_tema(professor, area, "Tema Escondido do Mural", ativo=False)
    client.force_login(aluno)

    html = client.get(reverse("projetos:mural")).content.decode()

    assert ativo.titulo in html
    assert "Tema Escondido do Mural" not in html


@pytest.mark.django_db
def test_mural_serve_qualquer_papel_autenticado(client, professor, area):
    """A rota é autenticada mas não exclusiva do aluno (Passo 5 do brief):
    um professor logado também consegue abrir o mural."""
    professor.areas.add(area)
    _cria_tema(professor, area, "Tema Visto por Professor")
    client.force_login(professor.usuario)

    resposta = client.get(reverse("projetos:mural"))

    assert resposta.status_code == 200
    assert "Tema Visto por Professor" in resposta.content.decode()


@pytest.mark.django_db
def test_mural_filtra_por_area_pela_tela(client, aluno, professor, area, outra_area):
    professor.areas.add(area)
    professor.areas.add(outra_area)
    da_area = _cria_tema(professor, area, "Tema Filtrado")
    de_outra_area = _cria_tema(professor, outra_area, "Tema de Outra Área")
    client.force_login(aluno)

    html = client.get(reverse("projetos:mural"), {"area": area.pk}).content.decode()

    assert da_area.titulo in html
    assert de_outra_area.titulo not in html


@pytest.mark.django_db
def test_mural_marca_texto_de_vaga_disponivel_e_esgotada(client, aluno, professor, area):
    # `aluno` (índice 1) e `professor` (índice 0) já ocupam CPFS[0] e
    # CPFS[1] — o professor e os alunos extras deste teste começam em 2.
    professor.areas.add(area)
    com_vaga = _cria_tema(professor, area, "Tema Com Vaga")
    outro_professor = _cria_professor(2, "Professor Sem Vaga")
    outro_professor.areas.add(area)
    sem_vaga = _cria_tema(outro_professor, area, "Tema Sem Vaga")
    for indice in range(3):
        aluno_usuario = _cria_aluno(3 + indice, f"Aluno Esgota {indice}")
        _cria_projeto_tcc1(aluno_usuario, outro_professor)
    client.force_login(aluno)

    html = client.get(reverse("projetos:mural")).content.decode()

    assert com_vaga.titulo in html
    assert sem_vaga.titulo in html
    assert "Vaga disponível" in html
    assert "Sem vaga no momento" in html


@pytest.mark.django_db
def test_mural_mostra_estado_vazio_sem_temas(client, aluno):
    client.force_login(aluno)

    html = client.get(reverse("projetos:mural")).content.decode()

    assert "Nenhum tema" in html
