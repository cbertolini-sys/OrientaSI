from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

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

    atas_pendentes = Ata.objects.filter(revisao__status=RevisaoSUGRAD.PENDENTE).select_related(
        "projeto__aluno", "projeto__orientador"
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
def aprovar_ata_view(request, ata_id):
    """Aprova uma ata pendente (Bloco E, spec §7)."""
    garante(permissions.pode_revisar_ata(request.user), "Esta área é exclusiva da SUGRAD.")
    ata = get_object_or_404(Ata, pk=ata_id)
    services.aprovar_ata(ata, por=request.user)
    messages.success(request, "Ata aprovada. Projeto concluído.")
    return redirect("documentos:painel")


@login_required
def devolver_ata_view(request, ata_id):
    """Devolve uma ata pendente com comentário (Bloco E, spec §7).

    Um formulário inválido (comentário em branco) não impede que a lista
    inteira seja perdida: a resposta é sempre um redirect para
    `documentos:painel` (mesmo padrão de `recusar_opcao_view`, Bloco B),
    com o erro relatado via `messages` — não há estado de formulário
    parcial para preservar entre POST e a nova renderização, porque a
    página lista várias atas, não edita um registro único.
    """
    garante(permissions.pode_revisar_ata(request.user), "Esta área é exclusiva da SUGRAD.")
    ata = get_object_or_404(Ata, pk=ata_id)
    formulario = FormularioDevolverAta(request.POST)
    if not formulario.is_valid():
        messages.error(request, "Informe um comentário para devolver a ata.")
        return redirect("documentos:painel")

    services.devolver_ata(ata, por=request.user, comentario=formulario.cleaned_data["comentario"])
    messages.success(request, "Ata devolvida.")
    return redirect("documentos:painel")
