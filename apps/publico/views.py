from django.shortcuts import render

from apps.contas.models import Area
from apps.publico import services


def catalogo(request):
    """Catálogo público de TCCs concluídos (Bloco G, spec §6) — sem login,
    sem dado sensível (só Título, Resumo, Autor, Orientador e o PDF).
    `area`/`ano` vêm da querystring como texto; `isdigit()` descarta
    entrada não numérica em vez de deixar `int()` levantar `ValueError` e
    derrubar a página com 500 — ninguém além de um usuário digitando a URL
    à mão produziria isso, mas a tela é pública e não tem formulário
    algum controlando o valor antes de chegar aqui."""
    area_id = request.GET.get("area")
    area_id = int(area_id) if area_id and area_id.isdigit() else None
    ano = request.GET.get("ano")
    ano = int(ano) if ano and ano.isdigit() else None
    return render(
        request,
        "publico/catalogo.html",
        {
            "projetos": services.catalogo_publico(area_id=area_id, ano=ano),
            "areas": Area.objects.order_by("nome"),
            "anos": services.anos_do_catalogo(),
            "area_selecionada": area_id,
            "ano_selecionado": ano,
        },
    )
