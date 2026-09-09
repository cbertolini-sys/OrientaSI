from django.contrib import messages
from django.contrib.auth import login
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from apps.contas import services
from apps.contas.forms import FormularioAlunoConvidado, FormularioProfessorConvidado
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
