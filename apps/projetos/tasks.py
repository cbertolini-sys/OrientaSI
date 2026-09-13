import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

logger = logging.getLogger(__name__)

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
    """Avisa a coordenação E o aluno de que as opções se esgotaram sem
    aceite (spec §5.2 e §7.3): quem esgotou é precisamente quem precisa de
    alocação manual, e a coordenação é quem tem esse poder — se o estado só
    existisse na tela do aluno, ninguém agiria.

    Dois `send_mail` distintos, não um só com os dois grupos no mesmo `to`:
    o aluno não precisa ver os e-mails de toda a coordenação (nem
    vice-versa) para saber que a candidatura esgotou. E dois TEXTOS
    distintos (rodada de correção 1, Importante 3) — antes desta correção os
    dois grupos recebiam o MESMO corpo, escrito na terceira pessoa para a
    coordenação ("este(a) aluno(a) precisa de alocação manual"), e o aluno
    lia um chamado a uma ação que não era dele. Também usa
    `candidatura.opcoes.count()` em vez do "três" cravado no texto original
    — `registrar_candidatura` aceita 1 a 3 opções, e uma candidatura de 1 ou
    2 opções chegava a dizer "as três opções ... se esgotaram", falso em
    dois dos três casos.

    RESÍDUO CONHECIDO (M9 da rodada de correção 1, não resolvido): os dois
    `send_mail` abaixo têm cada um seu próprio `try/except`, para que uma
    falha no segundo não seja atribuída ao primeiro. Isso NÃO elimina toda
    duplicata possível: se o envio ao aluno tiver sucesso e o envio à
    coordenação falhar, `self.retry` reexecuta a tarefa INTEIRA do zero (é
    assim que o Celery reprocessa uma tarefa) — e o aluno recebe o e-mail de
    novo, apesar de o primeiro envio já ter chegado. Eliminar isso de vez
    exigiria um jeito de a tarefa saber, ao ser reexecutada, que a metade
    "aluno" já foi entregue (um campo de controle em `Candidatura`, por
    exemplo) — maior do que o achado (Menor) pedia; registrado aqui em vez
    de resolvido em silêncio.
    """
    from apps.contas.services import coordenadores
    from apps.projetos.models import Candidatura

    candidatura = Candidatura.objects.select_related("aluno__usuario").get(pk=candidatura_id)
    contexto = {
        "aluno": candidatura.aluno.usuario,
        "link": _link_login(),
        "total_opcoes": candidatura.opcoes.count(),
    }

    try:
        corpo_aluno = render_to_string("email/candidatura_esgotada_aluno.txt", contexto)
        send_mail(
            subject="OrientaSI — sua candidatura de orientação esgotou as opções",
            message=corpo_aluno,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[candidatura.aluno.usuario.email],
        )
    except Exception as erro:  # noqa: BLE001 — repetimos qualquer falha de entrega
        raise self.retry(exc=erro, countdown=60 * 2**self.request.retries) from erro

    # M7 da rodada de correção 1: `coordenadores()` (apps/contas/services.py)
    # conta TAMBÉM coordenadores desativados de propósito — é a origem única
    # do teto de 4 do CLAUDE.md, e alterá-la aqui vazaria essa decisão para
    # fora do lugar que a define. Um coordenador inativo não pode agir sobre
    # o e-mail, então o filtro por `is_active` é feito AQUI, no ponto de
    # envio, não na função compartilhada.
    destinatarios_coordenacao = list(
        coordenadores().filter(is_active=True).values_list("email", flat=True)
    )
    if not destinatarios_coordenacao:
        # M8: sem isso, um sistema sem nenhum coordenador ativo falha em
        # silêncio — a candidatura fica ESGOTADA, o aluno é avisado, e
        # ninguém com poder de agir sequer sabe que precisa agir.
        logger.warning(
            "enviar_esgotamento: candidatura %s esgotou, mas não há coordenador ativo "
            "para notificar.",
            candidatura_id,
        )
        return

    try:
        corpo_coordenacao = render_to_string("email/candidatura_esgotada_coordenacao.txt", contexto)
        send_mail(
            subject="OrientaSI — candidatura sem orientador precisa de alocação manual",
            message=corpo_coordenacao,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=destinatarios_coordenacao,
        )
    except Exception as erro:  # noqa: BLE001 — repetimos qualquer falha de entrega
        raise self.retry(exc=erro, countdown=60 * 2**self.request.retries) from erro
