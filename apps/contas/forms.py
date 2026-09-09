from django import forms
from django.contrib.auth.password_validation import validate_password

from apps.comum.validators import valida_extensao_imagem, valida_tamanho_arquivo
from apps.contas.validators import valida_cpf

CLASSES = {
    # DaisyUI 5 não usa mais o sufixo "-bordered": `.input` e `.file-input` já
    # nascem com borda visível, sem modificador.
    forms.TextInput: "input w-full",
    forms.EmailInput: "input w-full",
    forms.PasswordInput: "input w-full",
    forms.ClearableFileInput: "file-input w-full",
}


def aplica_estilo(formulario):
    """Aplica as classes do DaisyUI a cada campo, conforme o tipo do widget."""
    for campo in formulario.fields.values():
        classe = CLASSES.get(type(campo.widget))
        if classe:
            campo.widget.attrs.setdefault("class", classe)


class FormularioConvidado(forms.Form):
    """Campos comuns a aluno e professor no aceite do convite."""

    nome_completo = forms.CharField(label="Nome completo", max_length=200)
    cpf = forms.CharField(
        label="CPF",
        max_length=14,
        help_text="Somente números.",
    )
    telefone = forms.CharField(label="Telefone", max_length=20, required=False)
    foto = forms.ImageField(
        label="Foto",
        required=False,
        validators=[valida_extensao_imagem, valida_tamanho_arquivo],
    )
    senha = forms.CharField(label="Senha", widget=forms.PasswordInput, strip=False)
    senha_confirmacao = forms.CharField(
        label="Confirme a senha", widget=forms.PasswordInput, strip=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        aplica_estilo(self)

    def clean_cpf(self):
        cpf = "".join(c for c in self.cleaned_data["cpf"] if c.isdigit())
        valida_cpf(cpf)
        return cpf

    def clean(self):
        limpos = super().clean()
        senha, confirmacao = limpos.get("senha"), limpos.get("senha_confirmacao")
        if senha and confirmacao and senha != confirmacao:
            self.add_error("senha_confirmacao", "As senhas não conferem.")
        if senha:
            validate_password(senha)
        return limpos


class FormularioAlunoConvidado(FormularioConvidado):
    matricula = forms.CharField(label="Matrícula", max_length=20)


class FormularioProfessorConvidado(FormularioConvidado):
    siape = forms.CharField(label="SIAPE", max_length=20)
