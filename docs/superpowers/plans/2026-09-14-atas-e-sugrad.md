# Atas e SUGRAD (Bloco E) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fechar o restante do ciclo de vida do TCC I: o orientador confirma
`Aprovado com Ressalvas → Aprovado`, o sistema gera a Ata (PDF via WeasyPrint)
e notifica a SUGRAD, e a SUGRAD aprova (`→ Concluído`) ou devolve com
comentário (o orientador reenvia).

**Architecture:** Novo app `apps/documentos` com o padrão já estabelecido
(`models.py`/`services.py`/`permissions.py`/`forms.py`/`views.py`/`urls.py`/
`tasks.py`, mais `tests/`). Uma pequena extensão em `apps/projetos`
(`aprovar_projeto`, `orientandos_atuais` ganha dois status novos no filtro,
duas views/rotas novas). `templates/base.html` ganha um link condicional por
papel para a SUGRAD.

**Tech Stack:** Django 5, PostgreSQL, Celery (notificação de e-mail),
WeasyPrint (geração de PDF), pytest-django, Playwright + axe-core.

**Spec:** `docs/superpowers/specs/2026-09-14-atas-e-sugrad-design.md`

## Global Constraints

- Todo identificador de código é em português; interface, mensagens e commits também.
- Regra de negócio nunca em `views.py`/`models.py` — só em `services.py` de cada
  app (CLAUDE.md, regra 4). `models.py` só tem campos, `Meta` e `__str__` —
  **nenhuma property nova no `Usuario`**: a checagem de papel SUGRAD é
  `usuario.papel == Usuario.SUGRAD`, direto, em `permissions.py` e no
  template, não um atributo computado no modelo.
- Permissão é POSSE (`usuario == projeto.orientador`) em toda checagem deste
  bloco, **exceto** `pode_revisar_ata`, que é por PAPEL
  (`usuario.papel == Usuario.SUGRAD`) — mesmo formato de
  `pode_ajustar_orientacao`/`pode_conceder_limite` (Bloco B), que já checam
  `is_coordenador` em vez de posse.
- Lookup de view sempre ESCOPADO ao dono quando a checagem é de posse
  (`get_object_or_404(Modelo, pk=..., campo_de_posse=request.user)`): dono
  alheio e pk inexistente respondem os DOIS com 404, nunca 403. `/painel/sugrad/`
  é a exceção — portão de PAPEL sem lookup de posse (lista atas de todo
  mundo), mesmo padrão de `painel_orientacoes`.
- **Disciplina de testes (CLAUDE.md):** toda checagem nova provada por mutação
  (comente a checagem, confirme que algum teste reprova, desfaça); uma checagem
  vizinha pode mascarar a ausência da nova — nunca inferir cobertura pela
  suíte passando; toda citação de arquivo:linha conferida no momento em que é
  escrita.
- Toda tela nova entra em `conftest.py::ROTAS` (nunca numa suíte de
  acessibilidade isolada) para receber as cinco checagens transversais.
- `docker compose exec web pytest` / `ruff check .` / `black --check .` depois
  de cada tarefa.

---

## Mapa de arquivos

- **Criar** `apps/documentos/models.py` — `Ata`, `RevisaoSUGRAD`.
- **Criar** `apps/documentos/migrations/0001_initial.py`.
- **Criar** `apps/documentos/admin.py`.
- **Criar** `apps/documentos/permissions.py` — `pode_revisar_ata`, `pode_reenviar_ata`.
- **Criar** `apps/documentos/services.py` — `gerar_ata`, `aprovar_ata`,
  `devolver_ata`, `reenviar_a_sugrad`.
- **Criar** `apps/documentos/tasks.py` — `enviar_ata_para_sugrad`,
  `enviar_devolucao_para_orientador`.
- **Criar** `apps/documentos/forms.py` — `FormularioDevolverAta`.
- **Criar** `apps/documentos/views.py` — `painel`, `aprovar_ata_view`, `devolver_ata_view`.
- **Criar** `apps/documentos/urls.py`.
- **Criar** `templates/documentos/painel_sugrad.html`, `templates/documentos/ata_pdf.html`.
- **Criar** `templates/email/ata_para_sugrad.txt`, `templates/email/ata_devolvida.txt`.
- **Criar** `apps/documentos/tests/{__init__.py,test_modelos.py,test_gerar_ata.py,
  test_revisao.py,test_notificacoes.py,test_formularios.py,test_telas.py}`.
- **Modificar** `apps/projetos/services.py` — `aprovar_projeto`,
  `orientandos_atuais` (filtro ganha `APROVADO_COM_RESSALVAS`/`APROVADO`).
- **Modificar** `apps/projetos/permissions.py` — `pode_aprovar_projeto`.
- **Modificar** `apps/projetos/views.py` — `aprovar_projeto_view`, `reenviar_ata_view`.
- **Modificar** `apps/projetos/urls.py` — duas rotas novas.
- **Modificar** `templates/projetos/orientacoes.html` — ações por estado
  (`Aprovado com Ressalvas`, `Aprovado`).
- **Modificar** `templates/base.html` — link "Painel SUGRAD" condicional.
- **Modificar** `config/urls.py` — `include("apps.documentos.urls")`.
- **Modificar** `conftest.py` — `ROTAS` (`/painel/sugrad/`).
- **Modificar** `apps/projetos/tests/test_reprovacao.py` ou novo teste —
  cobertura do filtro ampliado de `orientandos_atuais`.

---

## Tarefa 1: Modelos `Ata`/`RevisaoSUGRAD`

**Arquivos:**
- Criar: `apps/documentos/models.py`, `apps/documentos/migrations/0001_initial.py`,
  `apps/documentos/admin.py`.
- Teste: `apps/documentos/tests/test_modelos.py`.

**Interfaces:**
- Produz: `Ata` (`projeto`, `banca`, `numero`, `pdf`, `gerada_em`);
  `RevisaoSUGRAD` (`ata`, `status` — `PENDENTE|APROVADA|DEVOLVIDA`,
  `comentario`, `decidida_em`).

- [ ] **Passo 1: Escrever os testes de modelo (falhando)**

Crie `apps/documentos/tests/__init__.py` vazio, e
`apps/documentos/tests/test_modelos.py`:

```python
"""Testes de modelo do Bloco E (spec §4): `Ata`/`RevisaoSUGRAD` e o vínculo
`OneToOneField` entre elas."""

import pytest
from django.utils import timezone

from apps.bancas.models import Banca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.documentos.models import Ata, RevisaoSUGRAD
from apps.projetos.models import Projeto


def _cpf(indice):
    """CPF sintético com dígitos verificadores válidos, faixa 700000000+ —
    livre (conferida por grep) para os testes de `apps/documentos/`."""
    base = f"{700000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


@pytest.fixture
def projeto_aprovado(db):
    aluno = Usuario.objects.create_user(
        email="aluno.ata.modelo@ufsm.br",
        password="x",
        nome_completo="Aluno Ata Modelo",
        papel=Usuario.ALUNO,
        cpf=_cpf(1),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026ATA001")
    professor = Usuario.objects.create_user(
        email="professor.ata.modelo@ufsm.br",
        password="x",
        nome_completo="Professor Ata Modelo",
        cpf=_cpf(2),
    )
    PerfilProfessor.objects.create(usuario=professor, siape="ATA0001")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=professor,
        etapa=Projeto.TCC_I,
        status=Projeto.APROVADO,
        ano=2026,
        periodo=1,
    )
    banca = Banca.objects.create(
        projeto=projeto,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.REALIZADA,
        nota=8.5,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
    )
    return projeto, banca


@pytest.mark.django_db
def test_ata_criada_com_revisao_pendente(projeto_aprovado):
    projeto, banca = projeto_aprovado
    ata = Ata.objects.create(projeto=projeto, banca=banca, numero="001/2026")
    revisao = RevisaoSUGRAD.objects.create(ata=ata)
    assert revisao.status == RevisaoSUGRAD.PENDENTE
    assert revisao.comentario == ""
    assert revisao.decidida_em is None


@pytest.mark.django_db
def test_ata_str_inclui_numero(projeto_aprovado):
    projeto, banca = projeto_aprovado
    ata = Ata.objects.create(projeto=projeto, banca=banca, numero="002/2026")
    assert "002/2026" in str(ata)


def test_revisao_sugrad_tem_tres_status():
    assert RevisaoSUGRAD.PENDENTE == "PENDENTE"
    assert RevisaoSUGRAD.APROVADA == "APROVADA"
    assert RevisaoSUGRAD.DEVOLVIDA == "DEVOLVIDA"
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `docker compose exec web pytest apps/documentos/tests/test_modelos.py -v`
Expected: `ModuleNotFoundError: No module named 'apps.documentos.models'`.

- [ ] **Passo 3: Escrever `apps/documentos/models.py`**

```python
from django.db import models

from apps.bancas.models import Banca
from apps.projetos.models import Projeto


class Ata(models.Model):
    """Documento formal da defesa do TCC I, gerado automaticamente ao
    aprovar o projeto (Bloco E, spec §4.1/§5.1) — nunca por upload do
    usuário, por isso `pdf` não tem `validators` de extensão/tamanho como
    `Submissao` (Bloco C): o conteúdo é sempre produzido por
    `apps.documentos.services.gerar_ata`, nunca por um formulário externo.
    """

    projeto = models.ForeignKey(
        Projeto,
        on_delete=models.PROTECT,
        related_name="atas",
        verbose_name="projeto",
    )
    banca = models.ForeignKey(
        Banca,
        on_delete=models.PROTECT,
        related_name="atas",
        verbose_name="banca",
    )
    numero = models.CharField("número", max_length=20)
    pdf = models.FileField("PDF", upload_to="atas/")
    gerada_em = models.DateTimeField("gerada em", auto_now_add=True)

    class Meta:
        verbose_name = "ata"
        verbose_name_plural = "atas"
        ordering = ["-gerada_em"]

    def __str__(self):
        return f"Ata {self.numero} — {self.projeto}"


