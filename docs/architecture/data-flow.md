<!-- Extracted from `README.md` (Issue #568 PR A2). Update the pointer in README when this file's heading changes. -->

# Data Flow

clinosim implements a three-stage pipeline. Each stage is self-contained, has a well-defined input and output on disk, and can be run independently of the others.

```mermaid
flowchart TD
    subgraph stage1["Stage 1 — clinosim simulate"]
        pop["population engine<br/>Catchment (household-based)<br/>PersonRecord (Layer 1)<br/>Monthly LifeEvent"]
        act["patient activator<br/>Layer 1 → Layer 2"]
        enc["encounter creation<br/>disease YAML → department<br/>staff / ward / bed / OR"]
        loop["daily simulation loop<br/>clinical_course → physiology<br/>→ orders → diagnosis<br/>→ procedure + MAR<br/>→ discharge readiness?"]
        cif_s["CIF structural/<br/>immutable, one JSON per encounter"]
        pop --> act --> enc --> loop --> cif_s
    end

    subgraph stage2["Stage 2 — clinosim narrate"]
        gen2["document_enricher (document module)<br/>Stage 1 built-in: DR + Composition + ClinicalImpression<br/>template-based, fully deterministic"]
        llm2["clinosim narrate (cli_narrate.py)<br/>optional LLM narrative pass over structural CIF<br/>emits cif/narratives/&lt;version&gt;/"]
    end

    subgraph stage3["Stage 3 — clinosim export-fhir"]
        adapter["fhir_r4_adapter (+ per-theme _fhir_* builders)<br/>structural → 16 FHIR resource types<br/>narratives → DocumentReference (base64)<br/>display text via clinosim.codes"]
        fhir["output/fhir_r4/<br/>HL7 Bulk Data NDJSON + manifest.json"]
        adapter --> fhir
    end

    cif_s --> adapter
```

**Why three stages?**

- **Reproducibility** — Stage 1 is fully deterministic from a seed (includes built-in document enricher). Stage 3 is a pure function of CIF.
- **Extensibility** — Stage 2 (`clinosim narrate`) is optional and wires in LLM narrative providers (local Ollama, AWS Bedrock, Sakura Cloud Ollama) over the same structural CIF. Skipping it still produces valid FHIR (template-mode `docStatus="preliminary"`).
- **Cost control** — Stage 2 is the only stage that may call a paid LLM API. Bedrock / Sakura runs can be isolated to a single remote invocation.
- **Remote execution** — Stage 2 can be run on a machine with network access to the LLM (e.g. EC2 for Bedrock, Sakura Cloud for Ollama), while Stage 1 and Stage 3 stay local.

### Snapshot Semantics

- Simulation period: `--start` ~ `--end`
- `--end` = **snapshot date**
- No life events generated past the snapshot date (no future admissions)
- Inpatients whose `discharge_datetime` would fall after the snapshot date:
  - `discharge_datetime = None`
  - `Encounter.status = "in-progress"`
  - Partial data only (labs/vitals/orders/MAR up to snapshot day)
  - Primary `Condition.clinicalStatus = "active"` (not resolved)
- This produces a realistic EHR snapshot **including currently admitted patients** (e.g., 50-bed × 60% occupancy ≈ 30 in-progress encounters)

---

## End-to-end pipeline diagram

![clinosim end-to-end pipeline: population generation → physiology + encounter simulation → enricher stages → CIF → format adapters → NDJSON output](../assets/pipeline.svg)

For a step-by-step walkthrough see [`../design-guides/data-generation-walkthrough.md`](../design-guides/data-generation-walkthrough.md).
