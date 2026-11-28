# `docs/architecture/`

Architecture references for clinosim. Concerns that affect module boundaries
or cross-cutting invariants live here; per-module deep dives live inside each
module's own `README.md`.

## Contents

**Split from the historical root `DESIGN.md`** (Issue #568 PR B, 2026-08-09):

- [`design-principles.md`](design-principles.md) — realism-above-all,
  modular architecture, LLM integration, simulation modes, folder
  structure, inter-module interface conventions, naming. Historical
  foundation; largely stable.
- [`architecture-notes.md`](architecture-notes.md) — per-module
  architectural notes: code system, FHIR bulk data (AD-31), snapshot
  semantics (AD-32), hospital config layout (AD-34), vital sign
  patterns, NEWS2, resident identifiers (AD-54), EHR enrichment split
  (AD-55), extensibility (AD-56). Clinical documents via FHIR
  DocumentReference. LLM service architecture.
- [`adr-history.md`](adr-history.md) — clean `### AD-NN:` sections:
  Japanese localization (AD-42, AD-43), FHIR standards compliance +
  occupational injuries (AD-44 through AD-48, AD-61 through AD-73).

**Architecture decision records.** A pull request adds an ADR when it adds or changes an extension point, changes the CIF schema or what CIF stores, or deviates from a binding spec or an earlier ADR. The maintainer approves every record. New records are appended to [`adr-history.md`](adr-history.md) and [`adr-history.ja.md`](adr-history.ja.md) with the next AD number and get a row in the ADR table of [`architecture-notes.md`](architecture-notes.md) (and its `.ja.md`). The template and the details are in [`adr-history.md` — Recording a decision](adr-history.md#recording-a-decision).

**Extracted from the root `README.md`** (Issue #568 PR A):

- [`module-architecture.md`](module-architecture.md) — high-level module
  layering, dependency direction, and how the simulator / output subsystems
  cross-reference each other.
- [`data-flow.md`](data-flow.md) — end-to-end data flow across population,
  simulation, and FHIR export.
- [`module-dependency-graph.md`](module-dependency-graph.md) — conceptual
  data-flow diagram between the main modules (not the literal import graph:
  the modules are wired together by `clinosim/simulator/`).

## Related

- Design guides: [`../design-guides/`](../design-guides/README.md).
- Root pointer: [`../../DESIGN.md`](../../DESIGN.md) is now a landing
  page pointing at the three files above.
- Per-module architecture: `clinosim/modules/<X>/README.md`.
