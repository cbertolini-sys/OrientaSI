import hashlib
import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.contas import permissions
from apps.contas.models import Convite, Usuario


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


@transaction.atomic
def convidar(email, papel, por):
    """Cria o convite e enfileira o e-mail. O token em claro só existe no e-mail."""
    permissions.garante(permissions.pode_convidar(por), "Somente a coordenação envia convites.")

    email = email.strip().lower()
    if Usuario.objects.filter(email=email).exists():
        raise ValidationError(f"Já existe uma conta para {email}.")
    if any(c.esta_valido() for c in Convite.objects.filter(email=email)):
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
    permissions.garante(permissions.pode_convidar(por), "Somente a coordenação envia convites.")
    if convite.usado_em is not None:
        raise ValidationError("Este convite já foi utilizado.")

    # Reutilizamos usado_em para marcar o convite superado: esta_valido() já o
    # trata como inválido assim que usado_em deixa de ser None, e é o único
    # jeito de aposentar este registro sem acrescentar um campo só para isso.
    convite.usado_em = timezone.now()
    convite.save(update_fields=["usado_em"])
    return convidar(convite.email, convite.papel, por=por)
