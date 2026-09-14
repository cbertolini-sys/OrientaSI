# TCC II — Design do Bloco F

**Bloco:** F (de A–H; ver §12 da spec da Fase 1,
`docs/superpowers/specs/2026-09-08-fundacao-e-contas-design.md`)

## 1. Objetivo

Os Blocos B–E implementaram o ciclo de vida inteiro do TCC I, de `Em
Andamento` a `Concluído`. Este bloco fecha o curso: o TCC II nasce
automaticamente quando um TCC I é concluído (ou manualmente, para
equivalência externa), reaproveita a maior parte do que já existe
(`Submissao`, `Banca`, `Ata` são genéricos por `Projeto`), e acrescenta o que
é específico do TCC II — o checklist de correções pós-banca e o termo de
aceite de publicação — como pré-requisitos da mesma transição `Aprovado com
Ressalvas → Aprovado` que o Bloco E já implementou (sem gate) para o TCC I.

## 2. Escopo

### Dentro

- Criação automática do TCC II a partir de um TCC I `Concluído`
  (`Projeto.anterior`).
- Criação manual do TCC II pelo professor (equivalência externa), sob o
  mesmo limite de vagas do TCC I.
- `ItemCorrecao`: checklist de correções pós-banca, criado pelo orientador.
- `TermoPublicacao`: aceite de publicação assinado pelo aluno.
- Gate de `aprovar_projeto` para `TCC_II`: exige checklist concluído e termo
  assinado.
- `coorientador`/`coorientador_externo` em `Projeto` (lacuna registrada desde
  o Bloco C).
- Extensão de `/meu-tcc/` para reconhecer a etapa ativa (TCC_I ou TCC_II) em
  vez de assumir TCC_I.

### Fora

- **Nota por membro da banca / itens de correção estruturados vindos da
  banca.** O mapa de domínio original sugeria isso (`Avaliacao` por membro);
  o Bloco D já decidiu contra (nota única por banca). Os itens de correção
  deste bloco são digitados pelo orientador, não pelos membros da banca.
- **Campo `tipo` em `Submissao`**, previsto no mapa de domínio original.
  Continua sem uso — a distinção TCC_I/TCC_II já vem de serem `Projeto`s
  diferentes (`Projeto.anterior` liga um ao outro), não de um campo dentro
  de `Submissao`.
- **Aprovação do colegiado para coorientador externo**, mencionada no
  `inicio.pdf`. É processo de papel, fora do sistema — `coorientador_externo`
  é só um nome, sem fluxo de aprovação nem gate de negócio.
- **Catálogo público** exibindo coorientador ou qualquer dado do TCC II —
  Bloco G decide o que o catálogo expõe.
- **Reabrir/cancelar um TCC II reprovado** — reaproveita
  `reabrir_projeto`/`cancelar_projeto` (Bloco D), que já são genéricos por
  `Projeto`. Nenhuma mudança de código; só testado para `TCC_II`.
- **Posse do coorientador.** Só o orientador principal tem posse sobre o
  projeto (agendar banca, aprovar, gerenciar correções). Coorientador é
  informativo.

## 3. Decisões de arquitetura

### 3.1 Criação automática do TCC II

Disparada dentro de `apps.documentos.services.aprovar_ata` (Bloco E), no
momento em que `Projeto.status` vira `CONCLUIDO` — só quando
`ata.projeto.etapa == Projeto.TCC_I` (um TCC II concluído não deve tentar
criar um "TCC III" inexistente). Chama
`apps.projetos.services.criar_tcc_ii_automatico(projeto_tcc_i)` (import
local, mesmo padrão de `apps/documentos` → `apps/projetos` já usado por
`anexar_banca_ativa`/`gerar_ata`).

`criar_tcc_ii_automatico` **não** passa por `criar_projeto_sob_limite`
(§3.2): copia `aluno`, `orientador` e `coorientador`/`coorientador_externo`
do TCC I; `anterior = projeto_tcc_i`; `status = EM_ANDAMENTO`; sem checar
vaga — é continuação de um aluno que o professor já orienta, não um
compromisso novo (spec confirmada no brainstorming).

### 3.2 Criação manual reaproveita `criar_projeto_sob_limite`

