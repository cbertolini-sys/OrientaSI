# Bancas e Avaliação (Bloco D) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Criar o app `apps/bancas` (agendamento de banca, resultado da apresentação)
e fechar o ciclo de vida de `Projeto` a partir de `AGUARDANDO_DEFESA` até
`Aprovado com Ressalvas`/`Reprovado`, incluindo os dois caminhos que se abrem a
partir de `Reprovado`.

**Architecture:** Novo app `apps/bancas` com o padrão já estabelecido
(`models.py`/`services.py`/`permissions.py`/`forms.py`/`views.py`/`urls.py`/
`tasks.py`, mais `tests/`). Duas pequenas extensões em `apps/projetos`
(`Projeto.STATUS` ganha `CANCELADO`; `services.py` ganha `reabrir_projeto`/
`cancelar_projeto`; `orientandos_atuais` amplia o filtro de status). A tela
`/orientacoes/` (Bloco B/C) é o único ponto de entrada visível — nenhum link novo
em `base.html`.

**Tech Stack:** Django 5, PostgreSQL, Celery (notificação de agendamento),
pytest-django, Playwright + axe-core.

**Spec:** `docs/superpowers/specs/2026-09-14-bancas-e-avaliacao-design.md`

## Global Constraints

- Todo identificador de código é em português; interface, mensagens e commits também.
- Regra de negócio nunca em `views.py`/`models.py` — só em `services.py` de cada
  app (CLAUDE.md, regra 4).
- Permissão é sempre por POSSE (`usuario == projeto.orientador`), nunca por
  papel — mesmo padrão de `pode_editar_tema`/`pode_enviar_submissao`.
- Lookup de view sempre ESCOPADO ao dono
  (`get_object_or_404(Modelo, pk=..., campo_de_posse=request.user)`): dono
  alheio e pk inexistente respondem os DOIS com 404, nunca 403 pós-lookup —
  mesmo padrão de `editar_tema`/`desativar_tema` (Bloco B) e `meu_tcc` (Bloco C).
- **Disciplina de testes (CLAUDE.md):** toda checagem nova provada por mutação
  (comente a checagem, confirme que algum teste reprova, desfaça); uma checagem
  vizinha pode mascarar a ausência da nova — nunca inferir cobertura pela suíte
  passando; toda citação de arquivo:linha conferida no momento em que é escrita.
- Toda tela nova entra em `conftest.py::ROTAS` (nunca numa suíte de
  acessibilidade isolada) para receber as cinco checagens transversais (axe ×2
  larguras, toque ×2, responsivo, teclado, rotas).
- `docker compose exec web pytest` / `ruff check .` / `black --check .` depois
  de cada tarefa.

---

## Mapa de arquivos

- **Criar** `apps/bancas/models.py` — `Banca`, `MembroBanca`.
- **Criar** `apps/bancas/migrations/0001_initial.py`.
- **Criar** `apps/bancas/admin.py`.
- **Criar** `apps/bancas/permissions.py`.
- **Criar** `apps/bancas/services.py` — `agendar_banca`, `editar_banca`,
  `cancelar_banca`, `registrar_resultado`, `anexar_banca_ativa`.
- **Criar** `apps/bancas/tasks.py` — `enviar_agendamento_banca`.
- **Criar** `apps/bancas/forms.py` — `FormularioBanca`, `FormularioResultadoBanca`.
- **Criar** `apps/bancas/views.py` — `agendar`, `editar`, `cancelar`, `resultado`.
- **Criar** `apps/bancas/urls.py`.
- **Criar** `templates/bancas/formulario.html`, `templates/bancas/resultado.html`.
- **Criar** `templates/email/banca_agendada_aluno.txt`,
  `templates/email/banca_agendada_professor.txt`.
- **Criar** `apps/bancas/tests/{__init__.py,test_modelos.py,test_agendar.py,
  test_editar_cancelar.py,test_resultado.py,test_notificacoes.py,
  test_formularios.py,test_telas.py}`.
- **Modificar** `apps/projetos/models.py` — `Projeto.STATUS` ganha `CANCELADO`;
  `constraints` de `Projeto.Meta` passa a excluir também `CANCELADO`.
- **Modificar** `apps/projetos/services.py` — `orientandos_atuais` (filtro),
  `reabrir_projeto`, `cancelar_projeto`.
- **Modificar** `apps/projetos/permissions.py` — `pode_reabrir_projeto`,
  `pode_cancelar_projeto`.
- **Modificar** `apps/projetos/views.py` — `orientacoes` (chama
  `anexar_banca_ativa`), `reabrir_projeto_view`, `cancelar_projeto_view`.
- **Modificar** `apps/projetos/urls.py` — duas rotas novas.
- **Modificar** `templates/projetos/orientacoes.html` — ações por estado.
- **Modificar** `config/urls.py` — `include("apps.bancas.urls")`.
- **Modificar** `conftest.py` — `ROTAS` (três telas novas de `apps/bancas`).
- **Modificar** `apps/projetos/tests/test_fila_professor.py` — asserts de
  `orientandos_atuais` cobrindo os novos status.

---

## Tarefa 1: Modelos `Banca`/`MembroBanca` e `Projeto.CANCELADO`

**Arquivos:**
- Criar: `apps/bancas/models.py`, `apps/bancas/migrations/0001_initial.py`,
  `apps/bancas/admin.py`.
- Modificar: `apps/projetos/models.py`.
- Teste: `apps/bancas/tests/test_modelos.py`.

**Interfaces:**
- Produz: `Banca` (`projeto`, `data_hora`, `local`, `status`, `nota`,
  `resultado`, `comentario`), `MembroBanca` (`banca`, `professor`,
  `nome_externo`); `Projeto.CANCELADO`.

- [ ] **Passo 1: Escrever os testes de modelo (falhando)**

Crie `apps/bancas/tests/__init__.py` vazio, e `apps/bancas/tests/test_modelos.py`:

```python
"""Testes de modelo do Bloco D (spec §4): as duas constraints de banco —
`banca_ativa_unica_por_projeto` e `membro_banca_interno_xor_externo` — e o
novo status `CANCELADO` de `Projeto`."""

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.bancas.models import Banca, MembroBanca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto


def _cpf(indice):
    """CPF sintético com dígitos verificadores válidos, faixa 600000000+ —
    livre (conferida por grep) para os testes de `apps/bancas/`."""
    base = f"{600000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


@pytest.fixture
def projeto_aguardando_defesa(db):
    aluno = Usuario.objects.create_user(
        email="aluno.banca.modelo@ufsm.br",
        password="x",
        nome_completo="Aluno Banca Modelo",
        papel=Usuario.ALUNO,
        cpf=_cpf(1),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026BANCA01")
    professor = Usuario.objects.create_user(
        email="professor.banca.modelo@ufsm.br",
        password="x",
        nome_completo="Professor Banca Modelo",
        cpf=_cpf(2),
    )
    PerfilProfessor.objects.create(usuario=professor, siape="BANCA001")
    return Projeto.objects.create(
        aluno=aluno,
        orientador=professor,
        etapa=Projeto.TCC_I,
        status=Projeto.AGUARDANDO_DEFESA,
        ano=2026,
        periodo=1,
    )


@pytest.mark.django_db
def test_banca_ativa_unica_por_projeto_recusa_duas_agendadas(projeto_aguardando_defesa):
    Banca.objects.create(
        projeto=projeto_aguardando_defesa,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.AGENDADA,
    )
    with pytest.raises(IntegrityError):
        Banca.objects.create(
            projeto=projeto_aguardando_defesa,
            data_hora=timezone.now(),
            local="Sala 2",
            status=Banca.AGENDADA,
        )


@pytest.mark.django_db
def test_banca_ativa_unica_por_projeto_permite_cancelada_mais_agendada(
    projeto_aguardando_defesa,
):
    Banca.objects.create(
        projeto=projeto_aguardando_defesa,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.CANCELADA,
    )
    # Não levanta: a cancelada não conta para a restrição.
    nova = Banca.objects.create(
        projeto=projeto_aguardando_defesa,
        data_hora=timezone.now(),
        local="Sala 2",
        status=Banca.AGENDADA,
    )
    assert nova.pk is not None


@pytest.mark.django_db
def test_membro_banca_recusa_professor_e_externo_juntos(projeto_aguardando_defesa):
    banca = Banca.objects.create(
        projeto=projeto_aguardando_defesa,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.AGENDADA,
    )
    professor = PerfilProfessor.objects.first()
    with pytest.raises(IntegrityError):
        MembroBanca.objects.create(banca=banca, professor=professor, nome_externo="Fulano")


@pytest.mark.django_db
def test_membro_banca_recusa_nenhum_dos_dois(projeto_aguardando_defesa):
    banca = Banca.objects.create(
        projeto=projeto_aguardando_defesa,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.AGENDADA,
    )
    with pytest.raises(IntegrityError):
        MembroBanca.objects.create(banca=banca)


@pytest.mark.django_db
def test_membro_banca_aceita_so_externo(projeto_aguardando_defesa):
    banca = Banca.objects.create(
        projeto=projeto_aguardando_defesa,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.AGENDADA,
    )
    membro = MembroBanca.objects.create(banca=banca, nome_externo="Fulano de Tal")
    assert membro.professor is None


def test_projeto_tem_status_cancelado():
    assert Projeto.CANCELADO == "CANCELADO"
    assert ("CANCELADO", "Cancelado") in Projeto.STATUS
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `docker compose exec web pytest apps/bancas/tests/test_modelos.py -v`
Expected: `ModuleNotFoundError: No module named 'apps.bancas.models'` (ou
`ImportError`) — o app não tem `models.py` ainda.

- [ ] **Passo 3: Escrever `apps/bancas/models.py`**

```python
from django.db import models

from apps.contas.models import PerfilProfessor
from apps.projetos.models import Projeto


class Banca(models.Model):
    """Agendamento e resultado da apresentação de um `Projeto` (Bloco D,
    spec §4.2). `projeto` é `ForeignKey`, não `OneToOneField` — cancelar não
    apaga o registro (fica `CANCELADA`, histórico), e uma banca cancelada
    não impede uma banca nova para o mesmo projeto depois (§3.4 do spec).
    A restrição abaixo garante no máximo UMA banca NÃO CANCELADA por
    projeto ao mesmo tempo.
    """

    AGENDADA = "AGENDADA"
    REALIZADA = "REALIZADA"
    CANCELADA = "CANCELADA"
    STATUS = [
        (AGENDADA, "Agendada"),
        (REALIZADA, "Realizada"),
        (CANCELADA, "Cancelada"),
    ]

    projeto = models.ForeignKey(
        Projeto,
        on_delete=models.PROTECT,
        related_name="bancas",
        verbose_name="projeto",
    )
    data_hora = models.DateTimeField("data e hora")
    local = models.CharField("local", max_length=200)
    status = models.CharField("status", max_length=9, choices=STATUS, default=AGENDADA)
    # Uma nota e um resultado só, não um por membro (spec §3.2): decidido
    # coletivamente na apresentação, digitado pelo orientador. `resultado`
    # usa as MESMAS strings de `Projeto.APROVADO_COM_RESSALVAS`/
    # `Projeto.REPROVADO` — `registrar_resultado` grava
    # `projeto.status = banca.resultado` sem nenhuma tradução no meio.
    nota = models.DecimalField(
        "nota", max_digits=3, decimal_places=1, null=True, blank=True
    )
    resultado = models.CharField(
        "resultado",
        max_length=22,
        choices=[
            (Projeto.APROVADO_COM_RESSALVAS, "Aprovado com ressalvas"),
            (Projeto.REPROVADO, "Reprovado"),
        ],
        blank=True,
        default="",
    )
    comentario = models.TextField("comentário", blank=True, default="")
    criada_em = models.DateTimeField("criada em", auto_now_add=True)

    class Meta:
        verbose_name = "banca"
        verbose_name_plural = "bancas"
        ordering = ["-criada_em"]
        constraints = [
            models.UniqueConstraint(
                fields=["projeto"],
                condition=~models.Q(status="CANCELADA"),
                name="banca_ativa_unica_por_projeto",
            ),
        ]

    def __str__(self):
        return f"Banca de {self.projeto} — {self.get_status_display()}"


