# Bloco B — Mural de temas e alocação: Plano de Implementação

> **Para executores agênticos:** SUB-SKILL OBRIGATÓRIA: use
> `superpowers:subagent-driven-development` (recomendado) ou
> `superpowers:executing-plans` para implementar tarefa a tarefa. Os passos usam
> caixas de seleção (`- [ ]`) para acompanhamento.

**Objetivo:** ligar alunos a orientadores — o aluno registra até três opções, um professor
aceita, e nasce o `Projeto` de TCC I que o Bloco C conduzirá até a defesa.

**Arquitetura:** app `apps/projetos`, seguindo o padrão que o Bloco A firmou — regra de
negócio em `services.py`, permissões em `permissions.py`, envio assíncrono em `tasks.py`,
modelos só com estrutura. A alocação é contínua, com cascata de três opções e prazo
avançado por tarefa periódica do Celery.

**Stack:** Python 3.12, Django 5.1, PostgreSQL 16, Celery 5 (worker + beat), Redis,
Tailwind v4 + DaisyUI 5, HTMX, Alpine.js, pytest, Playwright, axe-core.

**Spec:** `docs/superpowers/specs/2026-09-10-mural-e-alocacao-design.md`

## Restrições globais

- **Idioma:** todo identificador em português. Interface, mensagens de erro, comentários e
  commits também.
- **Camada de serviço:** nenhuma regra de negócio em `views.py` ou `models.py`. Serviços
  que mudam estado usam `@transaction.atomic`.
- **Acessibilidade WCAG 2.1 AA:** rótulos associados, erros anunciáveis, alvos de toque
  ≥44×44px medidos a **360px e 1280px**, sem rolagem horizontal a 360px.
- **Rotas autenticadas** entram na suíte com **âncora de identidade**: URL e texto do
  `<h1>` confirmados **antes** de qualquer outra asserção.
- **Sem CDN.** Tudo servido do próprio projeto.
- **Comandos rodam no container:** `docker compose exec web <comando>`.
- **Commits com caminhos explícitos**, nunca `git add -A`.
- **`filterwarnings` em modo `error`**, com exceções apenas para `botocore` e `kombu`. Não
  acrescente exceções; reporte.

## Constantes do bloco

| constante | valor | onde |
|---|---|---|
| `LIMITE_PADRAO_VAGAS` | `3` | `apps/projetos/services.py` |
| `PRAZO_RESPOSTA_DIAS` | `7` | `config/settings.py` |
| `MES_INICIO_PERIODO_2` | `8` | `config/settings.py` |

## Uma calibragem deliberada deste plano

As Tarefas 1 a 5, 8, 10 e 13 trazem código e testes literais, porque contêm lógica nova ou
sutil. As Tarefas 6, 7, 9, 11 e 12 são telas CRUD sobre padrões que o Bloco A já firmou, e
para elas o plano descreve **o que cobrir** e aponta o arquivo de referência, em vez de
inventar markup.

Isso é decisão, não economia. Na Fase 1, boa parte do código literal do plano estava errado
— classes do DaisyUI 4 sobre o v5, um raciocínio de travamento que a reprodução derrubou,
duas afirmações sobre o que o axe detecta — e os implementadores tiveram de corrigir de
qualquer forma. O que mais valeu foram o contexto e os avisos, não o código. Onde existe
padrão validado no repositório, apontar para ele é mais confiável do que reescrevê-lo aqui.

## Mapa de arquivos

| arquivo | responsabilidade | tarefa |
|---|---|---|
| `conftest.py` | rotas com fábrica de usuário opcional | T1 |
| `templates/contas/_campo.html` | renderização de campo, hoje copiada seis vezes | T2 |
| `tests/test_arquitetura.py` | fechar as duas pendências da Fase 1 | T2 |
| `apps/comum/semestre.py` | `semestre_vigente()` | T3 |
| `apps/projetos/models.py` | `Tema`, `Projeto`, `LimiteOrientacao`, `Candidatura`, `OpcaoCandidatura` | T3, T4 |
| `apps/projetos/services.py` | toda a regra de negócio do bloco | T5, T6, T8, T9, T12 |
| `apps/projetos/permissions.py` | verificações de permissão | T6 |
| `apps/projetos/tasks.py` | três e-mails + a tarefa periódica do prazo | T8, T10 |
| `apps/projetos/views.py`, `urls.py`, `forms.py` | as cinco telas | T6-T12 |

---

## Tarefa 1: Generalizar a suíte de acessibilidade para rotas autenticadas

**Pré-requisito herdado da Fase 1 (spec §8.1).** Vem primeiro porque cinco telas novas
fariam mais cinco cópias da suíte.

**Arquivos:**
- Modificar: `conftest.py`
- Modificar: `tests/test_acessibilidade.py`, `tests/test_toque.py`, `tests/test_responsivo.py`, `tests/test_teclado.py`, `tests/test_rotas.py`
- Modificar: `apps/contas/tests/test_perfil_acessibilidade.py`, `apps/contas/tests/test_coordenacao_acessibilidade.py`

