# clinosim Design Guidelines — Landing Pointer

This file was 2819 lines / 154 KB — a documentation cliff for first-time
visitors. Issue #568 PR B split it into three thematically-grouped
files under `docs/architecture/`:

## The three parts

- **[Design principles](docs/architecture/design-principles.md)** —
  realism-above-all, modular architecture, LLM integration, simulation
  modes, folder structure, inter-module interface conventions, naming
  conventions. Historical foundation; largely stable.
- **[Architecture notes](docs/architecture/architecture-notes.md)** —
  per-module architectural notes (code system, FHIR bulk data,
  snapshot semantics, hospital config layout, vital sign patterns,
  identifiers, EHR enrichment, extensibility foundation), clinical
  document module (FHIR DocumentReference), LLM service architecture
  (pluggable providers + YAML prompts).
- **[ADR history](docs/architecture/adr-history.md)** — the clean
  per-ADR sections (`### AD-NN:`): Japanese localization (AD-42, AD-43),
  FHIR standards compliance + occupational injuries
  (AD-44 through AD-48, AD-61 through AD-70).

## Related documentation

- **[docs/README.md](docs/README.md)** — top-level docs landing page
- **[docs/architecture/README.md](docs/architecture/README.md)** —
  architecture-specific navigation
- **[MODULES.md](MODULES.md)** — module-level API index

## Historical context

The pre-split monolithic `DESIGN.md` is preserved in the git history
(pre-Issue #568 PR B). Individual ADR references in code and other
docs point at the new split files directly — no in-tree references
should still target the old top-level `DESIGN.md`.

For the reasoning behind splitting into 3 files (rather than the
originally-proposed 55+ per-ADR files), see the Issue #568 PR B
description.
