"""Testes de `tasks.enviar_ata_para_sugrad`/`enviar_devolucao_para_orientador`
(Bloco E, spec §8). Mesmo padrão de `apps/bancas/tests/test_notificacoes.py`:
`django_capture_on_commit_callbacks` + `CELERY_TASK_ALWAYS_EAGER`."""

import pytest
from django.core import mail
from django.utils import timezone

from apps.bancas.models import Banca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.documentos import services
from apps.projetos.models import Projeto


def _cpf(indice):
    base = f"{740000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


@pytest.fixture
def cenario(db):
    sugrad = Usuario.objects.create_user(
        email="sugrad.notif@ufsm.br",
        password="x",
        nome_completo="SUGRAD",
        papel=Usuario.SUGRAD,
        cpf=None,
    )
    aluno = Usuario.objects.create_user(
        email="aluno.notifata@ufsm.br",
        password="x",
        nome_completo="Aluno Notif Ata",
        papel=Usuario.ALUNO,
        cpf=_cpf(1),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026NOTIFATA1")
    orientador = Usuario.objects.create_user(
        email="orientador.notifata@ufsm.br",
        password="x",
        nome_completo="Orientador Notif Ata",
        cpf=_cpf(2),
    )
    PerfilProfessor.objects.create(usuario=orientador, siape="NOTIFATA1")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador,
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
    return {"sugrad": sugrad, "aluno": aluno, "orientador": orientador, "projeto": projeto}


@pytest.fixture
def cenario_tcc_ii(db):
    sugrad = Usuario.objects.create_user(
        email="sugrad.notiftccii@ufsm.br",
        password="x",
        nome_completo="SUGRAD",
        papel=Usuario.SUGRAD,
        cpf=None,
    )
    aluno = Usuario.objects.create_user(
        email="aluno.notiftccii@ufsm.br",
        password="x",
        nome_completo="Aluno Notif TCC II",
        papel=Usuario.ALUNO,
        cpf=_cpf(3),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026NOTIFTCCII1")
    orientador = Usuario.objects.create_user(
        email="orientador.notiftccii@ufsm.br",
        password="x",
        nome_completo="Orientador Notif TCC II",
        cpf=_cpf(4),
    )
    PerfilProfessor.objects.create(usuario=orientador, siape="NOTIFTCCII1")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador,
        etapa=Projeto.TCC_II,
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
    return {"sugrad": sugrad, "aluno": aluno, "orientador": orientador, "projeto": projeto}


@pytest.mark.django_db
def test_gerar_ata_notifica_sugrad(settings, django_capture_on_commit_callbacks, cenario):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with django_capture_on_commit_callbacks(execute=True):
        services.gerar_ata(cenario["projeto"])
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [cenario["sugrad"].email]


@pytest.mark.django_db
def test_devolver_ata_notifica_orientador(settings, django_capture_on_commit_callbacks, cenario):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with django_capture_on_commit_callbacks(execute=True):
        ata = services.gerar_ata(cenario["projeto"])
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        services.devolver_ata(ata, por=cenario["sugrad"], comentario="Falta a assinatura.")
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [cenario["orientador"].email]


@pytest.mark.django_db
def test_reenviar_a_sugrad_notifica_sugrad_de_novo(
    settings, django_capture_on_commit_callbacks, cenario
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with django_capture_on_commit_callbacks(execute=True):
        ata = services.gerar_ata(cenario["projeto"])
    with django_capture_on_commit_callbacks(execute=True):
        services.devolver_ata(ata, por=cenario["sugrad"], comentario="Falta algo.")
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        services.reenviar_a_sugrad(ata, por=cenario["orientador"])
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [cenario["sugrad"].email]


@pytest.mark.django_db
def test_aprovar_ata_de_tcc_ii_nao_notifica(
    settings, django_capture_on_commit_callbacks, cenario_tcc_ii
):
    """Aprovar a ata de um TCC II é o fim da linha — não cria um "TCC III",
    então não há cascata de notificação (Bloco F)."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with django_capture_on_commit_callbacks(execute=True):
        ata = services.gerar_ata(cenario_tcc_ii["projeto"])
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        services.aprovar_ata(ata, por=cenario_tcc_ii["sugrad"])
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_aprovar_ata_de_tcc_i_notifica_criacao_do_tcc_ii(
    settings, django_capture_on_commit_callbacks, cenario
):
    """Aprovar a ata de um TCC I cria o TCC II automaticamente
    (`apps.projetos.services.criar_tcc_ii_automatico`), o que dispara o
    e-mail de aviso ao aluno (Bloco F, spec §8) — diferente do
    comportamento de `aprovar_ata` isolado, que não notifica por si só."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with django_capture_on_commit_callbacks(execute=True):
        ata = services.gerar_ata(cenario["projeto"])
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        services.aprovar_ata(ata, por=cenario["sugrad"])
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [cenario["aluno"].email]
