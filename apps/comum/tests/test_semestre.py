import datetime

import pytest

from apps.comum.semestre import semestre_vigente


@pytest.mark.parametrize(
    "data, esperado",
    [
        (datetime.date(2026, 1, 15), (2026, 1)),
        (datetime.date(2026, 7, 31), (2026, 1)),
        (datetime.date(2026, 8, 1), (2026, 2)),
        (datetime.date(2026, 12, 31), (2026, 2)),
    ],
)
def test_semestre_vigente_usa_o_mes_de_corte(data, esperado):
    assert semestre_vigente(data) == esperado


def test_mes_de_corte_e_configuravel(settings):
    """O calendário acadêmico não acompanha o civil: greve e reposição deslocam a
    virada, e ajustar uma constante precisa bastar."""
    settings.MES_INICIO_PERIODO_2 = 9
    assert semestre_vigente(datetime.date(2026, 8, 15)) == (2026, 1)
