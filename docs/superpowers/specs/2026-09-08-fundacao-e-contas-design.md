# OrientaSI — Fase 1: Fundação e Contas

**Data:** 2026-09-08
**Bloco:** A (de A–H; ver §12)
**Status:** aprovado para planejamento

---

## 1. Objetivo

O OrientaSI é o sistema de gestão de TCC do curso de Sistemas de Informação. Este
documento especifica a **Fase 1**: a fundação técnica do projeto e a app de contas.

A Fase 1 termina quando uma pessoa é convidada por e-mail, se cadastra pelo link do
convite e entra no sistema — com toda a infraestrutura (Docker, Celery, MinIO,
design system, suíte de acessibilidade) verificada em funcionamento.

Os blocos B–H (temas, TCC I, bancas, atas, TCC II, catálogo público, API) recebem
cada um seu próprio ciclo de spec, plano e implementação. §12 mapeia o domínio
inteiro para que as fronteiras da Fase 1 sejam escolhas conscientes.

---

## 2. Escopo

### Dentro da Fase 1

- `docker-compose.yml` com `web`, `db`, `redis`, `celery_worker`, `minio` e o
  auxiliar `tailwind` (desenvolvimento).
- Esqueleto Django: `config/`, `apps/comum/`, `apps/contas/` e as apps `projetos/`,
  `bancas/` e `documentos/` criadas, registradas e vazias.
- Design system: Tailwind v4 + DaisyUI com tema institucional; HTMX e Alpine.js
  vendorizados.
- Suíte de testes com Playwright + axe-core rodando dentro do container.
- Modelo de usuário próprio (login por e-mail), perfis de aluno e professor,
  vocabulário de áreas.
- Convites por e-mail com token de uso único, enviados por Celery.
- Regra dos 4 coordenadores e trava do último coordenador.
- Conta única da SUGRAD, semeada por comando de gestão.
- Recuperação de senha.

### Fora da Fase 1

Mural de temas, candidaturas, projetos de TCC, bancas, avaliações, atas, painel da
SUGRAD, catálogo público, calendário público e API DRF. O modelo `ProfessorExterno`
também fica fora (§5.6).

---

## 3. Decisões de arquitetura

Cada decisão registra a alternativa recusada, porque o custo de reabrir uma decisão
sem saber por que ela foi tomada é alto.

### 3.1 Camada visual: Tailwind v4 + DaisyUI, construído do zero

O CLAUDE.md pede duas coisas incompatíveis: usar Tailwind com DaisyUI/Flowbite **e**
copiar o CSS e o layout de um projeto de referência que é CSS artesanal, com ~90KB
escritos à mão, tokens em `:root` e nenhum passo de build.

**Decisão:** construir com Tailwind v4 + DaisyUI, preservando do projeto de
referência apenas a **paleta institucional**, transposta para tokens do tema.

**Consequência aceita:** o layout do OrientaSI não será visualmente idêntico ao do
projeto de referência; a continuidade é cromática e tipográfica, não estrutural.
Entra Node no ciclo de build (§8.2).

### 3.2 DaisyUI, não Flowbite

Os dois oferecem `.btn`, `.card` e `.modal` com estilos diferentes; carregar ambos
duplica CSS e cria disputa de especificidade.

**Decisão:** apenas DaisyUI. Ele é CSS puro. O Flowbite embarca JavaScript próprio
para dropdown, prisão de foco em modal e abas — precisamente o papel que o CLAUDE.md
atribui ao Alpine.js. Dois frameworks disputando o mesmo evento de clique é a causa
clássica de modal que ignora `Esc`.

**Regra decorrente:** aparência vem do DaisyUI, comportamento vem do Alpine. Nenhum
componente mistura as duas origens.

### 3.3 Idioma do código: português

O `inicio.pdf` nomeia apps e modelos em inglês (`apps/accounts`, `StudentProfile`);
o CLAUDE.md declara o português como idioma oficial do projeto; o projeto de
referência nomeia tudo em português.

**Decisão:** apps, modelos, campos, funções e serviços em português —
`apps/contas`, `apps/projetos`, `apps/bancas`, `apps/documentos`. O CLAUDE.md é
atualizado para refletir os nomes reais.

### 3.4 Papéis: um `Usuario` com perfis 1-1 e flag de coordenação

**Decisão:** um único modelo `Usuario` com `papel` (`ALUNO`, `PROFESSOR`, `SUGRAD`)
mais o booleano `is_coordenador`, e perfis ligados por relação 1-1.

Modela o que os documentos descrevem — o professor **é** orientador e **pode ser**
coordenador — sem duplicar a pessoa. A regra dos 4 coordenadores vira uma contagem
direta em `services.py`.

