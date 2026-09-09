# Contexto do Projeto: OrientaSI

O **OrientaSI** é o sistema de gestão de TCC do curso de Sistemas de Informação.

Idioma oficial do projeto: **Português (pt-br)**.

---

## 🛠️ Comandos de Desenvolvimento (Docker Stack)

Todos os comandos devem rodar via container Docker:

* **Subir ambiente:** `docker compose up -d` (inclui `web`, `db`, `redis`,
  `celery_worker`, `minio` e o auxiliar `tailwind`, que compila o CSS em modo
  `--watch`; nenhum desses serviços está atrás de `profiles`, então este único
  comando sobe tudo).
* **Derrubar ambiente:** `docker compose down`
* **Criar migrações:** `docker compose exec web python manage.py makemigrations`
* **Aplicar migrações:** `docker compose exec web python manage.py migrate`
* **Criar superusuário:** `docker compose exec web python manage.py createsuperuser`
* **Semear o sistema (primeira instalação):**
  `docker compose exec web python manage.py semear_sistema --email-coordenador ... --nome-coordenador "..." --cpf-coordenador ... --email-sugrad ...`
  Cria a conta única da SUGRAD e o primeiro coordenador. É idempotente (rodar de
  novo com os mesmos argumentos não duplica nada), mas **recusa** promover um
  coordenador novo se o sistema já tiver algum — depois do primeiro, nomear
  coordenadores é tarefa do painel da coordenação, não deste comando.
* **Rodar testes (Pytest + Playwright + axe-core):** `docker compose exec web pytest`
* **Linter / Formatador:** `docker compose exec web ruff check .` / `docker compose exec web black .`
* **Logs do Celery:** `docker compose logs -f celery_worker`

---

## 🏗️ Stack Tecnológica & UI/UX

* **Backend:** Python 3.12+, Django 5+.
* **Frontend:** Django Templates + **HTMX** + **Alpine.js** + **Tailwind CSS v4** +
  **DaisyUI 5**. HTMX e Alpine são vendorizados em `static/js/` (sem CDN, ver
  regra de uploads/ativos abaixo).
* **CSS & Identidade Visual:** Tailwind v4 + DaisyUI, com tema próprio construído
  sobre as cores institucionais — marinho `#21376B`, azul `#055695`, ciano
  `#38C2C2`, laranja `#D9530E`. O laranja puro reprova o contraste AA para texto
  (branco sobre ele mede 4.04:1, abaixo do mínimo de 4.5:1); por isso o token de
  texto/ícone (`--color-warning`, usado por `.btn-warning`, `.text-warning` etc.)
  usa `#B8440B` (5.43:1, passa AA), e `#D9530E` sobrevive só como
  `--color-warning-institucional`, exclusivamente para uso **não-textual**
  (superfícies, bordas, indicadores, onde 3:1 basta). Nenhum código novo deve
  colocar texto sobre `--color-warning-institucional`. Ver `static/css/entrada.css`.
* **Flowbite não é usado.** A aparência vem do DaisyUI, o comportamento vem do
  Alpine.js — os dois disputariam o mesmo evento de clique se combinados.
* **Banco de Dados:** PostgreSQL.
* **Tarefas de Background:** Celery + Redis (envio de e-mails; processamento de
  atas fica para o Bloco E).
* **Geração de PDF:** WeasyPrint (Atas e documentos oficiais; uso real chega com
  o Bloco E, a dependência de sistema já é validada na Fase 1 — `tests/test_pdf.py`).
* **Documentação API:** Django REST Framework (DRF) + `drf-spectacular` — decisão
  registrada para o **Bloco H**. Nenhum dos dois está em `requirements.txt` hoje;
  não há API nesta fase.
* **Armazenamento:** Mídia (`.pdf`, `.docx`, fotos) via `django-storages` usando
  S3 / MinIO local.
* **Testes de Acessibilidade:** Playwright integrado com `axe-core`.

---

## 🏗️ Arquitetura de Containers (`docker-compose.yml`)

* `web`: Aplicação Django (Gunicorn em produção).
* `db`: Banco de dados PostgreSQL.
* `redis`: Broker de mensagens e cache.
* `celery_worker`: Processamento assíncrono de e-mails e PDFs.
* `minio`: S3 local para desenvolvimento.
* `tailwind`: compila `static/css/entrada.css` em `static/css/orientasi.css`
  (Tailwind CLI, modo `--watch`, imagem `node:22-alpine`, sem instalação local
  de Node). Sem `profiles`: sobe junto com `docker compose up -d`.

---

## 📁 Estrutura de Apps

* `apps/comum`: validators de upload e utilitários transversais a todo o projeto.
* `apps/contas`: usuário, perfis, áreas, convites, painel de perfil e painel da
  coordenação. Única app com regra de negócio implementada na Fase 1.
* `apps/projetos`: criada, registrada no `INSTALLED_APPS`, vazia — reservada
  para os Blocos B (temas e alocação) e C (TCC I).
* `apps/bancas`: criada, registrada, vazia — reservada para o Bloco D (bancas e
  avaliação).
