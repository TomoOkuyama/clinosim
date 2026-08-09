# clinosim

> **Clinically Realistic Hospital Data Simulator** — generate FHIR R4 EHR data from a virtual hospital.

[![CI](https://github.com/TomoOkuyama/clinosim/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/TomoOkuyama/clinosim/actions/workflows/ci.yml)
[![Docs](https://github.com/TomoOkuyama/clinosim/actions/workflows/docs.yml/badge.svg?branch=master)](https://tomookuyama.github.io/clinosim/)
[![PyPI](https://img.shields.io/pypi/v/clinosim.svg?label=PyPI&color=blue)](https://pypi.org/project/clinosim/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![FHIR](https://img.shields.io/badge/output-HL7%20FHIR%20R4%20Bulk-orange)](https://hl7.org/fhir/uv/bulkdata/)

📚 **Documentation site**: [tomookuyama.github.io/clinosim](https://tomookuyama.github.io/clinosim/)

🇯🇵 **日本語版**: [README.ja.md](README.ja.md)

> ⚠️ **Personal project disclaimer**: this is an independent personal project and is **not** an official product of any company or organisation. All design decisions and code are the responsibility of the individual contributors listed in `pyproject.toml`.
>
> ⚠️ **Synthetic data only**: all output is **fully synthetic**. clinosim does not ingest, reference, or reproduce any real patient data or PHI / PII. Output is **not intended for clinical use** and must not be relied upon for any diagnostic, therapeutic, or care decision.

## What clinosim does

clinosim generates synthetic EHR data through **forward simulation from a population**. Every patient carries a hidden **13-variable physiological state**, and every observation (labs, vitals, medications, diagnoses) is derived from that state — so the data is **clinically coherent by construction**.

Primary use cases:

- Training data for medical AI / ML models
- EHR system testing and QA
- Clinical-research method development
- Educational case datasets

---

## Why clinosim?

Most synthetic-EHR tools produce records by sampling from disease
distributions. **clinosim runs the disease.** A CKD patient's ED
creatinine is elevated even when they present for something unrelated.
A warfarin-anticoagulated patient sits in the therapeutic PT-INR band.
A sepsis patient shows the WBC / CRP / lactate cascade.

Three concrete differentiators:

- **Clinical coherence by construction.** Not a post-hoc filter — the
  physiology model makes incoherent labs impossible.
- **JP + US natively.** JP Core profile compliance for 16 primary FHIR
  resource types, JLAC10 / MHLW YJ codes, JP names / addresses /
  insurance out of the box. Not an English-only tool with translations
  bolted on.
- **YAML-driven extension.** 32 inpatient diseases + 46 ED / outpatient
  conditions are all data files, not code. Adding a disease is editing
  YAML.

### How clinosim compares to Synthea

[Synthea](https://synthetichealth.github.io/synthea/) (the widely-used
state-transition simulator by MITRE) and clinosim tackle synthetic EHR
from different angles. Both are open source and both emit FHIR — the
differences are in modeling approach and locale coverage.

| Dimension | clinosim | Synthea |
|---|---|---|
| Modeling approach | Physiology-driven forward simulation (13-var hidden state per patient) | State-transition modules per condition |
| Coherence between labs / vitals | Guaranteed by shared physiological state | Independent per module |
| Native FHIR R4 output | Bulk Data Access NDJSON, one file per ResourceType | FHIR R4 JSON per patient |
| JP Core profile compliance | 16 resource types | Not a design goal |
| Multi-locale (US + JP) | Both first-class; JP names, addresses, insurance, JLAC10, MHLW YJ | US-first; internationalization via community modules |
| Determinism guarantee | Byte-identical output within a MINOR release for the same seed | Deterministic per-run seed |
| Extension model | YAML-driven (edit a file, no code) | Java module (`.json` state machines + code) |
| Runtime | Python 3.11+ | Java 11+ |
| License | MIT | Apache 2.0 |

**When to use which:**

- **clinosim** — you need clinically coherent labs / vitals, JP output,
  or want to iterate on disease definitions without touching Java code.
- **Synthea** — you need a broad US population with well-established
  disease modules and a mature downstream tooling ecosystem.

### Sample output — one physiology-driven lab

For a JP patient on chronic warfarin for atrial fibrillation, clinosim
emits a PT-INR Observation like:

```json
{
  "resourceType": "Observation",
  "id": "lab-enc-jp-042-15-pt-inr",
  "meta": { "profile": [
    "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_LabResult"
  ]},
  "status": "final",
  "code": {"coding": [
    { "system": "urn:oid:1.2.392.200119.4.504", "code": "2B160000002327101",
      "display": "PT-INR" },
    { "system": "http://loinc.org", "code": "6301-6",
      "display": "INR in Platelet poor plasma by Coagulation assay" }
  ]},
  "subject": {"reference": "Patient/jp-042"},
  "effectiveDateTime": "2026-04-15T08:00:00+09:00",
  "valueQuantity": {"value": 2.7, "unit": "{INR}",
    "system": "http://unitsofmeasure.org", "code": "{INR}"},
  "referenceRange": [{
    "low": {"value": 2.0}, "high": {"value": 3.0},
    "text": "Warfarin therapeutic (AF stroke prevention)"
  }],
  "interpretation": [{"coding": [{
    "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
    "code": "N",
    "display": "Normal"
  }]}]
}
```

Notice: the INR value 2.7 wasn't sampled from a "PT-INR normal range".
The physiology engine detected warfarin from the chronic-medication
list, placed this patient in the 2.0 – 3.0 therapeutic band, and picked
the reference range and interpretation to match. Change the seed → a
different but still-therapeutic value. Remove the warfarin → a normal
(~1.0) INR next run. That is what "clinical coherence by construction"
means in practice.

### Pipeline diagram

![clinosim end-to-end pipeline: population generation → physiology + encounter simulation → enricher stages → CIF → format adapters → NDJSON output](docs/assets/pipeline.svg)

For a step-by-step walkthrough see [`docs/design-guides/data-generation-walkthrough.md`](docs/design-guides/data-generation-walkthrough.md).

---

## Install

**Requires Python 3.11 or newer.**

```bash
pip install clinosim
```

Development install (from a clone):

```bash
git clone https://github.com/TomoOkuyama/clinosim.git
cd clinosim
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Quick start

Generate a small US cohort and inspect its FHIR output:

```bash
clinosim simulate --country US --population 100 --seed 42 \
  --output ./out --format fhir-r4
ls ./out/fhir_r4/          # Patient.ndjson, Encounter.ndjson, ...
```

Generate a Japanese cohort with JP Core profiles:

```bash
clinosim simulate --country JP --population 100 --seed 42 \
  --output ./out-jp --format fhir-r4
```

Named-preset datasets (reproducible releases):

```bash
clinosim dataset list                           # show available presets
clinosim dataset build jp-100 --output ./jp-100-out
```

## Configuration

Runtime configuration is loaded from `clinosim/config/*.yaml`. The
tables below list the most-used CLI flags and environment variables.
See [`docs/reference/cli.md`](docs/reference/cli.md) for the full
reference.

### Key CLI flags (`clinosim simulate`)

| Flag | Default | Meaning |
|---|---|---|
| `--country {US,JP}` | `US` | Locale — controls names / addresses / insurance / code systems |
| `--population N` | catchment default from hospital config | Population size (persons) |
| `--seed N` | `42` | Deterministic seed (AD-16 invariant) |
| `--start YYYY-MM-DD` / `--end YYYY-MM-DD` | past 1 year ending today | Simulation window |
| `--output PATH` | `./output` | Output directory |
| `--format {cif,fhir-r4,csv}` | `cif` | One or more output formats |
| `--hospital-config PATH` | `hospital_operations.yaml` | Hospital-shape override YAML |

### Key environment variables

| Variable | Default | Meaning |
|---|---|---|
| `CLINOSIM_JP_CLINS_PKG_DIR` | unset | Path to the JP-CLINS package directory (required for JP-CLINS lab-compliance gate; see [`docs/jp-clins.md`](docs/jp-clins.md)) |
| `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | AWS default chain | Only needed for AWS Bedrock narrative provider (`--provider bedrock`) |

## Architecture at a glance

- **[`clinosim/simulator/`](clinosim/simulator/README.md)** — main
  simulation engine + CLI.
- **[`clinosim/modules/`](clinosim/modules/)** — 32 clinical /
  operational modules, each with its own `README.md` /
  `README.ja.md`.
- **[`clinosim/modules/output/fhir_r4/`](clinosim/modules/output/fhir_r4/README.md)**
  — FHIR R4 emit subsystem (10 subpackages grouped by clinical
  domain).
- **[`clinosim/types/`](clinosim/types/README.md)** — shared data
  types (dataclasses).
- **[`clinosim/audit/`](clinosim/audit/README.md)** — internal
  per-module PR verification gate.
- **[`clinosim/eval/`](clinosim/eval/README.md)** — public cohort
  evaluation framework.
- **[`clinosim/locale/`](clinosim/locale/README.md)** — country-
  specific data bundles (US / JP).

Deeper architecture reading:

- **[`docs/architecture/`](docs/architecture/README.md)** —
  design principles, module architecture, dependency graph, data
  flow, ADR history.
- **[`docs/reference/modules.md`](docs/reference/modules.md)** —
  single-page module reference.

## Data quality

clinosim's true goal is **FHIR R4 + JP Core compliant output with
clinical coherence and JP-locale quality**. PRs that change output
data are gated by a 3-axis Data Quality Review (structural / clinical
/ JP-language) driven by the [audit framework](clinosim/audit/README.md).

Formal evaluation (public gate) is available via `clinosim eval` —
see [`clinosim/eval/`](clinosim/eval/README.md) and
[`docs/eval.md`](docs/eval.md).

## Contributing

- **[`CONTRIBUTING.md`](CONTRIBUTING.md)** — how to file issues,
  propose changes, and open a PR (including the DCO signoff
  requirement).
- **[`docs/design-guides/documentation-and-code-quality-policy.md`](docs/design-guides/documentation-and-code-quality-policy.md)**
  — documentation-language pairing (English + Japanese), source-code
  comment-language rule, self-contained-OSS-quality standard,
  constants documentation rule, and dead-code hygiene expectations.
  **Every PR is reviewed against this policy.**
- **[`docs/CONTRIBUTING-modules.md`](docs/CONTRIBUTING-modules.md)** —
  practical playbook for adding a new module / FHIR builder.
- **[`AGENTS.md`](AGENTS.md)** — canonical instructions for AI coding
  agents working on clinosim.

CI requirements: `Unit tests (Py 3.12)`, `Integration tests (shard
1/3, 2/3, 3/3)`, `Signed-off-by check`, `mkdocs build`, `Build sdist
+ wheel`, `ruff dead-code (F401 / F841)`, `vulture dead-code`. Full
list in [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Governance and community

| Document | Purpose |
|---|---|
| [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) | Contributor Covenant 2.1 |
| [`SECURITY.md`](SECURITY.md) | How to report vulnerabilities privately via GitHub Security Advisories |
| [`CITATION.cff`](CITATION.cff) | Machine-readable citation metadata (`Cite this repository` button on GitHub) |
| [`CHANGELOG.md`](CHANGELOG.md) | Keep a Changelog format, [SemVer](https://semver.org/) contract |
| [Issue templates](.github/ISSUE_TEMPLATE/) | Structured bug-report / feature-request forms |
| [`good first issue` label](https://github.com/TomoOkuyama/clinosim/labels/good%20first%20issue) | Starter-friendly open tasks |

## License

MIT — see [`LICENSE`](LICENSE).

Each code system's data follows its original registry licence:

- ICD-10-CM, RxNorm: public domain
- LOINC: LOINC Licence (free for commercial use)
- WHO ICD-10: WHO terms of use
- CPT: AMA Copyright (educational / research subset)
- JLAC10, YJ, K-codes: 厚生労働省 / JCCLS public data

## Citation

```bibtex
@software{clinosim,
  title  = {clinosim: Clinically Realistic Hospital Data Simulator},
  year   = {2026},
  url    = {https://github.com/TomoOkuyama/clinosim}
}
```
