def test_weasyprint_gera_pdf():
    """Trava a regressão do dia em que alguém enxugar as libs do Dockerfile (spec §8.2):
    WeasyPrint depende de Pango, Cairo e HarfBuzz — incluindo `libharfbuzz-subset0`,
    instaladas via apt, não via pip. A própria Tarefa 5 encontrou essa lib faltando:
    sem ela, a importação já emite um DeprecationWarning, que o filterwarnings="error"
    do pytest transforma em falha aqui — meses antes de alguém notar na tarefa que
    gera as atas de defesa."""
    from weasyprint import HTML

    pdf = HTML(string="<p>Ata de defesa</p>").write_pdf()
    assert pdf.startswith(b"%PDF-"), (
        f"WeasyPrint não gerou um PDF válido (esperava b'%PDF-' no início do "
        f"arquivo, recebi {pdf[:20]!r}). Confira as bibliotecas de sistema do "
        f"Dockerfile (Pango, Cairo, HarfBuzz)."
    )
