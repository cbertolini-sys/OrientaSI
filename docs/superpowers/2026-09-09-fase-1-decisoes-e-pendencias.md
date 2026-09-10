# Fase 1 — Decisões tomadas e pendências conhecidas

**Data:** 2026-09-09
**Branch:** `fase-1-fundacao-contas` (28 commits + onda de correção final)
**Suíte ao fim:** 244 testes passando, 8 pulados

Este documento registra as decisões tomadas durante a execução da Fase 1 que **não estão
no spec original** — porque contradizem algo que ele afirmava, porque resolvem uma
ambiguidade que ele deixou, ou porque foram descobertas só na implementação. Ele existe
para que a Fase 2 não redescubra o mesmo pelo caminho difícil.

Cada decisão traz o que custa se estiver errada.

---

## 1. Decisões que corrigiram o spec ou o plano

Estas são as mais importantes: o documento de projeto afirmava algo que a implementação
provou falso.

### 1.1 O travamento de linha do teto de coordenadores estava errado

O spec §6.3 justificava a proteção do teto de 4 coordenadores dizendo que "promover é um
`UPDATE` de uma linha que passa a integrar o próprio conjunto travado, então duas
promoções simultâneas se serializam".

**Isso é falso no PostgreSQL em READ COMMITTED.** O `SELECT ... WHERE is_coordenador=true
FOR UPDATE` escolhe as linhas candidatas pelo snapshot do início do comando; a linha do
alvo ainda era `false` ali, então nunca entrava no conjunto travado nem era reavaliada.
Reproduzido: duas transações leem 3 e o sistema termina com **5 coordenadores**.

**Correção:** travar `papel=PROFESSOR`, predicado que a promoção nunca altera. A exatidão
da contagem sob a trava é garantida pela `CheckConstraint` `coordenador_e_professor`, que
torna `papel=PROFESSOR` superconjunto estrito de `is_coordenador=True`.

**Assimetria a lembrar:** `revogar_coordenacao` **estava** correto pelo motivo oposto —
ali as linhas *saem* do conjunto travado e são reavaliadas corretamente.

### 1.2 O axe-core não detecta ausência de `<fieldset>`/`<legend>`

O plano afirmava que a suíte pegaria a falta de agrupamento em grupos de caixas de
seleção. As regras `checkboxgroup`/`radiogroup` foram **removidas do axe-core 4**.
Verificado rodando o axe sem o `fieldset`: zero violações.

**Consequência:** requisitos de acessibilidade que o axe não cobre precisam de teste
próprio. O `<legend>` do painel de perfil tem um.

### 1.3 O axe também não detecta ausência de `autocomplete`

O critério WCAG 2.1 AA 1.3.5 (Identify Input Purpose) exige tokens de `autocomplete`. A
regra do axe só valida valores **presentes**, não a ausência. Todo formulário novo precisa
de asserção própria.

### 1.4 As classes do DaisyUI 4 não valem no DaisyUI 5

Os templates do plano usavam `.label`, `.label-text`, `.form-control` e sufixos
`-bordered`. No v5 instalado, `.label` aplica esmaecimento de 60% e derruba o contraste do
rótulo para 4,38:1 — abaixo do mínimo AA. As demais não geram regra alguma.

**Referência canônica de formulário:** `templates/contas/aceitar_convite.html`.

### 1.5 O laranja institucional reprova contraste para texto

`#D9530E` com texto branco dá **4,04:1**, abaixo do mínimo AA de 4,5:1 — e escurecer o
texto não resolve (4,06:1). O tema usa **`#B8440B`** (5,43:1) no token de texto e preserva
`#D9530E` apenas para superfícies, bordas e ícones, onde 3:1 basta.

### 1.6 Três testes que o spec exigia não existiam

O plano trouxe versões reduzidas do que o spec §10.1 pedia, e a implementação seguiu à
risca. Faltavam: a metade "views não mutam models" da regra de arquitetura, o
`manage.py check --deploy`, e o "Esc fecha modal" — este último impossível, porque a Fase 1
não tem modal (usa `<details>/<summary>`, onde `Esc` não fecha por design).

Os dois primeiros foram implementados; o terceiro foi reescrito no spec.

---

## 2. Decisões de arquitetura tomadas na execução

### 2.1 Coordenador inativo ocupa vaga, e por isso é listado

Se não ocupasse, reativar uma quinta pessoa pelo admin furaria o teto sem passar por
`promover_a_coordenador` — a regra inegociável seria contornável sem trava.

Escolhida essa semântica, **listar o inativo é consequência forçada**: a única porta de
liberação de vaga na tela é "Revogar coordenação", que fica na linha do coordenador.
Escondê-lo travaria o sistema em "4 de 4" com saída apenas pelo admin.

*Custo se errado:* uma conta desativada segura uma vaga que talvez devesse estar livre.

### 2.2 O e-mail é canonizado para minúsculas na gravação

