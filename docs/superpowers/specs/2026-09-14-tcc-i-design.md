# TCC I — Design do Bloco C

**Bloco:** C (de A–H; ver §12 da spec da Fase 1,
`docs/superpowers/specs/2026-09-08-fundacao-e-contas-design.md`)

## 1. Objetivo

O `Projeto` nasce no Bloco B (aceite de uma opção de candidatura) e para no status
`EM_ANDAMENTO` — nenhuma tarefa do Bloco B avança o ciclo de vida além disso. Este
bloco dá ao aluno o meio de entregar o trabalho escrito: o modelo `Submissao` (PDF +
editável) e a tela para enviá-lo e reenviá-lo, com o orientador enxergando o que foi
entregue.

## 2. Escopo

### Dentro

- Modelo `Submissao`, uma linha por `Projeto`.
- Serviço de envio/reenvio, com validação de extensão e tamanho.
- Tela do aluno para enviar/reenviar.
- Visibilidade do orientador (extensão da tela de orientações do Bloco B).

### Fora

- **Qualquer transição de `Projeto.status`.** O `Projeto` continua `EM_ANDAMENTO` ao
  fim deste bloco. `Aguardando Defesa` é responsabilidade do Bloco D — ver §3.1.
- **Qualquer ação do orientador sobre a submissão.** Ele só vê o que foi enviado;
  não há confirmação, aprovação nem qualquer outro gate neste bloco.
- **Agendamento de banca**, `Banca`, `MembroBanca`, `Avaliacao` — Bloco D.
- **Histórico de versões anteriores.** Reenviar substitui a entrega atual; a versão
  anterior não fica acessível pelo sistema (§3.2).
- **`coorientador` em `Projeto`.** Previsto no mapa de domínio original (§12 da spec
  da Fase 1: `Projeto: aluno, orientador, coorientador, etapa...`) e nunca
  implementado pelo Bloco B. Nenhuma tela ou regra deste bloco depende dele.
  **Lacuna registrada, não decidida aqui:** decidir antes de qualquer bloco que
  precise de um segundo orientador.
- Um campo `tipo` em `Submissao`, também previsto no mapa original. Sem uso neste
  bloco — se o Bloco F precisar distinguir tipos de envio (ex.: versão final
  pós-correções), decide na hora, sem depender desta decisão.

## 3. Decisões de arquitetura

### 3.1 A transição para `Aguardando Defesa` não é deste bloco

O `CLAUDE.md` descreve a transição como "aluno envia PDF/editável **e** orientador
agenda a banca" — duas condições, e a segunda depende do modelo `Banca`, que só
existe no Bloco D. Fechar a transição aqui exigiria um agendamento provisório
(campos soltos de data/local) que o Bloco D teria que substituir depois — trabalho
duplicado, ou pior, dois lugares divergentes guardando "quando é a banca".

**Decisão:** este bloco só entrega a `Submissao`. `Projeto.status` continua
`EM_ANDAMENTO` mesmo depois do envio. O Bloco D, ao especificar `agendar_banca`
(ou nome equivalente), decide como verificar que existe uma `Submissao` antes de
permitir o agendamento, e é ele quem grava a transição.

### 3.2 Reenviar substitui, não versiona

`Submissao` é uma linha por `Projeto` (`OneToOneField`), atualizada em cima do
mesmo registro a cada reenvio — não uma tabela de histórico. O campo `versao`
(inteiro, começa em 1, incrementado a cada reenvio) existe só para exibição
("está na 3ª versão enviada"); a versão anterior não é recuperável pelo sistema
depois de substituída.

**Custo aceito:** se um dia for preciso auditar o que foi enviado antes de uma
correção, o sistema não guarda isso. Decisão do usuário, ciente do trade-off
(a alternativa — histórico completo, sem limite de versões — foi apresentada e
recusada).

### 3.3 Os dois arquivos são obrigatórios juntos

PDF e editável são exigidos no mesmo envio, não em momentos separados. O PDF é
para leitura e avaliação da banca (Bloco D); o editável é para o Bloco F poder
aplicar as correções do checklist ao documento. Sem o editável, o Bloco F não
teria como produzir a versão corrigida.

### 3.4 Sem ação do orientador neste bloco

O envio do aluno é um depósito puro. O orientador enxerga o que foi enviado
através da extensão da tela de orientações do Bloco B (`orientacoes.html`,
`services.orientandos_atuais` — `apps/projetos/services.py:398` e
`apps/projetos/views.py`, conferir a linha exata ao implementar, este spec foi
escrito antes de qualquer edição do Bloco C nesses arquivos), mas nenhuma ação
dele é exigida ou possível sobre a submissão. Isso mantém o bloco pequeno e a
fronteira com o Bloco D limpa: o gate de "documento pronto para banca" é uma
decisão humana do orientador, fora do sistema, até o dia em que ele agenda a
banca.

