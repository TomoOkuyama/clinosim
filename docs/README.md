# docs/

Landing page for the `clinosim` documentation folder (Issue #568).

The full documentation site is published at
<https://tomookuyama.github.io/clinosim/>. This README is the
GitHub-folder-view companion — a map of what's in each subdirectory
and what to open first.

## For users

Start here if you're evaluating or using clinosim:

- **[getting-started/](getting-started/)** — installation, first cohort
  generation, and the 30-second smoke test.
- **[index.md](index.md)** — top-level project overview (mirrors the
  landing page of the docs site).
- **[eval.md](eval.md)** — the `clinosim eval` framework: what it scores
  and how to interpret the report.
- **[eval-rules.md](eval-rules.md)** — the per-axis rules the eval
  engine enforces.
- **[jp-clins.md](jp-clins.md)** — Japan Clinical Information Sharing
  (JP-CLINS) profile support and how JP cohorts differ from US.
- **[roadmap.md](roadmap.md)** — pointer to the GitHub Issues that
  track upcoming work (canonical live view; this file is stub).
- **[clinical_documents.md](clinical_documents.md)** — what document
  types clinosim generates and where they live in the CIF.
- **[fhir-server-ingestion.md](fhir-server-ingestion.md)** — importing
  clinosim output into HAPI / IRIS / other FHIR servers.
- **[synthea-comparison.md](synthea-comparison.md)** — how clinosim
  differs from [Synthea](https://synthetichealth.github.io/synthea/)
  and when to reach for which.
- **[benchmarks.md](benchmarks.md)** — cohort size / seed / runtime
  benchmarks.
- **[add-your-country.md](add-your-country.md)** — proposal template for
  adding a new country (US-Core / USCDI etc.).

## For contributors

- **[../AGENTS.md](../AGENTS.md)** — canonical agent + contributor
  instructions. **Read this first before opening a PR.**
- **[../CONTRIBUTING.md](../CONTRIBUTING.md)** — human-facing PR
  workflow, DCO sign-off, CI matrix.
- **[CONTRIBUTING-modules.md](CONTRIBUTING-modules.md)** — the
  module-boundary rules (AD-55/AD-56) that new modules must follow.
- **[design-guides/](design-guides/)** — long-form design guides,
  including the project-concept and implementation-rules docs that
  `AGENTS.md` links to for depth.
- **[design-notes/](design-notes/)** — smaller design memos filed
  against specific decisions.
- **[reference/](reference/)** — small stable references
  (constants, tables, external system URLs).
- **[development/](development/)** — release / publish / development
  runbooks (e.g. `publishing-to-pypi.md`).
- **[governance/](governance/)** — project governance model.

## Working notes

These folders hold in-flight and historical artefacts. Contributors
looking at recent work land here; readers looking for stable references
should NOT start here.

- **[audit-cycles/](audit-cycles/)** — the per-cycle audit reports
  (session-N artefacts) plus the by-design registry.
- **[reviews/](reviews/)** — data-quality-review outputs on specific
  changes; historical.
- **[superpowers/](superpowers/)** — in-flight and archived plan +
  spec files for larger changes (agents-driven planning artefact).

## Archives

- **[history/](history/)** — retired artefacts: old scratchpad code,
  early proof-of-concept files, replaced designs. Kept for the reflog;
  contributors don't need to read this.

## Not in this folder

- **Root READMEs** — `../README.md`, `../CHANGELOG.md`, `../DESIGN.md`
  (large, mixed audience — being split, see Issue #568)
- **Per-module docs** — every module under `../clinosim/modules/`
  has its own `README.md` describing its inputs/outputs and any
  invariants specific to that module.
- **Test conventions** — `../tests/README.md` (added by Issue #566).

## Contributing to these docs

Follow the file-suffix rule in `AGENTS.md § Documentation naming rule`:
English default (no suffix), Japanese variant `*.ja.md`. Add new user-
facing docs under `reference/`, new design notes under `design-notes/`,
new architecture guides under `design-guides/`.
