# Bancas e Avaliação — Design do Bloco D

**Bloco:** D (de A–H; ver §12 da spec da Fase 1,
`docs/superpowers/specs/2026-09-08-fundacao-e-contas-design.md`)

## 1. Objetivo

O Bloco C entregou a `Submissao` (PDF + editável) sem fechar nenhuma transição de
`Projeto.status` — `Aguardando Defesa` ficou explicitamente para este bloco (spec
do Bloco C, §3.1), porque depende de um agendamento de banca que só passa a existir
aqui. Este bloco cria o app `apps/bancas` (hoje registrado e vazio), com os modelos
`Banca`/`MembroBanca`, o agendamento, o registro do resultado da apresentação, e os
dois caminhos que se abrem quando o projeto é reprovado.

## 2. Escopo

### Dentro

- Modelos `Banca` e `MembroBanca`.
- Agendar banca (fecha `EM_ANDAMENTO → AGUARDANDO_DEFESA`), editar (reagendar) e
  cancelar (volta a `EM_ANDAMENTO`).
- Registrar o resultado da apresentação (fecha
  `AGUARDANDO_DEFESA → APROVADO_COM_RESSALVAS` ou `→ REPROVADO`).
- Reabrir ou cancelar definitivamente um projeto `REPROVADO`
  (`REPROVADO → EM_ANDAMENTO` ou `→ CANCELADO`, novo status).
- Notificação por e-mail do agendamento/reagendamento da banca.
- Extensão de `/orientacoes/` para cobrir todo esse novo ciclo.

### Fora

- **Nota ou avaliação por membro da banca.** Existe uma única nota e um único
  comentário por `Banca`, decididos coletivamente na apresentação e digitados
  pelo orientador — ver §3.2. O modelo `Avaliacao` do mapa de domínio original
  (§12 da spec da Fase 1: `Avaliacao: membro, nota, comentários`) não é criado
  neste bloco.
- **Qualquer ação do membro da banca no sistema**, interno ou externo — nenhum
  professor-membro (além do orientador) acessa uma tela própria para isto neste
  bloco. Ver §3.2.
- **`coorientador` em `Projeto`** e um "orientador externo" (mencionado no
  `docs/origem/inicio.pdf` como algo distinto de membro de banca, sujeito a
  aprovação do colegiado). Lacuna registrada desde o Bloco C, continua fora.
- **`ItemCorrecao`** (checklist de correções pós-banca) — Bloco F, mapa de
  domínio §12.
- **Ata e notificação da SUGRAD** — Bloco E.
- **Criação automática do TCC II** a partir de um TCC I `Concluído` — Bloco F.
- **Qualquer caminho a partir de `CANCELADO`.** Uma vez cancelado, este bloco não
  define reabertura nem qualquer outra ação sobre o projeto. Lacuna registrada,
  não decidida aqui.

## 3. Decisões de arquitetura

### 3.1 O orientador participa implicitamente da banca

A banca tem três integrantes (orientador + dois professores, `inicio.pdf`), mas
`MembroBanca` só registra os **dois** avaliadores adicionais. O orientador já é
`Projeto.orientador` — duplicar essa informação como uma terceira linha em
`MembroBanca` criaria uma fonte redundante que poderia divergir da FK original
(ex.: o projeto muda de orientador via painel da coordenação, Bloco B, e a linha
de `MembroBanca` não acompanha). `agendar_banca`/`editar_banca` recusam um
`MembroBanca` cujo `professor` seja o próprio orientador do projeto.

### 3.2 Uma nota geral, lançada só pelo orientador

O `inicio.pdf` é ambíguo — em um trecho diz "cada membro preenche seu formulário
de avaliação", em outro diz "o professor preenche a nota". Decisão: a nota é
**decidida coletivamente na apresentação** (fora do sistema, entre os três
avaliadores) e o orientador digita o resultado — uma nota, um comentário, um
resultado (`Aprovado com Ressalvas`/`Reprovado`) por `Banca`, não um por membro.

Isso elimina o subsistema inteiro de "cada membro acessa uma tela e preenche sua
avaliação" — nem para o membro interno (evitaria criar uma permissão e uma tela
novas só para isto) nem para o externo (que já não tem conta, regra 3 do
CLAUDE.md). O campo `resultado` usa as mesmas constantes de
`Projeto.APROVADO_COM_RESSALVAS`/`Projeto.REPROVADO`, para que
`registrar_resultado` grave `projeto.status = banca.resultado` sem tradução.

