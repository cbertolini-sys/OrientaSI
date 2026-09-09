from django.core.exceptions import PermissionDenied

from apps.contas.models import Usuario


def garante(condicao, mensagem):
    if not condicao:
        raise PermissionDenied(mensagem)


def pode_convidar(usuario):
    return bool(usuario and usuario.is_authenticated and usuario.is_coordenador)


def pode_promover(usuario):
    return pode_convidar(usuario)


def e_sugrad(usuario):
    return bool(usuario and usuario.is_authenticated and usuario.papel == Usuario.SUGRAD)