class RevisaoSUGRAD(models.Model):
    """Decisão (atual) da SUGRAD sobre uma `Ata` — uma linha só por `Ata`,
    sobrescrita a cada decisão (Bloco E, spec §3.3): mesmo padrão de "sem
    histórico" de `Submissao` (Bloco C) e `Banca.resultado` (Bloco D)."""

    PENDENTE = "PENDENTE"
    APROVADA = "APROVADA"
    DEVOLVIDA = "DEVOLVIDA"
    STATUS = [
        (PENDENTE, "Pendente"),
        (APROVADA, "Aprovada"),
        (DEVOLVIDA, "Devolvida"),
    ]

    ata = models.OneToOneField(
        Ata,
        on_delete=models.CASCADE,
        related_name="revisao",
        verbose_name="ata",
    )
    status = models.CharField("status", max_length=9, choices=STATUS, default=PENDENTE)
    comentario = models.TextField("comentário", blank=True, default="")
    decidida_em = models.DateTimeField("decidida em", null=True, blank=True)

    class Meta:
        verbose_name = "revisão da SUGRAD"
        verbose_name_plural = "revisões da SUGRAD"

    def __str__(self):
        return f"Revisão de {self.ata} — {self.get_status_display()}"
```

- [ ] **Passo 4: Criar `apps/documentos/admin.py`**

```python
from django.contrib import admin

from apps.documentos.models import Ata, RevisaoSUGRAD


class RevisaoSUGRADInline(admin.StackedInline):
    model = RevisaoSUGRAD
    extra = 0


@admin.register(Ata)
class AtaAdmin(admin.ModelAdmin):
    list_display = ["numero", "projeto", "banca", "gerada_em"]
    search_fields = ["numero", "projeto__aluno__nome_completo"]
    readonly_fields = ["gerada_em"]
    inlines = [RevisaoSUGRADInline]
```

- [ ] **Passo 5: Gerar e aplicar a migração**

Run: `docker compose exec web python manage.py makemigrations documentos`
Expected: cria `apps/documentos/migrations/0001_initial.py`.

Run: `docker compose exec web python manage.py migrate`
Expected: aplica sem erro.

- [ ] **Passo 6: Rodar os testes e confirmar que passam**

Run: `docker compose exec web pytest apps/documentos/tests/test_modelos.py -v`
Expected: todos `PASSED`.

- [ ] **Passo 7: `ruff` e `black`**

Run: `docker compose exec web ruff check .`
Run: `docker compose exec web black .`

- [ ] **Passo 8: Commit**

```bash
git add apps/documentos/models.py apps/documentos/admin.py \
        apps/documentos/migrations/ apps/documentos/tests/__init__.py \
        apps/documentos/tests/test_modelos.py
