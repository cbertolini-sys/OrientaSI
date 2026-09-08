def test_weasyprint_gera_pdf():
    """Trava a regressão do dia em que alguém enxugar as libs do Dockerfile (spec §8.2):
    WeasyPrint depende de Pango/Cairo instalados via apt, não via pip — se essas libs
    de sistema saírem do Dockerfile, a importação falha aqui, meses antes de alguém
    notar na tarefa que gera as atas de defesa."""
    from weasyprint import HTML

    pdf = HTML(string="<p>Ata de defesa</p>").write_pdf()
    assert pdf.startswith(b"%PDF-")
