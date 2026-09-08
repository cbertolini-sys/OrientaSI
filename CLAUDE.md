# \# Contexto do Projeto: OrientaSI


O \*\*OrientaSI\*\* é o sistema de gestão de TCC do curso de Sistemas de Informação. 

Idioma oficial do projeto: \*\*Português (pt-br)\*\*.


---


\#\# 🛠️ Comandos de Desenvolvimento (Docker Stack)


Todos os comandos devem rodar via container Docker:


\* \*\*Subir ambiente:\*\* \`docker compose up -d\`

\* \*\*Derrubar ambiente:\*\* \`docker compose down\`

\* \*\*Criar migrações:\*\* \`docker compose exec web python manage.py makemigrations\`

\* \*\*Aplicar migrações:\*\* \`docker compose exec web python manage.py migrate\`

\* \*\*Criar superusuário:\*\* \`docker compose exec web python manage.py createsuperuser\`

\* \*\*Rodar testes (Pytest + Playwright + axe-core):\*\* \`docker compose exec web pytest\`

\* \*\*Linter / Formatador:\*\* \`docker compose exec web ruff check .\` / \`docker compose exec web black .\`

\* \*\*Logs do Celery:\*\* \`docker compose logs -f celery\_worker\`


---


\#\# 🏗️ Stack Tecnológica & UI/UX


\* \*\*Backend:\*\* Python 3.12+, Django 5+.

\* \*\*Frontend:\*\* Django Templates + \*\*HTMX\*\* + \*\*Alpine.js\*\* + \*\*Tailwind CSS\*\* (DaisyUI/Flowbite).

\* \*\*CSS & Identidade Visual:\*\* Copiar a estrutura visual, cores e layout do projeto IntegraSI (sem citar ou referenciar o nome IntegraSI no código ou documentação).

\* \*\*Banco de Dados:\*\* PostgreSQL.

\* \*\*Tarefas de Background:\*\* Celery + Redis (Envio de e-mails, processamento de atas).

\* \*\*Geração de PDF:\*\* WeasyPrint (Atas e documentos oficiais).

\* \*\*Documentação API:\*\* Django REST Framework (DRF) + \`drf-spectacular\`.

\* \*\*Armazenamento:\*\* Mídia (\`.pdf\`, \`.docx\`, fotos) via \`django-storages\` usando S3 / MinIO local.

\* \*\*Testes de Acessibilidade:\*\* Playwright integrado com \`axe-core\`.


---


\#\# 🏗️ Arquitetura de Containers (\`docker-compose.yml\`)


\* \`web\`: Aplicação Django (Gunicorn em produção).

\* \`db\`: Banco de dados PostgreSQL.

\* \`redis\`: Broker de mensagens e cache.

\* \`celery\_worker\`: Processamento assíncrono de e-mails e PDFs.

\* \`minio\`: S3 local para desenvolvimento.


---


\#\# ♿ Acessibilidade (WCAG 2.1 AA) & Responsividade


1. \*\*Acessibilidade Nativa:\*\*

   \* Uso de HTML semântico (\`\<main\>\`, \`\<nav\>\`, \`\<header\>\`, \`\<article\>\`).

   \* Gerenciamento de foco em modais e menus responsivos via Alpine.js.

   \* Componentes acessíveis baseados em DaisyUI ou Flowbite com suporte total a leitores de tela e navegação por teclado (\`Tab\`, \`Enter\`, \`Space\`, \`Esc\`).

2. \*\*Mobile First:\*\*

   \* Interface 100% responsiva para telas mobile e desktop.

   \* Áreas clicáveis com dimensões mínimas de 44x44px.


---


\#\# 🔒 Regras de Negócio Inegociáveis


1. \*\*Limite de Vagas:\*\* Bloqueio automático de novas orientações quando o professor atingir \*\*3 alunos em TCC I\*\* e \*\*3 alunos em TCC II\*\* no semestre letivo vigente.

2. \*\*Coordenadores/Admins:\*\*

   \* Máximo de \*\*4 coordenadores\*\* no sistema.

   \* Trava de segurança: O último coordenador não pode remover seu próprio acesso de admin sem antes nomear outro.

3. \*\*Professores Externos:\*\* Autenticação simplificada via link enviado por e-mail (token temporário), informando apenas Nome e CPF para preenchimento da avaliação da banca.

4. \*\*Camada de Serviço (\`services.py\`):\*\* Lógicas complexas (transição de status, envio de convites, criação de atas, validação de vagas) ficam obrigatoriamente na camada de serviço de cada app, mantendo Models e Views limpos.

5. \*\*Painel SUGRAD:\*\* A SUGRAD interage obrigatoriamente via \*\*Painel do Sistema\*\*. Notificações por e-mail contêm links direcionando para a tela de login/painel.

6. \*\*Catálogo Público:\*\* Exibe apenas TCCs com status \`Concluído\`. Expor unicamente PDF Final, Título, Resumo, Autores e Orientador (ocultar CPF, telefone e dados sensíveis).

7. \*\*Validação de Uploads:\*\* Validar obrigatoriamente as extensões \`.pdf\` e \`.docx\` e limite máximo de tamanho (ex: 15MB) via \*validators\* nos modelos.


---


\#\# 🔄 Ciclo de Vida e Status do TCC


Status permitidos: \`Em Andamento\` ➔ \`Aguardando Defesa\` ➔ \`Aprovado com Ressalvas\` ➔ \`Aprovado\` ➔ \`Concluído\` (ou \`Reprovado\`).


1. \*\*\`Em Andamento\`:\*\* Aluno aceito e elaborando o trabalho.

2. \*\*\`Aguardando Defesa\`:\*\* Aluno envia PDF/Editável e orientador agenda a banca.

3. \*\*\`Aprovado com Ressalvas\`:\*\* Defesa realizada com nota e comentários, abrindo prazo de correções.

4. \*\*\`Aprovado\`:\*\* Orientador aprova o \*\*checklist de correções\*\* E o aluno assina o \*\*termo de aceite de publicação\*\* (TCC II).

5. \*\*\`Concluído\`:\*\* SUGRAD aprova a Ata no Painel SUGRAD.