git commit -m "Tarefa 1: modelos Ata e RevisaoSUGRAD"
```

---

## Tarefa 2: `aprovar_projeto` e o filtro de `orientandos_atuais`

**Arquivos:**
- Modificar: `apps/projetos/services.py`, `apps/projetos/permissions.py`.
- Teste: `apps/projetos/tests/test_aprovacao.py` (novo).

**Interfaces:**
- Consome: `Ata`, `RevisaoSUGRAD` (Tarefa 1) — só citados na docstring, a
  chamada de verdade a `gerar_ata` entra na Tarefa 3.
- Produz: `services.aprovar_projeto(projeto, por) -> None`;
  `permissions.pode_aprovar_projeto(usuario, projeto) -> bool`.
- Modifica: `orientandos_atuais` — mesma assinatura, filtro ganha
  `APROVADO_COM_RESSALVAS` e `APROVADO`.

Esta tarefa isola a transição de status **sem** gerar a ata de verdade —
`aprovar_projeto` só muda `Projeto.status`. A Tarefa 3 pluga `gerar_ata` nela.
Isolar assim evita que esta tarefa dependa de WeasyPrint/template HTML para
ser testável.

- [ ] **Passo 1: Escrever os testes (falhando)**

Crie `apps/projetos/tests/test_aprovacao.py`:

```python
"""Testes de `services.aprovar_projeto` (Bloco E, spec §5.1) e do filtro
ampliado de `orientandos_atuais` (spec §3.6)."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.comum.semestre import semestre_vigente
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos import services
from apps.projetos.models import Projeto


def _cpf(indice):
    base = f"{710000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.aprovacao.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=_cpf(indice),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"APROV{indice:03d}")


def _aluno(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"aluno.aprovacao.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        papel=Usuario.ALUNO,
        cpf=_cpf(indice),
    )
    PerfilAluno.objects.create(usuario=usuario, matricula=f"2026APROV{indice:02d}")
    return usuario


@pytest.fixture
def orientador(db):
    return _professor(1, "Orientador Aprovação")


@pytest.fixture
def projeto_com_ressalvas(db, orientador):
    ano, periodo = semestre_vigente()
    aluno = _aluno(2, "Aluno Com Ressalvas")
    return Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.APROVADO_COM_RESSALVAS,
        ano=ano,
        periodo=periodo,
    )


@pytest.mark.django_db
def test_aprovar_projeto_muda_status(projeto_com_ressalvas, orientador):
    services.aprovar_projeto(projeto_com_ressalvas, por=orientador.usuario)
    projeto_com_ressalvas.refresh_from_db()
    assert projeto_com_ressalvas.status == Projeto.APROVADO


@pytest.mark.django_db
def test_aprovar_projeto_recusa_quem_nao_e_o_orientador(projeto_com_ressalvas):
    outro = Usuario.objects.create_user(
        email="outro.aprovar@ufsm.br", password="x", nome_completo="Outro Aprovar", cpf=_cpf(3)
    )
    with pytest.raises(PermissionDenied):
        services.aprovar_projeto(projeto_com_ressalvas, por=outro)


@pytest.mark.django_db
def test_aprovar_projeto_recusa_fora_de_aprovado_com_ressalvas(
    projeto_com_ressalvas, orientador
):
    projeto_com_ressalvas.status = Projeto.EM_ANDAMENTO
    projeto_com_ressalvas.save()
    with pytest.raises(ValidationError):
        services.aprovar_projeto(projeto_com_ressalvas, por=orientador.usuario)


@pytest.mark.django_db
def test_orientandos_atuais_inclui_aprovado_com_ressalvas_e_aprovado(orientador):
    ano, periodo = semestre_vigente()
    aluno_ressalvas = _aluno(4, "Aluno Ressalvas Dois")
    Projeto.objects.create(
        aluno=aluno_ressalvas,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.APROVADO_COM_RESSALVAS,
        ano=ano,
        periodo=periodo,
    )
    aluno_aprovado = _aluno(5, "Aluno Aprovado")
    Projeto.objects.create(
        aluno=aluno_aprovado,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.APROVADO,
        ano=ano,
        periodo=periodo,
    )
    resultado = {p.aluno_id for p in services.orientandos_atuais(orientador)}
    assert aluno_ressalvas.id in resultado
    assert aluno_aprovado.id in resultado


@pytest.mark.django_db
def test_orientandos_atuais_exclui_concluido(orientador):
    ano, periodo = semestre_vigente()
    aluno_concluido = _aluno(6, "Aluno Concluído")
    Projeto.objects.create(
        aluno=aluno_concluido,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.CONCLUIDO,
        ano=ano,
        periodo=periodo,
    )
    resultado = {p.aluno_id for p in services.orientandos_atuais(orientador)}
    assert aluno_concluido.id not in resultado
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `docker compose exec web pytest apps/projetos/tests/test_aprovacao.py -v`
Expected: `AttributeError: module 'apps.projetos.services' has no attribute
'aprovar_projeto'` (e o teste de `orientandos_atuais` falha por assertion,
já que o filtro atual não inclui os dois status novos).

- [ ] **Passo 3: Ampliar o filtro de `orientandos_atuais`**

Em `apps/projetos/services.py`, na função `orientandos_atuais`, troque:

```python
            status__in=[Projeto.EM_ANDAMENTO, Projeto.AGUARDANDO_DEFESA, Projeto.REPROVADO],
```

por:

```python
            status__in=[
                Projeto.EM_ANDAMENTO,
                Projeto.AGUARDANDO_DEFESA,
                Projeto.REPROVADO,
                Projeto.APROVADO_COM_RESSALVAS,
                Projeto.APROVADO,
            ],
```

- [ ] **Passo 4: Acrescentar `pode_aprovar_projeto` a `apps/projetos/permissions.py`**

```python
def pode_aprovar_projeto(usuario, projeto):
    """`usuario` é exatamente o orientador de `projeto` (Bloco E, spec §3.1)
    — posse, não papel."""
    return bool(usuario and usuario.is_authenticated and usuario == projeto.orientador)
```

- [ ] **Passo 5: Acrescentar `aprovar_projeto` a `apps/projetos/services.py`**

```python
def aprovar_projeto(projeto, por):
    """Confirma que o aluno corrigiu o que a banca pediu — fecha
    `Aprovado com Ressalvas` → `Aprovado` para o TCC I (Bloco E, spec §3.1).
    Sem checklist: o `inicio.pdf` só descreve checklist de correções para o
    TCC II (Bloco F, ainda não existe); esta transição é uma confirmação
    simples do orientador."""
    if not permissions.pode_aprovar_projeto(por, projeto):
        raise PermissionDenied("Somente o orientador do projeto pode aprová-lo.")
    if projeto.status != Projeto.APROVADO_COM_RESSALVAS:
        raise ValidationError("Só é possível aprovar um projeto aprovado com ressalvas.")

    projeto.status = Projeto.APROVADO
    projeto.save(update_fields=["status"])
```

- [ ] **Passo 6: Rodar e confirmar que os testes passam**

Run: `docker compose exec web pytest apps/projetos/tests/test_aprovacao.py -v`
Expected: todos `PASSED`.

- [ ] **Passo 7: Mutação obrigatória — checagem de status**

Comente `if projeto.status != Projeto.APROVADO_COM_RESSALVAS: raise
ValidationError(...)` em `aprovar_projeto` e rode:
Run: `docker compose exec web pytest apps/projetos/tests/test_aprovacao.py -k recusa_fora_de_aprovado -v`
Expected: `FAILED`. Desfaça, confirme `PASSED` de novo.

- [ ] **Passo 8: Rodar a suíte de `apps/projetos` inteira**

Run: `docker compose exec web pytest apps/projetos/ -v`
Expected: todos `PASSED` (nenhuma regressão em `test_fila_professor.py`,
`test_reprovacao.py` etc., que também dependem de `orientandos_atuais`).

- [ ] **Passo 9: `ruff` e `black`, depois commit**

```bash
docker compose exec web ruff check .
docker compose exec web black .
git add apps/projetos/services.py apps/projetos/permissions.py \
        apps/projetos/tests/test_aprovacao.py
git commit -m "Tarefa 2: aprovar_projeto e orientandos_atuais amplia o filtro"
```

---

## Tarefa 3: `gerar_ata` (numeração e PDF)

**Arquivos:**
- Criar: `templates/documentos/ata_pdf.html`.
- Criar: `apps/documentos/services.py`.
- Modificar: `apps/projetos/services.py` (`aprovar_projeto` chama `gerar_ata`).
- Teste: `apps/documentos/tests/test_gerar_ata.py`.

**Interfaces:**
- Consome: `Ata`, `RevisaoSUGRAD` (Tarefa 1); `Banca` (Bloco D) — a banca
  ativa do projeto (`Banca.objects.filter(projeto=projeto).exclude(
  status=Banca.CANCELADA).latest("criada_em")`).
- Produz: `apps.documentos.services.gerar_ata(projeto) -> Ata`.

- [ ] **Passo 1: Escrever os testes (falhando)**

Crie `apps/documentos/tests/test_gerar_ata.py`:

```python
"""Testes de `services.gerar_ata` (Bloco E, spec §5.2)."""

import pytest
from django.utils import timezone

from apps.bancas.models import Banca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.documentos import services
from apps.documentos.models import Ata, RevisaoSUGRAD
from apps.projetos.models import Projeto


def _cpf(indice):
    base = f"{720000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _cria_projeto_aprovado(indice_aluno, indice_professor):
    aluno = Usuario.objects.create_user(
        email=f"aluno.gerarata.{indice_aluno}@ufsm.br",
        password="x",
        nome_completo=f"Aluno Gerar Ata {indice_aluno}",
        papel=Usuario.ALUNO,
        cpf=_cpf(indice_aluno),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula=f"2026GERAR{indice_aluno:02d}")
    professor = Usuario.objects.create_user(
        email=f"professor.gerarata.{indice_professor}@ufsm.br",
        password="x",
        nome_completo=f"Professor Gerar Ata {indice_professor}",
        cpf=_cpf(indice_professor),
    )
    PerfilProfessor.objects.create(usuario=professor, siape=f"GERAR{indice_professor:03d}")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=professor,
        etapa=Projeto.TCC_I,
        status=Projeto.APROVADO,
        ano=2026,
        periodo=1,
    )
    Banca.objects.create(
        projeto=projeto,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.REALIZADA,
        nota=8.5,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
        comentario="Boa apresentação.",
    )
    return projeto


@pytest.mark.django_db
def test_gerar_ata_cria_ata_com_pdf_valido():
    projeto = _cria_projeto_aprovado(1, 2)
    ata = services.gerar_ata(projeto)
    assert ata.pdf.name
    conteudo = ata.pdf.read()
    assert conteudo.startswith(b"%PDF-")


@pytest.mark.django_db
def test_gerar_ata_cria_revisao_pendente():
    projeto = _cria_projeto_aprovado(3, 4)
    ata = services.gerar_ata(projeto)
    assert ata.revisao.status == RevisaoSUGRAD.PENDENTE


@pytest.mark.django_db
def test_gerar_ata_numeracao_sequencial_no_mesmo_ano():
    projeto1 = _cria_projeto_aprovado(5, 6)
    projeto2 = _cria_projeto_aprovado(7, 8)
    ata1 = services.gerar_ata(projeto1)
    ata2 = services.gerar_ata(projeto2)
    ano_atual = ata1.gerada_em.year
    numero1 = int(ata1.numero.split("/")[0])
    numero2 = int(ata2.numero.split("/")[0])
    assert ata1.numero.endswith(f"/{ano_atual}")
    assert numero2 == numero1 + 1


@pytest.mark.django_db
def test_gerar_ata_usa_a_banca_nao_cancelada():
    projeto = _cria_projeto_aprovado(9, 10)
    banca_cancelada = Banca.objects.create(
        projeto=projeto,
        data_hora=timezone.now(),
        local="Sala Cancelada",
        status=Banca.CANCELADA,
    )
    ata = services.gerar_ata(projeto)
    assert ata.banca_id != banca_cancelada.id
    assert ata.banca.status == Banca.REALIZADA
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `docker compose exec web pytest apps/documentos/tests/test_gerar_ata.py -v`
Expected: `ModuleNotFoundError: No module named 'apps.documentos.services'`.

- [ ] **Passo 3: Criar `templates/documentos/ata_pdf.html`**

```html
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <title>Ata {{ numero }}</title>
  <style>
    body { font-family: sans-serif; font-size: 12pt; }
    h1 { font-size: 16pt; }
    table { border-collapse: collapse; width: 100%; margin-top: 1em; }
    td, th { border: 1px solid #333; padding: 4px 8px; text-align: left; }
  </style>
</head>
<body>
  <h1>Ata de Defesa de TCC I — {{ numero }}</h1>
  <table>
    <tr><th>Aluno</th><td>{{ projeto.aluno.nome_completo }}</td></tr>
    <tr><th>Orientador</th><td>{{ projeto.orientador.nome_completo }}</td></tr>
    <tr><th>Etapa</th><td>{{ projeto.get_etapa_display }}</td></tr>
    <tr><th>Data da defesa</th><td>{{ banca.data_hora }}</td></tr>
    <tr><th>Local</th><td>{{ banca.local }}</td></tr>
    <tr>
      <th>Membros da banca</th>
      <td>
        {% for membro in banca.membros.all %}
          {% if membro.professor %}{{ membro.professor.usuario.nome_completo }}{% else %}{{ membro.nome_externo }} (externo){% endif %}{% if not forloop.last %}, {% endif %}
        {% endfor %}
      </td>
    </tr>
    <tr><th>Nota</th><td>{{ banca.nota }}</td></tr>
    <tr><th>Resultado</th><td>{{ banca.get_resultado_display }}</td></tr>
    <tr><th>Comentário da banca</th><td>{{ banca.comentario }}</td></tr>
  </table>
</body>
</html>
```

- [ ] **Passo 4: Escrever `apps/documentos/services.py`**

```python
from django.core.files.base import ContentFile
from django.template.loader import render_to_string
from django.utils import timezone

from apps.bancas.models import Banca
from apps.documentos.models import Ata, RevisaoSUGRAD


def gerar_ata(projeto):
    """Cria a `Ata` da defesa de `projeto`, numerada e com o PDF já
    renderizado — chamada por `apps.projetos.services.aprovar_projeto`
    (Bloco E, spec §3.2: aprovar e gerar a ata são o mesmo passo). Não checa
    permissão: quem decide SE o projeto pode ser aprovado é
    `aprovar_projeto`; esta função só produz o documento a partir de um
    projeto já aprovado."""
    banca = (
        Banca.objects.filter(projeto=projeto).exclude(status=Banca.CANCELADA).latest("criada_em")
    )

    ano_atual = timezone.localdate().year
    # Custo aceito (spec §4.1): condição de corrida sob criação concorrente
    # de atas no mesmo ano — aprovar um TCC I é uma ação humana de baixa
    # frequência, não um caminho de alto throughput.
    proximo = Ata.objects.filter(gerada_em__year=ano_atual).count() + 1
    numero = f"{proximo:03d}/{ano_atual}"

    corpo_html = render_to_string(
        "documentos/ata_pdf.html", {"projeto": projeto, "banca": banca, "numero": numero}
    )
    from weasyprint import HTML

    pdf_bytes = HTML(string=corpo_html).write_pdf()

    ata = Ata(projeto=projeto, banca=banca, numero=numero)
    ata.pdf.save(f"ata-{numero.replace('/', '-')}.pdf", ContentFile(pdf_bytes), save=False)
    ata.save()

    RevisaoSUGRAD.objects.create(ata=ata)

    return ata
```

(`from weasyprint import HTML` dentro da função, não no topo do arquivo —
mesmo estilo de `tests/test_pdf.py`, que já importa `weasyprint` localmente;
evita carregar a lib pesada no carregamento do módulo para todo request.)

- [ ] **Passo 5: Rodar e confirmar que os testes passam**

Run: `docker compose exec web pytest apps/documentos/tests/test_gerar_ata.py -v`
Expected: todos `PASSED`.

- [ ] **Passo 6: Plugar `gerar_ata` em `aprovar_projeto`**

Em `apps/projetos/services.py`, dentro de `aprovar_projeto` (Tarefa 2), depois
de `projeto.save(update_fields=["status"])`:

```python
    from apps.documentos.services import gerar_ata

    gerar_ata(projeto)
```

(Import local — mesmo motivo de `anexar_banca_ativa` no Bloco D: `apps/projetos`
não deve depender de `apps/documentos` no carregamento do módulo.)

- [ ] **Passo 7: Rodar a suíte de `apps/projetos` de novo**

Run: `docker compose exec web pytest apps/projetos/tests/test_aprovacao.py -v`
Expected: ainda todos `PASSED` (agora `aprovar_projeto` também gera uma
`Ata` de verdade — os testes da Tarefa 2 não afirmam nada sobre `Ata`, então
continuam passando sem alteração).

- [ ] **Passo 8: `ruff` e `black`, depois commit**

```bash
docker compose exec web ruff check .
docker compose exec web black .
git add apps/documentos/services.py apps/documentos/tests/test_gerar_ata.py \
        templates/documentos/ata_pdf.html apps/projetos/services.py
git commit -m "Tarefa 3: gerar_ata (numeracao e PDF via WeasyPrint)"
```

---

## Tarefa 4: `aprovar_ata`/`devolver_ata` (permissão por papel)

**Arquivos:**
- Criar: `apps/documentos/permissions.py`.
- Modificar: `apps/documentos/services.py`.
- Teste: `apps/documentos/tests/test_revisao.py`.

**Interfaces:**
- Produz: `permissions.pode_revisar_ata(usuario) -> bool`;
  `permissions.pode_reenviar_ata(usuario, ata) -> bool`;
  `services.aprovar_ata(ata, por) -> None`;
  `services.devolver_ata(ata, por, comentario) -> None`.

- [ ] **Passo 1: Escrever os testes (falhando)**

Crie `apps/documentos/tests/test_revisao.py`:

```python
"""Testes de `services.aprovar_ata`/`devolver_ata` (Bloco E, spec §5.2) e
`permissions.pode_revisar_ata` (permissão por PAPEL, não posse — spec §3.5)."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.bancas.models import Banca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.documentos import permissions, services
from apps.documentos.models import RevisaoSUGRAD
from apps.projetos.models import Projeto


def _cpf(indice):
    base = f"{730000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


