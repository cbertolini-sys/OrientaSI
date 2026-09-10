import pytest
from django.db import IntegrityError, transaction

from apps.contas.models import Area, PerfilProfessor, Usuario
from apps.projetos.models import LimiteOrientacao, Projeto, Tema


@pytest.fixture
def professor(db):
    usuario = Usuario.objects.create_user(
        email="orientador@ufsm.br", password="x", nome_completo="Orientador", cpf="52998224725"
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape="1234567")


@pytest.fixture
def area(db):
    return Area.objects.create(nome="Engenharia de Software")


@pytest.fixture
def aluno(db):
    return Usuario.objects.create_user(
        email="aluno@ufsm.br",
        password="x",
        nome_completo="Aluno",
        papel=Usuario.ALUNO,
        cpf="11144477735",
    )


@pytest.fixture
def coordenador(db):
    return Usuario.objects.create_user(
        email="coordenador@ufsm.br",
        password="x",
        nome_completo="Coordenador",
        cpf="16899535009",
        is_coordenador=True,
        is_staff=True,
    )


@pytest.mark.django_db
def test_tema_exige_professor(area):
    with pytest.raises(IntegrityError), transaction.atomic():
        Tema.objects.create(
            professor=None, area=area, titulo="Título", descricao="Descrição do tema."
        )


@pytest.mark.django_db
def test_tema_exige_area(professor):
    with pytest.raises(IntegrityError), transaction.atomic():
        Tema.objects.create(
            professor=professor, area=None, titulo="Título", descricao="Descrição do tema."
        )


@pytest.mark.django_db
def test_projeto_recusa_dois_ativos_do_mesmo_aluno_na_mesma_etapa(aluno, professor):
    Projeto.objects.create(
        aluno=aluno,
        orientador=professor.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=2026,
        periodo=1,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Projeto.objects.create(
            aluno=aluno,
            orientador=professor.usuario,
            etapa=Projeto.TCC_I,
            status=Projeto.EM_ANDAMENTO,
            ano=2026,
            periodo=1,
        )


@pytest.mark.django_db
def test_projeto_concluido_nao_bloqueia_um_novo_ativo_na_mesma_etapa(aluno, professor):
    """A trava é sobre projeto ATIVO, não sobre o par (aluno, etapa) para sempre:
    um TCC I concluído não pode impedir que o aluno inicie outro (ex.: reprovado
    numa etapa anterior e reiniciando). Sem esta cobertura, uma trava implementada
    como UniqueConstraint incondicional passaria despercebida no teste acima."""
    Projeto.objects.create(
        aluno=aluno,
        orientador=professor.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.CONCLUIDO,
        ano=2025,
        periodo=2,
    )
    Projeto.objects.create(
        aluno=aluno,
        orientador=professor.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=2026,
        periodo=1,
    )
    assert Projeto.objects.filter(aluno=aluno, etapa=Projeto.TCC_I).count() == 2


@pytest.mark.django_db
@pytest.mark.parametrize("limite", [3, 2, 0])
def test_limite_orientacao_recusa_limite_igual_ou_menor_que_tres(professor, coordenador, limite):
    with pytest.raises(IntegrityError), transaction.atomic():
        LimiteOrientacao.objects.create(
            professor=professor,
            etapa=Projeto.TCC_I,
            ano=2026,
            periodo=1,
            limite=limite,
            justificativa="Justificativa qualquer.",
            autorizado_por=coordenador,
        )


@pytest.mark.django_db
def test_limite_orientacao_recusa_duplicata_de_professor_etapa_ano_e_periodo(
    professor, coordenador
):
    LimiteOrientacao.objects.create(
        professor=professor,
        etapa=Projeto.TCC_I,
        ano=2026,
        periodo=1,
        limite=4,
        justificativa="Primeira concessão.",
        autorizado_por=coordenador,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        LimiteOrientacao.objects.create(
            professor=professor,
            etapa=Projeto.TCC_I,
            ano=2026,
            periodo=1,
            limite=5,
            justificativa="Segunda concessão, mesma chave.",
            autorizado_por=coordenador,
        )
