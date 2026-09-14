import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

logger = logging.getLogger(__name__)


def _link_login():
    return f"{settings.URL_BASE}{reverse('login')}"


@shared_task(bind=True, max_retries=3)
def enviar_agendamento_banca(self, banca_id):
    """Avisa o aluno e cada membro INTERNO da banca (Bloco D, spec §8).
    Dois grupos, `send_mail` separado para cada um (mesmo motivo de
    `apps.projetos.tasks.enviar_esgotamento`: corpos de e-mail diferentes
    por grupo). Membro externo nunca recebe nada — não tem e-mail
    cadastrado (só nome, regra 3 do CLAUDE.md)."""
    from apps.bancas.models import Banca

    banca = (
        Banca.objects.select_related("projeto__aluno")
        .prefetch_related("membros__professor__usuario")
        .get(pk=banca_id)
    )
    aluno = banca.projeto.aluno
    link = _link_login()

    try:
        corpo_aluno = render_to_string(
            "email/banca_agendada_aluno.txt", {"aluno": aluno, "banca": banca, "link": link}
        )
        send_mail(
            subject="OrientaSI — sua banca de defesa foi agendada",
            message=corpo_aluno,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[aluno.email],
        )
    except Exception as erro:  # noqa: BLE001 — repetimos qualquer falha de entrega
        raise self.retry(exc=erro, countdown=60 * 2**self.request.retries) from erro

    for membro in banca.membros.all():
        if membro.professor is None:
            continue
        professor_usuario = membro.professor.usuario
        try:
            corpo_professor = render_to_string(
                "email/banca_agendada_professor.txt",
                {"professor": professor_usuario, "aluno": aluno, "banca": banca, "link": link},
            )
            send_mail(
                subject="OrientaSI — você foi indicado para uma banca de defesa",
                message=corpo_professor,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[professor_usuario.email],
            )
        except Exception as erro:  # noqa: BLE001 — repetimos qualquer falha de entrega
            raise self.retry(exc=erro, countdown=60 * 2**self.request.retries) from erro


@shared_task(bind=True, max_retries=3)
def enviar_item_correcao_criado(self, item_id):
    """Avisa o aluno de que o orientador registrou um novo item de correção
    pós-banca (Bloco F, spec §8 — decisão explícita do usuário: e-mail a
    cada item novo, ao contrário da recomendação de agrupar)."""
    from apps.bancas.models import ItemCorrecao

    item = ItemCorrecao.objects.select_related("projeto__aluno").get(pk=item_id)
    corpo = render_to_string(
        "email/item_correcao_criado.txt",
        {"aluno": item.projeto.aluno, "item": item, "link": _link_login()},
    )
    try:
        send_mail(
            subject="OrientaSI — novo item de correção no seu TCC II",
            message=corpo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[item.projeto.aluno.email],
        )
    except Exception as erro:  # noqa: BLE001 — repetimos qualquer falha de entrega
        raise self.retry(exc=erro, countdown=60 * 2**self.request.retries) from erro
