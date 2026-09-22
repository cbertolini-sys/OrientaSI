"""Testes de modelo do Bloco D (spec §4): as duas constraints de banco —
`banca_ativa_unica_por_projeto` e `membro_banca_interno_xor_externo` — e o
novo status `CANCELADO` de `Projeto`."""

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.bancas.models import Banca, MembroBanca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto


def _cpf(indice):
    """CPF sintético com dígitos verificadores válidos, faixa 600000000+ —
    livre (conferida por grep) para os testes de `apps/bancas/`."""
    base = f"{600000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


@pytest.fixture
def projeto_aguardando_defesa(db):
    aluno = Usuario.objects.create_user(
        email="aluno.banca.modelo@ufsm.br",
        password="x",
        nome_completo="Aluno Banca Modelo",
        papel=Usuario.ALUNO,
        cpf=_cpf(1),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026BANCA01")
    professor = Usuario.objects.create_user(
        email="professor.banca.modelo@ufsm.br",
        password="x",
        nome_completo="Professor Banca Modelo",
        cpf=_cpf(2),
    )
    PerfilProfessor.objects.create(usuario=professor, siape="BANCA001")
    return Projeto.objects.create(
        aluno=aluno,
        orientador=professor,
        etapa=Projeto.TCC_I,
        status=Projeto.AGUARDANDO_DEFESA,
        ano=2026,
        periodo=1,
    )


@pytest.mark.django_db
def test_banca_ativa_unica_por_projeto_recusa_duas_agendadas(projeto_aguardando_defesa):
    Banca.objects.create(
        projeto=projeto_aguardando_defesa,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.AGENDADA,
    )
    with pytest.raises(IntegrityError):
        Banca.objects.create(
            projeto=projeto_aguardando_defesa,
            data_hora=timezone.now(),
            local="Sala 2",
            status=Banca.AGENDADA,
        )


@pytest.mark.django_db
def test_banca_ativa_unica_por_projeto_permite_cancelada_mais_agendada(
    projeto_aguardando_defesa,
):
    Banca.objects.create(
        projeto=projeto_aguardando_defesa,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.CANCELADA,
    )
    # Não levanta: a cancelada não conta para a restrição.
    nova = Banca.objects.create(
        projeto=projeto_aguardando_defesa,
        data_hora=timezone.now(),
        local="Sala 2",
        status=Banca.AGENDADA,
    )
    assert nova.pk is not None


@pytest.mark.django_db
def test_banca_ativa_unica_por_projeto_permite_realizada_mais_agendada(
    projeto_aguardando_defesa,
):
    """ACHADO C1 da auditoria (2026-09-22): a condição antiga da constraint
    (`~Q(status="CANCELADA")`) também contava uma banca `REALIZADA` como
    ocupando a vaga única, bloqueando para sempre o reagendamento depois de
    `reabrir_projeto` (CLAUDE.md, "Ciclo de Vida", item 6). A condição certa
    trava só contra DUAS `AGENDADA` ao mesmo tempo — `REALIZADA` é
    histórico, não deve bloquear nada."""
    Banca.objects.create(
        projeto=projeto_aguardando_defesa,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.REALIZADA,
        resultado=Projeto.REPROVADO,
    )
    # Não levanta: a realizada não conta para a restrição.
    nova = Banca.objects.create(
        projeto=projeto_aguardando_defesa,
        data_hora=timezone.now(),
        local="Sala 2",
        status=Banca.AGENDADA,
    )
    assert nova.pk is not None


@pytest.mark.django_db
def test_membro_banca_recusa_professor_e_externo_juntos(projeto_aguardando_defesa):
    banca = Banca.objects.create(
        projeto=projeto_aguardando_defesa,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.AGENDADA,
    )
    professor = PerfilProfessor.objects.first()
    with pytest.raises(IntegrityError):
        MembroBanca.objects.create(banca=banca, professor=professor, nome_externo="Fulano")


@pytest.mark.django_db
def test_membro_banca_recusa_nenhum_dos_dois(projeto_aguardando_defesa):
    banca = Banca.objects.create(
        projeto=projeto_aguardando_defesa,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.AGENDADA,
    )
    with pytest.raises(IntegrityError):
        MembroBanca.objects.create(banca=banca)


@pytest.mark.django_db
def test_membro_banca_aceita_so_externo(projeto_aguardando_defesa):
    banca = Banca.objects.create(
        projeto=projeto_aguardando_defesa,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.AGENDADA,
    )
    membro = MembroBanca.objects.create(banca=banca, nome_externo="Fulano de Tal")
    assert membro.professor is None


def test_projeto_tem_status_cancelado():
    assert Projeto.CANCELADO == "CANCELADO"
    assert ("CANCELADO", "Cancelado") in Projeto.STATUS