**Interfaces:**
- Consome: `ROTAS`, `SELETOR_POR_ROTA`, `autentica_no_navegador` do `conftest.py`.
- Produz: `ROTAS` como lista de objetos `Rota(caminho, seletor, fabrica_usuario=None, h1=None)`;
  a fixture `rota` autentica quando `fabrica_usuario` existe.

- [ ] **Passo 1: Escrever o teste que prova a generalização (falhando)**

Acrescentar a `tests/test_rotas.py`:

```python
def test_rota_autenticada_e_medida_autenticada(page, live_server, db):
    """Uma rota com fábrica de usuário não pode acabar medindo a tela de login.

    Este projeto já teve duas vezes o defeito de a suíte passar medindo a página
    errada. A âncora de identidade é o que impede a terceira.
    """
    from conftest import ROTAS

    autenticadas = [r for r in ROTAS if r.fabrica_usuario is not None]
    assert autenticadas, "nenhuma rota autenticada registrada — a generalização não fez efeito"
    for rota in autenticadas:
        assert rota.h1, f"{rota.caminho} não declara o <h1> esperado (âncora de identidade)"
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Executar: `docker compose exec web pytest tests/test_rotas.py -v`
Esperado: FALHA com `AttributeError` — `ROTAS` ainda é lista de strings.

- [ ] **Passo 3: Reescrever `ROTAS` no `conftest.py`**

```python
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class Rota:
    """Uma rota submetida às quatro verificações transversais.

    `fabrica_usuario` é o que permite cobrir tela autenticada sem duplicar a suíte:
    quando presente, a fixture `rota` autentica no navegador antes de medir. `h1` é a
    âncora de identidade — sem ela, uma rota quebrada passa medindo a tela de login,
    defeito que este projeto já teve duas vezes.
    """

    caminho: str
    seletor: str
    fabrica_usuario: Optional[Callable] = None
    h1: Optional[str] = None


ROTAS = [
    Rota("/", "h1"),
    Rota("/convite/rota-para-teste-de-acessibilidade/", "form"),
    Rota("/contas/login/", "form"),
    Rota("/contas/password_reset/", "form"),
    Rota("/contas/password_reset/concluido/", "h1"),
    Rota("/contas/reset/concluido/", "h1"),
]
```

E a fixture `rota` passa a autenticar e a conferir a âncora:

```python
@pytest.fixture(params=ROTAS, ids=lambda r: r.caminho)
def rota(request, convite_das_rotas, page, live_server, autentica_no_navegador):
    """Devolve a rota já aberta no navegador, autenticada quando ela exige."""
    r = request.param
    if r.fabrica_usuario is not None:
        autentica_no_navegador(r.fabrica_usuario())
    page.goto(f"{live_server.url}{r.caminho}")
    if r.h1:
        texto = page.inner_text("h1")
        assert r.h1 in texto, (
            f"{r.caminho} deveria mostrar <h1> com {r.h1!r}, e mostrou {texto!r}. "
            "A suíte pode estar medindo a página errada."
        )
    return r
```

- [ ] **Passo 4: Migrar as quatro suítes transversais**

Cada uma passa a receber `rota` já aberta, em vez de fazer o próprio `goto`. Exemplo em
`tests/test_acessibilidade.py`:

```python
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("largura", LARGURAS_TESTADAS)
def test_pagina_nao_viola_wcag(page, rota, largura):
    page.set_viewport_size({"width": largura, "height": 800})
    page.reload()
    resultados = Axe().run(page, options=REGRAS_AXE)
    assert resultados.violations_count == 0, (
        f"{rota.caminho} a {largura}px viola {resultados.violations_count} regra(s):\n"
        f"{resultados.generate_report()}"
    )
