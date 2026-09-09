from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm
from django.contrib.auth.password_validation import validate_password

from apps.comum.validators import valida_extensao_imagem, valida_tamanho_arquivo
from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
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


class MisturaAcessibilidadeFormulario:
    """Repete, para os formulários prontos do `django.contrib.auth` (login e
    recuperação de senha), a mesma ligação de acessibilidade que
    `FormularioConvidado` (T7) já aplica aos formulários próprios do app:
    classes do DaisyUI via `aplica_estilo`, `aria-describedby` para texto de
    ajuda e `aria-invalid` + `aria-describedby` para erro, ligados após a
    validação.

    Como `AuthenticationForm`, `PasswordResetForm` e `SetPasswordForm` são do
    Django (não controlamos o `__init__`/`full_clean` deles na origem), a
    lógica é extraída aqui como mixin: entra antes da classe do Django na
    ordem de herança (MRO), então `super().__init__`/`super().full_clean`
    chamam a implementação do Django normalmente, e o pós-processamento roda
    depois.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        aplica_estilo(self)
        for nome, campo in self.fields.items():
            if campo.help_text:
                campo.widget.attrs["aria-describedby"] = f"ajuda-{nome}"

    def full_clean(self):
        super().full_clean()
        for nome, campo in self.fields.items():
            if not self.errors.get(nome):
                continue
            campo.widget.attrs["aria-invalid"] = "true"
            descritores = [
                d for d in [campo.widget.attrs.get("aria-describedby"), f"erro-{nome}"] if d
            ]
            campo.widget.attrs["aria-describedby"] = " ".join(descritores)


class FormularioLogin(MisturaAcessibilidadeFormulario, AuthenticationForm):
    """Formulário de login. O rótulo do e-mail já vem certo do Django (deriva
    de `Usuario.email.verbose_name`, "e-mail" -> "E-mail"), então só
    sobrescrevemos a mensagem de erro: a padrão do Django diz que "ambos os
    campos" (e-mail e senha) diferenciam maiúsculas de minúsculas, o que
    ficou incorreto sobre o e-mail depois da correção de
    `GerenciadorUsuario.get_by_natural_key` (login aceita o e-mail em
    qualquer caixa)."""

    error_messages = {
        "invalid_login": (
            "E-mail ou senha incorretos. A senha diferencia maiúsculas de minúsculas."
        ),
        "inactive": "Esta conta está inativa.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        campo_usuario = self.fields["username"]
        # `AuthenticationForm` marca o campo de e-mail com autofocus. Isso
        # rouba o foco do primeiro Tab assim que a página carrega, então a
        # primeira tabulação nunca alcança o link "Pular para o conteúdo" de
        # base.html (tests/test_teclado.py, achado nesta tarefa) — o
        # navegador já colocou o foco adiante dele antes de qualquer Tab.
        campo_usuario.widget.attrs.pop("autofocus", None)
        # `UsernameField` usa `TextInput` (type="text"). Como o identificador
        # é sempre um e-mail (USERNAME_FIELD), forçar type="email" abre o
        # teclado certo no celular (o projeto é mobile-first) — não é uma
        # exigência do WCAG, mas revisão 1 da T9 apontou a inconsistência com
        # o campo da tela de recuperação, que já usa EmailInput.
        campo_usuario.widget.input_type = "email"


class FormularioRecuperarSenha(MisturaAcessibilidadeFormulario, PasswordResetForm):
    """Formulário de recuperação de senha. Só corrige o rótulo do e-mail: a
    tradução pt-br embutida no Django para este formulário usa "Email" (sem
    hífen), inconsistente com "E-mail" usado no resto do projeto (inclusive
    no rótulo do login, que vem do `verbose_name` do model)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].label = "E-mail"


class FormularioDefinirNovaSenha(MisturaAcessibilidadeFormulario, SetPasswordForm):
    """Formulário de definição da nova senha, usado na tela de confirmação da
    recuperação. Os rótulos e o texto de ajuda (regras de senha) já vêm
    corretos e traduzidos do Django; só recebe estilo e acessibilidade do
    mixin."""


class FormularioPerfil(MisturaAcessibilidadeFormulario, forms.Form):
    """Campos que qualquer pessoa (aluno ou professor) mantém sobre si mesma
    na tela de perfil (T10). `FormularioPerfilProfessor`, abaixo, acrescenta
    o campo de áreas, exclusivo de professor."""

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
        # Sem autocomplete: a lista de "input purposes" do WCAG 2.1 AA
        # (critério 1.3.5) não tem um token para upload de arquivo — "photo"
        # não é um valor reconhecido de autocomplete (essa combinação já
        # existia, por engano, em `FormularioConvidado.foto`, mas não é
        # replicada aqui).
    )


class FormularioPerfilProfessor(FormularioPerfil):
    """Acrescenta a escolha das áreas de atuação, exclusiva do professor
    (`PerfilProfessor.areas`, T6). O widget é `CheckboxSelectMultiple`: o
    template (`templates/contas/perfil.html`) envolve este campo num
    `<fieldset>`/`<legend>` em vez do `<label>` usado pelos demais campos —
    sem isso, o axe aponta que o grupo de caixas de seleção não tem rótulo
    de grupo (regra `aria-input-field-name`/agrupamento), e um leitor de
    tela anuncia cada opção sem dizer a que pergunta ela responde."""

    areas = forms.ModelMultipleChoiceField(
        label="Áreas de atuação",
        queryset=Area.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
