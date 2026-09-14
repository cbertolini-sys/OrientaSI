from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.bancas import services
from apps.bancas.forms import FormularioBanca, FormularioItemCorrecao, FormularioResultadoBanca
from apps.bancas.models import Banca, ItemCorrecao
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


@login_required
def correcoes(request, projeto_id):
    """Lista os itens de correção do TCC II e permite criar novos (Bloco F,
    spec §7). O botão "Aprovar" desta tela posta pra
    `projetos:aprovar_projeto` (Bloco E) — a mesma rota do TCC_I; o gate da
    Tarefa 6 é quem decide se o pedido é aceito ou recusado."""
    projeto = get_object_or_404(Projeto, pk=projeto_id, orientador=request.user)

    if request.method == "POST":
        formulario = FormularioItemCorrecao(request.POST)
        if formulario.is_valid():
            services.criar_item_correcao(
                projeto, descricao=formulario.cleaned_data["descricao"], por=request.user
            )
            messages.success(request, "Item de correção criado.")
            return redirect("bancas:correcoes", projeto_id=projeto.pk)
    else:
        formulario = FormularioItemCorrecao()

    itens = projeto.itens_correcao.all()
    return render(
        request,
        "bancas/correcoes.html",
        {"projeto": projeto, "itens": itens, "formulario": formulario},
    )


@login_required
@require_POST
def concluir_item_view(request, item_id):
    """Marca um item de correção como concluído (Bloco F, spec §7)."""
    item = get_object_or_404(ItemCorrecao, pk=item_id, projeto__orientador=request.user)
    services.concluir_item_correcao(item, por=request.user)
    messages.success(request, "Item marcado como concluído.")
    return redirect("bancas:correcoes", projeto_id=item.projeto_id)