## 4. Modelagem de dados

### 4.1 `Submissao`

| campo | tipo | observações |
|---|---|---|
| `projeto` | `OneToOneField(Projeto)` | uma submissão por projeto, `PROTECT` — apagar o `Projeto` não pode arrastar a submissão em cascata, mesmo raciocínio de `Candidatura.aluno`/`OpcaoCandidatura.tema` no Bloco B |
| `pdf` | `FileField` | `upload_to="submissoes/"`, `validators=[valida_extensao_pdf, valida_tamanho_arquivo]` — só `.pdf` |
| `editavel` | `FileField` | `upload_to="submissoes/"`, `validators=[valida_extensao_editavel, valida_tamanho_arquivo]` — só `.docx` |
| `versao` | `PositiveSmallIntegerField` | `default=1`; incrementado a cada reenvio (§3.2) |
| `enviada_em` | `DateTimeField` | `auto_now_add=True` — data do primeiro envio |
| `atualizada_em` | `DateTimeField` | `auto_now=True` — data do envio mais recente |

Sem `Meta.constraints` além do `OneToOneField` (que já garante unicidade por
`Projeto` via índice único implícito do Django).

**Decisão:** `pdf` e `editavel` usam validators de extensão distintos, não o
`valida_extensao_documento` genérico (que aceita `.pdf` **e** `.docx` em
qualquer campo — pensado para `foto`-like uploads de um tipo só, não para dois
campos com formatos diferentes e nomes que prometem qual é qual). Acrescente
`valida_extensao_pdf` (só `.pdf`) e `valida_extensao_editavel` (só `.docx`) a
`apps/comum/validators.py`, seguindo o formato de `valida_extensao_imagem` —
`_valida_extensao(arquivo, {".pdf"})` e `_valida_extensao(arquivo, {".docx"})`
respectivamente. Sem isso, um aluno pode enviar um `.docx` no campo `pdf` (ou
vice-versa) sem nenhum erro, e a banca (Bloco D) receberia um "PDF" que na
verdade é um `.docx` — falha só descoberta na hora de abrir o arquivo.

## 5. Camada de serviço

`apps/projetos/services.py` (mesmo arquivo do Bloco B — `Submissao` é do mesmo
domínio `projetos/`). Nenhuma destas regras aparece em `views.py` ou `models.py`.

```
enviar_submissao(projeto, por, pdf, editavel) -> Submissao   cria ou atualiza; incrementa versao
```

`por` é o `Usuario` autenticado que faz a chamada — a permissão (só o aluno do
próprio `Projeto`) é checada dentro do serviço, no mesmo padrão de
`apps/projetos/permissions.py::pode_editar_tema`/`_e_o_dono` (posse), não por
papel. A view escopa o lookup do `Projeto` ao aluno autenticado
(`get_object_or_404(Projeto, pk=..., aluno=request.user)`), no padrão que o
Bloco B fixou em `editar_tema`/`desativar_tema` (T6) para não abrir um oráculo
de existência — tema alheio e tema inexistente respondem o mesmo 404.

`apps/projetos/permissions.py`: `pode_enviar_submissao(usuario, projeto)`.

### 5.1 Quando `enviar_submissao` pode ser chamado

Só quando `projeto.status == Projeto.EM_ANDAMENTO`. Como nenhum outro status é
alcançável até o Bloco D existir, esta checagem é hoje inalcançável em produção
— mas escreva-a mesmo assim, com teste, para o dia em que o Bloco D avançar o
status e um aluno tentar reenviar depois da banca já agendada. (Mesma lição do
Bloco B: uma checagem sem teste, mesmo que hoje inalcançável, é o tipo de coisa
que passa despercebida quando o resto do sistema muda ao redor dela.)

## 6. Telas

| rota | quem | o quê |
|---|---|---|
| `/meu-tcc/` (`projetos:meu_tcc`) | aluno | ver o projeto atual (se houver), enviar/reenviar `Submissao` |

A tela de orientações do Bloco B (`/orientacoes/`) ganha, para cada orientando
em `orientandos_atuais`, um indicador de "enviou" / "não enviou" e um link para
baixar o que foi enviado, se houver.