**Recusadas:** papéis via *Groups* do Django (tornam as duas regras inegociáveis
consultas indiretas por `Group.user_set`, oferecendo uma flexibilidade que um
domínio de papéis fixos não usa) e herança multi-tabela `Aluno(Usuario)` /
`Professor(Usuario)` (promover alguém ou corrigir um convite trocado exigiria migrar
linhas entre tabelas).

### 3.5 Autenticação: e-mail e senha próprios

**Decisão:** convite por e-mail com token de uso único; ao abrir o link, a pessoa
preenche seus dados e define a própria senha. `USERNAME_FIELD` é o e-mail.
Recuperação de senha pelo fluxo padrão do Django.

**Recusado:** SSO institucional — depende de liberação externa, é impossível de
exercitar em Docker local sem simulação e travaria a Fase 1 numa dependência de
terceiro. Também recusada a camada de indireção "senha agora, SSO depois": abstração
para um requisito que não existe.

### 3.6 SUGRAD: conta única do setor

**Decisão:** uma única conta compartilhada, semeada pelo comando `semear_sistema`,
sem passar pelo fluxo de convite.

**Consequência aceita e registrada:** a ata poderá afirmar que foi aprovada pela
SUGRAD em determinada data, mas **não** registrará qual servidor a aprovou. Se a
rastreabilidade nominal virar exigência de auditoria, a migração para contas
individuais altera o modelo, não o fluxo.

### 3.7 Configuração: um `settings.py` único dirigido por ambiente

**Decisão:** arquivo único, lendo variáveis de ambiente, com a variável `AMBIENTE`
(`dev` | `producao`) selecionando o bloco de segurança.

MinIO **não** é um back-end diferente do S3 — ele fala o protocolo S3, e o
`django-storages` usa a mesma classe para os dois; muda apenas o endpoint. Não há,
portanto, divergência de back-end que justifique dividir arquivos. O risco real do
arquivo único é subir em produção com configuração insegura em silêncio, e a defesa
para isso não é dividir arquivos, e sim impor os valores em vez de lê-los:

```python
AMBIENTE = os.environ.get("AMBIENTE", "dev")

if AMBIENTE == "producao":
    DEBUG = False                            # constante, não variável
    SECRET_KEY = obrigatorio("SECRET_KEY")   # ImproperlyConfigured se ausente
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31_536_000
else:
    DEBUG = True
    SECRET_KEY = os.environ.get("SECRET_KEY", "chave-de-desenvolvimento")
    INSTALLED_APPS += ["debug_toolbar"]
```

**Recusada** a divisão `base/dev/prod`: convenção legítima do Django, que se paga em
projetos com muitos ambientes (staging, homologação, CI, produção). Aqui são dois.

### 3.8 Estáticos por WhiteNoise, mídia por S3/MinIO

**Decisão:** WhiteNoise serve CSS e JS a partir do Gunicorn, com hash no nome e
cache longo; `django-storages` cuida só do que os usuários enviam — fotos, PDFs e
`.docx`. Dispensa nginx como requisito para arquivo estático e reserva o bucket ao
conteúdo que realmente precisa dele.

---

## 4. Estrutura de diretórios

```
OrientaSI/
├── docker-compose.yml
├── Dockerfile
├── .dockerignore  .env.example  .gitignore
├── pyproject.toml               # configuração de ruff, black e pytest
├── requirements.txt             # dependências de produção
├── requirements-dev.txt         # dependências de desenvolvimento e teste
├── package.json                 # tailwindcss, daisyui
├── manage.py  conftest.py  CLAUDE.md
│
├── config/
│   ├── settings.py              # único, dirigido por AMBIENTE (§3.7)
│   ├── celery.py                # app Celery + autodiscover
│   ├── urls.py  asgi.py  wsgi.py
│   └── saude.py                 # healthcheck consumido pelo compose
│
├── apps/
│   ├── comum/                   # validators de upload, mixins, template tags
│   ├── contas/                  # única app implementada na Fase 1
│   ├── projetos/                # criada, registrada, vazia  [Blocos B–C]
│   ├── bancas/                  # criada, registrada, vazia  [Bloco D]
│   └── documentos/              # criada, registrada, vazia  [Bloco E]
│
├── templates/                   # base.html, contas/, registration/, email/
├── static/
│   ├── css/entrada.css          # fonte: @import tailwindcss + @theme
│   ├── js/                      # htmx.min.js, alpine.min.js, alpine-focus.min.js
│   ├── fonts/                   # Inter e Jakarta vendorizadas
│   └── img/                     # logo e ícone do OrientaSI
├── tests/                       # transversais: acessibilidade, arquitetura, produção
└── docs/superpowers/specs/
```

