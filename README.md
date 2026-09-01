# clinosim

> **Clinically Realistic Hospital Data Simulator** — generate FHIR R4 EHR data from a virtual hospital.

[![CI](https://github.com/TomoOkuyama/clinosim/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/TomoOkuyama/clinosim/actions/workflows/ci.yml)
[![Docs](https://github.com/TomoOkuyama/clinosim/actions/workflows/docs.yml/badge.svg?branch=master)](https://tomookuyama.github.io/clinosim/)
[![PyPI](https://img.shields.io/pypi/v/clinosim.svg?label=PyPI&color=blue)](https://pypi.org/project/clinosim/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![FHIR](https://img.shields.io/badge/output-HL7%20FHIR%20R4%20Bulk-orange)](https://hl7.org/fhir/uv/bulkdata/)

📚 **[Documentation site](https://tomookuyama.github.io/clinosim/)**  |  🇯🇵 **[README.ja.md](README.ja.md)**

> ⚠️ **Personal project disclaimer** — independent personal project, not an official product of any organisation.
>
> ⚠️ **Synthetic data only** — fully synthetic output. Not for clinical use. clinosim does not ingest, reference, or reproduce any real patient data / PHI / PII.

## What is clinosim?

clinosim generates synthetic EHR data through **forward simulation from a population**. Every patient carries a hidden **14-variable physiological state** (`clinosim/types/clinical.py::PhysiologicalState`), and every observation (labs, vitals, medications, diagnoses) is derived from that state — so the data is **clinically coherent by construction**.

Primary use cases:

- Training data for medical AI / ML models
- EHR system testing and QA
- Clinical-research method development
- Educational case datasets

## Install

**Requires Python 3.11 or newer.**

```bash
pip install clinosim
```

Development install from a clone:

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

For the JP cohort, named-preset datasets, hospital-config override, and the full CLI reference, see **[docs/getting-started/configuration.md](docs/getting-started/configuration.md)**.

## See it in action

For a JP warfarin-anticoagulated patient, clinosim's physiology engine places the patient in the therapeutic PT-INR band and emits a lab value (e.g. `2.7`) inside that range — not by sampling a "PT-INR normal range", but because the hidden state chose it. Remove the warfarin and next run's INR drops back to ~1.0.

**[Full JSON walkthrough → docs/getting-started/first-cohort.md](docs/getting-started/first-cohort.md)**

## Why clinosim?

Most synthetic-EHR tools produce records by sampling from disease distributions. **clinosim runs the disease** — the CKD patient's ED creatinine is elevated even when presenting for something unrelated; the sepsis patient shows the WBC / CRP / lactate cascade.

- **Clinical coherence by construction** — physiology model makes incoherent labs impossible.
- **JP + US natively** — JP Core profile compliance for 16 primary FHIR resource types, JLAC10 / MHLW YJ codes, JP names / addresses / insurance out of the box.
- **YAML-driven extension** — 32 inpatient diseases + 46 ED / outpatient conditions are all data files, not code.
- **Longitudinal service lines** — oncology (10 cancer sites incl. male breast, chemo regimen cycles, radiation therapy Procedure, tumor-marker labs) + obstetrics (pregnancy modelled as a time-boxed `TemporalStatePeriod` lifecycle — annual conception, prenatal visits at gestational weeks 12/24/36, mother-side delivery Encounter with Z37.0 discharge dx + delivery Procedure + newborn Patient chain, postpartum visits at 7 d / 28 d) emit at correct temporal cadence, not as flat annotations. See [`docs/reference/oncology-obstetric-service-lines.md`](docs/reference/oncology-obstetric-service-lines.md).

Prior-art comparison (Synthea): [docs/synthea-comparison.md](docs/synthea-comparison.md).

## Learn more

| Topic | Where |
| --- | --- |
| Full documentation site | <https://tomookuyama.github.io/clinosim/> |
| Architecture reference | [`docs/architecture/`](docs/architecture/README.md) |
| Module index (33 modules) | [`clinosim/modules/`](clinosim/modules/README.md) |
| Data quality & evaluation | [`docs/eval.md`](docs/eval.md) |
| JP-CLINS profile support | [`docs/jp-clins.md`](docs/jp-clins.md) |
| Contributing | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| AI-agent conventions | [`AGENTS.md`](AGENTS.md) |
| Changelog | [`CHANGELOG.md`](CHANGELOG.md) |

## Community

- Code of Conduct — [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) (Contributor Covenant 2.1)
- Security policy — [`SECURITY.md`](SECURITY.md) (private disclosure via GitHub Security Advisories)
- Starter tasks — [`good first issue`](https://github.com/TomoOkuyama/clinosim/labels/good%20first%20issue) label
- Issue templates — [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/) (structured bug / feature forms)
- Citation — GitHub "Cite this repository" button (backed by [`CITATION.cff`](CITATION.cff))

## License

MIT — see [`LICENSE`](LICENSE). Bundled code-system data follows each upstream registry's licence; details in [`clinosim/codes/README.md`](clinosim/codes/README.md).

---

*Note: the top-level `clinosim/` Python package has no dedicated README by design. Module-level documentation lives under [`clinosim/modules/`](clinosim/modules/README.md), and framework docs sit alongside each subsystem — [`audit/`](clinosim/audit/README.md), [`eval/`](clinosim/eval/README.md), [`codes/`](clinosim/codes/README.md), [`benchmarks/`](clinosim/benchmarks/README.md).*
