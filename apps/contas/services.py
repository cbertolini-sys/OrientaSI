import hashlib
import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.contas import permissions
from apps.contas.models import Convite, Usuario

MSG_SOMENTE_COORDENACAO = "Somente a coordenação envia convites."


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


@transaction.atomic
def convidar(email, papel, por):
    """Cria o convite e enfileira o e-mail. O token em claro só existe no e-mail."""
    permissions.garante(permissions.pode_convidar(por), MSG_SOMENTE_COORDENACAO)

    if papel not in dict(Convite.PAPEIS_CONVIDAVEIS):
        # SUGRAD fica de fora de propósito: a conta do setor é semeada pelo
        # comando `semear_sistema`, nunca convidada (spec §5.5/§5.1).
        raise ValidationError(f"Não é possível convidar alguém como {papel}.")

    email = email.strip().lower()
    if Usuario.objects.filter(email__iexact=email).exists():
        raise ValidationError(f"Já existe uma conta para {email}.")
    convite_ativo = Convite.objects.filter(
        email__iexact=email, usado_em__isnull=True, expira_em__gt=timezone.now()
    ).exists()
    if convite_ativo:
        raise ValidationError(f"Já existe um convite ativo para {email}. Reenvie-o, se preciso.")

    token = secrets.token_urlsafe(32)
    convite = Convite.objects.create(
        email=email,
        papel=papel,
        token_hash=_hash(token),
        criado_por=por,
        expira_em=timezone.now() + timezone.timedelta(days=settings.CONVITE_VALIDADE_DIAS),
    )

    from apps.contas.tasks import enviar_convite

    transaction.on_commit(lambda: enviar_convite.delay(convite.id, token))
    return convite


@transaction.atomic
def reenviar_convite(convite, por):
    """Invalida o convite anterior e emite outro: um link por vez, sempre."""
    permissions.garante(permissions.pode_convidar(por), MSG_SOMENTE_COORDENACAO)
    if convite.usado_em is not None:
        raise ValidationError("Este convite já foi utilizado.")

    # Expira o convite anterior em vez de marcá-lo como usado: usado_em
    # significa "alguém aceitou" (a Tarefa 8 o grava junto com
    # usuario_criado), e este convite não foi aceito, foi substituído.
    # esta_valido() já devolve False para um convite expirado, então isto
    # basta para aposentá-lo sem sujar um campo que outras telas vão ler.
    convite.expira_em = timezone.now()
    convite.save(update_fields=["expira_em"])
    return convidar(convite.email, convite.papel, por=por)