**Custo aceito:** o sistema não guarda a nota individual de cada avaliador, só o
resultado coletivo. Se um dia for preciso essa granularidade, é uma extensão
futura — decisão tomada, ciente do trade-off.

### 3.3 Agendar banca exige `Submissao`

Mesma amarração que o Bloco C deixou em aberto (§3.1 daquele spec): `Projeto`
só entra em `AGUARDANDO_DEFESA` se já tiver uma `Submissao`. `agendar_banca`
recusa com `ValidationError` se `not hasattr(projeto, "submissao")`.

### 3.4 `Banca` é `ForeignKey`, não `OneToOneField`

Cancelar uma banca não apaga o registro — ele fica com `status=CANCELADA`,
histórico de que aquele agendamento não vingou, e o orientador pode agendar uma
banca nova para o mesmo `Projeto` depois. Um `OneToOneField` impediria essa
segunda banca para sempre. Em vez disso, `Banca.projeto` é uma `ForeignKey`
comum, com uma restrição de banco garantindo no máximo uma banca **não
cancelada** por projeto ao mesmo tempo:

```python
constraints = [
    models.UniqueConstraint(
        fields=["projeto"],
        condition=~models.Q(status="CANCELADA"),
        name="banca_ativa_unica_por_projeto",
    )
]
```

### 3.5 Sem trava de data para registrar o resultado

`registrar_resultado` não compara `banca.data_hora` com `timezone.now()`. Confia
no orientador para só registrar depois que a apresentação de fato aconteceu —
mesmo espírito de várias checagens deste sistema que preferem simplicidade a uma
trava que só existe para um erro de uso, não um ataque (ex.: nada impede hoje um
professor de aceitar uma candidatura fora do prazo por engano; o sistema não
tenta adivinhar a intenção de quem opera).

### 3.6 Reprovado abre dois caminhos, ambos exigem o orientador

`REPROVADO` deixa de ser terminal: o orientador pode `reabrir_projeto` (volta a
`EM_ANDAMENTO`, o aluno tenta de novo) ou `cancelar_projeto` (`CANCELADO`, novo
valor em `Projeto.STATUS` — distinto de `REPROVADO` porque um representa "foi a
banca e não passou" e o outro "o projeto foi encerrado", informações diferentes
para quem olhar o histórico depois). As duas ações vivem em
`apps/projetos/services.py` (operam só sobre `Projeto`, sem envolver `Banca`), não
em `apps/bancas`.

### 3.7 `orientandos_atuais` precisa enxergar além de `EM_ANDAMENTO`

`apps/projetos/services.py::orientandos_atuais` (Bloco B, estendida no Bloco C)
filtra hoje só `status=EM_ANDAMENTO` — um projeto que virasse
`AGUARDANDO_DEFESA` ou `REPROVADO` sumiria da tela `/orientacoes/`, e o
orientador não teria onde agendar banca, registrar resultado, ou reabrir/cancelar.
O filtro passa a `status__in=[EM_ANDAMENTO, AGUARDANDO_DEFESA, REPROVADO]`.
`CANCELADO` fica de fora — é terminal, mesmo raciocínio já registrado no Bloco B
para `CONCLUIDO` (lacuna aceita: um projeto encerrado não precisa ocupar
"orientandos atuais" para sempre).

## 4. Modelagem de dados

### 4.1 `Projeto` (alteração, `apps/projetos/models.py`)

Acrescenta `CANCELADO = "CANCELADO"` a `Projeto.STATUS` (§3.6). Nenhum outro
campo de `Projeto` muda neste bloco.

### 4.2 `Banca` (`apps/bancas/models.py`)