@pytest.fixture
def sugrad(db):
    return Usuario.objects.create_user(
        email="sugrad.revisao@ufsm.br",
        password="x",
        nome_completo="SUGRAD",
        papel=Usuario.SUGRAD,
        cpf=None,
    )


@pytest.fixture
def ata_pendente(db):
    aluno = Usuario.objects.create_user(
        email="aluno.revisao@ufsm.br",
        password="x",
        nome_completo="Aluno Revisão",
        papel=Usuario.ALUNO,
        cpf=_cpf(1),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026REVISAO1")
    professor = Usuario.objects.create_user(
        email="professor.revisao@ufsm.br",
        password="x",
        nome_completo="Professor Revisão",
        cpf=_cpf(2),
    )
    PerfilProfessor.objects.create(usuario=professor, siape="REVISAO01")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=professor,
        etapa=Projeto.TCC_I,
        status=Projeto.APROVADO,
        ano=2026,
        periodo=1,
    )
    Banca.objects.create(
        projeto=projeto,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.REALIZADA,
        nota=8.0,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
    )
    return services.gerar_ata(projeto)


@pytest.mark.django_db
def test_pode_revisar_ata_e_por_papel_nao_posse(sugrad, ata_pendente):
    assert permissions.pode_revisar_ata(sugrad)
    assert not permissions.pode_revisar_ata(ata_pendente.projeto.orientador)


@pytest.mark.django_db
def test_aprovar_ata_conclui_o_projeto(ata_pendente, sugrad):
    services.aprovar_ata(ata_pendente, por=sugrad)
    ata_pendente.revisao.refresh_from_db()
    assert ata_pendente.revisao.status == RevisaoSUGRAD.APROVADA
    assert ata_pendente.revisao.decidida_em is not None
    ata_pendente.projeto.refresh_from_db()
    assert ata_pendente.projeto.status == Projeto.CONCLUIDO


@pytest.mark.django_db
def test_aprovar_ata_recusa_quem_nao_e_sugrad(ata_pendente):
    with pytest.raises(PermissionDenied):
        services.aprovar_ata(ata_pendente, por=ata_pendente.projeto.orientador)


@pytest.mark.django_db
def test_devolver_ata_grava_comentario_sem_mudar_status_do_projeto(ata_pendente, sugrad):
    services.devolver_ata(ata_pendente, por=sugrad, comentario="Falta assinatura.")
    ata_pendente.revisao.refresh_from_db()
    assert ata_pendente.revisao.status == RevisaoSUGRAD.DEVOLVIDA
    assert ata_pendente.revisao.comentario == "Falta assinatura."
    ata_pendente.projeto.refresh_from_db()
    assert ata_pendente.projeto.status == Projeto.APROVADO


@pytest.mark.django_db
def test_aprovar_ata_recusa_revisar_duas_vezes(ata_pendente, sugrad):
    services.aprovar_ata(ata_pendente, por=sugrad)
    with pytest.raises(ValidationError):
        services.aprovar_ata(ata_pendente, por=sugrad)
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `docker compose exec web pytest apps/documentos/tests/test_revisao.py -v`
Expected: `ModuleNotFoundError: No module named 'apps.documentos.permissions'`.

- [ ] **Passo 3: Escrever `apps/documentos/permissions.py`**

```python
from apps.contas.models import Usuario


def pode_revisar_ata(usuario):
    """`usuario` tem `papel == Usuario.SUGRAD` — permissão por PAPEL, não
    posse (Bloco E, spec §3.5): a SUGRAD é um setor único (regra
    inegociável nº 2 do CLAUDE.md), não dono de nenhum projeto específico —
    ela revisa a ata de QUALQUER projeto. Mesmo formato de
    `apps.projetos.permissions.pode_ajustar_orientacao`, que já checa
    `is_coordenador` em vez de posse."""
    return bool(usuario and usuario.is_authenticated and usuario.papel == Usuario.SUGRAD)


def pode_reenviar_ata(usuario, ata):
    """`usuario` é exatamente o orientador do projeto da `ata` — posse,
    não papel (Bloco E, spec §5.2)."""
    return bool(usuario and usuario.is_authenticated and usuario == ata.projeto.orientador)
```

- [ ] **Passo 4: Acrescentar `aprovar_ata`/`devolver_ata` a `apps/documentos/services.py`**

Ao topo do arquivo, acrescente:

```python
from django.core.exceptions import PermissionDenied, ValidationError

from apps.documentos import permissions
from apps.projetos.models import Projeto
```

E ao final do arquivo:

```python
def aprovar_ata(ata, por):
    """A SUGRAD aprova a ata — fecha `Aprovado` → `Concluído` (Bloco E,
    spec §5.2). Permissão por papel (§3.5), não por posse do projeto."""
    if not permissions.pode_revisar_ata(por):
        raise PermissionDenied("Somente a SUGRAD revisa atas.")
    revisao = ata.revisao
    if revisao.status != RevisaoSUGRAD.PENDENTE:
        raise ValidationError("Esta ata já foi revisada.")

    revisao.status = RevisaoSUGRAD.APROVADA
    revisao.decidida_em = timezone.now()
    revisao.save(update_fields=["status", "decidida_em"])

    ata.projeto.status = Projeto.CONCLUIDO
    ata.projeto.save(update_fields=["status"])


def devolver_ata(ata, por, comentario):
    """A SUGRAD devolve a ata com um comentário — não muda
    `Projeto.status` (§3.4): a devolução é sobre o documento, não sobre o
    mérito acadêmico já decidido pela banca."""
    if not permissions.pode_revisar_ata(por):
        raise PermissionDenied("Somente a SUGRAD revisa atas.")
    revisao = ata.revisao
    if revisao.status != RevisaoSUGRAD.PENDENTE:
        raise ValidationError("Esta ata já foi revisada.")

    revisao.status = RevisaoSUGRAD.DEVOLVIDA
    revisao.comentario = comentario
    revisao.decidida_em = timezone.now()
    revisao.save(update_fields=["status", "comentario", "decidida_em"])
```

`RevisaoSUGRAD` já está importado no topo do arquivo (Tarefa 3). Adicione
`Usuario`? Não é preciso aqui — `Projeto.CONCLUIDO` e `Projeto.APROVADO` já
vêm de `apps.projetos.models.Projeto`, importado acima.

- [ ] **Passo 5: Rodar e confirmar que os testes passam**

Run: `docker compose exec web pytest apps/documentos/tests/test_revisao.py -v`
Expected: todos `PASSED`.

- [ ] **Passo 6: Mutação obrigatória — checagem de dupla revisão**

Comente `if revisao.status != RevisaoSUGRAD.PENDENTE: raise
ValidationError(...)` em `aprovar_ata` e rode:
Run: `docker compose exec web pytest apps/documentos/tests/test_revisao.py -k recusa_revisar_duas_vezes -v`
Expected: `FAILED`. Desfaça, confirme `PASSED` de novo.

- [ ] **Passo 7: `ruff` e `black`, depois commit**

```bash
docker compose exec web ruff check .
docker compose exec web black .
git add apps/documentos/permissions.py apps/documentos/services.py \
        apps/documentos/tests/test_revisao.py
git commit -m "Tarefa 4: aprovar_ata e devolver_ata"
```

---

## Tarefa 5: `reenviar_a_sugrad` e as views de `apps/projetos`

**Arquivos:**
- Modificar: `apps/documentos/services.py`.
- Modificar: `apps/projetos/views.py`, `apps/projetos/urls.py`.
- Teste: `apps/documentos/tests/test_revisao.py` (extensão),
  `apps/projetos/tests/test_aprovacao.py` (extensão, views HTTP).

**Interfaces:**
- Produz: `services.reenviar_a_sugrad(ata, por) -> None`;
  `views.aprovar_projeto_view`, `views.reenviar_ata_view` (em
  `apps/projetos`).

- [ ] **Passo 1: Escrever o teste de `reenviar_a_sugrad` (falhando)**

Acrescente a `apps/documentos/tests/test_revisao.py`:

```python
@pytest.mark.django_db
def test_reenviar_a_sugrad_volta_para_pendente(ata_pendente, sugrad):
    services.devolver_ata(ata_pendente, por=sugrad, comentario="Corrija a data.")
    services.reenviar_a_sugrad(ata_pendente, por=ata_pendente.projeto.orientador)
    ata_pendente.revisao.refresh_from_db()
    assert ata_pendente.revisao.status == RevisaoSUGRAD.PENDENTE


@pytest.mark.django_db
def test_reenviar_a_sugrad_recusa_quem_nao_e_o_orientador(ata_pendente, sugrad):
    services.devolver_ata(ata_pendente, por=sugrad, comentario="Corrija a data.")
    outro = Usuario.objects.create_user(
        email="outro.reenviar@ufsm.br", password="x", nome_completo="Outro Reenviar", cpf=_cpf(3)
    )
    with pytest.raises(PermissionDenied):
        services.reenviar_a_sugrad(ata_pendente, por=outro)


@pytest.mark.django_db
def test_reenviar_a_sugrad_recusa_fora_de_devolvida(ata_pendente):
    with pytest.raises(ValidationError):
        services.reenviar_a_sugrad(ata_pendente, por=ata_pendente.projeto.orientador)
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `docker compose exec web pytest apps/documentos/tests/test_revisao.py -k reenviar -v`
Expected: `AttributeError: module 'apps.documentos.services' has no attribute
'reenviar_a_sugrad'`.

- [ ] **Passo 3: Acrescentar `reenviar_a_sugrad` a `apps/documentos/services.py`**

```python
def reenviar_a_sugrad(ata, por):
    """O orientador reenvia uma ata `DEVOLVIDA` — volta a `PENDENTE`
    (Bloco E, spec §5.2). Não gera um PDF novo nem uma `Ata` nova (§2 do
    spec: reabre a mesma revisão)."""
    if not permissions.pode_reenviar_ata(por, ata):
        raise PermissionDenied("Somente o orientador do projeto reenvia a ata.")
    revisao = ata.revisao
    if revisao.status != RevisaoSUGRAD.DEVOLVIDA:
        raise ValidationError("Só é possível reenviar uma ata devolvida.")

    revisao.status = RevisaoSUGRAD.PENDENTE
    revisao.save(update_fields=["status"])