class MembroBanca(models.Model):
    """Um dos DOIS avaliadores adicionais de uma `Banca` — o orientador
    participa implicitamente, sem uma linha aqui (spec §3.1). Interno
    (`professor`, com conta no sistema) OU externo (`nome_externo`, só o
    nome — regra 3 do CLAUDE.md: sem FK, sem CPF, sem e-mail), nunca os
    dois, nunca nenhum — `CheckConstraint` abaixo.
    """

    banca = models.ForeignKey(
        Banca,
        # CASCADE, ao contrário de Banca.projeto (PROTECT): um MembroBanca
        # só existe em função da Banca que o contém — apagar a banca não
        # deixa membros órfãos para trás.
        on_delete=models.CASCADE,
        related_name="membros",
        verbose_name="banca",
    )
    professor = models.ForeignKey(
        PerfilProfessor,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="participacoes_em_banca",
        verbose_name="professor",
    )
    nome_externo = models.CharField(
        "nome (externo)", max_length=200, null=True, blank=True
    )

    class Meta:
        verbose_name = "membro da banca"
        verbose_name_plural = "membros da banca"
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(professor__isnull=False, nome_externo__isnull=True)
                    | models.Q(professor__isnull=True, nome_externo__isnull=False)
                ),
                name="membro_banca_interno_xor_externo",
            ),
        ]

    def __str__(self):
        if self.professor:
            return self.professor.usuario.nome_completo
        return f"{self.nome_externo} (externo)"
```

- [ ] **Passo 4: Acrescentar `CANCELADO` a `Projeto` e atualizar a constraint**

Em `apps/projetos/models.py`, na classe `Projeto`:

```python
    EM_ANDAMENTO = "EM_ANDAMENTO"
    AGUARDANDO_DEFESA = "AGUARDANDO_DEFESA"
    APROVADO_COM_RESSALVAS = "APROVADO_COM_RESSALVAS"
    APROVADO = "APROVADO"
    CONCLUIDO = "CONCLUIDO"
    REPROVADO = "REPROVADO"
    CANCELADO = "CANCELADO"
    STATUS = [
        (EM_ANDAMENTO, "Em andamento"),
        (AGUARDANDO_DEFESA, "Aguardando defesa"),
        (APROVADO_COM_RESSALVAS, "Aprovado com ressalvas"),
        (APROVADO, "Aprovado"),
        (CONCLUIDO, "Concluído"),
        (REPROVADO, "Reprovado"),
        (CANCELADO, "Cancelado"),
    ]
```

E na `Meta.constraints` (mesma classe), a condição da
`projeto_ativo_unico_por_aluno_e_etapa` passa a excluir `CANCELADO` também —
sem isto, um projeto cancelado (Bloco D) bloquearia para sempre uma nova
candidatura do mesmo aluno na mesma etapa, o mesmo defeito que a exclusão de
`CONCLUIDO`/`REPROVADO` já existe para evitar:

```python
            models.UniqueConstraint(
                fields=["aluno", "etapa"],
                condition=~Q(status__in=["CONCLUIDO", "REPROVADO", "CANCELADO"]),
                name="projeto_ativo_unico_por_aluno_e_etapa",
            ),
```

- [ ] **Passo 5: Criar `apps/bancas/admin.py`**

```python
from django.contrib import admin

from apps.bancas.models import Banca, MembroBanca


class MembroBancaInline(admin.TabularInline):
    model = MembroBanca
    extra = 0


@admin.register(Banca)
class BancaAdmin(admin.ModelAdmin):
    list_display = ["projeto", "data_hora", "local", "status", "resultado", "criada_em"]
    list_filter = ["status", "resultado"]
    search_fields = ["projeto__aluno__nome_completo", "local"]
    readonly_fields = ["criada_em"]
    inlines = [MembroBancaInline]
```

- [ ] **Passo 6: Gerar e aplicar as migrações**

Run: `docker compose exec web python manage.py makemigrations bancas projetos`
Expected: cria `apps/bancas/migrations/0001_initial.py` e uma migração nova em
`apps/projetos/migrations/` (ex.: `0004_...`) alterando `Projeto.status` e a
constraint.

Run: `docker compose exec web python manage.py migrate`
Expected: aplica as duas sem erro.

- [ ] **Passo 7: Rodar os testes e confirmar que passam**

Run: `docker compose exec web pytest apps/bancas/tests/test_modelos.py -v`
Expected: todos `PASSED`.

- [ ] **Passo 8: `ruff` e `black`**

Run: `docker compose exec web ruff check .`
Run: `docker compose exec web black .`

- [ ] **Passo 9: Commit**

```bash
git add apps/bancas/models.py apps/bancas/admin.py apps/bancas/migrations/ \
        apps/bancas/tests/__init__.py apps/bancas/tests/test_modelos.py \
        apps/projetos/models.py apps/projetos/migrations/
git commit -m "Tarefa 1: modelos Banca/MembroBanca e Projeto.CANCELADO"
```

---

## Tarefa 2: `agendar_banca`

**Arquivos:**
- Criar: `apps/bancas/permissions.py`, `apps/bancas/services.py`.
- Teste: `apps/bancas/tests/test_agendar.py`.

**Interfaces:**
- Consome: `Banca`, `MembroBanca` (Tarefa 1); `Projeto.EM_ANDAMENTO`,
  `Projeto.AGUARDANDO_DEFESA`, `Projeto.submissao` (Bloco C).
- Produz: `permissions.pode_agendar_banca(usuario, projeto) -> bool`;
  `services.agendar_banca(projeto, data_hora, local, membros, por) -> Banca`,
  onde `membros` é uma lista de exatamente 2 dicts, cada um
  `{"professor": PerfilProfessor}` ou `{"nome_externo": str}`.

- [ ] **Passo 1: Escrever os testes (falhando)**

Crie `apps/bancas/tests/test_agendar.py`:

```python
"""Testes de `services.agendar_banca` (Bloco D, spec §5.1)."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.bancas import permissions, services
from apps.bancas.models import Banca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto, Submissao


def _cpf(indice):
    base = f"{610000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.agendar.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=_cpf(indice),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"AGENDAR{indice:03d}")


@pytest.fixture
def orientador(db):
    return _professor(1, "Orientador Agendar")


@pytest.fixture
def dois_professores(db):
    return [_professor(2, "Membro Um"), _professor(3, "Membro Dois")]


@pytest.fixture
def projeto_com_submissao(db, orientador):
    aluno = Usuario.objects.create_user(
        email="aluno.agendar@ufsm.br",
        password="x",
        nome_completo="Aluno Agendar",
        papel=Usuario.ALUNO,
        cpf=_cpf(4),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026AGENDAR1")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=2026,
        periodo=1,
    )
    Submissao.objects.create(
        projeto=projeto, pdf="submissoes/v1.pdf", editavel="submissoes/v1.docx"
    )
    return projeto


@pytest.mark.django_db
def test_pode_agendar_banca_e_o_orientador(projeto_com_submissao, orientador):
    assert permissions.pode_agendar_banca(orientador.usuario, projeto_com_submissao)


@pytest.mark.django_db
def test_pode_agendar_banca_recusa_quem_nao_e_o_orientador(projeto_com_submissao):
    outro = Usuario.objects.create_user(
        email="outro.agendar@ufsm.br", password="x", nome_completo="Outro", cpf=_cpf(5)
    )
    assert not permissions.pode_agendar_banca(outro, projeto_com_submissao)


@pytest.mark.django_db
def test_agendar_banca_cria_banca_e_dois_membros(
    projeto_com_submissao, orientador, dois_professores
):
    banca = services.agendar_banca(
        projeto_com_submissao,
        data_hora=timezone.now() + timezone.timedelta(days=7),
        local="Sala 12",
        membros=[{"professor": dois_professores[0]}, {"nome_externo": "Fulano Externo"}],
        por=orientador.usuario,
    )
    assert banca.status == Banca.AGENDADA
    assert banca.membros.count() == 2
    projeto_com_submissao.refresh_from_db()
    assert projeto_com_submissao.status == Projeto.AGUARDANDO_DEFESA


@pytest.mark.django_db
def test_agendar_banca_recusa_quem_nao_e_o_orientador(projeto_com_submissao, dois_professores):
    outro = Usuario.objects.create_user(
        email="outro.agendar2@ufsm.br", password="x", nome_completo="Outro Dois", cpf=_cpf(6)
    )
    with pytest.raises(PermissionDenied):
        services.agendar_banca(
            projeto_com_submissao,
            data_hora=timezone.now(),
            local="Sala 12",
            membros=[{"professor": dois_professores[0]}, {"professor": dois_professores[1]}],
            por=outro,
        )


@pytest.mark.django_db
def test_agendar_banca_recusa_sem_submissao(orientador, dois_professores):
    aluno = Usuario.objects.create_user(
        email="aluno.semsubmissao@ufsm.br",
        password="x",
        nome_completo="Aluno Sem Submissão",
        papel=Usuario.ALUNO,
        cpf=_cpf(7),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026SEMSUB01")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=2026,
        periodo=1,
    )
    with pytest.raises(ValidationError):
        services.agendar_banca(
            projeto,
            data_hora=timezone.now(),
            local="Sala 12",
            membros=[{"professor": dois_professores[0]}, {"professor": dois_professores[1]}],
            por=orientador.usuario,
        )


@pytest.mark.django_db
def test_agendar_banca_recusa_fora_de_em_andamento(projeto_com_submissao, orientador, dois_professores):
    projeto_com_submissao.status = Projeto.AGUARDANDO_DEFESA
    projeto_com_submissao.save()
    with pytest.raises(ValidationError):
        services.agendar_banca(
            projeto_com_submissao,
            data_hora=timezone.now(),
            local="Sala 12",
            membros=[{"professor": dois_professores[0]}, {"professor": dois_professores[1]}],
            por=orientador.usuario,
        )


@pytest.mark.django_db
def test_agendar_banca_recusa_orientador_como_membro(
    projeto_com_submissao, orientador, dois_professores
):
    with pytest.raises(ValidationError):
        services.agendar_banca(
            projeto_com_submissao,
            data_hora=timezone.now(),
            local="Sala 12",
            membros=[{"professor": orientador}, {"professor": dois_professores[0]}],
            por=orientador.usuario,
        )


@pytest.mark.django_db
def test_agendar_banca_recusa_professor_repetido(
    projeto_com_submissao, orientador, dois_professores
):
    with pytest.raises(ValidationError):
        services.agendar_banca(
            projeto_com_submissao,
            data_hora=timezone.now(),
            local="Sala 12",
            membros=[{"professor": dois_professores[0]}, {"professor": dois_professores[0]}],
            por=orientador.usuario,
        )


@pytest.mark.django_db
def test_agendar_banca_recusa_numero_errado_de_membros(
    projeto_com_submissao, orientador, dois_professores
):
    with pytest.raises(ValidationError):
        services.agendar_banca(
            projeto_com_submissao,
            data_hora=timezone.now(),
            local="Sala 12",
            membros=[{"professor": dois_professores[0]}],
            por=orientador.usuario,
        )
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `docker compose exec web pytest apps/bancas/tests/test_agendar.py -v`
Expected: `ModuleNotFoundError` — `apps.bancas.services`/`permissions` não existem.

- [ ] **Passo 3: Escrever `apps/bancas/permissions.py`**

```python
def pode_agendar_banca(usuario, projeto):
    """`usuario` é exatamente o orientador de `projeto` — posse, não papel
    (Bloco D, spec §6). A view escopa o lookup do `Projeto` ao orientador
    autenticado; esta função é defesa em profundidade para quem chamar o
    serviço sem passar por lá."""
    return bool(usuario and usuario.is_authenticated and usuario == projeto.orientador)


def pode_editar_banca(usuario, banca):
    """Mesma regra de posse de `pode_agendar_banca`, sobre o projeto DONO
    da banca."""
    return bool(usuario and usuario.is_authenticated and usuario == banca.projeto.orientador)


def pode_cancelar_banca(usuario, banca):
    """Mesma regra de posse de `pode_editar_banca`."""
    return bool(usuario and usuario.is_authenticated and usuario == banca.projeto.orientador)


def pode_registrar_resultado_banca(usuario, banca):
    """Mesma regra de posse de `pode_editar_banca`."""
    return bool(usuario and usuario.is_authenticated and usuario == banca.projeto.orientador)
```

- [ ] **Passo 4: Escrever `apps/bancas/services.py` com `agendar_banca`**

```python
from django.core.exceptions import PermissionDenied, ValidationError

from apps.bancas import permissions
from apps.bancas.models import Banca, MembroBanca
from apps.projetos.models import Projeto


def _valida_membros(membros, orientador):
    """Compartilhada por `agendar_banca`/`editar_banca` (Tarefa 3): exatamente
    2 `membros`, nenhum sendo o próprio `orientador` (um `Usuario`), nenhum
    `professor` repetido entre os dois. Levanta `ValidationError` com
    mensagem específica para cada caso — não um `assert` genérico."""
    if len(membros) != 2:
        raise ValidationError("A banca precisa de exatamente dois membros, além do orientador.")

    professores = [m["professor"] for m in membros if "professor" in m]
    for professor in professores:
        if professor.usuario_id == orientador.id:
            raise ValidationError("O orientador já participa da banca — não é um dos dois membros.")
    if len(professores) != len({p.pk for p in professores}):
        raise ValidationError("Os dois membros professores precisam ser diferentes.")


def agendar_banca(projeto, data_hora, local, membros, por):
    """Agenda a `Banca` de `projeto` — fecha `EM_ANDAMENTO` →
    `AGUARDANDO_DEFESA` (Bloco D, spec §5.1). `por` é o `Usuario`
    autenticado; a permissão (só o orientador do projeto) é checada aqui
    dentro, mesmo padrão de posse de `apps.projetos.services.enviar_submissao`."""
    if not permissions.pode_agendar_banca(por, projeto):
        raise PermissionDenied("Somente o orientador do projeto agenda a banca.")
    if projeto.status != Projeto.EM_ANDAMENTO:
        raise ValidationError("Só é possível agendar banca com o projeto em andamento.")
    if not hasattr(projeto, "submissao"):
        raise ValidationError("O aluno ainda não enviou o trabalho — não há o que avaliar.")

    _valida_membros(membros, projeto.orientador)

    banca = Banca.objects.create(projeto=projeto, data_hora=data_hora, local=local)
    for membro in membros:
        MembroBanca.objects.create(banca=banca, **membro)

    projeto.status = Projeto.AGUARDANDO_DEFESA
    projeto.save(update_fields=["status"])

    return banca
```

- [ ] **Passo 5: Rodar e confirmar que os testes passam**

Run: `docker compose exec web pytest apps/bancas/tests/test_agendar.py -v`
Expected: todos `PASSED`.

- [ ] **Passo 6: Mutação obrigatória — comentar a checagem de `Submissao`**

Comente temporariamente a linha `if not hasattr(projeto, "submissao"): raise
ValidationError(...)` em `agendar_banca` e rode:
Run: `docker compose exec web pytest apps/bancas/tests/test_agendar.py -k recusa_sem_submissao -v`
Expected: `FAILED` (a checagem removida deixa de recusar). Desfaça o
comentário e rode de novo para confirmar `PASSED`.

- [ ] **Passo 7: `ruff` e `black`**

Run: `docker compose exec web ruff check .`
Run: `docker compose exec web black .`

- [ ] **Passo 8: Commit**

```bash
git add apps/bancas/permissions.py apps/bancas/services.py apps/bancas/tests/test_agendar.py
git commit -m "Tarefa 2: agendar_banca"
```

---

## Tarefa 3: `editar_banca` e `cancelar_banca`

**Arquivos:**
- Modificar: `apps/bancas/services.py`.
- Teste: `apps/bancas/tests/test_editar_cancelar.py`.

**Interfaces:**
- Consome: `_valida_membros` (Tarefa 2, mesmo arquivo).
- Produz: `services.editar_banca(banca, data_hora, local, membros, por) ->
  Banca`; `services.cancelar_banca(banca, por) -> None`.

- [ ] **Passo 1: Escrever os testes (falhando)**

Crie `apps/bancas/tests/test_editar_cancelar.py`:

```python
"""Testes de `services.editar_banca`/`cancelar_banca` (Bloco D, spec §5.1)."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.bancas import services
from apps.bancas.models import Banca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto, Submissao


