# Contributing to clinosim

Thanks for wanting to contribute!

**clinosim is an independent personal project** ([README](README.md)), so
this document keeps the process light while still protecting the two hard
properties the project relies on:

- **Determinism** — for a given `(seed, config, country, start, end,
  population)` tuple, output is byte-identical within a MINOR release line.
  Never introduce `random.random()` or globally-shared RNG state; every
  random draw must derive from a sub-seed of a passed-in
  `numpy.random.Generator`.
- **Synthetic data only** — never reference, embed, or reproduce real
  patient data / PHI / PII. All output must be fully synthetic. See the
  disclaimers in the [README](README.md#clinosim).

If you're going to work on the code, please also read:

- [`docs/CONTRIBUTING-modules.md`](docs/CONTRIBUTING-modules.md) — the
  practical playbook for adding a new module / plugin / FHIR builder
  (Base vs Module classification, enricher stages, registry usage, PR
  verification via `clinosim audit run`).
- [`DESIGN.md`](DESIGN.md) — landing pointer to the architecture docs
  under `docs/architecture/`; the architecture decision records
  (AD-1 through AD-71) are in
  [`docs/architecture/adr-history.md`](docs/architecture/adr-history.md)
  plus the summary tables in `design-principles.md` and
  `architecture-notes.md`.
- [`AGENTS.md`](AGENTS.md) — repo-wide conventions and invariants
  (canonical AI-agent instructions per the [AGENTS.md convention](https://agentmd.dev);
  `CLAUDE.md` is a thin pointer to this file).
- [`.github/TEMPLATE_MODULE_README.md`](.github/TEMPLATE_MODULE_README.md)
  — boilerplate for a new module directory.
- [`docs/design-guides/documentation-and-code-quality-policy.md`](docs/design-guides/documentation-and-code-quality-policy.md)
  — documentation-language pairing (English + Japanese), source-code comment
  language rule, self-contained-OSS-quality standard, constants documentation
  rule, and dead-code hygiene expectations. All PRs are reviewed against this
  policy.

---

## Getting set up

```bash
git clone https://github.com/TomoOkuyama/clinosim.git
cd clinosim
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Sanity check:

```bash
clinosim --help
pytest tests/unit -q               # ~1 minute, must be green
```

---

## Workflow

1. **Open an issue first** for non-trivial changes so scope and approach
   can be agreed before you spend time. Bug reports and feature requests
   have dedicated templates.
2. **Fork + branch** from `master`. Use a descriptive branch name
   (`fix/…` / `feat/…` / `docs/…`).
3. **Small, focused commits.** One logical change per PR is much easier
   to review than a mega-diff.
4. **Sign your commits (DCO — required).** See [DCO](#dco--signed-off-by-required) below.
5. **Run the tests locally** before opening the PR:

   ```bash
   pytest tests/unit -q                       # required, ~1 min
   pytest tests/integration -q                # recommended when touching
                                              # simulator / output / FHIR
                                              # code paths (~18 min local,
                                              # ~30 min in CI)
   ```

   Lint, format and type checks (the same commands CI runs; they block
   merge):

   ```bash
   make lint                                  # ruff check + ruff format --check
   make typecheck                             # mypy clinosim/
   ```

6. **Update `CHANGELOG.md`** — add a bullet under `[Unreleased]`
   describing user-facing behaviour changes. Skip only for docs-only PRs.
7. **Open the PR** — the PR template walks you through the checklist.
8. **CI must be green** on all required jobs before a maintainer merges:
   - `Unit tests (Py 3.12 shard 1/3, 2/3, 3/3)`
   - `Integration tests (shard 1/10 … 10/10)`
   - `Narrative regression (goldens)`
   - `Build sdist + wheel`
   - `Signed-off-by check`
   - `mkdocs build`
   - `JP-CLINS lab compliance gate` / `JP Core narrow compliance gate` /
     `US Core narrow compliance gate` (run only on PRs that touch paths
     affecting FHIR output)
   - `E2E tests (fast)`
   - `Quality (ruff + format + mypy)` — ruff check + ruff format --check + mypy
   - `vulture dead-code`

   Informational (not merge-blocking):
   - `Unit test coverage combine (informational)`

   Python 3.11 unit-test compatibility runs nightly (see
   [`.github/workflows/nightly.yml`](.github/workflows/nightly.yml)).
   Full workflow definitions in [`.github/workflows/`](.github/workflows/).

---

## DCO — Signed-off-by (required)

We use the [Developer Certificate of Origin](https://developercertificate.org/)
(DCO) instead of a CLA. Every commit on every PR must carry a
`Signed-off-by:` trailer that matches the author. That's a statement
that you have the right to contribute the change under the project's
license.

**How to sign a commit:**

```bash
git commit -s -m "your message"
# or, to sign every commit in a branch automatically:
git config format.signOff true
```

The trailer looks like:

```
Signed-off-by: Jane Doe <jane@example.com>
```

**Retro-signing a branch** (before a maintainer will merge):

```bash
git rebase --signoff origin/master
# or for a single commit:
git commit --amend --signoff --no-edit
git push --force-with-lease
```

The `DCO` GitHub Actions job blocks merges when any PR commit is missing
the trailer.

---

## What makes a good PR

- **A concrete bug report or feature request tied to it** (link the
  issue). "Refactor X for readability" without a motivating problem
  usually isn't a good PR.
- **No unrelated churn.** Don't reformat 400 files while fixing one
  bug — pre-existing lint / format debt is being worked down in
  separate issues (see [`good first issue`](https://github.com/TomoOkuyama/clinosim/labels/good%20first%20issue)).
- **Tests that would have caught the bug** (for fixes) or that exercise
  the new behaviour (for features). Any change that touches simulation
  paths needs a determinism check — the simplest is a byte-diff between
  two runs at the same seed.
- **CHANGELOG entry** describing what changed for a user of the
  library, not just what changed in the diff.
- **Documentation update** when the change adds a new module, YAML
  field, CLI subcommand, or public API surface.

---

## Coding rules

Every change follows these rules. Each one is defined in a binding spec; the link is the place to read the details.

1. **Code and data are separated.** Values that differ by country, age or sex, and tunable clinical or statistical values, live in YAML with a cited source. Code looks them up and never selects them in a country / age / sex branch; a country-specific algorithm is a named implementation chosen in YAML. See [implementation rules: grand design](docs/design-guides/implementation-rules.md#grand-design-code-and-data-are-separated) and the [configuration and reference data spec](docs/design-guides/configuration-and-reference-data-spec.md).
2. **Multilingual output.** Every user-visible string comes from a catalog or localized table, resolved at the emit site. English is required and is the fallback for a missing language; a key, raw code or slug never reaches output. JP output reads as Japanese EHR text (Latin script only where Japanese records use it), and an English-only code system keeps its English `coding.display` with the localized label in `.text`. See [code-mapping spec §5](docs/design-guides/code-mapping-and-localization-spec.md#5-localization) and [§6](docs/design-guides/code-mapping-and-localization-spec.md#6-fallback-rules).
3. **Codes.** Only codes verified against their authoritative source are used. They are registered in the code tables and resolved through `clinosim.codes` / `clinosim.locale.loader`, never written as literals in code. See [code-mapping spec §8](docs/design-guides/code-mapping-and-localization-spec.md#8-adding-or-changing-a-code) and [§9](docs/design-guides/code-mapping-and-localization-spec.md#9-prohibited-patterns).
4. **Country handling.** `is_jp` / `lang_for` are the only way to read the country or output language. A country branch only decides whether a structure a country profile mandates is emitted; it never selects a value. See [code-mapping spec §5](docs/design-guides/code-mapping-and-localization-spec.md#5-localization) and the [module guide](docs/CONTRIBUTING-modules.md#shared-helpers-go-into-clinosimmodules_sharedpy).
5. **Determinism.** A change never adds draws to a shared RNG stream; new randomness comes from a seed derived for the entity it concerns, or from a hash draw. See the [determinism and RNG spec](docs/design-guides/determinism-and-rng-spec.md#2-drawing-random-numbers).

---

## Documentation and comment-language policy

Every PR is reviewed against
[`docs/design-guides/documentation-and-code-quality-policy.md`](docs/design-guides/documentation-and-code-quality-policy.md).
The short version:

- Documentation files come in language pairs: English `README.md` plus
  Japanese `README.ja.md` (and the same pattern under `docs/`).
- Links inside an English document point to English documents; links inside
  a Japanese document point to Japanese documents.
- READMEs and Issue bodies are self-contained. No session identifiers,
  insider pronouns, or references to gitignored files.
- Source-code comments are English by default. Japanese is permitted only
  for JP-Core / JP-CLINS profile invariants, JLAC10 / JJ1017 / MEDIS
  code-system specifics, and verbatim quotes from Japanese authoritative
  sources.
- Every scalar constant / threshold / magic number is named, docstring-
  annotated (purpose / unit / source), and located in the right place per
  the policy.
- CI enforces the dead-code baseline (`ruff` F401 / F841) and DCO signoff.

Read the full policy before opening a PR that adds or changes documentation.

---

## Reporting bugs and requesting features

Use the [issue templates](https://github.com/TomoOkuyama/clinosim/issues/new/choose).
For security issues, see [`SECURITY.md`](SECURITY.md) — please do **not**
open a public issue.

---

## Code of Conduct

Participation is subject to the [Code of Conduct](CODE_OF_CONDUCT.md).

---

## Licensing

All contributions are licensed under the terms of the [MIT License](LICENSE).
By signing off your commits (DCO) you assert you have the right to submit
the code under that license.
