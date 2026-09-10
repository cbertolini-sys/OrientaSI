from django.conf import settings
from django.utils import timezone


def semestre_vigente(data=None):
    """Devolve `(ano, periodo)` do semestre letivo corrente.

    O mês de corte é configurável de propósito: calendário acadêmico não acompanha o
    civil, e num ano deslocado por greve ou reposição a virada precisa poder ser
    ajustada por constante, sem migração. O semestre GRAVADO nos registros é
    congelado em dois inteiros — ajustar o corte não muda o histórico.
    """
    data = data or timezone.localdate()
    periodo = 1 if data.month < settings.MES_INICIO_PERIODO_2 else 2
    return data.year, periodo
