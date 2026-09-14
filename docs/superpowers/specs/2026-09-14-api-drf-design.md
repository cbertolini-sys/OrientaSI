# Bloco H: API DRF — Spec

**Bloco:** H (de A–H; último bloco do roadmap — ver §12 do spec da Fase 1)

**Contexto:** Blocos A–G concluídos e mergeados em `main`. O `inicio.pdf`
original só registra a escolha de stack ("Documentação da API: Django REST
Framework (DRF) + drf-spectacular") — nenhum requisito lista quais recursos
a API deveria expor ou quais operações permitir. O `CLAUDE.md` confirma:
"decisão registrada para o Bloco H. Nenhum dos dois está em
`requirements.txt` hoje; não há API nesta fase." Este bloco decide o
escopo real e implementa.

## 1. Escopo

A API é **só leitura pública**: expõe em JSON exatamente o que `/catalogo/`
e `/calendario/` (Bloco G) já mostram em HTML, sem autenticação e sem
escrita. Nenhum outro domínio (contas, projetos, bancas, documentos) ganha
endpoint nesta primeira versão — decisão explícita do usuário durante o
brainstorming, contra a alternativa de replicar o domínio inteiro pra um
futuro app mobile (que exigiria decompor em vários blocos à parte).

## 2. Arquitetura

Duas dependências novas em `requirements.txt`: `djangorestframework` e
`drf-spectacular`.

O código da API vive dentro de `apps/publico` — mesmo domínio das telas
HTML de catálogo/calendário — em arquivos próprios, separados de
`views.py`/`urls.py` (HTML):

- `apps/publico/serializers.py`
- `apps/publico/api_views.py`
- `apps/publico/api_urls.py`

Nenhuma regra de negócio nova: as viewsets chamam
`services.catalogo_publico`/`services.calendario_publico` (Bloco G, já
existentes), exatamente como as views HTML já fazem — a API é só mais uma
forma de apresentação sobre a mesma camada de serviço.

Dois `ReadOnlyModelViewSet` (list + retrieve, GET apenas) registrados num
`DefaultRouter` — o router gera de graça uma página-índice em `/api/v1/`,
listando os recursos disponíveis. `drf-spectacular` gera o schema OpenAPI
(`/api/schema/`) e a UI do Swagger (`/api/docs/`); ambos entram em
`config/urls.py`, não dentro de `apps/publico` — documentação de API é
transversal ao projeto, não pertence a um domínio específico.

Prefixo `/api/v1/` (versionado desde o início — decisão do usuário: uma
mudança incompatível futura ganha `/api/v2/` sem quebrar quem já consome
`v1`).

## 3. Serialização

Dois `serializers.Serializer` explícitos — **não** `ModelSerializer`.
Listar os campos manualmente, em vez de deixar o DRF introspeccionar o
modelo inteiro, é a mesma disciplina da regra 6 do `CLAUDE.md`: nunca
correr o risco de um campo novo em `Projeto` (CPF, telefone, e-mail)
vazar pra API por acidente só porque foi adicionado ao modelo depois.

```python
class CatalogoSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    titulo = serializers.CharField(source="tema.titulo")
    resumo = serializers.CharField(source="tema.descricao")
    autor = serializers.CharField(source="aluno.nome_completo")
    orientador = serializers.CharField(source="orientador.nome_completo")
    pdf_url = serializers.SerializerMethodField()

    def get_pdf_url(self, projeto):
        return projeto.submissao.pdf.url


class CalendarioSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    aluno = serializers.CharField(source="projeto.aluno.nome_completo")
    titulo = serializers.SerializerMethodField()
    orientador = serializers.CharField(source="projeto.orientador.nome_completo")
    data_hora = serializers.DateTimeField()
    local = serializers.CharField()

    def get_titulo(self, banca):
        return banca.projeto.tema.titulo if banca.projeto.tema else None
```

`titulo` do calendário usa `SerializerMethodField`, não `source=
"projeto.tema.titulo"` direto: uma `Banca` de TCC_I pode ter
`projeto.tema is None` (candidatura aberta, Bloco B), o que quebraria o
`source` com `AttributeError`. No catálogo, `_projetos_catalogaveis`
(Bloco G) já garante `tema` não nulo, então o `source` direto é seguro
ali.

## 4. Endpoints, filtros, paginação e permissões

```python
class CatalogoViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CatalogoSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        area_id = self.request.query_params.get("area")
        area_id = int(area_id) if area_id and area_id.isdigit() else None
        ano = self.request.query_params.get("ano")
        ano = int(ano) if ano and ano.isdigit() else None
        return services.catalogo_publico(area_id=area_id, ano=ano)


class CalendarioViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CalendarioSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return services.calendario_publico()
```

Mesma validação tolerante de querystring da tela HTML (`isdigit()`, ignora
valor inválido em vez de deixar `int()` levantar e derrubar a resposta com
500) — reaproveita a disciplina do Bloco G, não duplica lógica nova.

`apps/publico/api_urls.py` registra as duas viewsets no router — `basename`
é obrigatório aqui porque nenhuma das duas define `queryset` como atributo
de classe (só `get_queryset()`), e sem `basename` o DRF não consegue
inferir o nome sozinho:

```python
router = DefaultRouter()
router.register("catalogo", CatalogoViewSet, basename="catalogo")
router.register("calendario", CalendarioViewSet, basename="calendario")

urlpatterns = router.urls
```

`GET /api/v1/catalogo/<id>/` e `GET /api/v1/calendario/<id>/` (retrieve)
vêm de graça do `ReadOnlyModelViewSet`. Como `get_queryset()` já é a fonte
elegível (`_projetos_catalogaveis`/bancas agendadas futuras), pedir o
`id` de um projeto fora do catálogo (TCC_I, sem termo assinado, sem tema)
responde 404 — o mesmo princípio de "não existe" e "não é seu" respondendo
igual, já usado em toda checagem de posse do sistema, aqui aplicado a
elegibilidade pública.

`REST_FRAMEWORK` (settings):

```python
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}
```

`DEFAULT_SCHEMA_CLASS` é exigido pelo próprio `drf-spectacular` — sem ele,
o DRF usa seu gerador de schema padrão (limitado) em vez do do
`drf-spectacular`, e `/api/schema/`/`/api/docs/` saem incompletos ou
quebrados. `SPECTACULAR_SETTINGS` com título/descrição/versão do projeto.
`config/urls.py` ganha `path("api/v1/", include(router.urls))`,
`path("api/schema/", SpectacularAPIView.as_view())`,
`path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"))`.

Paginação ativa por padrão (`PAGE_SIZE=20`) — decisão do usuário: prática
padrão de API REST, evita devolver a tabela inteira de uma vez conforme o
catálogo cresce. A resposta de list vem envelopada:
`{"count", "next", "previous", "results"}`.

## 5. Testes

Usam o mesmo fixture `client` já padrão em todo o projeto (respostas
JSON via `resposta.json()`, sem precisar do `APIClient` do DRF). Cobertura:

- Cada condição de elegibilidade do catálogo/calendário (já provada por
  mutação no Bloco G, na camada de serviço) reafirmada aqui só no nível
  HTTP — a lógica é a mesma `services.py`, a API não reintroduz regra
  nova a testar por mutação, só confirma que o endpoint devolve o que o
  serviço devolve.
- Filtros `area`/`ano` via querystring no endpoint de catálogo.
- Paginação: confirma que a resposta é o envelope `{"count", "next",
  "previous", "results"}`, não uma lista JSON nua — prova de que a
  configuração de paginação está de fato ativa.
- Querystring inválida (`?area=xyz&ano=abc`) não derruba a API com 500.
- `retrieve` de um projeto fora do catálogo (TCC_I, sem termo, sem tema)
  responde 404.
- `/api/docs/` e `/api/schema/` respondem 200 (só existência — conteúdo é
  gerado pelo `drf-spectacular`, não é nosso código pra testar em
  detalhe).

## 6. Fora de escopo

- Qualquer endpoint de escrita (POST/PUT/PATCH/DELETE) — API é só leitura
  pública.
- Autenticação/autorização — não há recurso protegido nesta primeira
  versão.
- Rate limiting/throttling — YAGNI, volume de tráfego não justifica agora.
- `/api/docs/` (Swagger UI) e `/api/schema/` **não entram** nas cinco
  suítes transversais de acessibilidade (`ROTAS`, `conftest.py`): a UI do
  Swagger é um bundle de terceiro servido pelo `drf-spectacular`, não um
  template nosso — não há o que corrigir do nosso lado se o axe-core
  apontar algo ali, e cobrar nosso próprio padrão WCAG de uma ferramenta
  de terceiro embutida não faz sentido. O mesmo vale pro
  `BrowsableAPIRenderer` do DRF quando `/api/v1/catalogo/` é aberto
  direto no navegador.
- Endpoints para qualquer outro domínio (contas, projetos, bancas,
  documentos) além de catálogo/calendário.

## 7. Critérios de aceitação

1. `GET /api/v1/catalogo/` devolve, para cada TCC_II `Concluído` com
   termo assinado e tema, exatamente os campos `id`, `titulo`, `resumo`,
   `autor`, `orientador`, `pdf_url` — nenhum CPF, telefone ou e-mail.
2. Um TCC_I, ou um TCC_II sem termo/sem tema, não aparece em
   `GET /api/v1/catalogo/` nem é acessível via
   `GET /api/v1/catalogo/<id>/` (404).
3. `GET /api/v1/catalogo/?area=<id>` e `?ano=<ano>` filtram como a tela
   HTML equivalente.
4. `GET /api/v1/calendario/` devolve só bancas `Agendada` com `data_hora`
   futura, com os campos `id`, `aluno`, `titulo` (`null` quando o projeto
   não tem tema), `orientador`, `data_hora`, `local`.
5. As duas listas vêm paginadas (`{"count", "next", "previous",
   "results"}`), 20 itens por página.
6. Uma querystring inválida em qualquer filtro não derruba a API com 500.
7. `/api/docs/` mostra a UI do Swagger; `/api/schema/` devolve o schema
   OpenAPI.
8. Nenhuma das regras acima está implementada em `api_views.py` além da
   leitura de querystring — a elegibilidade em si é sempre
   `apps/publico/services.py` (Bloco G), nunca reimplementada aqui.
9. `docker compose exec web pytest` passa.