```

- [ ] **Passo 4: Rodar e confirmar que os testes passam**

Run: `docker compose exec web pytest apps/documentos/tests/test_revisao.py -v`
Expected: todos `PASSED`.

- [ ] **Passo 5: Escrever os testes HTTP das duas views de `apps/projetos` (falhando)**

Acrescente a `apps/projetos/tests/test_aprovacao.py`:

```python
@pytest.mark.django_db
def test_aprovar_projeto_view_redireciona(client, projeto_com_ressalvas, orientador):
    client.force_login(orientador.usuario)
    resposta = client.post(f"/orientacoes/{projeto_com_ressalvas.pk}/aprovar/")
    assert resposta.status_code == 302
    projeto_com_ressalvas.refresh_from_db()
    assert projeto_com_ressalvas.status == Projeto.APROVADO


@pytest.mark.django_db
def test_aprovar_projeto_view_recusa_projeto_alheio_com_404(client, projeto_com_ressalvas):
    outro = _professor(7, "Outro Professor Aprovar View")
    client.force_login(outro.usuario)
    resposta = client.post(f"/orientacoes/{projeto_com_ressalvas.pk}/aprovar/")
    assert resposta.status_code == 404


@pytest.mark.django_db
def test_reenviar_ata_view_redireciona(client, orientador):
    from apps.bancas.models import Banca
    from apps.documentos import services as documentos_services
    from django.utils import timezone

    aluno = _aluno(8, "Aluno Reenviar View")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.APROVADO,
        ano=2026,
        periodo=1,
    )
    Banca.objects.create(
        projeto=projeto,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.REALIZADA,
        nota=7.0,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
    )
    ata = documentos_services.gerar_ata(projeto)
    sugrad = Usuario.objects.create_user(
        email="sugrad.reenviarview@ufsm.br",
        password="x",
        nome_completo="SUGRAD",
        papel=Usuario.SUGRAD,
        cpf=None,
    )
    documentos_services.devolver_ata(ata, por=sugrad, comentario="Falta algo.")

    client.force_login(orientador.usuario)
    resposta = client.post(f"/orientacoes/{ata.pk}/reenviar-sugrad/")
    assert resposta.status_code == 302
    ata.revisao.refresh_from_db()
    from apps.documentos.models import RevisaoSUGRAD

    assert ata.revisao.status == RevisaoSUGRAD.PENDENTE
```

- [ ] **Passo 6: Rodar e confirmar que falha**

Run: `docker compose exec web pytest apps/projetos/tests/test_aprovacao.py -k "view" -v`
Expected: `404`/`NoReverseMatch` — as rotas ainda não existem.

- [ ] **Passo 7: Acrescentar as duas views a `apps/projetos/views.py`**

Ao final do arquivo:

```python
@login_required
@require_POST
def aprovar_projeto_view(request, projeto_id):
    """Aprova um `Projeto` `Aprovado com Ressalvas` — gera a ata e notifica
    a SUGRAD (Bloco E, spec §7). Lookup escopado ao orientador autenticado,
    mesmo padrão de `desativar_tema`."""
    projeto = get_object_or_404(Projeto, pk=projeto_id, orientador=request.user)
    services.aprovar_projeto(projeto, por=request.user)
    messages.success(request, "Projeto aprovado. A ata foi gerada e enviada à SUGRAD.")
    return redirect("projetos:orientacoes")


@login_required
@require_POST
def reenviar_ata_view(request, ata_id):
    """Reenvia à SUGRAD uma ata devolvida (Bloco E, spec §7). Lookup
    escopado via `projeto__orientador`, mesmo raciocínio de
    `aprovar_projeto_view`."""
    from apps.documentos.models import Ata
    from apps.documentos.services import reenviar_a_sugrad

    ata = get_object_or_404(Ata, pk=ata_id, projeto__orientador=request.user)
    reenviar_a_sugrad(ata, por=request.user)
    messages.success(request, "Ata reenviada à SUGRAD.")
    return redirect("projetos:orientacoes")
```

(Import local de `Ata`/`reenviar_a_sugrad` dentro da view — mesmo motivo do
import local em `orientacoes`/`aprovar_projeto`: `apps/projetos` não deve
depender de `apps/documentos` no carregamento do módulo.)

- [ ] **Passo 8: Acrescentar as duas rotas a `apps/projetos/urls.py`**

```python
    path(
        "orientacoes/<int:projeto_id>/aprovar/",
        views.aprovar_projeto_view,
        name="aprovar_projeto",
    ),
    path(
        "orientacoes/<int:ata_id>/reenviar-sugrad/",
        views.reenviar_ata_view,
        name="reenviar_ata",
    ),
```

- [ ] **Passo 9: Rodar e confirmar que os testes passam**

Run: `docker compose exec web pytest apps/projetos/tests/test_aprovacao.py -v`
Expected: todos `PASSED`.

- [ ] **Passo 10: `ruff` e `black`, depois commit**

```bash
docker compose exec web ruff check .
docker compose exec web black .
git add apps/documentos/services.py apps/documentos/tests/test_revisao.py \
        apps/projetos/views.py apps/projetos/urls.py \
        apps/projetos/tests/test_aprovacao.py
git commit -m "Tarefa 5: reenviar_a_sugrad e as views de aprovar/reenviar"
```

---

## Tarefa 6: Notificações (`apps/documentos/tasks.py`)

**Arquivos:**
- Criar: `apps/documentos/tasks.py`, `templates/email/ata_para_sugrad.txt`,
  `templates/email/ata_devolvida.txt`.
- Modificar: `apps/documentos/services.py` (`gerar_ata`, `devolver_ata`,
  `reenviar_a_sugrad` disparam as tarefas).
- Teste: `apps/documentos/tests/test_notificacoes.py`.

**Interfaces:**
- Produz: `tasks.enviar_ata_para_sugrad(ata_id)`,
  `tasks.enviar_devolucao_para_orientador(ata_id)`.

- [ ] **Passo 1: Escrever os testes (falhando)**

Crie `apps/documentos/tests/test_notificacoes.py`:

```python
"""Testes de `tasks.enviar_ata_para_sugrad`/`enviar_devolucao_para_orientador`
(Bloco E, spec §8). Mesmo padrão de `apps/bancas/tests/test_notificacoes.py`:
`django_capture_on_commit_callbacks` + `CELERY_TASK_ALWAYS_EAGER`."""

import pytest
from django.core import mail
from django.utils import timezone

from apps.bancas.models import Banca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.documentos import services
from apps.projetos.models import Projeto


def _cpf(indice):
    base = f"{740000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


@pytest.fixture
def cenario(db):
    sugrad = Usuario.objects.create_user(
        email="sugrad.notif@ufsm.br",
        password="x",
        nome_completo="SUGRAD",
        papel=Usuario.SUGRAD,
        cpf=None,
    )
    aluno = Usuario.objects.create_user(
        email="aluno.notifata@ufsm.br",
        password="x",
        nome_completo="Aluno Notif Ata",
        papel=Usuario.ALUNO,
        cpf=_cpf(1),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026NOTIFATA1")
    orientador = Usuario.objects.create_user(
        email="orientador.notifata@ufsm.br",
        password="x",
        nome_completo="Orientador Notif Ata",
        cpf=_cpf(2),
    )
    PerfilProfessor.objects.create(usuario=orientador, siape="NOTIFATA1")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador,
        etapa=Projeto.TCC_I,
        status=Projeto.APROVADO,
        ano=2026,
        periodo=1,
    )
    Banca.objects.create(
        projeto=projeto,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.REALIZADA,
        nota=8.0,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
    )
    return {"sugrad": sugrad, "aluno": aluno, "orientador": orientador, "projeto": projeto}


@pytest.mark.django_db
def test_gerar_ata_notifica_sugrad(settings, django_capture_on_commit_callbacks, cenario):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with django_capture_on_commit_callbacks(execute=True):
        services.gerar_ata(cenario["projeto"])
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [cenario["sugrad"].email]


@pytest.mark.django_db
def test_devolver_ata_notifica_orientador(settings, django_capture_on_commit_callbacks, cenario):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with django_capture_on_commit_callbacks(execute=True):
        ata = services.gerar_ata(cenario["projeto"])
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        services.devolver_ata(ata, por=cenario["sugrad"], comentario="Falta a assinatura.")
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [cenario["orientador"].email]