```

**Não altere** o conjunto de tags do axe, o limiar de 44px, a tolerância de rolagem, a
isenção de link inline em prosa, nem a asserção `violations_count == 0`. Esta tarefa move
código; não afrouxa nada.

- [ ] **Passo 5: Substituir as duas suítes duplicadas por entradas em `ROTAS`**

`apps/contas/tests/test_perfil_acessibilidade.py` e `test_coordenacao_acessibilidade.py`
têm, cada um, cópias dos cinco corpos de teste. Substitua por duas entradas:

```python
# em conftest.py, junto das demais
Rota("/perfil/", "form", fabrica_usuario=cria_professor_para_rotas, h1="Meu perfil"),
Rota("/painel/", "form", fabrica_usuario=cria_coordenador_para_rotas, h1="Painel da coordenação"),
```

com as fábricas definidas no `conftest.py`. Defina **três**, porque as tarefas seguintes
precisam das três: `cria_professor_para_rotas` (professor com `PerfilProfessor` e ao menos
uma área), `cria_coordenador_para_rotas` (professor com `is_coordenador=True`) e
`cria_aluno_para_rotas` (aluno com `PerfilAluno`). Cada uma devolve um `Usuario` salvo, com
CPF e e-mail próprios para não colidir com as fixtures de `apps/contas/tests/`. Apague os corpos duplicados; **preserve** os testes específicos daquelas telas
que não são cópia (por exemplo, o que afirma o `<legend>` do grupo de áreas).

- [ ] **Passo 6: Rodar a suíte inteira**

Executar: `docker compose exec web pytest`
Esperado: PASSA. A contagem muda (as cópias saem, a parametrização entra); registre a nova.

- [ ] **Passo 7: Provar que a âncora pega**

Quebre de propósito: mude o `h1` esperado de `/perfil/` para um texto errado e confirme que
a suíte **reprova** nomeando a rota. Desfaça. Registre a saída no relatório.

- [ ] **Passo 8: Commit**

```bash
git add conftest.py tests/ apps/contas/tests/
git commit -m "Generaliza a suite de acessibilidade para rotas autenticadas"
```

---

## Tarefa 2: Extrair `_campo.html` e fechar as pendências do teste de arquitetura

**Pré-requisito herdado da Fase 1 (spec §8.2).**

**Arquivos:**
- Criar: `templates/contas/_campo.html`
- Modificar: `templates/contas/aceitar_convite.html`, `templates/contas/perfil.html`, `templates/contas/painel_coordenacao.html`, `templates/registration/login.html`, `templates/registration/password_reset_form.html`, `templates/registration/password_reset_confirm.html`
- Modificar: `tests/test_arquitetura.py`

**Interfaces:**
- Produz: o parcial `contas/_campo.html`, que recebe `campo` no contexto e renderiza
  rótulo, controle, ajuda e erros com a ligação de acessibilidade já correta.

- [ ] **Passo 1: Escrever os testes que faltam no teste de arquitetura (falhando)**

```python
MUTACOES = ("save", "create", "update", "delete", "set", "add", "remove", "clear")


def test_views_nao_mutam_models_direto(app):
    """A camada de serviço só se sustenta se um teste a defender.

    `set`/`add`/`remove`/`clear` entram na lista porque a gravação de M2M
    (`perfil.areas.set(...)`) é mutação como qualquer outra, e era o caso concreto
    que escapava da versão anterior desta regra.
    """


def test_o_arquivo_de_views_existe(app):
    """Falha alto se `views.py` sumir — a versão anterior pulava em silêncio, e um
    pacote `views/` no lugar do módulo desativaria a regra sem ninguém notar."""
```

Escreva as duas com o corpo real, usando `ast` como o teste já faz, e cobrindo tanto
`views.py` quanto o pacote `views/` (se existir, percorre os módulos dentro).

- [ ] **Passo 2: Rodar e confirmar que falha**

Executar: `docker compose exec web pytest tests/test_arquitetura.py -v`
Esperado: FALHA — `MUTACOES` ainda não tem os quatro verbos de M2M.

- [ ] **Passo 3: Implementar as duas regras**

- [ ] **Passo 4: Criar o parcial**

`templates/contas/_campo.html`, extraído de `aceitar_convite.html` (a versão que passou
pela suíte), incluindo o `aria-describedby`, o `aria-invalid` e o tratamento de grupo com
`<fieldset>`/`<legend>` quando o campo é de múltipla escolha.

- [ ] **Passo 5: Migrar os seis templates**

Substituir cada bloco por `{% include "contas/_campo.html" with campo=campo %}`.
**Cuidado:** `perfil.html` e `painel_coordenacao.html` usam `{% if formulario.errors %}` no
resumo de erros; `password_reset_form.html` e `password_reset_confirm.html` também, depois
da correção da onda final. Não reintroduza `non_field_errors` — foi um defeito real.

- [ ] **Passo 6: Rodar a suíte inteira**

Executar: `docker compose exec web pytest`
Esperado: PASSA, sem mudança de contagem — esta tarefa não acrescenta comportamento.

- [ ] **Passo 7: Commit**

```bash
git add templates/ tests/test_arquitetura.py
git commit -m "Extrai o parcial de campo e fecha as pendencias do teste de arquitetura"
```

---

## Tarefa 3: Semestre, `Tema`, `Projeto` e `LimiteOrientacao`

**Arquivos:**
- Criar: `apps/comum/semestre.py`, `apps/comum/tests/test_semestre.py`
- Criar: `apps/projetos/models.py`, `apps/projetos/admin.py`, `apps/projetos/tests/__init__.py`, `apps/projetos/tests/test_modelos.py`
- Modificar: `config/settings.py`

**Interfaces:**
- Produz: `apps.comum.semestre.semestre_vigente(data=None) -> (int, int)`;
  `apps.projetos.models.Tema`, `Projeto` (com `Projeto.TCC_I`, `TCC_II`, `EM_ANDAMENTO`),
  `LimiteOrientacao`.

- [ ] **Passo 1: Escrever os testes (falhando)**

```python
import datetime
import pytest
from apps.comum.semestre import semestre_vigente


