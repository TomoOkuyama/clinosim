# Documentation + Code-Quality Policy

**Status**: Active
**Applies to**: every contributor (human and automated) submitting changes to
this repository, on every pull request.
**Enforcement**: reviewers check compliance during PR review; some rules
(dead-code baseline in §6, signed-off commits in §7) are also enforced by CI.

This document is the single source of truth for how documentation is
written and how source-code quality is maintained in this project. It is
referenced from [`AGENTS.md`](../../AGENTS.md) (for automated agents),
[`CONTRIBUTING.md`](../../CONTRIBUTING.md) (for human contributors), and the
top-level READMEs.

The policy was ratified as part of the campaign designed in
[`docs/superpowers/specs/2026-08-09-doc-code-quality-campaign-design.md`](../superpowers/specs/2026-08-09-doc-code-quality-campaign-design.md).

---

## Contents

1. [Documentation language](#1-documentation-language)
2. [Cross-document linking (language consistency)](#2-cross-document-linking-language-consistency)
3. [Self-contained OSS quality](#3-self-contained-oss-quality)
4. [Source-code comment language](#4-source-code-comment-language)
5. [Constants and configuration](#5-constants-and-configuration)
6. [Dead-code hygiene](#6-dead-code-hygiene)
7. [Contributing workflow](#7-contributing-workflow)
8. [How to change this policy](#8-how-to-change-this-policy)

---

## 1. Documentation language

Every part of the project's documentation is either English or Japanese, and
the language of a file is identified by its filename suffix.

| File location                                        | Language                              | Required                                                    |
|------------------------------------------------------|---------------------------------------|-------------------------------------------------------------|
| Root `README.md`                                     | English                               | Yes                                                         |
| Root `README.ja.md`                                  | Japanese                              | Yes                                                         |
| Every package/module directory `README.md`           | English                               | Yes                                                         |
| Every package/module directory `README.ja.md`        | Japanese                              | Yes                                                         |
| `docs/**/*.md` (canonical English documents)         | English                               | Yes                                                         |
| `docs/**/*.ja.md` (Japanese mirror documents)        | Japanese                              | When the English document is user-facing or contributor-facing (not a purely internal design note) |

**Filename convention**: the default (unsuffixed) filename is always English.
Japanese counterparts use the `<name>.ja.md` suffix — for example
`README.ja.md`, `installation.ja.md`. No other language-mixing suffix
conventions are introduced.

**Rule**: whenever a new user-facing or contributor-facing documentation
file is added in English, a Japanese counterpart is added in the same
directory using the `.ja.md` suffix. Whenever the English file is updated,
the Japanese file is updated in the same PR (or a follow-up Issue is filed
and linked in the PR description).

---

## 2. Cross-document linking (language consistency)

- Links inside an **English** document point to **English** documents.
- Links inside a **Japanese** document point to **Japanese** documents.
- If the target document only exists in one language, the link may point to
  the other language, but the link text must include a language marker
  (e.g. `[foo (English)](foo.md)` inside a Japanese document). File a
  follow-up Issue to add the missing translation.
- External links (GitHub Issues, upstream specs, RFCs) may be in either
  language and do not need a marker.

---

## 3. Self-contained OSS quality

All READMEs, documentation files, and Issue bodies must be understandable
to a first-time contributor who has no prior context on the repository or
its history.

**Prohibited in any repo-committed document or Issue body**:

- Session or conversation identifiers (`session-NN`, "last session",
  "previous session", etc.).
- Insider pronouns ("you and I", "as we discussed", "私", "あなた").
- References to local, gitignored files (e.g. `.resume-prompt.md`, personal
  notes, scratchpad files).
- Un-explained project-internal jargon without a link to a definition.
- Time-relative language without an absolute date ("yesterday", "recently"
  → use `YYYY-MM-DD`).

**Required in every README**:

- Purpose sentence — what does this module do, in one sentence.
- Scope boundaries — what it does not do; what other modules do instead.
- Public API surface — what does it export; what should callers import.
- Dependencies — which other modules or external systems does it use.
- Constants and configuration — see [§5](#5-constants-and-configuration).
- Testing pointer — how to run the module's tests.
- Ownership / area lead — may be `maintainers@` if no single owner.

Every new module README starts from the boilerplate at
[`.github/TEMPLATE_MODULE_README.md`](../../.github/TEMPLATE_MODULE_README.md).

---

## 4. Source-code comment language

**Default: English.** Every comment (line comment, docstring, TODO/FIXME
marker, block comment) is written in English unless it falls into an
explicitly permitted Japanese-comment category listed below.

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
   通知, JAHIS technical reports, jpfhir.jp implementation guides). Quote
   the source in Japanese and add a one-line English gloss so an
   English-only reader can navigate.

**All other comments must be English**, including:

- Simulator core (`clinosim/simulator/`)
- Audit / eval / benchmark harnesses
- Non-JP module business logic
- Test files
- CLI help strings (use gettext-style locale files for translation)

A comment that only says "Japanese output" or "JP handling" without
quoting the spec text does **not** qualify for the Japanese exception —
write it in English.

---

## 5. Constants and configuration

Every scalar constant, threshold, cutoff, or magic number that affects
patient state, clinical logic, resource output, or a user-visible number
must be:

1. **Named** — never inlined as a bare literal in the middle of an
   expression.
2. **Docstring-annotated** with:
   - purpose — what does it mean,
   - unit — mg/dL, days, count, probability, …,
   - source / rationale — clinical reference, spec section, empirical
     tuning, link to a design ADR or external source.
3. **Located** in one of:
   - a module-local `_constants.py` (private to the module),
   - the module's public `__init__.py` if the constant is part of the API,
   - `clinosim/config/*.yaml` if runtime-configurable,
   - `clinosim/types/config.py` if a typed config model.

Bare `MAGIC_NUMBER = 42` without a docstring is a review-blocker.

---

## 6. Dead-code hygiene

- CI runs `ruff` with F401 (unused import) and F841 (unused local) as
  errors. This is baseline.
- CI also runs `vulture` at 60 % confidence against a project-level
  by-design whitelist ([`.vulture-whitelist.py`](../../.vulture-whitelist.py))
  on every PR (`vulture dead-code` job — merge-blocking). Any new finding
  not covered by an existing whitelist entry fails the job.
- The whitelist is categorised. When adding a new entry, place it under
  the correct category (dataclass / Pydantic fields; Protocol / ABC
  signatures; test-only public API; test-referenced constants;
  attributes set by one module and read by another; delete candidates
  pending removal). See the file header for full category definitions.
- The 60 % threshold was chosen after reconnaissance: at 80 % the tree
  yields only a single finding (ruff F401 already sweeps the
  unused-imports class that dominates the 80–99 % band), so 60 % is the
  useful signal band for this codebase.
- When removing dead code, prefer full deletion. Do not leave "removed by
  X" placeholder comments — the commit history is the authoritative
  record.

---

## 7. Contributing workflow

- Never commit directly to `master`. Every change lands via a branch + PR
  + CI + merge.
- Every commit is signed off (`Signed-off-by:` trailer). The DCO CI job
  blocks merges when any commit is missing the trailer.
- Every commit is `ruff format`-clean and `ruff check`-clean.
- One logical change per PR. Do not bundle unrelated refactors.
- CHANGELOG entry required for user-facing behaviour changes.
- Test plan required in every PR description.

See [`CONTRIBUTING.md`](../../CONTRIBUTING.md) for the full contribution
workflow, including local setup, DCO signoff mechanics, and CI job
descriptions.

---

## 8. How to change this policy

This policy governs a large portion of the codebase and every future PR.
Changes to it are not routine. To propose a change:

1. Open a GitHub Issue describing the change, its motivation, and its
   expected impact on existing code and documentation.
2. Get maintainer agreement on the direction before opening a PR.
3. The PR updates this document, updates any downstream pointers
   (`AGENTS.md`, `CONTRIBUTING.md`, both top-level READMEs), and includes a
   `## Change history` entry below with the date and a one-sentence
   summary.
4. If the change tightens the policy, file follow-up Issues for any
   existing code / documentation that will fall out of compliance, so the
   codebase catches up rather than being left with a mixed standard.

### Change history

- **2026-08-09** — Policy created. Extracted from §2 of the campaign
  design spec at
  [`docs/superpowers/specs/2026-08-09-doc-code-quality-campaign-design.md`](../superpowers/specs/2026-08-09-doc-code-quality-campaign-design.md).
