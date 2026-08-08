# `docs/architecture/`

Architecture references for clinosim. Concerns that affect module boundaries
or cross-cutting invariants live here; per-module deep dives live inside each
module's own `README.md`.

## Contents

- [`module-architecture.md`](module-architecture.md) — high-level module
  layering, dependency direction, and how the simulator / output subsystems
  cross-reference each other. Extracted from the root `README.md` (Issue #568
  PR A).
- [`data-flow.md`](data-flow.md) — end-to-end data flow across population,
  simulation, and FHIR export. Extracted from `README.md` (Issue #568 PR A2).
- [`module-dependency-graph.md`](module-dependency-graph.md) — top-level
  package import graph. Extracted from `README.md` (Issue #568 PR A2).

## Related

- Design guides: [`../design-guides/`](../design-guides/README.md).
- Historical ADRs (2025-era): `DESIGN.md` at the repo root — pending split
  into per-ADR files under `adr/` (Issue #568 PR B).
- Per-module architecture: `clinosim/modules/<X>/README.md`.
