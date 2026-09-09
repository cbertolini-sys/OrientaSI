from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from apps.contas import services
from apps.contas.forms import (
    FormularioAlunoConvidado,
    FormularioPerfil,
    FormularioPerfilProfessor,
    FormularioProfessorConvidado,
)
from apps.contas.models import Usuario


def aceitar_convite(request, token):
    """Tela em que a pessoa convidada preenche seus dados e cria a conta."""
    try:
        convite = services.busca_convite_valido(token)
    except ValidationError as erro:
        return render(
            request,
            "contas/convite_invalido.html",
            {"mensagem": erro.messages[0]},
            status=404,
        )

    Formulario = (
        FormularioAlunoConvidado if convite.papel == Usuario.ALUNO else FormularioProfessorConvidado
    )
    formulario = Formulario(request.POST or None, request.FILES or None)

    if request.method == "POST" and formulario.is_valid():
        try:
            usuario = services.aceitar_convite(token, formulario.cleaned_data)
        except ValidationError as erro:
            formulario.add_error(None, erro.messages[0])
        else:
            login(request, usuario)
            messages.success(request, "Cadastro concluído. Bem-vindo(a) ao OrientaSI.")
            return redirect("inicio")

    return render(
        request,
        "contas/aceitar_convite.html",
        {"formulario": formulario, "convite": convite},
    )


@login_required
def perfil(request):
    """Tela em que a pessoa autenticada mantém os próprios dados. Professor
    recebe também o campo de áreas de atuação; aluno não (não existe
    `PerfilAluno.areas` — spec §5.4, só professor tem área de atuação)."""
    e_professor = request.user.papel == Usuario.PROFESSOR
    Formulario = FormularioPerfilProfessor if e_professor else FormularioPerfil

    if request.method == "POST":
        formulario = Formulario(request.POST, request.FILES)
        if formulario.is_valid():
            services.atualiza_perfil(
                request.user,
                telefone=formulario.cleaned_data["telefone"],
                areas=formulario.cleaned_data.get("areas"),
                foto=formulario.cleaned_data.get("foto"),
            )
            messages.success(request, "Perfil atualizado.")
            return redirect("contas:perfil")
    else:
        inicial = {"telefone": request.user.telefone}
        if e_professor:
            inicial["areas"] = request.user.perfil_professor.areas.all()
        formulario = Formulario(initial=inicial)

    return render(request, "contas/perfil.html", {"formulario": formulario})