@pytest.mark.django_db
def test_reenviar_a_sugrad_notifica_sugrad_de_novo(
    settings, django_capture_on_commit_callbacks, cenario
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with django_capture_on_commit_callbacks(execute=True):
        ata = services.gerar_ata(cenario["projeto"])
    with django_capture_on_commit_callbacks(execute=True):
        services.devolver_ata(ata, por=cenario["sugrad"], comentario="Falta algo.")
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        services.reenviar_a_sugrad(ata, por=cenario["orientador"])
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [cenario["sugrad"].email]


@pytest.mark.django_db
def test_aprovar_ata_nao_notifica(settings, django_capture_on_commit_callbacks, cenario):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with django_capture_on_commit_callbacks(execute=True):
        ata = services.gerar_ata(cenario["projeto"])
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        services.aprovar_ata(ata, por=cenario["sugrad"])
    assert len(mail.outbox) == 0
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `docker compose exec web pytest apps/documentos/tests/test_notificacoes.py -v`
Expected: `test_gerar_ata_notifica_sugrad` e os outros dois de notificação
falham (`mail.outbox` vazio); `test_aprovar_ata_nao_notifica` passa à toa.

- [ ] **Passo 3: Criar os templates de e-mail**

`templates/email/ata_para_sugrad.txt`:

```
Olá, SUGRAD.

Uma nova ata está disponível para revisão:

Aluno: {{ ata.projeto.aluno.nome_completo }}
Número da ata: {{ ata.numero }}

Entre no sistema para baixar o PDF e decidir: {{ link }}

OrientaSI — Sistema de Gestão de TCC
```

`templates/email/ata_devolvida.txt`:

```
Olá, {{ orientador.nome_completo }}.

A SUGRAD devolveu a ata {{ ata.numero }} de {{ ata.projeto.aluno.nome_completo }}
com o seguinte comentário:

{{ comentario }}

Entre no sistema para reenviar depois de resolver: {{ link }}

OrientaSI — Sistema de Gestão de TCC
```

- [ ] **Passo 4: Escrever `apps/documentos/tasks.py`**

```python
import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

logger = logging.getLogger(__name__)


def _link_login():
    return f"{settings.URL_BASE}{reverse('login')}"


@shared_task(bind=True, max_retries=3)
def enviar_ata_para_sugrad(self, ata_id):
    """Avisa a SUGRAD de que uma ata está pronta para revisão — disparada
    por `gerar_ata` e por `reenviar_a_sugrad` (Bloco E, spec §8). Destinatário:
    a única conta `papel=SUGRAD` ativa (mesmo raciocínio de
    `apps.contas.services.coordenadores`, adaptado a uma conta só)."""
    from apps.contas.models import Usuario
    from apps.documentos.models import Ata

    ata = Ata.objects.select_related("projeto__aluno").get(pk=ata_id)
    sugrad = Usuario.objects.filter(papel=Usuario.SUGRAD, is_active=True).first()
    if sugrad is None:
        # Mesma decisão de `enviar_esgotamento` (Bloco B) quando não há
        # coordenador ativo: registra e não falha a aprovação do projeto.
        logger.warning(
            "enviar_ata_para_sugrad: ata %s pronta, mas não há conta SUGRAD ativa.", ata_id
        )
        return

    corpo = render_to_string("email/ata_para_sugrad.txt", {"ata": ata, "link": _link_login()})
    try:
        send_mail(
            subject="OrientaSI — nova ata para revisão",
            message=corpo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[sugrad.email],
        )
    except Exception as erro:  # noqa: BLE001 — repetimos qualquer falha de entrega
        raise self.retry(exc=erro, countdown=60 * 2**self.request.retries) from erro


@shared_task(bind=True, max_retries=3)
def enviar_devolucao_para_orientador(self, ata_id):
    """Avisa o orientador de que a SUGRAD devolveu a ata, com o comentário
    (Bloco E, spec §8)."""
    from apps.documentos.models import Ata

    ata = Ata.objects.select_related("projeto__orientador", "revisao").get(pk=ata_id)
    orientador = ata.projeto.orientador
    corpo = render_to_string(
        "email/ata_devolvida.txt",
        {"ata": ata, "orientador": orientador, "comentario": ata.revisao.comentario, "link": _link_login()},
    )
    try:
        send_mail(
            subject="OrientaSI — a SUGRAD devolveu uma ata",
            message=corpo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[orientador.email],
        )
    except Exception as erro:  # noqa: BLE001 — repetimos qualquer falha de entrega
        raise self.retry(exc=erro, countdown=60 * 2**self.request.retries) from erro
```

- [ ] **Passo 5: Disparar as tarefas em `gerar_ata`/`devolver_ata`/`reenviar_a_sugrad`**

Em `apps/documentos/services.py`, acrescente ao topo:

```python
from django.db import transaction

from apps.documentos.tasks import enviar_ata_para_sugrad, enviar_devolucao_para_orientador
```

No final de `gerar_ata` (antes do `return ata`):

```python
    transaction.on_commit(lambda: enviar_ata_para_sugrad.delay(ata.id))
```

No final de `devolver_ata`:

```python
    transaction.on_commit(lambda: enviar_devolucao_para_orientador.delay(ata.id))
```

No final de `reenviar_a_sugrad`:

```python
    transaction.on_commit(lambda: enviar_ata_para_sugrad.delay(ata.id))
```

- [ ] **Passo 6: Rodar e confirmar que os testes passam**

Run: `docker compose exec web pytest apps/documentos/tests/test_notificacoes.py -v`
Expected: todos `PASSED`.

- [ ] **Passo 7: Rodar a suíte de `apps/documentos` inteira**

Run: `docker compose exec web pytest apps/documentos/ -v`
Expected: todos `PASSED` (os testes das Tarefas 1, 3 e 4 não usam
`django_capture_on_commit_callbacks`, então o `on_commit` novo não dispara
neles — mesma observação já registrada no Bloco D).

- [ ] **Passo 8: `ruff` e `black`, depois commit**

```bash
docker compose exec web ruff check .
docker compose exec web black .
git add apps/documentos/tasks.py apps/documentos/services.py \
        apps/documentos/tests/test_notificacoes.py \
        templates/email/ata_para_sugrad.txt templates/email/ata_devolvida.txt
git commit -m "Tarefa 6: notificacoes de ata para a SUGRAD e de devolucao"
```

---

## Tarefa 7: Painel da SUGRAD

**Arquivos:**
- Criar: `apps/documentos/forms.py`, `apps/documentos/views.py`,
  `apps/documentos/urls.py`, `templates/documentos/painel_sugrad.html`.
- Modificar: `config/urls.py`.
- Teste: `apps/documentos/tests/test_formularios.py`, `apps/documentos/tests/test_telas.py`.

**Interfaces:**
- Consome: `services.aprovar_ata`/`devolver_ata` (Tarefa 4).
- Produz: `FormularioDevolverAta`; rota `documentos:painel`.

- [ ] **Passo 1: Escrever o teste de formulário (falhando)**

Crie `apps/documentos/tests/test_formularios.py`:

```python
"""Teste de `FormularioDevolverAta` (Bloco E, spec §7)."""

from apps.documentos.forms import FormularioDevolverAta


def test_formulario_devolver_ata_exige_comentario():
    formulario = FormularioDevolverAta(data={"comentario": ""})
    assert not formulario.is_valid()


def test_formulario_devolver_ata_aceita_comentario():
    formulario = FormularioDevolverAta(data={"comentario": "Falta a assinatura do orientador."})
    assert formulario.is_valid(), formulario.errors
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `docker compose exec web pytest apps/documentos/tests/test_formularios.py -v`
Expected: `ModuleNotFoundError: No module named 'apps.documentos.forms'`.

- [ ] **Passo 3: Escrever `apps/documentos/forms.py`**

```python
from django import forms

from apps.contas.forms import MisturaAcessibilidadeFormulario


class FormularioDevolverAta(MisturaAcessibilidadeFormulario, forms.Form):
    """Devolução de uma ata pela SUGRAD (Bloco E, spec §7) — o comentário é
    obrigatório: sem ele, a devolução é silêncio com outro nome, e o
    orientador não sabe o que corrigir (mesmo raciocínio de
    `FormularioRecusaOpcao`, Bloco B)."""

    comentario = forms.CharField(
        label="Comentário",
        widget=forms.Textarea(attrs={"class": "textarea w-full"}),
    )
```

- [ ] **Passo 4: Rodar e confirmar que os testes passam**

Run: `docker compose exec web pytest apps/documentos/tests/test_formularios.py -v`
Expected: todos `PASSED`.

- [ ] **Passo 5: Escrever os testes de tela (falhando)**

Crie `apps/documentos/tests/test_telas.py`:

```python
"""Testes HTTP de `/painel/sugrad/` (Bloco E, spec §7). Portão de PAPEL, sem
lookup de posse — lista atas de qualquer projeto (mesmo padrão de
`painel_orientacoes`, Bloco B)."""

import pytest
from django.utils import timezone

from apps.bancas.models import Banca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.documentos import services
from apps.projetos.models import Projeto


def _cpf(indice):
    base = f"{750000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


@pytest.fixture
def ata_pendente(db):
    aluno = Usuario.objects.create_user(
        email="aluno.telasugrad@ufsm.br",
        password="x",
        nome_completo="Aluno Tela SUGRAD",
        papel=Usuario.ALUNO,
        cpf=_cpf(1),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026TELASUG1")
    orientador = Usuario.objects.create_user(
        email="orientador.telasugrad@ufsm.br",
        password="x",
        nome_completo="Orientador Tela SUGRAD",
        cpf=_cpf(2),
    )
    PerfilProfessor.objects.create(usuario=orientador, siape="TELASUG01")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador,
        etapa=Projeto.TCC_I,
        status=Projeto.APROVADO,
        ano=2026,
        periodo=1,
    )
    Banca.objects.create(
        projeto=projeto,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.REALIZADA,
        nota=8.0,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
    )
    return services.gerar_ata(projeto)


@pytest.fixture
def sugrad(db):
    return Usuario.objects.create_user(
        email="sugrad.tela@ufsm.br",
        password="x",
        nome_completo="SUGRAD",
        papel=Usuario.SUGRAD,
        cpf=None,
    )


@pytest.mark.django_db
def test_painel_lista_ata_pendente(client, ata_pendente, sugrad):
    client.force_login(sugrad)
    resposta = client.get("/painel/sugrad/")
    assert ata_pendente.numero in resposta.content.decode()


@pytest.mark.django_db
def test_painel_recusa_quem_nao_e_sugrad(client, ata_pendente):
    client.force_login(ata_pendente.projeto.orientador)
    resposta = client.get("/painel/sugrad/")
    assert resposta.status_code == 403


@pytest.mark.django_db
def test_aprovar_ata_view_redireciona(client, ata_pendente, sugrad):
    client.force_login(sugrad)
    resposta = client.post(f"/painel/sugrad/{ata_pendente.pk}/aprovar/")
    assert resposta.status_code == 302
    ata_pendente.projeto.refresh_from_db()
    assert ata_pendente.projeto.status == Projeto.CONCLUIDO


@pytest.mark.django_db
def test_devolver_ata_view_exige_comentario(client, ata_pendente, sugrad):
    client.force_login(sugrad)
    resposta = client.post(f"/painel/sugrad/{ata_pendente.pk}/devolver/", {"comentario": ""})
    assert resposta.status_code == 302
    ata_pendente.revisao.refresh_from_db()
    from apps.documentos.models import RevisaoSUGRAD

    assert ata_pendente.revisao.status == RevisaoSUGRAD.PENDENTE
```

- [ ] **Passo 6: Rodar e confirmar que falha**

Run: `docker compose exec web pytest apps/documentos/tests/test_telas.py -v`
Expected: `404`/erro de resolução de URL — `apps/documentos/urls.py`/`views.py`
não existem ainda, e `config/urls.py` não inclui o app.

- [ ] **Passo 7: Escrever `apps/documentos/views.py`**

```python
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.documentos import permissions, services
from apps.documentos.forms import FormularioDevolverAta
from apps.documentos.models import Ata, RevisaoSUGRAD
from apps.projetos.permissions import garante


@login_required
def painel(request):
    """Painel da SUGRAD: lista atas `PENDENTE` (Bloco E, spec §7). Portão de
    PAPEL, sem lookup de posse — mesmo padrão de `painel_orientacoes`
    (Bloco B): a SUGRAD revisa a ata de QUALQUER projeto."""
    garante(permissions.pode_revisar_ata(request.user), "Esta área é exclusiva da SUGRAD.")

    atas_pendentes = Ata.objects.filter(revisao__status=RevisaoSUGRAD.PENDENTE).select_related(
        "projeto__aluno", "projeto__orientador"
    )
    itens = [
        {"ata": ata, "formulario_devolver": FormularioDevolverAta(auto_id=f"id_devolver_{ata.pk}_%s")}
        for ata in atas_pendentes
    ]
    return render(request, "documentos/painel_sugrad.html", {"itens": itens})


@login_required
def aprovar_ata_view(request, ata_id):
    """Aprova uma ata pendente (Bloco E, spec §7)."""
    garante(permissions.pode_revisar_ata(request.user), "Esta área é exclusiva da SUGRAD.")
    ata = get_object_or_404(Ata, pk=ata_id)
    services.aprovar_ata(ata, por=request.user)
    messages.success(request, "Ata aprovada. Projeto concluído.")
    return redirect("documentos:painel")


@login_required
def devolver_ata_view(request, ata_id):
    """Devolve uma ata pendente com comentário (Bloco E, spec §7).

    Um formulário inválido (comentário em branco) não impede que a lista
    inteira seja perdida: a resposta é sempre um redirect para
    `documentos:painel` (mesmo padrão de `recusar_opcao_view`, Bloco B),
    com o erro relatado via `messages` — não há estado de formulário
    parcial para preservar entre POST e a nova renderização, porque a
    página lista várias atas, não edita um registro único.
    """
    garante(permissions.pode_revisar_ata(request.user), "Esta área é exclusiva da SUGRAD.")
    ata = get_object_or_404(Ata, pk=ata_id)
    formulario = FormularioDevolverAta(request.POST)
    if not formulario.is_valid():
        messages.error(request, "Informe um comentário para devolver a ata.")
        return redirect("documentos:painel")

    services.devolver_ata(ata, por=request.user, comentario=formulario.cleaned_data["comentario"])
    messages.success(request, "Ata devolvida.")
    return redirect("documentos:painel")
```

`RevisaoSUGRAD` não precisa ser importado em `views.py` além do que `painel`
já usa (`revisao__status=RevisaoSUGRAD.PENDENTE`); `devolver_ata_view` não
usa a constante diretamente.

`permissions.garante` não existe em `apps/documentos/permissions.py` — em vez
de duplicar a função `garante` (já existe em `apps/projetos/permissions.py`),
importe-a de lá (`from apps.projetos.permissions import garante`), como o
código acima já faz. Isso é aceitável: `garante` é um utilitário puro (não
depende de nenhum modelo de `apps.projetos`), e duplicá-la criaria duas
implementações da mesma checagem para manter sincronizadas.

- [ ] **Passo 8: Escrever `apps/documentos/urls.py`**

```python
from django.urls import path

from apps.documentos import views

app_name = "documentos"

urlpatterns = [
    path("painel/sugrad/", views.painel, name="painel"),
    path("painel/sugrad/<int:ata_id>/aprovar/", views.aprovar_ata_view, name="aprovar_ata"),
    path("painel/sugrad/<int:ata_id>/devolver/", views.devolver_ata_view, name="devolver_ata"),
]
```

- [ ] **Passo 9: Registrar em `config/urls.py`**

```python
    path("", include("apps.documentos.urls")),
```

- [ ] **Passo 10: Criar `templates/documentos/painel_sugrad.html`**

```html
{% extends "base.html" %}

{% block titulo %} — Painel SUGRAD{% endblock %}

{% block conteudo %}
  <article class="mx-auto max-w-3xl rounded-box bg-base-100 p-6 shadow-sm">
    <h1 class="font-display text-2xl font-bold text-primary">Painel SUGRAD</h1>
    <p class="mt-2 text-sm text-base-content/80">Atas aguardando revisão.</p>

    {% if itens %}
      <ul class="mt-4 space-y-6">
        {% for item in itens %}
          <li class="rounded-box border border-base-300 p-4">
            <p class="font-medium">{{ item.ata.numero }} — {{ item.ata.projeto.aluno.nome_completo }}</p>
            <p class="text-sm text-base-content/80">Orientador: {{ item.ata.projeto.orientador.nome_completo }}</p>
            <p class="mt-2">
              <a href="{{ item.ata.pdf.url }}" class="link">Baixar PDF da ata</a>
            </p>

            <div class="mt-4 flex flex-wrap items-start gap-6">
              <form method="post" action="{% url 'documentos:aprovar_ata' item.ata.pk %}">
                {% csrf_token %}
                <button type="submit" class="btn btn-primary">
                  Aprovar
                  <span class="sr-only"> ata {{ item.ata.numero }}</span>
                </button>
              </form>

              <form
                method="post"
                action="{% url 'documentos:devolver_ata' item.ata.pk %}"
                class="w-full flex-1 space-y-2 sm:min-w-64"
              >
                {% csrf_token %}
                {% with campo=item.formulario_devolver.comentario %}
                  {% include "contas/_campo.html" with campo=campo %}
                {% endwith %}
                <button type="submit" class="btn btn-outline">
                  Devolver
                  <span class="sr-only"> ata {{ item.ata.numero }}</span>
                </button>
              </form>
            </div>
          </li>
        {% endfor %}
      </ul>
    {% else %}
      <p class="mt-4 text-base-content/80">Nenhuma ata aguardando revisão no momento.</p>
    {% endif %}
  </article>
{% endblock %}
```

- [ ] **Passo 11: Rodar e confirmar que os testes passam**

Run: `docker compose exec web pytest apps/documentos/tests/test_telas.py -v`
Expected: todos `PASSED`.

- [ ] **Passo 12: Rodar a suíte de `apps/documentos` inteira**

Run: `docker compose exec web pytest apps/documentos/ -v`
Expected: todos `PASSED`.

- [ ] **Passo 13: `ruff` e `black`, depois commit**

```bash
docker compose exec web ruff check .
docker compose exec web black .
git add apps/documentos/forms.py apps/documentos/views.py apps/documentos/urls.py \
        config/urls.py templates/documentos/painel_sugrad.html \
        apps/documentos/tests/test_formularios.py apps/documentos/tests/test_telas.py
git commit -m "Tarefa 7: painel da SUGRAD"
```

---

## Tarefa 8: Extensão de `/orientacoes/` e nav da SUGRAD

**Arquivos:**
- Modificar: `templates/projetos/orientacoes.html`, `templates/base.html`.
- Teste: `apps/projetos/tests/test_orientacoes_bancas.py` (extensão) ou novo
  `apps/projetos/tests/test_orientacoes_atas.py`.

**Interfaces:**
- Consome: `projeto.status`, `Ata`/`RevisaoSUGRAD` via `projeto.atas`
  (`related_name` de `Ata.projeto`).

- [ ] **Passo 1: Escrever os testes (falhando)**

Crie `apps/projetos/tests/test_orientacoes_atas.py`:

```python
"""Testes de `/orientacoes/` mostrando as ações do Bloco E: Aprovar
(Aprovado com Ressalvas), comentário+Reenviar (Aprovado, ata devolvida)."""

import pytest
from django.utils import timezone

from apps.bancas.models import Banca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.documentos import services as documentos_services
from apps.projetos.models import Projeto


def _cpf(indice):
    base = f"{760000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.orientacoesatas.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=_cpf(indice),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"ORIA{indice:03d}")


def _aluno(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"aluno.orientacoesatas.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        papel=Usuario.ALUNO,
        cpf=_cpf(indice),
    )
    PerfilAluno.objects.create(usuario=usuario, matricula=f"2026ORIA{indice:03d}")
    return usuario


@pytest.mark.django_db
def test_orientacoes_mostra_aprovar_para_aprovado_com_ressalvas(client):
    orientador = _professor(1, "Orientador Aprovar Link")
    aluno = _aluno(2, "Aluno Aprovar Link")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.APROVADO_COM_RESSALVAS,
        ano=2026,
        periodo=1,
    )
    client.force_login(orientador.usuario)
    conteudo = client.get("/orientacoes/").content.decode()
    assert f"/orientacoes/{projeto.pk}/aprovar/" in conteudo


