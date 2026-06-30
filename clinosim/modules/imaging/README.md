# imaging module

## 役割

Tier 1 #2 = Imaging metadata-only chain。`extensions["imaging"]: list[ImagingStudyRecord]`
を populate(POST_ENCOUNTER stage、order=90、device/hai/antibiotic と同 always-on
near-essential cascade)。

PR1 scope:
- Modalities: CR(plain X-ray)+ CT
- Body sites: chest + head
- Diseases: bacterial_pneumonia / aspiration_pneumonia / hemorrhagic_stroke

## Dependencies

- `clinosim/types/imaging.py` — `ImagingStudyRecord` / `ImagingSeries` / `RadiologyReport`
- `clinosim/types/encounter.py` — `Order.imaging_modality` / `imaging_body_site_code` / `imaging_views`
- `clinosim/simulator/seeding.py` — `ENRICHER_SEED_OFFSETS["imaging"] = 0x494D`
- `clinosim/simulator/enrichers.py` — POST_ENCOUNTER stage registration

## Reference data

- `reference_data/modalities.yaml` — DCM modality 定義(CR + CT)
- `reference_data/body_sites.yaml` — SNOMED body site + procedure codes(LOINC + CPT + JP-K)
- `reference_data/impression_templates.yaml` — disease × modality × normal/abnormal report templates

## Consumers

- `clinosim/modules/output/_fhir_service_request.py` — ImagingStudy 経由間接 + Order(IMAGING)直接
- `clinosim/modules/output/_fhir_imaging_study.py` — ImagingStudy resource(新)
- `clinosim/modules/output/_fhir_endpoint.py` — Endpoint resource(新)
- `clinosim/modules/output/_fhir_diagnostic_report.py` — radiology DR variant
- `clinosim/modules/imaging/audit.py` — AD-60 audit plug-in

## 関連

- Spec: `docs/superpowers/specs/2026-06-30-tier1-imaging-chain-design.md`
- DESIGN.md: AD-62(Imaging metadata-only chain with WADO-RS placeholder)
