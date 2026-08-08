# Documentation + Code-Quality Campaign — Design Spec

**Date**: 2026-08-09
**Status**: Draft — pending maintainer review
**Owner**: Repository maintainers
**Related tracker**: (to be filed) `[META] Documentation + code-quality campaign`

---

## 1. Context

clinosim is a synthetic-EHR simulator distributed as an open-source project.
As the codebase has grown to roughly 40 Python packages under `clinosim/`
(including 32 `modules/*` subpackages and a substantial `modules/output/fhir_r4/`
subtree), the documentation and code-comment surface has drifted:

- The top-level `README.md` (English) and `README.ja.md` (Japanese) are
  present but predate several architectural changes.
- Every module under `clinosim/modules/*` has an English `README.md`, but
  no Japanese counterpart, and their content quality is uneven.
- Core packages (`simulator/`, `audit/`, `benchmarks/`, `eval/`, `types/`,
  `dataset/`, `config/`) and the FHIR-R4 output subtree (nine sub-directories)
  have no README at all.
- Source-code comments mix English and Japanese without an explicit policy.
  Some modules that would benefit from Japanese (JLAC10 / JJ1017 / JP-CLINS
  lab code) already use it; others contain Japanese comments that should be
  English for a global contributor audience.
- Constants and thresholds are scattered across files with no consistent
  documentation of their meaning, unit, or provenance.
- Two audits (static-analysis and semantic) have never been run project-wide,
  so an unknown amount of dead code may exist.

This spec defines **(a)** a persistent documentation + code-quality policy
that all future maintenance work must follow, and **(b)** a one-time
15-Issue campaign that brings the current tree into compliance with that
policy.

---

## 2. Persistent policy (durable rules)

**All contributors — human and AI-agent — must follow these rules when
adding, modifying, or reviewing code and documentation.** These rules
outlive this campaign. Once the campaign lands, the same rules govern
every subsequent PR.

This section is the canonical statement of the policy. When Issue #2
of the campaign is complete, this policy will be extracted into
`docs/design-guides/documentation-and-code-quality-policy.md` and
referenced from `AGENTS.md` and `CONTRIBUTING.md`. Until then, this
spec is the single source of truth.

### 2.1 Documentation language

| File                                         | Language                              | Required |
|----------------------------------------------|---------------------------------------|----------|
| Root `README.md`                             | English                               | Yes      |
| Root `README.ja.md`                          | Japanese                              | Yes      |
| Every package/module directory `README.md`   | English                               | Yes      |
| Every package/module directory `README.ja.md`| Japanese                              | Yes      |
| `docs/**/*.md` (English canonical)           | English                               | Yes      |
| `docs/**/*.ja.md` (Japanese mirror)          | Japanese                              | If an EN counterpart exists that a JP audience is expected to read |

**Rule**: whenever a new user-facing or contributor-facing documentation
file is added in English, a Japanese counterpart is added in the same
directory using the `<name>.ja.md` suffix. Whenever the English file is
updated, the Japanese file is updated in the same PR (or a follow-up
Issue is filed and linked in the PR description).

### 2.2 Cross-document linking (language consistency)

- Links inside an **English** document point to **English** documents.
- Links inside a **Japanese** document point to **Japanese** documents.
- If the target document only exists in one language, the link may point
  to the other language, but the link text must include a language marker
  (e.g. `[foo (English)](foo.md)` inside a Japanese doc). File a follow-up
  Issue to add the missing translation.
- External links (GitHub Issues, upstream specs, RFCs) may be in either
  language and do not need a marker.

### 2.3 Self-contained OSS quality

All READMEs and docs (including Issue bodies) must be understandable to
a first-time contributor who has no prior context on the repository or
its history.

**Prohibited in any repo-committed document or Issue body**:

- Session or conversation identifiers (`session-NN`, "last session", etc.)
- Insider pronouns ("you and I", "as we discussed", "私", "あなた")
- References to local, gitignored files (`.resume-prompt.md`, personal notes)
- Un-explained project-internal jargon without a link to a definition
- Time-relative language without an absolute date ("yesterday", "recently"
  → use `YYYY-MM-DD`)

**Required in every README**:

