# Contexto do Projeto: OrientaSI

O **OrientaSI** é o sistema de gestão de TCC do curso de Sistemas de Informação.

Idioma oficial do projeto: **Português (pt-br)**.

---

## 🛠️ Comandos de Desenvolvimento (Docker Stack)

Todos os comandos devem rodar via container Docker:

* **Preparar o `.env` (uma vez, num clone novo):** `cp .env.example .env` —
  os serviços declaram `env_file: .env`, então num clone limpo o `docker
  compose up -d` falha antes de subir qualquer container. Não repita o comando
  num ambiente já configurado: ele sobrescreve o `.env` existente.
* **Subir ambiente:** `docker compose up -d` (inclui `web`, `db`, `redis`,
  `celery_worker`, `celery_beat`, `minio` e o auxiliar `tailwind`, que compila
  o CSS em modo `--watch`; nenhum desses serviços está atrás de `profiles`,
  então este único comando sobe tudo).
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
* `celery_beat`: Agendador — publica as tarefas periódicas (hoje, o avanço da
  cascata de candidatura por prazo vencido) na fila do `celery_worker`.
* `minio`: S3 local para desenvolvimento.
* `tailwind`: compila `static/css/entrada.css` em `static/css/orientasi.css`
  (Tailwind CLI, modo `--watch`, imagem `node:22-alpine`, sem instalação local
  de Node). Sem `profiles`: sobe junto com `docker compose up -d`.

---

## 📁 Estrutura de Apps

* `apps/comum`: validators de upload e utilitários transversais a todo o projeto.
* `apps/contas`: usuário, perfis, áreas, convites, painel de perfil e painel da
  coordenação. Única app com regra de negócio no Bloco A.
* `apps/projetos`: mural de temas, candidatura do aluno em cascata (até três
  opções, com prazo automático via Celery Beat), fila de aceite/recusa do
  professor e painel da coordenação para ajustar orientação e conceder limite
  (Bloco B, implementado). Envio/reenvio do trabalho escrito (PDF + editável)
  pelo aluno em `/meu-tcc/`, com visibilidade do estado de envio para o
  orientador em `/orientacoes/` (`Submissao`, Bloco C, implementado). Reabertura
  e cancelamento definitivo de um projeto `Reprovado` (`reabrir_projeto`/
  `cancelar_projeto`, Bloco D, implementado). O modelo `Projeto` nasce no Bloco
  B; as transições `EM_ANDAMENTO` → `Aguardando Defesa` →
  `Aprovado com Ressalvas`/`Reprovado` já estão implementadas (Bloco D); as
  demais (aprovação de correções, TCC II) ficam para os Blocos E–F.
* `apps/bancas`: agendamento de banca (`agendar_banca`/`editar_banca`/
  `cancelar_banca`), registro do resultado da apresentação
  (`registrar_resultado`) e notificação por e-mail do agendamento (Bloco D,
  implementado). `Banca`/`MembroBanca` — nota e resultado são únicos por
  banca, não um por membro (decisão registrada, ver regra 3 abaixo e o spec
  do bloco). Sem `Avaliacao` por membro, sem checklist de correções (Bloco
  F) e sem ata (Bloco E) — ainda não existem.
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

1. **Limite de Vagas (implementado no Bloco B):** Bloqueio automático de novas
   orientações quando o professor atingir **3 alunos em TCC I** e **3 alunos em
   TCC II** no semestre letivo vigente (`LIMITE_PADRAO_VAGAS`, em
   `apps/projetos/services.py`). A coordenação pode conceder uma **exceção para
   cima** a esse teto — nunca para baixo — para um professor, uma etapa e um
   semestre específicos, com justificativa obrigatória e autoria registrada
   (`LimiteOrientacao`, em `apps/projetos/models.py`). A exceção vale só para a
   chave exata (professor, etapa, ano, período): não se propaga para outra
   etapa nem sobrevive à virada do semestre. Revogar a exceção não desfaz os
   projetos já criados sob ela, só trava o próximo aceite.