| campo | tipo | observações |
|---|---|---|
| `projeto` | `ForeignKey(Projeto)` | `related_name="bancas"`, `PROTECT`; ver §3.4 sobre não ser `OneToOneField` |
| `data_hora` | `DateTimeField` | |
| `local` | `CharField(max_length=200)` | texto livre — sala física ou link de videoconferência |
| `status` | `CharField`, choices `AGENDADA\|REALIZADA\|CANCELADA` | `default=AGENDADA` |
| `nota` | `DecimalField(max_digits=3, decimal_places=1)` | `null=True, blank=True` — só preenchido em `REALIZADA` |
| `resultado` | `CharField`, choices `Projeto.APROVADO_COM_RESSALVAS\|Projeto.REPROVADO` | `blank=True, default=""` — ver §3.2 |
| `comentario` | `TextField` | `blank=True, default=""` |
| `criada_em` | `DateTimeField` | `auto_now_add=True` |

Restrição: `banca_ativa_unica_por_projeto` (§3.4).

### 4.3 `MembroBanca` (`apps/bancas/models.py`)

| campo | tipo | observações |
|---|---|---|
| `banca` | `ForeignKey(Banca)` | `related_name="membros"`, `CASCADE` — apagar a banca apaga seus membros, ao contrário de `Banca.projeto` (que é `PROTECT`) |
| `professor` | `ForeignKey(PerfilProfessor)` | `null=True, blank=True` — membro interno |
| `nome_externo` | `CharField(max_length=200)` | `null=True, blank=True` — membro externo, só o nome (regra 3 do CLAUDE.md: sem FK, sem CPF, sem e-mail) |

Restrição (`CheckConstraint`): exatamente um de `professor`/`nome_externo`
preenchido — nunca os dois, nunca nenhum.

```python
constraints = [
    models.CheckConstraint(
        check=(
            models.Q(professor__isnull=False, nome_externo__isnull=True)
            | models.Q(professor__isnull=True, nome_externo__isnull=False)
        ),
        name="membro_banca_interno_xor_externo",
    )
]
```

A contagem de exatamente 2 `MembroBanca` por `Banca`, e a exclusão do próprio
orientador (§3.1), são regra de negócio — vivem em `services.py`, não em
constraint de banco (mesmo raciocínio de todas as contagens deste projeto até
aqui: limite de vagas, máximo de coordenadores).

## 5. Camada de serviço

### 5.1 `apps/bancas/services.py`

```
agendar_banca(projeto, data_hora, local, membros, por) -> Banca
editar_banca(banca, data_hora, local, membros, por) -> Banca
cancelar_banca(banca, por) -> None
registrar_resultado(banca, nota, resultado, comentario, por) -> Banca
```

`membros`: lista de exatamente 2 dicts, cada um `{"professor": PerfilProfessor}`
ou `{"nome_externo": str}`.

`agendar_banca` — checagens, nesta ordem:
1. Posse: `por == projeto.orientador` (`permissions.pode_agendar_banca`).
2. `projeto.status == Projeto.EM_ANDAMENTO` (`ValidationError` senão).
3. `hasattr(projeto, "submissao")` (§3.3; `ValidationError` senão).
4. Exatamente 2 `membros`; nenhum `professor` igual a `projeto.orientador`
   (via `PerfilProfessor`, não `Usuario` — comparar
   `membro["professor"].usuario == projeto.orientador`); nenhum `professor`
   repetido entre os dois. `ValidationError` senão.

Efeito: cria `Banca` (`AGENDADA`) e os 2 `MembroBanca`; `projeto.status =
AGUARDANDO_DEFESA`; agenda `tasks.enviar_agendamento_banca(banca.id)` via
`transaction.on_commit`.

`editar_banca` — mesma posse (`por == banca.projeto.orientador`,
`permissions.pode_editar_banca`) e mesma validação de `membros`; só permitido
com `banca.status == AGENDADA`. Substitui `data_hora`/`local`/os 2
`MembroBanca` (apaga os antigos, cria os novos) e reagenda a mesma notificação.

`cancelar_banca` — posse (`permissions.pode_cancelar_banca`) +
`status == AGENDADA`. `banca.status = CANCELADA`; `projeto.status =
EM_ANDAMENTO`. Sem notificação (§7).

`registrar_resultado` — posse (`permissions.pode_registrar_resultado_banca`) +
`status == AGENDADA` (não registra duas vezes). Preenche
`nota`/`resultado`/`comentario`; `banca.status = REALIZADA`; `projeto.status =
resultado`.

### 5.2 `apps/projetos/services.py` (extensão)

```
reabrir_projeto(projeto, por) -> None    REPROVADO -> EM_ANDAMENTO
cancelar_projeto(projeto, por) -> None   REPROVADO -> CANCELADO
```