@pytest.mark.parametrize(
    "data, esperado",
    [
        (datetime.date(2026, 1, 15), (2026, 1)),
        (datetime.date(2026, 7, 31), (2026, 1)),
        (datetime.date(2026, 8, 1), (2026, 2)),
        (datetime.date(2026, 12, 31), (2026, 2)),
    ],
)
def test_semestre_vigente_usa_o_mes_de_corte(data, esperado):
    assert semestre_vigente(data) == esperado


def test_mes_de_corte_e_configuravel(settings):
    """O calendário acadêmico não acompanha o civil: greve e reposição deslocam a
    virada, e ajustar uma constante precisa bastar."""
    settings.MES_INICIO_PERIODO_2 = 9
    assert semestre_vigente(datetime.date(2026, 8, 15)) == (2026, 1)
```

Mais testes de modelo em `apps/projetos/tests/test_modelos.py` cobrindo: `Tema` exige
professor e área; `Projeto` recusa dois ativos do mesmo aluno na mesma etapa
(`IntegrityError` dentro de `transaction.atomic`); `LimiteOrientacao` recusa `limite` igual
ou menor que 3 e recusa duplicata de `(professor, etapa, ano, periodo)`.

- [ ] **Passo 2: Rodar e confirmar que falha**

Executar: `docker compose exec web pytest apps/comum/tests/test_semestre.py apps/projetos/ -v`
Esperado: FALHA com `ModuleNotFoundError`.

- [ ] **Passo 3: Escrever `apps/comum/semestre.py`**

```python
from django.conf import settings
from django.utils import timezone


def semestre_vigente(data=None):
    """Devolve `(ano, periodo)` do semestre letivo corrente.

    O mês de corte é configurável de propósito: calendário acadêmico não acompanha o
    civil, e num ano deslocado por greve ou reposição a virada precisa poder ser
    ajustada por constante, sem migração. O semestre GRAVADO nos registros é
    congelado em dois inteiros — ajustar o corte não muda o histórico.
    """
    data = data or timezone.localdate()
    periodo = 1 if data.month < settings.MES_INICIO_PERIODO_2 else 2
    return data.year, periodo
```

Em `config/settings.py`, junto das demais constantes do projeto:

```python
MES_INICIO_PERIODO_2 = 8
PRAZO_RESPOSTA_DIAS = 7
```

- [ ] **Passo 4: Escrever os três modelos**

`apps/projetos/models.py` com `Tema`, `Projeto` e `LimiteOrientacao` exatamente como o spec
§4 descreve, incluindo as travas: `UniqueConstraint` condicional de projeto ativo por aluno
e etapa; `UniqueConstraint(professor, etapa, ano, periodo)` no limite; `CheckConstraint`
`limite > 3`.

Comentários explicando o porquê: por que o carimbo é `ano`+`periodo` e não texto, e por que
a `CheckConstraint` do limite é maior que 3 (o modelo existe para autorizar **exceção para
cima**; restringir para baixo seria outra funcionalidade).

- [ ] **Passo 5: Migrar e rodar**

```bash
docker compose exec web python manage.py makemigrations projetos
docker compose exec web python manage.py migrate
docker compose exec web pytest apps/comum/ apps/projetos/ -v
```

- [ ] **Passo 6: Commit**

```bash
git add apps/comum/ apps/projetos/ config/settings.py
git commit -m "Adiciona o calculo do semestre e os modelos de tema, projeto e limite"
```

---

## Tarefa 4: `Candidatura` e `OpcaoCandidatura`

**Arquivos:**
- Modificar: `apps/projetos/models.py`, `apps/projetos/admin.py`
- Teste: `apps/projetos/tests/test_modelos.py`

**Interfaces:**
- Consome: `Tema` da T3.
- Produz: `Candidatura` (com `EM_CURSO`, `ACEITA`, `ESGOTADA`, `CANCELADA`) e
  `OpcaoCandidatura` (com `AGUARDANDO`, `ENVIADA`, `ACEITA`, `RECUSADA`, `EXPIRADA`,
  `CANCELADA`).

- [ ] **Passo 1: Escrever os testes (falhando)**

Cobrindo: uma candidatura `EM_CURSO` por aluno (`IntegrityError` na segunda); `ordem` única
por candidatura; `ordem` fora de 1..3 recusada; opção com tema de outro professor recusada.

- [ ] **Passo 2: Rodar e confirmar que falha**

- [ ] **Passo 3: Escrever os dois modelos** conforme o spec §4.2 e §4.3.

- [ ] **Passo 4: Migrar, rodar, commitar**

---

## Tarefa 5: A regra das vagas e a prova de concorrência

**Esta tarefa vem antes de qualquer tela de aceite, por exigência do spec §9.** O
travamento será provado, não afirmado.

**Arquivos:**
- Criar: `apps/projetos/services.py`, `apps/projetos/tests/test_vagas.py`, `apps/projetos/tests/test_concorrencia.py`

**Interfaces:**
- Produz:
  - `LIMITE_PADRAO_VAGAS = 3`
  - `vagas_ocupadas(professor, etapa, ano, periodo) -> int`
  - `limite_do_professor(professor, etapa, ano, periodo) -> int`
  - `criar_projeto_sob_limite(aluno, professor, tema, etapa) -> Projeto`

- [ ] **Passo 1: Escrever os testes de vaga (falhando)**

Cobrindo: contagem só do semestre vigente (um projeto de semestre anterior **não** conta —
é a decisão 3.5 do spec, com o custo aceito); limite padrão 3; limite elevado respeitado;
limite revogado não desfaz projetos existentes mas trava o próximo.

- [ ] **Passo 2: Escrever o teste de concorrência (falhando)**

```python
def test_duas_aceitacoes_simultaneas_no_ultimo_lugar_resultam_em_uma_recusa():
    """Aceitar é um INSERT, não um UPDATE — travar os Projeto existentes não impede
    outra transação de inserir mais um (leitura fantasma). O travamento é na linha do
    professor, que é o recurso disputado. Este teste prova isso com threads e conexões
    reais; sem ele, a garantia seria só uma frase no comentário — que foi exatamente
    como a Fase 1 descobriu que o raciocínio do spec estava errado.
    """
