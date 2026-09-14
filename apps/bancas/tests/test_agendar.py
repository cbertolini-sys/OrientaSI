"""Testes de `services.agendar_banca` (Bloco D, spec §5.1)."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.bancas import permissions, services
from apps.bancas.models import Banca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto, Submissao


def _cpf(indice):
    base = f"{610000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.agendar.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=_cpf(indice),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"AGENDAR{indice:03d}")


@pytest.fixture
def orientador(db):
    return _professor(1, "Orientador Agendar")


@pytest.fixture
def dois_professores(db):
    return [_professor(2, "Membro Um"), _professor(3, "Membro Dois")]


@pytest.fixture
def projeto_com_submissao(db, orientador):
    aluno = Usuario.objects.create_user(
        email="aluno.agendar@ufsm.br",
        password="x",
        nome_completo="Aluno Agendar",
        papel=Usuario.ALUNO,
        cpf=_cpf(4),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026AGENDAR1")
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
    return projeto


@pytest.mark.django_db
def test_pode_agendar_banca_e_o_orientador(projeto_com_submissao, orientador):
    assert permissions.pode_agendar_banca(orientador.usuario, projeto_com_submissao)


@pytest.mark.django_db
def test_pode_agendar_banca_recusa_quem_nao_e_o_orientador(projeto_com_submissao):
    outro = Usuario.objects.create_user(
        email="outro.agendar@ufsm.br", password="x", nome_completo="Outro", cpf=_cpf(5)
    )
    assert not permissions.pode_agendar_banca(outro, projeto_com_submissao)


@pytest.mark.django_db
def test_agendar_banca_cria_banca_e_dois_membros(
    projeto_com_submissao, orientador, dois_professores
):
    banca = services.agendar_banca(
        projeto_com_submissao,
        data_hora=timezone.now() + timezone.timedelta(days=7),
        local="Sala 12",
        membros=[{"professor": dois_professores[0]}, {"nome_externo": "Fulano Externo"}],
        por=orientador.usuario,
    )
    assert banca.status == Banca.AGENDADA
    assert banca.membros.count() == 2
    projeto_com_submissao.refresh_from_db()
    assert projeto_com_submissao.status == Projeto.AGUARDANDO_DEFESA


@pytest.mark.django_db
def test_agendar_banca_recusa_quem_nao_e_o_orientador(projeto_com_submissao, dois_professores):
    outro = Usuario.objects.create_user(
        email="outro.agendar2@ufsm.br", password="x", nome_completo="Outro Dois", cpf=_cpf(6)
    )
    with pytest.raises(PermissionDenied):
        services.agendar_banca(
            projeto_com_submissao,
            data_hora=timezone.now(),
            local="Sala 12",
            membros=[{"professor": dois_professores[0]}, {"professor": dois_professores[1]}],
            por=outro,
        )


@pytest.mark.django_db
def test_agendar_banca_recusa_sem_submissao(orientador, dois_professores):
    aluno = Usuario.objects.create_user(
        email="aluno.semsubmissao@ufsm.br",
        password="x",
        nome_completo="Aluno Sem Submissão",
        papel=Usuario.ALUNO,
        cpf=_cpf(7),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026SEMSUB01")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=2026,
        periodo=1,
    )
    with pytest.raises(ValidationError):
        services.agendar_banca(
            projeto,
            data_hora=timezone.now(),
            local="Sala 12",
            membros=[{"professor": dois_professores[0]}, {"professor": dois_professores[1]}],
            por=orientador.usuario,
        )


@pytest.mark.django_db
def test_agendar_banca_recusa_fora_de_em_andamento(
    projeto_com_submissao, orientador, dois_professores
):
    projeto_com_submissao.status = Projeto.AGUARDANDO_DEFESA
    projeto_com_submissao.save()
    with pytest.raises(ValidationError):
        services.agendar_banca(
            projeto_com_submissao,
            data_hora=timezone.now(),
            local="Sala 12",
            membros=[{"professor": dois_professores[0]}, {"professor": dois_professores[1]}],
            por=orientador.usuario,
        )


@pytest.mark.django_db
def test_agendar_banca_recusa_orientador_como_membro(
    projeto_com_submissao, orientador, dois_professores
):
    with pytest.raises(ValidationError):
        services.agendar_banca(
            projeto_com_submissao,
            data_hora=timezone.now(),
            local="Sala 12",
            membros=[{"professor": orientador}, {"professor": dois_professores[0]}],
            por=orientador.usuario,
        )


@pytest.mark.django_db
def test_agendar_banca_recusa_professor_repetido(
    projeto_com_submissao, orientador, dois_professores
):
    with pytest.raises(ValidationError):
        services.agendar_banca(
            projeto_com_submissao,
            data_hora=timezone.now(),
            local="Sala 12",
            membros=[{"professor": dois_professores[0]}, {"professor": dois_professores[0]}],
            por=orientador.usuario,
        )


@pytest.mark.django_db
def test_agendar_banca_recusa_numero_errado_de_membros(
    projeto_com_submissao, orientador, dois_professores
):
    with pytest.raises(ValidationError):
        services.agendar_banca(
            projeto_com_submissao,
            data_hora=timezone.now(),
            local="Sala 12",
            membros=[{"professor": dois_professores[0]}],
            por=orientador.usuario,
        )


@pytest.mark.django_db
def test_anexar_banca_ativa_marca_none_sem_banca(projeto_com_submissao):
    from apps.bancas import services as bancas_services

    projetos = [projeto_com_submissao]
    bancas_services.anexar_banca_ativa(projetos)
    assert projetos[0].banca_ativa is None


@pytest.mark.django_db
def test_anexar_banca_ativa_encontra_a_nao_cancelada(
    projeto_com_submissao, orientador, dois_professores
):
    from apps.bancas import services as bancas_services

    banca = services.agendar_banca(
        projeto_com_submissao,
        data_hora=timezone.now(),
        local="Sala 1",
        membros=[{"professor": dois_professores[0]}, {"professor": dois_professores[1]}],
        por=orientador.usuario,
    )
    projetos = [projeto_com_submissao]
    bancas_services.anexar_banca_ativa(projetos)
    assert projetos[0].banca_ativa.pk == banca.pk


@pytest.mark.django_db
def test_anexar_banca_ativa_sem_query_extra_por_projeto(orientador, dois_professores):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from apps.bancas import services as bancas_services
    from apps.contas.models import PerfilAluno

    def _cria_projeto_com_banca(indice):
        aluno = Usuario.objects.create_user(
            email=f"aluno.anexar.{indice}@ufsm.br",
            password="x",
            nome_completo=f"Aluno Anexar {indice}",
            papel=Usuario.ALUNO,
            cpf=_cpf(10 + indice),
        )
        PerfilAluno.objects.create(usuario=aluno, matricula=f"2026ANEXAR{indice:02d}")
        projeto = Projeto.objects.create(
            aluno=aluno,
            orientador=orientador.usuario,
            etapa=Projeto.TCC_I,
            status=Projeto.EM_ANDAMENTO,
            ano=2026,
            periodo=1,
        )
        Submissao.objects.create(
            projeto=projeto,
            pdf=f"submissoes/{indice}.pdf",
            editavel=f"submissoes/{indice}.docx",
        )
        services.agendar_banca(
            projeto,
            data_hora=timezone.now(),
            local="Sala 1",
            membros=[{"professor": dois_professores[0]}, {"professor": dois_professores[1]}],
            por=orientador.usuario,
        )
        return projeto

    projetos = [_cria_projeto_com_banca(1)]
    with CaptureQueriesContext(connection) as captura:
        bancas_services.anexar_banca_ativa(projetos)
        for p in projetos:
            _ = p.banca_ativa.local if p.banca_ativa else None
    numero_com_um = len(captura.captured_queries)

    projetos = [_cria_projeto_com_banca(2), _cria_projeto_com_banca(3)]
    with CaptureQueriesContext(connection) as captura:
        bancas_services.anexar_banca_ativa(projetos)
        for p in projetos:
            _ = p.banca_ativa.local if p.banca_ativa else None
    assert len(captura.captured_queries) == numero_com_um
