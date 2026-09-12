# Bloco B — Mural de temas e alocação de orientação

**Data:** 2026-09-10
**Bloco:** B (de A–H)
**Depende de:** Bloco A (Fase 1), concluído e integrado na `main`
**Status:** aprovado para planejamento

---

## 1. Objetivo

O Bloco B liga alunos a orientadores. Ele termina quando um aluno registra até três
opções de orientação, um professor aceita, e nasce o `Projeto` de TCC I que o Bloco C vai
conduzir até a defesa.

O Bloco A entregou pessoas no sistema; este entrega o primeiro vínculo entre elas.

---

## 2. Escopo

### Dentro

- Mural de temas, visível apenas a quem tem cadastro.
- Painel do professor para publicar, editar e desativar os próprios temas.
- Candidatura do aluno com até três opções ordenadas.
- Cascata com prazo: uma opção por vez, avanço automático por recusa ou expiração.
- Fila do professor: aceitar ou recusar com justificativa.
- Criação do `Projeto` de TCC I no aceite.
- Regra das vagas por semestre, com exceção autorizada pela coordenação.
- Ajuste de orientação pela coordenação.
- Três notificações por e-mail, assíncronas.

### Fora

Submissões de arquivo, aprovação do projeto, notas, bancas, atas, TCC II, catálogo
público e API. O `Projeto` nasce aqui com status `Em Andamento` e nada mais.

---

## 3. Decisões de arquitetura

Cada decisão registra a alternativa recusada e o custo aceito.

### 3.1 Alocação contínua, por ordem de chegada

O `inicio.pdf` descreve dois mecanismos incompatíveis: aceite individual pelo professor
("se o professor aceita, o aluno fica como orientando") e alocação em lote ordenada por
desempenho escolar ("tem que ser por desempenho escolar a alocação").

**Decisão:** alocação contínua. O aluno manifesta interesse, o professor aceita quando
puder, e vale a ordem de chegada até as vagas encherem.

**Custo aceito e registrado:** um professor requisitado terá as vagas preenchidas por quem
manifestou interesse primeiro, e não por desempenho. A frase do documento sobre desempenho
escolar **não** é implementada.

**Consequência positiva:** o sistema não precisa de nota escolar. A pendência registrada no
fim da Fase 1 — "o `inicio.pdf` pressupõe desempenho escolar e o sistema não tem de onde
ler" — deixa de existir.

### 3.2 As três opções funcionam em cascata, com prazo

**Decisão:** o aluno registra até três alvos em ordem. O sistema envia apenas para o
primeiro. Se o professor recusar, ou não responder dentro de `PRAZO_RESPOSTA_DIAS`, o
sistema avança sozinho para o próximo.

Preserva o sentido da ordem escolhida e resolve o pior caso da alocação contínua: o aluno
preso esperando um professor que nunca responde.

