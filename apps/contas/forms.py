from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm
from django.contrib.auth.password_validation import validate_password

from apps.comum.validators import valida_extensao_imagem, valida_tamanho_arquivo
from apps.contas.models import Area, Convite, PerfilAluno, PerfilProfessor, Usuario
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
        # Sem `autocomplete`: "photo" NÃO é um token da lista de "input
        # purposes" do WHATWG/WCAG 2.1 (critério 1.3.5), e nenhum token dessa
        # lista serve para upload de arquivo. Era atributo inválido, contra o
        # mesmo critério que o projeto testa. `FormularioPerfil.foto` (T10) já
        # nascera sem ele, com esta justificativa; aqui o engano sobreviveu
        # até a revisão final.
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

    def __init__(self, *args, email=None, **kwargs):
        # `email` vem do convite (a pessoa não digita o próprio e-mail: ele já
        # está no convite) e serve só para a validação de senha em `clean`,
        # ver ali.
        self.email_do_convite = email or ""
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
            # `user=` não é decoração (achado da revisão final): sem ele, o
            # `UserAttributeSimilarityValidator` de AUTH_PASSWORD_VALIDATORS
            # fica inerte, e "Ana Silva" pode escolher a senha "anasilva1". O
            # usuário ainda não existe neste ponto (é este formulário que o
            # cria), então montamos uma instância NÃO SALVA só para o
            # validador comparar os atributos — é o mesmo que o
            # `UserCreationForm` do Django faz.
            validate_password(
                senha,
                user=Usuario(
                    email=self.email_do_convite,
                    nome_completo=limpos.get("nome_completo", ""),
                ),
            )
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
    """Formulário de recuperação de senha.

    Corrige o rótulo do e-mail (a tradução pt-br embutida no Django para este
    formulário usa "Email" sem hífen, inconsistente com "E-mail" no resto do
    projeto) e desvia o envio para o Celery, ver `send_mail` abaixo.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].label = "E-mail"

    def send_mail(self, *args, **kwargs):
        """Enfileira a tarefa em vez de falar SMTP dentro da requisição.

        A spec §6 lista `enviar_recuperacao_senha(usuario_id)` como uma das
        duas tarefas Celery e a §7.6 diz "fluxo padrão do Django, com o e-mail
        enviado por Celery" — a implementação usava o `PasswordResetView` cru,
        com o SMTP dentro da requisição (achado da revisão final).

        `PasswordResetForm.save()` chama este método uma vez para CADA conta
        ativa com senha utilizável que casa com o e-mail informado, e não o
        chama nenhuma vez quando não há conta — é assim que o Django não
        revela quem tem cadastro. Sobrescrever aqui preserva essa
        não-enumeração inteira: a resposta HTTP é idêntica nos dois casos
        (`apps/contas/tests/test_autenticacao.py`).

        Os argumentos do Django são ignorados de propósito: o único dado que a
        tarefa precisa é o id do usuário (`contexto["user"]`), e o assunto, o
        corpo e o token são montados no worker (`apps/contas/tasks.py`).
        """
        from apps.contas.tasks import enviar_recuperacao_senha

        contexto = kwargs.get("context") or args[2]
        enviar_recuperacao_senha.delay(contexto["user"].pk)


class FormularioDefinirNovaSenha(MisturaAcessibilidadeFormulario, SetPasswordForm):
    """Formulário de definição da nova senha, usado na tela de confirmação da
    recuperação. Os rótulos e o texto de ajuda (regras de senha) já vêm
    corretos e traduzidos do Django; só recebe estilo e acessibilidade do
    mixin."""


class FormularioPerfil(MisturaAcessibilidadeFormulario, forms.Form):
    """Campos que qualquer pessoa autenticada mantém sobre si mesma na tela
    de perfil (T10; identidade — nome/e-mail/CPF — acrescentada depois, a
    pedido explícito do usuário: "editar todos os campos"). Recebe o
    `usuario` de quem está editando (obrigatório — `perfil`, em
    apps/contas/views.py, é o único lugar que instancia este formulário) só
    pra validar unicidade de e-mail/CPF EXCLUINDO a própria conta: sem isso,
    salvar o formulário sem mudar nada reprovaria "já existe uma conta com
    este e-mail/CPF" contra si mesma.

    `FormularioPerfilAluno`/`FormularioPerfilProfessor`, abaixo, acrescentam
    respectivamente matrícula e (SIAPE + áreas de atuação), exclusivos de
    cada perfil.

    `cpf` fica `required=False` aqui — a conta da SUGRAD não tem CPF
    (`Usuario.Meta.constraints`, `cpf_obrigatorio_para_pessoas`, isenta só
    `papel=SUGRAD`) — e a obrigatoriedade pra aluno/professor é reforçada em
    `clean_cpf`, não no campo, porque o campo é compartilhado pelos três
    papéis."""

    nome_completo = forms.CharField(
        label="Nome completo",
        max_length=200,
        widget=forms.TextInput(attrs={"autocomplete": "name"}),
    )
    email = forms.EmailField(
        label="E-mail",
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )
    cpf = forms.CharField(
        label="CPF",
        max_length=14,
        required=False,
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
        # Sem autocomplete: a lista de "input purposes" do WCAG 2.1 AA
        # (critério 1.3.5) não tem um token para upload de arquivo — "photo"
        # não é um valor reconhecido de autocomplete (essa combinação já
        # existia, por engano, em `FormularioConvidado.foto`, mas não é
        # replicada aqui).
    )

    def __init__(self, *args, usuario, **kwargs):
        self.usuario = usuario
        super().__init__(*args, **kwargs)

    def clean_email(self):
        # `__iexact`, não `=`: o e-mail é gravado sempre em minúsculas
        # (`apps/contas/signals.py::normaliza_email_do_usuario`, roda em
        # QUALQUER `save()`), mas a checagem de unicidade acontece ANTES
        # desse sinal — sem `__iexact`, "Ana@ufsm.br" passaria pela
        # validação do formulário mesmo já existindo "ana@ufsm.br", e só
        # estouraria depois, como `IntegrityError` cru (500) no `save()`.
        email = self.cleaned_data["email"].lower()
        if Usuario.objects.exclude(pk=self.usuario.pk).filter(email__iexact=email).exists():
            raise forms.ValidationError("Já existe uma conta cadastrada com este e-mail.")
        return email

    def clean_cpf(self):
        cpf = "".join(c for c in self.cleaned_data["cpf"] if c.isdigit())
        if not cpf:
            if self.usuario.papel != Usuario.SUGRAD:
                raise forms.ValidationError("CPF é obrigatório.")
            return cpf
        valida_cpf(cpf)
        if Usuario.objects.exclude(pk=self.usuario.pk).filter(cpf=cpf).exists():
            raise forms.ValidationError("Já existe uma conta cadastrada com este CPF.")
        return cpf


class FormularioPerfilAluno(FormularioPerfil):
    """Acrescenta a matrícula, exclusiva de quem tem `PerfilAluno`."""

    matricula = forms.CharField(label="Matrícula", max_length=20)

    def clean_matricula(self):
        matricula = self.cleaned_data["matricula"]
        if (
            PerfilAluno.objects.exclude(usuario=self.usuario)
            .filter(matricula=matricula)
            .exists()
        ):
            raise forms.ValidationError("Já existe um aluno cadastrado com esta matrícula.")
        return matricula


class FormularioPerfilProfessor(FormularioPerfil):
    """Acrescenta o SIAPE e a escolha das áreas de atuação, exclusivos de
    quem tem `PerfilProfessor` (`PerfilProfessor.areas`, T6). O widget de
    `areas` é `CheckboxSelectMultiple`: o template
    (`templates/contas/perfil.html`) envolve este campo num
    `<fieldset>`/`<legend>` em vez do `<label>` usado pelos demais campos.

    Sem o `<fieldset>`/`<legend>`, um leitor de tela anuncia cada opção
    ("Redes", "Inteligência Artificial"...) sem dizer a que pergunta elas
    respondem — a pessoa ouve os nomes soltos, sem saber que são escolhas de
    área de atuação. **O axe-core (rodado com as tags wcag2a/wcag2aa/wcag21aa,
    as mesmas de `tests/test_acessibilidade.py`) não aponta essa ausência**:
    as regras `checkboxgroup`/`radiogroup` que cobririam isso foram removidas
    do axe-core 4 (confirmado rodando o mesmo `Axe().run` contra o markup sem
    `<fieldset>`: zero violações). Por isso
    `apps/contas/tests/test_perfil_view.py::test_form_professor_tem_fieldset_e_legend_para_areas`
    afirma a presença do `<fieldset>`/`<legend>` diretamente no HTML — é a
    única rede de segurança contra a remoção deste elemento, o axe não
    cobre."""

    siape = forms.CharField(label="SIAPE", max_length=20)
    # Só as 16 SUBÁREAS do CNPq/CAPES são marcáveis (`area__isnull=False`,
    # ou seja, toda `Area` que TEM uma área-pai) — pedido explícito do
    # usuário: refatoração de terminologia, "cada uma das 4 áreas tem
    # subáreas (totalizando 16). Quero que o professor consiga selecionar as
    # subáreas". As 4 ÁREAS de topo (`area=None`) viram só cabeçalhos de
    # agrupamento no template, não marcáveis. Restringir o `queryset`, e não
    # só a lista renderizada no template, faz o formulário recusar de
    # verdade um pk de área-de-topo que chegasse manipulado num POST — não é
    # só uma questão de apresentação.
    areas = forms.ModelMultipleChoiceField(
        label="Áreas de atuação",
        queryset=Area.objects.filter(area__isnull=False),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def clean_siape(self):
        siape = self.cleaned_data["siape"]
        if (
            PerfilProfessor.objects.exclude(usuario=self.usuario)
            .filter(siape=siape)
            .exists()
        ):
            raise forms.ValidationError("Já existe um professor cadastrado com este SIAPE.")
        return siape


class FormularioConvite(MisturaAcessibilidadeFormulario, forms.Form):
    """Formulário de convite do painel da coordenação (T11). `papel` reusa
    `Convite.PAPEIS_CONVIDAVEIS` (só aluno/professor — SUGRAD nunca é
    convidado, ver `services.convidar`) em vez de repetir a lista, para as
    duas opções nunca divergirem. Herda `MisturaAcessibilidadeFormulario`
    pelo mesmo motivo de `FormularioPerfil` (T10): mesma ligação de
    aria-invalid/aria-describedby depois da validação, sem duplicar a
    lógica."""

    email = forms.EmailField(label="E-mail")
    papel = forms.ChoiceField(label="Papel", choices=Convite.PAPEIS_CONVIDAVEIS)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # `aplica_estilo` (chamado por `MisturaAcessibilidadeFormulario.__init__`)
        # não trata `Select` (só campos de texto e upload): o <select> do
        # papel precisa da classe do DaisyUI 5 à parte. Sem sufixo
        # "-bordered", igual a `.input`/`.file-input` — a v5 já nasce com
        # borda visível.
        self.fields["papel"].widget.attrs.setdefault("class", "select w-full")