```

Use threads reais e conexões separadas, com a sobreposição forçada (não dependente do
escalonador), no padrão de `apps/contas/tests/test_coordenacao_concorrencia.py`.

- [ ] **Passo 3: Rodar e confirmar que ambos falham**

- [ ] **Passo 4: Implementar**

```python
LIMITE_PADRAO_VAGAS = 3


def vagas_ocupadas(professor, etapa, ano, periodo):
    return Projeto.objects.filter(
        orientador=professor.usuario, etapa=etapa, ano=ano, periodo=periodo
    ).count()


def limite_do_professor(professor, etapa, ano, periodo):
    """3, salvo autorização expressa da coordenação para este semestre e etapa."""
    autorizado = LimiteOrientacao.objects.filter(
        professor=professor, etapa=etapa, ano=ano, periodo=periodo
    ).values_list("limite", flat=True).first()
    return autorizado or LIMITE_PADRAO_VAGAS


@transaction.atomic
def criar_projeto_sob_limite(aluno, professor, tema, etapa):
    """Cria o projeto sob a trava da linha do professor.

    O travamento é DIFERENTE do usado no teto de coordenadores (apps/contas). Lá,
    promover é um UPDATE de linha existente, e travar um conjunto que já a contém
    serializa as transações. Aqui, aceitar é um INSERT: travar os Projeto existentes
    não impede outra transação de inserir mais um — a linha nem existe para ser
    travada. Por isso travamos a linha do professor, que é o recurso disputado.

    As duas leituras (contagem e limite) acontecem DEPOIS do bloqueio; se o limite
    fosse lido antes, duas transações concorrentes poderiam usar valores diferentes.
    """
    professor = PerfilProfessor.objects.select_for_update().get(pk=professor.pk)
    ano, periodo = semestre_vigente()
    ocupadas = vagas_ocupadas(professor, etapa, ano, periodo)
    limite = limite_do_professor(professor, etapa, ano, periodo)
    if ocupadas >= limite:
        raise ValidationError(
            f"{professor.usuario.nome_completo} já tem {ocupadas} de {limite} vagas "
            f"ocupadas em {etapa} neste semestre. Peça à coordenação para elevar o "
            "limite, ou escolha outro orientador."
        )
    return Projeto.objects.create(
        aluno=aluno.usuario, orientador=professor.usuario, tema=tema,
        etapa=etapa, status=Projeto.EM_ANDAMENTO, ano=ano, periodo=periodo,
    )