`criar_projeto_sob_limite(aluno, professor, tema, etapa)`
(`apps/projetos/services.py:68`, Bloco B) já existe, já é a função
testada contra corrida (`test_concorrencia.py`) que trava a linha do
`PerfilProfessor`, revalida `vagas_ocupadas`/`limite_do_professor`, e cria o
`Projeto`. `criar_tcc_ii_manual` é uma casca fina sobre ela:
`criar_projeto_sob_limite(aluno, professor, tema=None, etapa=Projeto.TCC_II)`
— sem reimplementar a checagem de limite. `tema=None` porque o TCC II não
tem conceito de mural/tema como o TCC I.

### 3.3 Gate de `aprovar_projeto` para TCC_II

`aprovar_projeto` (Bloco E) ganha, no início da função, uma checagem
condicional a `projeto.etapa == Projeto.TCC_II`:

- Recusa (`ValidationError`, mensagem específica) se existir algum
  `ItemCorrecao` de `projeto` com `concluido=False`.
- Recusa (`ValidationError`, mensagem específica) se não existir
  `TermoPublicacao` para `projeto`.

Para `TCC_I`, nada muda — a função continua só a confirmação simples que o
Bloco E já implementou.

### 3.4 `TermoPublicacao` é a existência da linha, não um booleano

Schema do mapa de domínio original: `TermoPublicacao(projeto,
assinado_em)` — dois campos, sem um terceiro "assinado" booleano. A
EXISTÊNCIA da linha já significa "assinado"; `assinar_termo_publicacao`
cria a linha (`auto_now_add` em `assinado_em`) e não há como desfazer —
assinar é uma ação única, ao contrário de `RevisaoSUGRAD` (Bloco E), que
pode ser revisitada (`PENDENTE`/`DEVOLVIDA`/`APROVADA`).

### 3.5 `/meu-tcc/` deixa de assumir TCC_I

`apps/projetos/views.py::meu_tcc` hoje chama
`services.projeto_ativo_do_aluno(request.user, Projeto.TCC_I)`, fixo. Passa
a tentar `Projeto.TCC_II` primeiro, caindo para `Projeto.TCC_I` se não
houver — as duas etapas nunca coexistem ativas ao mesmo tempo (TCC_I sai de
"ativo" ao virar `Concluído`, condição já embutida na `UniqueConstraint`
`projeto_ativo_unico_por_aluno_e_etapa`), então isso sempre mostra a etapa
corrente do aluno, sem ambiguidade. Quando a etapa é `TCC_II` e o status é
`Aprovado com Ressalvas`, a tela ganha uma lista somente-leitura dos
`ItemCorrecao` pendentes e um botão "Assinar termo de aceite de publicação"
(desaparece depois de assinado).

### 3.6 `coorientador` é só informativo

Mesma exclusividade interno/externo de `MembroBanca` (Bloco D):
`coorientador` (FK `PerfilProfessor`, opcional) XOR `coorientador_externo`
(texto, opcional) — mas aqui os DOIS podem ficar vazios (coorientador é
opcional por completo, ao contrário dos dois membros obrigatórios de
`Banca`). Sem nenhuma permissão nova: aparece nas telas (`/orientacoes/`, a
ata) como informação; o orientador principal continua sendo o único com
posse sobre o projeto.

## 4. Modelagem de dados

### 4.1 `Projeto` (extensão, `apps/projetos/models.py`)

| campo | tipo | observações |
|---|---|---|
| `anterior` | `ForeignKey("self")` | `null=True, blank=True`, `on_delete=SET_NULL` (apagar o TCC I não pode impedir a consulta ao TCC II que restou); aponta pro TCC I quando o TCC II nasce automaticamente; `None` na criação manual |
| `coorientador` | `ForeignKey(PerfilProfessor)` | `null=True, blank=True`, `on_delete=PROTECT`, `related_name="projetos_como_coorientador"` |
| `coorientador_externo` | `CharField(max_length=200)` | `blank=True, default=""` |

Restrição (`CheckConstraint`, mesmo padrão do Bloco D — `condition=`, não
`check=`, por causa da depreciação do Django 5.2+):

```python
models.CheckConstraint(
    condition=(
        models.Q(coorientador__isnull=True, coorientador_externo="")
        | (models.Q(coorientador__isnull=False) & models.Q(coorientador_externo=""))
        | (models.Q(coorientador__isnull=True) & ~models.Q(coorientador_externo=""))
    ),
    name="projeto_coorientador_nao_duplo",
)
```

