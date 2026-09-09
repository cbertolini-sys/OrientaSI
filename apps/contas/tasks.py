from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse


@shared_task(bind=True, max_retries=3, default_retry_delay=60, retry_backoff=True)
def enviar_convite(self, convite_id, token):
    from apps.contas.models import Convite

    convite = Convite.objects.get(pk=convite_id)
    caminho = reverse("contas:aceitar_convite", kwargs={"token": token})
    corpo = render_to_string(
        "email/convite.txt",
        {
            "convite": convite,
            "link": f"{settings.URL_BASE}{caminho}",
            "validade_dias": settings.CONVITE_VALIDADE_DIAS,
        },
    )
    try:
        send_mail(
            subject="OrientaSI — convite de cadastro",
            message=corpo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[convite.email],
        )
    except Exception as erro:  # noqa: BLE001 — repetimos qualquer falha de entrega
        raise self.retry(exc=erro) from erro