### 4.1 Anatomia de `apps/contas/`

```
contas/
├── models.py                    # só estrutura: campos, Meta, __str__
├── services.py                  # toda regra de negócio, @transaction.atomic
├── permissions.py               # garante(), pode_convidar(), pode_promover()
├── validators.py                # CPF, SIAPE, matrícula
├── tasks.py                     # Celery: enviar_convite, enviar_recuperacao
├── forms.py  views.py  urls.py  admin.py
├── management/commands/semear_sistema.py
├── migrations/
└── tests/                       # test_services.py, test_views.py, test_regras.py
```

### 4.2 Justificativas estruturais

**`apps/comum/` existe desde a Fase 1** porque o Django serializa o *caminho de
importação* do validator dentro do arquivo de migração. Um `valida_tamanho_arquivo`
que nascesse em `contas` e depois fosse usado por `documentos` não poderia ser
movido sem editar migrações já aplicadas. Como a regra de upload do CLAUDE.md
(extensões `.pdf` e `.docx`, máximo de 15MB) atravessa três apps, o validator nasce
no lugar definitivo. Na Fase 1 ele já serve à foto de perfil.

**As apps vazias existem desde o início** para fixar as fronteiras antes de haver
código para mover, e para que `tests/test_arquitetura.py` possa rodar desde já as
duas asserções que sustentam a convenção do projeto: nenhuma view importa `models`
sem passar por `services`, e nenhum `models.py` importa `services`. Sem um teste que
a defenda, a convenção de `services.py` vira comentário no CLAUDE.md.

---

## 5. Modelagem de dados — `apps/contas`

### 5.1 `Usuario` (AbstractBaseUser, PermissionsMixin)

| campo | tipo | observações |
|---|---|---|
| `email` | EmailField | `unique`, `USERNAME_FIELD` |
| `nome_completo` | CharField(200) | |
| `cpf` | CharField(11) | `unique`, `null=True` — só dígitos |
| `telefone` | CharField(20) | `blank=True` |
| `foto` | ImageField | validators de extensão e tamanho (`apps.comum`) |
| `papel` | CharField | `ALUNO` \| `PROFESSOR` \| `SUGRAD` |
| `is_coordenador` | BooleanField | `default=False` |
| `is_active`, `is_staff`, `is_superuser` | | de `PermissionsMixin` |
| `criado_em` | DateTimeField | `auto_now_add` |

Restrições de banco:

1. `cpf_obrigatorio_para_pessoas` — `CheckConstraint`: `cpf` não nulo quando `papel`
   é `ALUNO` ou `PROFESSOR`. A conta da SUGRAD é um setor, não uma pessoa, e não tem
   CPF; no PostgreSQL valores nulos não colidem em índice único, então `unique`
   continua valendo para quem tem CPF.
2. `conta_sugrad_unica` — `UniqueConstraint(fields=["papel"], condition=Q(papel="SUGRAD"))`.
   Índice parcial: o banco recusa a segunda conta SUGRAD. A decisão 3.6 é imposta
   pelo esquema, não pela disciplina de quem escreve o código.
3. `coordenador_e_professor` — `CheckConstraint`: `is_coordenador=True` implica
   `papel=PROFESSOR`. Aluno coordenador passa a ser estado inalcançável, não estado
   indesejado.

`is_staff` acompanha `is_coordenador`: o coordenador é o administrador do sistema.

### 5.2 `PerfilAluno`

Relação 1-1 com `Usuario`, `related_name="perfil_aluno"`. Campo: `matricula`
(CharField, `unique`).

### 5.3 `PerfilProfessor`

Relação 1-1 com `Usuario`, `related_name="perfil_professor"`. Campos: `siape`
(CharField, `unique`) e `areas` (ManyToMany para `Area`).

### 5.4 `Area`

Vocabulário controlado: `nome` (CharField, `unique`) e `descricao` (TextField,
`blank`).

Fica em `apps/contas` e não em `apps/projetos` porque essa é a única direção de
dependência acíclica: `projetos` já importará de `contas` (todo projeto aponta para
um `Usuario`), enquanto o inverso criaria ciclo. Se surgirem outras tabelas de
referência — linhas de pesquisa, titulações —, elas puxam um `apps/referenciais` e
`Area` migra junto; uma tabela só não justifica uma app.

Na Fase 1 o vocabulário é mantido pelo coordenador via Django admin (ele já é
`is_staff`); o professor escolhe as suas na tela de perfil. Uma tela de CRUD
dedicada não se paga enquanto ninguém além do coordenador edita áreas.

