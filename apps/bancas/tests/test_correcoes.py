"""Testes do Bloco F: `ItemCorrecao` (modelo nesta primeira parte, serviços
na Tarefa 4)."""

import pytest

from apps.bancas.models import ItemCorrecao
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto


def _cpf(indice):
    base = f"{810000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


@pytest.fixture
def projeto_tcc_ii(db):
    orientador = Usuario.objects.create_user(
        email="professor.correcao.modelo@ufsm.br",
        password="x",
        nome_completo="Professor Correção Modelo",
        cpf=_cpf(1),
    )
    PerfilProfessor.objects.create(usuario=orientador, siape="CORR0001")
    aluno = Usuario.objects.create_user(
        email="aluno.correcao.modelo@ufsm.br",
        password="x",
        nome_completo="Aluno Correção Modelo",
        papel=Usuario.ALUNO,
        cpf=_cpf(2),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026CORR001")
    return Projeto.objects.create(
        aluno=aluno,
        orientador=orientador,
        etapa=Projeto.TCC_II,
        status=Projeto.APROVADO_COM_RESSALVAS,
        ano=2026,
        periodo=1,
    )


@pytest.mark.django_db
def test_item_correcao_nasce_nao_concluido(projeto_tcc_ii):
    item = ItemCorrecao.objects.create(projeto=projeto_tcc_ii, descricao="Ajustar a conclusão.")
    assert item.concluido is False