Ambas: posse (`por == projeto.orientador`,
`permissions.pode_reabrir_projeto`/`pode_cancelar_projeto`) +
`projeto.status == Projeto.REPROVADO` (`ValidationError` senão).

`orientandos_atuais` muda o filtro conforme §3.7.

## 6. Permissões

`apps/bancas/permissions.py` (mesmo padrão de posse do resto do projeto — nunca
por papel):

```
pode_agendar_banca(usuario, projeto)              usuario == projeto.orientador
pode_editar_banca(usuario, banca)                 usuario == banca.projeto.orientador
pode_cancelar_banca(usuario, banca)                usuario == banca.projeto.orientador
pode_registrar_resultado_banca(usuario, banca)    usuario == banca.projeto.orientador
```

Quatro funções, não uma reaproveitada — mesmo estilo de `pode_editar_tema`/
`pode_desativar_tema` no Bloco B (corpos idênticos, nomes por verbo).

`apps/projetos/permissions.py` (extensão):

```
pode_reabrir_projeto(usuario, projeto)     usuario == projeto.orientador
pode_cancelar_projeto(usuario, projeto)    usuario == projeto.orientador
```

As views escopam o lookup por dono
(`get_object_or_404(Projeto, pk=..., orientador=request.user)` para agendar;
`get_object_or_404(Banca, pk=..., projeto__orientador=request.user)` para
editar/cancelar/registrar resultado) — mesmo padrão `editar_tema`/
`desativar_tema` do Bloco B: banca (ou projeto) alheio e inexistente respondem o
mesmo 404, nunca 403.

## 7. Telas

Tudo em `apps/bancas`, alcançado a partir de `/orientacoes/` (Bloco B/C, agora
estendida — §3.7):

| rota | quem | o quê |
|---|---|---|
| `/bancas/agendar/<projeto_id>/` | orientador | `FormularioBanca`: `data_hora`, `local`, 2 blocos de membro |
| `/bancas/<id>/editar/` | orientador | mesmo `FormularioBanca`, pré-carregado |
| `/bancas/<id>/cancelar/` | orientador | `<form method="post">` direto em `/orientacoes/`, sem tela própria — mesmo padrão simples de `desativar_tema` |
| `/bancas/<id>/resultado/` | orientador | `FormularioResultadoBanca`: `nota`, `resultado`, `comentario` |

Em `/orientacoes/`, cada `<li>` de orientando ganha, conforme o estado:

- **`EM_ANDAMENTO` com submissão:** link "Agendar banca".
- **`AGUARDANDO_DEFESA`:** mostra data/local/membros da banca ativa, com
  "Editar", "Cancelar" e "Registrar resultado".
- **`REPROVADO`:** mostra o resultado da última banca (nota/comentário), com
  "Reabrir projeto" e "Cancelar definitivamente" (mesmo padrão de formulário
  simples de POST).

`FormularioBanca`: `data_hora` e `local` como campos diretos; os dois membros
como quatro campos (`membro_1_professor`, `membro_1_externo`,
`membro_2_professor`, `membro_2_externo` — dois `ModelChoiceField` de
`PerfilProfessor`, dois `CharField`), com `clean()` exigindo exatamente um
preenchido por bloco e recusando repetição/o próprio orientador — mesmo estilo
de `clean()` de `FormularioCandidatura` (Bloco B), que já recusa professor
repetido entre os campos de opção.

## 8. Notificações (`apps/bancas/tasks.py`)

Mesmo padrão de `apps/projetos/tasks.py` (Celery, `send_mail`,
`render_to_string`, retentativa com recuo exponencial):

`enviar_agendamento_banca(banca_id)` — disparada por `agendar_banca` **e**
`editar_banca` (reagendar reenvia o aviso). Um `send_mail` para o aluno, e um
`send_mail` por `MembroBanca` interno com e-mail cadastrado — remetentes
separados, não um único `to` com os dois grupos (mesmo motivo do
`enviar_esgotamento`, Bloco B: corpos de e-mail potencialmente diferentes por
grupo). Membro externo nunca recebe nada — não tem e-mail cadastrado. Link
sempre para a tela de login (regra 5 do CLAUDE.md).

