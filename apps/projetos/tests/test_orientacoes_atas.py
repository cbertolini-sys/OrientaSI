"""Testes de `/orientacoes/` mostrando as ações do Bloco E: Aprovar
(Aprovado com Ressalvas), comentário+Reenviar (Aprovado, ata devolvida)."""

import pytest
from django.utils import timezone

from apps.bancas.models import Banca
from apps.comum.semestre import semestre_vigente
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.documentos import services as documentos_services
from apps.projetos.models import Projeto


def _cpf(indice):
    base = f"{760000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.orientacoesatas.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=_cpf(indice),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"ORIA{indice:03d}")


def _aluno(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"aluno.orientacoesatas.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        papel=Usuario.ALUNO,
        cpf=_cpf(indice),
    )
    PerfilAluno.objects.create(usuario=usuario, matricula=f"2026ORIA{indice:03d}")
    return usuario


@pytest.mark.django_db
def test_orientacoes_mostra_aprovar_para_aprovado_com_ressalvas(client):
    orientador = _professor(1, "Orientador Aprovar Link")
    aluno = _aluno(2, "Aluno Aprovar Link")
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
def test_orientacoes_mostra_reenviar_para_ata_devolvida(client):
    orientador = _professor(3, "Orientador Devolvida Link")
    aluno = _aluno(4, "Aluno Devolvida Link")
    ano, periodo = semestre_vigente()
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.APROVADO,
        ano=ano,
        periodo=periodo,
    )
    Banca.objects.create(
        projeto=projeto,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.REALIZADA,
        nota=8.0,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
    )
    ata = documentos_services.gerar_ata(projeto)
    sugrad = Usuario.objects.create_user(
        email="sugrad.orientacoesatas@ufsm.br",
        password="x",
        nome_completo="SUGRAD",
        papel=Usuario.SUGRAD,
        cpf=None,
    )
    documentos_services.devolver_ata(ata, por=sugrad, comentario="Falta a assinatura.")

    client.force_login(orientador.usuario)
    conteudo = client.get("/orientacoes/").content.decode()
    assert "Falta a assinatura." in conteudo
    assert f"/orientacoes/{ata.pk}/reenviar-sugrad/" in conteudo


@pytest.mark.django_db
def test_base_mostra_link_painel_sugrad_so_para_sugrad(client):
    sugrad = Usuario.objects.create_user(
        email="sugrad.navlink@ufsm.br",
        password="x",
        nome_completo="SUGRAD",
        papel=Usuario.SUGRAD,
        cpf=None,
    )
    client.force_login(sugrad)
    conteudo = client.get("/").content.decode()
    assert 'href="/painel/sugrad/"' in conteudo


@pytest.mark.django_db
def test_base_esconde_link_painel_sugrad_para_professor(client):
    professor = _professor(5, "Professor Sem SUGRAD Link")
    client.force_login(professor.usuario)
    conteudo = client.get("/").content.decode()
    assert 'href="/painel/sugrad/"' not in conteudo
