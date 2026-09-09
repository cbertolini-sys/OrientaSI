import pytest
from django.db import IntegrityError, transaction

from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario


@pytest.fixture
def professora(db):
    return Usuario.objects.create_user(
        email="ana@ufsm.br", password="x", nome_completo="Ana", cpf="52998224725"
    )


@pytest.mark.django_db
def test_perfil_professor_guarda_siape_e_areas(professora):
    ia = Area.objects.create(nome="Inteligência Artificial")
    redes = Area.objects.create(nome="Redes")
    perfil = PerfilProfessor.objects.create(usuario=professora, siape="1234567")
    perfil.areas.set([ia, redes])

    assert professora.perfil_professor.siape == "1234567"
    assert set(professora.perfil_professor.areas.all()) == {ia, redes}


@pytest.mark.django_db
def test_matricula_e_unica():
    """A unicidade é reforçada pelo banco, não pela aplicação: o segundo
    `create` com a mesma matrícula precisa estourar IntegrityError."""
    joao = Usuario.objects.create_user(
        email="joao@ufsm.br",
        password="x",
        nome_completo="João",
        papel=Usuario.ALUNO,
        cpf="52998224725",
    )
    maria = Usuario.objects.create_user(
        email="maria@ufsm.br",
        password="x",
        nome_completo="Maria",
        papel=Usuario.ALUNO,
        cpf="16899535009",
    )
    PerfilAluno.objects.create(usuario=joao, matricula="201910001")

    with pytest.raises(IntegrityError), transaction.atomic():
        PerfilAluno.objects.create(usuario=maria, matricula="201910001")


@pytest.mark.django_db
def test_area_tem_nome_unico():
    Area.objects.create(nome="Redes")
    with pytest.raises(IntegrityError), transaction.atomic():
        Area.objects.create(nome="Redes")