`cancelar_banca` e `registrar_resultado` não notificam ninguém — decisão
consciente, não lacuna: este bloco não pediu isso.

## 9. Pré-requisitos herdados

- `apps/projetos/models.py::Projeto` (`status`, `orientador`, `submissao` via
  `related_name` do Bloco C).
- `apps/contas/models.py::PerfilProfessor`.
- `apps/projetos/services.py::orientandos_atuais`,
  `views.py::orientacoes`, `templates/projetos/orientacoes.html` — pontos de
  extensão (§3.7, §7).
- `apps/contas/tasks.py::enviar_convite` / `apps/projetos/tasks.py` — padrão de
  tarefa Celery de e-mail a seguir em `apps/bancas/tasks.py`.
- `config/urls.py` — `apps/bancas.urls` entra com `path("",
  include("apps.bancas.urls"))`, mesmo padrão de `apps.projetos.urls`.

## 10. Testes

Seguindo a disciplina do CLAUDE.md (§"Disciplina de Testes"): toda checagem
nova provada por mutação. Casos mínimos:

- `agendar_banca` recusa sem `Submissao`, recusa fora de `EM_ANDAMENTO`, recusa
  quem não é o orientador (404 na view), recusa o orientador como um dos dois
  membros, recusa professor repetido entre os dois membros.
- `agendar_banca` bem-sucedido: `Projeto.status == AGUARDANDO_DEFESA`, `Banca`
  e 2 `MembroBanca` criados, e-mail enfileirado para aluno + membro interno
  (não para o externo).
- `banca_ativa_unica_por_projeto`: duas `Banca` `AGENDADA` para o mesmo
  `Projeto` violam a constraint; uma `CANCELADA` e uma `AGENDADA` não.
- `membro_banca_interno_xor_externo`: `professor` e `nome_externo` ambos
  preenchidos (ou ambos vazios) violam a constraint.
- `editar_banca`/`cancelar_banca`/`registrar_resultado` recusam fora de
  `AGENDADA` (mutação obrigatória: cada checagem de status precisa de um teste
  que a comente e observe outro teste reprovar).
- `cancelar_banca`: `Projeto` volta a `EM_ANDAMENTO`; `Banca.status ==
  CANCELADA`; nenhum e-mail disparado.
- `registrar_resultado`: `Projeto.status` recebe `banca.resultado` exatamente;
  `Banca.status == REALIZADA`; chamar de novo é recusado.
- `reabrir_projeto`/`cancelar_projeto`: só a partir de `REPROVADO`, só pelo
  orientador (404 senão).
- `/orientacoes/` mostra as ações corretas para cada um dos quatro estados
  (`EM_ANDAMENTO` com/sem submissão, `AGUARDANDO_DEFESA`, `REPROVADO`).

## 11. Critérios de aceitação

1. Orientador agenda banca de um projeto com submissão; `Projeto.status` vira
   `AGUARDANDO_DEFESA`; e-mail enfileirado para aluno e membros internos.
2. Agendar sem submissão, fora de `EM_ANDAMENTO`, com o próprio orientador como
   membro, ou com professor repetido, é recusado com mensagem clara.
3. Orientador reagenda (edita) a banca `AGENDADA`; o e-mail é reenviado.
4. Orientador cancela a banca `AGENDADA`; `Projeto` volta a `EM_ANDAMENTO`;
   nenhum e-mail é enviado no cancelamento.
5. Orientador registra nota + comentário + resultado; `Projeto.status` vira
   `Aprovado com Ressalvas` ou `Reprovado`, conforme o resultado escolhido.
6. Registrar resultado duas vezes na mesma banca é recusado.
7. A partir de `Reprovado`, o orientador reabre (volta a `EM_ANDAMENTO`) ou
   cancela definitivamente (`Cancelado`) o projeto.
8. Quem não é o orientador do projeto (outro professor, o próprio aluno) recebe
   404 ao tentar agendar, editar, cancelar ou registrar resultado de uma banca
   alheia — nunca 403.
9. `/orientacoes/` mostra a ação correta disponível para cada estado do
   projeto (agendar / editar-cancelar-registrar / reabrir-cancelar).
10. Nenhuma das regras acima está implementada em `views.py` ou `models.py`.
11. `docker compose exec web pytest` passa, incluindo acessibilidade nas rotas
    novas.