No Bloco B, `Tema` terá `FK` para `Area` e para `PerfilProfessor`, com validação em
`projetos/services.py` de que a área do tema pertence às áreas declaradas pelo
professor.

### 5.5 `Convite`

| campo | tipo | observações |
|---|---|---|
| `email` | EmailField | destinatário |
| `papel` | CharField | `ALUNO` \| `PROFESSOR` (SUGRAD não é convidada) |
| `token_hash` | CharField | `unique` |
| `criado_por` | FK Usuario | |
| `criado_em` | DateTimeField | `auto_now_add` |
| `expira_em` | DateTimeField | padrão: 7 dias |
| `usado_em` | DateTimeField | `null` |
| `usuario_criado` | FK Usuario | `null` — quem nasceu do convite |

**O token é guardado como hash, nunca em claro.** O texto do token existe apenas no
corpo do e-mail, como o Django faz na recuperação de senha. Se o banco vazar, os
convites pendentes não são utilizáveis.

**Risco assumido, não omissão: o token em claro passa pelo broker.**
`services.convidar` enfileira `enviar_convite(convite_id, token)`, então o token
viaja como argumento da mensagem Celery e fica no Redis até o `ack` — republicado
a cada tentativa, já que `CELERY_TASK_ACKS_LATE` está ligado e a tarefa repete em
recuo exponencial. A justificativa original parava aqui; a revisão final
acrescentou o que faltava: **o token também entra no traceback quando
`enviar_convite` levanta**, porque os argumentos da tarefa aparecem no registro de
falha do Celery — e tracebacks vão para o log do worker, que costuma ser retido
por mais tempo e lido por mais gente do que o próprio broker.

Aceito para a Fase 1 porque o Redis é interno à stack, o token vale 7 dias, é de
uso único e dá acesso apenas ao cadastro de uma conta nova com um e-mail que o
próprio convite já fixa. **A saída, se um dia incomodar:** passar só o
`convite_id` na mensagem e guardar o token cifrado (não o hash — o e-mail precisa
do texto) numa coluna própria, decifrando dentro da tarefa. O custo é uma chave de
cifra para gerenciar; o ganho é que nem o broker nem o log do worker chegam a ver
o token.

### 5.6 `ProfessorExterno` — adiado para o Bloco D

O `inicio.pdf` coloca `ExternalTeacherProfile` na app de contas, mas nada na Fase 1
lê ou escreve nessa tabela. Uma tabela sem escritor é uma tabela cujo formato
ninguém validou; quando as bancas forem implementadas, saberemos exatamente de que
campos ela precisa. O nome fica reservado em `apps/contas`.

---

## 6. Camada de serviço

`apps/contas/services.py` — nenhuma dessas regras aparece em views ou models.

```
convidar(email, papel, por)             → Convite
reenviar_convite(convite, por)          → Convite
aceitar_convite(token, dados)           → Usuario
promover_a_coordenador(usuario, por)    → Usuario
revogar_coordenacao(usuario, por)       → Usuario
```

`apps/contas/permissions.py` fornece `garante(condicao, mensagem)`,
`pode_convidar(usuario)`, `pode_promover(usuario)` e `e_sugrad(usuario)`.

`apps/contas/tasks.py` expõe `enviar_convite(convite_id)` e
`enviar_recuperacao_senha(usuario_id)`, ambas com repetição em recuo exponencial.

### 6.1 `convidar`

Exige que quem convida seja coordenador. Recusa se o e-mail já tem conta ou se já
existe convite ativo e não expirado para ele. Gera token aleatório, grava o hash,
enfileira `enviar_convite`.

### 6.2 `aceitar_convite`

Dentro de `transaction.atomic`: valida o token pelo hash, verifica que não expirou
nem foi usado, cria o `Usuario` com a senha escolhida, cria o perfil correspondente
ao papel do convite, marca o convite como usado e o vincula ao usuário criado.
Token inválido, expirado ou já usado produz a mesma mensagem genérica — a diferença
entre eles não é informação que o solicitante precise ter.

### 6.3 `promover_a_coordenador` — o teto de 4

Dentro de `transaction.atomic`, a contagem é feita com `select_for_update()` sobre
as linhas de coordenadores. Isso não é decoração: promover é um `UPDATE` de uma
linha que passa a integrar o próprio conjunto travado, de modo que duas promoções
simultâneas se serializam e a segunda relê a contagem já atualizada. Sem o bloqueio,
dois cliques concorrentes ultrapassam o limite de 4.

Valida também que o alvo tem `papel=PROFESSOR`, e define `is_staff=True`.

### 6.4 `revogar_coordenacao` — a trava do último

