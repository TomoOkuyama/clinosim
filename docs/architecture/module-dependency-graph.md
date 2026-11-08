<!-- Extracted from `README.md` (Issue #568 PR A2). Update the pointer in README when this file's heading changes. -->

# Module Dependency Graph

Conceptual data-flow view of the main modules. It is not the literal import graph:
modules rarely import each other directly; `clinosim/simulator/` calls them in turn.

```mermaid
flowchart TD
    codes["codes<br/>(international code systems)"]
    locale["locale<br/>(country)"]
    output["output<br/>(FHIR / CIF / CSV)"]
    patient["patient activator"]
    encounter["encounter"]
    disease["disease (YAML)"]
    facility["facility (queue)"]
    population["population"]
    staff["staff"]
    healthcare["healthcare_system"]
    identity["identity<br/>(insurance numbering)"]

    subgraph loop["daily simulation loop"]
        cc["clinical_course"] --> phys["physiology"]
        phys --> obs["observation"]
        phys --> dx["diagnosis"]
        dx --> cc
        obs --> proc["procedure + MAR"]
        dx --> order["order"]
        order --> proc
    end

    codes -->|lookup| output
    locale --> output
    locale --> patient
    patient --> encounter
    encounter --> loop
    disease --> loop
    facility --> loop
    loop --> output
    population --> disease
    population --> facility
    population --> staff
    healthcare --> staff
    population --> identity
    identity --> output
```

`llm_service` and `validator` are cross-cutting (used in dedicated phases).
`identity` is an enricher (AD-54) that is on by default (JP can opt out with
`--no-jp-insurance`; US always runs it): it runs as a post-population pass via the
enricher registry (AD-56) and its data is emitted as FHIR `Coverage` by `output`.

See each module's `clinosim/modules/<module>/README.md` for details.

---
