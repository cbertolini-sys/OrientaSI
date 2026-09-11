from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.projetos import permissions, services
from apps.projetos.forms import FormularioTema
from apps.projetos.models import Tema


@login_required
def meus_temas(request):
    """Painel do professor para cadastrar os temas que oferece (T6). O mural
    público que os alunos veem (Tarefa 7) só lista os temas `ativo` deste
    professor.

    A permissão é conferida ANTES de acessar `request.user.perfil_professor`
    (achado herdado de `apps/contas/views.py::perfil`, Fase 1): o papel
    PROFESSOR é o padrão de `create_user`/`create_superuser`, mas nada cria
    `PerfilProfessor` automaticamente, e acessar o perfil sem essa checagem
    levantaria `RelatedObjectDoesNotExist` (500) para quem tem o papel mas
    não o perfil.
    """
    permissions.garante(
        permissions.pode_criar_tema(request.user), "Somente professores cadastram temas."
    )
    professor = request.user.perfil_professor

    if request.method == "POST":
        formulario = FormularioTema(request.POST, professor=professor)
        if formulario.is_valid():
            try:
                services.criar_tema(
                    professor=professor,
                    area=formulario.cleaned_data["area"],
                    titulo=formulario.cleaned_data["titulo"],
                    descricao=formulario.cleaned_data["descricao"],
                    por=request.user,
                )
            except ValidationError as erro:
                formulario.add_error("area", erro.messages[0])
            else:
                messages.success(request, "Tema cadastrado.")
                return redirect("projetos:meus_temas")
    else:
        formulario = FormularioTema(professor=professor)

    return render(
        request,
        "projetos/meus_temas.html",
        {"formulario": formulario, "temas": professor.temas.all()},
    )


@login_required
@require_POST
def desativar_tema(request, tema_id):
    """Desativa um tema do professor autenticado.

    `services.desativar_tema` recusa (`PermissionDenied`, convertido em 403
    pelo Django) quem não é o professor dono do tema — a checagem de
    permissão fica inteira no serviço, esta view só orquestra o lookup e a
    mensagem de resultado."""
    tema = get_object_or_404(Tema, pk=tema_id)
    services.desativar_tema(tema, por=request.user)
    messages.success(request, "Tema desativado.")
    return redirect("projetos:meus_temas")
