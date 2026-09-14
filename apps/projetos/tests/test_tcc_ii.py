"""Testes do Bloco F: TCC II. Modelos (`Projeto.anterior`/`coorientador`,
`TermoPublicacao`) nesta primeira parte; serviços nas tarefas seguintes."""

import pytest
from django.db import IntegrityError

from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos import services
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


@pytest.mark.django_db
def test_criar_tcc_ii_automatico_copia_aluno_e_orientador(projeto_tcc_i):
    tcc_ii = services.criar_tcc_ii_automatico(projeto_tcc_i)
    assert tcc_ii.aluno_id == projeto_tcc_i.aluno_id
    assert tcc_ii.orientador_id == projeto_tcc_i.orientador_id
    assert tcc_ii.etapa == Projeto.TCC_II
    assert tcc_ii.status == Projeto.EM_ANDAMENTO
    assert tcc_ii.anterior_id == projeto_tcc_i.id


@pytest.mark.django_db
def test_criar_tcc_ii_automatico_copia_coorientador(projeto_tcc_i):
    coorientador = _professor(7, "Coorientador Copiado")
    projeto_tcc_i.coorientador = coorientador
    projeto_tcc_i.save()
    tcc_ii = services.criar_tcc_ii_automatico(projeto_tcc_i)
    assert tcc_ii.coorientador_id == coorientador.id


@pytest.mark.django_db
def test_criar_tcc_ii_automatico_nao_checa_limite_de_vagas(projeto_tcc_i):
    """Mutação obrigatória (spec §3.1): este teste prova a AUSÊNCIA da
    checagem de vaga. Cria 3 outros TCC_II EM_ANDAMENTO para o mesmo
    orientador (o teto padrão) antes de chamar `criar_tcc_ii_automatico` —
    se a função checasse limite, este quarto TCC_II seria recusado."""
    from apps.comum.semestre import semestre_vigente

    ano, periodo = semestre_vigente()
    orientador = projeto_tcc_i.orientador
    for indice in (10, 11, 12):
        Projeto.objects.create(
            aluno=_aluno(indice, f"Aluno Vaga Cheia {indice}"),
            orientador=orientador,
            etapa=Projeto.TCC_II,
            status=Projeto.EM_ANDAMENTO,
            ano=ano,
            periodo=periodo,
        )
    tcc_ii = services.criar_tcc_ii_automatico(projeto_tcc_i)
    assert tcc_ii.pk is not None