(Os três ramos: nenhum coorientador; só interno; só externo — nunca os
dois.)

### 4.2 `ItemCorrecao` (`apps/bancas/models.py` — mapa de domínio tagueia `[F]` dentro de `bancas/`)

| campo | tipo | observações |
|---|---|---|
| `projeto` | `ForeignKey(Projeto)` | `related_name="itens_correcao"`, `PROTECT` |
| `descricao` | `TextField` | texto livre, digitado pelo orientador |
| `concluido` | `BooleanField` | `default=False` |
| `criado_em` | `DateTimeField` | `auto_now_add=True` |

### 4.3 `TermoPublicacao` (`apps/projetos/models.py`)

| campo | tipo | observações |
|---|---|---|
| `projeto` | `OneToOneField(Projeto)` | `related_name="termo_publicacao"`, `PROTECT` |
| `assinado_em` | `DateTimeField` | `auto_now_add=True` |

## 5. Camada de serviço

### 5.1 `apps/projetos/services.py` (extensão)

```
criar_tcc_ii_automatico(projeto_tcc_i) -> Projeto         sem checar vaga; anterior=projeto_tcc_i
criar_tcc_ii_manual(aluno, professor, por) -> Projeto     checa vaga via criar_projeto_sob_limite; posse: por == professor.usuario
assinar_termo_publicacao(projeto, por) -> TermoPublicacao posse: por == projeto.aluno
```

`aprovar_projeto` ganha o gate do §3.3 (mesma assinatura
`aprovar_projeto(projeto, por)`, sem mudança de interface).

### 5.2 `apps/bancas/services.py` (extensão)

```
criar_item_correcao(projeto, descricao, por) -> ItemCorrecao   posse: por == projeto.orientador
concluir_item_correcao(item, por) -> None                       posse: por == item.projeto.orientador
```

## 6. Permissões

`apps/projetos/permissions.py` (extensão):
```
pode_criar_tcc_ii_manual(usuario)          hasattr(usuario, "perfil_professor") — mesmo portão de pode_criar_tema
pode_assinar_termo(usuario, projeto)       usuario == projeto.aluno
```

`apps/bancas/permissions.py` (extensão):
```
pode_gerenciar_correcao(usuario, projeto)  usuario == projeto.orientador
```

Lookups de view escopados por posse, mesmo padrão desde o Bloco B: dono
alheio e inexistente respondem os dois com 404.

## 7. Telas

| rota | quem | o quê |
|---|---|---|
| `/temas/tcc-ii/criar/` | professor | formulário: escolhe aluno (sem TCC II ativo), cria o `Projeto` TCC_II manual |
| `/orientacoes/<projeto_id>/correcoes/` | orientador | lista `ItemCorrecao` (com checkbox/POST para concluir cada um), formulário para criar item novo, botão "Aprovar" (habilitado só quando o gate do §3.3 permite) |
| `/meu-tcc/` (estendida) | aluno | mostra a etapa ativa (TCC_I ou TCC_II, §3.5); para TCC_II em `Aprovado com Ressalvas`: lista somente-leitura de `ItemCorrecao` pendentes + botão de assinar o termo |

Em `/orientacoes/`, quando `etapa == TCC_II` e `status ==
APROVADO_COM_RESSALVAS`: link "Gerenciar correções" no lugar do botão
"Aprovar" direto que o TCC_I usa — o botão "Aprovar" continua existindo,
mas dentro da tela de correções.

## 8. Notificações

- `criar_tcc_ii_automatico`/`criar_tcc_ii_manual`
  (`apps/projetos/tasks.py`): e-mail ao aluno avisando que o TCC II começou.
- `criar_item_correcao` (`apps/bancas/tasks.py`): e-mail ao aluno a cada
  item criado — sem agrupar (decisão confirmada no brainstorming).
- `concluir_item_correcao`/`assinar_termo_publicacao`: sem notificação — o
  orientador só confere ao abrir a tela de correções.

## 9. Pré-requisitos herdados

- `apps/projetos/services.py::criar_projeto_sob_limite`,
  `vagas_ocupadas`, `limite_do_professor` (Bloco B) — reaproveitados sem
  alteração por `criar_tcc_ii_manual` (§3.2).