2. **Coordenadores/Admins:**

   * Máximo de **4 coordenadores** no sistema (`LIMITE_COORDENADORES`, em
     `apps/contas/services.py`).
   * Trava de segurança: o último coordenador não pode remover seu próprio
     acesso de admin sem antes nomear outro.
   * `semear_sistema` só cria o **primeiro** coordenador; a partir daí, promover
     e revogar é responsabilidade exclusiva do painel da coordenação.
3. **Membros Externos de Banca (implementado no Bloco D):** Sem autenticação e
   sem acesso ao sistema — **decisão revertida** em relação a uma versão
   anterior deste documento, que previa login por token e um modelo
   `ProfessorExterno` próprio. O orientador informa só o **nome** do avaliador
   externo ao montar a banca (campo de texto em `MembroBanca`, sem FK, sem
   CPF, sem `ProfessorExterno`) — o orientador participa da banca
   implicitamente, sem uma linha própria em `MembroBanca`. **Divergência do
   `inicio.pdf` original, decidida no brainstorming do Bloco D:** não existe
   uma nota por membro (`Avaliacao`, prevista no mapa de domínio original).
   Existe uma única nota, um único resultado e um único comentário por
   `Banca`, decididos coletivamente na apresentação e digitados pelo
   orientador (`services.registrar_resultado`, `apps/bancas/services.py`) —
   nem o membro externo nem o interno acessam alguma tela do sistema para
   registrar sua própria avaliação.
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
8. **Alocação Contínua, Não por Desempenho (Bloco B):** o aluno manifesta
   interesse por até três professores em ordem, e o primeiro professor que
   aceitar leva a vaga — não o aluno com melhor desempenho escolar. Isso
   contraria o `inicio.pdf`, que pedia alocação em lote por desempenho;
   decisão tomada, com o custo aceito de que um professor requisitado
   preenche as vagas por ordem de chegada dos alunos, não por mérito. O
   sistema não tem de onde tirar uma métrica de desempenho, então essa é
   também a única alternativa viável.

---

## 🔄 Ciclo de Vida e Status do TCC

Status permitidos: `Em Andamento` ➔ `Aguardando Defesa` ➔ `Aprovado com Ressalvas`
➔ `Aprovado` ➔ `Concluído` (ou `Reprovado`). **Acréscimo do Bloco D, fora do
vocabulário original do `inicio.pdf`:** `Cancelado` — encerramento definitivo
de um projeto `Reprovado`, distinto de `Reprovado` (que registra que a banca
não aprovou, não que o projeto foi encerrado). Ver regra 3.6 do spec do
Bloco D para o raciocínio completo.

O modelo `Projeto` existe desde o Bloco B (`apps/projetos/models.py`). O Bloco
C acrescentou o envio do trabalho escrito (`Submissao`). O Bloco D implementou
o restante do ciclo até `Reprovado`: `agendar_banca` fecha `EM_ANDAMENTO` →
`Aguardando Defesa` (exige uma `Submissao` já enviada); `registrar_resultado`
fecha `Aguardando Defesa` → `Aprovado com Ressalvas`/`Reprovado`; a partir de
`Reprovado`, `reabrir_projeto`/`cancelar_projeto` levam a `Em Andamento` (o
aluno tenta de novo) ou a `Cancelado` (fim de linha). `Aprovado` e `Concluído`
— aprovação do checklist de correções, termo de publicação, ata e aprovação
da SUGRAD — ficam para os Blocos E e F, que ainda vão implementá-los sobre o
mesmo modelo.

1. **`Em Andamento`:** Aluno aceito e elaborando o trabalho.
2. **`Aguardando Defesa`:** Aluno envia PDF/Editável e orientador agenda a banca
   (`apps/bancas`, Bloco D).
3. **`Aprovado com Ressalvas`:** Defesa realizada com nota e comentários (uma
   nota geral da banca, não uma por membro — ver regra 3), abrindo prazo de
   correções.
4. **`Aprovado`:** Orientador aprova o **checklist de correções** E o aluno
   assina o **termo de aceite de publicação** (TCC II). **Ainda não
   implementado (Bloco F).**
