from rest_framework import serializers


class CatalogoSerializer(serializers.Serializer):
    """Serializa um `Projeto` catalogável (Bloco H, spec §3) — só os cinco
    campos que a regra 6 do CLAUDE.md permite expor publicamente. Campos
    explícitos, não `ModelSerializer`: nenhum campo novo em `Projeto`
    (CPF, telefone) vaza pra API por acidente."""

    id = serializers.IntegerField()
    titulo = serializers.CharField(source="tema.titulo")
    resumo = serializers.CharField(source="tema.descricao")
    autor = serializers.CharField(source="aluno.nome_completo")
    orientador = serializers.CharField(source="orientador.nome_completo")
    pdf_url = serializers.SerializerMethodField()

    def get_pdf_url(self, projeto) -> str:
        return projeto.submissao.pdf.url


class CalendarioSerializer(serializers.Serializer):
    """Serializa uma `Banca` agendada futura (Bloco H, spec §3)."""

    id = serializers.IntegerField()
    aluno = serializers.CharField(source="projeto.aluno.nome_completo")
    titulo = serializers.SerializerMethodField()
    orientador = serializers.CharField(source="projeto.orientador.nome_completo")
    data_hora = serializers.DateTimeField()
    local = serializers.CharField()

    def get_titulo(self, banca) -> str | None:
        return banca.projeto.tema.titulo if banca.projeto.tema else None
