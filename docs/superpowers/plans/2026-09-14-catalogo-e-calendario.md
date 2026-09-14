# Bloco G: Catálogo e Calendário Públicos — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expor duas telas públicas (sem login) — `/catalogo/` (TCCs concluídos
para download) e `/calendario/` (apresentações futuras) — sobre `Projeto`/
`Banca` já existentes, sem modelo novo.

**Architecture:** Nova app `apps/publico`, sem models próprios, com um
`services.py` de duas consultas (`catalogo_publico`, `calendario_publico`).
Reabre parte do Bloco F: `Projeto.tema` (existente desde o Bloco B) passa a
ser usado também pelo TCC_II, como fonte de Título/Resumo do catálogo — sem
campos novos. Reabre `enviar_submissao` (Bloco C) para aceitar reenvio
pós-banca no TCC_II, e corrige um bug latente de 500 encontrado em `meu_tcc`
no processo.

**Tech Stack:** Django 5 (views baseadas em função, templates), sem HTMX (as
duas telas são GET simples), `django-storages`/S3 (URLs pré-assinadas já
funcionam sem sessão — nada novo a configurar).

**Spec:** `docs/superpowers/specs/2026-09-14-catalogo-e-calendario-design.md`

## Global Constraints

- Todo identificador de código é em português; interface, mensagens e
  commits também (CLAUDE.md).
- Regra de negócio complexa fica em `services.py`; `views.py`/`models.py`
  não têm regra de negócio (CLAUDE.md, regra 4; spec §9).
- Nenhum dado sensível (CPF, telefone, e-mail) exposto nas telas públicas
  (CLAUDE.md, regra 6; spec §6).
- Toda tela nova entra em `conftest.py::ROTAS` para as cinco suítes
  transversais (acessibilidade, toque, responsivo, teclado, rotas).
- Toda checagem nova é provada por mutação antes de seguir em frente
  (CLAUDE.md, "Disciplina de Testes").

---

## Task 1: TCC_II ganha `tema` (reabertura do Bloco F)

**Files:**
- Modify: `apps/projetos/services.py:1354-1396` (`criar_tcc_ii_automatico`,
  `criar_tcc_ii_manual`)
- Modify: `apps/projetos/forms.py` (`FormularioCriarTccII`, linhas ~271-281)
- Modify: `apps/projetos/views.py:706-731` (`criar_tcc_ii_manual_view`)
- Test: `apps/projetos/tests/test_tcc_ii.py`

**Interfaces:**
- Produz: `criar_tcc_ii_manual(aluno, professor, tema, por)` — assinatura
  muda de `(aluno, professor, por)` para incluir `tema` como terceiro
  parâmetro posicional, antes de `por` (que continua *keyword-only* por
  convenção de todo chamador existente). Tarefas seguintes (nenhuma neste
  plano consome isto diretamente) devem usar a nova assinatura.
- Consome: nada de tarefas futuras deste plano.

- [ ] **Step 1: Atualizar os testes existentes de `criar_tcc_ii_manual` (vão quebrar até o Step 3)**

Em `apps/projetos/tests/test_tcc_ii.py`, adicione os imports que faltam e um
helper `_tema`:

```python
from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
```

(troque a linha existente `from apps.contas.models import PerfilAluno,
PerfilProfessor, Usuario` por esta, acrescentando `Area`)

```python
from apps.projetos.models import Projeto, Tema, TermoPublicacao
```

(troque a linha existente `from apps.projetos.models import Projeto,
TermoPublicacao` por esta, acrescentando `Tema`)

Acrescente, logo depois de `_aluno`:

```python
def _tema(indice, professor, titulo="Tema TCC II de Teste"):
    area = Area.objects.create(nome=f"Área TCC II {indice}")
    return Tema.objects.create(
        professor=professor, area=area, titulo=titulo, descricao="Descrição de teste."
    )
```

Agora troque cada um dos quatro testes que chamam `criar_tcc_ii_manual`:

```python
@pytest.mark.django_db
def test_criar_tcc_ii_manual_cria_sem_anterior():
    orientador = _professor(20, "Orientador Manual")
    aluno = _aluno(21, "Aluno Manual")
    tema = _tema(20, orientador)
    tcc_ii = services.criar_tcc_ii_manual(aluno.perfil_aluno, orientador, tema, por=orientador.usuario)
    assert tcc_ii.anterior is None
    assert tcc_ii.etapa == Projeto.TCC_II
    assert tcc_ii.orientador_id == orientador.usuario_id
    assert tcc_ii.tema_id == tema.id
```

```python
@pytest.mark.django_db
def test_criar_tcc_ii_manual_recusa_quem_nao_e_o_professor():
    orientador = _professor(22, "Orientador Manual Dois")
    outro = _professor(23, "Outro Professor Manual")
    aluno = _aluno(24, "Aluno Manual Dois")
    tema = _tema(22, orientador)
    with pytest.raises(PermissionDenied):
        services.criar_tcc_ii_manual(aluno.perfil_aluno, orientador, tema, por=outro.usuario)
```

```python
@pytest.mark.django_db
def test_criar_tcc_ii_manual_recusa_professor_no_limite():
    from apps.comum.semestre import semestre_vigente

    orientador = _professor(25, "Orientador Manual Limite")
    tema = _tema(25, orientador)
    ano, periodo = semestre_vigente()
    for indice in (26, 27, 28):
        Projeto.objects.create(
            aluno=_aluno(indice, f"Aluno Limite Manual {indice}"),
            orientador=orientador.usuario,
            etapa=Projeto.TCC_II,
            status=Projeto.EM_ANDAMENTO,
            ano=ano,
            periodo=periodo,
        )
    aluno_novo = _aluno(29, "Aluno Manual Recusado")
    with pytest.raises(ValidationError):
        services.criar_tcc_ii_manual(aluno_novo.perfil_aluno, orientador, tema, por=orientador.usuario)
```

```python
@pytest.mark.django_db
def test_criar_tcc_ii_manual_view_redireciona(client):
    orientador = _professor(30, "Orientador Manual View")
    aluno = _aluno(31, "Aluno Manual View")
    tema = _tema(30, orientador)
    client.force_login(orientador.usuario)
    resposta = client.post("/temas/tcc-ii/criar/", {"aluno": aluno.perfil_aluno.pk, "tema": tema.pk})
    assert resposta.status_code == 302
    assert Projeto.objects.filter(
        aluno=aluno, etapa=Projeto.TCC_II, orientador=orientador.usuario, tema=tema
    ).exists()
```

E o teste de notificação, perto do fim do arquivo:

```python
@pytest.mark.django_db
def test_criar_tcc_ii_manual_notifica_aluno(settings, django_capture_on_commit_callbacks):
    from django.core import mail

    orientador = _professor(70, "Orientador Notif Manual")
    aluno = _aluno(71, "Aluno Notif Manual")
    tema = _tema(70, orientador)
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with django_capture_on_commit_callbacks(execute=True):
        services.criar_tcc_ii_manual(aluno.perfil_aluno, orientador, tema, por=orientador.usuario)
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [aluno.email]
```

- [ ] **Step 2: Rodar e confirmar que os quatro testes acima falham (assinatura antiga)**

Run: `docker compose exec web pytest apps/projetos/tests/test_tcc_ii.py -k manual -v`
Expected: `TypeError: criar_tcc_ii_manual() takes 3 positional arguments but 4 were given` (ou equivalente) em cada um.

- [ ] **Step 3: Estender `criar_tcc_ii_automatico` para copiar `tema`**

Em `apps/projetos/services.py`, dentro de `criar_tcc_ii_automatico`, no
`Projeto.objects.create(...)`, acrescente `tema=projeto_tcc_i.tema,` junto
das outras cópias:

```python
    tcc_ii = Projeto.objects.create(
        aluno=projeto_tcc_i.aluno,
        orientador=projeto_tcc_i.orientador,
        tema=projeto_tcc_i.tema,
        coorientador=projeto_tcc_i.coorientador,
        coorientador_externo=projeto_tcc_i.coorientador_externo,
        etapa=Projeto.TCC_II,
        status=Projeto.EM_ANDAMENTO,
        anterior=projeto_tcc_i,
        ano=ano,
        periodo=periodo,
    )
```

