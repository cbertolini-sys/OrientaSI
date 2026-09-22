# OrientaSI — Business Rules, Workflow & Domain Logic Audit

## Remediation Status (updated 2026-09-22, second pass)

Following the audit, all 4 Critical and 8 of 9 High findings were fixed in this codebase, each with a new regression test proven by mutation (per CLAUDE.md's own testing discipline — the check was temporarily removed/broken and the test was confirmed to fail before the fix was restored). A number of Medium/Low findings were fixed alongside them. Nothing was committed; the working tree holds the changes.

### Second pass: code review + full re-audit

After the first remediation pass, the diff was reviewed (`/code-review high`) and then **all five areas were re-audited from scratch** by fresh subagents, explicitly tasked with (a) verifying every fix just applied and (b) finding anything the fixes themselves introduced. This caught real regressions the first pass missed:

- **The code review caught 4 issues in the first-pass fixes**, all corrected: a genuine unhandled-`IntegrityError` race still reachable in `aprovar_ata`/`criar_tcc_ii_automatico` under real concurrency (closed with `select_for_update()` on `RevisaoSUGRAD` plus a second-layer `IntegrityError→ValidationError` translation, verified with a new real-thread `django_db(transaction=True)` test mirroring the project's existing `test_coordenacao_concorrencia.py` pattern); a masked admin test that would have passed even without the fix it claimed to prove (rewritten to include every field the mutated form actually requires, with an explicit `errornote` assertion); `agendar_banca` not actually calling the `_substituir_membros` helper its own docstring claimed it did; and an inconsistent `IntegrityError` handler in `agendar_banca` that didn't inspect `constraint_name` like its siblings.
- **The full re-audit surfaced one genuine regression my own C2 fix caused**: wrapping `aprovar_projeto` in `@transaction.atomic` removed the *loud* failure (`IntegrityError`) that used to (accidentally) prevent two concurrent approvals from both generating an `Ata` for the same `Projeto` — atomicity serialized the two `gerar_ata` calls instead, so both succeeded, silently producing two Atas. Fixed with `select_for_update()` on the `Projeto` row in `aprovar_projeto` (same pattern as the rest of the codebase).
- **A template bug (H-1) that made the C1 fix unreachable from the UI**: after `reabrir_projeto`, `/orientacoes/` kept showing the *old* historical banca's "Reprovado" card (with Reabrir/Cancelar buttons) instead of "Agendar banca", because the branch `{% elif projeto.banca_ativa %}` didn't also check `projeto.status == "REPROVADO"`. Fixed and covered by a new HTTP-level test.
- **Two more real concurrency/consistency bugs found by the `apps/publico` re-audit**: `/api/v1/` (the DRF router root) silently went from 200 to 403 after the M13 settings flip, because the router's auto-generated `APIRootView` doesn't inherit the two viewsets' explicit `AllowAny` — fixed with a custom `APIRootView` subclass. And a timezone bug in the homepage mini-calendar (`views.inicio` read `b.data_hora.date()` in UTC instead of localized America/São_Paulo, contradicting the adjacent "Próximas Apresentações" list on the same page) — fixed with `timezone.localtime(...)`.
- Also fixed in this pass: a misleading `ValidationError` message in `criar_tcc_ii_automatico` (said only the TCC II creation failed, when actually the *entire* ata approval was rolled back); the public catalog's area `<select>` listing top-level áreas that can never match anything (filter only matches subáreas); `_projetos_catalogaveis()` missing `submissao__isnull=False` (an admin-created edge case 500'd the entire public API list); a missing tiebreaker on the catalog's `order_by` (non-deterministic pagination under ties); `gerar_ata`'s `IntegrityError` handler not inspecting `constraint_name`; a masked concurrency-test assertion (it would still pass with the `select_for_update()` lock removed, because a sibling defense layer produced an equally-valid-looking refusal — tightened to assert the *specific* refusal message only the lock can produce); a missing `CELERY_TASK_ALWAYS_EAGER` on the new real-thread test (would otherwise publish to the real Redis broker/worker on every run); three stale docstrings still describing the pre-fix behavior; a stray Cyrillic character in a docstring; and three untracked scratch files left in the repo root by the code-review skill's live verification, now deleted.
- **Not fixed, left as documented open findings**: `apps/contas` still has M7/M8/M10 (broker-failure 500 in `convidar`, email change without re-auth, no `desativar_usuario` service) and most Low items; `apps/projetos` still has the fact that nothing prevents a student from having an active TCC I *and* TCC II simultaneously in the two directions H5 didn't cover (F-1 — a real gap, but the fix requires generalizing a check used elsewhere and was left for a deliberate follow-up rather than rushed into an already-large diff); the production PDF-link-expiry issue (H9, infra/deployment, not a code fix); the catalog's "PDF Final might be the pre-defense draft" gap (item 6, needs a new invariant check tied to banca timing); the calendar's weaker consent model than the catalog's (F1, likely an intentional Bloco G decision that deserves a product conversation, not a silent code change); and the cross-cutting `ROTAS`-completeness test gap (item 4, now confirmed High-severity since new business logic sits behind the untested `/meu-tcc/` TCC II branch and 6 of 8 `/orientacoes/` status branches — a real but larger task: writing the completeness-enforcing test plus the missing fixture personas).

**Final verification**: `pytest apps/ tests/` (full suite, all five Playwright cross-cutting suites included) green twice over across both passes; `ruff check .` clean; `makemigrations --check --dry-run` clean throughout. Every fix in both passes was proven by mutation, including the concurrency fixes (real `threading`+`django_db(transaction=True)` tests, not just sequential simulations).

**Fixed and mutation-proven:**
- **C1** — `Banca` uniqueness constraint narrowed to `AGENDADA` only (migration `bancas/0003`); `agendar_banca` translates the residual `IntegrityError` to a `ValidationError`; `anexar_banca_ativa` corrected for the now-possible two-non-cancelled-bancas state.
- **C2** — `aprovar_projeto` wrapped in `@transaction.atomic`.
- **C3** — `aprovar_ata` wrapped in `@transaction.atomic`; root cause closed by H5.
- **C4** — `Projeto.STATUS_TERMINAIS` extracted as the one shared list consumed by both the `UniqueConstraint` and the two "friendly check" functions in `services.py`.
- **H1** — `@require_POST` added to `aprovar_ata_view`/`devolver_ata_view`.
- **H2** — `revogar_coordenacao`'s floor check now excludes inactive coordinators (and is skipped entirely when the target being revoked is itself inactive).
- **H3** — `is_coordenador` added to `UsuarioAdmin.readonly_fields`.
- **H4** — `criar_item_correcao`/`concluir_item_correcao` gated on `etapa == TCC_II` and `status == APROVADO_COM_RESSALVAS`.
- **H5** — `criar_tcc_ii_manual` now rejects a student with an existing active TCC I.
- **H6** — `assinar_termo_publicacao` gated on etapa/status/not-already-signed.
- **H7** — `try/except ValidationError` added to `cancelar` (banca), `concluir_item_view`, `aprovar_ata_view`, `devolver_ata_view`, `reabrir_projeto_view`, `cancelar_projeto_view`, `reenviar_ata_view`, and the `/meu-tcc/` "assinar termo" POST branch.
- **H8** — `@transaction.atomic` added across `apps/bancas/services.py` and `apps/documentos/services.py`, and to the two previously-uncovered functions in `apps/projetos/services.py`.
- **M1** — `Ata.numero` given `unique=True` (migration `documentos/0002`); `IntegrityError` translated in `gerar_ata`.
- **M2** — `registrar_resultado` whitelists `resultado` against `Banca.resultado`'s choices and asserts `projeto.status == AGUARDANDO_DEFESA` before writing.
- **M3** — Closed as a byproduct of H8 (`agendar_banca`/`editar_banca` now atomic); `_substituir_membros` extracted to deduplicate the member-replacement logic (L1).
- **M4** — `cancelar_banca` asserts `projeto.status == AGUARDANDO_DEFESA` before reverting it.
- **M5** — `reenviar_a_sugrad` now clears the stale `comentario`/`decidida_em` from the previous devolution.
- **M6** — `atualiza_perfil` split into an atomic inner function plus an outer wrapper that translates `IntegrityError` to `ValidationError`; `views.perfil` now catches it.
- **M11** — `criar_tcc_i_manual` now cancels the student's in-flight `Candidatura` (and its pending options), mirroring `cancelar_candidatura`.
- **M12** — `orientandos_atuais` no longer filters by the current semester — a non-terminal project from a past semester no longer disappears from `/orientacoes/`, the only screen with the action buttons for it. (`test_orientandos_atuais_so_lista_projetos_em_andamento_do_professor` was reworded since it previously pinned the opposite behavior; a new test pins the fix.)
- **M13** — `REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]` flipped to `IsAuthenticated`; the two public viewsets already declared `AllowAny` explicitly, so `/api/v1/catalogo/` and `/api/v1/calendario/` are unaffected.
- **L1** — `_substituir_membros` helper (see M3).
- **L2** — `Banca.resultado` and `Projeto.status` both widened from `max_length=22` to `32` (migrations `bancas/0004`, `projetos/0007`).
- **L5** — `criar_projeto_sob_limite` now inspects the failing constraint's name before translating `IntegrityError`, instead of assuming it's always the same one.
- **L6** — `criar_tcc_i_manual`/`criar_tcc_ii_manual` reject `aluno == professor` and a deactivated or non-`ALUNO` target, via a shared `_garante_aluno_valido_para_orientacao_manual` helper.
- **L9** — `ProjetoAdmin`/`TermoPublicacaoAdmin` disable `add`, and `ProjetoAdmin` makes `status`/`etapa` read-only.
- **L13** — `views.painel`'s inline `Convite.objects...[:50]` moved to a named `services.convites_recentes()` (`LIMITE_CONVITES_NO_PAINEL` constant), matching the other four lists on that screen.
- **L14** — `FormularioRecuperarSenha.send_mail` given Django's real explicit signature instead of `kwargs.get("context") or args[2]`.

**Investigated and deliberately NOT fixed, with reasoning:**
- **M9** — The audit's own suggested fix (`UniqueConstraint` on `Convite.email` where `usado_em IS NULL`) was implemented, migrated, and then **reverted** after it broke `reenviar_convite` in the *normal*, non-racy path: `reenviar_convite` retires the old invite by setting only `expira_em`, never `usado_em` (documented as intentional — `usado_em` means "accepted", not "superseded"), so a reenvio legitimately produces two `usado_em IS NULL` rows for the same email. A real fix needs a new field distinguishing "superseded" from "pending", which is a small schema/behavior change touching accept/reenvio/display logic — left for a deliberate follow-up rather than rushed. The reasoning is recorded in `Convite.Meta`'s docstring in place of the constraint.
- **H9** (production catalog PDF link expiry), **M7** (broker-failure 500 in `convidar`), **M8** (email change without re-auth), **M10** (no `desativar_usuario` service), **M14–M16** (email-helper dedup, per-recipient retry, `ROTAS` completeness test), and the `apps/publico` M17–M22/L24–L26 findings were **not attempted** in this pass — each is either a deployment/infra decision (H9), a larger feature addition (M8, M10), or a refactor/test-authoring task better scoped on its own rather than folded into an already-large batch. They remain open in the findings above.
- Most Low findings outside the ones listed as fixed were left as-is (documentation drift, `Convite.esta_valido()`'s regra-4 placement, `is_staff` handling in promote/revoke, missing photo-removal UI, etc.) — none affect correctness, and several (like `esta_valido()`) touch a template and several call sites for a style-only win.

**Verification:** every fix above was proven by mutation (the guard was removed, the pinning test was confirmed to fail with the exact predicted symptom, then the guard was restored) and the affected app's test suite was re-run green afterward. `pytest apps/ tests/` (full project, including the 5 Playwright-driven cross-cutting suites), `ruff check .`, and `makemigrations --check --dry-run` were all run clean after every fix landed — confirmed twice, the second time with no concurrent processes.

---

**Date:** 2026-09-22
**Scope:** `apps/contas`, `apps/projetos`, `apps/bancas`, `apps/documentos`, `apps/publico` (HTML + DRF API), plus cross-cutting infrastructure (Celery, email, settings, migrations, test coverage discipline).
**Method:** Five independent read-only audits (one per functional slice, run in parallel), each cross-referencing the code against `CLAUDE.md` (the authoritative Portuguese-language spec) and the existing test suite, with every citation re-verified against the file as it exists today. No code was modified to produce this report.

All file paths are relative to the repo root. Line numbers were verified at audit time — see the note in `CLAUDE.md`'s own "Disciplina de Testes" section about not trusting stale citations.

---

## Executive Summary

The codebase is unusually disciplined for its size: the service-layer convention (`views.py` never mutates the ORM) is **machine-enforced** by `tests/test_arquitetura.py`, concurrency-sensitive paths in the candidatura cascade and vaga limit are protected by `select_for_update()` with documented, *tested* lock ordering, production security settings are thorough and locked down by `tests/test_producao.py`, and shared utilities (`apps/comum`) have no duplicate reimplementations anywhere in the codebase. Where the team applied its own "prove it by mutation" discipline, the code holds up.

That discipline was applied unevenly across the project's timeline. **Everything built in Blocos B and C (temas, candidatura cascade, vaga limit) is solid.** Starting with **Bloco D (bancas) and continuing through E/F (atas, SUGRAD, TCC II)**, a specific pattern repeats: state-transition service functions were written **without `@transaction.atomic`**, and the views that call them were written **without a `try/except ValidationError`**. Because the project runs in Postgres autocommit (no `ATOMIC_REQUESTS`), every `.save()` in those functions is independently and immediately committed. This one gap is the root cause of three of the four Critical findings below, and of most of the High/Medium findings in `apps/bancas` and `apps/documentos`: a WeasyPrint or S3 hiccup during ata generation permanently strands a project in `Aprovado` with no ata; approving an ata can crash with a 500 that leaves the TCC I `Concluído` but no TCC II created; and a `Banca`'s own uniqueness constraint quietly makes the documented "reprovado → reopen → re-schedule" recovery path impossible.

A second, independent thread runs through `apps/contas`: the "last coordinator can't remove their own access" safety net (regra inegociável nº 2) counts *inactive* coordinators as still occupying the floor, so a specific two-step admin sequence can leave the system with zero usable coordinators and no self-service recovery path — precisely the scenario the rule exists to prevent.

A third thread, in `apps/publico`, is reassuring: **no PII leak was found.** Every public HTML template and every DRF serializer was traced field-by-field against the regra 6 allowlist (PDF Final, Título, Resumo, Autores, Orientador), and nothing sensitive reaches either surface. The findings there are instead about correctness under production configuration (a 1-hour-expiring PDF link) and test-coverage gaps that would let a future PII leak through undetected — the tests assert what data is *present*, not what's *absent*.

No findings below are speculative: every Critical and High item was traced to a concrete, reachable sequence of actions through the existing UI/service layer (documented where the reachability required a specific precondition, e.g. admin access). Items whose reachability could not be fully confirmed by static reading are explicitly marked "needs verification" rather than asserted.

**Totals:** 4 Critical · 15 High · 30 Medium · 26 Low/code-smell findings, plus a substantial "verified correct" appendix per area (not reproduced in full here — see the individual audit hand-offs) confirming the candidatura-cascade concurrency model, the production security posture, the architecture-enforcement test, and the public API's field-level privacy allowlist.

---

## CRITICAL

### C1 — `Banca`'s own uniqueness constraint makes the documented "reprovado → reabrir → re-schedule" recovery path permanently impossible
**Files:** `apps/bancas/models.py:57-63`, `apps/bancas/services.py:41`, `apps/projetos/services.py:1402-1412`

```python
# apps/bancas/models.py:57
constraints = [
    models.UniqueConstraint(
        fields=["projeto"],
        condition=~models.Q(status="CANCELADA"),
        name="banca_ativa_unica_por_projeto",
    ),
]
```

The condition excludes only `CANCELADA`. A `REALIZADA` (already-held) banca still occupies the unique slot **forever**, contradicting both the model's own docstring and `CLAUDE.md`'s documented cycle (`Reprovado → reabrir_projeto → Em Andamento → aluno tenta de novo`).

**Deterministic failure scenario (no concurrency needed):** `agendar_banca` → `registrar_resultado(REPROVADO)` → `reabrir_projeto` (all documented, reachable UI actions) → orientador tries to schedule the second defense → `Banca.objects.create(...)` raises `IntegrityError` → the view only catches `ValidationError` → **HTTP 500**, and the student can never be re-defended through the UI.

**Impact:** the entire documented recovery path from `Reprovado` is dead on arrival. Not caught by tests: `test_modelos.py:69` only asserts `CANCELADA + AGENDADA` coexist; nothing exercises `REALIZADA + AGENDADA`.

**Fix direction:** widen the condition to exclude `REALIZADA` as well, or have `reabrir_projeto` cancel the stale banca; either way, translate the resulting `IntegrityError` into a `ValidationError` (`agendar_banca` doesn't today, unlike `criar_projeto_sob_limite`, which already does this correctly).

---

### C2 — `aprovar_projeto` is not atomic: `Aprovado` commits before the Ata is generated, and a PDF/storage failure leaves the project permanently stranded
**Files:** `apps/projetos/services.py:1428-1451` (no `@transaction.atomic`), `apps/documentos/services.py:14-47`

```python
# apps/projetos/services.py:1446
projeto.status = Projeto.APROVADO
projeto.save(update_fields=["status"])

from apps.documentos.services import gerar_ata
gerar_ata(projeto)  # WeasyPrint render + S3/MinIO upload — can raise
```

`config/settings.py` sets no `ATOMIC_REQUESTS`, so line 1447 is **already committed** by the time `gerar_ata`'s `HTML(...).write_pdf()` or `ata.pdf.save(...)` runs and can fail (missing system library, OOM, template error, MinIO/S3 outage).

**Failure scenario:** any of those failures → project is `APROVADO`, no `Ata`, no `RevisaoSUGRAD`, no SUGRAD email, and an unhandled 500 to the orientador. There is **no retry path**: `aprovar_projeto` guards on `status == APROVADO_COM_RESSALVAS`, so it can never be called again, and the SUGRAD panel filters on `Ata`, so the project becomes permanently invisible to the one role that could otherwise intervene.

**Fix direction:** `@transaction.atomic` on `aprovar_projeto` (the `transaction.on_commit` email hooks in `documentos/services.py` already assume this and will simply start working as documented), and/or allow ata regeneration for a project stuck `Aprovado` with no `Ata`.

---

### C3 — `aprovar_ata` is not atomic: `Concluído` commits before `criar_tcc_ii_automatico`, and a real, documented feature (`criar_tcc_ii_manual`) can make it crash irrecoverably
**Files:** `apps/documentos/services.py:50-69` (no `@transaction.atomic`), `apps/projetos/services.py:1454-1482`, `apps/projetos/services.py:1485-1509` (`criar_tcc_ii_manual`), `apps/projetos/models.py:151-155`, `apps/documentos/views.py:31-38`

```python
# apps/documentos/services.py:59
revisao.status = RevisaoSUGRAD.APROVADA
revisao.save(update_fields=["status", "decidida_em"])

ata.projeto.status = Projeto.CONCLUIDO
ata.projeto.save(update_fields=["status"])

if ata.projeto.etapa == Projeto.TCC_I:
    criar_tcc_ii_automatico(ata.projeto)  # bare .create(), no IntegrityError handling
```

**Fully traced, reachable failure scenario:** (1) a student has a TCC I in `Aprovado`, ata pending with SUGRAD; (2) meanwhile a *different* professor legitimately uses "Criar nova orientação" → `criar_tcc_ii_manual` for the *same* student (documented Bloco F path) — nothing in `criar_tcc_ii_manual` checks whether the student already has an active TCC I, so this succeeds; (3) SUGRAD approves the pending ata — lines 59-64 commit (`revisão APROVADA`, TCC I `CONCLUIDO`), then `criar_tcc_ii_automatico`'s bare `Projeto.objects.create(...)` hits the `projeto_ativo_unico_por_aluno_e_etapa` constraint → `IntegrityError`. The view has no `try/except` → **HTTP 500**, and the revisão is now `APROVADA` so the SUGRAD can never re-trigger the action (`"Esta ata já foi revisada."` on retry).

**Impact:** silent, permanent data loss — ata approved, TCC I concluded, no TCC II ever created — hit through two independently legitimate features composed together, with a 500 dead-ending the SUGRAD's only recourse.

**Fix direction:** `@transaction.atomic` on `aprovar_ata`; in `criar_tcc_ii_manual`, reject (with a `ValidationError`) creating a TCC II for a student whose TCC I hasn't reached a terminal status; in `criar_tcc_ii_automatico`, catch `IntegrityError` and no-op if a TCC II already exists rather than raising blind.

---

### C4 — `CANCELADO` is missing from the service-layer "does this student have an active project" checks, though present in the DB constraint: a canceled student is permanently locked out of re-applying
**Files:** `apps/projetos/services.py:635-639` (`_possui_projeto_ativo`), `apps/projetos/services.py:554-559` (`projeto_ativo_do_aluno`), vs. `apps/projetos/models.py:151-155`

```python
# models.py:151 — the actual DB constraint (correct, includes CANCELADO)
condition=~Q(status__in=["CONCLUIDO", "REPROVADO", "CANCELADO"]),

# services.py:635 — the "mirrors the constraint" friendly check (stale, does NOT)
.exclude(status__in=[Projeto.CONCLUIDO, Projeto.REPROVADO])
```

Both service functions' docstrings explicitly claim to mirror the `UniqueConstraint` — they no longer do, since `CANCELADO` was added to the constraint (migration 0004) without updating these two call sites.

**Deterministic failure scenario, entirely through documented UI:** orientador fails the student at the defense (`registrar_resultado` → `REPROVADO`), then clicks "Cancelar projeto" (→ `CANCELADO`, a documented terminal state per `CLAUDE.md` §7, "nenhuma ação definida a partir daqui" — but re-applying to a *different* professor should still be possible, since the DB constraint agrees `CANCELADO` frees up the slot). Instead: `registrar_candidatura` raises `"... já tem uma orientação em andamento..."` forever, `/candidatura/` renders the canceled project as if it were the student's current orientation and never shows the form, and `/meu-tcc/` shows a submission form for a project that can never move again. The student has no path back into the system without a coordination/admin intervention that doesn't currently exist as a screen.

**Not covered by any test** — despite the exact analogous cases for `REPROVADO` and `CONCLUIDO` each having a dedicated pinning test right next to this one, suggesting the gap is an oversight, not a decision.

**Fix direction:** extract the terminal-status list into one constant consumed by both `Projeto.Meta.constraints` and the two service functions.

---

## HIGH

### H1 — SUGRAD's `aprovar_ata_view` (and `devolver_ata_view`) accept GET: CSRF-free, one-click approval of any pending ata
**Files:** `apps/documentos/views.py:31-38, 41-61`

No `@require_POST` — the sole exception in the entire codebase, where every other state-changing view (`apps/contas`, `apps/projetos`, `apps/bancas`) uses it. Because CSRF protection does not apply to safe HTTP methods, `GET /painel/sugrad/<id>/aprovar/` while the SUGRAD session is open — via an `<img src>`, a link-prefetcher, or a malicious email — approves the ata, transitions `Aprovado → Concluído`, and fires `criar_tcc_ii_automatico`, irreversibly. `devolver_ata_view` is only accidentally safe (an empty `QueryDict` fails form validation), not by design.

**Fix direction:** add `@require_POST` to both views, matching every other view in the project.

---

### H2 — `revogar_coordenacao`'s "last coordinator" floor counts *inactive* coordinators, so the system can end up with zero usable coordinators
**File:** `apps/contas/services.py:417-422`, interacting with `apps/contas/services.py:28-50`

```python
atuais = list(Usuario.objects.select_for_update().filter(is_coordenador=True))
if len(atuais) <= 1:
    raise ValidationError("Este é o último coordenador do sistema...")
```

This count is correct — and *tested* to be correct — as the **ceiling** (max 4 coordinators, where an inactive coordinator deliberately still occupies a slot). Reused unmodified as the **floor**, the same inclusion becomes permissive instead of conservative.

**Traced failure scenario:** system has coordinators A and B. A superuser deactivates B in `/admin/`. A (still active) opens the panel and self-revokes — `len(atuais) == 2 > 1` passes, since B is still counted despite being unable to log in. Result: the only remaining `is_coordenador=True` account cannot authenticate. The coordination panel is now unreachable by anyone; recovery requires a separate superuser via `/admin/` or the shell — exactly what regra inegociável nº 2 exists to prevent. Not covered by any existing test (all floor tests use active coordinators).

**Fix direction:** the floor check should count `is_coordenador=True, is_active=True` specifically, while `coordenadores()` (the ceiling/display count) keeps its current, deliberately inclusive semantics.

---

### H3 — Django admin lets a staff user toggle `is_coordenador` directly, bypassing both the 4-coordinator cap and the last-coordinator floor
**File:** `apps/contas/admin.py:37-55`

`UsuarioAdmin` exposes `is_coordenador` as a plain editable field with no `readonly_fields` entry and no `save_model` override delegating to `services.promover_a_coordenador`/`revogar_coordenacao` — the only two gates that enforce `LIMITE_COORDENADORES`. **Reachability is narrower than it looks**: `promover_a_coordenador` grants `is_staff=True` but no model permissions, so an ordinary coordinator promoted through the panel cannot reach this screen. The path requires a superuser or a staff account explicitly granted `contas.change_usuario` — hence High rather than Critical, per the originating audit's own calibration.

**Fix direction:** make `is_coordenador` `readonly_fields` in the admin (promotion has its own dedicated door), consistent with how `TemaAdmin` already locks down `professor` post-creation.

---

### H4 — `ItemCorrecao` creation/completion has no `etapa`/`status` guard: TCC I checklist items and post-approval items are both silently accepted
**Files:** `apps/bancas/services.py:137-160`, `apps/bancas/views.py:120-154`, `apps/bancas/permissions.py:25-28`

The only gate on `criar_item_correcao`/`concluir_item_correcao` is ownership (`orientador == projeto.orientador`); the TCC-II-only, post-defense-only restriction that `CLAUDE.md` describes exists **only as a template `{% elif %}`**, i.e. presentation-only.

**Two deterministic failure scenarios:** (a) an orientador opens `/bancas/<tcc_i_id>/correcoes/` for a **TCC I** project directly (bookmark, typed URL) and adds an item — it's created and emails the student about a checklist requirement `aprovar_projeto` will never actually check for a TCC I; (b) the same URL still works after a TCC II reaches `Aprovado`/`Concluído`/`Cancelado` — a new item is created and the student is emailed about a closed TCC. A third, lower-probability race (concurrent item-add during `aprovar_projeto`'s evaluation) is also unguarded, since `aprovar_projeto` has no lock and no atomic block.

**Fix direction:** move the `etapa == TCC_II` + `status == APROVADO_COM_RESSALVAS` rule into the service functions (this is also a straight regra 4 violation — the rule currently lives only in a template).

---

### H5 — `criar_tcc_ii_manual` doesn't check for an existing active TCC I, enabling the C3 crash
**File:** `apps/projetos/services.py:1485-1509`

The docstring says "for a student without a TCC I in the system," but nothing enforces it, and `FormularioCriarOrientacaoManual.aluno` deliberately lists every student (its own comment argues the `UniqueConstraint` alone is protection enough — true only *within* the same etapa, not across TCC I/TCC II). This is the direct enabler of Critical finding C3.

**Fix direction:** `criar_tcc_ii_manual` should raise `ValidationError` when the student has a non-terminal TCC I.

---

### H6 — `/meu-tcc/`'s "assinar termo" action has no service-layer guard: the etapa/status rule lives only in `views.py`, and double-submit 500s
**Files:** `apps/projetos/views.py:562-573`, `apps/projetos/services.py:1543-1550`

```python
# services.py — only checks ownership
def assinar_termo_publicacao(projeto, por):
    if not permissions.pode_assinar_termo(por, projeto):
        raise PermissionDenied(...)
    return TermoPublicacao.objects.create(projeto=projeto)
```

The view computes `pode_assinar` (etapa == TCC_II, status == APROVADO_COM_RESSALVAS, not already signed) purely for template rendering and **never consults it before calling the service**. Reachable via a direct POST: (1) double-submit → `OneToOneField` unique violation → unhandled `IntegrityError` → 500; (2) a TCC II student in `Em Andamento` can pre-sign before the defense, satisfying `aprovar_projeto`'s gate prematurely; (3) a TCC I student can create a `TermoPublicacao` the spec defines as TCC-II-only. This is also a regra 4 violation (business rule in `views.py`).

**Correctly implemented, for the record:** the model makes "existence = signed" airtight (no blank/unsigned state possible), and there is no un-sign path anywhere in the app layer.

**Fix direction:** move all three conditions into `assinar_termo_publicacao` as `ValidationError`s; wrap the view's call in `try/except`.

---

### H7 — State-changing views across `apps/bancas` and `apps/documentos` return HTTP 500 instead of a message on any double-submit or stale-state POST
**Files:** `apps/bancas/views.py:88, 152`, `apps/documentos/views.py:36, 59`, `apps/projetos/views.py:729-750` (a milder variant)

`cancelar` (banca), `concluir_item_view`, `aprovar_ata_view`, `devolver_ata_view`, and `reabrir_projeto_view`/`cancelar_projeto_view` all call services that raise `ValidationError` on a stale state, with **no `try/except`** in the view. A double-click, a stale browser tab, or a retried POST after a flaky connection turns an action that *already succeeded* into a server error page — contrasted with `aprovar_projeto_view`, which correctly handles this same failure class, proving the team knows the right pattern (`test_tcc_ii.py:450` explicitly pins that exact behavior for a sibling view).

**Fix direction:** wrap each of these calls in `try/except ValidationError` → `messages.error(...)`, mirroring `aprovar_projeto_view`.

---

### H8 — Underlying root cause: no `@transaction.atomic` anywhere in `apps/bancas/services.py`, `apps/documentos/services.py`, or on two functions in `apps/projetos/services.py`
**Files:** `apps/bancas/services.py` (entire file), `apps/documentos/services.py` (entire file), `apps/projetos/services.py:1428, 1454`

Every Bloco B/C service function in `apps/projetos/services.py` (15 of them) is `@transaction.atomic`; **every** Bloco D/E/F function that mutates more than one row is not, in either app. This single gap is the mechanical cause of C1 (partially — the constraint issue compounds it), C2, C3, and contributes directly to H4's race and to several Medium findings below (M1, M2, M5 in the consolidated list). It is called out as its own finding because fixing it in one pass (adding the decorator to ~11 functions) closes multiple independent bug reports at once.

**Fix direction:** `@transaction.atomic` on `agendar_banca`, `editar_banca`, `cancelar_banca`, `registrar_resultado`, `criar_item_correcao`, `gerar_ata`, `aprovar_ata`, `devolver_ata`, `reenviar_a_sugrad`, `aprovar_projeto`, `criar_tcc_ii_automatico`. As a side effect, this also makes the existing `transaction.on_commit(...)` calls in these functions behave as their code already implies they do (today, in autocommit, they run synchronously/inline, not deferred — currently harmless, but silently wrong).

---

### H9 — In production, the public catalog's "Baixar PDF" link expires after 1 hour
**Files:** `config/settings.py:216-220`, `apps/publico/serializers.py:17-18`, `templates/publico/catalogo.html:55`

Production uses `S3Storage` with `querystring_auth: True` and no `AWS_QUERYSTRING_EXPIRE` set anywhere in the repo, so `django-storages`' default (3600s) applies. `Submissao.pdf.url` — the field both the HTML catalog and `/api/v1/catalogo/` expose as the PDF link — is a pre-signed URL that a visitor, a search-engine crawler, or any API consumer that caches the response will find dead after one hour.

**Why it wasn't caught:** dev (MinIO with `custom_domain`) swaps in an unsigned URL that never expires, and the test suite forces `FileSystemStorage` — production is the *only* environment where this URL actually expires, and it has no test coverage.

**Impact:** the catalog's core purpose (regra 6 — expose the final PDF) silently breaks after an hour, with no error surfaced anywhere.

**Fix direction:** either serve the object with public read + `querystring_auth=False` scoped to the `submissoes/` prefix, or add a small `apps/publico` view that signs the URL at click-time (bonus: doesn't expose bucket structure, and gives the API a stable `pdf_url`).

---

## MEDIUM

| # | Area | Title | Files |
|---|---|---|---|
| M1 | bancas/documentos | `Ata.numero` (`NNN/AAAA`) has no `UniqueConstraint`; `count()`-based sequencing collides on concurrent approval *and* on any admin deletion of an ata | `apps/documentos/services.py:25-30`, `models.py:27` |
| M2 | bancas | `registrar_resultado` writes `resultado` straight into `Projeto.status` with no service-layer whitelist (only the form restricts values) | `apps/bancas/services.py:95-113` |
| M3 | bancas | `agendar_banca`/`editar_banca` not atomic: a mid-sequence failure strands a `Banca` with 0-1 members while the project stays `Em Andamento`; `editar_banca` deletes all members *before* re-creating them | `apps/bancas/services.py:41-48, 66-76` |
| M4 | bancas | `cancelar_banca` reverts `Projeto.status` to `Em Andamento` unconditionally (infers state rather than asserting it) — low practical reachability today, robustness gap | `apps/bancas/services.py:79-92` |
| M5 | documentos | `reenviar_a_sugrad` resets `revisao.status` to `Pendente` but leaves the stale `comentario`/`decidida_em` from the previous devolution | `apps/documentos/services.py:90-103` |
| M6 | contas | `views.perfil` doesn't catch `IntegrityError` on a concurrent unique-field collision (CPF/email/matrícula/SIAPE) — the twin flow (`aceitar_convite`) already has this exact protection | `apps/contas/views.py:90-105`, `services.py:246-298` |
| M7 | contas | `convidar`'s Celery dispatch (`on_commit`) can raise on broker downtime *after* the `Convite` row is already committed — the coordinator sees a 500 with no way to know the invite exists | `apps/contas/services.py:173-176`, `views.py:168-179` |
| M8 | contas | E-mail (the login identifier) is user-editable from the profile with no re-authentication, confirmation, or old-address notice — a hijacked session can pivot to a permanent account takeover via "forgot password" | `apps/contas/forms.py:292-334`, `services.py:280-288` |
| M9 | contas | `convidar` has no DB constraint against two simultaneously active invites for the same e-mail (read-then-write race); the "one link at a time" invariant the docstrings claim isn't backed by a constraint | `apps/contas/services.py:156-171`, `models.py:196-239` |
| M10 | contas | No service exists to deactivate a user at all — `is_active` is admin/shell-only, with **no check** that a professor being deactivated has active orientandos; the regra-2 "coordination panel is the exclusive door" principle isn't extended to deactivation | `apps/contas/services.py` (absence), `admin.py:46` |
| M11 | projetos | `criar_tcc_i_manual` doesn't close the student's in-flight `Candidatura` (`EM_CURSO`) — the cascade keeps running for a student who already has a manually-assigned orientador, wasting other professors' review and eventually alerting the coordination about a student who doesn't actually need manual allocation | `apps/projetos/services.py:1512-1540` |
| M12 | projetos | Semester rollover removes an in-progress project from `/orientacoes/` (the only screen offering agendar/aprovar/reabrir/cancelar) — `orientandos_atuais` filters by *current* semester while `Projeto.ano/periodo` are frozen at creation | `apps/projetos/services.py:525-538` |
| M13 | cross-cutting | Global DRF default permission is `AllowAny` — correct for today's two read-only public endpoints, but a fail-open default for whatever authenticated endpoint is added next | `config/settings.py:301-310` |
| M14 | cross-cutting | No shared email helper: `send_mail` boilerplate duplicated across 11 call sites, `_link_login()` copy-pasted verbatim 3×; `apps/comum` (the designated home for cross-app utilities) has no email module | `apps/*/tasks.py` (11 sites) |
| M15 | cross-cutting | `enviar_agendamento_banca` retries its *entire* per-recipient loop on any single failure — already-delivered emails (student, other members) get re-sent up to 4× total; the same defect was identified and documented as "known residue" for a sibling task but not fixed here | `apps/bancas/tasks.py:46-62` |
| M16 | cross-cutting | No test enforces that every non-POST-only route in `urls.py` has a `conftest.py` `ROTAS` entry — two real content gaps found: `/meu-tcc/`'s entire TCC II branch (including the publication-consent button) and 7 of 9 status branches of `/orientacoes/` have never been run through the accessibility/keyboard/touch/responsive suites | `conftest.py:1144-1322` |
| M17 | publico | `catalogo_publico()`'s `order_by("-atas__revisao__decidida_em")` traverses a multivalued (FK, not O2O) relation without `.distinct()` — latent row-duplication / `MultipleObjectsReturned` bomb if a project ever accumulates two Atas (not reachable today, but the admin can create the precondition) | `apps/publico/services.py:28-32` |
| M18 | publico | Catalog eligibility doesn't require a `Submissao` to exist — an admin-created edge case makes the HTML page degrade silently (blank PDF link) but the DRF API 500s the *entire* list, not just the broken item | `apps/publico/services.py:10-15`, `serializers.py:17-18` |
| M19 | publico | Timezone bug in the homepage mini-calendar: `b.data_hora.date()` reads the UTC date instead of localized `America/Sao_Paulo`, contradicting the adjacent "Próximas Apresentações" list (which *does* localize) on the same page, up to 3 hours off | `apps/publico/views.py:23-29` |
| M20 | publico | Catalog's area filter `<select>` lists top-level áreas that never match anything (the underlying filter only matches subáreas, mirroring the professor-profile form which correctly restricts to subáreas) — silently returns "no results" for a plausible user choice | `apps/publico/views.py:75`, `services.py:34` |
| M21 | publico | Nothing enforces that the "PDF Final" shown in the catalog is the post-defense corrected version rather than the pre-banca draft — `aprovar_projeto` doesn't check `submissao.atualizada_em` against the banca date, despite a docstring elsewhere naming this exact invariant as the reason a TCC II resubmission path was reopened | `apps/publico/services.py:10-15`, `apps/projetos/services.py:1438-1444, 582-607` |
| M22 | publico | Test-coverage gap mirroring the audit's own overall theme: no test in `apps/publico` asserts CPF/telefone/e-mail are *absent* from the catalog HTML or API (only presence of safe fields is checked) — a future field leak would pass the suite silently; the calendar API also lacks the catalog API's `set(keys) == {...}` allowlist assertion, and pagination's 20-item cap has no test with 21+ objects | `apps/publico/tests/*` |

---

## LOW / Code Smells

| # | Area | Title |
|---|---|---|
| L1 | bancas | `agendar_banca`/`editar_banca` duplicate the member-persistence + notification block verbatim; a `_substituir_membros` helper would also be the natural home for the missing atomic (M3) |
| L2 | bancas | `Banca.resultado` `max_length=22` is an unexplained exact fit to `"APROVADO_COM_RESSALVAS"` — a future longer status value truncates/errors silently |
| L3 | projetos | `views.py` builds `projeto.ata_ativa` with one query per orientando in a loop (N+1) right next to a correctly-factored single-query sibling (`anexar_banca_ativa`) |
| L4 | documentos | `painel_sugrad` builds one form per ata in the view and misses a `select_related("revisao")` the template needs |
| L5 | projetos | `criar_projeto_sob_limite` translates *any* `IntegrityError` into "student already has an orientation," unlike its sibling `conceder_limite`, which correctly inspects the constraint name first |
| L6 | projetos | Manual creation (`criar_tcc_i_manual`/`criar_tcc_ii_manual`) never checks the target has `papel == ALUNO`, is active, or isn't the requesting professor themself — reachable only via admin-created edge states, not the normal invite flow |
| L7 | projetos | `criar_tcc_i_manual`/`criar_tcc_ii_manual` are near-duplicates of each other, mirrored again in `tasks.py`'s two near-identical notification tasks; "up to 3 options" is hardcoded independently in 4 places with no shared constant |
| L8 | projetos | `enviar_submissao` doesn't delete the previous file from storage on resubmission — orphaned files accumulate in MinIO/S3 |
| L9 | projetos | `apps/projetos/admin.py`'s `ProjetoAdmin` has no `readonly_fields` on `status`/`etapa` and no `has_add_permission` override — a staff user with model access can create a `Projeto` bypassing the vaga limit or jump straight to `Concluído`; reachability is superuser-only under the current permission-granting flow |
| L10 | contas | `aceitar_convite`'s generic `IntegrityError` handler blames "CPF, matrícula or SIAPE" for what can actually be an e-mail collision (the check ran too early, at invite time, not re-verified at accept time) |
| L11 | contas | `Convite.esta_valido()` is a business-rule method living in `models.py`, against regra 4 — the one exception in an otherwise clean codebase (the team's own `signals.py` docstring shows they're aware of this exact rule) |
| L12 | contas | `revogar_coordenacao` unconditionally clears `is_staff`, which can strip a superuser's own admin access if they were also a coordinator; `promover_a_coordenador` grants `is_staff` with no accompanying model permissions, making it inert until H3's admin path is closed |
| L13 | contas | `views.painel` queries `Convite` directly with a hardcoded `[:50]`, the one list in that view not sourced from the service layer (the surrounding comment explains why the other four lists *are*) |
| L14 | contas | `FormularioRecuperarSenha.send_mail` reads Django's internal `PasswordResetForm.save()` argument by position (`args[2]`), fragile to a future Django signature change |
| L15 | contas | No way to remove a profile photo once uploaded from the UI (form omits `initial`, so the "clear" checkbox never renders) — admin-only removal |
| L16 | contas | No constraint ties `PerfilAluno`/`PerfilProfessor` to `Usuario.papel`, and nothing prevents one account from having both — reachable only via admin/shell, not the invite flow; the coordinator seeded by `semear_sistema` has neither profile and can't publish a tema or orient without manual admin intervention |
| L17 | contas | `revogar_coordenacao`'s concurrency safety is correct by inspection (traced through READ COMMITTED + EvalPlanQual) but, unlike its `promover` sibling, has no dedicated concurrency test — a violation of the project's own "prove it by mutation" rule for its most delicate remaining lock |
| L18 | contas | Minor doc/implementation drift: upload validators live only in `apps/comum`, not also `apps/contas/validators.py` as `CLAUDE.md` implies; extension validation is filename-only (mitigated for images by Pillow content sniffing); the invite token travels in plain text through the Celery task queue and the URL path (hence access logs/`Referer`) |
| L19 | cross-cutting | No `LOGGING` config and no `task_soft_time_limit` — a periodic task or email task that fails deterministically retries forever with nobody notified beyond a worker-stdout line |
| L20 | cross-cutting | `CELERY_TASK_ACKS_LATE = True` is set globally rather than per-task; combined with non-idempotent email sends, a worker crash mid-task can redeliver and double-send an email (low-probability, no data corruption) |
| L21 | cross-cutting | Upload validators are declared on model fields but only actually run because every current caller goes through a form that redeclares them — `enviar_submissao` never calls `full_clean()`, so a future non-form caller (management command, API) would silently skip extension/size validation |
| L22 | cross-cutting | Dead code: an unused `logger` in `apps/bancas/tasks.py` (copy-paste residue); a test module imports `semestre_vigente` via a re-export path instead of the canonical `apps.comum.semestre` |
| L23 | cross-cutting | `CSRF_TRUSTED_ORIGINS` is not set for the production reverse-proxy deployment — likely fine given `SECURE_PROXY_SSL_HEADER` is configured, but unverified against the actual proxy config outside this repo |
| L24 | publico | No rate limiting (`DEFAULT_THROTTLE_CLASSES`) on the two anonymous public API routes |
| L25 | publico | The HTML `/catalogo/` and `/calendario/` pages render their full result set with no pagination, unlike the API (20/page) — harmless today, will not scale |
| L26 | publico | Querystring parsing/coercion (`area`, `ano`) is duplicated between the HTML view and the API viewset (the underlying eligibility query itself is correctly shared via `services.py`, so this is a smaller, cosmetic duplication) |

Additional low-severity/informational notes from the `publico` audit, not requiring action but worth recording: the cross-cutting accessibility suite measures `/catalogo/` and `/calendario/` while *authenticated*, which is never the state a real public visitor is in (functional anonymous-access tests exist separately and are correct); `BrowsableAPIRenderer` is active in production on read-only endpoints, a slightly larger surface than necessary; and `TermoPublicacao` consent is a hard precondition for graduation with no revocation path anywhere in the app layer — a legitimate product decision, flagged only because "irrevocable consent required to graduate" merits a conscious LGPD read, not because it's a bug.

---

## Verified Correct (selected highlights — not an exhaustive list)

To avoid the report reading as universally critical, and per each sub-audit's own methodology, the following load-bearing mechanisms were specifically checked and confirmed sound:

- **The vaga-limit lock** (`criar_projeto_sob_limite`) and the **candidatura-cascade lock ordering** (`Candidatura` → `PerfilProfessor`, consistently applied across `aceitar_opcao`, `recusar_opcao`, `avancar_cascata`) are correctly implemented, `@transaction.atomic`, and covered by real multi-thread/multi-connection regression tests (`test_concorrencia.py`, `test_prazo.py`) — including the specific "professor accepts at the exact instant Celery's beat expires the option" race.
- **The Celery Beat periodic task** (`avancar_candidaturas_vencidas`) is idempotent under double-firing, isolates per-iteration failures, and re-validates state after acquiring its lock. This is, per the cross-cutting audit, "the strongest part of the codebase."
- **No PII reaches any public surface.** Both DRF serializers are explicit (not `ModelSerializer`), every `source=` points to a scalar field, and neither the OpenAPI schema nor any public template touches CPF, telefone, e-mail, matrícula, or SIAPE.
- **Production security posture** (`DEBUG=False`, env-sourced `SECRET_KEY`, HSTS, secure cookies, S3 private-by-default with signed URLs) is thorough and locked down by `tests/test_producao.py`'s `manage.py check --deploy --fail-level=WARNING`.
- **The service-layer architecture rule (regra 4) is enforced by an AST-parsing test** (`tests/test_arquitetura.py`) that fails the build if any view calls a mutating ORM method — not just documented, mechanically guaranteed (with the two narrow, already-documented exceptions noted in H6/L11 above).
- **`apps/comum` is a genuine single source of truth** — no duplicate CPF validator, no duplicate upload validator, no duplicate `semestre_vigente` implementation anywhere in the codebase.
- The 4-coordinator ceiling **is** race-safe under real concurrency (two-thread test with a deliberate delay), the double-booking constraint on `Banca` **does** prevent two simultaneously `AGENDADA` bancas, and double-`registrar_resultado` **is** correctly blocked and tested.
- Migrations are in sync with models (`makemigrations --check` → "No changes detected"), and the two non-schema migrations in the codebase both have correct, tested reverse operations.

---

## Strategic & Architectural Recommendations

Ordered by leverage — the first two items alone resolve or substantially mitigate 3 of 4 Critical findings and roughly a third of the High/Medium list.

1. **Wrap every Bloco D/E/F state-transition service function in `@transaction.atomic`.** This is the single highest-leverage fix in the report: it directly resolves C2, C3, and M3/M5, and it makes the existing (currently inert) `transaction.on_commit` calls in `apps/bancas` and `apps/documentos` behave as their own code already implies. Roughly 11 functions across two files.
2. **Add `@require_POST` to `apps/documentos/views.py`'s two mutating views and wrap every un-guarded state-transition view in `try/except ValidationError`.** Resolves H1 and H7 in one consistent pass, matching the pattern already used correctly elsewhere (`aprovar_projeto_view`).
3. **Extract a single shared "terminal status" constant** consumed by both `Projeto.Meta.constraints` and the service-layer "does this student have an active project" helpers, closing C4 and preventing the next constraint update from silently drifting out of sync with its own service-layer mirror again.
4. **Give `apps/comum` an email-sending helper** (`enviar_email(assunto, template, contexto, destinatarios)`), collapsing the 11 duplicated `send_mail`/retry blocks into one place — directly fixes M14, and makes M15's per-recipient retry bug a one-line fix to apply consistently everywhere.
5. **Add a `UniqueConstraint` on `Ata.numero`.** Turns a silently-accepted, low-probability duplicate-legal-document race into a loud, retryable `IntegrityError` — a small change with an outsized reduction in worst-case damage (M1).
6. **Fix the coordinator-floor count and lock down `is_coordenador` in the admin together** (H2 + H3) — they're two doors to the same invariant; closing only one leaves the safety net with a hole.
7. **Add a test that diffs `conftest.py`'s `ROTAS` list against every non-POST-only route in every app's `urls.py`**, and add the two missing personas identified (M16: `/meu-tcc/` in the TCC II branch, `/orientacoes/` in its other 7 status branches). This is process, not product — but it's the exact enforcement mechanism the project already builds for its architecture rule (`test_arquitetura.py`) and for `ROTAS` membership, just not yet for *completeness* of that list.
8. **Introduce a real `services.desativar_usuario`** with a guard against deactivating a professor with active orientandos, giving the coordination panel a door for an operation that currently only exists as a bare, unchecked admin toggle (M10) — and extend the same "no orphaned Convite left dangling" care already shown elsewhere in `apps/contas` to this path.
9. **Add negative-assertion privacy tests** (`assert usuario.cpf not in resposta.content`) to `apps/publico`'s test suite. The audit found no leak today, but the suite currently only proves what data *is* present — exactly the shape of regression that would pass silently, which is the one category of bug this system can least afford.
10. **Resolve the production PDF-link expiry (H9) before the catalog is relied on in production** — it is the kind of bug that is invisible in every environment except the one that matters, and it undermines the entire purpose of Bloco G.

---

## Summary Table

| ID | Severity | Area | Title |
|---|---|---|---|
| C1 | Critical | bancas | `banca_ativa_unica_por_projeto` blocks all re-scheduling after `reabrir_projeto` |
| C2 | Critical | projetos/documentos | `aprovar_projeto` not atomic — PDF/storage failure permanently strands `Aprovado` with no Ata |
| C3 | Critical | documentos/projetos | `aprovar_ata` not atomic — manual TCC II creation can crash it, losing the automatic TCC II forever |
| C4 | Critical | projetos | `CANCELADO` missing from service-layer active-project checks — student locked out permanently |
| H1 | High | documentos | `aprovar_ata_view`/`devolver_ata_view` accept GET — CSRF-free approval |
| H2 | High | contas | Coordinator floor counts inactive coordinators — can reach zero usable coordinators |
| H3 | High | contas | Admin can toggle `is_coordenador` directly, bypassing cap/floor (superuser-reachable) |
| H4 | High | bancas | `ItemCorrecao` create/complete has no etapa/status guard (template-only) |
| H5 | High | projetos | `criar_tcc_ii_manual` doesn't check for an existing active TCC I |
| H6 | High | projetos | `/meu-tcc/` "assinar termo" has no service-layer guard; double-submit 500s |
| H7 | High | bancas/documentos/projetos | Multiple state-changing views 500 instead of messaging on double-submit |
| H8 | High | bancas/documentos | Root cause: no `@transaction.atomic` across nearly all Bloco D/E/F services |
| H9 | High | publico | Production catalog PDF link expires after 1 hour, untested |
| M1–M22 | Medium | (mixed) | See Medium table above |
| L1–L26 | Low | (mixed) | See Low table above |

**Totals: 4 Critical · 9 named High findings (H8 itself accounts for the mechanism behind several) · 22 Medium · 26 Low.**

---

*This report reflects a point-in-time, read-only static + test-suite audit. No code was changed. Items marked "needs verification" in the individual sub-audits (concurrency reproductions not run against a live database, and one deployment-environment question about `CSRF_TRUSTED_ORIGINS`) should be confirmed empirically before prioritization, per the project's own "prove it, don't assert it" testing discipline.*