Recusa a revogação quando existe apenas um coordenador no sistema, seja ele o alvo
ou o solicitante. A mensagem de erro instrui a nomear outro coordenador antes.
Define `is_staff=False` ao revogar.

### 6.5 `semear_sistema` (comando de gestão)

Resolve o ovo-e-galinha de "o coordenador envia os convites": cria a conta da SUGRAD
e promove a primeira pessoa a coordenadora. Idempotente — reexecutar não duplica
nada nem rebaixa ninguém.

---

## 7. Fluxos da Fase 1

1. **Semeadura.** `createsuperuser` cria o superusuário; `semear_sistema` cria a
   conta da SUGRAD e o primeiro coordenador.
2. **Convite.** O coordenador informa e-mail e papel. O sistema grava o convite e o
   Celery envia a mensagem com o link.
3. **Cadastro.** A pessoa abre o link, preenche os dados do seu papel — aluno: nome,
   foto, CPF, telefone e matrícula; professor: nome, foto, CPF, telefone e SIAPE —
   define a senha e entra no sistema.
4. **Perfil do professor.** Seleciona suas áreas de atuação entre as cadastradas.
5. **Coordenação.** O coordenador promove ou revoga outros coordenadores, dentro das
   regras de §6.3 e §6.4.
6. **Recuperação de senha.** Fluxo padrão do Django, com o e-mail enviado por Celery.

---

## 8. Ambiente Docker

### 8.1 Serviços

| serviço | imagem ou build | papel |
|---|---|---|
| `web` | build, `target: dev` | Django (runserver em dev, Gunicorn em produção) |
| `db` | `postgres:16-alpine` | banco; volume `dados_postgres` |
| `redis` | `redis:7-alpine` | broker do Celery e cache |
| `celery_worker` | mesma imagem do `web` | e-mails; futuramente, geração de atas |
| `minio` | `minio/minio` | S3 local; volume `dados_minio` |
| `minio_init` | `minio/mc` | execução única: cria o bucket e aplica a política |
| `tailwind` | `node:22-alpine` | `--watch` do CSS; apenas no profile `dev` |

`db`, `redis` e `minio` declaram `healthcheck`; `web` e `celery_worker` usam
`depends_on` com `condition: service_healthy`. Sem isso, o Django sobe antes de o
PostgreSQL aceitar conexões e o primeiro `up` de uma máquina limpa falha — o clássico
"funciona no segundo `docker compose up`".

### 8.2 Dockerfile em três estágios

```
FROM node:22-alpine   AS css     # tailwindcss --minify → orientasi.css
FROM python:3.12-slim AS base    # libs de sistema + requirements.txt + código
FROM base             AS dev     # + requirements-dev.txt + Chromium do Playwright
FROM base             AS prod    # + CSS do estágio css + gunicorn
```

**WeasyPrint exige bibliotecas de sistema.** Ele não é Python puro: renderiza via
Pango e Cairo, e falha já na importação se elas não estiverem presentes. No
`python:3.12-slim` isso significa instalar explicitamente `libpango-1.0-0`,
`libpangoft2-1.0-0`, `libharfbuzz0b`, `libcairo2` e `libgdk-pixbuf-2.0-0` no estágio
`base`. É uma falha que só apareceria no Bloco E, meses depois — por isso a Fase 1
já inclui um teste que importa o WeasyPrint e gera um PDF de uma linha. Custa
segundos na suíte e trava a regressão no dia em que alguém enxugar o Dockerfile.

**Os navegadores do Playwright ficam apenas no estágio `dev`.**
`playwright install --with-deps chromium` acrescenta centenas de megabytes que a
imagem de produção não precisa. O compose de desenvolvimento constrói `target: dev`,
e é por isso que `docker compose exec web pytest` roda a suíte de acessibilidade sem
container adicional, exatamente como o CLAUDE.md promete.

### 8.3 Dependências

`requirements.txt`:

```
django>=5.1,<6.0        psycopg[binary]>=3.2    dj-database-url
celery[redis]>=5.4      redis>=5.0              django-storages[s3]>=1.14
weasyprint>=62          Pillow>=10.4            python-dotenv
gunicorn>=23            whitenoise>=6.7
```

`djangorestframework` e `drf-spectacular` **não** entram agora, pela mesma razão que
adiou o `ProfessorExterno` (§5.6): nada na Fase 1 os usa. Acrescentar uma dependência
no Bloco H é uma linha e uma reconstrução de imagem. O WeasyPrint é a exceção
deliberada — ele não é dependência Python isolada, e sim um conjunto de bibliotecas
de sistema no Dockerfile, cuja ausência só apareceria meses depois (§8.2).

`requirements-dev.txt`:

