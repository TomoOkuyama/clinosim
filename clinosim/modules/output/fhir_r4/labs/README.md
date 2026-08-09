# `fhir_r4/labs/` — laboratory FHIR R4 builders

## Purpose

Emits FHIR R4 resources for laboratory results, vital-signs
observations, microbiology cultures, imaging studies, and their
associated diagnostic reports and service requests. This is the
subpackage that carries the heaviest JP-locale specialisation
(JLAC10 lab codes, JP-CLINS `Observation-LabResult-eCS` profile,
JJ1017 procedure codes).

## Scope

- **In scope**: `Observation` (labs + vitals + microbiology),
  `DiagnosticReport`, `ServiceRequest`, `ImagingStudy`, JLAC10 lab-
  code loader (`coding_package`), JP-CLINS profile compliance for
  every emitted `Observation.category = laboratory`.
- **Out of scope**: emitting FHIR resources for non-lab domains
  (see sibling directories `encounters/`, `conditions/`,
  `procedures/`, `demographics/`, `documents/`, `medications/`),
  laboratory *result generation* (in
  [`clinosim.modules.observation/`](../../../observation/README.md)),
  microbiology *organism sampling* (in
  [`clinosim.modules.hai/`](../../../hai/README.md)).

## Public API

Builders are dispatched through the parent facade
(`register_bundle_builder`), not called directly from outside this
subpackage.

## JP-Core / JP-CLINS profile compliance

Every `Observation.category = laboratory` emitted by this subpackage
targets:

- Profile URI: `http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_LabResult`
- Additional JP-CLINS eCS profile:
  `http://jpfhir.jp/fhir/clins/StructureDefinition/JP_Observation_LabResult_eCS`

Code system precedence for the same analyte:

1. JLAC10 (17-digit, when available) — `urn:oid:1.2.392.200119.4.504`.
2. LOINC — `http://loinc.org`.

`coding_package.py` is the JLAC10 loader; per policy §4, Japanese
authoritative source quotations (JSLM 公式マスター, JAHIS technical
reports, jpfhir.jp implementation guides) may appear in-line in
Japanese with English gloss.

## Dependencies

- `clinosim.types.encounter` — `Order`, `ObservationResult`,
  `VitalSignRecord`.
- `clinosim.types.microbiology` — `MicrobiologyResult`, `Specimen`.
- `clinosim.types.imaging` — `ImagingStudyRecord`, `RadiologyReport`.
- `clinosim.codes.data.{jlac10,loinc,snomed}` — coding lookups.
- Sibling `lib/` — shared helpers.

## Constants and configuration

- JLAC10 authoritative source: [JSLM (Japan Society of Laboratory
  Medicine) 公式マスター](https://www.jslm.org/) and
  [jpfhir.jp](https://jpfhir.jp/).
- Vital-sign reference / critical bounds — currently positional tuples
  in `observations.py`; Hotspot B of the constants audit
  ([`docs/reviews/2026-08-09-constants-audit.md`](../../../../../docs/reviews/2026-08-09-constants-audit.md)).
- `RADIOLOGY_DR_ID_PREFIX` and other resource-ID prefixes come from
  the `lib/ids.py` module.

## Directory contents

```
clinosim/modules/output/fhir_r4/labs/
  __init__.py               subpackage facade
  observations.py           lab + vital-sign Observation builder (Hotspot B)
  microbiology.py           microbiology Observation + culture chain
  diagnostic_report.py      DiagnosticReport builder (radiology + lab variants)
  service_request.py        ServiceRequest builder
  imaging_study.py          ImagingStudy builder
  coding_package.py         JLAC10 loader + per-context specimen-material coding
  coding_strategy.py        code-system selection logic
```

## Testing

```bash
pytest tests/unit -k labs -q
pytest tests/integration -k labs -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
