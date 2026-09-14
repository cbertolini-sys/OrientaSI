# Atas e SUGRAD — Design do Bloco E

**Bloco:** E (de A–H; ver §12 da spec da Fase 1,
`docs/superpowers/specs/2026-09-08-fundacao-e-contas-design.md`)

## 1. Objetivo

O Bloco D fechou o ciclo até `Aprovado com Ressalvas` ou `Reprovado`. Este bloco
fecha o restante do ciclo do TCC I: o orientador confirma que o aluno corrigiu o
que a banca pediu (`Aprovado`), o sistema gera a Ata da defesa em PDF e notifica
a SUGRAD, e a SUGRAD aprova ou devolve com comentários — aprovando, o projeto
chega a `Concluído`.

## 2. Escopo

### Dentro

- Transição `Aprovado com Ressalvas → Aprovado` para o TCC I (confirmação
  simples do orientador, sem checklist).
- Modelos `Ata` e `RevisaoSUGRAD` (`apps/documentos`).
- Geração automática da Ata (WeasyPrint) e notificação por e-mail à SUGRAD ao
  aprovar o projeto.
- Painel da SUGRAD: listar atas pendentes, baixar PDF, aprovar ou devolver com
  comentário.
- Devolução: o orientador vê o comentário em `/orientacoes/` e reenvia a
  mesma ata à SUGRAD.
- `Aprovado → Concluído` quando a SUGRAD aprova a ata.

### Fora

- **Checklist de correções (`ItemCorrecao`) e termo de aceite de publicação.**
  O `inicio.pdf` original descreve os dois como etapas do **TCC II**, não do
  TCC I (mapa de domínio da Fase 1, §12: `ItemCorrecao` tagueado `[F]`; o
  próprio spec da Fase 1 registra que "as etapas extras do TCC II — checklist
  de correções e termo de publicação" não duplicam `Projeto`, são modelos
  próprios do Bloco F). A transição `Aprovado com Ressalvas → Aprovado` deste
  bloco vale só para `Projeto.etapa == TCC_I`; quando o Bloco F existir, ele
  decide como o TCC II enriquece (ou substitui) esta mesma transição sem
  quebrar o caminho do TCC I.
- **Regeneração do PDF da ata entre revisões.** `reenviar_a_sugrad` reabre a
  mesma `Ata`/`RevisaoSUGRAD` para `PENDENTE` — não gera um PDF novo. Se o
  conteúdo da ata precisar mudar entre revisões, é lacuna registrada.
- **Catálogo público e calendário de apresentações** — Bloco G.
- **Qualquer caminho a partir de `Concluído`** — estado terminal, nenhuma ação
  definida (mesmo padrão de `Cancelado` no Bloco D).
- **Histórico de revisões da SUGRAD.** `RevisaoSUGRAD` é uma linha só por
  `Ata` (`OneToOneField`), sobrescrita a cada decisão — mesmo padrão de
  "sem histórico" já usado em `Submissao` (Bloco C) e `Banca.resultado`
  (Bloco D). Quem revisou antes e o que disse fica perdido depois da próxima
  decisão.

## 3. Decisões de arquitetura

### 3.1 `Aprovado` para TCC I é uma confirmação simples, sem checklist

O `inicio.pdf` descreve, para o TCC I: "Uma vez aprovado o professor preenche a
nota e aponta o TCC I como Aprovado (ou Aprovado com Ressalvas)... Uma vez
aprovado o sistema cria a ata". O checklist de correções e o termo de
publicação só aparecem na seção do TCC II do mesmo documento. Como o spec da
Fase 1 já decidiu que essas duas etapas são modelos próprios do Bloco F (não
uma extensão do `Projeto`), a transição `Aprovado com Ressalvas → Aprovado`
deste bloco é apenas uma confirmação do orientador
(`apps.projetos.services.aprovar_projeto`) — sem gate de checklist. Quando o
Bloco F existir, ele decide se/como condicionar essa mesma transição para
`Projeto.etapa == TCC_II`.

