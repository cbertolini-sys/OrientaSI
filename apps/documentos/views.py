from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.documentos import permissions, services
from apps.documentos.forms import FormularioDevolverAta
from apps.documentos.models import Ata, RevisaoSUGRAD
from apps.projetos.permissions import garante


@login_required
def painel(request):
    """Painel da SUGRAD: lista atas `PENDENTE` (Bloco E, spec §7). Portão de
    PAPEL, sem lookup de posse — mesmo padrão de `painel_orientacoes`
    (Bloco B): a SUGRAD revisa a ata de QUALQUER projeto."""
    garante(permissions.pode_revisar_ata(request.user), "Esta área é exclusiva da SUGRAD.")

    # `select_related("revisao")` (achado L4 da auditoria, 2026-09-22): o
    # template acessa `item.ata.revisao` (o link "Aprovar"/"Devolver" e o
    # comentário de uma devolução anterior); sem isto, cada ata da lista
    # disparava uma query extra só para buscar a própria revisão que já foi
    # usada para FILTRAR esta queryset.
    atas_pendentes = Ata.objects.filter(revisao__status=RevisaoSUGRAD.PENDENTE).select_related(
        "projeto__aluno", "projeto__orientador", "revisao"
    )
    itens = [
        {
            "ata": ata,
            "formulario_devolver": FormularioDevolverAta(auto_id=f"id_devolver_{ata.pk}_%s"),
        }
        for ata in atas_pendentes
    ]
    return render(request, "documentos/painel_sugrad.html", {"itens": itens})


@login_required
@require_POST
def aprovar_ata_view(request, ata_id):
    """Aprova uma ata pendente (Bloco E, spec §7).

    `@require_POST` (achado H1 da auditoria, 2026-09-22): esta view era a
    ÚNICA exceção do sistema sem essa trava — uma transição de status real
    (`Aprovado → Concluído`, com a criação automática do TCC II junto)
    ficava alcançável por GET, sem proteção nenhuma de CSRF (que o Django
    não aplica a métodos seguros): um `<img src>`, um link-prefetcher ou uma
    prévia de e-mail bastavam para aprovar a ata enquanto a SUGRAD estivesse
    logada. `try/except` (achado H7): um segundo clique numa revisão que já
    saiu de `PENDENTE` levantava `ValidationError` sem tratamento — 500."""
    garante(permissions.pode_revisar_ata(request.user), "Esta área é exclusiva da SUGRAD.")
    ata = get_object_or_404(Ata, pk=ata_id)
    try:
        services.aprovar_ata(ata, por=request.user)
    except ValidationError as erro:
        messages.error(request, erro.messages[0])
    else:
        messages.success(request, "Ata aprovada. Projeto concluído.")
    return redirect("documentos:painel")


@login_required
@require_POST
def devolver_ata_view(request, ata_id):
    """Devolve uma ata pendente com comentário (Bloco E, spec §7).

    Um formulário inválido (comentário em branco) não impede que a lista
    inteira seja perdida: a resposta é sempre um redirect para
    `documentos:painel` (mesmo padrão de `recusar_opcao_view`, Bloco B),
    com o erro relatado via `messages` — não há estado de formulário
    parcial para preservar entre POST e a nova renderização, porque a
    página lista várias atas, não edita um registro único.

    `@require_POST` (achado H1): antes só era "protegida" por acidente — um
    GET faz `FormularioDevolverAta(request.POST)` ver um `QueryDict` vazio e
    cair no `if not formulario.is_valid()`, mas isso nunca foi uma decisão,
    era uma coincidência de como o Django popula `request.POST` num GET.
    `try/except` (achado H7): mesma razão de `aprovar_ata_view`.
    """
    garante(permissions.pode_revisar_ata(request.user), "Esta área é exclusiva da SUGRAD.")
    ata = get_object_or_404(Ata, pk=ata_id)
    formulario = FormularioDevolverAta(request.POST)
    if not formulario.is_valid():
        messages.error(request, "Informe um comentário para devolver a ata.")
        return redirect("documentos:painel")

    try:
        services.devolver_ata(
            ata, por=request.user, comentario=formulario.cleaned_data["comentario"]
        )
    except ValidationError as erro:
        messages.error(request, erro.messages[0])
    else:
        messages.success(request, "Ata devolvida.")
    return redirect("documentos:painel")
