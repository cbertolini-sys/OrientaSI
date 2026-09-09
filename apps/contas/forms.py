from django import forms
from django.contrib.auth.password_validation import validate_password

from apps.comum.validators import valida_extensao_imagem, valida_tamanho_arquivo
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import valida_cpf


def aplica_estilo(formulario):
    """Aplica as classes do DaisyUI a cada campo, conforme o tipo do widget.

    Usa `isinstance` em cadeia, não busca por tipo exato: um widget subclassado
    (por exemplo, uma tarefa futura que personalize um campo com um widget
    próprio) ainda é reconhecido pelo seu tipo-base e recebe a classe certa —
    uma busca por `type(widget) is X` deixaria esse widget silenciosamente sem
    estilo.
    """
    for campo in formulario.fields.values():
        widget = campo.widget
        if isinstance(widget, forms.ClearableFileInput):
            # DaisyUI 5 não usa mais o sufixo "-bordered": `.file-input` já
            # nasce com borda visível, sem modificador.
            classe = "file-input w-full"
        elif isinstance(widget, (forms.TextInput, forms.EmailInput, forms.PasswordInput)):
            classe = "input w-full"
        else:
            classe = None
        if classe:
            widget.attrs.setdefault("class", classe)


class FormularioConvidado(forms.Form):
    """Campos comuns a aluno e professor no aceite do convite."""

    nome_completo = forms.CharField(
        label="Nome completo",
        max_length=200,
        widget=forms.TextInput(attrs={"autocomplete": "name"}),
    )
    cpf = forms.CharField(
        label="CPF",
        max_length=14,
        help_text="Você pode digitar com ou sem pontuação: pontos e traço são removidos "
        "automaticamente.",
    )
    telefone = forms.CharField(
        label="Telefone",
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "tel"}),
    )
    foto = forms.ImageField(
        label="Foto",
        required=False,
        validators=[valida_extensao_imagem, valida_tamanho_arquivo],
        widget=forms.ClearableFileInput(attrs={"autocomplete": "photo"}),
    )
    senha = forms.CharField(
        label="Senha",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        strip=False,
    )
    senha_confirmacao = forms.CharField(
        label="Confirme a senha",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        strip=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        aplica_estilo(self)
        # aria-describedby do texto de ajuda é conhecido desde já (não depende de
        # validação); o de erro só existe depois de full_clean, ver abaixo.
        for nome, campo in self.fields.items():
            if campo.help_text:
                campo.widget.attrs["aria-describedby"] = f"ajuda-{nome}"

    def full_clean(self):
        super().full_clean()
        # Só depois de validar sabemos quais campos erraram: aqui ligamos
        # aria-invalid e acrescentamos o id do bloco de erro ao
        # aria-describedby, para que um leitor de tela anuncie a mensagem de
        # erro (e a ajuda, se houver) ao tabular até o campo — sem isto, o
        # `role="alert"` do bloco de erro só é ouvido por quem já está com o
        # foco nele no instante em que a página carrega, o que nunca acontece.
        for nome, campo in self.fields.items():
            if not self.errors.get(nome):
                continue
            campo.widget.attrs["aria-invalid"] = "true"
            descritores = [
                d for d in [campo.widget.attrs.get("aria-describedby"), f"erro-{nome}"] if d
            ]
            campo.widget.attrs["aria-describedby"] = " ".join(descritores)

    def clean_cpf(self):
        cpf = "".join(c for c in self.cleaned_data["cpf"] if c.isdigit())
        valida_cpf(cpf)
        if Usuario.objects.filter(cpf=cpf).exists():
            raise forms.ValidationError("Já existe uma conta cadastrada com este CPF.")
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

    def clean_matricula(self):
        matricula = self.cleaned_data["matricula"]
        if PerfilAluno.objects.filter(matricula=matricula).exists():
            raise forms.ValidationError("Já existe um aluno cadastrado com esta matrícula.")
        return matricula


class FormularioProfessorConvidado(FormularioConvidado):
    siape = forms.CharField(label="SIAPE", max_length=20)

    def clean_siape(self):
        siape = self.cleaned_data["siape"]
        if PerfilProfessor.objects.filter(siape=siape).exists():
            raise forms.ValidationError("Já existe um professor cadastrado com este SIAPE.")
        return siape
