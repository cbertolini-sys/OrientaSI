from django.core.exceptions import PermissionDenied


def garante(condicao, mensagem):
    if not condicao:
        raise PermissionDenied(mensagem)


def pode_criar_tema(usuario):
    """Só quem tem `PerfilProfessor` cadastra temas.

    A checagem é a EXISTÊNCIA do perfil (`hasattr`), não `usuario.papel ==
    Usuario.PROFESSOR`: o papel padrão de
    `Usuario.objects.create_user`/`create_superuser` é PROFESSOR
    (`apps.contas.models.GerenciadorUsuario`), mas nada cria
    `PerfilProfessor` automaticamente — nem o `createsuperuser` que o
    CLAUDE.md manda rodar. Usar `papel` aqui reproduziria, para
    `/temas/meus/`, o mesmo `RelatedObjectDoesNotExist` (500) que
    `apps/contas/views.py::perfil` já teve na Fase 1.
    """
    return bool(usuario and usuario.is_authenticated and hasattr(usuario, "perfil_professor"))