- `apps/projetos/services.py::projeto_ativo_do_aluno` (Bloco C) —
  reaproveitado duas vezes (TCC_II, depois TCC_I) por `/meu-tcc/` (§3.5).
- `apps/bancas/services.py::agendar_banca`/`registrar_resultado` (Bloco D) —
  já genéricos por `Projeto.etapa`; nenhuma mudança de código, só testados
  para TCC_II.
- `apps/documentos/services.py::gerar_ata`/`aprovar_ata` (Bloco E) — `gerar_ata`
  já genérico; `aprovar_ata` ganha a chamada condicional do §3.1.
- `apps/projetos/services.py::reabrir_projeto`/`cancelar_projeto` (Bloco D) —
  já genéricos; só testados para TCC_II.
- `apps/projetos/permissions.py::pode_criar_tema` (Bloco B) — mesmo portão
  de papel reaproveitado por `pode_criar_tcc_ii_manual` (§6).

## 10. Testes

Seguindo a disciplina do CLAUDE.md (§"Disciplina de Testes"): toda checagem
nova provada por mutação. Casos mínimos:

- `criar_tcc_ii_automatico`: `Projeto` novo com `etapa=TCC_II`,
  `anterior=projeto_tcc_i`, `status=EM_ANDAMENTO`; não é bloqueado mesmo com
  o professor no teto de vagas de TCC_II (mutação obrigatória: comente essa
  ausência de checagem e confirme que um teste específico reprova).
- `aprovar_ata` só chama `criar_tcc_ii_automatico` quando
  `etapa == TCC_I` — um TCC_II concluído não cria um terceiro projeto.
- `criar_tcc_ii_manual`: cria com `anterior=None`; recusa quando o
  professor está no limite (reaproveita a mensagem de
  `criar_projeto_sob_limite`); recusa quem não tem `perfil_professor`.
- `criar_item_correcao`/`concluir_item_correcao`: posse (404 na view,
  `PermissionDenied` no serviço); e-mail enfileirado só na criação.
- `aprovar_projeto` em `TCC_II`: recusa com item pendente; recusa sem termo
  assinado; aprova quando os dois estão satisfeitos. Cada uma das duas
  condições precisa da sua PRÓPRIA mutação — comentar uma não pode mascarar
  a ausência de teste da outra (checagem vizinha, CLAUDE.md).
- `assinar_termo_publicacao`: cria a linha; posse (só o aluno do projeto).
- `Projeto.projeto_coorientador_nao_duplo`: `coorientador` e
  `coorientador_externo` preenchidos juntos violam a constraint.
- `/meu-tcc/` mostra TCC_II quando existe um ativo, mesmo com um TCC_I
  `Concluído` no histórico do aluno.
- `/orientacoes/` mostra "Gerenciar correções" (não "Aprovar" direto) para
  `TCC_II` em `Aprovado com Ressalvas`.

## 11. Critérios de aceitação

1. Um TCC I chega a `Concluído`; um `Projeto` TCC_II nasce automaticamente,
   mesmo aluno e orientador, `anterior` apontando pro TCC I, sem checar
   limite de vagas.
2. Professor cria um TCC II manualmente para um aluno sem TCC I no sistema;
   checa o limite de vagas (recusa se o professor estiver no teto).
3. Aluno envia PDF/editável do TCC II via `/meu-tcc/` (mesmo fluxo do
   Bloco C, sem mudança de código).
4. Orientador agenda banca e registra resultado do TCC II (mesmo fluxo do
   Bloco D, sem mudança de código).
5. Orientador cria itens de correção após `Aprovado com Ressalvas`; aluno
   recebe e-mail por item.
6. Aprovar o projeto (TCC_II) com algum item pendente, ou sem o termo
   assinado, é recusado com mensagem clara e específica pro motivo.
7. Aluno assina o termo de publicação; orientador conclui todos os itens;
   `aprovar_projeto` então funciona, gera a ata e notifica a SUGRAD (mesmo
   fluxo do Bloco E).
8. SUGRAD aprova a ata do TCC II; `Projeto.status` vira `Concluído`; nenhum
   "TCC III" é criado.
9. `coorientador`/`coorientador_externo` nunca coexistem no mesmo `Projeto`.
10. Nenhuma das regras acima está implementada em `views.py` ou `models.py`.
11. `docker compose exec web pytest` passa, incluindo acessibilidade nas
    rotas novas.