```

- [ ] **Passo 5: Rodar os dois arquivos e a suíte inteira**

- [ ] **Passo 6: Provar que o teste de concorrência discrimina**

Troque o `select_for_update` da linha do professor por um `select_for_update` sobre os
`Projeto` existentes — o travamento errado — e confirme que o teste **reprova** com dois
projetos criados. Desfaça. Registre a saída no relatório: sem isso, o teste não foi visto
falhando e não vale como regressão.

- [ ] **Passo 7: Commit**

---

## Tarefa 6: Temas — serviços, permissões e painel do professor

**Arquivos:**
- Criar: `apps/projetos/permissions.py`, `apps/projetos/forms.py`, `apps/projetos/views.py`, `apps/projetos/urls.py`, `templates/projetos/meus_temas.html`
- Modificar: `apps/projetos/services.py`, `config/urls.py`, `conftest.py`
- Teste: `apps/projetos/tests/test_temas.py`

**Interfaces:**
- Produz: `criar_tema(professor, area, titulo, descricao, por) -> Tema`;
  `desativar_tema(tema, por)`; `pode_criar_tema(usuario)`; rota nomeada `projetos:meus_temas`.

- [ ] **Passo 1: Escrever os testes (falhando)**

Cobrindo: professor cria tema numa área que declarou; tema fora das áreas dele é recusado
com mensagem nomeando a área; aluno não cria tema (`PermissionDenied`); desativar tira do
mural e preserva as candidaturas que o referenciam.

- [ ] **Passo 2: Rodar e confirmar que falha**

- [ ] **Passo 3: Implementar serviços e permissões**

- [ ] **Passo 4: Escrever a tela**

`/temas/meus/`, seguindo `templates/contas/perfil.html` como referência e usando o parcial
`contas/_campo.html` da T2. **Não copie markup do DaisyUI 4** — as classes `.label`,
`.label-text` e `.form-control` não valem no v5 instalado.

- [ ] **Passo 5: Acrescentar a rota à suíte**

```python
Rota("/temas/meus/", "form", fabrica_usuario=cria_professor_para_rotas, h1="Meus temas"),
```

- [ ] **Passo 6: Rodar a suíte inteira**

Se a suíte de acessibilidade reprovar a tela nova, **o defeito é da tela**. Não afrouxe
asserção, não reduza regras do axe, não exclua seletor. Se concluir que é falso positivo,
reporte com o raciocínio.

- [ ] **Passo 7: Commit**

---

## Tarefa 7: O mural de temas

**Arquivos:**
- Criar: `templates/projetos/mural.html`
- Modificar: `apps/projetos/views.py`, `apps/projetos/urls.py`, `apps/projetos/services.py`, `conftest.py`
- Teste: `apps/projetos/tests/test_mural.py`

**Interfaces:**
- Consome: `Tema` (T3), `vagas_ocupadas`/`limite_do_professor` (T5).
- Produz: rota nomeada `projetos:mural`; `temas_do_mural(area=None) -> QuerySet`.

- [ ] **Passo 1: Escrever os testes (falhando)**

Cobrindo: o mural exige autenticação (anônimo é redirecionado); mostra apenas temas
`ativo=True`; filtra por área; **marca quais professores ainda têm vaga** — que é o que
torna a escolha informada antes da recusa da T8.

- [ ] **Passo 2: Rodar e confirmar que falha**
- [ ] **Passo 3: Implementar o serviço e a view**
- [ ] **Passo 4: Escrever a tela**, seguindo `templates/contas/perfil.html` e usando o parcial `contas/_campo.html`. **Não copie markup do DaisyUI 4.**
- [ ] **Passo 5: Acrescentar a rota à suíte**

A rota do mural é autenticada mas serve a qualquer papel; registre-a com a fábrica de aluno:

```python
Rota("/temas/", "h1", fabrica_usuario=cria_aluno_para_rotas, h1="Mural de temas"),
```

---

## Tarefa 8: Registrar candidatura e a cascata

**Arquivos:**
- Modificar: `apps/projetos/services.py`, `apps/projetos/forms.py`
- Criar: `apps/projetos/tasks.py`, `templates/email/manifestacao_interesse.txt`, `templates/email/candidatura_recusada.txt`, `templates/email/candidatura_esgotada.txt`
- Teste: `apps/projetos/tests/test_candidatura.py`

**Interfaces:**
- Consome: `criar_projeto_sob_limite` (T5), `vagas_ocupadas`/`limite_do_professor` (T5).
- Produz: `registrar_candidatura(aluno, opcoes) -> Candidatura` (onde `opcoes` é lista
  ordenada de `(professor, tema_ou_None)`); `avancar_cascata(candidatura)`;
  `cancelar_candidatura(candidatura, por)`; tarefas `enviar_manifestacao(opcao_id)`,
  `enviar_recusa(opcao_id)`, `enviar_esgotamento(candidatura_id)`.

- [ ] **Passo 1: Escrever os testes (falhando)**

Cobrindo, no mínimo:
- registrar com três opções envia e-mail **só** para a primeira;
- registrar com professor já no limite é **recusado**, nomeando o professor (spec §5.1);
- registrar com um aluno que já tem candidatura `EM_CURSO` é recusado;
- `avancar_cascata` marca a atual como `EXPIRADA` e envia a próxima;
- esgotadas as três, a candidatura fica `ESGOTADA` **e a coordenação é notificada**;
- cancelar candidatura marca as opções restantes como `CANCELADA`.

Os testes de e-mail usam `django_capture_on_commit_callbacks`, como em `apps/contas` — o
`transaction.on_commit` não dispara sozinho sob pytest-django, e o serviço está certo.

- [ ] **Passo 2: Rodar e confirmar que falha**
- [ ] **Passo 3: Implementar os serviços da cascata**
- [ ] **Passo 4: Escrever as três tarefas Celery e os três templates de e-mail**
- [ ] **Passo 5: Rodar a suíte inteira**
- [ ] **Passo 6: Provar por mutação que o teste da recusa por limite discrimina** — remova a checagem de vaga do `registrar_candidatura`, confirme que o teste reprova, e desfaça. Registre a saída.
- [ ] **Passo 7: Commit**

---

## Tarefa 9: A fila do professor — aceitar e recusar

**Arquivos:**
- Modificar: `apps/projetos/services.py`, `apps/projetos/views.py`, `apps/projetos/urls.py`, `apps/projetos/permissions.py`, `conftest.py`
- Criar: `templates/projetos/orientacoes.html`
- Teste: `apps/projetos/tests/test_fila_professor.py`

**Interfaces:**
- Consome: `criar_projeto_sob_limite` (T5), `avancar_cascata` (T8).
- Produz: `aceitar_opcao(opcao, por) -> Projeto`; `recusar_opcao(opcao, por, justificativa)`;
  `pode_responder_opcao(usuario, opcao)`; rota `projetos:orientacoes`.

- [ ] **Passo 1: Escrever os testes (falhando)**

Cobrindo: aceitar cria `Projeto` e marca as demais opções como `CANCELADA`; **aceitar
revalida a vaga dentro da transação** (o e-mail pode ter dias); recusar exige justificativa
não vazia; recusar avança a cascata; responder opção já respondida é recusado; responder
opção de outro professor devolve 403; aceitar depois de o aluno cancelar é recusado.

- [ ] **Passo 2: Rodar e confirmar que falha**
- [ ] **Passo 3: Implementar `aceitar_opcao`, `recusar_opcao` e a permissão**
- [ ] **Passo 4: Escrever a tela** — formulários POST com CSRF, **não links GET**: são ações que mudam estado.
- [ ] **Passo 5: Acrescentar a rota à suíte** com âncora de identidade
- [ ] **Passo 6: Rodar a suíte inteira.** Se a suíte reprovar a tela, o defeito é da tela.
- [ ] **Passo 7: Commit**

---

## Tarefa 10: A tarefa periódica do prazo e o `celery_beat`

**Arquivos:**
- Modificar: `apps/projetos/tasks.py`, `config/settings.py`, `docker-compose.yml`
- Teste: `apps/projetos/tests/test_prazo.py`

**Interfaces:**
- Consome: `avancar_cascata` (T8).
- Produz: tarefa `avancar_candidaturas_vencidas()`; serviço `celery_beat` no compose.

- [ ] **Passo 1: Escrever os testes (falhando)**

```python
def test_opcao_vencida_avanca(...):
    """Manipula `prazo` diretamente, sem sleep e sem depender do relógio."""