### 3.2 Aprovar já gera a ata e notifica a SUGRAD, num só passo

Mesmo texto do `inicio.pdf`: "uma vez aprovado o sistema cria a ata... e envia
um email para a SUGRAD". `aprovar_projeto` (em `apps/projetos/services.py`,
onde a transição de status já vive) chama
`apps.documentos.services.gerar_ata(projeto)` dentro da mesma transação, e a
notificação é agendada via `transaction.on_commit` — não existe um botão
separado "gerar ata".

### 3.3 `RevisaoSUGRAD` é uma linha por `Ata`, sem histórico

Ver §2 "Fora". `PENDENTE` (criada junto com a `Ata`) → `APROVADA` ou
`DEVOLVIDA`. `reenviar_a_sugrad` volta `DEVOLVIDA` para `PENDENTE`,
sobrescrevendo o `comentario` anterior — mesmo raciocínio de
`Submissao.versao` (Bloco C) e `Banca.nota`/`resultado` (Bloco D): o sistema
guarda o estado atual, não a trajetória.

### 3.4 Devolvida não desfaz `Aprovado`

Uma ata `DEVOLVIDA` não muda `Projeto.status` — ele continua `Aprovado`. A
devolução é sobre o **documento** (ata), não sobre o mérito acadêmico já
decidido pela banca; desfazer a aprovação do orientador reabriria uma decisão
que não está em questão. O orientador só vê o comentário e reenvia.

### 3.5 Permissão da SUGRAD é por PAPEL, não por posse

Diferente de toda outra checagem deste sistema desde o Bloco B (sempre posse
— "é ESTE professor/orientador?"), `pode_revisar_ata` pergunta só
"`usuario.papel == Usuario.SUGRAD`?": a SUGRAD é um setor único (regra
inegociável nº 2 do CLAUDE.md — só uma conta), não dono de nenhum projeto
específico — ela revisa a ata de QUALQUER projeto. Mesmo formato de
`pode_ajustar_orientacao`/`pode_conceder_limite` (Bloco B), que já checam
`usuario.is_coordenador` em vez de posse.

### 3.6 `orientandos_atuais` precisa enxergar `Aprovado com Ressalvas`

Mesma classe de lacuna já fechada no Bloco D (§3.7 daquele spec):
`orientandos_atuais` filtra hoje
`status__in=[EM_ANDAMENTO, AGUARDANDO_DEFESA, REPROVADO]` — sem
`APROVADO_COM_RESSALVAS`, o projeto sumiria de `/orientacoes/` assim que a
banca fosse realizada, e o orientador nunca veria onde clicar "Aprovar". O
filtro ganha `APROVADO_COM_RESSALVAS` e `APROVADO` (este último para o
orientador ver o comentário de uma ata devolvida e reenviar). `CONCLUIDO`
continua fora — estado terminal, mesmo raciocínio já registrado para
`CONCLUIDO`/`CANCELADO`.

## 4. Modelagem de dados

### 4.1 `Ata` (`apps/documentos/models.py`)

| campo | tipo | observações |
|---|---|---|
| `projeto` | `ForeignKey(Projeto)` | `related_name="atas"`, `PROTECT` |
| `banca` | `ForeignKey(Banca)` | a banca que originou a aprovação, `PROTECT` |
| `numero` | `CharField` | formato `"NNN/AAAA"`, sequencial por ano civil de `gerada_em` |
| `pdf` | `FileField` | gerado por `gerar_ata`, nunca por upload do usuário — sem `validators` de extensão/tamanho (não é um FileField que aceita input externo) |
| `gerada_em` | `DateTimeField` | `auto_now_add=True` |

`projeto` não é `OneToOneField`: nada neste bloco impede reabrir e reprovar de
novo (Bloco D) depois de já ter uma `Ata` antiga de uma rodada anterior — a
mesma lacuna que `Banca` já tem em relação a `Projeto` (histórico de bancas
canceladas). `gerar_ata` sempre cria uma `Ata` nova; não há checagem de
duplicidade neste bloco.

