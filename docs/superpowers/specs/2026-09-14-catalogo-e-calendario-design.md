# Bloco G: Catálogo e Calendário Públicos — Spec

**Bloco:** G (de A–H; ver §12 do spec da Fase 1)

**Contexto:** Blocos A–F concluídos e mergeados em `main`. O ciclo de vida completo
do TCC (I e II, `Em Andamento` → `Concluído`) já está implementado. Este bloco
expõe duas telas **públicas** (sem login): o catálogo de TCCs concluídos, para
download, e o calendário de apresentações futuras. Nenhum modelo novo — ambas
são consultas sobre `Projeto`/`Banca` já existentes (nota do mapa de domínio,
§12: "o catálogo público não vira modelo").

---

## 1. Escopo do catálogo

O catálogo mostra **só o TCC_II concluído com termo de publicação assinado** —
não qualquer TCC concluído. Como `TermoPublicacao` só é criado no fluxo do
TCC_II (Bloco F), um aluno que concluiu apenas o TCC_I (sem nunca avançar para
o TCC_II) nunca aparece no catálogo. Esta é a leitura literal do
`inicio.pdf` ("Publicar no catálogo apenas o PDF final") e do mapa de domínio:
"PDF final" é o do TCC_II, não o rascunho do TCC_I.

Critério de elegibilidade: `Projeto.etapa == TCC_II`, `Projeto.status ==
CONCLUIDO`, `TermoPublicacao` existente para o projeto (o `aprovar_projeto` do
Bloco F já garante isso antes de chegar a `Aprovado` → `Concluído` — não é uma
checagem nova, é uma consequência do gate que já existe), **e `tema` não
nulo**. Este último ponto é uma checagem nova, de verdade: um TCC_I pode
nascer sem `tema` (candidatura "aberta", sem tema pré-publicado — Bloco B,
`inicio.pdf`: "se o orientador estiver aberto a algum tema ele pode
solicitar"), e `criar_tcc_ii_automatico` (item 2 abaixo) herda esse `tema`
tal como está — inclusive `None`. Sem Título/Resumo, o projeto não tem o que
mostrar no catálogo, então fica de fora até (se um dia acontecer) ganhar um
tema por outro caminho.

## 2. Reabertura de decisões do Bloco F

Este bloco reabre parte do desenho do Bloco F (já mergeado), porque só ao
desenhar o catálogo ficou claro que faltava uma fonte para Título/Resumo do
TCC_II:

**`Projeto.tema` (existente desde o Bloco B) passa a ser usado também pelo
TCC_II**, em vez de ficar sempre `None`:

- `criar_tcc_ii_automatico(projeto_tcc_i)`: passa a copiar também
  `tema=projeto_tcc_i.tema` (além de aluno/orientador/coorientador/
  coorientador_externo, que já copiava). O TCC_II herda o tema do TCC_I que
  o originou.
- `criar_tcc_ii_manual(aluno, professor, tema, por)`: ganha o parâmetro
  `tema`, obrigatório — o professor **escolhe um dos seus próprios Temas já
  cadastrados** (ativos ou não; um tema desativado após preencher a vaga
  original ainda pode ser reaproveitado aqui). Repassado a
  `criar_projeto_sob_limite(aluno, professor, tema=tema, etapa=Projeto.TCC_II)`
  em vez de `tema=None`.
- `FormularioCriarTccII` ganha `tema = forms.ModelChoiceField(...)`, com
  `queryset` filtrado a `Tema.objects.filter(professor=professor)` — só os
  temas do professor autenticado, não de qualquer professor.

Com isso, **catálogo lê `projeto.tema.titulo` e `projeto.tema.descricao`
diretamente como Título e Resumo** — nenhum campo novo em `Projeto`. Uma
única fonte de título/descrição para qualquer TCC (I ou II), sem duplicar
dado.

## 3. Reabertura de `enviar_submissao` (Bloco C)

O `inicio.pdf` original pede que, após a banca, o aluno "deposite a versão
corrigida" do TCC_II. Hoje `enviar_submissao` (`apps/projetos/services.py`)
só aceita envio/reenvio com `projeto.status == EM_ANDAMENTO` — sem isso, o
"PDF Final" do catálogo seria sempre a versão pré-banca, nunca a corrigida.

Correção: a checagem de status passa a aceitar `EM_ANDAMENTO` sempre, e
também `APROVADO_COM_RESSALVAS` quando `projeto.etapa == Projeto.TCC_II`.
Para o TCC_I, nada muda — continua exigindo `EM_ANDAMENTO`.

## 4. Bug encontrado: `meu_tcc` sem tratamento de `ValidationError`

`apps/projetos/views.py::meu_tcc` (linhas ~501–511) chama
`services.enviar_submissao` dentro do `POST` sem `try/except`. Isso já podia
gerar um 500 hoje (o template mostra o formulário de envio incondicionalmente,
independente do status do projeto) — só não era alcançado na prática porque
nada levava o aluno a reenviar fora de `EM_ANDAMENTO`. A correção do item 3
torna esse caminho mais alcançável (o aluno passa a ver o formulário também
em `Aprovado com Ressalvas`, mas ainda pode haver outros estados em que o
reenvio deveria falhar com mensagem, não 500). Correção: envolver a chamada
em `try/except ValidationError`, mesmo padrão já usado em
`aprovar_projeto_view`.

## 5. Camada de serviço

Nova app `apps/publico`, sem models próprios. `apps/publico/services.py`:

```python
def catalogo_publico(area_id=None, ano=None):
    """Projetos publicáveis: TCC_II, Concluído, com TermoPublicacao
    assinado. Mais recente primeiro (data em que a SUGRAD aprovou a ata)."""
    qs = (
        Projeto.objects.filter(
            etapa=Projeto.TCC_II,
            status=Projeto.CONCLUIDO,
            termo_publicacao__isnull=False,
            tema__isnull=False,
        )
        .select_related("tema", "aluno", "orientador", "submissao")
        .order_by("-atas__revisao__decidida_em")
    )
    if area_id:
        qs = qs.filter(orientador__perfil_professor__areas=area_id)
    if ano:
        qs = qs.filter(ano=ano)
    return qs


def calendario_publico():
    """Bancas ainda não realizadas, mais próxima primeiro. Uma banca cuja
    data já passou some da agenda mesmo que o orientador ainda não tenha
    registrado o resultado — calendário é agenda, não histórico."""
    return (
        Banca.objects.filter(status=Banca.AGENDADA, data_hora__gte=timezone.now())
        .select_related("projeto__tema", "projeto__aluno", "projeto__orientador")
        .order_by("data_hora")
    )
```

Filtro de área usa `PerfilProfessor.areas` (M2M já existente desde o Bloco A)
— a área do **orientador** do projeto, não `tema.area` diretamente (embora
`Tema.area` seja obrigatório e coincida na prática, filtrar pelo orientador é
a mesma fonte já usada em outros pontos do sistema e não depende de
`tema` estar presente). Filtro de ano usa `Projeto.ano` (campo simples, já
existe).

Nenhuma paginação ou busca textual nesta primeira versão (YAGNI — volume
atual não justifica).

## 6. Telas

- **`/catalogo/`** — pública, sem login. Lista `catalogo_publico(area_id,
  ano)`; cada item mostra Título, Resumo (truncado), Autor, Orientador, e um
  link de download (`submissao.pdf.url` — já é uma URL pré-assinada do S3/
  MinIO, `querystring_auth=True`, funciona sem sessão Django). Dois
  `<select>` no topo (Área, Ano), formulário GET simples recarregando a
  página via querystring — sem HTMX, não há necessidade de atualização
  parcial.
- **`/calendario/`** — pública, sem login. Lista `calendario_publico()`:
  aluno, título (quando `projeto.tema` existir), orientador, data/hora,
  local. Sem filtro.
- Ambas linkadas em `templates/base.html` (nav pública, visível também a
  quem não está autenticado).

Nenhum dado sensível exposto em nenhuma das duas telas — nem CPF, nem
telefone, nem e-mail (mesma disciplina da regra 6 do `CLAUDE.md`).

## 7. Fora de escopo

- Paginação ou busca textual além do filtro Área/Ano do catálogo.
- Contagem de downloads, exportação RSS/ICS do calendário.
- Filtro no calendário (por área, por orientador) ou histórico de bancas já
  realizadas — calendário é só agenda futura.
- Qualquer edição de `Tema` a partir do fluxo do TCC_II — ele só é lido ou
  escolhido, nunca criado ou alterado por aqui.
- API pública (Bloco H).
- Ordenação alternativa no catálogo (por título, por orientador) — só "mais
  recente primeiro".

## 8. Critérios de aceitação

1. Um TCC_II concluído com termo assinado aparece em `/catalogo/`, com
   Título, Resumo, Autor, Orientador e um link de PDF que baixa de verdade,
   sem login.
2. Um TCC_I concluído sem TCC_II associado NÃO aparece em `/catalogo/`.
3. Um TCC_II concluído SEM termo assinado é impossível de existir (o gate do
   Bloco F já impede `Aprovado`/`Concluído` sem termo) — não precisa de
   checagem redundante no catálogo.
4. Um TCC_II concluído cujo `tema` é `None` (herdado de um TCC_I nascido de
   candidatura aberta) NÃO aparece em `/catalogo/`.
5. Filtrar `/catalogo/?area=<id>` mostra só projetos cujo orientador atua
   naquela área; `?ano=<ano>` filtra por `Projeto.ano`.
6. Uma `Banca` `AGENDADA` com `data_hora` futura aparece em `/calendario/`;
   uma `REALIZADA`, `CANCELADA`, ou com `data_hora` no passado, não aparece.
7. `criar_tcc_ii_automatico` copia o `tema` do TCC_I; `criar_tcc_ii_manual`
   exige um `tema` do professor autenticado (recusa um tema de outro
   professor).
8. Reenviar a submissão do TCC_II em `Aprovado com Ressalvas` funciona
   (atualiza `Submissao`); o mesmo reenvio para TCC_I fora de
   `EM_ANDAMENTO` continua recusado com mensagem clara, não 500.
9. Nenhuma das regras acima está implementada em `views.py` ou `models.py`.
10. `docker compose exec web pytest` passa, incluindo acessibilidade nas
    rotas novas (`/catalogo/`, `/calendario/`).
