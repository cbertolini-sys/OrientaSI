"""Testes de `services.aprovar_ata`/`devolver_ata` (Bloco E, spec §5.2) e
`permissions.pode_revisar_ata` (permissão por PAPEL, não posse — spec §3.5)."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.bancas.models import Banca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.documentos import permissions, services
from apps.documentos.models import RevisaoSUGRAD
from apps.projetos.models import Projeto


def _cpf(indice):
    base = f"{730000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


@pytest.fixture
def sugrad(db):
    return Usuario.objects.create_user(
        email="sugrad.revisao@ufsm.br",
        password="x",
        nome_completo="SUGRAD",
        papel=Usuario.SUGRAD,
        cpf=None,
    )


@pytest.fixture
def ata_pendente(db):
    aluno = Usuario.objects.create_user(
        email="aluno.revisao@ufsm.br",
        password="x",
        nome_completo="Aluno Revisão",
        papel=Usuario.ALUNO,
        cpf=_cpf(1),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026REVISAO1")
    professor = Usuario.objects.create_user(
        email="professor.revisao@ufsm.br",
        password="x",
        nome_completo="Professor Revisão",
        cpf=_cpf(2),
    )
    PerfilProfessor.objects.create(usuario=professor, siape="REVISAO01")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=professor,
        etapa=Projeto.TCC_I,
        status=Projeto.APROVADO,
        ano=2026,
        periodo=1,
    )
    Banca.objects.create(
        projeto=projeto,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.REALIZADA,
        nota=8.0,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
    )
    return services.gerar_ata(projeto)


@pytest.mark.django_db
def test_pode_revisar_ata_e_por_papel_nao_posse(sugrad, ata_pendente):
    assert permissions.pode_revisar_ata(sugrad)
    assert not permissions.pode_revisar_ata(ata_pendente.projeto.orientador)


@pytest.mark.django_db
def test_aprovar_ata_conclui_o_projeto(ata_pendente, sugrad):
    services.aprovar_ata(ata_pendente, por=sugrad)
    ata_pendente.revisao.refresh_from_db()
    assert ata_pendente.revisao.status == RevisaoSUGRAD.APROVADA
    assert ata_pendente.revisao.decidida_em is not None
    ata_pendente.projeto.refresh_from_db()
    assert ata_pendente.projeto.status == Projeto.CONCLUIDO


@pytest.mark.django_db
def test_aprovar_ata_recusa_quem_nao_e_sugrad(ata_pendente):
    with pytest.raises(PermissionDenied):
        services.aprovar_ata(ata_pendente, por=ata_pendente.projeto.orientador)


@pytest.mark.django_db
def test_devolver_ata_grava_comentario_sem_mudar_status_do_projeto(ata_pendente, sugrad):
    services.devolver_ata(ata_pendente, por=sugrad, comentario="Falta assinatura.")
    ata_pendente.revisao.refresh_from_db()
    assert ata_pendente.revisao.status == RevisaoSUGRAD.DEVOLVIDA
    assert ata_pendente.revisao.comentario == "Falta assinatura."
    ata_pendente.projeto.refresh_from_db()
    assert ata_pendente.projeto.status == Projeto.APROVADO


@pytest.mark.django_db
def test_aprovar_ata_recusa_revisar_duas_vezes(ata_pendente, sugrad):
    services.aprovar_ata(ata_pendente, por=sugrad)
    with pytest.raises(ValidationError):
        services.aprovar_ata(ata_pendente, por=sugrad)


@pytest.mark.django_db
def test_reenviar_a_sugrad_volta_para_pendente(ata_pendente, sugrad):
    services.devolver_ata(ata_pendente, por=sugrad, comentario="Corrija a data.")
    services.reenviar_a_sugrad(ata_pendente, por=ata_pendente.projeto.orientador)
    ata_pendente.revisao.refresh_from_db()
    assert ata_pendente.revisao.status == RevisaoSUGRAD.PENDENTE


@pytest.mark.django_db
def test_reenviar_a_sugrad_recusa_quem_nao_e_o_orientador(ata_pendente, sugrad):
    services.devolver_ata(ata_pendente, por=sugrad, comentario="Corrija a data.")
    outro = Usuario.objects.create_user(
        email="outro.reenviar@ufsm.br", password="x", nome_completo="Outro Reenviar", cpf=_cpf(3)
    )
    with pytest.raises(PermissionDenied):
        services.reenviar_a_sugrad(ata_pendente, por=outro)


@pytest.mark.django_db
def test_reenviar_a_sugrad_recusa_fora_de_devolvida(ata_pendente):
    with pytest.raises(ValidationError):
        services.reenviar_a_sugrad(ata_pendente, por=ata_pendente.projeto.orientador)
