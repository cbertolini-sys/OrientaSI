"""Testes do Bloco F: TCC II. Modelos (`Projeto.anterior`/`coorientador`,
`TermoPublicacao`) nesta primeira parte; serviços nas tarefas seguintes."""

import pytest
from django.db import IntegrityError

from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto, TermoPublicacao


def _cpf(indice):
    """CPF sintético com dígitos verificadores válidos, faixa 800000000+ —
    livre (conferida por grep) para os testes do Bloco F."""
    base = f"{800000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.tccii.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=_cpf(indice),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"TCCII{indice:03d}")


def _aluno(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"aluno.tccii.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        papel=Usuario.ALUNO,
        cpf=_cpf(indice),
    )
    PerfilAluno.objects.create(usuario=usuario, matricula=f"2026TCCII{indice:02d}")
    return usuario


@pytest.fixture
def projeto_tcc_i(db):
    orientador = _professor(1, "Orientador TCC II Modelo")
    aluno = _aluno(2, "Aluno TCC II Modelo")
    return Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.CONCLUIDO,
        ano=2026,
        periodo=1,
    )


@pytest.mark.django_db
def test_projeto_tcc_ii_aponta_para_anterior(projeto_tcc_i):
    tcc_ii = Projeto.objects.create(
        aluno=projeto_tcc_i.aluno,
        orientador=projeto_tcc_i.orientador,
        etapa=Projeto.TCC_II,
        status=Projeto.EM_ANDAMENTO,
        anterior=projeto_tcc_i,
        ano=2026,
        periodo=2,
    )
    assert tcc_ii.anterior_id == projeto_tcc_i.id


@pytest.mark.django_db
def test_projeto_coorientador_recusa_interno_e_externo_juntos(projeto_tcc_i):
    coorientador = _professor(3, "Coorientador Duplo")
    with pytest.raises(IntegrityError):
        Projeto.objects.create(
            aluno=_aluno(4, "Aluno Coorientador Duplo"),
            orientador=projeto_tcc_i.orientador,
            etapa=Projeto.TCC_I,
            status=Projeto.EM_ANDAMENTO,
            coorientador=coorientador,
            coorientador_externo="Fulano Externo",
            ano=2026,
            periodo=1,
        )


@pytest.mark.django_db
def test_projeto_coorientador_aceita_so_um_ou_nenhum(projeto_tcc_i):
    coorientador = _professor(5, "Coorientador Único")
    projeto = Projeto.objects.create(
        aluno=_aluno(6, "Aluno Coorientador Único"),
        orientador=projeto_tcc_i.orientador,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        coorientador=coorientador,
        ano=2026,
        periodo=1,
    )
    assert projeto.coorientador_id == coorientador.id
    assert projeto.coorientador_externo == ""


@pytest.mark.django_db
def test_termo_publicacao_existencia_significa_assinado(projeto_tcc_i):
    termo = TermoPublicacao.objects.create(projeto=projeto_tcc_i)
    assert termo.assinado_em is not None
