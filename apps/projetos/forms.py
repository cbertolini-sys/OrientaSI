from django import forms
from django.core.exceptions import ValidationError

from apps.comum.validators import (
    valida_extensao_editavel,
    valida_extensao_pdf,
    valida_tamanho_arquivo,
)
from apps.contas.forms import MisturaAcessibilidadeFormulario
from apps.contas.models import Area, PerfilProfessor
from apps.projetos.models import Projeto, Tema


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


class _CampoTema(forms.ModelChoiceField):
    """`ModelChoiceField` que rotula cada opção como "título — professor",
    em vez do `Tema.__str__` padrão (só o título, `apps/projetos/models.py`)
    — o aluno escolhe entre temas de professores diferentes em
    `FormularioCandidatura`, abaixo, e o título sozinho não deixa claro quem
    orienta cada um."""

    def label_from_instance(self, tema):
        return f"{tema.titulo} — {tema.professor.usuario.nome_completo}"


class FormularioCandidatura(MisturaAcessibilidadeFormulario, forms.Form):
    """Formulário de montagem da candidatura do aluno (T11, spec §6:
    "/candidatura/" — "montar, acompanhar e cancelar"): até três `Tema`s
    ativos, em ordem de preferência.

    ESCOPO DA ESCOLHA (decisão do controlador desta tarefa, não lacuna do
    spec): só oferece `Tema`, nunca "professor sem tema específico". O
    modelo permite `tema=None` em `OpcaoCandidatura`
    (`services.registrar_candidatura`, T8, continua aceitando esse caminho —
    não é removido nem proibido lá), mas não existe hoje nenhuma tela de
    navegação por professor no sistema: o mural inteiro (T7,
    `services.temas_do_mural`) é organizado por `Tema`. Construir um segundo
    mecanismo de busca só para o caso "professor sem tema" duplicaria a
    organização do mural sem que esta tarefa pedisse — a view
    (`apps/projetos/views.py::candidatura`) deriva `professor` de
    `tema.professor` ao montar `opcoes` para o serviço.

    TRÊS CAMPOS NOMEADOS, não um único campo de seleção múltipla: a ORDEM em
    que o aluno preenche `opcao_1`/`opcao_2`/`opcao_3` É a ordem da cascata
    (spec §5.2). Um único `<select multiple>` devolveria ao Django os valores
    marcados na ordem em que aparecem NO WIDGET, não na ordem em que a
    pessoa clicou — HTML não expõe essa segunda informação de volta ao
    servidor. Três campos evitam o problema por construção, ao custo de um
    formulário um pouco mais verboso.

    Só `opcao_1` é obrigatório (o `required=True` padrão de
    `ModelChoiceField`); `opcao_2`/`opcao_3` são opcionais. `clean()` recusa
    um "buraco" (`opcao_3` preenchido sem `opcao_2`): sem essa regra, o que a
    view faria da 3ª opção isolada seria ambíguo — comprimi-la para a 2ª
    posição reescreveria, em silêncio, a prioridade que o aluno declarou.

    A checagem de PROFESSOR REPETIDO aqui é só uma mensagem legível ANTES do
    POST — `services.registrar_candidatura` já recusa professor repetido
    com sua própria `ValidationError`, que continua sendo quem decide de
    fato (este formulário não a substitui, só evita o round-trip ao servidor
    para o caso mais comum). TEMA REPETIDO não tem checagem própria: como
    `Tema.professor` é uma FK fixa, dois campos apontando para o MESMO Tema
    já apontam para o MESMO professor — a checagem de professor repetido,
    abaixo, cobre os dois casos por construção, sem duplicar a regra.
    """

    opcao_1 = _CampoTema(
        label="1ª opção",
        queryset=Tema.objects.filter(ativo=True)
        .select_related("professor__usuario")
        .order_by("titulo", "pk"),
        widget=forms.Select(attrs={"class": "select w-full"}),
    )
    opcao_2 = _CampoTema(
        label="2ª opção",
        queryset=Tema.objects.filter(ativo=True)
        .select_related("professor__usuario")
        .order_by("titulo", "pk"),
        required=False,
        widget=forms.Select(attrs={"class": "select w-full"}),
    )
    opcao_3 = _CampoTema(
        label="3ª opção",
        queryset=Tema.objects.filter(ativo=True)
        .select_related("professor__usuario")
        .order_by("titulo", "pk"),
        required=False,
        widget=forms.Select(attrs={"class": "select w-full"}),
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("opcao_3") and not cleaned.get("opcao_2"):
            raise ValidationError("Preencha a 2ª opção antes de escolher uma 3ª.")

        temas_escolhidos = [
            cleaned[nome]
            for nome in ("opcao_1", "opcao_2", "opcao_3")
            if cleaned.get(nome) is not None
        ]
        professores_escolhidos = [tema.professor_id for tema in temas_escolhidos]
        if len(professores_escolhidos) != len(set(professores_escolhidos)):
            raise ValidationError(
                "Cada professor só pode aparecer uma vez na candidatura — escolha temas de "
                "professores diferentes."
            )
        return cleaned


class FormularioTrocarOrientador(MisturaAcessibilidadeFormulario, forms.Form):
    """Formulário de troca de orientador de um `Projeto` (T12, painel da
    coordenação — spec §6: "/painel/orientacoes/ | coordenação | visão
    geral, troca de orientador, limites").

    A view instancia um formulário POR projeto listado no painel, com
    `auto_id` próprio (mesmo padrão de `FormularioRecusaOpcao`, acima) —
    sem isso, o `id` do campo "novo_orientador" se repetiria a cada `<li>`
    da lista de projetos.

    `projeto=` no construtor exclui o ORIENTADOR ATUAL do `<select>`: a
    troca é sempre PARA outro professor. Oferecer o próprio orientador como
    opção levaria `services.trocar_orientador` a contar a vaga já ocupada
    por ESTE projeto contra o teto do próprio professor (ver a LACUNA
    REGISTRADA na docstring daquele serviço) — excluir a opção evita o caso
    aqui, na tela, sem exigir uma checagem nova no serviço para um cenário
    que esta tela nunca oferece.
    """

    novo_orientador = forms.ModelChoiceField(
        label="Novo orientador",
        queryset=PerfilProfessor.objects.select_related("usuario").order_by(
            "usuario__nome_completo"
        ),
        widget=forms.Select(attrs={"class": "select w-full"}),
    )

    def __init__(self, *args, projeto=None, **kwargs):
        super().__init__(*args, **kwargs)
        if projeto is not None:
            self.fields["novo_orientador"].queryset = self.fields[
                "novo_orientador"
            ].queryset.exclude(usuario=projeto.orientador)


class FormularioConcederLimite(MisturaAcessibilidadeFormulario, forms.Form):
    """Formulário de concessão de limite elevado de vagas a um professor
    (T12, painel da coordenação — spec §3.6).

    `limite` só recebe `min_value=1` aqui — a recusa de um limite menor ou
    igual a `LIMITE_PADRAO_VAGAS` é regra de NEGÓCIO
    (`services.conceder_limite`, que conhece a constante), não validação de
    formulário: `min_value=1` é só a primeira linha de defesa contra um
    valor obviamente errado (negativo ou zero), e a mensagem específica
    ("precisa ser maior que 3") vem do serviço.
    """

    professor = forms.ModelChoiceField(
        label="Professor",
        queryset=PerfilProfessor.objects.select_related("usuario").order_by(
            "usuario__nome_completo"
        ),
        widget=forms.Select(attrs={"class": "select w-full"}),
    )
    etapa = forms.ChoiceField(
        label="Etapa",
        choices=Projeto.ETAPAS,
        widget=forms.Select(attrs={"class": "select w-full"}),
    )
    limite = forms.IntegerField(
        label="Novo limite de vagas",
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "input w-full"}),
    )
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


class FormularioSubmissao(MisturaAcessibilidadeFormulario, forms.Form):
    """Envio/reenvio do trabalho escrito (Bloco C). `MisturaAcessibilidadeFormulario`
    já detecta `ClearableFileInput` e aplica `.file-input w-full`
    (`apps/contas/forms.py::aplica_estilo`) — nenhum `widget=` explícito
    precisa ser passado aqui. Sem `autocomplete` nos dois campos: nenhum
    token da lista de "input purposes" do WHATWG/WCAG 2.1 (critério 1.3.5)
    serve para upload de arquivo (mesmo raciocínio de `FormularioConvidado.foto`,
    `apps/contas/forms.py`)."""

    pdf = forms.FileField(
        label="PDF",
        validators=[valida_extensao_pdf, valida_tamanho_arquivo],
    )
    editavel = forms.FileField(
        label="Editável (.docx)",
        validators=[valida_extensao_editavel, valida_tamanho_arquivo],
    )