A normalização do Django minusculiza apenas o domínio, o que permitiria duas contas para a
mesma pessoa. Um sinal `pre_save` canoniza o endereço inteiro, e `get_by_natural_key` faz
busca insensível a caixa com queda defensiva para correspondência exata.

*Custo se errado:* endereços com maiúsculas na parte local são canonizados — nenhum
provedor real os trata como distintos.

### 2.3 O `semear_sistema` recusa nomear o segundo coordenador

O comando é bootstrap do **primeiro**. Os demais entram pelo painel, que aplica o teto.
Se todos os coordenadores forem removidos, o comando volta a liberar o bootstrap.

### 2.4 Tela autenticada não entra na lista de rotas anônimas

A suíte de acessibilidade navega anônima; acrescentar uma rota protegida faria as quatro
verificações medirem a **tela de login** e passarem. Telas autenticadas têm suíte própria,
com **âncora de identidade** (URL e texto do `<h1>` confirmados antes de qualquer outra
asserção).

Isto foi provado duas vezes na execução: sem a âncora, todas as verificações passam
medindo a página errada.

### 2.5 A validação de unicidade vive no formulário e no serviço

O formulário dá o erro no campo certo, que é o que a pessoa precisa ver; o serviço
converte `IntegrityError` em `ValidationError` como rede para corrida.

---

## 3. Riscos assumidos

### 3.1 O token do convite trafega em claro pelo broker

Só o hash é persistido, então o texto precisa trafegar de alguma forma. Ele fica no Redis
até o *ack* e é republicado a cada retentativa — e **entra no traceback** quando a tarefa
falha, indo para o log do worker.

*Saída, se um dia incomodar:* passar só o `convite_id` e guardar o token cifrado.

### 3.2 A proteção contra chamada síncrona insegura está desligada nos testes

O driver síncrono do Playwright confunde o detector de contexto assíncrono do Django. A
variável de escape é ligada na coleta quando a sessão inclui teste de navegador.
**O projeto não tem código assíncrono**, então a proteção desligada não protege nada hoje.

*Reavaliar:* na primeira view assíncrona.

### 3.3 Não há teste de concorrência para o travamento do convite

A prova é de SQL emitido (`FOR UPDATE` presente), não de corrida com duas conexões — ao
contrário do teto de coordenadores, que **tem** teste de concorrência real com threads.

---

## 4. Pendências conhecidas

Nenhuma é alcançável hoje; todas foram avaliadas e adiadas conscientemente.

| Pendência | Por que foi adiada |
|---|---|
| `MUTACOES` do teste de arquitetura não cobre `set`/`add`/`remove`/`clear` | `areas.set()` é o caso concreto que escaparia. **Pré-requisito do Bloco B.** |
| O teste de arquitetura pula em silêncio se `views.py` não existir | Um Bloco B com `views/` como pacote passaria a pular inteiro. **Pré-requisito do Bloco B.** |
| O spec §4.2 e §10.1 ainda descrevem a regra como "views não importam models" | Diverge do teste implementado, que asserta **mutação**. Documentação. |
| A troca para busca por igualdade exata depende do sinal de normalização | Uma linha em caixa mista exigiria importação fora do ORM, que não existe. |
| Com 1 coordenador ativo e 1 inativo, o ativo pode revogar a si mesmo | Deixaria um único coordenador que não autentica. Exige desativação pelo admin. |
| `createsuperuser` aceita CPF inválido | `_criar` não chama `full_clean`. Convite valida por formulário, admin por ModelForm, `semear_sistema` valida. |
| Um teste do `semear_sistema` não verifica a mensagem da exceção | Prova que falha, não que falha pelo motivo certo. Correção de uma linha. |
| HTMX e Alpine carregados sem uso | Fundação deliberada; a primeira tela do Bloco B os ativa. |

---

## 5. Pré-requisitos do Bloco B

Fazer **antes** de construir telas novas — as três dívidas se multiplicam por tela.

1. **Extrair `templates/contas/_campo.html`.** O bloco de renderização de campo está
   copiado em seis templates, incluindo os comentários. Foi a causa raiz de um defeito
   real: uma correção aplicada a duas telas não voltou para as outras duas, e o resumo de
   erros das telas de recuperação de senha ficou meses sem aparecer.
2. **Generalizar a lista de rotas para telas autenticadas.** A suíte de acessibilidade já
   foi bifurcada duas vezes, e as três cópias divergiram em três direções. O mecanismo que
   falta é pequeno: uma entrada de rota que carregue uma fábrica de usuário opcional.
3. **Fechar as duas pendências do teste de arquitetura** (mutações de M2M e o pulo
   silencioso).

---

## 6. Decisão pendente para o Bloco B

O `inicio.pdf` diz que a alocação de orientadores é feita **"por desempenho escolar"**, e o
sistema não tem de onde ler essa nota. Isso precisa ser resolvido no *brainstorm* do Bloco
B, antes de modelar `Candidatura`.
