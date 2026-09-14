"""Testes de `/orientacoes/` para o Bloco F: exibição de coorientador, e
"Gerenciar correções" (não "Aprovar" direto) para TCC_II em
Aprovado com Ressalvas."""

import pytest

from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto
from apps.projetos.services import semestre_vigente


def _cpf(indice):
    base = f"{830000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.orientacoestccii.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=_cpf(indice),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"ORITCCII{indice:02d}")


def _aluno(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"aluno.orientacoestccii.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        papel=Usuario.ALUNO,
        cpf=_cpf(indice),
    )
    PerfilAluno.objects.create(usuario=usuario, matricula=f"2026ORITCCII{indice:02d}")
    return usuario


@pytest.mark.django_db
def test_orientacoes_mostra_gerenciar_correcoes_para_tcc_ii(client):
    orientador = _professor(1, "Orientador TCC II Link")
    aluno = _aluno(2, "Aluno TCC II Link")
    ano, periodo = semestre_vigente()
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_II,
        status=Projeto.APROVADO_COM_RESSALVAS,
        ano=ano,
        periodo=periodo,
    )
    client.force_login(orientador.usuario)
    conteudo = client.get("/orientacoes/").content.decode()
    assert f"/bancas/{projeto.pk}/correcoes/" in conteudo
    assert f"/orientacoes/{projeto.pk}/aprovar/" not in conteudo


@pytest.mark.django_db
def test_orientacoes_continua_mostrando_aprovar_direto_para_tcc_i(client):
    orientador = _professor(3, "Orientador TCC I Link")
    aluno = _aluno(4, "Aluno TCC I Link")
    ano, periodo = semestre_vigente()
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.APROVADO_COM_RESSALVAS,
        ano=ano,
        periodo=periodo,
    )
    client.force_login(orientador.usuario)
    conteudo = client.get("/orientacoes/").content.decode()
    assert f"/orientacoes/{projeto.pk}/aprovar/" in conteudo


@pytest.mark.django_db
def test_orientacoes_mostra_coorientador_interno(client):
    orientador = _professor(5, "Orientador Coorientador Link")
    coorientador = _professor(6, "Coorientador Link")
    aluno = _aluno(7, "Aluno Coorientador Link")
    ano, periodo = semestre_vigente()
    Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        coorientador=coorientador,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=ano,
        periodo=periodo,
    )
    client.force_login(orientador.usuario)
    conteudo = client.get("/orientacoes/").content.decode()
    assert "Coorientador Link" in conteudo