**Custo aceito:** a numeração (`count() + 1`, §5.2) tem uma condição de
corrida sob criação concorrente de atas no mesmo ano — duas aprovações
simultâneas podem gerar o mesmo número. Aceitável porque aprovar um TCC I é
uma ação humana de baixa frequência (um orientador aprovando um aluno por
vez), não um caminho de alto throughput; se isso um dia importar, a correção
é uma sequência de banco (`Sequence`) ou uma trava (`select_for_update`) na
consulta do contador, não decidida aqui.

### 4.2 `RevisaoSUGRAD` (`apps/documentos/models.py`)

| campo | tipo | observações |
|---|---|---|
| `ata` | `OneToOneField(Ata)` | `related_name="revisao"`, `CASCADE` (revisão só existe em função da ata) |
| `status` | `CharField`, choices `PENDENTE\|APROVADA\|DEVOLVIDA` | `default=PENDENTE` |
| `comentario` | `TextField` | `blank=True, default=""` — só preenchido quando `DEVOLVIDA` |
| `decidida_em` | `DateTimeField` | `null=True, blank=True` — preenchida só quando sai de `PENDENTE` |

## 5. Camada de serviço

### 5.1 `apps/projetos/services.py` (extensão)

```
aprovar_projeto(projeto, por) -> None    APROVADO_COM_RESSALVAS -> APROVADO; gera a Ata
```

Checagens: posse (`por == projeto.orientador`,
`permissions.pode_aprovar_projeto`) + `projeto.status ==
Projeto.APROVADO_COM_RESSALVAS` (`ValidationError` senão). Efeito:
`projeto.status = Projeto.APROVADO`; chama
`apps.documentos.services.gerar_ata(projeto)` (import local, mesmo motivo do
`anexar_banca_ativa` no Bloco D: `apps/projetos` não deve depender de
`apps/documentos` no carregamento do módulo).

`orientandos_atuais`: filtro ganha `APROVADO_COM_RESSALVAS` e `APROVADO`
(§3.6).

### 5.2 `apps/documentos/services.py`

```
gerar_ata(projeto) -> Ata                          cria Ata (numeração) + RevisaoSUGRAD PENDENTE; notifica SUGRAD
reenviar_a_sugrad(ata, por) -> None                 DEVOLVIDA -> PENDENTE; notifica SUGRAD
aprovar_ata(ata, por) -> None                       PENDENTE -> APROVADA; Projeto.status = CONCLUIDO
devolver_ata(ata, por, comentario) -> None          PENDENTE -> DEVOLVIDA; notifica o orientador
```

`gerar_ata`: busca a `Banca` ativa do projeto (`Banca.objects.filter(projeto=
projeto).exclude(status=Banca.CANCELADA).latest("criada_em")` — a mesma que
`registrar_resultado` marcou `REALIZADA`); numera
`f"{Ata.objects.filter(gerada_em__year=ano).count() + 1:03d}/{ano}"`; renderiza
o template HTML da ata via `django.template.loader.render_to_string` e gera o
PDF com `weasyprint.HTML(string=corpo).write_pdf()`, salvo em `pdf` via
`ContentFile`; cria a `Ata` e a `RevisaoSUGRAD` `PENDENTE`; agenda a
notificação à SUGRAD via `transaction.on_commit`.

`aprovar_ata`/`devolver_ata`: permissão por papel
(`permissions.pode_revisar_ata`, §3.5) — `PermissionDenied` senão. Ambas
exigem `revisao.status == PENDENTE` (`ValidationError` senão — não decide
duas vezes). `aprovar_ata` também muda `ata.projeto.status =
Projeto.CONCLUIDO`.

`reenviar_a_sugrad`: posse (`por == ata.projeto.orientador`,
`permissions.pode_reenviar_ata`) + `revisao.status == DEVOLVIDA`
(`ValidationError` senão).

## 6. Permissões