def _cpf(indice):
    base = f"{620000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.editar.{indice}@ufsm.br", password="x", nome_completo=nome, cpf=_cpf(indice)
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"EDITAR{indice:03d}")


@pytest.fixture
def orientador(db):
    return _professor(1, "Orientador Editar")


@pytest.fixture
def dois_professores(db):
    return [_professor(2, "Membro Editar Um"), _professor(3, "Membro Editar Dois")]


@pytest.fixture
def banca_agendada(db, orientador, dois_professores):
    aluno = Usuario.objects.create_user(
        email="aluno.editar@ufsm.br",
        password="x",
        nome_completo="Aluno Editar",
        papel=Usuario.ALUNO,
        cpf=_cpf(4),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026EDITAR01")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=2026,
        periodo=1,
    )
    Submissao.objects.create(projeto=projeto, pdf="submissoes/v1.pdf", editavel="submissoes/v1.docx")
    return services.agendar_banca(
        projeto,
        data_hora=timezone.now() + timezone.timedelta(days=7),
        local="Sala 1",
        membros=[{"professor": dois_professores[0]}, {"professor": dois_professores[1]}],
        por=orientador.usuario,
    )


@pytest.mark.django_db
def test_editar_banca_atualiza_dados_e_membros(banca_agendada, orientador, dois_professores):
    nova_data = timezone.now() + timezone.timedelta(days=10)
    services.editar_banca(
        banca_agendada,
        data_hora=nova_data,
        local="Sala 2",
        membros=[{"professor": dois_professores[0]}, {"nome_externo": "Nova Externa"}],
        por=orientador.usuario,
    )
    banca_agendada.refresh_from_db()
    assert banca_agendada.local == "Sala 2"
    assert banca_agendada.membros.count() == 2
    assert banca_agendada.membros.filter(nome_externo="Nova Externa").exists()


@pytest.mark.django_db
def test_editar_banca_recusa_quem_nao_e_o_orientador(banca_agendada, dois_professores):
    outro = Usuario.objects.create_user(
        email="outro.editar@ufsm.br", password="x", nome_completo="Outro Editar", cpf=_cpf(5)
    )
    with pytest.raises(PermissionDenied):
        services.editar_banca(
            banca_agendada,
            data_hora=timezone.now(),
            local="Sala 3",
            membros=[{"professor": dois_professores[0]}, {"professor": dois_professores[1]}],
            por=outro,
        )


@pytest.mark.django_db
def test_editar_banca_recusa_fora_de_agendada(banca_agendada, orientador, dois_professores):
    banca_agendada.status = Banca.CANCELADA
    banca_agendada.save()
    with pytest.raises(ValidationError):
        services.editar_banca(
            banca_agendada,
            data_hora=timezone.now(),
            local="Sala 3",
            membros=[{"professor": dois_professores[0]}, {"professor": dois_professores[1]}],
            por=orientador.usuario,
        )


@pytest.mark.django_db
def test_cancelar_banca_volta_projeto_para_em_andamento(banca_agendada, orientador):
    services.cancelar_banca(banca_agendada, por=orientador.usuario)
    banca_agendada.refresh_from_db()
    assert banca_agendada.status == Banca.CANCELADA
    banca_agendada.projeto.refresh_from_db()
    assert banca_agendada.projeto.status == Projeto.EM_ANDAMENTO


@pytest.mark.django_db
def test_cancelar_banca_recusa_quem_nao_e_o_orientador(banca_agendada):
    outro = Usuario.objects.create_user(
        email="outro.cancelar@ufsm.br", password="x", nome_completo="Outro Cancelar", cpf=_cpf(6)
    )
    with pytest.raises(PermissionDenied):
        services.cancelar_banca(banca_agendada, por=outro)


@pytest.mark.django_db
def test_cancelar_banca_recusa_fora_de_agendada(banca_agendada, orientador):
    banca_agendada.status = Banca.REALIZADA
    banca_agendada.save()
    with pytest.raises(ValidationError):
        services.cancelar_banca(banca_agendada, por=orientador.usuario)
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `docker compose exec web pytest apps/bancas/tests/test_editar_cancelar.py -v`
Expected: `AttributeError: module 'apps.bancas.services' has no attribute 'editar_banca'`.

- [ ] **Passo 3: Acrescentar `editar_banca`/`cancelar_banca` a `apps/bancas/services.py`**

```python
def editar_banca(banca, data_hora, local, membros, por):
    """Reagenda `banca` — só permitida enquanto `AGENDADA` (Bloco D, spec
    §5.1). Substitui os `MembroBanca` (apaga os antigos, cria os novos) em
    vez de tentar casar a lista antiga com a nova membro a membro — mais
    simples, e o histórico de "quem era o membro antes" não é um requisito
    deste bloco."""
    if not permissions.pode_editar_banca(por, banca):
        raise PermissionDenied("Somente o orientador do projeto edita a banca.")
    if banca.status != Banca.AGENDADA:
        raise ValidationError("Só é possível editar uma banca ainda agendada.")

    _valida_membros(membros, banca.projeto.orientador)

    banca.data_hora = data_hora
    banca.local = local
    banca.save(update_fields=["data_hora", "local"])

    banca.membros.all().delete()
    for membro in membros:
        MembroBanca.objects.create(banca=banca, **membro)

    return banca


def cancelar_banca(banca, por):
    """Cancela `banca` e devolve o projeto a `EM_ANDAMENTO` — o orientador
    pode agendar uma banca nova depois (Bloco D, spec §3.4/§5.1). Sem
    notificação por e-mail (spec §8)."""
    if not permissions.pode_cancelar_banca(por, banca):
        raise PermissionDenied("Somente o orientador do projeto cancela a banca.")
    if banca.status != Banca.AGENDADA:
        raise ValidationError("Só é possível cancelar uma banca ainda agendada.")

    banca.status = Banca.CANCELADA
    banca.save(update_fields=["status"])

    banca.projeto.status = Projeto.EM_ANDAMENTO
    banca.projeto.save(update_fields=["status"])
```

- [ ] **Passo 4: Rodar e confirmar que os testes passam**

Run: `docker compose exec web pytest apps/bancas/tests/test_editar_cancelar.py -v`
Expected: todos `PASSED`.

- [ ] **Passo 5: Mutação obrigatória — checagem de status em `cancelar_banca`**

Comente `if banca.status != Banca.AGENDADA: raise ValidationError(...)` dentro
de `cancelar_banca` e rode:
Run: `docker compose exec web pytest apps/bancas/tests/test_editar_cancelar.py -k cancelar_banca_recusa_fora_de_agendada -v`
Expected: `FAILED`. Desfaça o comentário, rode de novo, confirme `PASSED`.

- [ ] **Passo 6: `ruff` e `black`, depois commit**

```bash
docker compose exec web ruff check .
docker compose exec web black .
git add apps/bancas/services.py apps/bancas/tests/test_editar_cancelar.py
git commit -m "Tarefa 3: editar_banca e cancelar_banca"
```

---

## Tarefa 4: `registrar_resultado`

**Arquivos:**
- Modificar: `apps/bancas/services.py`.
- Teste: `apps/bancas/tests/test_resultado.py`.

**Interfaces:**
- Produz: `services.registrar_resultado(banca, nota, resultado, comentario,
  por) -> Banca`.

- [ ] **Passo 1: Escrever os testes (falhando)**

Crie `apps/bancas/tests/test_resultado.py`:

```python
"""Testes de `services.registrar_resultado` (Bloco D, spec §5.1)."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.bancas import services
from apps.bancas.models import Banca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto, Submissao


def _cpf(indice):
    base = f"{630000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.resultado.{indice}@ufsm.br", password="x", nome_completo=nome, cpf=_cpf(indice)
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"RESULT{indice:03d}")


@pytest.fixture
def orientador(db):
    return _professor(1, "Orientador Resultado")


@pytest.fixture
def banca_agendada(db, orientador):
    aluno = Usuario.objects.create_user(
        email="aluno.resultado@ufsm.br",
        password="x",
        nome_completo="Aluno Resultado",
        papel=Usuario.ALUNO,
        cpf=_cpf(2),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026RESULT01")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=2026,
        periodo=1,
    )
    Submissao.objects.create(projeto=projeto, pdf="submissoes/v1.pdf", editavel="submissoes/v1.docx")
    membro1 = _professor(3, "Membro Resultado Um")
    membro2 = _professor(4, "Membro Resultado Dois")
    return services.agendar_banca(
        projeto,
        data_hora=timezone.now(),
        local="Sala 1",
        membros=[{"professor": membro1}, {"professor": membro2}],
        por=orientador.usuario,
    )


@pytest.mark.django_db
def test_registrar_resultado_aprovado_com_ressalvas(banca_agendada, orientador):
    services.registrar_resultado(
        banca_agendada,
        nota=8.5,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
        comentario="Boa apresentação, ajustar a conclusão.",
        por=orientador.usuario,
    )
    banca_agendada.refresh_from_db()
    assert banca_agendada.status == Banca.REALIZADA
    assert str(banca_agendada.nota) == "8.5"
    banca_agendada.projeto.refresh_from_db()
    assert banca_agendada.projeto.status == Projeto.APROVADO_COM_RESSALVAS


@pytest.mark.django_db
def test_registrar_resultado_reprovado(banca_agendada, orientador):
    services.registrar_resultado(
        banca_agendada,
        nota=3.0,
        resultado=Projeto.REPROVADO,
        comentario="Não atendeu aos critérios mínimos.",
        por=orientador.usuario,
    )
    banca_agendada.projeto.refresh_from_db()
    assert banca_agendada.projeto.status == Projeto.REPROVADO


@pytest.mark.django_db
def test_registrar_resultado_recusa_quem_nao_e_o_orientador(banca_agendada):
    outro = Usuario.objects.create_user(
        email="outro.resultado@ufsm.br", password="x", nome_completo="Outro Resultado", cpf=_cpf(5)
    )
    with pytest.raises(PermissionDenied):
        services.registrar_resultado(
            banca_agendada,
            nota=7.0,
            resultado=Projeto.APROVADO_COM_RESSALVAS,
            comentario="",
            por=outro,
        )


@pytest.mark.django_db
def test_registrar_resultado_recusa_duas_vezes(banca_agendada, orientador):
    services.registrar_resultado(
        banca_agendada,
        nota=8.0,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
        comentario="Ok.",
        por=orientador.usuario,
    )
    with pytest.raises(ValidationError):
        services.registrar_resultado(
            banca_agendada,
            nota=9.0,
            resultado=Projeto.APROVADO_COM_RESSALVAS,
            comentario="De novo.",
            por=orientador.usuario,
        )
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `docker compose exec web pytest apps/bancas/tests/test_resultado.py -v`
Expected: `AttributeError` — `registrar_resultado` ainda não existe.

- [ ] **Passo 3: Acrescentar `registrar_resultado` a `apps/bancas/services.py`**

```python
def registrar_resultado(banca, nota, resultado, comentario, por):
    """Registra o resultado da apresentação — fecha `AGUARDANDO_DEFESA` →
    `resultado` (Bloco D, spec §3.2/§5.1). Sem trava de data (§3.5): confia
    no orientador para só chamar depois que a apresentação aconteceu."""
    if not permissions.pode_registrar_resultado_banca(por, banca):
        raise PermissionDenied("Somente o orientador do projeto registra o resultado.")
    if banca.status != Banca.AGENDADA:
        raise ValidationError("Esta banca já teve o resultado registrado, ou foi cancelada.")

    banca.nota = nota
    banca.resultado = resultado
    banca.comentario = comentario
    banca.status = Banca.REALIZADA
    banca.save(update_fields=["nota", "resultado", "comentario", "status"])

    banca.projeto.status = resultado
    banca.projeto.save(update_fields=["status"])

    return banca
