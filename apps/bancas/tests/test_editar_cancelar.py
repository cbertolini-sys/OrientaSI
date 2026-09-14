"""Testes de `services.editar_banca`/`cancelar_banca` (Bloco D, spec §5.1)."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.bancas import services
from apps.bancas.models import Banca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto, Submissao


def _cpf(indice):
    base = f"{620000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.editar.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=_cpf(indice),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"EDITAR{indice:03d}")


@pytest.fixture
def orientador(db):
    return _professor(1, "Orientador Editar")


@pytest.fixture
def dois_professores(db):
    return [_professor(2, "Membro Editar Um"), _professor(3, "Membro Editar Dois")]


@pytest.fixture
def banca_agendada(db, orientador, dois_professores):
    aluno = Usuario.objects.create_user(
        email="aluno.editar@ufsm.br",
        password="x",
        nome_completo="Aluno Editar",
        papel=Usuario.ALUNO,
        cpf=_cpf(4),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026EDITAR01")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=2026,
        periodo=1,
    )
    Submissao.objects.create(
        projeto=projeto, pdf="submissoes/v1.pdf", editavel="submissoes/v1.docx"
    )
    return services.agendar_banca(
        projeto,
        data_hora=timezone.now() + timezone.timedelta(days=7),
        local="Sala 1",
        membros=[{"professor": dois_professores[0]}, {"professor": dois_professores[1]}],
        por=orientador.usuario,
    )


@pytest.mark.django_db
def test_editar_banca_atualiza_dados_e_membros(banca_agendada, orientador, dois_professores):
    nova_data = timezone.now() + timezone.timedelta(days=10)
    services.editar_banca(
        banca_agendada,
        data_hora=nova_data,
        local="Sala 2",
        membros=[{"professor": dois_professores[0]}, {"nome_externo": "Nova Externa"}],
        por=orientador.usuario,
    )
    banca_agendada.refresh_from_db()
    assert banca_agendada.local == "Sala 2"
    assert banca_agendada.membros.count() == 2
    assert banca_agendada.membros.filter(nome_externo="Nova Externa").exists()


@pytest.mark.django_db
def test_editar_banca_recusa_quem_nao_e_o_orientador(banca_agendada, dois_professores):
    outro = Usuario.objects.create_user(
        email="outro.editar@ufsm.br", password="x", nome_completo="Outro Editar", cpf=_cpf(5)
    )
    with pytest.raises(PermissionDenied):
        services.editar_banca(
            banca_agendada,
            data_hora=timezone.now(),
            local="Sala 3",
            membros=[{"professor": dois_professores[0]}, {"professor": dois_professores[1]}],
            por=outro,
        )


@pytest.mark.django_db
def test_editar_banca_recusa_fora_de_agendada(banca_agendada, orientador, dois_professores):
    banca_agendada.status = Banca.CANCELADA
    banca_agendada.save()
    with pytest.raises(ValidationError):
        services.editar_banca(
            banca_agendada,
            data_hora=timezone.now(),
            local="Sala 3",
            membros=[{"professor": dois_professores[0]}, {"professor": dois_professores[1]}],
            por=orientador.usuario,
        )


@pytest.mark.django_db
def test_cancelar_banca_volta_projeto_para_em_andamento(banca_agendada, orientador):
    services.cancelar_banca(banca_agendada, por=orientador.usuario)
    banca_agendada.refresh_from_db()
    assert banca_agendada.status == Banca.CANCELADA
    banca_agendada.projeto.refresh_from_db()
    assert banca_agendada.projeto.status == Projeto.EM_ANDAMENTO


@pytest.mark.django_db
def test_cancelar_banca_recusa_quem_nao_e_o_orientador(banca_agendada):
    outro = Usuario.objects.create_user(
        email="outro.cancelar@ufsm.br", password="x", nome_completo="Outro Cancelar", cpf=_cpf(6)
    )
    with pytest.raises(PermissionDenied):
        services.cancelar_banca(banca_agendada, por=outro)


@pytest.mark.django_db
def test_cancelar_banca_recusa_fora_de_agendada(banca_agendada, orientador):
    banca_agendada.status = Banca.REALIZADA
    banca_agendada.save()
    with pytest.raises(ValidationError):
        services.cancelar_banca(banca_agendada, por=orientador.usuario)