`apps/projetos/permissions.py` (extensão):
```
pode_aprovar_projeto(usuario, projeto)    usuario == projeto.orientador
```

`apps/documentos/permissions.py` (novo):
```
pode_revisar_ata(usuario)             usuario.papel == Usuario.SUGRAD   (por PAPEL — §3.5)
pode_reenviar_ata(usuario, ata)       usuario == ata.projeto.orientador
```

As views escopam o lookup: `/orientacoes/<projeto_id>/aprovar/` e
`/orientacoes/<ata_id>/reenviar-sugrad/` usam
`get_object_or_404(..., orientador=request.user)` / `projeto__orientador=
request.user` (dono alheio e inexistente respondem os dois com 404, mesmo
padrão desde o Bloco B). `/painel/sugrad/` não tem lookup por posse — é um
portão de papel só (`permissions.garante(pode_revisar_ata(request.user),
...)`, mesmo formato de `painel_orientacoes`, Bloco B), que lista TODAS as
atas pendentes, de qualquer projeto.

## 7. Telas

| rota | quem | o quê |
|---|---|---|
| `/orientacoes/<projeto_id>/aprovar/` | orientador | POST-only — mesmo padrão simples de `desativar_tema`/`reabrir_projeto` |
| `/orientacoes/<ata_id>/reenviar-sugrad/` | orientador | POST-only |
| `/painel/sugrad/` (`documentos:painel`) | SUGRAD | lista atas `PENDENTE`: link de download do PDF, formulário "Aprovar" (POST simples) e "Devolver" (POST + `comentario` obrigatório) |

Em `/orientacoes/`, o `<li>` de cada orientando ganha mais dois ramos (depois
dos já existentes do Bloco D):
- `projeto.status == APROVADO_COM_RESSALVAS`: botão "Aprovar".
- `projeto.status == APROVADO` e a ata ativa está `DEVOLVIDA`: mostra o
  comentário da SUGRAD + botão "Reenviar à SUGRAD".
- `projeto.status == APROVADO` sem ata pendente/devolvida (aguardando a
  SUGRAD decidir, ou já `CONCLUIDO`): mensagem de estado, sem ação.

`templates/base.html` ganha o link "Painel SUGRAD" condicionado a
`user.papel == Usuario.SUGRAD` — mesmo padrão condicional por papel dos
demais links (`user.is_coordenador`, `user.perfil_professor` etc.).

## 8. Notificações (`apps/documentos/tasks.py`)

Mesmo padrão de `apps/bancas/tasks.py`/`apps/projetos/tasks.py` (Celery,
`send_mail`, `render_to_string`, retentativa com recuo exponencial):

- `enviar_ata_para_sugrad(ata_id)` — disparada por `gerar_ata` e por
  `reenviar_a_sugrad`. Destinatário: a única conta `Usuario.objects.filter(
  papel=Usuario.SUGRAD, is_active=True).first()` (mesmo raciocínio de
  `apps.contas.services.coordenadores`, adaptado a uma conta só). Se não
  houver conta SUGRAD ativa (sistema mal configurado), registra um
  `logger.warning` e não falha a aprovação do projeto — mesma decisão de
  `enviar_esgotamento` (Bloco B) quando não há coordenador ativo.
- `enviar_devolucao_para_orientador(ata_id)` — disparada por `devolver_ata`.
  Destinatário: `ata.projeto.orientador`.
- `aprovar_ata` não notifica ninguém (decisão confirmada, §5.2/pergunta
  respondida no brainstorming).

Link sempre para a tela de login (regra 5 do CLAUDE.md).

## 9. Pré-requisitos herdados

- `apps/bancas/models.py::Banca` (`Bloco D`) — origem da `Ata`.
- `apps/projetos/models.py::Projeto` (`status`, `orientador`, `etapa`).
- `apps/contas/models.py::Usuario.SUGRAD`, e a constraint `conta_sugrad_unica`
  (Bloco A) — garante no máximo uma conta a notificar.