* `apps/documentos`: criada, registrada, vazia — reservada para o Bloco E (atas
  e SUGRAD).

Todo identificador de código (apps, modelos, campos, funções, variáveis) é em
português. Interface, mensagens de erro, comentários e commits também.

---

## ♿ Acessibilidade (WCAG 2.1 AA) & Responsividade

1. **Acessibilidade Nativa:**

   * Uso de HTML semântico (`<main>`, `<nav>`, `<header>`, `<article>`).
   * Gerenciamento de foco em modais e menus responsivos via Alpine.js.
   * Componentes acessíveis baseados em DaisyUI, com suporte total a leitores de
     tela e navegação por teclado (`Tab`, `Enter`, `Space`, `Esc`).
2. **Mobile First:**

   * Interface 100% responsiva para telas mobile e desktop, sem rolagem
     horizontal a partir de 360px.
   * Áreas clicáveis com dimensões mínimas de 44x44px.

---

## 🔒 Regras de Negócio Inegociáveis

1. **Limite de Vagas:** Bloqueio automático de novas orientações quando o professor
   atingir **3 alunos em TCC I** e **3 alunos em TCC II** no semestre letivo
   vigente. (Regra especificada para o Bloco B/C — a Fase 1 não tem projetos de
   TCC ainda.)
2. **Coordenadores/Admins:**

   * Máximo de **4 coordenadores** no sistema (`LIMITE_COORDENADORES`, em
     `apps/contas/services.py`).
   * Trava de segurança: o último coordenador não pode remover seu próprio
     acesso de admin sem antes nomear outro.
   * `semear_sistema` só cria o **primeiro** coordenador; a partir daí, promover
     e revogar é responsabilidade exclusiva do painel da coordenação.
3. **Professores Externos:** Autenticação simplificada via link enviado por
   e-mail (token temporário), informando apenas Nome e CPF para preenchimento da
   avaliação da banca. **Esta é uma decisão de arquitetura registrada para o
   Bloco D — o modelo `ProfessorExterno` e esse fluxo não existem na Fase 1.**
4. **Camada de Serviço (`services.py`):** Lógicas complexas (transição de status,
   envio de convites, criação de atas, validação de vagas) ficam
   obrigatoriamente na camada de serviço de cada app. `models.py` contém apenas
   campos, `Meta` e `__str__`; `views.py` não contém regra de negócio.
5. **Painel SUGRAD:** A SUGRAD interage obrigatoriamente via **Painel do
   Sistema**. Notificações por e-mail contêm links direcionando para a tela de
   login/painel.
6. **Catálogo Público:** Exibe apenas TCCs com status `Concluído`. Expor
   unicamente PDF Final, Título, Resumo, Autores e Orientador (ocultar CPF,
   telefone e dados sensíveis). (Bloco G.)
7. **Validação de Uploads:** Validar obrigatoriamente as extensões `.pdf` e
   `.docx` e limite máximo de tamanho (ex: 15MB) via *validators* nos modelos
   (`apps/comum/validators.py`, `apps/contas/validators.py`).

---

## 🔄 Ciclo de Vida e Status do TCC

Status permitidos: `Em Andamento` ➔ `Aguardando Defesa` ➔ `Aprovado com Ressalvas`
➔ `Aprovado` ➔ `Concluído` (ou `Reprovado`).

Este ciclo de vida é especificado para os Blocos C–F; o modelo `Projeto` ainda não
existe na Fase 1 (`apps/projetos` está vazia).

1. **`Em Andamento`:** Aluno aceito e elaborando o trabalho.
2. **`Aguardando Defesa`:** Aluno envia PDF/Editável e orientador agenda a banca.
3. **`Aprovado com Ressalvas`:** Defesa realizada com nota e comentários, abrindo
   prazo de correções.
4. **`Aprovado`:** Orientador aprova o **checklist de correções** E o aluno
   assina o **termo de aceite de publicação** (TCC II).
5. **`Concluído`:** SUGRAD aprova a Ata no Painel SUGRAD.

---

## 🗺️ Fases

O projeto é planejado e revisado em fases, uma spec e um plano por fase, em
`docs/superpowers/specs/` e `docs/superpowers/plans/`.

O domínio inteiro está mapeado em oito blocos (ver §12 do spec da Fase 1),
para que as fronteiras de cada fase sejam escolhas conscientes:

* **A — Fundação e contas** (esta fase, concluída): esqueleto Django em Docker,
  modelo de usuário, perfis, áreas, convites, login/logout, recuperação de
  senha, painel de perfil, painel da coordenação, comando de semeadura.
* **B** — temas e alocação
* **C** — TCC I
* **D** — bancas e avaliação (inclui `ProfessorExterno` e autenticação por token)
* **E** — atas e SUGRAD
* **F** — TCC II
* **G** — catálogo e calendário públicos
* **H** — API DRF (`djangorestframework` + `drf-spectacular` entram aqui)

Antes de assumir que uma regra de negócio, modelo ou tela já existe, confira a
qual bloco ela pertence e se aquele bloco já foi implementado.