```
pytest  pytest-django  pytest-playwright  axe-playwright-python
ruff  black  django-debug-toolbar  model-bakery
```

### 8.4 Ordem de execução

A infraestrutura é levantada em degraus verificáveis, para que uma falha posterior
tenha causa localizável:

1. `Dockerfile`, `docker-compose.yml` e `.env.example` — `docker compose up -d` sobe
   os cinco containers em estado saudável.
2. Esqueleto Django com as apps vazias — `/saude/` responde 200.
3. Celery ligado — uma tarefa de teste executa e aparece em
   `docker compose logs -f celery_worker`.
4. MinIO ligado — um envio de teste chega ao bucket.
5. Somente então, os modelos de `contas`.

Quando o convite por e-mail falhar no passo 5, já estará estabelecido que Celery,
Redis e SMTP não são a causa.

### 8.5 Segredos

Todos os segredos vivem em `.env`, que fica fora do controle de versão; o
repositório versiona apenas `.env.example` com valores de exemplo.

A senha de aplicativo do Gmail presente na última página do `inicio.pdf` deve ser
**revogada e substituída** antes do primeiro envio real: ela circulou em documento e
deve ser considerada comprometida.

---

## 9. UI e acessibilidade

### 9.1 Tema

Tailwind v4 configura-se em CSS, não em JavaScript — não há `tailwind.config.js`. A
identidade visual mora em `static/css/entrada.css`:

```css
@import "tailwindcss";
@plugin "daisyui" { themes: orientasi --default; }

@theme {
  --color-marinho: #21376b;   --color-azul:    #055695;
  --color-ciano:   #38c2c2;   --color-laranja: #d9530e;
  --font-display: "Jakarta", system-ui, sans-serif;
  --font-corpo:   "Inter", system-ui, sans-serif;
}
```

As fontes são vendorizadas em `static/fonts/`. Nada de Google Fonts: é requisição a
terceiro e ponto de falha fora da rede.

### 9.2 HTMX e Alpine

Ambos vendorizados em `static/js/`, com versão fixada. O projeto não carrega CDN — o
sistema precisa funcionar na rede da universidade sem depender de domínio externo.

Junto do Alpine vai o plugin oficial `@alpinejs/focus`, que entrega o requisito de
gerenciamento de foco do CLAUDE.md: `x-trap` prende o foco dentro do modal aberto e
o devolve ao elemento de origem quando fecha — a parte que modais artesanais quase
sempre erram.

### 9.3 Região de anúncio para o HTMX

Quando o HTMX troca um trecho da página, o leitor de tela não anuncia nada: a pessoa
aciona "Enviar convite", o convite é enviado, e ela não recebe sinal algum.

Por isso o `base.html` carrega uma região `aria-live="polite"` permanente, e toda
resposta HTMX que represente sucesso ou erro escreve nela via `hx-swap-oob`. É
decisão de arquitetura de template, não detalhe de tela: fora do `base.html`, cada
tela nova reinventaria o mecanismo de um jeito diferente.

### 9.4 Demais requisitos

HTML semântico (`<main>`, `<nav>`, `<header>`, `<article>`), `lang="pt-br"`, link
"pular para o conteúdo" como primeiro elemento focável, foco visível em todos os
controles, alvos de toque de no mínimo 44×44 px e layout responsivo a partir de
360 px de largura.

---

## 10. Testes

### 10.1 Suíte transversal

```
tests/test_acessibilidade.py   axe-core por página; tags wcag2a, wcag2aa, wcag21aa
tests/test_toque.py            todo elemento interativo mede ao menos 44×44 px
tests/test_responsivo.py       a 360px, nenhuma página rola na horizontal
tests/test_teclado.py          1º Tab alcança "pular para o conteúdo", em toda rota
tests/test_arquitetura.py      views não importam models direto; models não importam services
tests/test_producao.py         com AMBIENTE=producao: DEBUG falso, SECRET_KEY exigida,
                               `manage.py check --deploy` sem avisos
tests/test_pdf.py              importa WeasyPrint e gera um PDF de uma linha
```

Os quatro primeiros são parametrizados sobre uma **lista única de rotas** declarada
em `conftest.py`. É o detalhe que faz a suíte crescer sozinha: quando o Bloco B
adicionar o mural de temas, acrescentar uma linha nessa lista submete a tela nova a
todas as verificações de uma vez. Sem a lista compartilhada, cada bloco escreveria
seus próprios testes e a cobertura viraria loteria.

Mecanicamente: a fixture `live_server` do `pytest-django` levanta o Django numa porta
real, a fixture `page` do `pytest-playwright` abre o Chromium do estágio `dev`, e o
`axe-playwright-python` injeta o axe-core e devolve as violações. A falha reporta
regra, seletor e trecho do HTML.