def test_opcao_no_prazo_nao_avanca(...):
    ...
```

- [ ] **Passo 2: Rodar e confirmar que falha**

- [ ] **Passo 3: Implementar a tarefa e o agendamento**

```python
CELERY_BEAT_SCHEDULE = {
    "avancar-candidaturas-vencidas": {
        "task": "apps.projetos.tasks.avancar_candidaturas_vencidas",
        "schedule": crontab(minute=0),  # de hora em hora
    }
}
```

Agendamento **estático**, sem `django-celery-beat`: a dependência só se paga quando alguém
precisa mudar a periodicidade pela interface, e ninguém precisa.

- [ ] **Passo 4: Acrescentar o serviço ao compose**

```yaml
  celery_beat:
    build:
      context: .
      target: dev
    command: celery -A config beat --loglevel=info
    volumes:
      - .:/app
    env_file:
      - .env
    depends_on:
      db: {condition: service_healthy}
      redis: {condition: service_healthy}
```

- [ ] **Passo 5: Verificar o agendador de verdade**

```bash
docker compose up -d --build
docker compose logs --tail=20 celery_beat
```

Esperado: o log mostra o agendador ativo e a tarefa registrada. Este passo é o ponto da
tarefa: o teste unitário prova a lógica, não que o `beat` está de pé.

- [ ] **Passo 6: Commit**

---

## Tarefa 11: A tela do aluno

**Arquivos:**
- Criar: `templates/projetos/candidatura.html`
- Modificar: `apps/projetos/views.py`, `apps/projetos/urls.py`, `apps/projetos/forms.py`, `conftest.py`
- Teste: `apps/projetos/tests/test_tela_candidatura.py`

**Interfaces:**
- Consome: `registrar_candidatura`, `cancelar_candidatura` (T8).
- Produz: rota `projetos:candidatura`.

- [ ] **Passo 1: Escrever os testes (falhando)**

Cobrindo: o aluno monta a candidatura escolhendo até três alvos em ordem; a tela mostra em
qual opção a cascata está e **a justificativa das recusas já recebidas**; cancelar funciona;
professor não acessa a tela do aluno.

- [ ] **Passo 2: Rodar e confirmar que falha**
- [ ] **Passo 3: Implementar os serviços e as permissões**
- [ ] **Passo 4: Escrever a tela**, com o parcial `contas/_campo.html` e formulários POST com CSRF
- [ ] **Passo 5: Acrescentar a rota à suíte** com âncora de identidade
- [ ] **Passo 6: Rodar a suíte inteira.** Se a suíte reprovar a tela, o defeito é da tela.
- [ ] **Passo 7: Commit**

---

## Tarefa 12: Painel da coordenação — troca de orientador e limites

**Arquivos:**
- Modificar: `apps/projetos/services.py`, `apps/projetos/views.py`, `apps/projetos/urls.py`, `apps/projetos/permissions.py`, `apps/projetos/forms.py`, `conftest.py`
- Criar: `templates/projetos/painel_orientacoes.html`
- Teste: `apps/projetos/tests/test_painel_orientacoes.py`

**Interfaces:**
- Consome: `vagas_ocupadas`, `limite_do_professor` (T5).
- Produz: `trocar_orientador(projeto, novo_professor, por) -> Projeto`;
  `conceder_limite(professor, etapa, limite, justificativa, por) -> LimiteOrientacao`;
  `revogar_limite(limite, por)`; `pode_ajustar_orientacao(usuario)`;
  `pode_conceder_limite(usuario)`; rota `projetos:painel_orientacoes`.

- [ ] **Passo 1: Escrever os testes (falhando)**

Cobrindo, e o primeiro é o que mais importa:
- **`trocar_orientador` revalida a vaga do professor novo** — sem isso, o ajuste da
  coordenação vira a porta dos fundos por onde a regra das 3 vagas é contornada;
- conceder limite exige justificativa não vazia e registra quem autorizou;
- conceder limite igual ou menor que 3 é recusado;
- revogar limite **não** desfaz projetos já criados, e trava o próximo aceite;
- professor comum não concede limite nem troca orientador (403).

- [ ] **Passo 2: Rodar e confirmar que falha**
- [ ] **Passo 3: Implementar os serviços e as permissões**
- [ ] **Passo 4: Escrever a tela**, com o parcial `contas/_campo.html` e formulários POST com CSRF
- [ ] **Passo 5: Acrescentar a rota à suíte** com âncora de identidade
- [ ] **Passo 6: Rodar a suíte inteira.** Se a suíte reprovar a tela, o defeito é da tela.
- [ ] **Passo 7: Commit**

---

## Tarefa 13: Atualizar o `CLAUDE.md`

**Arquivos:**
- Modificar: `CLAUDE.md`, `tests/test_documentacao.py`, `README.md`

**Interfaces:** nenhuma de código.

- [ ] **Passo 1: Escrever os testes (falhando)**

```python
def test_claude_md_descreve_a_excecao_ao_teto_de_vagas():
    """O CLAUDE.md dizia que o bloqueio em 3 é automático e absoluto. Passou a admitir
    exceção autorizada pela coordenação. Documento que descreve regra mais rígida do
    que o sistema aplica faz alguém confiar numa trava que não existe."""
    assert "exceção" in CLAUDE and "coordenação" in CLAUDE