- Purpose sentence (what does this module do, in one sentence)
- Scope boundaries (what it does not do; what other modules do instead)
- Public API surface (what does it export; what should callers import)
- Dependencies (which other modules or external systems does it use)
- Constants and configuration (see §2.5)
- Testing pointer (how to run the module's tests)
- Ownership / area lead (may be `maintainers@` if no single owner)

The [`.github/TEMPLATE_MODULE_README.md`](../../.github/TEMPLATE_MODULE_README.md)
boilerplate is the starting point for any new module README.

### 2.4 Source-code comment language

**Default: English.** Every comment (line comment, docstring, TODO/FIXME
marker, block comment) is written in English unless it falls into an
explicitly permitted Japanese-comment category.

**Permitted Japanese-comment categories**:

1. **JP-Core / JP-CLINS profile invariants.** When a comment exists to
   document a Japanese healthcare profile constraint (e.g. "JP eCS
   requires `MedicationRequest.status='completed'`") and the surrounding
   variable / element names come from the Japanese spec vocabulary
   (`検体検査`, `処方せん`, `救急`, etc.), Japanese is permitted so that
   Japanese-locale contributors can cross-reference the spec text.
2. **JLAC10 / JJ1017 / MEDIS code-system specifics.** Comments that quote
   or explain a Japanese code-system entry (five-axis JLAC10, JJ1017
   procedure code, MEDIS drug master, YJ code, HOT code) may include the
   original Japanese text of the code entry.
3. **Verbatim quotes from Japanese authoritative sources** (厚生労働省
   通知, JAHIS technical reports, jpfhir.jp implementation guides).
   Quote the source in Japanese and add a one-line English gloss.

**All other comments must be English**, including:

- Simulator core (`clinosim/simulator/`)
- Audit / eval / benchmark harnesses
- Non-JP module business logic
- Test files
- CLI help strings (use gettext-style locale files for translation)

A comment that only says "Japanese output" or "JP handling" without
quoting the spec text does **not** qualify for the Japanese exception —
write it in English.

### 2.5 Constants and configuration

Every scalar constant, threshold, cutoff, or magic number that affects
patient state, clinical logic, resource output, or a user-visible number
must be:

1. **Named** (never inlined as a bare literal in the middle of an expression),
2. **Docstring-annotated** with:
   - purpose (what does it mean),
   - unit (mg/dL, days, count, probability, …),
   - source / rationale (clinical reference, spec section, empirical tuning,
     link to a design ADR or external source),
3. **Located** in one of:
   - a module-local `_constants.py` (private to the module),
   - the module's public `__init__.py` if the constant is part of the API,
   - `clinosim/config/*.yaml` if runtime-configurable,
   - `clinosim/types/config.py` if a typed config model.

Bare `MAGIC_NUMBER = 42` without a docstring is a review-blocker.

### 2.6 Dead-code hygiene

- CI runs `ruff` with F401 (unused import) and F841 (unused local) as
  errors. This is baseline.
- On every major release cycle (or at least every six months), maintainers
  run `vulture` at a confidence threshold of 80% or higher, review the
  results, and either delete dead symbols or add them to a by-design
  exclusion registry (`.vulture-whitelist.py` or equivalent) with a
  one-line comment explaining why the symbol looks unused but must be kept
  (e.g. plugin entry-point, reflected access, public API kept for backward
  compatibility).
- When removing dead code, prefer full deletion. Do not leave "removed by
  X" placeholder comments — the commit history is the authoritative record.

### 2.7 Contributing workflow (unchanged, restated for continuity)

- Never commit directly to `master`. Every change lands via a branch + PR
  + CI + merge.
- Every commit is signed off (`Signed-off-by:` trailer).
- Every commit is `ruff format`-clean and `ruff check`-clean.

---

## 3. One-time compliance campaign (15 Issues)

The campaign brings the current tree into full compliance with §2. Every
Issue below is self-contained (any reader can pick it up without prior
context), uses the body template in §4, and is filed under a shared
tracking Issue for status visibility.

### 3.1 Phase 0 — Policy foundation

**Issue 1 — `[META]` Documentation + code-quality campaign tracker**
Long-lived tracking Issue. Body lists all 15 sub-Issues with their current
status, dependencies, and phase. Updated as each sub-Issue closes.

**Issue 2 — Define documentation + code-quality policy**
Extract §2 of this spec into a permanent, versioned document at
`docs/design-guides/documentation-and-code-quality-policy.md`. Add a
pointer section to `AGENTS.md` and a short reference in `CONTRIBUTING.md`.
Once merged, all subsequent Issue #3–#15 acceptance criteria reference
this document.

### 3.2 Phase 1 — Audits (produce reports that inform later cleanup)

**Issue 3 — Static-analysis dead-code sweep (`ruff`)**
Enable / verify F401 (unused import), F841 (unused local variable), and
unreachable-code lints as CI errors. Fix all current violations in-repo.
Publish a short report at `docs/reviews/YYYY-MM-DD-ruff-dead-code-sweep.md`
listing counts per module.

**Issue 4 — Semantic dead-code scan (`vulture`)**
Run `vulture` at confidence ≥ 80%. Publish the raw list, then triage each
finding into (a) delete, (b) keep with by-design annotation, (c) needs
follow-up Issue. File the follow-up Issues. Merge the cleanup PR after
triage.

**Issue 5 — Constants + magic-number audit**
Grep for bare numeric literals in `clinosim/**/*.py` (excluding tests and
generated code). For each finding, decide: name-and-document (per §2.5),
already documented, or is a legitimate one-off (e.g. array index, loop
bound) that needs no rename. Publish results at
`docs/reviews/YYYY-MM-DD-constants-audit.md`.

### 3.3 Phase 2 — Top-level documents (OSS front door)

**Issue 6 — Rewrite root `README.md` (English)**
Full rewrite of the top-level English README for OSS discoverability. Must
include: one-paragraph elevator pitch, screenshot / diagram, install
instructions, minimum quick-start (5 lines), architecture pointer, link
to `CONTRIBUTING.md`, license, citation. Self-contained per §2.3.
Cross-links to English documents only per §2.2.

**Issue 7 — Rewrite root `README.ja.md` (Japanese)**
Japanese mirror of Issue #6. Same structure, same information density,
Japanese-only cross-links per §2.2.

**Issue 8 — De-duplicate and tidy top-level docs**
Reconcile the overlaps between:
- root `MODULES.md` (23 KB) vs `docs/reference/modules.md`
- root `DESIGN.md` (1.8 KB pointer after prior split) vs
  `docs/architecture/*`
- root `CONTRIBUTING.md` vs `docs/governance/contributing.md`
- `AGENTS.md` (67 KB) — extract contributor-facing sections into
  `docs/governance/contributing.md`; keep `AGENTS.md` focused on
  AI-agent-specific instructions.

Result: exactly one canonical location per topic, with pointer files where
redirection helps discovery.

### 3.4 Phase 3 — Source-code comment sweep

**Issue 9 — Normalise source-code comments per §2.4**
Sweep every `clinosim/**/*.py`. Convert non-compliant Japanese comments
to English. Retain Japanese comments in permitted categories (§2.4).
Publish an audit CSV at `docs/reviews/YYYY-MM-DD-comment-language-audit.md`
listing every Japanese comment site and its disposition (retained /
translated / removed). Do the change in one PR per module-group to keep
PRs reviewable.

### 3.5 Phase 4 — Per-module READMEs (English + Japanese)

Each Issue below covers a group of directories. For every directory in
the Issue: audit or create an English `README.md`, then create a Japanese
`README.ja.md` mirror. Each README follows the "Required in every README"
checklist from §2.3 and starts from the boilerplate in
`.github/TEMPLATE_MODULE_README.md`.

**Issue 10 — READMEs for core Python packages**
Target: `clinosim/simulator/`, `clinosim/audit/`, `clinosim/benchmarks/`,
`clinosim/eval/`, `clinosim/types/`, `clinosim/dataset/`, `clinosim/config/`.
Seven directories × (EN + JA) = 14 new files.

**Issue 11 — READMEs for clinical-data modules (audit + JA)**
Target: `clinosim/modules/{patient, disease, encounter, observation,
procedure, diagnosis, allergy, immunization, family_history, physiology,
care_level, code_status}/`. Twelve directories × audit-EN + new-JA =
up to 24 file changes.

**Issue 12 — READMEs for orders / medications / imaging modules**
Target: `clinosim/modules/{order, antibiotic, device, hai, imaging}/`.
Five directories × (audit-EN + new-JA) = up to 10 file changes.

**Issue 13 — READMEs for documents / narrative / clinical-course modules**
Target: `clinosim/modules/{document, clinical_course, health_checkup}/`
and the `clinosim/modules/document/narrative/` subtree.

**Issue 14 — READMEs for ops / identity / i18n / service modules**
Target: `clinosim/modules/{identity, facility, healthcare_system, staff,
nursing, triage, population, sdoh, validator, llm_service}/` and
`clinosim/locale/`. Eleven directories × (audit-EN + new-JA).

**Issue 15 — READMEs for the FHIR-R4 output subtree**
Target: `clinosim/modules/output/` (audit existing EN + new JA) plus
`clinosim/modules/output/fhir_r4/`, `fhir_r4/labs/`, `fhir_r4/lib/`,
`fhir_r4/post_process/`, `fhir_r4/encounters/`, `fhir_r4/conditions/`,
`fhir_r4/procedures/`, `fhir_r4/demographics/`, `fhir_r4/documents/`,
`fhir_r4/medications/`. Ten directories × (EN + JA) = 20 files. Per
§2.4, JLAC10 / JJ1017 / JP-CLINS-specific commentary in these READMEs
may be given as Japanese quote + English gloss.

---

## 4. Issue body template (uniform across all 15)

Every Issue filed by this campaign uses the following body structure so
that any contributor can pick up any Issue without needing further
context.

```markdown
## Context
<Why this Issue exists. Who benefits. How it fits into the wider campaign.
Link to the campaign tracker Issue and the policy document.>

## Current state
<Concrete facts. Path names, file counts, grep-reproducible measurements,
observed inconsistencies. This section must be verifiable by any reader
running the given commands.>

## Goal
<Observable end state. What must be true after this Issue closes.>

## Scope
### In scope
- <bullet list of concrete changes>

### Out of scope
- <bullet list of things that could look related but are handled elsewhere
  or explicitly deferred, with the reason>

## Acceptance criteria
- [ ] <checkbox items, each independently verifiable>
- [ ] All new files pass CI (ruff, mypy, pytest).
- [ ] Documentation cross-links follow §2.2 language-consistency rule.
- [ ] Any Japanese comment added is justified per §2.4.

## References
- Policy: `docs/design-guides/documentation-and-code-quality-policy.md`
  (after Issue #2 closes) or `docs/superpowers/specs/2026-08-09-doc-code-quality-campaign-design.md` §2 in the interim.
- Campaign tracker: #<META Issue number>
- <spec ADR / external references as applicable>

## Notes
<Any dependencies on other Issues in the campaign, non-blocker considerations,
suggested review focus for reviewers.>
```

**Prohibited in Issue bodies** (per §2.3):
- Session identifiers, conversation history, insider pronouns.
- References to gitignored or local files.

---

## 5. Phase ordering and dependencies

```
Issue #2  ── policy doc committed ──┐
                                    ├── Issue #9  (comment sweep uses §2.4)
                                    ├── Issue #10-15 (READMEs cite §2.3-§2.5)
                                    │
Issue #3, #4, #5 (audits) ─────────┤   independent, can run in parallel
                                    │
Issue #6, #7, #8 (top-level docs) ──┤   Issue #6 and #7 are paired
                                    │
Issue #10-15 (module READMEs) ──────┘   parallelizable across groups
Issue #1 (tracker) — kept open until every other Issue closes
```

Recommended order for a single-track worker:
`#2 → #3 → #4 → #5 → #6 → #7 → #8 → #9 → #10 → #11 → #12 → #13 → #14 → #15 → close #1`.

Recommended order for parallel workers: pull #2 first, then work #3/#4/#5
independently, then split #6+#7 from #8, then #9 alone, then #10-#15
in parallel.

---

## 6. Success measure

The campaign succeeds when:

1. Every directory under `clinosim/**/` that contains `.py` files has both
   a `README.md` (English) and a `README.ja.md` (Japanese).
2. `ruff check` and CI report zero F401 / F841 / unreachable-code
   violations project-wide.
3. `vulture --min-confidence 80 clinosim/` reports zero unexplained
   findings (all findings are either deleted or on the by-design whitelist).
4. Every scalar constant flagged by the Issue #5 audit is either documented
   per §2.5 or explicitly ruled out-of-scope with a documented reason.
5. The policy at `docs/design-guides/documentation-and-code-quality-policy.md`
   exists, is referenced from `AGENTS.md` and `CONTRIBUTING.md`, and is
   linked from the top-level README (both languages).
6. Issue #1 (the tracker) can be closed with all fifteen sub-Issues closed.

---

## 7. Non-goals

- **No new feature work is bundled into this campaign.** Only documentation,
  dead-code cleanup, and comment normalisation.
- **No re-architecture.** Module boundaries and public APIs are not changed
  by this campaign.
- **No third-language documentation.** English + Japanese only; other
  languages are outside scope.
- **No mass rename of variables or functions.** Renames only happen where
  a specific dead-code or constants Issue requires them, on a per-symbol
  basis with an explicit rationale.

---

## 8. Maintenance after the campaign

Once Issue #1 (the tracker) is closed:

- The policy at `docs/design-guides/documentation-and-code-quality-policy.md`
  is the durable source of truth. Every future PR is reviewed against it.
- The `.github/TEMPLATE_MODULE_README.md` boilerplate is updated whenever
  §2.3's "Required in every README" checklist changes.
- CI enforces §2.6 (dead-code baseline) automatically.
- §2.4 (comment language) is enforced by reviewer discipline; no automated
  linter is proposed at this time.
- This spec file itself is archived to `docs/history/specs-archive/` after
  Issue #1 closes, since the durable policy has taken its place.
