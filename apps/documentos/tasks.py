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
def enviar_ata_para_sugrad(self, ata_id):
    """Avisa a SUGRAD de que uma ata está pronta para revisão — disparada
    por `gerar_ata` e por `reenviar_a_sugrad` (Bloco E, spec §8). Destinatário:
    a única conta `papel=SUGRAD` ativa (mesmo raciocínio de
    `apps.contas.services.coordenadores`, adaptado a uma conta só)."""
    from apps.contas.models import Usuario
    from apps.documentos.models import Ata

    ata = Ata.objects.select_related("projeto__aluno").get(pk=ata_id)
    sugrad = Usuario.objects.filter(papel=Usuario.SUGRAD, is_active=True).first()
    if sugrad is None:
        # Mesma decisão de `enviar_esgotamento` (Bloco B) quando não há
        # coordenador ativo: registra e não falha a aprovação do projeto.
        logger.warning(
            "enviar_ata_para_sugrad: ata %s pronta, mas não há conta SUGRAD ativa.", ata_id
        )
        return

    corpo = render_to_string("email/ata_para_sugrad.txt", {"ata": ata, "link": _link_login()})
    try:
        send_mail(
            subject="OrientaSI — nova ata para revisão",
            message=corpo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[sugrad.email],
        )
    except Exception as erro:  # noqa: BLE001 — repetimos qualquer falha de entrega
        raise self.retry(exc=erro, countdown=60 * 2**self.request.retries) from erro


@shared_task(bind=True, max_retries=3)
def enviar_devolucao_para_orientador(self, ata_id):
    """Avisa o orientador de que a SUGRAD devolveu a ata, com o comentário
    (Bloco E, spec §8)."""
    from apps.documentos.models import Ata

    ata = Ata.objects.select_related("projeto__orientador", "revisao").get(pk=ata_id)
    orientador = ata.projeto.orientador
    corpo = render_to_string(
        "email/ata_devolvida.txt",
        {
            "ata": ata,
            "orientador": orientador,
            "comentario": ata.revisao.comentario,
            "link": _link_login(),
        },
    )
    try:
        send_mail(
            subject="OrientaSI — a SUGRAD devolveu uma ata",
            message=corpo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[orientador.email],
        )
    except Exception as erro:  # noqa: BLE001 — repetimos qualquer falha de entrega
        raise self.retry(exc=erro, countdown=60 * 2**self.request.retries) from erro