def test_claude_md_nomeia_a_app_de_projetos():
    assert "apps/projetos" in CLAUDE


def test_readme_documenta_o_celery_beat():
    ...
```

- [ ] **Passo 2: Rodar e confirmar que falha**

- [ ] **Passo 3: Atualizar o `CLAUDE.md`**

1. **Regra 1** passa a descrever o teto de 3 **com** a exceção autorizada por semestre e
   etapa, com justificativa obrigatória e autoria registrada.
2. Acrescentar `celery_beat` à arquitetura de containers.
3. Acrescentar `apps/projetos` à estrutura de apps, com sua responsabilidade.
4. Registrar que a alocação **não** é por desempenho escolar, contrariando o `inicio.pdf`
   — decisão tomada, com o custo aceito.
5. Atualizar a seção de fases: Bloco B concluído.

- [ ] **Passo 4: Atualizar o `README.md`** com o `celery_beat` e o comando de subida.

- [ ] **Passo 5: Percorrer os 15 critérios de aceitação do spec**, um a um, a partir de um
  ambiente reconstruído, registrando o resultado e a evidência de cada. Se algum não for
  atendido, **diga qual e por quê**.

- [ ] **Passo 6: Rodar a suíte inteira e commitar**

---

## Ao concluir

Com as 13 tarefas concluídas, o Bloco B está entregue e o próximo ciclo é o **Bloco C —
TCC I**: submissões em `.pdf` e `.docx`, aprovação do orientador, notas e a máquina de
status completa, sobre o `Projeto` que este bloco passou a criar.