5. **`Concluído`:** SUGRAD aprova a Ata no Painel SUGRAD. **Ainda não
   implementado (Bloco E).**
6. **`Reprovado`:** Defesa realizada sem aprovação — o orientador reabre
   (volta a `Em Andamento`) ou cancela definitivamente (`Cancelado`).
7. **`Cancelado`:** Estado terminal — nenhuma ação definida a partir daqui
   (lacuna registrada, spec do Bloco D §2).

---

## 🗺️ Fases

O projeto é planejado e revisado em fases, uma spec e um plano por fase, em
`docs/superpowers/specs/` e `docs/superpowers/plans/`.

O domínio inteiro está mapeado em oito blocos (ver §12 do spec da Fase 1),
para que as fronteiras de cada fase sejam escolhas conscientes:

* **A — Fundação e contas** (concluído): esqueleto Django em Docker,
  modelo de usuário, perfis, áreas, convites, login/logout, recuperação de
  senha, painel de perfil, painel da coordenação, comando de semeadura.
* **B — temas e alocação (concluído)**: mural de temas, painel do professor
  para publicar/editar/desativar tema, candidatura do aluno com até três
  opções em cascata (prazo automático via Celery Beat), fila de aceite/recusa
  do professor, criação do `Projeto` de TCC I no aceite, limite de vagas com
  exceção autorizada pela coordenação, e painel da coordenação para trocar
  orientador e conceder/revogar limite.
* **C — TCC I (concluído)**: modelo `Submissao` (PDF + editável, sem
  histórico de versões — reenvio substitui e incrementa `versao`), tela do
  aluno para enviar/reenviar (`/meu-tcc/`) e visibilidade do estado de envio
  para o orientador em `/orientacoes/`. Não fecha a transição de
  `Projeto.status` para `Aguardando Defesa` — essa transição também depende
  do agendamento de uma `Banca` (Bloco D).
* **D — bancas e avaliação (concluído)**: `Banca`/`MembroBanca`
  (`apps/bancas`); agendar/editar/cancelar banca; registrar resultado (uma
  nota geral, não por membro — ver regra 3); a partir de `Reprovado`,
  reabrir o projeto ou cancelá-lo definitivamente (`Cancelado`, status novo).
  Sem `Avaliacao` por membro, sem checklist de correções (Bloco F) e sem ata
  (Bloco E).
* **E** — atas e SUGRAD
* **F** — TCC II
* **G** — catálogo e calendário públicos
* **H** — API DRF (`djangorestframework` + `drf-spectacular` entram aqui)

Antes de assumir que uma regra de negócio, modelo ou tela já existe, confira a
qual bloco ela pertence e se aquele bloco já foi implementado.

---

## 🧪 Disciplina de Testes

Convenções de engenharia para os Blocos C em diante, tiradas de padrões que se
repetiram nas revisões do Bloco B:

* **Uma checagem nova só está provada por mutação, nunca pela suíte verde.**
  Rodar a suíte com o código certo não diz nada sobre o código errado. Prove
  removendo de propósito a checagem (a permissão, o filtro, a trava) e
  confirmando que algum teste reprova; só então desfaça a remoção. "A suíte
  passou" não é evidência de que a checagem nova é testada.
* **Uma checagem vizinha pode mascarar a ausência da checagem nova.** Uma
  trava de outra função, ou de outro elemento da mesma tela, às vezes absorve
  o efeito da mutação sem que nenhum teste perceba, e a suíte inteira continua
  verde com a checagem nova ausente. A defesa é sempre a mesma: mutar e olhar
  a saída do teste, nunca inferir cobertura pela suíte passando.
* **Uma citação de arquivo:linha só vale se conferida no momento em que é
  escrita.** Um commit anterior pode ter deslocado o arquivo, e uma citação
  copiada de memória (ou de uma revisão anterior) fica errada em silêncio. Leia
  o código real antes de citar a linha, não confie numa citação já pronta.
