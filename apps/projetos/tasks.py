from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

# As três notificações do Bloco B (spec §7), seguindo o padrão de
# `apps/contas/tasks.py::enviar_convite`: `render_to_string` de um template
# em templates/email/, `send_mail`, e retentativa com recuo exponencial
# explícito no `countdown` — `retry_backoff` do decorator só vale para
# `autoretry_for`, e aqui o retry é manual (`self.retry(...)` no `except`).
#
# Nenhuma das três aponta para as telas de `/orientacoes/` ou `/candidatura/`
# (T9 e T11) nem para o painel da coordenação (T12): essas rotas não existem
# nesta tarefa. O link é sempre a tela de login (CLAUDE.md, regra 5: "e-mails
# contêm links direcionando para a tela de login/painel"), de onde quem
# recebe o e-mail é redirecionado para o que precisa fazer, uma vez logado.


def _link_login():
    return f"{settings.URL_BASE}{reverse('login')}"


@shared_task(bind=True, max_retries=3)
def enviar_manifestacao(self, opcao_id):
    """Avisa o professor da `OpcaoCandidatura` de que recebeu uma nova
    manifestação de interesse — a opção da vez na cascata (spec §7.1)."""
    from apps.projetos.models import OpcaoCandidatura

    opcao = OpcaoCandidatura.objects.select_related(
        "professor__usuario", "candidatura__aluno__usuario", "tema"
    ).get(pk=opcao_id)
    corpo = render_to_string(
        "email/manifestacao_interesse.txt",
        {
            "opcao": opcao,
            "aluno": opcao.candidatura.aluno.usuario,
            "link": _link_login(),
            "prazo_dias": settings.PRAZO_RESPOSTA_DIAS,
        },
    )
    try:
        send_mail(
            subject="OrientaSI — nova manifestação de interesse em orientação",
            message=corpo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[opcao.professor.usuario.email],
        )
    except Exception as erro:  # noqa: BLE001 — repetimos qualquer falha de entrega
        # Mesmo recuo exponencial de `enviar_convite` (apps/contas/tasks.py).
        raise self.retry(exc=erro, countdown=60 * 2**self.request.retries) from erro


@shared_task(bind=True, max_retries=3)
def enviar_recusa(self, opcao_id):
    """Avisa o aluno de que uma opção foi recusada, com a justificativa —
    obrigatória por spec §6 ("sem ela, a recusa é silêncio com outro nome").
    Chamada por `recusar_opcao` (T9); esta tarefa só entrega o e-mail."""
    from apps.projetos.models import OpcaoCandidatura

    opcao = OpcaoCandidatura.objects.select_related(
        "professor__usuario", "candidatura__aluno__usuario"
    ).get(pk=opcao_id)
    corpo = render_to_string(
        "email/candidatura_recusada.txt",
        {"opcao": opcao, "link": _link_login()},
    )
    try:
        send_mail(
            subject="OrientaSI — sua manifestação de interesse foi recusada",
            message=corpo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[opcao.candidatura.aluno.usuario.email],
        )
    except Exception as erro:  # noqa: BLE001 — repetimos qualquer falha de entrega
        raise self.retry(exc=erro, countdown=60 * 2**self.request.retries) from erro


@shared_task(bind=True, max_retries=3)
def enviar_esgotamento(self, candidatura_id):
    """Avisa a coordenação E o aluno de que as três opções se esgotaram sem
    aceite (spec §5.2 e §7.3): quem esgotou as três é precisamente quem
    precisa de alocação manual, e a coordenação é quem tem esse poder — se o
    estado só existisse na tela do aluno, ninguém agiria.

    Dois `send_mail` distintos, não um só com os dois grupos no mesmo `to`:
    o aluno não precisa ver os e-mails de toda a coordenação (nem
    vice-versa) para saber que a candidatura esgotou.
    """
    from apps.contas.services import coordenadores
    from apps.projetos.models import Candidatura

    candidatura = Candidatura.objects.select_related("aluno__usuario").get(pk=candidatura_id)
    corpo = render_to_string(
        "email/candidatura_esgotada.txt",
        {"aluno": candidatura.aluno.usuario, "link": _link_login()},
    )
    destinatarios_coordenacao = list(coordenadores().values_list("email", flat=True))
    try:
        send_mail(
            subject="OrientaSI — sua candidatura de orientação esgotou as três opções",
            message=corpo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[candidatura.aluno.usuario.email],
        )
        if destinatarios_coordenacao:
            send_mail(
                subject="OrientaSI — candidatura sem orientador precisa de alocação manual",
                message=corpo,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=destinatarios_coordenacao,
            )
    except Exception as erro:  # noqa: BLE001 — repetimos qualquer falha de entrega
        raise self.retry(exc=erro, countdown=60 * 2**self.request.retries) from erro
