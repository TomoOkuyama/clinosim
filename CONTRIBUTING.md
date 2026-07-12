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
- [`DESIGN.md`](DESIGN.md) — 55+ architecture decision records.
- [`CLAUDE.md`](CLAUDE.md) — repo-wide conventions and invariants.
- [`.github/TEMPLATE_MODULE_README.md`](.github/TEMPLATE_MODULE_README.md)
  — boilerplate for a new module directory.

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

   Optional local checks (the same commands CI runs — CI marks these
   informational for now while the pre-existing lint/type debt is being
   worked down):

   ```bash
   make lint                                  # ruff check + ruff format --check
   make typecheck                             # mypy clinosim/
   ```

6. **Update `CHANGELOG.md`** — add a bullet under `[Unreleased]`
   describing user-facing behaviour changes. Skip only for docs-only PRs.
7. **Open the PR** — the PR template walks you through the checklist.
8. **CI must be green** on all required jobs before a maintainer merges:
   `Unit tests (3.11, 3.12)`, `Integration tests (3.12)`,
   `Build sdist + wheel`, and `DCO`. `Lint` / `Type check` are
   informational for now (see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

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
