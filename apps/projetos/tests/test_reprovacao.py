"""Testes dos dois caminhos a partir de `Projeto.REPROVADO` (Bloco D, spec
§3.6) e do filtro ampliado de `orientandos_atuais` (spec §3.7)."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.comum.semestre import semestre_vigente
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos import services
from apps.projetos.models import Projeto


def _cpf(indice):
    base = f"{640000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.reprovacao.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=_cpf(indice),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"REPROV{indice:03d}")


def _aluno(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"aluno.reprovacao.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        papel=Usuario.ALUNO,
        cpf=_cpf(indice),
    )
    PerfilAluno.objects.create(usuario=usuario, matricula=f"2026REPROV{indice:02d}")
    return usuario


@pytest.fixture
def orientador(db):
    return _professor(1, "Orientador Reprovação")


@pytest.fixture
def projeto_reprovado(db, orientador):
    ano, periodo = semestre_vigente()
    aluno = _aluno(2, "Aluno Reprovado")
    return Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.REPROVADO,
        ano=ano,
        periodo=periodo,
    )


@pytest.mark.django_db
def test_reabrir_projeto_volta_para_em_andamento(projeto_reprovado, orientador):
    services.reabrir_projeto(projeto_reprovado, por=orientador.usuario)
    projeto_reprovado.refresh_from_db()
    assert projeto_reprovado.status == Projeto.EM_ANDAMENTO


@pytest.mark.django_db
def test_reabrir_projeto_recusa_quem_nao_e_o_orientador(projeto_reprovado):
    outro = Usuario.objects.create_user(
        email="outro.reabrir@ufsm.br", password="x", nome_completo="Outro Reabrir", cpf=_cpf(3)
    )
    with pytest.raises(PermissionDenied):
        services.reabrir_projeto(projeto_reprovado, por=outro)


@pytest.mark.django_db
def test_reabrir_projeto_recusa_fora_de_reprovado(projeto_reprovado, orientador):
    projeto_reprovado.status = Projeto.EM_ANDAMENTO
    projeto_reprovado.save()
    with pytest.raises(ValidationError):
        services.reabrir_projeto(projeto_reprovado, por=orientador.usuario)


@pytest.mark.django_db
def test_cancelar_projeto_marca_cancelado(projeto_reprovado, orientador):
    services.cancelar_projeto(projeto_reprovado, por=orientador.usuario)
    projeto_reprovado.refresh_from_db()
    assert projeto_reprovado.status == Projeto.CANCELADO


@pytest.mark.django_db
def test_cancelar_projeto_recusa_quem_nao_e_o_orientador(projeto_reprovado):
    outro = Usuario.objects.create_user(
        email="outro.cancelarprojeto@ufsm.br",
        password="x",
        nome_completo="Outro Cancelar Projeto",
        cpf=_cpf(4),
    )
    with pytest.raises(PermissionDenied):
        services.cancelar_projeto(projeto_reprovado, por=outro)


@pytest.mark.django_db
def test_orientandos_atuais_inclui_aguardando_defesa_e_reprovado(orientador):
    ano, periodo = semestre_vigente()
    aluno_aguardando = _aluno(5, "Aluno Aguardando Defesa")
    Projeto.objects.create(
        aluno=aluno_aguardando,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.AGUARDANDO_DEFESA,
        ano=ano,
        periodo=periodo,
    )
    aluno_reprovado = _aluno(6, "Aluno Reprovado Dois")
    Projeto.objects.create(
        aluno=aluno_reprovado,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.REPROVADO,
        ano=ano,
        periodo=periodo,
    )
    resultado = {p.aluno_id for p in services.orientandos_atuais(orientador)}
    assert aluno_aguardando.id in resultado
    assert aluno_reprovado.id in resultado


@pytest.mark.django_db
def test_orientandos_atuais_exclui_cancelado(orientador):
    ano, periodo = semestre_vigente()
    aluno_cancelado = _aluno(7, "Aluno Cancelado")
    Projeto.objects.create(
        aluno=aluno_cancelado,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.CANCELADO,
        ano=ano,
        periodo=periodo,
    )
    resultado = {p.aluno_id for p in services.orientandos_atuais(orientador)}
    assert aluno_cancelado.id not in resultado
