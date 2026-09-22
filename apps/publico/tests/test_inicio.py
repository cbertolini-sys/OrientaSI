"""Teste da vitrine pública (`/`, `views.inicio`) — mini-calendário do mês
corrente."""

from datetime import date, datetime

import pytest
from django.utils import timezone

from apps.bancas.models import Banca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto


def _cpf(indice):
    base = f"{860000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


@pytest.mark.django_db
def test_inicio_mini_calendario_usa_data_local_nao_utc(client, monkeypatch):
    """ACHADO da re-auditoria de `apps/publico` (2026-09-22): `views.inicio`
    lia `b.data_hora.date()`/`.year`/`.month` direto, sem localizar — como
    `b.data_hora` vem do ORM em UTC (`USE_TZ=True`), uma banca marcada para
    tarde da noite em horário de Brasília (UTC−3) virava, em UTC, o dia
    SEGUINTE. Uma banca em 2099-06-15 às 23:30 (BRT) é 2099-06-16 02:30
    (UTC) — sem `timezone.localtime()`, o dia 16 aparecia marcado no
    mini-calendário, não o 15, contradizendo a lista "Próximas
    Apresentações" logo abaixo (que usa o filtro `|date:` do template,
    sempre localizado). Datas em 2099 de propósito: garantem que a banca
    está no futuro (`calendario_publico` exige `data_hora__gte=now()`)
    sem depender de quando esta suíte roda. `hoje` é monkeypatchado para o
    mesmo mês/ano, para o mini-calendário renderizar junho de 2099 em vez
    do mês real de hoje. Prova por mutação: tirar os `timezone.localtime()`
    de `views.inicio` faz este teste reprovar (o dia 16 apareceria marcado
    em vez do 15)."""
    from apps.publico import views as publico_views

    monkeypatch.setattr(publico_views.timezone, "localdate", lambda: date(2099, 6, 20))

    aluno = Usuario.objects.create_user(
        email="aluno.inicio.tz@ufsm.br",
        password="x",
        nome_completo="Aluno Início TZ",
        papel=Usuario.ALUNO,
        cpf=_cpf(1),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2099INICIOTZ1")
    orientador = Usuario.objects.create_user(
        email="orientador.inicio.tz@ufsm.br",
        password="x",
        nome_completo="Orientador Início TZ",
        cpf=_cpf(2),
    )
    PerfilProfessor.objects.create(usuario=orientador, siape="INICIOTZ01")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador,
        etapa=Projeto.TCC_I,
        status=Projeto.AGUARDANDO_DEFESA,
        ano=2099,
        periodo=1,
    )
    fuso_brt = timezone.get_current_timezone()
    data_hora_brt = timezone.make_aware(datetime(2099, 6, 15, 23, 30), fuso_brt)
    Banca.objects.create(
        projeto=projeto, data_hora=data_hora_brt, local="Sala 1", status=Banca.AGENDADA
    )

    resposta = client.get("/")
    semanas = resposta.context["semanas_do_mes"]
    dias = {dia["numero"]: dia["tem_banca"] for semana in semanas for dia in semana if dia}

    assert dias.get(15) is True
    assert dias.get(16) in (False, None)
