from urllib.parse import urlsplit

from celery import shared_task
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


@shared_task(bind=True, max_retries=3)
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
        # `retry_backoff` do decorator só vale para autoretry_for; com retry()
        # manual, o backoff exponencial precisa vir explícito no countdown.
        raise self.retry(exc=erro, countdown=60 * 2**self.request.retries) from erro


def _contexto_de_recuperacao(usuario):
    """Monta o contexto dos templates de e-mail da recuperação de senha.

    O `PasswordResetForm` do Django monta este contexto dentro da requisição,
    tirando domínio e protocolo de `request.get_host()`/`request.is_secure()`.
    Aqui não há requisição — a tarefa roda no worker —, então os dois saem de
    `settings.URL_BASE`, a mesma origem que o e-mail de convite já usa. É
    também mais correto: `is_secure()` é False atrás de um proxy que termina o
    TLS, e o `{{ protocol }}` do template sairia como `http` num sistema
    servido por HTTPS.
    """
    partes = urlsplit(settings.URL_BASE)
    return {
        "email": usuario.email,
        "user": usuario,
        "uid": urlsafe_base64_encode(force_bytes(usuario.pk)),
        "token": default_token_generator.make_token(usuario),
        "protocol": partes.scheme or "https",
        "domain": partes.netloc,
        "site_name": partes.netloc,
    }


@shared_task(bind=True, max_retries=3)
def enviar_recuperacao_senha(self, usuario_id):
    """Envia o e-mail de recuperação de senha (spec §6 e §7.6).

    Existe porque o fluxo cru do `PasswordResetView` faz o SMTP DENTRO da
    requisição: com o servidor de e-mail lento ou fora do ar, a pessoa recebe
    um 500 em vez da tela "confira seu e-mail", e não há repetição nenhuma. É
    a mesma classe de problema que motivou fazer o convite assíncrono; a
    assimetria não foi decidida, foi esquecida (achado da revisão final).

    O token é gerado AQUI, e não passado como argumento: o
    `default_token_generator` do Django produz um token válido para o usuário
    a qualquer momento, então não é preciso pôr um token de redefinição de
    senha dentro da mensagem no broker (o que seria o mesmo risco assumido
    para o token do convite, registrado na spec §5.5).
    """
    from apps.contas.models import Usuario

    usuario = Usuario.objects.get(pk=usuario_id)
    contexto = _contexto_de_recuperacao(usuario)
    # `password_reset_subject.txt` vem do próprio Django (traduzido para
    # pt-br); o corpo é o template do projeto, em templates/registration/.
    # O strip é exigência do Django: assunto não pode conter quebra de linha.
    assunto = "".join(
        render_to_string("registration/password_reset_subject.txt", contexto).splitlines()
    )
    corpo = render_to_string("registration/password_reset_email.html", contexto)
    try:
        send_mail(
            subject=assunto,
            message=corpo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[usuario.email],
        )
    except Exception as erro:  # noqa: BLE001 — repetimos qualquer falha de entrega
        # Mesmo recuo exponencial de `enviar_convite` (spec §6: "ambas com
        # repetição em recuo exponencial").
        raise self.retry(exc=erro, countdown=60 * 2**self.request.retries) from erro