```

- [ ] **Passo 4: Rodar e confirmar que os testes passam**

Run: `docker compose exec web pytest apps/bancas/tests/test_resultado.py -v`
Expected: todos `PASSED`.

- [ ] **Passo 5: Mutação obrigatória — checagem de dupla escrita**

Comente `if banca.status != Banca.AGENDADA: raise ValidationError(...)` em
`registrar_resultado` e rode:
Run: `docker compose exec web pytest apps/bancas/tests/test_resultado.py -k recusa_duas_vezes -v`
Expected: `FAILED`. Desfaça, confirme `PASSED` de novo.

- [ ] **Passo 6: `ruff` e `black`, depois commit**

```bash
docker compose exec web ruff check .
docker compose exec web black .
git add apps/bancas/services.py apps/bancas/tests/test_resultado.py
git commit -m "Tarefa 4: registrar_resultado"
```

---

## Tarefa 5: `reabrir_projeto`/`cancelar_projeto` e o filtro de `orientandos_atuais`

**Arquivos:**
- Modificar: `apps/projetos/services.py`, `apps/projetos/permissions.py`.
- Teste: `apps/projetos/tests/test_reprovacao.py` (novo).

**Interfaces:**
- Produz: `services.reabrir_projeto(projeto, por) -> None`;
  `services.cancelar_projeto(projeto, por) -> None`;
  `permissions.pode_reabrir_projeto(usuario, projeto) -> bool`;
  `permissions.pode_cancelar_projeto(usuario, projeto) -> bool`.
- Modifica: `orientandos_atuais` — mesma assinatura, filtro ampliado
  (spec §3.7).

- [ ] **Passo 1: Escrever os testes (falhando)**

Crie `apps/projetos/tests/test_reprovacao.py`:

```python
"""Testes dos dois caminhos a partir de `Projeto.REPROVADO` (Bloco D, spec
§3.6) e do filtro ampliado de `orientandos_atuais` (spec §3.7)."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.comum.semestre import semestre_vigente
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos import services
from apps.projetos.models import Projeto


def _cpf(indice):
    base = f"{640000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.reprovacao.{indice}@ufsm.br", password="x", nome_completo=nome, cpf=_cpf(indice)
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"REPROV{indice:03d}")


def _aluno(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"aluno.reprovacao.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        papel=Usuario.ALUNO,
        cpf=_cpf(indice),
    )
    PerfilAluno.objects.create(usuario=usuario, matricula=f"2026REPROV{indice:02d}")
    return usuario


@pytest.fixture
def orientador(db):
    return _professor(1, "Orientador Reprovação")


@pytest.fixture
def projeto_reprovado(db, orientador):
    ano, periodo = semestre_vigente()
    aluno = _aluno(2, "Aluno Reprovado")
    return Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.REPROVADO,
        ano=ano,
        periodo=periodo,
    )


@pytest.mark.django_db
def test_reabrir_projeto_volta_para_em_andamento(projeto_reprovado, orientador):
    services.reabrir_projeto(projeto_reprovado, por=orientador.usuario)
    projeto_reprovado.refresh_from_db()
    assert projeto_reprovado.status == Projeto.EM_ANDAMENTO


@pytest.mark.django_db
def test_reabrir_projeto_recusa_quem_nao_e_o_orientador(projeto_reprovado):
    outro = Usuario.objects.create_user(
        email="outro.reabrir@ufsm.br", password="x", nome_completo="Outro Reabrir", cpf=_cpf(3)
    )
    with pytest.raises(PermissionDenied):
        services.reabrir_projeto(projeto_reprovado, por=outro)


@pytest.mark.django_db
def test_reabrir_projeto_recusa_fora_de_reprovado(projeto_reprovado, orientador):
    projeto_reprovado.status = Projeto.EM_ANDAMENTO
    projeto_reprovado.save()
    with pytest.raises(ValidationError):
        services.reabrir_projeto(projeto_reprovado, por=orientador.usuario)


@pytest.mark.django_db
def test_cancelar_projeto_marca_cancelado(projeto_reprovado, orientador):
    services.cancelar_projeto(projeto_reprovado, por=orientador.usuario)
    projeto_reprovado.refresh_from_db()
    assert projeto_reprovado.status == Projeto.CANCELADO


@pytest.mark.django_db
def test_cancelar_projeto_recusa_quem_nao_e_o_orientador(projeto_reprovado):
    outro = Usuario.objects.create_user(
        email="outro.cancelarprojeto@ufsm.br",
        password="x",
        nome_completo="Outro Cancelar Projeto",
        cpf=_cpf(4),
    )
    with pytest.raises(PermissionDenied):
        services.cancelar_projeto(projeto_reprovado, por=outro)


@pytest.mark.django_db
def test_orientandos_atuais_inclui_aguardando_defesa_e_reprovado(orientador):
    ano, periodo = semestre_vigente()
    aluno_aguardando = _aluno(5, "Aluno Aguardando Defesa")
    Projeto.objects.create(
        aluno=aluno_aguardando,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.AGUARDANDO_DEFESA,
        ano=ano,
        periodo=periodo,
    )
    aluno_reprovado = _aluno(6, "Aluno Reprovado Dois")
    Projeto.objects.create(
        aluno=aluno_reprovado,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.REPROVADO,
        ano=ano,
        periodo=periodo,
    )
    resultado = {p.aluno_id for p in services.orientandos_atuais(orientador)}
    assert aluno_aguardando.id in resultado
    assert aluno_reprovado.id in resultado


@pytest.mark.django_db
def test_orientandos_atuais_exclui_cancelado(orientador):
    ano, periodo = semestre_vigente()
    aluno_cancelado = _aluno(7, "Aluno Cancelado")
    Projeto.objects.create(
        aluno=aluno_cancelado,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.CANCELADO,
        ano=ano,
        periodo=periodo,
    )
    resultado = {p.aluno_id for p in services.orientandos_atuais(orientador)}
    assert aluno_cancelado.id not in resultado
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `docker compose exec web pytest apps/projetos/tests/test_reprovacao.py -v`
Expected: `AttributeError: module 'apps.projetos.services' has no attribute
'reabrir_projeto'` (e `test_orientandos_atuais_inclui_...` falha por assertion,
já que o filtro atual só devolve `EM_ANDAMENTO`).

- [ ] **Passo 3: Ampliar o filtro de `orientandos_atuais`**

Em `apps/projetos/services.py`, na função `orientandos_atuais`, troque
`status=Projeto.EM_ANDAMENTO` por:

```python
            status__in=[Projeto.EM_ANDAMENTO, Projeto.AGUARDANDO_DEFESA, Projeto.REPROVADO],
```

(mantém `.select_related("aluno", "tema", "submissao")` como está, e a
docstring da função ganha uma linha citando o Bloco D — spec §3.7.)

- [ ] **Passo 4: Acrescentar `pode_reabrir_projeto`/`pode_cancelar_projeto` a `apps/projetos/permissions.py`**

```python
def pode_reabrir_projeto(usuario, projeto):
    """`usuario` é exatamente o orientador de `projeto` (Bloco D, spec §3.6)
    — posse, não papel."""
    return bool(usuario and usuario.is_authenticated and usuario == projeto.orientador)


def pode_cancelar_projeto(usuario, projeto):
    """Mesma regra de posse de `pode_reabrir_projeto`."""
    return bool(usuario and usuario.is_authenticated and usuario == projeto.orientador)
```

- [ ] **Passo 5: Acrescentar `reabrir_projeto`/`cancelar_projeto` a `apps/projetos/services.py`**

```python
def reabrir_projeto(projeto, por):
    """Reabre um `Projeto` `REPROVADO` — volta a `EM_ANDAMENTO`, o aluno
    tenta de novo (Bloco D, spec §3.6). Só o orientador, só a partir de
    `REPROVADO`."""
    if not permissions.pode_reabrir_projeto(por, projeto):
        raise PermissionDenied("Somente o orientador do projeto pode reabri-lo.")
    if projeto.status != Projeto.REPROVADO:
        raise ValidationError("Só é possível reabrir um projeto reprovado.")

    projeto.status = Projeto.EM_ANDAMENTO
    projeto.save(update_fields=["status"])


def cancelar_projeto(projeto, por):
    """Encerra definitivamente um `Projeto` `REPROVADO` (Bloco D, spec
    §3.6) — distinto de `REPROVADO`: registra que o projeto foi encerrado,
    não só que a banca não aprovou."""
    if not permissions.pode_cancelar_projeto(por, projeto):
        raise PermissionDenied("Somente o orientador do projeto pode cancelá-lo.")
    if projeto.status != Projeto.REPROVADO:
        raise ValidationError("Só é possível cancelar um projeto reprovado.")

    projeto.status = Projeto.CANCELADO
    projeto.save(update_fields=["status"])
```

`PermissionDenied` já está importado em `apps/projetos/services.py`? Confira
com `grep -n "^from django.core.exceptions" apps/projetos/services.py` — se só
`ValidationError` estiver na lista, acrescente `PermissionDenied` ao mesmo
`from django.core.exceptions import ...`.

- [ ] **Passo 6: Rodar e confirmar que os testes passam**

Run: `docker compose exec web pytest apps/projetos/tests/test_reprovacao.py -v`
Expected: todos `PASSED`.

- [ ] **Passo 7: Rodar a suíte de `apps/projetos` inteira**

O filtro de `orientandos_atuais` mudou — outros testes que dependem dele
(`test_fila_professor.py`, `test_submissao.py`, `test_tela_meu_tcc.py`)
precisam continuar passando:

Run: `docker compose exec web pytest apps/projetos/ -v`
Expected: todos `PASSED` (nenhuma regressão).

- [ ] **Passo 8: `ruff` e `black`, depois commit**

```bash
docker compose exec web ruff check .
docker compose exec web black .
git add apps/projetos/services.py apps/projetos/permissions.py \
        apps/projetos/tests/test_reprovacao.py
git commit -m "Tarefa 5: reabrir_projeto, cancelar_projeto, e orientandos_atuais amplia o filtro"
```

---

## Tarefa 6: Notificação de agendamento (`apps/bancas/tasks.py`)

**Arquivos:**
- Criar: `apps/bancas/tasks.py`, `templates/email/banca_agendada_aluno.txt`,
  `templates/email/banca_agendada_professor.txt`.
- Modificar: `apps/bancas/services.py` (`agendar_banca`/`editar_banca`
  disparam a tarefa).
- Teste: `apps/bancas/tests/test_notificacoes.py`.

**Interfaces:**
- Produz: `tasks.enviar_agendamento_banca(banca_id)`.

- [ ] **Passo 1: Escrever os testes (falhando)**

Crie `apps/bancas/tests/test_notificacoes.py`:

```python
"""Testes de `tasks.enviar_agendamento_banca` (Bloco D, spec §8). Mesmo
padrão de `apps/projetos/tests/test_fila_professor.py`:
`django_capture_on_commit_callbacks` para disparar o `transaction.on_commit`
dentro do teste, e `CELERY_TASK_ALWAYS_EAGER` para a tarefa rodar
sincronamente."""

import pytest
from django.core import mail
from django.utils import timezone

from apps.bancas import services
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto, Submissao


def _cpf(indice):
    base = f"{650000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.notif.{indice}@ufsm.br", password="x", nome_completo=nome, cpf=_cpf(indice)
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"NOTIF{indice:03d}")


@pytest.fixture
def cenario(db):
    orientador = _professor(1, "Orientador Notif")
    aluno = Usuario.objects.create_user(
        email="aluno.notif@ufsm.br",
        password="x",
        nome_completo="Aluno Notif",
        papel=Usuario.ALUNO,
        cpf=_cpf(2),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026NOTIF001")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=2026,
        periodo=1,
    )
    Submissao.objects.create(projeto=projeto, pdf="submissoes/v1.pdf", editavel="submissoes/v1.docx")
    membro_interno = _professor(3, "Membro Interno Notif")
    return {
        "orientador": orientador,
        "aluno": aluno,
        "projeto": projeto,
        "membro_interno": membro_interno,
    }


@pytest.mark.django_db
def test_agendar_banca_notifica_aluno_e_membro_interno(
    settings, django_capture_on_commit_callbacks, cenario
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with django_capture_on_commit_callbacks(execute=True):
        services.agendar_banca(
            cenario["projeto"],
            data_hora=timezone.now(),
            local="Sala 1",
            membros=[
                {"professor": cenario["membro_interno"]},
                {"nome_externo": "Fulano Externo"},
            ],
            por=cenario["orientador"].usuario,
        )
    destinatarios = {destinatario for m in mail.outbox for destinatario in m.to}
    assert cenario["aluno"].email in destinatarios
    assert cenario["membro_interno"].usuario.email in destinatarios
    # Nunca um e-mail para "Fulano Externo" — não tem endereço cadastrado.
    assert len(mail.outbox) == 2


@pytest.mark.django_db
def test_editar_banca_reenvia_notificacao(settings, django_capture_on_commit_callbacks, cenario):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with django_capture_on_commit_callbacks(execute=True):
        banca = services.agendar_banca(
            cenario["projeto"],
            data_hora=timezone.now(),
            local="Sala 1",
            membros=[{"professor": cenario["membro_interno"]}, {"nome_externo": "Fulano"}],
            por=cenario["orientador"].usuario,
        )
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        services.editar_banca(
            banca,
            data_hora=timezone.now() + timezone.timedelta(days=1),
            local="Sala 2",
            membros=[{"professor": cenario["membro_interno"]}, {"nome_externo": "Fulano"}],
            por=cenario["orientador"].usuario,
        )
    assert len(mail.outbox) == 2


@pytest.mark.django_db
def test_cancelar_banca_nao_notifica(settings, django_capture_on_commit_callbacks, cenario):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with django_capture_on_commit_callbacks(execute=True):
        banca = services.agendar_banca(
            cenario["projeto"],
            data_hora=timezone.now(),
            local="Sala 1",
            membros=[{"professor": cenario["membro_interno"]}, {"nome_externo": "Fulano"}],
            por=cenario["orientador"].usuario,
        )
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        services.cancelar_banca(banca, por=cenario["orientador"].usuario)
    assert len(mail.outbox) == 0
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `docker compose exec web pytest apps/bancas/tests/test_notificacoes.py -v`
Expected: `test_agendar_banca_notifica_...` falha (`mail.outbox` vazio — nada
dispara e-mail ainda).

- [ ] **Passo 3: Criar os templates de e-mail**

`templates/email/banca_agendada_aluno.txt`:

```
Olá, {{ aluno.nome_completo }}.

Sua banca de defesa foi agendada:

Data e hora: {{ banca.data_hora }}
Local: {{ banca.local }}

Entre no sistema para mais detalhes: {{ link }}

OrientaSI — Sistema de Gestão de TCC
```

`templates/email/banca_agendada_professor.txt`:

```
Olá, {{ professor.nome_completo }}.

Você foi indicado como membro da banca de defesa de {{ aluno.nome_completo }}:

Data e hora: {{ banca.data_hora }}
Local: {{ banca.local }}

Entre no sistema para mais detalhes: {{ link }}

OrientaSI — Sistema de Gestão de TCC
```

- [ ] **Passo 4: Escrever `apps/bancas/tasks.py`**

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
def enviar_agendamento_banca(self, banca_id):
    """Avisa o aluno e cada membro INTERNO da banca (Bloco D, spec §8).
    Dois grupos, `send_mail` separado para cada um (mesmo motivo de
    `apps.projetos.tasks.enviar_esgotamento`: corpos de e-mail diferentes
    por grupo). Membro externo nunca recebe nada — não tem e-mail
    cadastrado (só nome, regra 3 do CLAUDE.md)."""
    from apps.bancas.models import Banca

    banca = Banca.objects.select_related("projeto__aluno").prefetch_related(
        "membros__professor__usuario"
    ).get(pk=banca_id)
    aluno = banca.projeto.aluno
    link = _link_login()

    try:
        corpo_aluno = render_to_string(
            "email/banca_agendada_aluno.txt", {"aluno": aluno, "banca": banca, "link": link}
        )
        send_mail(
            subject="OrientaSI — sua banca de defesa foi agendada",
            message=corpo_aluno,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[aluno.email],
        )
    except Exception as erro:  # noqa: BLE001 — repetimos qualquer falha de entrega
        raise self.retry(exc=erro, countdown=60 * 2**self.request.retries) from erro

    for membro in banca.membros.all():
        if membro.professor is None:
            continue
        professor_usuario = membro.professor.usuario
        try:
            corpo_professor = render_to_string(
                "email/banca_agendada_professor.txt",
                {"professor": professor_usuario, "aluno": aluno, "banca": banca, "link": link},
            )
            send_mail(
                subject="OrientaSI — você foi indicado para uma banca de defesa",
                message=corpo_professor,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[professor_usuario.email],
            )
        except Exception as erro:  # noqa: BLE001 — repetimos qualquer falha de entrega
            raise self.retry(exc=erro, countdown=60 * 2**self.request.retries) from erro
```

- [ ] **Passo 5: Disparar a tarefa em `agendar_banca`/`editar_banca`**

Em `apps/bancas/services.py`, acrescente ao topo do arquivo:

```python
from django.db import transaction

from apps.bancas.tasks import enviar_agendamento_banca
```

E, ao FINAL de `agendar_banca` (antes do `return banca`) e ao final de
`editar_banca` (antes do `return banca`), a mesma linha:

```python
    transaction.on_commit(lambda: enviar_agendamento_banca.delay(banca.id))
```

- [ ] **Passo 6: Rodar e confirmar que os testes passam**

Run: `docker compose exec web pytest apps/bancas/tests/test_notificacoes.py -v`
Expected: todos `PASSED`.

- [ ] **Passo 7: Rodar a suíte de `apps/bancas` inteira**

Run: `docker compose exec web pytest apps/bancas/ -v`
Expected: todos `PASSED` — confirma que anexar a notificação não quebrou
`test_agendar.py`/`test_editar_cancelar.py`/`test_resultado.py` (nenhum deles
usa `django_capture_on_commit_callbacks`, então o `on_commit` novo não
dispara nesses testes — mesma observação já registrada em
`test_fila_professor.py` para `enviar_recusa`).

- [ ] **Passo 8: `ruff` e `black`, depois commit**

```bash
docker compose exec web ruff check .
docker compose exec web black .
git add apps/bancas/tasks.py apps/bancas/services.py apps/bancas/tests/test_notificacoes.py \
        templates/email/banca_agendada_aluno.txt templates/email/banca_agendada_professor.txt
git commit -m "Tarefa 6: notificacao de agendamento de banca"
```

---

## Tarefa 7: Formulários (`apps/bancas/forms.py`)

**Arquivos:**
- Criar: `apps/bancas/forms.py`.
- Teste: `apps/bancas/tests/test_formularios.py`.

**Interfaces:**
- Produz: `FormularioBanca` (campos `data_hora`, `local`,
  `membro_1_professor`, `membro_1_externo`, `membro_2_professor`,
  `membro_2_externo`; `cleaned_data["membros"]` no formato que
  `services.agendar_banca`/`editar_banca` esperam); `FormularioResultadoBanca`
  (`nota`, `resultado`, `comentario`).

- [ ] **Passo 1: Escrever os testes (falhando)**

Crie `apps/bancas/tests/test_formularios.py`:

```python
"""Testes de `FormularioBanca`/`FormularioResultadoBanca` (Bloco D, spec §7)."""

import pytest

from apps.bancas.forms import FormularioBanca, FormularioResultadoBanca
from apps.contas.models import PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto


def _cpf(indice):
    base = f"{660000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.formulario.{indice}@ufsm.br", password="x", nome_completo=nome, cpf=_cpf(indice)
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"FORM{indice:03d}")


@pytest.mark.django_db
def test_formulario_banca_aceita_professor_e_externo():
    orientador = _professor(1, "Orientador Formulário")
    membro = _professor(2, "Membro Formulário")
    formulario = FormularioBanca(
        data={
            "data_hora": "2026-12-01T14:00",
            "local": "Sala 5",
            "membro_1_professor": membro.pk,
            "membro_1_externo": "",
            "membro_2_professor": "",
            "membro_2_externo": "Fulano Externo",
        },
        orientador=orientador.usuario,
    )
    assert formulario.is_valid(), formulario.errors
    membros = formulario.cleaned_data["membros"]
    assert membros[0] == {"professor": membro}
    assert membros[1] == {"nome_externo": "Fulano Externo"}


@pytest.mark.django_db
def test_formulario_banca_recusa_membro_com_os_dois_campos():
    orientador = _professor(3, "Orientador Formulário Dois")
    membro = _professor(4, "Membro Formulário Dois")
    formulario = FormularioBanca(
        data={
            "data_hora": "2026-12-01T14:00",
            "local": "Sala 5",
            "membro_1_professor": membro.pk,
            "membro_1_externo": "Fulano",
            "membro_2_professor": "",
            "membro_2_externo": "Beltrano",
        },
        orientador=orientador.usuario,
    )
    assert not formulario.is_valid()


@pytest.mark.django_db
def test_formulario_banca_recusa_membro_sem_nenhum_campo():
    orientador = _professor(5, "Orientador Formulário Três")
    formulario = FormularioBanca(
        data={
            "data_hora": "2026-12-01T14:00",
            "local": "Sala 5",
            "membro_1_professor": "",
            "membro_1_externo": "",
            "membro_2_professor": "",
            "membro_2_externo": "Beltrano",
        },
        orientador=orientador.usuario,
    )
    assert not formulario.is_valid()


@pytest.mark.django_db
def test_formulario_banca_exclui_o_orientador_do_queryset():
    orientador = _professor(6, "Orientador Formulário Quatro")
    formulario = FormularioBanca(orientador=orientador.usuario)
    assert orientador not in formulario.fields["membro_1_professor"].queryset
    assert orientador not in formulario.fields["membro_2_professor"].queryset


def test_formulario_resultado_banca_aceita_aprovado_com_ressalvas():
    formulario = FormularioResultadoBanca(
        data={"nota": "8.5", "resultado": Projeto.APROVADO_COM_RESSALVAS, "comentario": "Ok."}
    )
    assert formulario.is_valid(), formulario.errors


def test_formulario_resultado_banca_recusa_nota_fora_da_faixa():
    formulario = FormularioResultadoBanca(
        data={"nota": "11", "resultado": Projeto.APROVADO_COM_RESSALVAS, "comentario": ""}
    )
    assert not formulario.is_valid()
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `docker compose exec web pytest apps/bancas/tests/test_formularios.py -v`
Expected: `ModuleNotFoundError: No module named 'apps.bancas.forms'`.

- [ ] **Passo 3: Escrever `apps/bancas/forms.py`**

```python
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
    local = forms.CharField(label="Local", max_length=200, widget=forms.TextInput(attrs={"class": "input w-full"}))
    membro_1_professor = forms.ModelChoiceField(
        label="1º membro — professor (deixe em branco se for externo)",
        queryset=PerfilProfessor.objects.select_related("usuario").order_by("usuario__nome_completo"),
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
        queryset=PerfilProfessor.objects.select_related("usuario").order_by("usuario__nome_completo"),
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
                f"Preencha só um campo para o {indice}º membro — professor OU nome externo, não os dois."
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
```

- [ ] **Passo 4: Rodar e confirmar que os testes passam**

Run: `docker compose exec web pytest apps/bancas/tests/test_formularios.py -v`
Expected: todos `PASSED`.

- [ ] **Passo 5: `ruff` e `black`, depois commit**

```bash
docker compose exec web ruff check .
docker compose exec web black .
git add apps/bancas/forms.py apps/bancas/tests/test_formularios.py
git commit -m "Tarefa 7: FormularioBanca e FormularioResultadoBanca"
```

---

## Tarefa 8: Telas de `apps/bancas` (agendar/editar/cancelar/resultado)

**Arquivos:**
- Criar: `apps/bancas/views.py`, `apps/bancas/urls.py`,
  `templates/bancas/formulario.html`, `templates/bancas/resultado.html`.
- Modificar: `config/urls.py`.
- Teste: `apps/bancas/tests/test_telas.py`.

**Interfaces:**
- Consome: `FormularioBanca`, `FormularioResultadoBanca` (Tarefa 7);
  `services.agendar_banca`/`editar_banca`/`cancelar_banca`/`registrar_resultado`
  (Tarefas 2–4).
- Produz: rotas `bancas:agendar`, `bancas:editar`, `bancas:cancelar`,
  `bancas:resultado`.

- [ ] **Passo 1: Escrever os testes (falhando)**

Crie `apps/bancas/tests/test_telas.py`:

```python
"""Testes HTTP das telas de `apps/bancas` (Bloco D, spec §7). Lookup
escopado ao orientador — dono alheio e pk inexistente respondem os DOIS com
404, nunca 403 (mesmo padrão de `editar_tema`/`desativar_tema`, Bloco B)."""

import pytest
from django.utils import timezone

from apps.bancas import services
from apps.bancas.models import Banca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto, Submissao


def _cpf(indice):
    base = f"{670000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.tela.{indice}@ufsm.br", password="x", nome_completo=nome, cpf=_cpf(indice)
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"TELA{indice:03d}")


@pytest.fixture
def cenario(db):
    orientador = _professor(1, "Orientador Tela")
    aluno = Usuario.objects.create_user(
        email="aluno.tela@ufsm.br",
        password="x",
        nome_completo="Aluno Tela",
        papel=Usuario.ALUNO,
        cpf=_cpf(2),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026TELA0001")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=2026,
        periodo=1,
    )
    Submissao.objects.create(projeto=projeto, pdf="submissoes/v1.pdf", editavel="submissoes/v1.docx")
    membro1 = _professor(3, "Membro Tela Um")
    membro2 = _professor(4, "Membro Tela Dois")
    return {
        "orientador": orientador,
        "projeto": projeto,
        "membro1": membro1,
        "membro2": membro2,
    }


@pytest.mark.django_db
def test_agendar_get_mostra_formulario(client, cenario):
    client.force_login(cenario["orientador"].usuario)
    resposta = client.get(f"/bancas/agendar/{cenario['projeto'].pk}/")
    assert resposta.status_code == 200


@pytest.mark.django_db
def test_agendar_post_cria_banca_e_redireciona(client, cenario):
    client.force_login(cenario["orientador"].usuario)
    resposta = client.post(
        f"/bancas/agendar/{cenario['projeto'].pk}/",
        {
            "data_hora": "2026-12-01T14:00",
            "local": "Sala 9",
            "membro_1_professor": cenario["membro1"].pk,
            "membro_1_externo": "",
            "membro_2_professor": cenario["membro2"].pk,
            "membro_2_externo": "",
        },
    )
    assert resposta.status_code == 302
    assert Banca.objects.filter(projeto=cenario["projeto"]).exists()


@pytest.mark.django_db
def test_agendar_recusa_projeto_alheio_com_404(client, cenario):
    outro_professor = _professor(5, "Outro Professor Tela")
    client.force_login(outro_professor.usuario)
    resposta = client.get(f"/bancas/agendar/{cenario['projeto'].pk}/")
    assert resposta.status_code == 404


@pytest.mark.django_db
def test_cancelar_recusa_banca_alheia_com_404(client, cenario):
    banca = services.agendar_banca(
        cenario["projeto"],
        data_hora=timezone.now(),
        local="Sala 1",
        membros=[{"professor": cenario["membro1"]}, {"professor": cenario["membro2"]}],
        por=cenario["orientador"].usuario,
    )
    outro_professor = _professor(6, "Outro Professor Cancelar")
    client.force_login(outro_professor.usuario)
    resposta = client.post(f"/bancas/{banca.pk}/cancelar/")
    assert resposta.status_code == 404


@pytest.mark.django_db
def test_resultado_post_registra_e_redireciona(client, cenario):
    banca = services.agendar_banca(
        cenario["projeto"],
        data_hora=timezone.now(),
        local="Sala 1",
        membros=[{"professor": cenario["membro1"]}, {"professor": cenario["membro2"]}],
        por=cenario["orientador"].usuario,
    )
    client.force_login(cenario["orientador"].usuario)
    resposta = client.post(
        f"/bancas/{banca.pk}/resultado/",
        {"nota": "8.0", "resultado": Projeto.APROVADO_COM_RESSALVAS, "comentario": "Ok."},
    )
    assert resposta.status_code == 302
    banca.refresh_from_db()
    assert banca.status == Banca.REALIZADA
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `docker compose exec web pytest apps/bancas/tests/test_telas.py -v`
Expected: `404`/erro de resolução de URL — nem `apps/bancas/urls.py` nem
`views.py` existem ainda, e `config/urls.py` não inclui o app.

- [ ] **Passo 3: Escrever `apps/bancas/views.py`**

```python
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.bancas import services
from apps.bancas.forms import FormularioBanca, FormularioResultadoBanca
from apps.bancas.models import Banca
from apps.projetos.models import Projeto


@login_required
def agendar(request, projeto_id):
    """Agenda a banca de `projeto_id` (Bloco D, spec §7). Lookup escopado ao
    orientador autenticado — projeto alheio e projeto inexistente respondem
    os dois com 404, mesmo padrão de `editar_tema`/`meu_tcc`."""
    projeto = get_object_or_404(Projeto, pk=projeto_id, orientador=request.user)

    if request.method == "POST":
        formulario = FormularioBanca(request.POST, orientador=request.user)
        if formulario.is_valid():
            try:
                services.agendar_banca(
                    projeto,
                    data_hora=formulario.cleaned_data["data_hora"],
                    local=formulario.cleaned_data["local"],
                    membros=formulario.cleaned_data["membros"],
                    por=request.user,
                )
            except ValidationError as erro:
                formulario.add_error(None, erro.messages[0])
            else:
                messages.success(request, "Banca agendada.")
                return redirect("projetos:orientacoes")
    else:
        formulario = FormularioBanca(orientador=request.user)

    return render(
        request,
        "bancas/formulario.html",
        {"formulario": formulario, "projeto": projeto, "titulo": "Agendar banca"},
    )


@login_required
def editar(request, banca_id):
    """Reagenda uma banca já `AGENDADA` (Bloco D, spec §7). Lookup escopado
    via `projeto__orientador`, mesmo raciocínio de `agendar`."""
    banca = get_object_or_404(Banca, pk=banca_id, projeto__orientador=request.user)

    if request.method == "POST":
        formulario = FormularioBanca(request.POST, orientador=request.user)
        if formulario.is_valid():
            try:
                services.editar_banca(
                    banca,
                    data_hora=formulario.cleaned_data["data_hora"],
                    local=formulario.cleaned_data["local"],
                    membros=formulario.cleaned_data["membros"],
                    por=request.user,
                )
            except ValidationError as erro:
                formulario.add_error(None, erro.messages[0])
            else:
                messages.success(request, "Banca atualizada.")
                return redirect("projetos:orientacoes")
    else:
        formulario = FormularioBanca(
            orientador=request.user,
            initial={"data_hora": banca.data_hora, "local": banca.local},
        )

    return render(
        request,
        "bancas/formulario.html",
        {"formulario": formulario, "projeto": banca.projeto, "titulo": "Editar banca"},
    )


@login_required
@require_POST
def cancelar(request, banca_id):
    """Cancela uma banca `AGENDADA` (Bloco D, spec §7) — sem tela própria,
    um `<form>` direto em `/orientacoes/`, mesmo padrão simples de
    `desativar_tema`."""
    banca = get_object_or_404(Banca, pk=banca_id, projeto__orientador=request.user)
    services.cancelar_banca(banca, por=request.user)
    messages.success(request, "Banca cancelada.")
    return redirect("projetos:orientacoes")


@login_required
def resultado(request, banca_id):
    """Registra o resultado de uma banca `AGENDADA` (Bloco D, spec §7)."""
    banca = get_object_or_404(Banca, pk=banca_id, projeto__orientador=request.user)

    if request.method == "POST":
        formulario = FormularioResultadoBanca(request.POST)
        if formulario.is_valid():
            try:
                services.registrar_resultado(
                    banca,
                    nota=formulario.cleaned_data["nota"],
                    resultado=formulario.cleaned_data["resultado"],
                    comentario=formulario.cleaned_data["comentario"],
                    por=request.user,
                )
            except ValidationError as erro:
                formulario.add_error(None, erro.messages[0])
            else:
                messages.success(request, "Resultado registrado.")
                return redirect("projetos:orientacoes")
    else:
        formulario = FormularioResultadoBanca()

    return render(request, "bancas/resultado.html", {"formulario": formulario, "banca": banca})
```

- [ ] **Passo 4: Escrever `apps/bancas/urls.py`**

```python
from django.urls import path

from apps.bancas import views

app_name = "bancas"

urlpatterns = [
    path("bancas/agendar/<int:projeto_id>/", views.agendar, name="agendar"),
    path("bancas/<int:banca_id>/editar/", views.editar, name="editar"),
    path("bancas/<int:banca_id>/cancelar/", views.cancelar, name="cancelar"),
    path("bancas/<int:banca_id>/resultado/", views.resultado, name="resultado"),
]
```

- [ ] **Passo 5: Registrar em `config/urls.py`**

Acrescente, junto às demais linhas `include`:

```python
    path("", include("apps.bancas.urls")),
```

- [ ] **Passo 6: Criar `templates/bancas/formulario.html`**

```html
{% extends "base.html" %}

{% block titulo %} — {{ titulo }}{% endblock %}

{% block conteudo %}
  <article class="mx-auto max-w-xl rounded-box bg-base-100 p-6 shadow-sm">
    <h1 class="font-display text-2xl font-bold text-primary">{{ titulo }}</h1>
    <p class="mt-2 text-sm text-base-content/80">
      Projeto de {{ projeto.aluno.nome_completo }}.
    </p>

    <form method="post" class="mt-6 space-y-4">
      {% csrf_token %}
      {% if formulario.non_field_errors %}
        <div role="alert" class="alert alert-error">
          {% for erro in formulario.non_field_errors %}<p>{{ erro }}</p>{% endfor %}
        </div>
      {% endif %}
      {% for campo in formulario %}
        {% include "contas/_campo.html" with campo=campo %}
      {% endfor %}
      <button type="submit" class="btn btn-primary">Salvar</button>
    </form>
  </article>
{% endblock %}
```

- [ ] **Passo 7: Criar `templates/bancas/resultado.html`**

```html
{% extends "base.html" %}

{% block titulo %} — Registrar resultado{% endblock %}

{% block conteudo %}
  <article class="mx-auto max-w-xl rounded-box bg-base-100 p-6 shadow-sm">
    <h1 class="font-display text-2xl font-bold text-primary">Registrar resultado</h1>
    <p class="mt-2 text-sm text-base-content/80">
      Banca de {{ banca.projeto.aluno.nome_completo }} — {{ banca.data_hora }}.
    </p>

    <form method="post" class="mt-6 space-y-4">
      {% csrf_token %}
      {% if formulario.non_field_errors %}
        <div role="alert" class="alert alert-error">
          {% for erro in formulario.non_field_errors %}<p>{{ erro }}</p>{% endfor %}
        </div>
      {% endif %}
      {% for campo in formulario %}
        {% include "contas/_campo.html" with campo=campo %}
      {% endfor %}
      <button type="submit" class="btn btn-primary">Salvar</button>
    </form>
  </article>
{% endblock %}
```

- [ ] **Passo 8: Rodar e confirmar que os testes passam**

Run: `docker compose exec web pytest apps/bancas/tests/test_telas.py -v`
Expected: todos `PASSED`.

- [ ] **Passo 9: Rodar a suíte de `apps/bancas` inteira**

Run: `docker compose exec web pytest apps/bancas/ -v`
Expected: todos `PASSED`.

- [ ] **Passo 10: `ruff` e `black`, depois commit**

```bash
docker compose exec web ruff check .
docker compose exec web black .
git add apps/bancas/views.py apps/bancas/urls.py config/urls.py \
        templates/bancas/formulario.html templates/bancas/resultado.html \
        apps/bancas/tests/test_telas.py
git commit -m "Tarefa 8: telas de agendar/editar/cancelar/registrar resultado"
```

---

## Tarefa 9: Extensão de `/orientacoes/`

**Arquivos:**
- Criar: `apps/projetos/tests/test_orientacoes_bancas.py`.
- Modificar: `apps/bancas/services.py` (`anexar_banca_ativa`),
  `apps/projetos/views.py`, `apps/projetos/urls.py`,
  `templates/projetos/orientacoes.html`.

**Interfaces:**
- Consome: `orientandos_atuais` (Tarefa 5); `Banca`, `MembroBanca` (Tarefa 1).
- Produz: `apps.bancas.services.anexar_banca_ativa(projetos) -> list[Projeto]`
  (efeito colateral: cada `Projeto` ganha o atributo `.banca_ativa`, uma
  `Banca` não cancelada ou `None`); `views.reabrir_projeto_view`,
  `views.cancelar_projeto_view` em `apps/projetos`.

- [ ] **Passo 1: Escrever o teste de `anexar_banca_ativa` (falhando)**

Acrescente a `apps/bancas/tests/test_agendar.py` (reaproveitando as fixtures
`orientador`/`dois_professores`/`projeto_com_submissao` já definidas lá):

```python
from django.test.utils import CaptureQueriesContext
from django.db import connection


@pytest.mark.django_db
def test_anexar_banca_ativa_marca_none_sem_banca(projeto_com_submissao):
    from apps.bancas import services as bancas_services

    projetos = [projeto_com_submissao]
    bancas_services.anexar_banca_ativa(projetos)
    assert projetos[0].banca_ativa is None


@pytest.mark.django_db
def test_anexar_banca_ativa_encontra_a_nao_cancelada(
    projeto_com_submissao, orientador, dois_professores
):
    from apps.bancas import services as bancas_services

    banca = services.agendar_banca(
        projeto_com_submissao,
        data_hora=timezone.now(),
        local="Sala 1",
        membros=[{"professor": dois_professores[0]}, {"professor": dois_professores[1]}],
        por=orientador.usuario,
    )
    projetos = [projeto_com_submissao]
    bancas_services.anexar_banca_ativa(projetos)
    assert projetos[0].banca_ativa.pk == banca.pk


@pytest.mark.django_db
def test_anexar_banca_ativa_sem_query_extra_por_projeto(
    orientador, dois_professores
):
    from apps.bancas import services as bancas_services
    from apps.contas.models import PerfilAluno
    from apps.projetos.models import Submissao

    def _cria_projeto_com_banca(indice):
        aluno = Usuario.objects.create_user(
            email=f"aluno.anexar.{indice}@ufsm.br",
            password="x",
            nome_completo=f"Aluno Anexar {indice}",
            papel=Usuario.ALUNO,
            cpf=_cpf(10 + indice),
        )
        PerfilAluno.objects.create(usuario=aluno, matricula=f"2026ANEXAR{indice:02d}")
        projeto = Projeto.objects.create(
            aluno=aluno,
            orientador=orientador.usuario,
            etapa=Projeto.TCC_I,
            status=Projeto.EM_ANDAMENTO,
            ano=2026,
            periodo=1,
        )
        Submissao.objects.create(
            projeto=projeto, pdf=f"submissoes/{indice}.pdf", editavel=f"submissoes/{indice}.docx"
        )
        services.agendar_banca(
            projeto,
            data_hora=timezone.now(),
            local="Sala 1",
            membros=[{"professor": dois_professores[0]}, {"professor": dois_professores[1]}],
            por=orientador.usuario,
        )
        return projeto

    projetos = [_cria_projeto_com_banca(1)]
    with CaptureQueriesContext(connection) as captura:
        bancas_services.anexar_banca_ativa(projetos)
        for p in projetos:
            _ = p.banca_ativa.local if p.banca_ativa else None
    numero_com_um = len(captura.captured_queries)

    projetos = [_cria_projeto_com_banca(1), _cria_projeto_com_banca(2)]
    with CaptureQueriesContext(connection) as captura:
        bancas_services.anexar_banca_ativa(projetos)
        for p in projetos:
            _ = p.banca_ativa.local if p.banca_ativa else None
    assert len(captura.captured_queries) == numero_com_um
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `docker compose exec web pytest apps/bancas/tests/test_agendar.py -k anexar_banca_ativa -v`
Expected: `AttributeError` — `anexar_banca_ativa` não existe.

- [ ] **Passo 3: Escrever `anexar_banca_ativa` em `apps/bancas/services.py`**

```python
def anexar_banca_ativa(projetos):
    """Decora cada `Projeto` de `projetos` (lista já materializada, não
    queryset) com `.banca_ativa` — a `Banca` não cancelada desse projeto, ou
    `None` (Bloco D, spec §3.7/§7). UMA query para todos os projetos, não
    uma por projeto: mesma disciplina de N+1 de
    `apps.projetos.services.orientandos_atuais` (`select_related`) — aqui
    não dá pra usar `select_related`/`prefetch_related` na queryset de
    `Projeto` porque `Banca.projeto` é o lado FK inverso vindo de OUTRO
    app; a alternativa é este mapa construído com uma query só."""
    ids = [p.id for p in projetos]
    bancas_por_projeto = {
        banca.projeto_id: banca
        for banca in Banca.objects.filter(projeto_id__in=ids)
        .exclude(status=Banca.CANCELADA)
        .prefetch_related("membros__professor__usuario")
    }
    for projeto in projetos:
        projeto.banca_ativa = bancas_por_projeto.get(projeto.id)
    return projetos
```

- [ ] **Passo 4: Rodar e confirmar que os testes passam**

Run: `docker compose exec web pytest apps/bancas/tests/test_agendar.py -k anexar_banca_ativa -v`
Expected: todos `PASSED`.

- [ ] **Passo 5: Escrever o teste de `/orientacoes/` (falhando)**

Crie `apps/projetos/tests/test_orientacoes_bancas.py`:

```python
"""Testes de `/orientacoes/` mostrando as ações de cada estado do Bloco D
(spec §7): agendar (EM_ANDAMENTO com submissão), editar/cancelar/registrar
resultado (AGUARDANDO_DEFESA), reabrir/cancelar (REPROVADO)."""

import pytest

from apps.bancas import services as bancas_services
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto, Submissao
from django.utils import timezone


def _cpf(indice):
    base = f"{680000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.orientacoesbancas.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=_cpf(indice),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"ORIB{indice:03d}")


def _aluno(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"aluno.orientacoesbancas.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        papel=Usuario.ALUNO,
        cpf=_cpf(indice),
    )
    PerfilAluno.objects.create(usuario=usuario, matricula=f"2026ORIB{indice:03d}")
    return usuario


@pytest.mark.django_db
def test_orientacoes_mostra_agendar_banca_para_em_andamento_com_submissao(client):
    orientador = _professor(1, "Orientador Agendar Link")
    aluno = _aluno(2, "Aluno Agendar Link")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=2026,
        periodo=1,
    )
    Submissao.objects.create(projeto=projeto, pdf="submissoes/v1.pdf", editavel="submissoes/v1.docx")
    client.force_login(orientador.usuario)
    resposta = client.get("/orientacoes/")
    assert f"/bancas/agendar/{projeto.pk}/" in resposta.content.decode()


@pytest.mark.django_db
def test_orientacoes_mostra_acoes_de_aguardando_defesa(client):
    orientador = _professor(3, "Orientador Aguardando Link")
    aluno = _aluno(4, "Aluno Aguardando Link")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=2026,
        periodo=1,
    )
    Submissao.objects.create(projeto=projeto, pdf="submissoes/v1.pdf", editavel="submissoes/v1.docx")
    membro1 = _professor(5, "Membro Aguardando Um")
    membro2 = _professor(6, "Membro Aguardando Dois")
    from apps.bancas import services as banca_services

    banca = banca_services.agendar_banca(
        projeto,
        data_hora=timezone.now(),
        local="Sala 7",
        membros=[{"professor": membro1}, {"professor": membro2}],
        por=orientador.usuario,
    )
    client.force_login(orientador.usuario)
    conteudo = client.get("/orientacoes/").content.decode()
    assert f"/bancas/{banca.pk}/editar/" in conteudo
    assert f"/bancas/{banca.pk}/cancelar/" in conteudo
    assert f"/bancas/{banca.pk}/resultado/" in conteudo


@pytest.mark.django_db
def test_orientacoes_mostra_reabrir_e_cancelar_para_reprovado(client):
    orientador = _professor(7, "Orientador Reprovado Link")
    aluno = _aluno(8, "Aluno Reprovado Link")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.REPROVADO,
        ano=2026,
        periodo=1,
    )
    client.force_login(orientador.usuario)
    conteudo = client.get("/orientacoes/").content.decode()
    assert f"/orientacoes/{projeto.pk}/reabrir/" in conteudo
    assert f"/orientacoes/{projeto.pk}/cancelar/" in conteudo


@pytest.mark.django_db
def test_reabrir_projeto_view_redireciona(client):
    orientador = _professor(9, "Orientador Reabrir View")
    aluno = _aluno(10, "Aluno Reabrir View")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.REPROVADO,
        ano=2026,
        periodo=1,
    )
    client.force_login(orientador.usuario)
    resposta = client.post(f"/orientacoes/{projeto.pk}/reabrir/")
    assert resposta.status_code == 302
    projeto.refresh_from_db()
    assert projeto.status == Projeto.EM_ANDAMENTO


@pytest.mark.django_db
def test_cancelar_projeto_view_recusa_projeto_alheio_com_404(client):
    orientador = _professor(11, "Orientador Cancelar View")
    outro = _professor(12, "Outro Professor Cancelar View")
    aluno = _aluno(13, "Aluno Cancelar View")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.REPROVADO,
        ano=2026,
        periodo=1,
    )
    client.force_login(outro.usuario)
    resposta = client.post(f"/orientacoes/{projeto.pk}/cancelar/")
    assert resposta.status_code == 404
```

- [ ] **Passo 6: Rodar e confirmar que falha**

Run: `docker compose exec web pytest apps/projetos/tests/test_orientacoes_bancas.py -v`
Expected: falhas — nenhum link/rota novos existe ainda em `orientacoes.html`/`urls.py`.

- [ ] **Passo 7: Estender `apps/projetos/views.py::orientacoes`**

Localize a função `orientacoes` (ela já monta `orientandos = list(services.orientandos_atuais(professor))`,
ou equivalente — confira a linha exata antes de editar). Logo depois de
materializar a lista de orientandos em uma lista (adicione `list(...)` se a
view hoje passar a queryset direto ao template), acrescente:

```python
    from apps.bancas.services import anexar_banca_ativa

    orientandos = list(services.orientandos_atuais(professor))
    anexar_banca_ativa(orientandos)
```

(O `import` local, não no topo do arquivo, é deliberado: evita que
`apps/projetos/views.py` — o app mais antigo — dependa de `apps/bancas` — o
mais novo — no carregamento do módulo. Mesmo raciocínio de imports locais já
usado em `apps/projetos/tasks.py`.)

- [ ] **Passo 8: Acrescentar as duas views de projeto**

Em `apps/projetos/views.py`, junto às demais views simples de POST
(`desativar_tema` é o modelo a seguir):

```python
@login_required
@require_POST
def reabrir_projeto_view(request, projeto_id):
    """Reabre um `Projeto` `REPROVADO` — volta a `EM_ANDAMENTO` (Bloco D,
    spec §7). Lookup escopado ao orientador autenticado, mesmo padrão de
    `desativar_tema`: projeto alheio e inexistente respondem os dois com
    404."""
    projeto = get_object_or_404(Projeto, pk=projeto_id, orientador=request.user)
    services.reabrir_projeto(projeto, por=request.user)
    messages.success(request, "Projeto reaberto.")
    return redirect("projetos:orientacoes")


@login_required
@require_POST
def cancelar_projeto_view(request, projeto_id):
    """Cancela definitivamente um `Projeto` `REPROVADO` (Bloco D, spec §7).
    Mesmo padrão de lookup escopado de `reabrir_projeto_view`."""
    projeto = get_object_or_404(Projeto, pk=projeto_id, orientador=request.user)
    services.cancelar_projeto(projeto, por=request.user)
    messages.success(request, "Projeto cancelado.")
    return redirect("projetos:orientacoes")
```

(Confirme que `require_POST` e `get_object_or_404` já estão importados no
topo do arquivo — ambos já são usados por `desativar_tema`.)

- [ ] **Passo 9: Acrescentar as duas rotas a `apps/projetos/urls.py`**

```python
    path(
        "orientacoes/<int:projeto_id>/reabrir/",
        views.reabrir_projeto_view,
        name="reabrir_projeto",
    ),
    path(
        "orientacoes/<int:projeto_id>/cancelar/",
        views.cancelar_projeto_view,
        name="cancelar_projeto",
    ),
```

- [ ] **Passo 10: Estender `templates/projetos/orientacoes.html`**

Troque o `<li>` de cada orientando (dentro de `{% for projeto in orientandos %}`,
na seção "Orientandos atuais") de:

```html
            <li class="rounded-box border border-base-300 p-4">
              <p class="font-medium">{{ projeto.aluno.nome_completo }}</p>
              <p class="text-sm text-base-content/80">
                {{ projeto.get_etapa_display }}
                {% if projeto.tema %} — {{ projeto.tema.titulo }}{% endif %}
              </p>
              {% if projeto.submissao %}
                <p class="mt-1 text-sm">
                  <a href="{{ projeto.submissao.pdf.url }}" class="link">
                    Ver PDF enviado (versão {{ projeto.submissao.versao }})
                  </a>
                </p>
              {% else %}
                <p class="mt-1 text-sm text-base-content/70">Ainda não enviou o trabalho.</p>
              {% endif %}
            </li>
```

para:

```html
            <li class="rounded-box border border-base-300 p-4">
              <p class="font-medium">{{ projeto.aluno.nome_completo }}</p>
              <p class="text-sm text-base-content/80">
                {{ projeto.get_etapa_display }}
                {% if projeto.tema %} — {{ projeto.tema.titulo }}{% endif %}
              </p>

              {% comment %}
                Três ramos, nesta ordem (Bloco D, spec §7): EM_ANDAMENTO
                (com/sem submissão), banca AGENDADA, banca REALIZADA (só
                aparece aqui quando o projeto está REPROVADO — os outros
                dois resultados possíveis de uma banca REALIZADA,
                Aprovado com Ressalvas, já saem do filtro de
                `orientandos_atuais`, spec §3.7). `projeto.banca_ativa.status`
                é o proxy checado, não `projeto.status` diretamente — mesmo
                raciocínio já registrado em candidatura.html sobre preferir
                um campo mais específico a comparar a string de status.
              {% endcomment %}
              {% if projeto.submissao %}
                <p class="mt-1 text-sm">
                  <a href="{{ projeto.submissao.pdf.url }}" class="link">
                    Ver PDF enviado (versão {{ projeto.submissao.versao }})
                  </a>
                </p>
              {% endif %}

              {% if projeto.banca_ativa.status == "AGENDADA" %}
                <p class="mt-1 text-sm">
                  Banca agendada: {{ projeto.banca_ativa.data_hora }} — {{ projeto.banca_ativa.local }}
                </p>
                <p class="text-sm text-base-content/80">
                  Membros:
                  {% for membro in projeto.banca_ativa.membros.all %}
                    {% if membro.professor %}{{ membro.professor.usuario.nome_completo }}{% else %}{{ membro.nome_externo }} (externo){% endif %}{% if not forloop.last %}, {% endif %}
                  {% endfor %}
                </p>
                <div class="mt-2 flex flex-wrap items-center gap-2">
                  <a href="{% url 'bancas:editar' projeto.banca_ativa.pk %}" class="btn btn-outline btn-sm">Editar</a>
                  <form method="post" action="{% url 'bancas:cancelar' projeto.banca_ativa.pk %}">
                    {% csrf_token %}
                    <button type="submit" class="btn btn-outline btn-sm">Cancelar</button>
                  </form>
                  <a href="{% url 'bancas:resultado' projeto.banca_ativa.pk %}" class="btn btn-primary btn-sm">Registrar resultado</a>
                </div>
              {% elif projeto.banca_ativa %}
                <p class="mt-1 text-sm">
                  Resultado da banca: Reprovado — nota {{ projeto.banca_ativa.nota }}.
                  {{ projeto.banca_ativa.comentario }}
                </p>
                <div class="mt-2 flex flex-wrap items-center gap-2">
                  <form method="post" action="{% url 'projetos:reabrir_projeto' projeto.pk %}">
                    {% csrf_token %}
                    <button type="submit" class="btn btn-outline btn-sm">Reabrir projeto</button>
                  </form>
                  <form method="post" action="{% url 'projetos:cancelar_projeto' projeto.pk %}">
                    {% csrf_token %}
                    <button type="submit" class="btn btn-outline btn-sm">Cancelar definitivamente</button>
                  </form>
                </div>
              {% elif not projeto.submissao %}
                <p class="mt-1 text-sm text-base-content/70">Ainda não enviou o trabalho.</p>
              {% else %}
                <p class="mt-1 text-sm">
                  <a href="{% url 'bancas:agendar' projeto.pk %}" class="link">Agendar banca</a>
                </p>
              {% endif %}
            </li>
```

- [ ] **Passo 11: Rodar e confirmar que os testes passam**

Run: `docker compose exec web pytest apps/projetos/tests/test_orientacoes_bancas.py -v`
Expected: todos `PASSED`.

- [ ] **Passo 12: Rodar a suíte de `apps/projetos` inteira**

Run: `docker compose exec web pytest apps/projetos/ -v`
Expected: todos `PASSED` — nenhuma regressão em `test_fila_professor.py`
(que também renderiza `orientacoes.html`).

- [ ] **Passo 13: `ruff` e `black`, depois commit**

```bash
docker compose exec web ruff check .
docker compose exec web black .
git add apps/bancas/services.py apps/bancas/tests/test_agendar.py \
        apps/projetos/views.py apps/projetos/urls.py \
        templates/projetos/orientacoes.html \
        apps/projetos/tests/test_orientacoes_bancas.py
git commit -m "Tarefa 9: /orientacoes/ ganha as acoes do Bloco D por estado"
```

---

## Tarefa 10: Rotas transversais e suíte de acessibilidade completa

**Arquivos:**
- Modificar: `conftest.py`.

**Interfaces:**
- Consome: todas as telas das Tarefas 8 e 9.

- [ ] **Passo 1: Ler o final de `conftest.py` (a lista `ROTAS` e a última fábrica)**

Confira o formato exato antes de editar — `Rota(caminho, seletor,
fabrica_usuario, h1, persona=None)` (`conftest.py:164-208`). `caminho` já
aceita, além de uma string fixa, um CALLABLE que recebe o `Usuario` devolvido
por `fabrica_usuario` e retorna o caminho — mecanismo introduzido na rodada
de correção 2 da T6 para `/temas/<id>/editar/`
(`conftest.py:287-342`/`908`): a fábrica ANEXA o `pk` que a rota precisa
como atributo solto no próprio `Usuario` que ela retorna
(`usuario.tema_id_para_rota = tema.pk`), e o `caminho` da `Rota` é
`lambda usuario: f"/temas/{usuario.tema_id_para_rota}/editar/"`. Use
EXATAMENTE esse mecanismo — já existe, não precisa de nenhuma mudança em
`Rota` nem na fixture `rota`.

- [ ] **Passo 2: Acrescentar a fábrica para as três telas de `apps/bancas`**

```python
def cria_professor_com_banca_agendada_para_rotas():
    """Fábrica de `/bancas/agendar/<id>/`, `/bancas/<id>/editar/` e
    `/bancas/<id>/resultado/` (Bloco D): professor orientador com um
    `Projeto` `EM_ANDAMENTO` com `Submissao`, e uma `Banca` `AGENDADA` já
    criada sobre ele. Os dois `pk`s que as rotas precisam (`projeto.pk` para
    agendar, `banca.pk` para editar/resultado) são anexados ao `Usuario`
    devolvido — mesmo mecanismo de `usuario.tema_id_para_rota` em
    `cria_professor_com_tema_para_rotas` (T6): a fixture `rota` só recebe o
    que `fabrica_usuario()` retorna, então não há outro jeito de entregar um
    segundo `pk` a ela."""
    from apps.bancas.services import agendar_banca
    from apps.comum.semestre import semestre_vigente
    from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
    from apps.projetos.models import Projeto, Submissao

    orientador = Usuario.objects.create_user(
        email="professor-banca-das-rotas@ufsm.br",
        password="x",
        nome_completo="Professor Banca das Rotas",
        cpf=_gera_cpf_das_rotas(5),
    )
    PerfilProfessor.objects.create(usuario=orientador, siape="1000006")

    aluno = Usuario.objects.create_user(
        email="aluno-banca-das-rotas@ufsm.br",
        password="x",
        nome_completo="Aluno Banca das Rotas",
        cpf=_gera_cpf_das_rotas(6),
        papel=Usuario.ALUNO,
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026399905")

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
        projeto=projeto, pdf="submissoes/rota-banca.pdf", editavel="submissoes/rota-banca.docx"
    )

    membro1 = Usuario.objects.create_user(
        email="membro1-banca-das-rotas@ufsm.br",
        password="x",
        nome_completo="Membro Um Banca das Rotas",
        cpf=_gera_cpf_das_rotas(7),
    )
    perfil_membro1 = PerfilProfessor.objects.create(usuario=membro1, siape="1000007")

    banca = agendar_banca(
        projeto,
        data_hora=timezone.now() + timezone.timedelta(days=7),
        local="Sala das Rotas",
        membros=[{"professor": perfil_membro1}, {"nome_externo": "Externo das Rotas"}],
        por=orientador,
    )

    orientador.projeto_id_para_rota = projeto.pk
    orientador.banca_id_para_rota = banca.pk
    return orientador
```

- [ ] **Passo 3: Acrescentar as três `Rota` a `ROTAS`**

```python
    Rota(
        lambda usuario: f"/bancas/agendar/{usuario.projeto_id_para_rota}/",
        "form",
        fabrica_usuario=cria_professor_com_banca_agendada_para_rotas,
        h1="Agendar banca",
    ),
    Rota(
        lambda usuario: f"/bancas/{usuario.banca_id_para_rota}/editar/",
        "form",
        fabrica_usuario=cria_professor_com_banca_agendada_para_rotas,
        h1="Editar banca",
    ),
    Rota(
        lambda usuario: f"/bancas/{usuario.banca_id_para_rota}/resultado/",
        "form",
        fabrica_usuario=cria_professor_com_banca_agendada_para_rotas,
        h1="Registrar resultado",
    ),
```

Cada `Rota` chama `fabrica_usuario()` de novo (a fixture `rota` roda uma vez
por rota, isolada por transação) — sem estado global, sem lista mutável,
cada rodada tem seu próprio `Usuario` com seu próprio `projeto_id_para_rota`/
`banca_id_para_rota`.

- [ ] **Passo 4: Rodar as cinco suítes transversais completas**

`orientacoes.html` também mudou (Tarefa 9) — roda tudo, não filtrado:

Run: `docker compose exec web pytest tests/test_acessibilidade.py tests/test_toque.py tests/test_responsivo.py tests/test_teclado.py tests/test_rotas.py -v`
Expected: todos `PASSED`. Se `color-contrast` ou alvo de toque reprovarem em
algum elemento novo (botões "Editar"/"Cancelar"/"Registrar resultado" em
`orientacoes.html`, ou os campos de `formulario.html`/`resultado.html`),
ajuste a classe DaisyUI do elemento (mesmo tipo de correção feita no Bloco C,
Tarefa 4, para `text-base-content/60` → `/70`) e rode de novo até passar.

- [ ] **Passo 5: Rodar a suíte inteira**

Run: `docker compose exec web pytest`
Expected: todos `PASSED`.

- [ ] **Passo 6: `ruff` e `black`**

Run: `docker compose exec web ruff check .`
Run: `docker compose exec web black --check .`

- [ ] **Passo 7: Commit**

```bash
git add conftest.py
git commit -m "Tarefa 10: rotas transversais das telas do Bloco D"
```

---

## Ao concluir

Depois da Tarefa 10, verifique os 11 critérios de aceitação do spec (§11) um
a um, com evidência real — mesmo formato que a Tarefa 13 do Bloco B e o "Ao
concluir" do Bloco C usaram. Atualize `CLAUDE.md`: marque o Bloco D como
concluído (mesmo formato das entradas de A/B/C), remova a nota "nada disto
existe ainda" da regra 3 (Membros Externos de Banca), e ajuste a seção
"Ciclo de Vida e Status do TCC" para refletir que `Aguardando Defesa` →
`Aprovado com Ressalvas`/`Reprovado` já está implementado, e que `CANCELADO`
existe como um status adicional fora da lista original do `inicio.pdf`
(documentar essa divergência explicitamente, como as demais decisões
registradas). Depois, invoque `superpowers:finishing-a-development-branch`
para a branch deste bloco.