@pytest.mark.django_db
def test_orientacoes_mostra_reenviar_para_ata_devolvida(client):
    orientador = _professor(3, "Orientador Devolvida Link")
    aluno = _aluno(4, "Aluno Devolvida Link")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.APROVADO,
        ano=2026,
        periodo=1,
    )
    Banca.objects.create(
        projeto=projeto,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.REALIZADA,
        nota=8.0,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
    )
    ata = documentos_services.gerar_ata(projeto)
    sugrad = Usuario.objects.create_user(
        email="sugrad.orientacoesatas@ufsm.br",
        password="x",
        nome_completo="SUGRAD",
        papel=Usuario.SUGRAD,
        cpf=None,
    )
    documentos_services.devolver_ata(ata, por=sugrad, comentario="Falta a assinatura.")

    client.force_login(orientador.usuario)
    conteudo = client.get("/orientacoes/").content.decode()
    assert "Falta a assinatura." in conteudo
    assert f"/orientacoes/{ata.pk}/reenviar-sugrad/" in conteudo


@pytest.mark.django_db
def test_base_mostra_link_painel_sugrad_so_para_sugrad(client):
    sugrad = Usuario.objects.create_user(
        email="sugrad.navlink@ufsm.br",
        password="x",
        nome_completo="SUGRAD",
        papel=Usuario.SUGRAD,
        cpf=None,
    )
    client.force_login(sugrad)
    conteudo = client.get("/").content.decode()
    assert 'href="/painel/sugrad/"' in conteudo


@pytest.mark.django_db
def test_base_esconde_link_painel_sugrad_para_professor(client):
    professor = _professor(5, "Professor Sem SUGRAD Link")
    client.force_login(professor.usuario)
    conteudo = client.get("/").content.decode()
    assert 'href="/painel/sugrad/"' not in conteudo
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `docker compose exec web pytest apps/projetos/tests/test_orientacoes_atas.py -v`
Expected: falhas — nenhum ramo novo existe ainda em `orientacoes.html`/`base.html`.

- [ ] **Passo 3: Estender `templates/projetos/orientacoes.html`**

Dentro do `{% if projeto.banca_ativa.status == "AGENDADA" %}...{% elif
projeto.banca_ativa %}...{% elif not projeto.submissao %}...{% else %}...
{% endif %}` (Bloco D, Tarefa 9), acrescente MAIS DOIS ramos ANTES do
`{% elif projeto.banca_ativa %}` que trata `REPROVADO` — a ordem importa
porque `projeto.banca_ativa` também é truthy para bancas `REALIZADA` de
projetos `APROVADO_COM_RESSALVAS`/`APROVADO`, não só `REPROVADO`:

