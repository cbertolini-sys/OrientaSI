import calendar
import sys
from datetime import date

import django
from django.shortcuts import render
from django.utils import timezone

from apps.contas.models import Area
from apps.publico import services


def inicio(request):
    """Página inicial pública — vitrine com uma amostra real do catálogo e
    da agenda, os mesmos `services.catalogo_publico`/`calendario_publico`
    de `/catalogo/`/`/calendario/`, só um recorte menor (pra não duplicar
    as telas completas). Registrada em `config/urls.py` no lugar do
    `TemplateView` original — o nome da rota continua `inicio`, então
    nenhum `{% url 'inicio' %}` espalhado pelos templates muda.

    O calendário aqui é só do mês corrente, sem navegação entre meses —
    pra isso, `/calendario/` já existe; construir um seletor de mês era
    escopo maior do que uma vitrine pede.
    """
    hoje = timezone.localdate()
    todas_bancas = services.calendario_publico()
    # `timezone.localtime(...)` antes de `.date()`/`.year`/`.month` (achado
    # da re-auditoria de `apps/publico`, 2026-09-22): `b.data_hora` vem do
    # ORM em UTC (`USE_TZ=True`) — ler `.date()` direto nele lia a data em
    # UTC, não em America/Sao_Paulo, contradizendo a lista "Próximas
    # Apresentações" logo abaixo na mesma página (que usa o filtro de
    # template `|date:`, que SEMPRE localiza). Uma banca às 21h de Brasília
    # (UTC−3) virava meia-noite UTC do dia seguinte — a bolinha do
    # calendário marcava o dia errado, e uma banca no dia 31 às 21h sumia
    # do mês inteiro (o `month` também lido em UTC).
    dias_com_banca = {
        timezone.localtime(b.data_hora).date()
        for b in todas_bancas
        if timezone.localtime(b.data_hora).year == hoje.year
        and timezone.localtime(b.data_hora).month == hoje.month
    }
    semanas = []
    for semana in calendar.Calendar(firstweekday=6).monthdayscalendar(hoje.year, hoje.month):
        linha = []
        for dia in semana:
            if dia == 0:
                linha.append(None)
            else:
                data_do_dia = date(hoje.year, hoje.month, dia)
                linha.append(
                    {
                        "numero": dia,
                        "hoje": data_do_dia == hoje,
                        "tem_banca": data_do_dia in dias_com_banca,
                    }
                )
        semanas.append(linha)
    return render(
        request,
        "inicio.html",
        {
            "projetos_recentes": services.catalogo_publico()[:4],
            "bancas_proximas": todas_bancas[:5],
            "mes_atual": hoje,
            "semanas_do_mes": semanas,
        },
    )


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
            # `area__isnull=False` (achado da re-auditoria de `apps/publico`,
            # 2026-09-22): o filtro (`services.catalogo_publico`) casa contra
            # `PerfilProfessor.areas`, que só aceita SUBÁREAS
            # (`FormularioPerfilProfessor.areas`, `apps/contas/forms.py`) —
            # listar as 4 áreas de TOPO aqui oferecia 4 opções que nunca
            # bateriam com nada, sempre devolvendo "Nenhum TCC publicado
            # ainda" para quem as escolhesse. Mesmo predicado que o
            # formulário de perfil já usa.
            "areas": Area.objects.filter(area__isnull=False).order_by("ordem", "nome"),
            "anos": services.anos_do_catalogo(),
            "area_selecionada": area_id,
            "ano_selecionado": ano,
        },
    )


def calendario(request):
    """Calendário público de apresentações futuras (Bloco G, spec §6) —
    sem login, sem filtro (YAGNI: nenhum requisito pediu)."""
    return render(request, "publico/calendario.html", {"bancas": services.calendario_publico()})


def sobre(request):
    """Página pública "Sobre" — o que o sistema é, os quatro fluxogramas de
    papel e a ficha técnica. Sem login e sem models próprios, mesmo padrão
    de `catalogo`/`calendario` — inclusive para quem nunca vai ter conta
    (a comunidade externa lendo sobre o sistema antes de acessar o
    catálogo).

    Python/Django lidos da instalação real, não escritos à mão (mesmo
    cuidado do sistema irmão IntegraSI, `templates/catalogo/sobre.html`
    de lá): uma versão digitada na página envelhece na primeira
    atualização, e ninguém lembra de vir corrigir uma página pública. Só
    maior.menor — o patch muda toda hora e não é o que a frase promete."""
    versao_python = f"{sys.version_info.major}.{sys.version_info.minor}"
    versao_django = ".".join(django.get_version().split(".")[:2])
    return render(
        request,
        "publico/sobre.html",
        {"versao_python": versao_python, "versao_django": versao_django},
    )