Rotas cobertas na Fase 1: login, recuperação de senha, aceitar convite, painel do
coordenador, perfil do professor e perfil do aluno.

**Sobre "Esc fecha modal", que esta seção prometia (corrigido na revisão final):
a Fase 1 não tem modal nenhum.** A única interação de mostrar/esconder do bloco é
a confirmação de promover/revogar do painel da coordenação, e ela usa
`<details>`/`<summary>` — um *disclosure* nativo do HTML, sem JavaScript, em que
`Esc` **não** fecha por design (fecha-se clicando ou teclando Enter/Espaço no
próprio `<summary>`, que é o que o texto de confirmação instrui). Escrever um
teste de `Esc` aqui seria afirmar um comportamento que o HTML não tem.

O primeiro modal de verdade chega com o **Bloco D** (bancas: convite a professor
externo e agendamento). É lá que entram, juntos, o `Esc` para fechar, a
armadilha de foco enquanto aberto e a devolução do foco ao gatilho — e é lá que
`tests/test_teclado.py` ganha essa segunda asserção.

### 10.2 Testes de `contas`

Além da suíte transversal, `apps/contas/tests/` cobre cada serviço de §6, com
atenção aos casos que definem as regras inegociáveis: promoção que atinge o teto de
4, revogação do último coordenador, convite expirado, convite reutilizado, tentativa
de criar uma segunda conta SUGRAD e tentativa de tornar um aluno coordenador.

### 10.3 Pré-requisitos do Bloco B

Dívida registrada na revisão final da Fase 1. Não são melhorias opcionais: são as
duas duplicações que já **causaram** defeito neste bloco, e que o Bloco B
multiplicaria por mais uma tela cada.

**(a) Extrair `templates/contas/_campo.html`.** O bloco que renderiza um campo
(`<label>` com marcação de obrigatório, o widget, o texto de ajuda com
`id="ajuda-…"` e o bloco de erro com `id="erro-…"` e `role="alert"`) está copiado
**seis vezes** — `aceitar_convite.html`, `perfil.html`, `painel_coordenacao.html`,
`registration/login.html`, `registration/password_reset_form.html` e
`registration/password_reset_confirm.html`. Foi a causa raiz do defeito do resumo
de erros: a correção de `{% if form.non_field_errors %}` para `{% if form.errors %}`
foi feita em duas cópias na Tarefa 10 e **nunca voltou** para as três telas da
Tarefa 9 — o resumo de erros e a movimentação de foco simplesmente não existiam
nas telas de recuperação de senha, e nenhuma suíte fazia POST nelas. Com o partial,
a correção teria sido de uma linha em um arquivo.

**(b) Generalizar `ROTAS` para rotas autenticadas.** `conftest.py` declara a lista
única de rotas que alimenta as quatro suítes transversais, mas todas elas navegam
anônimas — uma rota atrás de `login_required` mediria a tela de login. Por isso a
suíte de acessibilidade já foi **bifurcada duas vezes**
(`apps/contas/tests/test_perfil_acessibilidade.py` na Tarefa 10 e
`test_coordenacao_acessibilidade.py` na Tarefa 11), e as três cópias já divergiram
em três direções: a varredura do axe por largura chegou ao painel na revisão da
T11, às rotas anônimas antes disso, e só à tela de perfil na revisão final. O
Bloco B, com o mural de temas, faria a quarta cópia.

O mecanismo que falta é pequeno: uma entrada de `ROTAS` capaz de carregar uma
**fábrica de usuário opcional** — a rota mais a função que cria e autentica quem a
visita (a fixture `autentica_no_navegador`, já em `conftest.py`, faz a parte do
navegador). Com isso, acrescentar uma tela autenticada volta a ser uma linha na
lista, e a âncora de identidade (confirmar URL final e `<h1>`, para a suíte não
passar verde medindo a tela de login) passa a valer para todas de uma vez.

---

## 11. Contradições entre os documentos, e como foram resolvidas

| Assunto | `inicio.pdf` | `CLAUDE.md` | Resolução |
|---|---|---|---|
| Camada visual | copiar CSS do projeto de referência | Tailwind + DaisyUI/Flowbite | Tailwind v4 + DaisyUI; só a paleta é herdada (§3.1) |
| Idioma do código | apps e modelos em inglês | português é o idioma oficial | português (§3.3) |
| Professor externo | "não precisaria ter acesso ao sistema" | autenticação por token temporário | token, decidido para o Bloco D |
| Status do TCC | cinco status, sem `Concluído` | seis status, com `Concluído` | seis, conforme o CLAUDE.md |