```html
              {% if projeto.banca_ativa.status == "AGENDADA" %}
                ...(inalterado, Bloco D)...
              {% elif projeto.status == "APROVADO_COM_RESSALVAS" %}
                <form method="post" action="{% url 'projetos:aprovar_projeto' projeto.pk %}">
                  {% csrf_token %}
                  <button type="submit" class="btn btn-primary btn-sm">Aprovar</button>
                </form>
              {% elif projeto.status == "APROVADO" and projeto.ata_ativa.revisao.status == "DEVOLVIDA" %}
                <p class="mt-1 text-sm">
                  A SUGRAD devolveu a ata: {{ projeto.ata_ativa.revisao.comentario }}
                </p>
                <form method="post" action="{% url 'projetos:reenviar_ata' projeto.ata_ativa.pk %}">
                  {% csrf_token %}
                  <button type="submit" class="btn btn-outline btn-sm">Reenviar à SUGRAD</button>
                </form>
              {% elif projeto.status == "APROVADO" %}
                <p class="mt-1 text-sm text-base-content/70">Aguardando revisão da SUGRAD.</p>
              {% elif projeto.banca_ativa %}
                ...(inalterado, Bloco D — ramo do REPROVADO)...
              {% elif not projeto.submissao %}
                ...(inalterado, Bloco D)...
              {% else %}
                ...(inalterado, Bloco D)...
              {% endif %}
```

Isto introduz `projeto.ata_ativa` — um atributo novo, decorado no `Projeto`
pela view, do mesmo jeito que `projeto.banca_ativa` foi decorado no Bloco D
(`anexar_banca_ativa`). Ver Passo 4.

**Comparação por string literal de `projeto.status`, não um campo mais
específico:** ao contrário do ramo `AGENDADA`/`elif banca_ativa` (que usa
`banca_ativa.status` como proxy), aqui não existe proxy melhor —
`APROVADO_COM_RESSALVAS` e `APROVADO` não têm um objeto associado cuja
presença os distinga (a `Ata` só existe depois de `APROVADO`). Comparar
`projeto.status` direto é a opção certa aqui, mesmo padrão de
`opcao.situacao == "RECUSADA"` quando não há campo mais específico
disponível.

- [ ] **Passo 4: Decorar `projeto.ata_ativa` na view `orientacoes`**

Em `apps/projetos/views.py`, na view `orientacoes` (que já chama
`anexar_banca_ativa(orientandos)`, Bloco D Tarefa 9), acrescente logo depois:

```python
    for projeto in orientandos:
        projeto.ata_ativa = projeto.atas.select_related("revisao").order_by("-gerada_em").first()
```

(`Ata.objects` não precisa de import aqui — `projeto.atas` é o
`related_name` de `Ata.projeto`, Tarefa 1. Sem `Prefetch`/mapa em lote como
`anexar_banca_ativa`: cada orientando tem no máximo uma ata relevante — a
mais recente —, e o volume de "orientandos atuais" de um professor é pequeno
o bastante (teto de 3 vagas por etapa, CLAUDE.md regra 1) para não valer a
complexidade extra de uma segunda função de lote nesta tarefa. **Lacuna
registrada, não decidida aqui:** se este N+1 um dia importar, refatore para o
mesmo padrão de `anexar_banca_ativa`.)

- [ ] **Passo 5: Acrescentar o link condicional em `templates/base.html`**

No bloco `navegacao`, dentro do `{% if user.is_authenticated %}`, acrescente
um novo `<li>` condicionado ao papel SUGRAD — sem `hasattr`/perfil (papel é
um campo direto de `Usuario`, sem `RelatedObjectDoesNotExist` a evitar, mesmo
raciocínio de `user.is_coordenador`):

```html
              {% if user.papel == "SUGRAD" %}
                <li>
                  <a href="{% url 'documentos:painel' %}" class="btn btn-ghost">
                    Painel SUGRAD
                  </a>
                </li>
              {% endif %}
```

- [ ] **Passo 6: Rodar e confirmar que os testes passam**

Run: `docker compose exec web pytest apps/projetos/tests/test_orientacoes_atas.py -v`
Expected: todos `PASSED`.

- [ ] **Passo 7: Rodar a suíte de `apps/projetos` inteira e `tests/test_navegacao.py`**

Run: `docker compose exec web pytest apps/projetos/ tests/test_navegacao.py -v`
Expected: todos `PASSED` — nenhuma regressão em `test_fila_professor.py`,
`test_orientacoes_bancas.py` (Bloco D) nem nos quatro testes de persona de
`test_navegacao.py` (nenhum deles é `papel=SUGRAD`, então nenhum precisa de
asserção nova — a SUGRAD não tem teste de persona próprio ali; os dois
testes novos do Passo 1 já cobrem a visibilidade do link).

- [ ] **Passo 8: `ruff` e `black`, depois commit**

```bash
docker compose exec web ruff check .
docker compose exec web black .
git add templates/projetos/orientacoes.html templates/base.html \
        apps/projetos/views.py apps/projetos/tests/test_orientacoes_atas.py
git commit -m "Tarefa 8: /orientacoes/ ganha as acoes do Bloco E e o link do painel SUGRAD"
```

---

## Tarefa 9: Rotas transversais e suíte de acessibilidade completa

**Arquivos:**
- Modificar: `conftest.py`.

**Interfaces:**
- Consome: `/painel/sugrad/` (Tarefa 7).

- [ ] **Passo 1: Acrescentar a fábrica de `/painel/sugrad/`**

Perto de `cria_professor_com_banca_agendada_para_rotas` (Bloco D), acrescente:

```python
def cria_sugrad_com_ata_pendente_para_rotas():
    """Fábrica de `/painel/sugrad/` (Bloco E): conta SUGRAD com uma `Ata`
    `PENDENTE` já gerada, para a lista do painel não ficar vazia na
    medição."""
    from apps.bancas.services import agendar_banca, registrar_resultado
    from apps.comum.semestre import semestre_vigente
    from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
    from apps.projetos.models import Projeto, Submissao

    sugrad = Usuario.objects.create_user(
        email="sugrad-das-rotas@ufsm.br",
        password="x",
        nome_completo="SUGRAD das Rotas",
        papel=Usuario.SUGRAD,
        cpf=None,
    )

    orientador = Usuario.objects.create_user(
        email="orientador-ata-das-rotas@ufsm.br",
        password="x",
        nome_completo="Orientador Ata das Rotas",
        cpf=_gera_cpf_das_rotas(33),
    )
    PerfilProfessor.objects.create(usuario=orientador, siape="1000022")

    aluno = Usuario.objects.create_user(
        email="aluno-ata-das-rotas@ufsm.br",
        password="x",
        nome_completo="Aluno Ata das Rotas",
        cpf=_gera_cpf_das_rotas(34),
        papel=Usuario.ALUNO,
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026399921")

    ano, periodo = semestre_vigente()
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=ano,
        periodo=periodo,
    )
    Submissao.objects.create(
        projeto=projeto, pdf="submissoes/rota-ata.pdf", editavel="submissoes/rota-ata.docx"
    )

    membro1 = Usuario.objects.create_user(
        email="membro1-ata-das-rotas@ufsm.br",
        password="x",
        nome_completo="Membro Um Ata das Rotas",
        cpf=_gera_cpf_das_rotas(35),
    )
    perfil_membro1 = PerfilProfessor.objects.create(usuario=membro1, siape="1000023")
    membro2 = Usuario.objects.create_user(
        email="membro2-ata-das-rotas@ufsm.br",
        password="x",
        nome_completo="Membro Dois Ata das Rotas",
        cpf=_gera_cpf_das_rotas(36),
    )
    perfil_membro2 = PerfilProfessor.objects.create(usuario=membro2, siape="1000024")

    banca = agendar_banca(
        projeto,
        data_hora=timezone.now(),
        local="Sala das Rotas",
        membros=[{"professor": perfil_membro1}, {"professor": perfil_membro2}],
        por=orientador,
    )
    registrar_resultado(
        banca,
        nota=8.5,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
        comentario="Boa apresentação.",
        por=orientador,
    )

    from apps.projetos.services import aprovar_projeto

    aprovar_projeto(projeto, por=orientador)

    return sugrad
```

- [ ] **Passo 2: Acrescentar a `Rota` a `ROTAS`**

```python
    Rota(
        "/painel/sugrad/",
        "form",
        fabrica_usuario=cria_sugrad_com_ata_pendente_para_rotas,
        h1="Painel SUGRAD",
    ),
```

(`"form"` como seletor de âncora, mesmo critério das outras telas com
formulário — `/painel/sugrad/` tem o formulário de devolução; confirme, ao
rodar o Passo 3, que o `<h1>` "Painel SUGRAD" bate — se a suíte reprovar por
âncora, é sinal de que o `h1` do template ficou diferente do texto aqui.)

- [ ] **Passo 3: Rodar as cinco suítes transversais completas**

`orientacoes.html`/`base.html` também mudaram (Tarefa 8) — roda tudo, não
filtrado:

Run: `docker compose exec web pytest tests/test_acessibilidade.py tests/test_toque.py tests/test_responsivo.py tests/test_teclado.py tests/test_rotas.py -v`
Expected: todos `PASSED`. Se `color-contrast` ou alvo de toque reprovarem em
algum elemento novo, ajuste a classe DaisyUI do elemento (mesmo tipo de
correção do Bloco C, Tarefa 4) e rode de novo até passar.

- [ ] **Passo 4: Rodar a suíte inteira**

Run: `docker compose exec web pytest`
Expected: todos `PASSED`.

- [ ] **Passo 5: `ruff` e `black`**

Run: `docker compose exec web ruff check .`
Run: `docker compose exec web black --check .`

- [ ] **Passo 6: Commit**

```bash
git add conftest.py
git commit -m "Tarefa 9: rotas transversais das telas do Bloco E"
```

---

## Ao concluir

Depois da Tarefa 9, verifique os 9 critérios de aceitação do spec (§11) um a
um, com evidência real — mesmo formato dos Blocos C e D. Atualize
`CLAUDE.md`: marque o Bloco E como concluído (mesmo formato das entradas
anteriores), ajuste a seção "Ciclo de Vida e Status do TCC" removendo "Ainda
não implementado (Bloco E)" do item `Concluído`, e a descrição de
`apps/documentos`/`apps/projetos` na "Estrutura de Apps" para mencionar
`Ata`/`RevisaoSUGRAD` e `aprovar_projeto`. Depois, invoque
`superpowers:finishing-a-development-branch` para a branch deste bloco.
