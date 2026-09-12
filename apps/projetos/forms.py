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
