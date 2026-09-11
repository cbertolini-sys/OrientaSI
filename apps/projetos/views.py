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
                # Não alcançável por ESTA tela hoje: `FormularioTema.area` já
                # restringe o `<select>` às áreas do professor
                # (`professor.areas.all()`), então uma área fora dessa lista
                # é recusada antes, em `ModelChoiceField.to_python`, com a
                # mensagem genérica do Django — nunca chega aqui (verificado
                # rodando o teste, não só lendo o código; ver preocupação nº3
                # do relatório da T6). Este `except` continua sendo a única
                # reação correta se o queryset do widget for afrouxado depois
                # (ex.: um bug que volte a `Area.objects.all()`), então fica.
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


@login_required
def editar_tema(request, tema_id):
    """Edita um tema do professor autenticado (acréscimo de escopo da
    rodada de correção 1 da T6: o spec exige edição em §2 e §6, e nenhuma
    tarefa do plano original a implementava).

    Reaproveita o mesmo formulário (`FormularioTema`) do cadastro, com
    `initial=` para pré-preencher os valores atuais — não duplica o
    formulário.
    """
    tema = get_object_or_404(Tema, pk=tema_id)
    permissions.garante(
        permissions.pode_editar_tema(request.user, tema),
        "Você só pode editar temas que você mesmo cadastrou.",
    )
    professor = tema.professor

    if request.method == "POST":
        formulario = FormularioTema(request.POST, professor=professor)
        if formulario.is_valid():
            try:
                services.editar_tema(
                    tema,
                    area=formulario.cleaned_data["area"],
                    titulo=formulario.cleaned_data["titulo"],
                    descricao=formulario.cleaned_data["descricao"],
                    por=request.user,
                )
            except ValidationError as erro:
                # Mesma ressalva de `meus_temas`: não alcançável por esta
                # tela hoje, porque `FormularioTema.area` já restringe o
                # `<select>` às áreas do professor — fica como a reação
                # correta se essa restrição for afrouxada depois.
                formulario.add_error("area", erro.messages[0])
            else:
                messages.success(request, "Tema atualizado.")
                return redirect("projetos:meus_temas")
    else:
        formulario = FormularioTema(
            initial={"titulo": tema.titulo, "descricao": tema.descricao, "area": tema.area},
            professor=professor,
        )

    return render(request, "projetos/editar_tema.html", {"formulario": formulario, "tema": tema})