E atualize a docstring da função, trocando a frase final `"NÃO checa limite
de vagas (...)"` para acrescentar, no fim: `"Copia também \`tema\` — se o
TCC I nasceu de uma candidatura aberta (sem tema pré-publicado), o TCC II
herda \`tema=None\` do mesmo jeito; sem tema, o catálogo (Bloco G) não
publica este TCC II."`

- [ ] **Step 4: Mudar a assinatura de `criar_tcc_ii_manual` para exigir `tema`**

Troque o corpo inteiro da função por:

```python
def criar_tcc_ii_manual(aluno, professor, tema, por):
    """Cria um TCC II do zero, sem TCC I anterior no sistema — comprova
    equivalência externa (Bloco F, spec §3.2). Casca fina sobre
    `criar_projeto_sob_limite` (Bloco B, linha 68): reaproveita a checagem
    de vaga testada contra corrida em vez de duplicá-la. `tema` é
    obrigatório e precisa ser um dos próprios temas de `professor` (Bloco
    G, spec §2) — fonte de Título/Resumo no catálogo público; a checagem de
    posse é feita aqui, não só no formulário, porque o formulário não é o
    único chamador possível desta função."""
    if not permissions.pode_criar_tcc_ii_manual(por, professor):
        raise PermissionDenied("Somente o próprio professor cria um TCC II em seu nome.")
    if tema.professor_id != professor.id:
        raise PermissionDenied("O tema precisa ser um dos seus próprios temas.")

    tcc_ii = criar_projeto_sob_limite(aluno, professor, tema=tema, etapa=Projeto.TCC_II)

    from apps.projetos.tasks import enviar_tcc_ii_criado

    transaction.on_commit(lambda: enviar_tcc_ii_criado.delay(tcc_ii.id))

    return tcc_ii
```

- [ ] **Step 5: Rodar e confirmar que os quatro testes do Step 1 agora passam**

Run: `docker compose exec web pytest apps/projetos/tests/test_tcc_ii.py -k manual -v`
Expected: todos `PASSED`.

- [ ] **Step 6: Escrever o teste de cópia de tema (automático) — falhando primeiro por mutação**

Acrescente em `apps/projetos/tests/test_tcc_ii.py`, perto de
`test_criar_tcc_ii_automatico_copia_coorientador`:

```python
@pytest.mark.django_db
def test_criar_tcc_ii_automatico_copia_tema(projeto_tcc_i):
    tema = _tema(8, projeto_tcc_i.orientador.perfil_professor)
    projeto_tcc_i.tema = tema
    projeto_tcc_i.save()
    tcc_ii = services.criar_tcc_ii_automatico(projeto_tcc_i)
    assert tcc_ii.tema_id == tema.id
```

Run: `docker compose exec web pytest apps/projetos/tests/test_tcc_ii.py::test_criar_tcc_ii_automatico_copia_tema -v`
Expected: `PASSED` (o Step 3 já fez a mudança) — se `FAILED`, o Step 3 não
foi aplicado corretamente, corrija antes de seguir.

**Prova por mutação:** comente a linha `tema=projeto_tcc_i.tema,` do Step 3,
rode o teste de novo — Expected: `FAILED` (`tcc_ii.tema_id` é `None`).
Restaure a linha, rode de novo — Expected: `PASSED`.

- [ ] **Step 7: Escrever o teste de posse do tema (manual) — mutation-provable**

```python
@pytest.mark.django_db
def test_criar_tcc_ii_manual_recusa_tema_de_outro_professor():
    orientador = _professor(60, "Orientador Manual Tema Alheio")
    outro_professor = _professor(61, "Outro Professor Tema Alheio")
    aluno = _aluno(62, "Aluno Manual Tema Alheio")
    tema_alheio = _tema(60, outro_professor)
    with pytest.raises(PermissionDenied):
        services.criar_tcc_ii_manual(
            aluno.perfil_aluno, orientador, tema_alheio, por=orientador.usuario
        )
```

Run: `docker compose exec web pytest apps/projetos/tests/test_tcc_ii.py::test_criar_tcc_ii_manual_recusa_tema_de_outro_professor -v`
Expected: `PASSED`.

**Prova por mutação:** comente as duas linhas do `if tema.professor_id !=
professor.id:` no Step 4, rode de novo — Expected: `FAILED` (nenhuma
exceção levantada). Restaure, rode de novo — Expected: `PASSED`.

- [ ] **Step 8: Adicionar o campo `tema` ao formulário de criação manual**

Em `apps/projetos/forms.py`, troque `FormularioCriarTccII` inteiro por:

```python
class FormularioCriarTccII(MisturaAcessibilidadeFormulario, forms.Form):
    """Criação manual do TCC II, pra comprovar equivalência externa (Bloco
    F, spec §7). `aluno` lista TODO `PerfilAluno` — sem pré-filtrar quem já
    tem TCC II ativo: `criar_projeto_sob_limite` já recusa com mensagem
    clara via `UniqueConstraint` (`IntegrityError` traduzido, Bloco B),
    então filtrar aqui seria duplicar essa proteção sem necessidade. `tema`
    nasce com queryset vazio, mesmo padrão de `FormularioTema.area`: a view
    passa `professor=` no construtor, e só então o campo lista os temas
    DESSE professor (Bloco G, spec §2) — sem essa restrição por instância,
    o professor poderia escolher o tema de outro (a checagem de posse em
    `services.criar_tcc_ii_manual` recusaria, mas o formulário já evita
    oferecer a opção errada)."""

    aluno = forms.ModelChoiceField(
        label="Aluno",
        queryset=PerfilAluno.objects.select_related("usuario").order_by("usuario__nome_completo"),
        widget=forms.Select(attrs={"class": "select w-full"}),
    )
    tema = forms.ModelChoiceField(
        label="Tema",
        queryset=Tema.objects.none(),
        widget=forms.Select(attrs={"class": "select w-full"}),
    )

    def __init__(self, *args, professor=None, **kwargs):
        super().__init__(*args, **kwargs)
        if professor is not None:
            self.fields["tema"].queryset = Tema.objects.filter(professor=professor)
```

- [ ] **Step 9: Passar `professor=` ao formulário e `tema` ao serviço na view**

Em `apps/projetos/views.py`, troque `criar_tcc_ii_manual_view` inteira por:

```python
@login_required
def criar_tcc_ii_manual_view(request):
    """Professor cria um TCC II manualmente (Bloco F, spec §7). Portão de
    PAPEL primeiro (`pode_criar_tema`, mesmo reaproveitamento de
    `orientacoes`/`meus_temas` — ela só pergunta "é professor?"), antes de
    tocar `perfil_professor`. `tema` (Bloco G) vem do formulário, já
    restrito aos temas do próprio `professor` (`FormularioCriarTccII`)."""
    permissions.garante(
        permissions.pode_criar_tema(request.user), "Somente professores criam TCC II."
    )
    professor = request.user.perfil_professor

    if request.method == "POST":
        formulario = FormularioCriarTccII(request.POST, professor=professor)
        if formulario.is_valid():
            try:
                services.criar_tcc_ii_manual(
                    formulario.cleaned_data["aluno"],
                    professor,
                    formulario.cleaned_data["tema"],
                    por=request.user,
                )
            except ValidationError as erro:
                formulario.add_error(None, erro.messages[0])
            else:
                messages.success(request, "TCC II criado.")
                return redirect("projetos:orientacoes")
    else:
        formulario = FormularioCriarTccII(professor=professor)

    return render(request, "projetos/criar_tcc_ii.html", {"formulario": formulario})
```

Nenhuma mudança de template é necessária: `templates/projetos/criar_tcc_ii.html`
já itera `{% for campo in formulario %}` genericamente — o campo `tema`
aparece automaticamente.

- [ ] **Step 10: Rodar a suíte inteira de `test_tcc_ii.py`**

