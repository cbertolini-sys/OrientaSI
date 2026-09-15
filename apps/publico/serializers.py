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

    def get_pdf_url(self, projeto):
        return projeto.submissao.pdf.url
