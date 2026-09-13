from django import forms

from apps.contas.forms import MisturaAcessibilidadeFormulario
from apps.contas.models import Area


class FormularioTema(MisturaAcessibilidadeFormulario, forms.Form):
    """Formulário de cadastro de tema (T6, painel `projetos:meus_temas`).

    `area` nasce com queryset vazio: a view passa `professor=` no
    construtor, e só então o campo é restrito às áreas que ESSE professor
    declarou em `PerfilProfessor.areas` (T6, Tarefa 10 do Bloco A). Sem essa
    restrição por instância, o campo listaria toda `Area` do sistema, e o
    mural (Tarefa 7) anunciaria um tema numa área em que o professor não
    afirma atuar — `services.criar_tema` recusa isso de qualquer forma, mas
    o formulário já evita oferecer a opção errada.

    Reusa `MisturaAcessibilidadeFormulario` (apps/contas/forms.py) para a
    mesma ligação de `aria-describedby`/`aria-invalid` que os demais
    formulários do projeto já têm, em vez de duplicá-la aqui.
    """

    titulo = forms.CharField(label="Título", max_length=200)
    descricao = forms.CharField(
        label="Descrição",
        widget=forms.Textarea(attrs={"class": "textarea w-full"}),
    )
    area = forms.ModelChoiceField(
        label="Área",
        queryset=Area.objects.none(),
        widget=forms.Select(attrs={"class": "select w-full"}),
    )

    def __init__(self, *args, professor=None, **kwargs):
        super().__init__(*args, **kwargs)
        if professor is not None:
            self.fields["area"].queryset = professor.areas.all()


class FormularioRecusaOpcao(MisturaAcessibilidadeFormulario, forms.Form):
    """Formulário de recusa de uma manifestação de interesse (T9). A
    justificativa é obrigatória (spec §6: "sem ela, a recusa é silêncio com
    outro nome, e o aluno não tem como decidir o próximo passo") — o
    `required=True` padrão de `CharField` já barra o campo vazio aqui; a
    checagem em `services.recusar_opcao` (que também recusa string em
    branco/só espaço) é quem protege qualquer chamador que não passe por
    este formulário.

    A tela de orientações (`templates/projetos/orientacoes.html`) instancia
    um formulário POR manifestação pendente, dentro de uma lista — o `id`
    padrão ("id_justificativa") colidiria entre as linhas, e um
    `<label for=...>` duplicado é ambíguo para leitor de tela. A view passa
    `auto_id=f"id_recusa_{opcao.pk}_%s"` (parâmetro já aceito por
    `forms.Form.__init__`, sem precisar de override aqui) para cada
    instância ganhar ids únicos.
    """

    justificativa = forms.CharField(
        label="Justificativa",
        widget=forms.Textarea(attrs={"class": "textarea w-full"}),
    )


class FormularioFiltroMural(MisturaAcessibilidadeFormulario, forms.Form):
    """Filtro de área do mural de temas (T7). Formulário de GET, não de POST:
    `area` é sempre opcional (`required=False`) — em branco, o mural mostra
    temas de todas as áreas, e não há "erro" possível de o aluno não
    escolher nenhuma.
    """

    area = forms.ModelChoiceField(
        label="Área",
        queryset=Area.objects.all(),
        required=False,
        empty_label="Todas as áreas",
        widget=forms.Select(attrs={"class": "select w-full"}),
    )