Run: `docker compose exec web pytest apps/projetos/tests/test_tcc_ii.py -v`
Expected: todos `PASSED`.

- [ ] **Step 11: `ruff`, `black`, e commit**

```bash
docker compose exec web ruff check .
docker compose exec web black .
git add apps/projetos/services.py apps/projetos/forms.py apps/projetos/views.py apps/projetos/tests/test_tcc_ii.py
git commit -m "Tarefa 1: TCC_II ganha tema (herdado ou escolhido pelo professor)"
```

---

## Task 2: Reabertura de `enviar_submissao` + correção do bug em `meu_tcc`

**Files:**
- Modify: `apps/projetos/services.py:470-506` (`enviar_submissao`)
- Modify: `apps/projetos/views.py:456-526` (`meu_tcc`)
- Test: `apps/projetos/tests/test_submissao.py`
- Test: `apps/projetos/tests/test_tela_meu_tcc.py`

**Interfaces:**
- Consome: nada da Task 1.
- Produz: nada consumido por tasks futuras (Tasks 3-6 são independentes
  disto).

- [ ] **Step 1: Escrever os testes de serviço (falhando)**

Em `apps/projetos/tests/test_submissao.py`, acrescente, depois de
`projeto_em_andamento`:

```python
@pytest.fixture
def projeto_tcc_ii_com_ressalvas(db):
    aluno_usuario = Usuario.objects.create_user(
        email="aluno.submissao.tccii@ufsm.br",
        password="x",
        nome_completo="Aluno Submissão TCC II",
        papel=Usuario.ALUNO,
        cpf=_cpf_valido(950000006),
    )
    PerfilAluno.objects.create(usuario=aluno_usuario, matricula="2026SUB0006")
    professor_usuario = Usuario.objects.create_user(
        email="professor.submissao.tccii@ufsm.br",
        password="x",
        nome_completo="Professor Submissão TCC II",
        cpf=_cpf_valido(950000007),
    )
    PerfilProfessor.objects.create(usuario=professor_usuario, siape="9500007")
    return Projeto.objects.create(
        aluno=aluno_usuario,
        orientador=professor_usuario,
        etapa=Projeto.TCC_II,
        status=Projeto.APROVADO_COM_RESSALVAS,
        ano=2026,
        periodo=2,
    )
```

E, no fim do arquivo:

```python
@pytest.mark.django_db
def test_enviar_submissao_aceita_reenvio_em_aprovado_com_ressalvas_para_tcc_ii(
    projeto_tcc_ii_com_ressalvas,
):
    submissao = services.enviar_submissao(
        projeto_tcc_ii_com_ressalvas,
        por=projeto_tcc_ii_com_ressalvas.aluno,
        pdf=_arquivo("corrigido.pdf"),
        editavel=_arquivo("corrigido.docx"),
    )
    assert submissao.versao == 1


@pytest.mark.django_db
def test_enviar_submissao_recusa_tcc_ii_fora_dos_status_permitidos(projeto_tcc_ii_com_ressalvas):
    """Mutação obrigatória: prova que a exceção é específica de
    `APROVADO_COM_RESSALVAS`, não "qualquer status" para TCC_II."""
    projeto_tcc_ii_com_ressalvas.status = Projeto.AGUARDANDO_DEFESA
    projeto_tcc_ii_com_ressalvas.save(update_fields=["status"])
    with pytest.raises(ValidationError):
        services.enviar_submissao(
            projeto_tcc_ii_com_ressalvas,
            por=projeto_tcc_ii_com_ressalvas.aluno,
            pdf=_arquivo("v1.pdf"),
            editavel=_arquivo("v1.docx"),
        )
```

- [ ] **Step 2: Rodar e confirmar que o primeiro teste falha**

Run: `docker compose exec web pytest apps/projetos/tests/test_submissao.py -k aceita_reenvio_em_aprovado -v`
Expected: `FAILED` com `ValidationError` (o código antigo recusa qualquer
status que não seja `EM_ANDAMENTO`).

- [ ] **Step 3: Estender a checagem de status em `enviar_submissao`**

Em `apps/projetos/services.py`, troque:

```python
    if projeto.status != Projeto.EM_ANDAMENTO:
        raise ValidationError(
            "Este projeto não está mais em andamento — não é possível enviar ou "
            "reenviar a submissão."
        )
```

por:

```python
    status_permitidos = [Projeto.EM_ANDAMENTO]
    if projeto.etapa == Projeto.TCC_II:
        status_permitidos.append(Projeto.APROVADO_COM_RESSALVAS)
    if projeto.status not in status_permitidos:
        raise ValidationError(
            "Este projeto não está mais em andamento — não é possível enviar ou "
            "reenviar a submissão."
        )
```

E acrescente ao final da docstring de `enviar_submissao`: `"Bloco G reabre
esta função: o TCC II também aceita reenvio em \`Aprovado com Ressalvas\`
— é como o aluno deposita a versão corrigida depois da banca (spec §3), pré-requisito para o \"PDF Final\" do catálogo público refletir a correção,
não o rascunho pré-banca."`

- [ ] **Step 4: Rodar e confirmar que os dois testes do Step 1 passam**

Run: `docker compose exec web pytest apps/projetos/tests/test_submissao.py -k "aceita_reenvio_em_aprovado or recusa_tcc_ii_fora" -v`
Expected: ambos `PASSED`.

**Prova por mutação:** no Step 3, troque `if projeto.etapa == Projeto.TCC_II:`
por `if False:` temporariamente, rode
`test_enviar_submissao_aceita_reenvio_em_aprovado_com_ressalvas_para_tcc_ii`
de novo — Expected: `FAILED`. Restaure, confirme `PASSED` de novo.

- [ ] **Step 5: Rodar a suíte inteira de `test_submissao.py` (regressão do TCC_I)**

Run: `docker compose exec web pytest apps/projetos/tests/test_submissao.py -v`
Expected: todos `PASSED`, incluindo
`test_enviar_submissao_recusa_fora_de_em_andamento` (TCC_I continua
recusado fora de `EM_ANDAMENTO` — esse teste não muda).

- [ ] **Step 6: Escrever os testes de VIEW para o bug de 500 e o reenvio (falhando)**

Em `apps/projetos/tests/test_tela_meu_tcc.py`, acrescente ao final:

```python
@pytest.mark.django_db
def test_meu_tcc_permite_reenvio_em_aprovado_com_ressalvas_para_tcc_ii(client):
    from apps.projetos.models import Submissao

    aluno_usuario = Usuario.objects.create_user(
        email="aluno.meutccii.reenvio@ufsm.br",
        password="x",
        nome_completo="Aluno Meu TCC II Reenvio",
        papel=Usuario.ALUNO,
        cpf=_cpf_valido(950000030),
    )
    PerfilAluno.objects.create(usuario=aluno_usuario, matricula="2026MTC0030")
    professor_usuario = Usuario.objects.create_user(
        email="professor.meutccii.reenvio@ufsm.br",
        password="x",
        nome_completo="Professor Meu TCC II Reenvio",
        cpf=_cpf_valido(950000031),
    )
    PerfilProfessor.objects.create(usuario=professor_usuario, siape="9500031")
    Projeto.objects.create(
        aluno=aluno_usuario,
        orientador=professor_usuario,
        etapa=Projeto.TCC_II,
        status=Projeto.APROVADO_COM_RESSALVAS,
        ano=2026,
        periodo=2,
    )

    client.force_login(aluno_usuario)
    resposta = client.post(
        reverse("projetos:meu_tcc"),
        {"pdf": _arquivo("corrigido.pdf"), "editavel": _arquivo("corrigido.docx")},
    )
    assert resposta.status_code == 302
    assert Submissao.objects.filter(projeto__aluno=aluno_usuario).exists()


@pytest.mark.django_db
def test_meu_tcc_recusa_reenvio_tcc_ii_fora_dos_status_permitidos_sem_500(client):
    aluno_usuario = Usuario.objects.create_user(
        email="aluno.meutccii.recusa@ufsm.br",
        password="x",
        nome_completo="Aluno Meu TCC II Recusa",
        papel=Usuario.ALUNO,
        cpf=_cpf_valido(950000032),
    )
    PerfilAluno.objects.create(usuario=aluno_usuario, matricula="2026MTC0032")
    professor_usuario = Usuario.objects.create_user(
        email="professor.meutccii.recusa@ufsm.br",
        password="x",
        nome_completo="Professor Meu TCC II Recusa",
        cpf=_cpf_valido(950000033),
    )
    PerfilProfessor.objects.create(usuario=professor_usuario, siape="9500033")
    Projeto.objects.create(
        aluno=aluno_usuario,
        orientador=professor_usuario,
        etapa=Projeto.TCC_II,
        status=Projeto.AGUARDANDO_DEFESA,
        ano=2026,
        periodo=2,
    )

    client.force_login(aluno_usuario)
    resposta = client.post(
        reverse("projetos:meu_tcc"),
        {"pdf": _arquivo("v1.pdf"), "editavel": _arquivo("v1.docx")},
    )
    assert resposta.status_code == 200
    assert "não é possível enviar ou reenviar" in resposta.content.decode()
```

