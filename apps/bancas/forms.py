from django import forms
from django.core.exceptions import ValidationError

from apps.contas.forms import MisturaAcessibilidadeFormulario
from apps.contas.models import PerfilProfessor
from apps.projetos.models import Projeto


class FormularioBanca(MisturaAcessibilidadeFormulario, forms.Form):
    """Agendamento/reagendamento de uma `Banca` (Bloco D, spec §7). Cada um
    dos dois membros vem de um par de campos (`_professor`/`_externo`) —
    `clean()` exige exatamente um preenchido por par, mesmo estilo do
    `clean()` de `FormularioCandidatura` (Bloco B), que já recusa opções
    repetidas do mesmo jeito."""

    data_hora = forms.DateTimeField(
        label="Data e hora",
        widget=forms.DateTimeInput(
            attrs={"class": "input w-full", "type": "datetime-local"},
            format="%Y-%m-%dT%H:%M",
        ),
        input_formats=["%Y-%m-%dT%H:%M"],
    )
    local = forms.CharField(
        label="Local", max_length=200, widget=forms.TextInput(attrs={"class": "input w-full"})
    )
    membro_1_professor = forms.ModelChoiceField(
        label="1º membro — professor (deixe em branco se for externo)",
        queryset=PerfilProfessor.objects.select_related("usuario").order_by(
            "usuario__nome_completo"
        ),
        required=False,
        widget=forms.Select(attrs={"class": "select w-full"}),
    )
    membro_1_externo = forms.CharField(
        label="1º membro — nome, se for externo",
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"class": "input w-full"}),
    )
    membro_2_professor = forms.ModelChoiceField(
        label="2º membro — professor (deixe em branco se for externo)",
        queryset=PerfilProfessor.objects.select_related("usuario").order_by(
            "usuario__nome_completo"
        ),
        required=False,
        widget=forms.Select(attrs={"class": "select w-full"}),
    )
    membro_2_externo = forms.CharField(
        label="2º membro — nome, se for externo",
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"class": "input w-full"}),
    )

    def __init__(self, *args, orientador=None, **kwargs):
        super().__init__(*args, **kwargs)
        if orientador is not None and hasattr(orientador, "perfil_professor"):
            self.fields["membro_1_professor"].queryset = self.fields[
                "membro_1_professor"
            ].queryset.exclude(usuario=orientador)
            self.fields["membro_2_professor"].queryset = self.fields[
                "membro_2_professor"
            ].queryset.exclude(usuario=orientador)

    def _limpa_membro(self, indice):
        professor = self.cleaned_data.get(f"membro_{indice}_professor")
        nome_externo = (self.cleaned_data.get(f"membro_{indice}_externo") or "").strip()
        if professor and nome_externo:
            raise ValidationError(
                f"Preencha só um campo para o {indice}º membro — professor OU nome externo, "
                "não os dois."
            )
        if not professor and not nome_externo:
            raise ValidationError(f"Preencha o {indice}º membro — professor ou nome externo.")
        return {"professor": professor} if professor else {"nome_externo": nome_externo}

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned

        membros = []
        for indice in (1, 2):
            try:
                membros.append(self._limpa_membro(indice))
            except ValidationError as erro:
                self.add_error(None, erro)

        if self.errors:
            return cleaned

        professores = [m["professor"] for m in membros if "professor" in m]
        if len(professores) != len({p.pk for p in professores}):
            self.add_error(None, "Os dois membros professores precisam ser diferentes.")
            return cleaned

        cleaned["membros"] = membros
        return cleaned


class FormularioResultadoBanca(MisturaAcessibilidadeFormulario, forms.Form):
    """Registro do resultado da apresentação (Bloco D, spec §7): uma nota,
    um resultado, um comentário — nunca um por membro (spec §3.2)."""

    nota = forms.DecimalField(
        label="Nota",
        max_digits=3,
        decimal_places=1,
        min_value=0,
        max_value=10,
        widget=forms.NumberInput(attrs={"class": "input w-full", "step": "0.1"}),
    )
    resultado = forms.ChoiceField(
        label="Resultado",
        choices=[
            (Projeto.APROVADO_COM_RESSALVAS, "Aprovado com ressalvas"),
            (Projeto.REPROVADO, "Reprovado"),
        ],
        widget=forms.Select(attrs={"class": "select w-full"}),
    )
    comentario = forms.CharField(
        label="Comentário",
        required=False,
        widget=forms.Textarea(attrs={"class": "textarea w-full"}),
    )


class FormularioItemCorrecao(MisturaAcessibilidadeFormulario, forms.Form):
    """Criação de um item de correção pelo orientador (Bloco F, spec §7)."""

    descricao = forms.CharField(
        label="Descrição da correção",
        widget=forms.Textarea(attrs={"class": "textarea w-full"}),
    )
