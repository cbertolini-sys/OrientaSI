# OrientaSI

Sistema de gestão de TCC do Curso de Sistemas de Informação.

## Como subir o ambiente

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py semear_sistema \
  --email-coordenador coordenacao@ufsm.br \
  --nome-coordenador "Coordenação do Curso" \
  --cpf-coordenador 39053344705 \
  --email-sugrad sugrad@ufsm.br
```

`docker compose up -d` sobe todos os serviços de uma vez — `web`, `db`, `redis`,
`celery_worker`, `minio` e o auxiliar `tailwind` (compila o CSS em modo
`--watch`) — nenhum deles está atrás de um profile.

`semear_sistema` cria a conta única da SUGRAD e o primeiro coordenador do
sistema; é idempotente, mas recusa nomear um segundo coordenador se o sistema
já tiver um — depois do primeiro, use o painel da coordenação.

O sistema fica em http://localhost:8000 e o console do MinIO em
http://localhost:9001.

## Testes

```bash
docker compose exec web pytest
docker compose exec web ruff check .
docker compose exec web black --check .
```

A suíte inclui verificação automática de acessibilidade (WCAG 2.1 AA) com
Playwright e axe-core, alvos de toque, responsividade, navegação por teclado,
arquitetura (camada de serviço, ausência de regra de negócio em `views.py`/
`models.py`), configuração de produção e geração de PDF.

## Stack

Django 5 + PostgreSQL + Celery/Redis + MinIO (S3), templates Django com HTMX,
Alpine.js e Tailwind v4 + DaisyUI. Detalhes de arquitetura, identidade visual e
convenções de código em `CLAUDE.md`.

## Estrutura de apps

- `apps/comum` — validators e utilitários transversais.
- `apps/contas` — usuário, perfis, áreas, convites, painel de perfil e painel
  da coordenação. Única app com regra de negócio na Fase 1.
- `apps/projetos`, `apps/bancas`, `apps/documentos` — criadas e registradas,
  vazias, reservadas para os blocos B–E.

## Documentação

- Contexto, convenções e regras de negócio: `CLAUDE.md`
- Especificações por fase: `docs/superpowers/specs/`
- Planos de implementação por fase: `docs/superpowers/plans/`