**Recusadas:** enviar às três simultaneamente (a ordem de preferência perde sentido, e dois
professores podem avaliar um aluno já levado) e uma por vez com reescolha manual (a "1ª, 2ª
e 3ª opção" do documento deixa de existir, e o aluno fica sem recurso contra o silêncio).

### 3.3 O semestre é derivado da data

**Decisão:** o semestre vigente é calculado a partir da data corrente, com os meses de
corte em `settings`. Não existe modelo `Semestre` nem tela de manutenção.

**Custo aceito:** num ano de calendário deslocado — greve, reposição, pandemia — a virada
acontece na data errada e as contagens de vaga mudam no meio de um semestre real em
andamento. **Mitigação:** os meses de corte são configuráveis, então o ajuste é uma
constante, não uma migração.

**Recusadas:** modelo próprio mantido pela coordenação (mais robusto, mas exige tela e
trava de unicidade do vigente) e texto livre por registro (a contagem de vagas passaria a
depender de todos digitarem `2026/1` igual).

### 3.4 O carimbo do semestre é gravado como dois inteiros

**Decisão:** `Projeto` e `Candidatura` gravam `ano` (inteiro) e `periodo` (1 ou 2) no
momento da criação.

O semestre **vigente** é derivado da data; o semestre **gravado** é congelado. Se os meses
de corte forem ajustados depois, as contagens históricas não mudam retroativamente. Dois
inteiros são ordenáveis e imunes à deriva de `2026/1` contra `2026.1` contra `2026-1`.

### 3.5 A vaga conta apenas orientações iniciadas no semestre vigente

**Decisão:** a contagem considera `Projeto` cujo carimbo de semestre é o vigente.
Orientações de semestres anteriores, ainda em andamento, não pesam.

É a leitura literal do `CLAUDE.md` ("3 alunos em TCC I no semestre letivo vigente") e
libera vagas a cada virada sem ninguém precisar encerrar nada.

**Custo aceito:** um professor com três orientandos atrasados do semestre anterior pode
ficar com seis ativos simultâneos, que é o que o limite existe para impedir.

**Lacuna registrada na rodada de correção 1 da Tarefa 5, para não repetir a
investigação:** `vagas_ocupadas` filtra só pelo carimbo de semestre (`ano`, `periodo`),
sem filtrar por `status`. Pela leitura literal deste parágrafo — que só fala do carimbo
de semestre, não do status — um `Projeto` `REPROVADO` ou `CONCLUIDO` do semestre vigente
segue ocupando vaga até a virada do semestre seguinte. Inalcançável no Bloco B, onde só
`EM_ANDAMENTO` existe, mas o Bloco C introduz as transições de status e encosta
diretamente nisso: **este parágrafo não decide o caso, e precisa decidir antes do
Bloco C** — se um projeto encerrado (aprovado, reprovado ou concluído) libera a vaga
imediatamente ou só na virada do semestre.

**Recusada:** contar toda orientação ativa independentemente do semestre de início — mais
fiel à carga de trabalho real, mas exigiria que alguém encerrasse vínculos para liberar
vaga.

### 3.6 O teto de 3 admite exceção autorizada pela coordenação

**Decisão:** 3 continua sendo o teto padrão e o bloqueio segue automático. A coordenação
pode elevar o teto de um professor específico, para uma etapa específica, num semestre
específico, com justificativa obrigatória e autoria registrada.

Isto **flexibiliza** a regra que o `CLAUDE.md` descreve como inegociável. Por isso:

- a autorização vale por semestre e por etapa, e morre com eles — uma exceção pontual não
  vira permanente por esquecimento;
- a justificativa é obrigatória e quem autorizou fica registrado, porque a decisão precisa
  sobreviver à memória de quem estava na coordenação;
- revogar a autorização **não** desfaz orientações já aceitas: trava o próximo aceite.
  Desvincular alunos retroativamente seria pior que a exceção.

**O `CLAUDE.md` será atualizado** para descrever o teto com sua exceção. Documento que
descreve regra mais rígida que o sistema aplica faz alguém confiar numa trava inexistente.

**Recusadas:** autorização caso a caso por aluno (controle mais fino, mas cria um fluxo de
aprovação com espera, e-mail e mais uma fila) e alocação direta pela coordenação sem teto
(o professor não conseguiria aceitar o quarto aluno nem sabendo que foi autorizado).

### 3.7 O aceite cria o `Projeto`, não um vínculo intermediário

**Decisão:** quando o professor aceita, nasce um `Projeto` com `etapa=TCC_I` e status
`Em Andamento`. O Bloco C acrescenta submissões, aprovação e a máquina de status.

É o que o documento descreve: o vínculo aceito **é** o TCC começando. E torna a contagem de
vagas inequívoca.

**Recusadas:** um modelo `Orientacao` que o Bloco C converteria em `Projeto` (duplica o
vínculo em duas tabelas e cria uma conversão que pode falhar pela metade) e usar a própria
`Candidatura` aceita como vínculo (o modelo passaria a significar pedido e orientação
vigente ao mesmo tempo).

### 3.8 O prazo avança por tarefa periódica, com agendamento estático

**Decisão:** um serviço `celery_beat` no `docker-compose.yml`, rodando `celery -A config
beat`, com `CELERY_BEAT_SCHEDULE` estático em `settings.py`. Uma tarefa horária busca
opções com prazo vencido e avança a cascata.

**Recusada — avaliação preguiçosa na leitura:** não exigiria infraestrutura, mas derrota o
propósito da cascata. Se ninguém abrir a tela certa, nada avança, e o aluno segue preso
esperando — exatamente o cenário que a cascata veio resolver.

**Recusada — `django-celery-beat`:** só se paga quando alguém precisa mudar a periodicidade
pela interface, e ninguém precisa. O agendamento estático dispensa a dependência.

---

## 4. Modelagem de dados

Tudo em `apps/projetos/`, hoje vazia.

### 4.1 `Tema`

| campo | tipo | observações |
|---|---|---|
| `professor` | FK `PerfilProfessor` | |
| `area` | FK `contas.Area` | validado em serviço: ∈ `professor.areas` |
| `titulo` | CharField(200) | |
| `descricao` | TextField | |
| `ativo` | BooleanField | `default=True`; desativado some do mural sem apagar histórico |
| `criado_em` | DateTimeField | `auto_now_add` |

**Lacuna registrada na rodada de correção 1 da Tarefa 6, para não repetir a
investigação:** `editar_tema` (§5) permite editar título, descrição e área mesmo depois de
o tema já ter recebido candidatura — o spec (§2 e §6) concede a edição sem condicioná-la, e
`OpcaoCandidatura.tema` aponta para o MESMO registro, não para uma cópia. Editar um tema
depois que um aluno já se candidatou a ele muda a oferta debaixo de quem se candidatou: o
título, a descrição ou a área que o aluno viu ao escolher deixam de bater com o que está
gravado, retroativamente, sem aviso a ninguém. O Bloco B não guarda registro do que o aluno
viu — `OpcaoCandidatura` tem só a FK, sem cópia de título ou descrição —, então a divergência
não é sequer detectável aqui; o Bloco C, que introduz prazo e cascata sobre essas opções, encosta
diretamente nisso: **este parágrafo não decide o caso, e precisa decidir antes do Bloco C**
— se editar um tema com candidatura pendente deve ser bloqueado, avisar o aluno, ou versionar
o tema em vez de sobrescrevê-lo.

### 4.2 `Candidatura`

Um pedido do aluno, com até três alvos.

| campo | tipo | observações |
|---|---|---|
| `aluno` | FK `PerfilAluno` | |
| `status` | CharField | `EM_CURSO` \| `ACEITA` \| `ESGOTADA` \| `CANCELADA` |
| `opcao_atual` | SmallInteger | 1 a 3; onde a cascata está |
| `ano`, `periodo` | Integer | carimbo do semestre |
| `criado_em` | DateTimeField | |

Trava: uma `Candidatura` com status `EM_CURSO` por aluno.

### 4.3 `OpcaoCandidatura`

| campo | tipo | observações |
|---|---|---|
| `candidatura` | FK `Candidatura` | |
| `ordem` | SmallInteger | 1, 2 ou 3 |
| `professor` | FK `PerfilProfessor` | |
| `tema` | FK `Tema` | nulo = "aberto a temas" |
| `situacao` | CharField | `AGUARDANDO` \| `ENVIADA` \| `ACEITA` \| `RECUSADA` \| `EXPIRADA` \| `CANCELADA` |
| `enviada_em`, `prazo`, `respondida_em` | DateTimeField | nulos até acontecerem |
| `justificativa` | TextField | `blank`; preenchida na recusa |

Travas: `(candidatura, ordem)` única; `ordem` entre 1 e 3; `tema` nulo ou pertencente ao
`professor` da própria opção.

**Achado da Tarefa 4, registrado para não repetir a investigação:** as duas primeiras são
`UniqueConstraint`/`CheckConstraint` comuns, mas a terceira ("tema pertencente ao professor")
não é expressável como `CheckConstraint` — o `CHECK` do PostgreSQL não permite join nem
subquery contra outra tabela, e o Django recusa a tentativa (`FieldError: Joined field
references are not permitted in this query`) ao aplicar a migração. Ela exige uma trigger de
banco (o caminho implementado, via `RunSQL`) ou uma FK composta `(tema_id, professor_id)`
contra um `UniqueConstraint(id, professor)` em `Tema`. Qualquer trava futura desta forma
("campo X deve ser consistente com um campo de outra tabela") tem a mesma limitação — vale
checar antes de especificá-la como `CheckConstraint` simples.

### 4.4 `Projeto`

| campo | tipo | observações |
|---|---|---|
| `aluno` | FK `Usuario` | |
| `orientador` | FK `Usuario` | |
| `tema` | FK `Tema` | nulo |
| `etapa` | CharField | `TCC_I` \| `TCC_II` |
| `status` | CharField | ciclo completo do `CLAUDE.md`; só `EM_ANDAMENTO` alcançável neste bloco |
| `ano`, `periodo` | Integer | carimbo; congela a contagem de vagas |
| `criado_em` | DateTimeField | |

Trava: um `Projeto` ativo por aluno por etapa (`UniqueConstraint` condicional ao status).

### 4.5 `LimiteOrientacao`

| campo | tipo | observações |
|---|---|---|
| `professor` | FK `PerfilProfessor` | |
| `etapa` | CharField | `TCC_I` \| `TCC_II` |
| `ano`, `periodo` | Integer | a autorização vale por semestre |
| `limite` | PositiveSmallInteger | `CheckConstraint`: maior que `LIMITE_PADRAO_VAGAS` |
| `justificativa` | TextField | obrigatória |
| `autorizado_por` | FK `Usuario` | |
| `criado_em` | DateTimeField | |

Trava: `(professor, etapa, ano, periodo)` única.

### 4.6 Cálculo do semestre

`apps/comum/semestre.py` expõe `semestre_vigente() -> (ano, periodo)`, derivado da data
corrente e dos meses de corte definidos em `settings`.

---

## 5. Camada de serviço

`apps/projetos/services.py`. Nenhuma destas regras aparece em `views.py` ou `models.py`.

```
criar_tema(professor, area, titulo, descricao, por)      valida área ∈ professor.areas
editar_tema(tema, area, titulo, descricao, por)          valida área ∈ professor.areas
desativar_tema(tema, por)
registrar_candidatura(aluno, opcoes)      → Candidatura  @atomic; dispara a 1ª opção
aceitar_opcao(opcao, por)                 → Projeto      @atomic; revalida vaga sob trava
recusar_opcao(opcao, por, justificativa)                 avança a cascata
avancar_cascata(candidatura)                             usada pela recusa e pelo prazo
cancelar_candidatura(candidatura, por)
trocar_orientador(projeto, novo, por)                    coordenação; revalida vaga
conceder_limite(professor, etapa, limite, justificativa, por)
revogar_limite(limite, por)
vagas_ocupadas(professor, etapa, ano, periodo)   → int
limite_do_professor(professor, etapa, ano, periodo) → int
```

`apps/projetos/permissions.py`: `pode_criar_tema`, `pode_criar_tema_para`,
`pode_editar_tema`, `pode_desativar_tema`, `pode_responder_opcao`,
`pode_ajustar_orientacao`, `pode_conceder_limite`.

`pode_criar_tema` é permissão de **papel** (quem pede é professor com perfil); as três
seguintes são de **posse** (o tema é de quem pede). A distinção decide a ordem nas views que
recebem um `<id>` na URL (`editar_tema`, `desativar_tema`): o portão de papel roda primeiro,
antes de tocar `perfil_professor`, e a posse é aplicada escopando o próprio lookup
(`get_object_or_404(Tema, pk=..., professor=...)`), para que "não é seu" e "não existe"
respondam o mesmo 404 — sem isso a URL vira um oráculo de existência sobre temas desativados
de outros professores, que o mural não lista. `pode_criar_tema_para` não tem lookup a escopar:
é aplicada dentro de `criar_tema`, sobre o `professor` recebido como argumento. Os serviços
mantêm a checagem de posse **também** quando a view já escopou o lookup — a redundância é o
que protege um chamador que não escope (outro serviço, um comando de management).

### 5.1 Escolher um professor sem vaga

`registrar_candidatura` **recusa** opções que apontem para professor já no limite da etapa
no semestre vigente, com mensagem nomeando o professor.

A alternativa — aceitar a opção e deixá-la falhar no aceite — desperdiça o tempo das duas
pessoas: o professor avalia uma manifestação que não pode aceitar, e o aluno consome uma
das três opções num alvo impossível. Como as vagas só se liberam na virada do semestre
(decisão 3.5), não há cenário em que esperar valha a pena.

O mural marca quem ainda tem vaga, para a escolha ser informada antes da recusa.

### 5.2 A máquina da candidatura

```
registrar_candidatura
        │
        ▼
  opção 1 ENVIADA ──── aceita ──▶ Projeto criado
   (prazo: 7 dias)                candidatura ACEITA
        │                         opções restantes → CANCELADA
        ├── recusada ──┐
        └── expirada ──┤
                       ▼
              existe próxima opção?
                  sim ──▶ envia, reinicia o prazo
                  não ──▶ candidatura ESGOTADA
```

`ESGOTADA` notifica **a coordenação**, além do aluno: quem esgotou as três opções é
precisamente quem precisa de alocação manual, e a coordenação é quem tem esse poder. Se o
estado só existir na tela do aluno, ninguém age.

### 5.3 A regra das vagas e o travamento

```python
LIMITE_PADRAO_VAGAS = 3
PRAZO_RESPOSTA_DIAS = 7   # em settings.py, junto das demais constantes do projeto
```

Aplicada em **`aceitar_opcao` e `trocar_orientador`**, nunca só numa das duas — o ajuste da
coordenação não pode ser a porta dos fundos por onde a regra é contornada.

**O travamento é diferente do usado no Bloco A, e a diferença importa.**

No Bloco A, o teto de coordenadores foi protegido travando linhas de professores, porque
promover é um `UPDATE` de linha existente: travar um conjunto que já a contém serializa as
transações.

Aqui, aceitar é um `INSERT` de `Projeto` novo. Travar os `Projeto` existentes **não** impede
outra transação de inserir mais um — é leitura fantasma, e a linha nem existe para ser
travada. A saída é travar a **linha do professor**, que é o recurso disputado:

```python
with transaction.atomic():
    professor = PerfilProfessor.objects.select_for_update().get(pk=professor.pk)
    if vagas_ocupadas(...) >= limite_do_professor(...):
        raise ValidationError(...)
    Projeto.objects.create(...)
```

Duas aceitações simultâneas para o mesmo professor disputam a mesma linha: a segunda
espera, relê contagem e limite já atualizados, e é recusada. Para professores diferentes não
há contenção.

**As duas leituras acontecem depois do bloqueio.** Se o limite fosse lido antes, duas
transações concorrentes poderiam usar valores diferentes.

**Aceitar revalida a vaga dentro da transação.** O e-mail que o professor recebeu pode ter
dias, e as vagas podem ter enchido nesse meio-tempo: a tela oferecer "aceitar" não é
promessa de que ainda cabe.

---

## 6. Telas

Todas autenticadas.

| rota | quem | o quê |
|---|---|---|
| `/temas/` | autenticado | mural, com filtro por área |
| `/temas/meus/` | professor | criar e desativar os próprios, e listar todos |
| `/temas/<id>/editar/` | professor dono | editar um tema seu |
| `/candidatura/` | aluno | montar, acompanhar e cancelar |
| `/orientacoes/` | professor | fila de manifestações e orientandos atuais |
| `/painel/orientacoes/` | coordenação | visão geral, troca de orientador, limites |

A justificativa da recusa é obrigatória e chega ao aluno. Sem ela, a recusa é silêncio com
outro nome, e o aluno não tem como decidir o próximo passo.

---

## 7. Notificações

Três, todas por Celery, seguindo o padrão do convite do Bloco A: `transaction.on_commit`,
retentativa com recuo exponencial, e teste capturando os callbacks.

1. Manifestação de interesse, ao professor.
2. Recusa, ao aluno, com a justificativa.
3. Esgotamento das três opções, à coordenação e ao aluno.

---

## 8. Pré-requisitos herdados da Fase 1

Ambos foram registrados como dívida no fim do Bloco A. Cinco telas autenticadas novas os
tornam bloqueantes, e por isso são as **duas primeiras tarefas** do plano.

**8.1 Generalizar a lista de rotas da suíte de acessibilidade.** Hoje ela cobre rotas
anônimas; cada tela autenticada ganhou arquivo próprio, e as três cópias já divergiram em
três direções — uma roda numa largura só, duas ficaram acidentalmente mais estritas que a
régua oficial. Cinco telas fariam mais cinco cópias. Falta uma entrada de rota que carregue
uma fábrica de usuário opcional.

**8.2 Extrair `templates/contas/_campo.html`.** O bloco de renderização de campo está
copiado seis vezes. Foi a causa raiz de um defeito real: uma correção aplicada a duas telas
não voltou para outras duas, e o resumo de erros ficou invisível nas telas de recuperação de
senha. Cinco formulários novos copiariam o problema cinco vezes.

Junto deles, fechar as duas pendências do teste de arquitetura registradas na Fase 1: a
lista de mutações não cobre `set`/`add`/`remove`/`clear` — e `areas.set()` é o caso concreto
que escaparia — e o teste pula em silêncio se `views.py` não existir, o que aconteceria se
este bloco usasse `views/` como pacote.

---

## 9. Testes

**O teste de concorrência vem antes da tela de aceite.** A Fase 1 terminou com um teste
assim porque a justificativa escrita no spec original estava errada, e só a reprodução
revelou. Aqui o risco tem outra forma — leitura fantasma num `INSERT` — e o travamento por
linha de professor será provado, não afirmado: duas aceitações simultâneas resultam em uma
recusa.

**A cascata é testada com controle do tempo**, manipulando `prazo` diretamente, sem `sleep`
e sem depender do relógio. A tarefa periódica tem teste próprio: opções vencidas avançam,
opções no prazo não.

**Cada transição da máquina tem teste**, incluindo as que ninguém lembra: recusar opção já
respondida, aceitar depois de o aluno cancelar, aceitar quando as vagas encheram entre o
e-mail e o clique, conceder limite a professor que já está no teto.

**As seis rotas entram na suíte de acessibilidade** com âncora de identidade — URL e texto
do `<h1>` confirmados antes de qualquer outra asserção. Sem isso, uma rota quebrada passa
medindo a tela de login, e isso já aconteceu duas vezes neste projeto.

Rota com `<id>` de banco na URL entra na mesma lista `ROTAS`, com `caminho` callable
resolvido depois da fábrica — **não** em suíte própria ao lado. `/temas/<id>/editar/` é a
única do Bloco B (as demais rotas do bloco são caminhos estáticos), mas a regra vale para
qualquer rota dinâmica futura: uma suíte própria roda o axe e esquece as outras quatro
verificações, e foi exatamente assim que um alvo de toque de 24px passou despercebido numa
tela nova.

Valem as lições da Fase 1 que custaram rodadas de correção: `autocomplete` onde se aplica;
`<fieldset>`/`<legend>` em grupos de opção, com teste próprio, porque o axe não detecta a
ausência; tabela em contêiner rolante **com `tabindex`**; alvo de toque medido a 360px e a
1280px; e o resumo de erros condicionado a `formulario.errors`, não a `non_field_errors`.

---

## 10. Critérios de aceitação

1. `docker compose up -d` sobe também o `celery_beat`, saudável.
2. Um professor publica um tema dentro de uma das suas áreas; tema fora das áreas dele é
   recusado.
3. Um tema desativado some do mural e continua visível nas candidaturas que o referenciam.
4. Um aluno registra três opções; apenas o primeiro professor recebe e-mail.
5. O primeiro professor recusa com justificativa; o segundo recebe e-mail; o aluno lê a
   justificativa.
6. Uma opção vence o prazo; a tarefa periódica avança sozinha para a seguinte.
7. Esgotadas as três, a candidatura fica `ESGOTADA` e a coordenação é notificada.
8. Um professor aceita; nasce o `Projeto` com `etapa=TCC_I` e status `Em Andamento`.
9. O quarto aceite do mesmo professor, na mesma etapa e semestre, é recusado com mensagem
   clara.
10. A coordenação eleva o limite daquele professor com justificativa; o quarto aceite passa.
11. Revogar o limite não desfaz os projetos já criados, e trava o próximo aceite.
12. A coordenação troca o orientador de um projeto; a vaga do professor novo é revalidada.
13. Duas aceitações simultâneas para o mesmo professor no último lugar resultam em uma
    recusa, provado por teste com conexões reais.
14. `docker compose exec web pytest` passa, incluindo acessibilidade nas seis rotas novas.
15. Nenhuma das regras acima está implementada em `views.py` ou `models.py`.