Sobre o professor externo: como o `inicio.pdf` também exige que **cada** membro da
banca preencha o formulário de avaliação, e o externo é membro de banca, a versão do
CLAUDE.md é a única coerente — ele entra sem senha, apenas por token. O fluxo será
especificado no Bloco D.

---

## 12. Mapa do domínio (blocos futuros)

Registrado aqui para que as fronteiras da Fase 1 sejam escolhas conscientes. Nada
disto é implementado agora.

```
projetos/    Semestre         2026/1 — âncora do limite de vagas             [B]
             Tema             professor, área, título, descrição, ativo      [B]
             Candidatura      aluno, tema, ordem 1ª|2ª|3ª, status            [B]
             Projeto          aluno, orientador, coorientador, etapa
                              TCC_I|TCC_II, status, anterior→self            [C]
             Submissao        projeto, pdf, editável, versão, tipo           [C]
             TermoPublicacao  projeto, assinado_em                           [F]

bancas/      Banca            projeto, data_hora, local, status              [D]
             MembroBanca      banca, interno→Usuario | externo→nome (texto)  [D]
             Avaliacao        membro, nota, comentários                      [D]
             ItemCorrecao     projeto, descrição, concluído (checklist)      [F]

documentos/  Ata              projeto, banca, pdf, número, gerada_em         [E]
             RevisaoSUGRAD    ata, APROVADA|DEVOLVIDA, comentários           [E]
```

Blocos: **A** fundação e contas (esta fase) · **B** temas e alocação · **C** TCC I ·
**D** bancas e avaliação · **E** atas e SUGRAD · **F** TCC II · **G** catálogo e
calendário públicos · **H** API DRF.

Três decisões antecipadas deste mapa:

**Membro externo de banca não tem conta, login nem modelo próprio — decisão
revertida.** Uma versão anterior deste mapa (e da regra 3 do `CLAUDE.md`) previa
`ProfessorExterno` com CPF e autenticação por token via e-mail, para que o próprio
avaliador externo preenchesse sua avaliação. Revertido: o membro externo é só um
**nome** (campo de texto em `MembroBanca`, sem FK, sem CPF, sem token). Quem lança a
nota e os comentários dele é quem já tem acesso ao sistema — o orientador ou a
coordenação em nome dele. Isso elimina o subsistema de autenticação externa inteiro
do Bloco D: sem token temporário, sem tela de login simplificada, sem o risco de
segurança de expor um formulário de avaliação a um link de e-mail.

**O catálogo público não vira modelo.** A tabela-resumo do `inicio.pdf` prevê um
`PublicCatalog`, mas ele duplicaria dados que já existem em `Projeto`. Catálogo é uma
consulta — projetos com status `Concluído` e termo de publicação assinado — exposta
por uma view que seleciona apenas os cinco campos permitidos pela regra 6 do
CLAUDE.md. Copiar os dados criaria a possibilidade de o catálogo discordar do
sistema.

**A separação TCC I / TCC II é um campo, não duas tabelas.** `Projeto.etapa` mais o
auto-relacionamento `Projeto.anterior` modelam "o TCC II nasce do TCC I aprovado"
sem duplicar a estrutura. O ciclo de vida é o mesmo nos dois; o que muda são as
etapas extras do TCC II — checklist de correções e termo de publicação —, que são
modelos próprios e não uma segunda cópia de `Projeto`.

---

## 13. Critérios de aceitação da Fase 1

A fase está concluída quando todos os itens abaixo são verificáveis:

1. `docker compose up -d` sobe `web`, `db`, `redis`, `celery_worker` e `minio` em
   estado saudável a partir de um clone limpo.
2. `/saude/` responde 200.
3. `docker compose exec web pytest` passa, incluindo os testes de acessibilidade,
   toque, responsividade, teclado, arquitetura, produção e PDF.
4. `docker compose exec web ruff check .` e `black --check .` passam.
5. `semear_sistema` cria a conta da SUGRAD e o primeiro coordenador, e é idempotente.
6. Um coordenador convida um aluno; o e-mail sai pelo Celery; o link abre o
   formulário; a pessoa se cadastra, envia foto (que chega ao MinIO) e entra.
7. O mesmo fluxo funciona para um professor, que em seguida seleciona suas áreas.
8. A quinta promoção a coordenador é recusada com mensagem clara.
9. A revogação do último coordenador é recusada com mensagem clara.
10. Um aluno não pode ser promovido a coordenador.
11. A criação de uma segunda conta SUGRAD é recusada pelo banco.
12. Um convite expirado e um convite já usado são recusados com a mesma mensagem.
13. Nenhuma das regras acima está implementada em `views.py` ou `models.py`.