- [ ] **Step 7: Rodar e confirmar que ambos falham**

Run: `docker compose exec web pytest apps/projetos/tests/test_tela_meu_tcc.py -k "permite_reenvio or recusa_reenvio" -v`
Expected: o primeiro `FAILED` (302 esperado, `ValidationError` não tratado
ainda derruba com 500 — mas como o Step 3/4 desta tarefa já mudou o
serviço, na verdade este teste específico já passaria; o segundo,
`recusa_reenvio_tcc_ii_fora_dos_status_permitidos_sem_500`, é quem prova o
bug: `FAILED` com um 500 hoje, porque a view não captura
`ValidationError`.

- [ ] **Step 8: Corrigir `meu_tcc` para capturar `ValidationError`**

Em `apps/projetos/views.py`, troque:

```python
    if request.method == "POST":
        formulario = FormularioSubmissao(request.POST, request.FILES)
        if formulario.is_valid():
            services.enviar_submissao(
                projeto,
                por=request.user,
                pdf=formulario.cleaned_data["pdf"],
                editavel=formulario.cleaned_data["editavel"],
            )
            messages.success(request, "Submissão enviada com sucesso.")
            return redirect("projetos:meu_tcc")
    else:
        formulario = FormularioSubmissao()
```

por:

```python
    if request.method == "POST":
        formulario = FormularioSubmissao(request.POST, request.FILES)
        if formulario.is_valid():
            try:
                services.enviar_submissao(
                    projeto,
                    por=request.user,
                    pdf=formulario.cleaned_data["pdf"],
                    editavel=formulario.cleaned_data["editavel"],
                )
            except ValidationError as erro:
                formulario.add_error(None, erro.messages[0])
            else:
                messages.success(request, "Submissão enviada com sucesso.")
                return redirect("projetos:meu_tcc")
    else:
        formulario = FormularioSubmissao()
```

(a condição continua igual à original — o bloco `acao == "assinar_termo"`
logo acima sempre termina em `return redirect(...)` quando entra, então
este `if request.method == "POST":` já só é alcançado para o POST de
envio/reenvio de verdade; nenhuma condição extra é necessária aqui, só o
`try/except` em volta da chamada ao serviço.)

- [ ] **Step 9: Rodar e confirmar que os dois testes do Step 6 passam**

Run: `docker compose exec web pytest apps/projetos/tests/test_tela_meu_tcc.py -k "permite_reenvio or recusa_reenvio" -v`
Expected: ambos `PASSED`.

**Prova por mutação:** remova o `try/except` do Step 8 (volte à chamada
direta sem captura), rode
`test_meu_tcc_recusa_reenvio_tcc_ii_fora_dos_status_permitidos_sem_500` de
novo — Expected: `FAILED` (500 em vez de 200). Restaure, confirme `PASSED`.

- [ ] **Step 10: Rodar a suíte inteira de `apps/projetos`**

Run: `docker compose exec web pytest apps/projetos/ -v`
Expected: todos `PASSED`.

- [ ] **Step 11: `ruff`, `black`, e commit**

```bash
docker compose exec web ruff check .
docker compose exec web black .
git add apps/projetos/services.py apps/projetos/views.py apps/projetos/tests/test_submissao.py apps/projetos/tests/test_tela_meu_tcc.py
git commit -m "Tarefa 2: reenvio pos-banca no TCC_II e correcao do 500 em meu_tcc"
```

---

## Task 3: App `apps/publico` — scaffold, wiring e camada de serviço

**Files:**
- Create: `apps/publico/__init__.py`
- Create: `apps/publico/apps.py`
- Create: `apps/publico/services.py`
- Create: `apps/publico/urls.py`
- Create: `apps/publico/views.py` (vazio nesta tarefa — só o suficiente pra
  `urls.py` importar sem erro; Tasks 4/5 preenchem)
- Create: `apps/publico/tests/__init__.py`
- Create: `apps/publico/tests/test_catalogo.py`
- Create: `apps/publico/tests/test_calendario.py`
- Modify: `config/settings.py` (`INSTALLED_APPS`)
- Modify: `config/urls.py` (`include("apps.publico.urls")`)

**Interfaces:**
- Produz: `apps.publico.services.catalogo_publico(area_id=None, ano=None)`
  → queryset de `Projeto`; `apps.publico.services.calendario_publico()` →
  queryset de `Banca`; `apps.publico.services.anos_do_catalogo()` →
  queryset de `int` distintos. Tasks 4 e 5 consomem exatamente estas três
  funções.
- Consome: `Projeto.tema` (Task 1), nada mais de tarefas anteriores.

- [ ] **Step 1: Criar o esqueleto da app**

`apps/publico/__init__.py` (vazio).

`apps/publico/apps.py`:

```python
from django.apps import AppConfig


class PublicoConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.publico"
    verbose_name = "Público"
```

`apps/publico/views.py`:

```python
```

(vazio de propósito — Tasks 4 e 5 acrescentam `catalogo`/`calendario`.)

`apps/publico/urls.py`:

```python
from apps.publico import views  # noqa: F401 — mantém o import válido; Tasks 4/5 usam `views.*`

app_name = "publico"

urlpatterns = []
```

`apps/publico/tests/__init__.py` (vazio).

- [ ] **Step 2: Registrar a app e incluir suas URLs**

Em `config/settings.py`, em `INSTALLED_APPS`, acrescente depois de
`"apps.documentos",`:

```python
    "apps.publico",
```

Em `config/urls.py`, acrescente depois de
`path("", include("apps.documentos.urls")),`:

```python
    path("", include("apps.publico.urls")),
```

- [ ] **Step 3: Rodar a suíte inteira pra confirmar que nada quebrou com a app vazia**

Run: `docker compose exec web pytest -q`
Expected: todos `PASSED` (nenhum teste novo ainda).

- [ ] **Step 4: Escrever os testes de `catalogo_publico` (falhando)**

Crie `apps/publico/tests/test_catalogo.py`:

```python
"""Testes do Bloco G: `catalogo_publico`/`anos_do_catalogo`
(`apps/publico/services.py`)."""

import pytest
from django.utils import timezone

from apps.bancas.models import Banca
from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.documentos.models import Ata, RevisaoSUGRAD
from apps.projetos.models import Projeto, Submissao, Tema, TermoPublicacao
from apps.publico import services


def _cpf(indice):
    base = f"{840000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _projeto_catalogavel(
    indice,
    *,
    area=None,
    ano=2026,
    decidida_em=None,
    com_tema=True,
    com_termo=True,
    etapa=Projeto.TCC_II,
    status=Projeto.CONCLUIDO,
):
    """Monta um `Projeto` diretamente no estado-alvo (não percorre o fluxo
    real de banca→ata→SUGRAD) — mesmo padrão já usado em
    `apps/documentos/tests/test_revisao.py` e `test_notificacoes.py` pra
    fixtures de "TCC II concluído". Os `*_kwargs` permitem cada teste
    desligar exatamente UMA das quatro condições de elegibilidade (spec
    §1) sem duplicar o resto da montagem."""
    orientador = Usuario.objects.create_user(
        email=f"orientador.catalogo.{indice}@ufsm.br",
        password="x",
        nome_completo=f"Orientador Catálogo {indice}",
        cpf=_cpf(indice * 10 + 1),
    )
    perfil_orientador = PerfilProfessor.objects.create(usuario=orientador, siape=f"CAT{indice:03d}")
    tema_area = area or Area.objects.create(nome=f"Área Catálogo {indice}")
    if area is not None:
        perfil_orientador.areas.add(area)
    aluno = Usuario.objects.create_user(
        email=f"aluno.catalogo.{indice}@ufsm.br",
        password="x",
        nome_completo=f"Aluno Catálogo {indice}",
        papel=Usuario.ALUNO,
        cpf=_cpf(indice * 10 + 2),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula=f"2026CAT{indice:03d}")
    tema = None
    if com_tema:
        tema = Tema.objects.create(
            professor=perfil_orientador,
            area=tema_area,
            titulo=f"Título do TCC {indice}",
            descricao=f"Resumo do TCC {indice}.",
        )
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador,
        tema=tema,
        etapa=etapa,
        status=status,
        ano=ano,
        periodo=1,
    )
    Submissao.objects.create(
        projeto=projeto,
        pdf=f"submissoes/catalogo-{indice}.pdf",
        editavel=f"submissoes/catalogo-{indice}.docx",
    )
    if com_termo:
        TermoPublicacao.objects.create(projeto=projeto)
    banca = Banca.objects.create(
        projeto=projeto,
        data_hora=timezone.now(),
        local="Sala Catálogo",
        status=Banca.REALIZADA,
        nota=9.0,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
    )
    ata = Ata.objects.create(
        projeto=projeto, banca=banca, numero=f"{indice:03d}/2026", pdf="atas/catalogo.pdf"
    )
    RevisaoSUGRAD.objects.create(
        ata=ata, status=RevisaoSUGRAD.APROVADA, decidida_em=decidida_em or timezone.now()
    )
    return projeto


@pytest.mark.django_db
def test_catalogo_publico_mostra_tcc_ii_concluido_com_termo_e_tema():
    projeto = _projeto_catalogavel(1)
    assert projeto in services.catalogo_publico()


@pytest.mark.django_db
def test_catalogo_publico_esconde_tcc_i():
    projeto = _projeto_catalogavel(2, etapa=Projeto.TCC_I)
    assert projeto not in services.catalogo_publico()


@pytest.mark.django_db
def test_catalogo_publico_esconde_nao_concluido():
    projeto = _projeto_catalogavel(3, status=Projeto.APROVADO)
    assert projeto not in services.catalogo_publico()


@pytest.mark.django_db
def test_catalogo_publico_esconde_sem_termo():
    projeto = _projeto_catalogavel(4, com_termo=False)
    assert projeto not in services.catalogo_publico()


@pytest.mark.django_db
def test_catalogo_publico_esconde_sem_tema():
    projeto = _projeto_catalogavel(5, com_tema=False)
    assert projeto not in services.catalogo_publico()


@pytest.mark.django_db
def test_catalogo_publico_filtra_por_area():
    area = Area.objects.create(nome="Área Filtro Catálogo")
    outra_area = Area.objects.create(nome="Outra Área Filtro Catálogo")
    projeto_na_area = _projeto_catalogavel(6, area=area)
    projeto_fora = _projeto_catalogavel(7, area=outra_area)
    resultado = services.catalogo_publico(area_id=area.pk)
    assert projeto_na_area in resultado
    assert projeto_fora not in resultado


@pytest.mark.django_db
def test_catalogo_publico_filtra_por_ano():
    projeto_2025 = _projeto_catalogavel(8, ano=2025)
    projeto_2026 = _projeto_catalogavel(9, ano=2026)
    resultado = services.catalogo_publico(ano=2025)
    assert projeto_2025 in resultado
    assert projeto_2026 not in resultado


@pytest.mark.django_db
def test_catalogo_publico_ordena_mais_recente_primeiro():
    antigo = _projeto_catalogavel(10, decidida_em=timezone.now() - timezone.timedelta(days=30))
    recente = _projeto_catalogavel(11, decidida_em=timezone.now())
    resultado = list(services.catalogo_publico())
    assert resultado.index(recente) < resultado.index(antigo)


@pytest.mark.django_db
def test_anos_do_catalogo_lista_anos_distintos_mais_recente_primeiro():
    _projeto_catalogavel(13, ano=2024)
    _projeto_catalogavel(14, ano=2026)
    _projeto_catalogavel(15, ano=2024)
    assert list(services.anos_do_catalogo()) == [2026, 2024]
```

- [ ] **Step 5: Rodar e confirmar que todos falham (`services.py` não existe ainda)**

Run: `docker compose exec web pytest apps/publico/tests/test_catalogo.py -v`
Expected: `FAILED` em todos com `ModuleNotFoundError` ou `AttributeError`
(nenhuma função em `apps.publico.services` existe ainda).

- [ ] **Step 6: Implementar `catalogo_publico`/`anos_do_catalogo`**

Crie `apps/publico/services.py`:

```python
from apps.bancas.models import Banca
from apps.projetos.models import Projeto


def _projetos_catalogaveis():
    """Projetos elegíveis pro catálogo, sem os filtros de área/ano (Bloco
    G, spec §1): TCC_II, Concluído, termo de publicação assinado, com tema
    (fonte de Título/Resumo — um TCC_II herdado de um TCC_I de candidatura
    aberta pode não ter tema, e por isso fica de fora)."""
    return Projeto.objects.filter(
        etapa=Projeto.TCC_II,
        status=Projeto.CONCLUIDO,
        termo_publicacao__isnull=False,
        tema__isnull=False,
    )


def catalogo_publico(area_id=None, ano=None):
    """Lista pública de TCCs concluídos (Bloco G, spec §5). Mais recente
    primeiro — a data em que a SUGRAD aprovou a ata, não a de criação do
    projeto (`atas__revisao__decidida_em`: `Ata.projeto` tem
    `related_name="atas"`, `RevisaoSUGRAD.ata` tem `related_name="revisao"`
    — ambos de apps/documentos/models.py). `area_id` filtra pela área do
    ORIENTADOR (`PerfilProfessor.areas`, M2M), não por `tema.area`
    diretamente — mesma fonte usada em outros pontos do sistema, e não
    depende de `tema` estar presente (embora aqui sempre esteja, pelo
    filtro de `_projetos_catalogaveis`)."""
    qs = (
        _projetos_catalogaveis()
        .select_related("tema", "aluno", "orientador", "submissao")
        .order_by("-atas__revisao__decidida_em")
    )
    if area_id:
        qs = qs.filter(orientador__perfil_professor__areas=area_id)
    if ano:
        qs = qs.filter(ano=ano)
    return qs


def anos_do_catalogo():
    """Anos distintos entre os projetos elegíveis, mais recente primeiro —
    popula o `<select>` de filtro por ano em `/catalogo/`."""
    return _projetos_catalogaveis().order_by("-ano").values_list("ano", flat=True).distinct()


def calendario_publico():
    """Bancas ainda não realizadas, mais próxima primeiro (Bloco G, spec
    §5). Uma banca cuja `data_hora` já passou some da agenda mesmo que o
    orientador ainda não tenha registrado o resultado — calendário é
    agenda, não histórico."""
    from django.utils import timezone

    return (
        Banca.objects.filter(status=Banca.AGENDADA, data_hora__gte=timezone.now())
        .select_related("projeto__tema", "projeto__aluno", "projeto__orientador")
        .order_by("data_hora")
    )
```

- [ ] **Step 7: Rodar e confirmar que os testes do catálogo passam**

Run: `docker compose exec web pytest apps/publico/tests/test_catalogo.py -v`
Expected: todos `PASSED`.

**Prova por mutação (elegibilidade):** em `_projetos_catalogaveis`, comente
uma linha de cada vez (`etapa=Projeto.TCC_II,`, depois
`status=Projeto.CONCLUIDO,`, depois `termo_publicacao__isnull=False,`,
depois `tema__isnull=False,`) e rode
`test_catalogo_publico_esconde_tcc_i`/`esconde_nao_concluido`/
`esconde_sem_termo`/`esconde_sem_tema` (um de cada vez, o correspondente à
linha comentada) — Expected: `FAILED` a cada mutação (a checagem vizinha
das outras três NÃO mascara a ausência desta). Restaure cada linha e
confirme `PASSED` de novo antes de mutar a próxima.

- [ ] **Step 8: Escrever os testes de `calendario_publico` (falhando)**

Crie `apps/publico/tests/test_calendario.py`:

```python
"""Testes do Bloco G: `calendario_publico` (`apps/publico/services.py`)."""

import pytest
from django.utils import timezone

from apps.bancas.models import Banca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto
from apps.publico import services


def _cpf(indice):
    base = f"{850000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _banca(indice, data_hora, status=Banca.AGENDADA):
    orientador = Usuario.objects.create_user(
        email=f"orientador.calendario.{indice}@ufsm.br",
        password="x",
        nome_completo=f"Orientador Calendário {indice}",
        cpf=_cpf(indice * 10 + 1),
    )
    PerfilProfessor.objects.create(usuario=orientador, siape=f"CAL{indice:03d}")
    aluno = Usuario.objects.create_user(
        email=f"aluno.calendario.{indice}@ufsm.br",
        password="x",
        nome_completo=f"Aluno Calendário {indice}",
        papel=Usuario.ALUNO,
        cpf=_cpf(indice * 10 + 2),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula=f"2026CAL{indice:03d}")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador,
        etapa=Projeto.TCC_I,
        status=Projeto.AGUARDANDO_DEFESA,
        ano=2026,
        periodo=1,
    )
    return Banca.objects.create(
        projeto=projeto, data_hora=data_hora, local=f"Sala {indice}", status=status
    )


@pytest.mark.django_db
def test_calendario_publico_mostra_banca_agendada_futura():
    futura = timezone.now() + timezone.timedelta(days=5)
    banca = _banca(1, futura)
    assert banca in services.calendario_publico()


@pytest.mark.django_db
def test_calendario_publico_esconde_banca_realizada():
    futura = timezone.now() + timezone.timedelta(days=5)
    banca = _banca(2, futura, status=Banca.REALIZADA)
    assert banca not in services.calendario_publico()


@pytest.mark.django_db
def test_calendario_publico_esconde_banca_cancelada():
    futura = timezone.now() + timezone.timedelta(days=5)
    banca = _banca(3, futura, status=Banca.CANCELADA)
    assert banca not in services.calendario_publico()


@pytest.mark.django_db
def test_calendario_publico_esconde_banca_com_data_passada():
    passada = timezone.now() - timezone.timedelta(days=1)
    banca = _banca(4, passada)
    assert banca not in services.calendario_publico()


@pytest.mark.django_db
def test_calendario_publico_ordena_mais_proxima_primeiro():
    mais_distante = _banca(5, timezone.now() + timezone.timedelta(days=10))
    mais_proxima = _banca(6, timezone.now() + timezone.timedelta(days=2))
    resultado = list(services.calendario_publico())
    assert resultado.index(mais_proxima) < resultado.index(mais_distante)
```

- [ ] **Step 9: Rodar e confirmar que falham**

Run: `docker compose exec web pytest apps/publico/tests/test_calendario.py -v`
Expected: `FAILED` em todos (`calendario_publico` já existe do Step 6, então
na verdade devem passar — se algum falhar, releia o Step 6 antes de seguir;
este passo existe pra confirmar que os testes exercitam código de verdade,
não uma função ausente).

- [ ] **Step 10: Confirmar que passam**

Run: `docker compose exec web pytest apps/publico/tests/test_calendario.py -v`
Expected: todos `PASSED`.

**Prova por mutação:** em `calendario_publico`, troque
`status=Banca.AGENDADA` por `status__in=[Banca.AGENDADA, Banca.REALIZADA]`
temporariamente, rode `test_calendario_publico_esconde_banca_realizada` —
Expected: `FAILED`. Restaure, confirme `PASSED`. Repita trocando
`data_hora__gte=timezone.now()` por nada (remova o filtro) e rode
`test_calendario_publico_esconde_banca_com_data_passada` — Expected:
`FAILED`. Restaure, confirme `PASSED`.

- [ ] **Step 11: `ruff`, `black`, e commit**

```bash
docker compose exec web ruff check .
docker compose exec web black .
git add apps/publico config/settings.py config/urls.py
git commit -m "Tarefa 3: app apps/publico com catalogo_publico e calendario_publico"
```

---

## Task 4: Tela `/catalogo/`

**Files:**
- Modify: `apps/publico/views.py` (`catalogo`)
- Modify: `apps/publico/urls.py`
- Create: `templates/publico/catalogo.html`
- Test: `apps/publico/tests/test_catalogo.py` (extensão)

**Interfaces:**
- Consome: `services.catalogo_publico(area_id, ano)`,
  `services.anos_do_catalogo()` (Task 3).

- [ ] **Step 1: Escrever os testes de view (falhando)**

Acrescente ao final de `apps/publico/tests/test_catalogo.py`:

```python
@pytest.mark.django_db
def test_catalogo_view_mostra_titulo_e_link_de_download(client):
    projeto = _projeto_catalogavel(12)
    resposta = client.get("/catalogo/")
    conteudo = resposta.content.decode()
    assert projeto.tema.titulo in conteudo
    assert projeto.aluno.nome_completo in conteudo


@pytest.mark.django_db
def test_catalogo_view_ignora_querystring_invalida_sem_500(client):
    resposta = client.get("/catalogo/?area=xyz&ano=abc")
    assert resposta.status_code == 200


@pytest.mark.django_db
def test_catalogo_view_sem_login_funciona(client):
    resposta = client.get("/catalogo/")
    assert resposta.status_code == 200
```

- [ ] **Step 2: Rodar e confirmar que falham**

Run: `docker compose exec web pytest apps/publico/tests/test_catalogo.py -k view -v`
Expected: `FAILED` com 404 (nenhuma URL `/catalogo/` existe ainda).

- [ ] **Step 3: Implementar a view**

Em `apps/publico/views.py`:

```python
from django.shortcuts import render

from apps.contas.models import Area
from apps.publico import services


def catalogo(request):
    """Catálogo público de TCCs concluídos (Bloco G, spec §6) — sem login,
    sem dado sensível (só Título, Resumo, Autor, Orientador e o PDF).
    `area`/`ano` vêm da querystring como texto; `isdigit()` descarta
    entrada não numérica em vez de deixar `int()` levantar `ValueError` e
    derrubar a página com 500 — ninguém além de um usuário digitando a URL
    à mão produziria isso, mas a tela é pública e não tem formulário
    algum controlando o valor antes de chegar aqui."""
    area_id = request.GET.get("area")
    area_id = int(area_id) if area_id and area_id.isdigit() else None
    ano = request.GET.get("ano")
    ano = int(ano) if ano and ano.isdigit() else None
    return render(
        request,
        "publico/catalogo.html",
        {
            "projetos": services.catalogo_publico(area_id=area_id, ano=ano),
            "areas": Area.objects.order_by("nome"),
            "anos": services.anos_do_catalogo(),
            "area_selecionada": area_id,
            "ano_selecionado": ano,
        },
    )
```

- [ ] **Step 4: Registrar a URL**

Em `apps/publico/urls.py`, troque `urlpatterns = []` por:

```python
urlpatterns = [
    path("catalogo/", views.catalogo, name="catalogo"),
]
```

(acrescente `from django.urls import path` no topo do arquivo, junto do
import de `views` já existente.)

- [ ] **Step 5: Criar o template**

Crie `templates/publico/catalogo.html`:

```html
{% extends "base.html" %}

{% block titulo %} — Catálogo de TCCs{% endblock %}

{% block conteudo %}
  <article class="mx-auto max-w-3xl rounded-box bg-base-100 p-6 shadow-sm">
    <h1 class="font-display text-2xl font-bold text-primary">Catálogo de TCCs</h1>

    <form method="get" class="mt-4 flex flex-wrap items-end gap-4">
      <div>
        <label for="filtro-area" class="label"><span class="label-text">Área</span></label>
        <select id="filtro-area" name="area" class="select w-full">
          <option value="">Todas</option>
          {% for area in areas %}
            <option value="{{ area.pk }}" {% if area_selecionada == area.pk %}selected{% endif %}>
              {{ area.nome }}
            </option>
          {% endfor %}
        </select>
      </div>
      <div>
        <label for="filtro-ano" class="label"><span class="label-text">Ano</span></label>
        <select id="filtro-ano" name="ano" class="select w-full">
          <option value="">Todos</option>
          {% for ano_opcao in anos %}
            <option value="{{ ano_opcao }}" {% if ano_selecionado == ano_opcao %}selected{% endif %}>
              {{ ano_opcao }}
            </option>
          {% endfor %}
        </select>
      </div>
      <button type="submit" class="btn btn-primary">Filtrar</button>
    </form>

    {% if projetos %}
      <ul class="mt-6 space-y-4">
        {% for projeto in projetos %}
          <li class="rounded-box border border-base-300 p-4">
            <p class="font-medium">{{ projeto.tema.titulo }}</p>
            <p class="mt-1 text-sm text-base-content/80">
              {{ projeto.tema.descricao|truncatewords:40 }}
            </p>
            <p class="mt-2 text-sm">
              Autor: {{ projeto.aluno.nome_completo }} —
              Orientador: {{ projeto.orientador.nome_completo }}
            </p>
            <p class="mt-2">
              <a href="{{ projeto.submissao.pdf.url }}" class="link">Baixar PDF</a>
            </p>
          </li>
        {% endfor %}
      </ul>
    {% else %}
      <p class="mt-6">Nenhum TCC publicado ainda.</p>
    {% endif %}
  </article>
{% endblock %}
```

- [ ] **Step 6: Rodar e confirmar que os testes de view passam**

Run: `docker compose exec web pytest apps/publico/tests/test_catalogo.py -v`
Expected: todos `PASSED`.

- [ ] **Step 7: `ruff`, `black`, e commit**

```bash
docker compose exec web ruff check .
docker compose exec web black .
git add apps/publico/views.py apps/publico/urls.py templates/publico/catalogo.html apps/publico/tests/test_catalogo.py
git commit -m "Tarefa 4: tela /catalogo/"
```

---

## Task 5: Tela `/calendario/`

**Files:**
- Modify: `apps/publico/views.py` (`calendario`)
- Modify: `apps/publico/urls.py`
- Create: `templates/publico/calendario.html`
- Test: `apps/publico/tests/test_calendario.py` (extensão)

**Interfaces:**
- Consome: `services.calendario_publico()` (Task 3).

- [ ] **Step 1: Escrever os testes de view (falhando)**

Acrescente ao final de `apps/publico/tests/test_calendario.py`:

```python
@pytest.mark.django_db
def test_calendario_view_renderiza_lista(client):
    futura = timezone.now() + timezone.timedelta(days=5)
    banca = _banca(7, futura)
    resposta = client.get("/calendario/")
    assert resposta.status_code == 200
    assert banca.projeto.aluno.nome_completo in resposta.content.decode()


@pytest.mark.django_db
def test_calendario_view_sem_login_funciona(client):
    resposta = client.get("/calendario/")
    assert resposta.status_code == 200
```

- [ ] **Step 2: Rodar e confirmar que falham**

Run: `docker compose exec web pytest apps/publico/tests/test_calendario.py -k view -v`
Expected: `FAILED` com 404.

- [ ] **Step 3: Implementar a view**

Em `apps/publico/views.py`, acrescente:

```python
def calendario(request):
    """Calendário público de apresentações futuras (Bloco G, spec §6) —
    sem login, sem filtro (YAGNI: nenhum requisito pediu)."""
    return render(request, "publico/calendario.html", {"bancas": services.calendario_publico()})
```

- [ ] **Step 4: Registrar a URL**

Em `apps/publico/urls.py`, acrescente ao `urlpatterns`:

```python
    path("calendario/", views.calendario, name="calendario"),
```

- [ ] **Step 5: Criar o template**

Crie `templates/publico/calendario.html`:

```html
{% extends "base.html" %}

{% block titulo %} — Calendário de Apresentações{% endblock %}

{% block conteudo %}
  <article class="mx-auto max-w-2xl rounded-box bg-base-100 p-6 shadow-sm">
    <h1 class="font-display text-2xl font-bold text-primary">Calendário de Apresentações</h1>

    {% if bancas %}
      <ul class="mt-6 space-y-4">
        {% for banca in bancas %}
          <li class="rounded-box border border-base-300 p-4">
            <p class="font-medium">
              {{ banca.projeto.aluno.nome_completo }}
              {% if banca.projeto.tema %} — "{{ banca.projeto.tema.titulo }}"{% endif %}
            </p>
            <p class="mt-1 text-sm text-base-content/80">
              Orientador: {{ banca.projeto.orientador.nome_completo }}
            </p>
            <p class="mt-1 text-sm">{{ banca.data_hora }} — {{ banca.local }}</p>
          </li>
        {% endfor %}
      </ul>
    {% else %}
      <p class="mt-6">Nenhuma apresentação agendada no momento.</p>
    {% endif %}
  </article>
{% endblock %}
```

- [ ] **Step 6: Rodar e confirmar que os testes de view passam**

Run: `docker compose exec web pytest apps/publico/tests/test_calendario.py -v`
Expected: todos `PASSED`.

- [ ] **Step 7: `ruff`, `black`, e commit**

```bash
docker compose exec web ruff check .
docker compose exec web black .
git add apps/publico/views.py apps/publico/urls.py templates/publico/calendario.html apps/publico/tests/test_calendario.py
git commit -m "Tarefa 5: tela /calendario/"
```

---

## Task 6: Navegação, rotas transversais e fechamento do bloco

**Files:**
- Modify: `templates/base.html`
- Modify: `conftest.py`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consome: `/catalogo/`, `/calendario/` (Tasks 4/5).

- [ ] **Step 1: Acrescentar os links na navegação**

Em `templates/base.html`, dentro de `<ul class="flex flex-wrap items-center
gap-2">`, como os dois primeiros `<li>` (antes de `{% if
user.is_authenticated %}`, pra ficarem visíveis com ou sem login):

```html
            <li><a href="{% url 'publico:catalogo' %}" class="btn btn-ghost">Catálogo</a></li>
            <li><a href="{% url 'publico:calendario' %}" class="btn btn-ghost">Calendário</a></li>
```

- [ ] **Step 2: Rodar a suíte inteira pra confirmar que a navegação não quebrou nenhuma tela existente**

Run: `docker compose exec web pytest -q`
Expected: todos `PASSED` (dois botões a mais no cabeçalho de TODA página —
mesmo tipo de mudança que já estourou 360px uma vez, T12 do Bloco B; a
suíte de responsividade cobre isso de novo aqui).

- [ ] **Step 3: Ler o final de `conftest.py` e confirmar o índice livre de `_gera_cpf_das_rotas`**

Run: `grep -n "_gera_cpf_das_rotas([0-9]*)" conftest.py | grep -oP "_gera_cpf_das_rotas\(\K[0-9]+" | sort -n | tail -5`
Expected: o maior índice impresso é `39` (Bloco F) — os índices `40-43`
abaixo estão livres. Se a saída mostrar um índice `>= 40`, ajuste os
números abaixo para continuar depois do maior encontrado.

- [ ] **Step 4: Acrescentar as duas fábricas**

Perto de `cria_professor_com_correcao_para_rotas` (Bloco F), em
`conftest.py`:

```python
def cria_projeto_catalogavel_para_rotas():
    """Fábrica de `/catalogo/` (Bloco G): um TCC_II Concluído completo
    (tema, submissão, termo, ata aprovada) — sem isso a suíte mediria a
    lista vazia, uma tela degenerada em vez da real (mesmo raciocínio de
    `cria_sugrad_com_ata_pendente_para_rotas`, Bloco E)."""
    from apps.bancas.models import Banca
    from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
    from apps.documentos.models import Ata, RevisaoSUGRAD
    from apps.projetos.models import Projeto, Submissao, Tema, TermoPublicacao

    orientador = Usuario.objects.create_user(
        email="orientador-catalogo-das-rotas@ufsm.br",
        password="x",
        nome_completo="Orientador Catálogo das Rotas",
        cpf=_gera_cpf_das_rotas(40),
    )
    perfil_orientador = PerfilProfessor.objects.create(usuario=orientador, siape="1000027")
    aluno = Usuario.objects.create_user(
        email="aluno-catalogo-das-rotas@ufsm.br",
        password="x",
        nome_completo="Aluno Catálogo das Rotas",
        cpf=_gera_cpf_das_rotas(41),
        papel=Usuario.ALUNO,
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026399923")
    area = Area.objects.create(nome="Área Catálogo das Rotas")
    tema = Tema.objects.create(
        professor=perfil_orientador,
        area=area,
        titulo="Tema Catálogo das Rotas",
        descricao="Descrição do tema catalogado.",
    )
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador,
        tema=tema,
        etapa=Projeto.TCC_II,
        status=Projeto.CONCLUIDO,
        ano=2026,
        periodo=1,
    )
    Submissao.objects.create(
        projeto=projeto,
        pdf="submissoes/rota-catalogo.pdf",
        editavel="submissoes/rota-catalogo.docx",
    )
    TermoPublicacao.objects.create(projeto=projeto)
    banca = Banca.objects.create(
        projeto=projeto,
        data_hora=timezone.now(),
        local="Sala Catálogo das Rotas",
        status=Banca.REALIZADA,
        nota=9.0,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
    )
    ata = Ata.objects.create(
        projeto=projeto, banca=banca, numero="999/2026", pdf="atas/rota-catalogo.pdf"
    )
    RevisaoSUGRAD.objects.create(ata=ata, status=RevisaoSUGRAD.APROVADA, decidida_em=timezone.now())
    return aluno


def cria_banca_agendada_para_calendario_das_rotas():
    """Fábrica de `/calendario/` (Bloco G): uma `Banca` `AGENDADA` no
    futuro, pra suíte medir a tela com pelo menos um item."""
    from apps.bancas.models import Banca
    from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
    from apps.projetos.models import Projeto

    orientador = Usuario.objects.create_user(
        email="orientador-calendario-das-rotas@ufsm.br",
        password="x",
        nome_completo="Orientador Calendário das Rotas",
        cpf=_gera_cpf_das_rotas(42),
    )
    PerfilProfessor.objects.create(usuario=orientador, siape="1000028")
    aluno = Usuario.objects.create_user(
        email="aluno-calendario-das-rotas@ufsm.br",
        password="x",
        nome_completo="Aluno Calendário das Rotas",
        cpf=_gera_cpf_das_rotas(43),
        papel=Usuario.ALUNO,
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026399924")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador,
        etapa=Projeto.TCC_I,
        status=Projeto.AGUARDANDO_DEFESA,
        ano=2026,
        periodo=1,
    )
    Banca.objects.create(
        projeto=projeto,
        data_hora=timezone.now() + timezone.timedelta(days=5),
        local="Sala Calendário das Rotas",
        status=Banca.AGENDADA,
    )
    return aluno
```

- [ ] **Step 5: Acrescentar as duas `Rota`**

Ao final de `ROTAS`:

```python
    Rota(
        "/catalogo/",
        "form",
        fabrica_usuario=cria_projeto_catalogavel_para_rotas,
        h1="Catálogo de TCCs",
    ),
    Rota(
        "/calendario/",
        "h1",
        fabrica_usuario=cria_banca_agendada_para_calendario_das_rotas,
        h1="Calendário de Apresentações",
    ),
```

(`/catalogo/` usa seletor `"form"` — a tela tem o formulário de filtro;
`/calendario/` usa `"h1"` — não tem formulário nenhum. `fabrica_usuario`
autentica no navegador mesmo sendo páginas públicas — inofensivo aqui: a
página se comporta igual autenticado ou não, e reaproveitar o mecanismo já
existente evita inventar um caminho novo só pra rota pública.)

- [ ] **Step 6: Rodar as cinco suítes transversais completas**

Run: `docker compose exec web pytest tests/test_acessibilidade.py tests/test_toque.py tests/test_responsivo.py tests/test_teclado.py tests/test_rotas.py -v`
Expected: todos `PASSED`. Se `color-contrast` ou alvo de toque reprovarem
em algum elemento novo, ajuste a classe DaisyUI do elemento e rode de novo
até passar.

- [ ] **Step 7: Rodar a suíte inteira**

Run: `docker compose exec web pytest`
Expected: todos `PASSED`.

- [ ] **Step 8: `ruff` e `black`**

Run: `docker compose exec web ruff check .`
Run: `docker compose exec web black --check .`

- [ ] **Step 9: Commit da navegação e das rotas**

```bash
git add templates/base.html conftest.py
git commit -m "Tarefa 6: navegacao publica e rotas transversais de catalogo/calendario"
```

- [ ] **Step 10: Verificar os 10 critérios de aceitação do spec (§8) com evidência real**

Para cada critério, rode um comando ou leia um teste que já prova aquele
critério especificamente — não infira do "a suíte passou". Sugestão de
mapeamento:

1. `test_catalogo_view_mostra_titulo_e_link_de_download` +
   `test_catalogo_publico_mostra_tcc_ii_concluido_com_termo_e_tema`.
2. `test_catalogo_publico_esconde_tcc_i`.
3. Nenhuma checagem redundante no código — confirme lendo
   `_projetos_catalogaveis` e `apps/projetos/services.py::aprovar_projeto`
   (Bloco F) lado a lado.
4. `test_catalogo_publico_esconde_sem_tema`.
5. `test_catalogo_publico_filtra_por_area` +
   `test_catalogo_publico_filtra_por_ano`.
6. `test_calendario_publico_mostra_banca_agendada_futura` +
   `test_calendario_publico_esconde_banca_realizada`/`_cancelada`/
   `_com_data_passada`.
7. `test_criar_tcc_ii_automatico_copia_tema` +
   `test_criar_tcc_ii_manual_recusa_tema_de_outro_professor`.
8. `test_enviar_submissao_aceita_reenvio_em_aprovado_com_ressalvas_para_tcc_ii`
   + `test_meu_tcc_recusa_reenvio_tcc_ii_fora_dos_status_permitidos_sem_500`.
9. Releia `apps/publico/views.py`/`apps/publico/models.py` (não existe) —
   confirme que toda regra fica em `services.py`.
10. `docker compose exec web pytest` (Step 7 já rodou isso).

- [ ] **Step 11: Atualizar `CLAUDE.md`**

Marque o Bloco G como concluído na seção "Fases", no mesmo formato das
entradas anteriores (A–F). Acrescente uma linha em "Estrutura de Apps"
para `apps/publico` (catálogo e calendário públicos, sem models próprios).
Não há "Ciclo de Vida" a mudar — nenhum status novo, nenhuma transição
nova.

```bash
git add CLAUDE.md
git commit -m "Marca Bloco G (catalogo e calendario publicos) como concluido no CLAUDE.md"
```

- [ ] **Step 12: Invocar `superpowers:finishing-a-development-branch`**

Branch `bloco-g-catalogo-e-calendario`, base `main`.

---

## Ao concluir

Com o Bloco G concluído, restam os Blocos H (API DRF). O domínio de TCC I e
TCC II, incluindo suas telas públicas (catálogo e calendário), está
completo.