- `weasyprint` já validado como dependência de sistema (`tests/test_pdf.py`,
  Fase 1) — este é o primeiro bloco que efetivamente usa `HTML(...).write_pdf()`
  em produção.
- `apps/projetos/services.py::orientandos_atuais`,
  `views.py::orientacoes`, `templates/projetos/orientacoes.html` — pontos de
  extensão (§3.6, §7), mesmos arquivos estendidos nos Blocos C e D.
- `config/urls.py` — `apps.documentos.urls` entra com `path("",
  include("apps.documentos.urls"))`, mesmo padrão de `apps.bancas.urls`.

## 10. Testes

Seguindo a disciplina do CLAUDE.md (§"Disciplina de Testes"): toda checagem
nova provada por mutação. Casos mínimos:

- `aprovar_projeto` recusa fora de `APROVADO_COM_RESSALVAS`, recusa quem não
  é o orientador (404 na view); bem-sucedido: `Projeto.status == APROVADO`,
  `Ata` criada com `numero` no formato certo, `RevisaoSUGRAD` `PENDENTE`
  criada, e-mail enfileirado para a SUGRAD.
- Numeração: duas `Ata` no mesmo ano recebem números sequenciais
  (`001/2026`, `002/2026`); uma `Ata` de ano civil diferente reinicia a
  contagem.
- `aprovar_ata`/`devolver_ata` recusam quem não tem `papel == SUGRAD`
  (`PermissionDenied`, não 404 — não há lookup escopado por posse aqui,
  `/painel/sugrad/` é portão de papel); recusam decidir duas vezes
  (`ValidationError` fora de `PENDENTE`).
- `aprovar_ata`: `Projeto.status == CONCLUIDO`; sem e-mail disparado.
- `devolver_ata`: `RevisaoSUGRAD.status == DEVOLVIDA`, `comentario` gravado;
  e-mail enfileirado para o orientador; `Projeto.status` permanece
  `APROVADO` (mutação obrigatória: comente essa preservação e confirme que
  algum teste reprova).
- `reenviar_a_sugrad`: só a partir de `DEVOLVIDA`; volta para `PENDENTE`;
  e-mail enfileirado para a SUGRAD de novo; recusa quem não é o orientador.
- `orientandos_atuais` inclui `APROVADO_COM_RESSALVAS` e `APROVADO`, exclui
  `CONCLUIDO`.
- `/orientacoes/` mostra "Aprovar" / comentário+"Reenviar" / estado neutro
  para os três sub-estados de `APROVADO_COM_RESSALVAS`/`APROVADO`.
- `/painel/sugrad/` lista só atas `PENDENTE` (uma `DEVOLVIDA` some da lista
  até ser reenviada).

## 11. Critérios de aceitação

1. Orientador aprova um projeto `Aprovado com Ressalvas`; `Projeto.status`
   vira `Aprovado`; uma `Ata` é criada com PDF válido e número sequencial;
   e-mail enfileirado para a SUGRAD.
2. Aprovar fora de `Aprovado com Ressalvas`, ou por quem não é o orientador,
   é recusado (404 para posse, `ValidationError` para o estado).
3. A SUGRAD aprova a ata pendente; `Projeto.status` vira `Concluído`.
4. A SUGRAD devolve a ata com comentário; `Projeto.status` continua
   `Aprovado`; o orientador vê o comentário em `/orientacoes/` e recebe
   e-mail; a ata some de `/painel/sugrad/`.
5. Orientador reenvia uma ata devolvida; ela volta a aparecer em
   `/painel/sugrad/`; e-mail enfileirado para a SUGRAD.
6. Decidir a mesma ata duas vezes (aprovar/devolver) é recusado.
7. Quem não tem `papel == SUGRAD` não acessa `/painel/sugrad/` nem
   aprova/devolve atas.
8. Nenhuma das regras acima está implementada em `views.py` ou `models.py`.
9. `docker compose exec web pytest` passa, incluindo acessibilidade nas rotas
   novas.
