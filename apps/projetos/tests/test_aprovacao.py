"""Testes de `services.aprovar_projeto` (Bloco E, spec §5.1) e do filtro
ampliado de `orientandos_atuais` (spec §3.6)."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.comum.semestre import semestre_vigente
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos import services
from apps.projetos.models import Projeto


def _cpf(indice):
    base = f"{710000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.aprovacao.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=_cpf(indice),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"APROV{indice:03d}")


def _aluno(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"aluno.aprovacao.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        papel=Usuario.ALUNO,
        cpf=_cpf(indice),
    )
    PerfilAluno.objects.create(usuario=usuario, matricula=f"2026APROV{indice:02d}")
    return usuario


@pytest.fixture
def orientador(db):
    return _professor(1, "Orientador Aprovação")


@pytest.fixture
def projeto_com_ressalvas(db, orientador):
    ano, periodo = semestre_vigente()
    aluno = _aluno(2, "Aluno Com Ressalvas")
    return Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.APROVADO_COM_RESSALVAS,
        ano=ano,
        periodo=periodo,
    )


@pytest.mark.django_db
def test_aprovar_projeto_muda_status(projeto_com_ressalvas, orientador):
    services.aprovar_projeto(projeto_com_ressalvas, por=orientador.usuario)
    projeto_com_ressalvas.refresh_from_db()
    assert projeto_com_ressalvas.status == Projeto.APROVADO


@pytest.mark.django_db
def test_aprovar_projeto_recusa_quem_nao_e_o_orientador(projeto_com_ressalvas):
    outro = Usuario.objects.create_user(
        email="outro.aprovar@ufsm.br", password="x", nome_completo="Outro Aprovar", cpf=_cpf(3)
    )
    with pytest.raises(PermissionDenied):
        services.aprovar_projeto(projeto_com_ressalvas, por=outro)


@pytest.mark.django_db
def test_aprovar_projeto_recusa_fora_de_aprovado_com_ressalvas(projeto_com_ressalvas, orientador):
    projeto_com_ressalvas.status = Projeto.EM_ANDAMENTO
    projeto_com_ressalvas.save()
    with pytest.raises(ValidationError):
        services.aprovar_projeto(projeto_com_ressalvas, por=orientador.usuario)


@pytest.mark.django_db
def test_orientandos_atuais_inclui_aprovado_com_ressalvas_e_aprovado(orientador):
    ano, periodo = semestre_vigente()
    aluno_ressalvas = _aluno(4, "Aluno Ressalvas Dois")
    Projeto.objects.create(
        aluno=aluno_ressalvas,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.APROVADO_COM_RESSALVAS,
        ano=ano,
        periodo=periodo,
    )
    aluno_aprovado = _aluno(5, "Aluno Aprovado")
    Projeto.objects.create(
        aluno=aluno_aprovado,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.APROVADO,
        ano=ano,
        periodo=periodo,
    )
    resultado = {p.aluno_id for p in services.orientandos_atuais(orientador)}
    assert aluno_ressalvas.id in resultado
    assert aluno_aprovado.id in resultado


@pytest.mark.django_db
def test_orientandos_atuais_exclui_concluido(orientador):
    ano, periodo = semestre_vigente()
    aluno_concluido = _aluno(6, "Aluno Concluído")
    Projeto.objects.create(
        aluno=aluno_concluido,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.CONCLUIDO,
        ano=ano,
        periodo=periodo,
    )
    resultado = {p.aluno_id for p in services.orientandos_atuais(orientador)}
    assert aluno_concluido.id not in resultado
