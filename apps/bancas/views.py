from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.bancas import services
from apps.bancas.forms import FormularioBanca, FormularioResultadoBanca
from apps.bancas.models import Banca
from apps.projetos.models import Projeto


@login_required
def agendar(request, projeto_id):
    """Agenda a banca de `projeto_id` (Bloco D, spec §7). Lookup escopado ao
    orientador autenticado — projeto alheio e projeto inexistente respondem
    os dois com 404, mesmo padrão de `editar_tema`/`meu_tcc`."""
    projeto = get_object_or_404(Projeto, pk=projeto_id, orientador=request.user)

    if request.method == "POST":
        formulario = FormularioBanca(request.POST, orientador=request.user)
        if formulario.is_valid():
            try:
                services.agendar_banca(
                    projeto,
                    data_hora=formulario.cleaned_data["data_hora"],
                    local=formulario.cleaned_data["local"],
                    membros=formulario.cleaned_data["membros"],
                    por=request.user,
                )
            except ValidationError as erro:
                formulario.add_error(None, erro.messages[0])
            else:
                messages.success(request, "Banca agendada.")
                return redirect("projetos:orientacoes")
    else:
        formulario = FormularioBanca(orientador=request.user)

    return render(
        request,
        "bancas/formulario.html",
        {"formulario": formulario, "projeto": projeto, "titulo": "Agendar banca"},
    )


@login_required
def editar(request, banca_id):
    """Reagenda uma banca já `AGENDADA` (Bloco D, spec §7). Lookup escopado
    via `projeto__orientador`, mesmo raciocínio de `agendar`."""
    banca = get_object_or_404(Banca, pk=banca_id, projeto__orientador=request.user)

    if request.method == "POST":
        formulario = FormularioBanca(request.POST, orientador=request.user)
        if formulario.is_valid():
            try:
                services.editar_banca(
                    banca,
                    data_hora=formulario.cleaned_data["data_hora"],
                    local=formulario.cleaned_data["local"],
                    membros=formulario.cleaned_data["membros"],
                    por=request.user,
                )
            except ValidationError as erro:
                formulario.add_error(None, erro.messages[0])
            else:
                messages.success(request, "Banca atualizada.")
                return redirect("projetos:orientacoes")
    else:
        formulario = FormularioBanca(
            orientador=request.user,
            initial={"data_hora": banca.data_hora, "local": banca.local},
        )

    return render(
        request,
        "bancas/formulario.html",
        {"formulario": formulario, "projeto": banca.projeto, "titulo": "Editar banca"},
    )


@login_required
@require_POST
def cancelar(request, banca_id):
    """Cancela uma banca `AGENDADA` (Bloco D, spec §7) — sem tela própria,
    um `<form>` direto em `/orientacoes/`, mesmo padrão simples de
    `desativar_tema`."""
    banca = get_object_or_404(Banca, pk=banca_id, projeto__orientador=request.user)
    services.cancelar_banca(banca, por=request.user)
    messages.success(request, "Banca cancelada.")
    return redirect("projetos:orientacoes")


@login_required
def resultado(request, banca_id):
    """Registra o resultado de uma banca `AGENDADA` (Bloco D, spec §7)."""
    banca = get_object_or_404(Banca, pk=banca_id, projeto__orientador=request.user)

    if request.method == "POST":
        formulario = FormularioResultadoBanca(request.POST)
        if formulario.is_valid():
            try:
                services.registrar_resultado(
                    banca,
                    nota=formulario.cleaned_data["nota"],
                    resultado=formulario.cleaned_data["resultado"],
                    comentario=formulario.cleaned_data["comentario"],
                    por=request.user,
                )
            except ValidationError as erro:
                formulario.add_error(None, erro.messages[0])
            else:
                messages.success(request, "Resultado registrado.")
                return redirect("projetos:orientacoes")
    else:
        formulario = FormularioResultadoBanca()

    return render(request, "bancas/resultado.html", {"formulario": formulario, "banca": banca})
