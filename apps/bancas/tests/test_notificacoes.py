"""Testes de `tasks.enviar_agendamento_banca` (Bloco D, spec §8). Mesmo
padrão de `apps/projetos/tests/test_fila_professor.py`:
`django_capture_on_commit_callbacks` para disparar o `transaction.on_commit`
dentro do teste, e `CELERY_TASK_ALWAYS_EAGER` para a tarefa rodar
sincronamente."""

import pytest
from django.core import mail
from django.utils import timezone

from apps.bancas import services
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto, Submissao


def _cpf(indice):
    base = f"{650000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.notif.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=_cpf(indice),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"NOTIF{indice:03d}")


@pytest.fixture
def cenario(db):
    orientador = _professor(1, "Orientador Notif")
    aluno = Usuario.objects.create_user(
        email="aluno.notif@ufsm.br",
        password="x",
        nome_completo="Aluno Notif",
        papel=Usuario.ALUNO,
        cpf=_cpf(2),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026NOTIF001")
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
    membro_interno = _professor(3, "Membro Interno Notif")
    return {
        "orientador": orientador,
        "aluno": aluno,
        "projeto": projeto,
        "membro_interno": membro_interno,
    }


@pytest.mark.django_db
def test_agendar_banca_notifica_aluno_e_membro_interno(
    settings, django_capture_on_commit_callbacks, cenario
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with django_capture_on_commit_callbacks(execute=True):
        services.agendar_banca(
            cenario["projeto"],
            data_hora=timezone.now(),
            local="Sala 1",
            membros=[
                {"professor": cenario["membro_interno"]},
                {"nome_externo": "Fulano Externo"},
            ],
            por=cenario["orientador"].usuario,
        )
    destinatarios = {destinatario for m in mail.outbox for destinatario in m.to}
    assert cenario["aluno"].email in destinatarios
    assert cenario["membro_interno"].usuario.email in destinatarios
    # Nunca um e-mail para "Fulano Externo" — não tem endereço cadastrado.
    assert len(mail.outbox) == 2


@pytest.mark.django_db
def test_editar_banca_reenvia_notificacao(settings, django_capture_on_commit_callbacks, cenario):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with django_capture_on_commit_callbacks(execute=True):
        banca = services.agendar_banca(
            cenario["projeto"],
            data_hora=timezone.now(),
            local="Sala 1",
            membros=[{"professor": cenario["membro_interno"]}, {"nome_externo": "Fulano"}],
            por=cenario["orientador"].usuario,
        )
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        services.editar_banca(
            banca,
            data_hora=timezone.now() + timezone.timedelta(days=1),
            local="Sala 2",
            membros=[{"professor": cenario["membro_interno"]}, {"nome_externo": "Fulano"}],
            por=cenario["orientador"].usuario,
        )
    assert len(mail.outbox) == 2


@pytest.mark.django_db
def test_cancelar_banca_nao_notifica(settings, django_capture_on_commit_callbacks, cenario):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with django_capture_on_commit_callbacks(execute=True):
        banca = services.agendar_banca(
            cenario["projeto"],
            data_hora=timezone.now(),
            local="Sala 1",
            membros=[{"professor": cenario["membro_interno"]}, {"nome_externo": "Fulano"}],
            por=cenario["orientador"].usuario,
        )
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        services.cancelar_banca(banca, por=cenario["orientador"].usuario)
    assert len(mail.outbox) == 0