**Decisão:** o link entra na navegação por **papel** (todo aluno vê), não por
existência de `Projeto` — mesmo padrão que o Bloco B já usa para todos os
outros links de `base.html` (nenhum deles verifica estado, só papel). Um aluno
sem `Projeto` ativo abre a tela e vê um estado vazio explicando o motivo ("você
ainda não tem uma orientação em andamento"), no mesmo formato que
`orientacoes.html`/`candidatura.html` já usam para seus próprios estados
vazios. Condicionar a navegação por estado seria um tipo de checagem que
`base.html` não tem hoje, e não há necessidade de introduzi-la aqui.

## 7. Notificações

Nenhuma neste bloco. O orientador vê a submissão passivamente ao abrir
`/orientacoes/`; não há e-mail de "aluno enviou o trabalho". Se isso for
desejável, é uma extensão futura, não decidida aqui.

## 8. Pré-requisitos herdados dos Blocos A e B

- `apps/comum/validators.py::_valida_extensao` (helper privado),
  `valida_tamanho_arquivo` — existem; `valida_extensao_pdf`/
  `valida_extensao_editavel` são novos (§4.1), seguindo o formato de
  `valida_extensao_imagem`, o único validator de extensão em uso hoje (para
  `Usuario.foto`). `valida_extensao_documento` (que aceita `.pdf`/`.docx` em
  qualquer campo) existe mas não é usado por este bloco — ver a decisão em
  §4.1 sobre por que os dois campos precisam de validators distintos.
- `settings.TAMANHO_MAXIMO_UPLOAD_MB = 15`.
- Armazenamento de mídia via `django-storages` (S3/MinIO), mesmo padrão de
  `Usuario.foto` — `config/settings.py::STORAGES`.
- `apps/projetos/services.py::orientandos_atuais`, `views.py::orientacoes`,
  `templates/projetos/orientacoes.html` (Bloco B, T9) — pontos de extensão
  para a visibilidade do orientador.
- Navegação condicional por papel em `templates/base.html` (Bloco B, T12) —
  a rota nova do aluno entra ali, no mesmo padrão.

## 9. Testes

Seguindo a disciplina registrada no `CLAUDE.md` (§"Disciplina de Testes",
escrita ao fim do Bloco B): toda checagem nova provada por mutação, nunca só
pela suíte passando — em especial a permissão de posse (§5) e a checagem de
status (§5.1), que hoje é inalcançável e por isso mais fácil de esquecer de
testar.

Casos mínimos:
- aluno envia PDF + editável válidos; `Submissao` criada com `versao=1`.
- reenvio atualiza a mesma linha, incrementa `versao`, substitui os arquivos.
- extensão errada é recusada em cada campo especificamente: um `.docx` no
  campo `pdf` é recusado (não só extensões fora de `.pdf`/`.docx`), e um
  `.pdf` no campo `editavel` também — prova de que os validators são
  distintos por campo, não o genérico `valida_extensao_documento`.
- arquivo maior que `TAMANHO_MAXIMO_UPLOAD_MB` é recusado.
- professor (ou aluno de outro projeto) tentando enviar para um `Projeto` que
  não é seu recebe 404 (lookup escopado, não 403 pós-lookup).
- `Projeto` em qualquer status diferente de `EM_ANDAMENTO` recusa o envio —
  mutação obrigatória: comente esta checagem e confirme que algum teste
  reprova, mesmo sabendo que hoje nenhum outro status é alcançável em produção
  (o teste cria o `Projeto` diretamente com outro status, sem depender de o
  Bloco D existir).
- `/orientacoes/` mostra corretamente "enviou"/"não enviou" para os dois casos.

## 10. Critérios de aceitação

1. Aluno com `Projeto` `EM_ANDAMENTO` envia PDF e editável; `Submissao` criada.
2. Reenviar substitui o conteúdo anterior e incrementa `versao`.
3. Extensão errada — inclusive `.docx` no campo `pdf` ou `.pdf` no campo
   `editavel`, não só extensões fora de `.pdf`/`.docx` — ou arquivo acima de
   15MB, é recusado com mensagem clara.
4. Enviar sem um dos dois arquivos é recusado.
5. Aluno de outro projeto (ou professor) tentando enviar para um `Projeto`
   alheio recebe 404, não 403.
6. `Projeto.status` permanece `EM_ANDAMENTO` depois do envio — nenhuma
   transição de status acontece neste bloco.
7. `/orientacoes/` mostra o estado de envio de cada orientando.
8. Nenhuma das regras acima está implementada em `views.py` ou `models.py`.
9. `docker compose exec web pytest` passa, incluindo acessibilidade na rota
   nova.
