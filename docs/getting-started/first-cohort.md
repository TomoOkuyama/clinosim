# Your first cohort — reading the FHIR output

This walkthrough shows what one physiology-driven lab value looks like in clinosim's FHIR R4 output. It follows on from [`quick-start.md`](quick-start.md).

## Generate the JP warfarin cohort

```bash
clinosim simulate --country JP --population 100 --seed 42 \
  --start 2026-01-01 --end 2026-03-31 \
  --output ./out-jp --format fhir-r4
```

`--country JP` requires the JP-CLINS FHIR package (see [Installation](installation.md)); without it the run exits with an error unless you pass `--allow-legacy`.

Pick a patient on chronic warfarin for atrial fibrillation. `fhir_r4/Observation.ndjson` will contain a PT-INR entry like the one below (abridged; `identifier`, `category`, `encounter`, `performer`, `specimen` etc. omitted). This excerpt was produced with `--allow-legacy`, so the lab code is the legacy 5-digit JLAC10 OID; with the JP-CLINS package installed the JLAC10 coding is the 17-digit JP-CLINS CoreLabo code instead.

```json
{
  "resourceType": "Observation",
  "id": "lab-45136ca9d209",
  "meta": { "profile": [
    "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_LabResult",
    "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common",
    "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Observation_LabResult_eCS"
  ]},
  "status": "final",
  "code": {"coding": [
    { "system": "urn:oid:1.2.392.200119.4.1005", "code": "2B030",
      "display": "プロトロンビン時間" },
    { "system": "http://loinc.org", "code": "6301-6",
      "display": "INR in Platelet poor plasma by Coagulation assay" }
  ], "text": "プロトロンビン時間"},
  "subject": {"reference": "Patient/pt-cbdea7ced336"},
  "effectiveDateTime": "2026-03-14T10:39:00+09:00",
  "valueQuantity": {"value": 2.6, "unit": "{INR}",
    "system": "http://unitsofmeasure.org", "code": "{INR}"},
  "referenceRange": [{
    "low": {"value": 0.85, "unit": "{INR}"}, "high": {"value": 1.15, "unit": "{INR}"},
    "text": "一般基準値（非ワーファリン服用）"
  }],
  "interpretation": [{"coding": [{
    "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
    "code": "H"
  }]}]
}
```

## Why this matters

Notice: the INR value `2.6` was not sampled from a "PT-INR normal range". The physiology engine detected warfarin from the chronic-medication list and placed this patient around the 2.0 – 3.0 therapeutic band (target centre 2.5). The reference range is the general (non-warfarin) range from the locale's reference-range table, so the value is flagged `H` against it.

- Change the seed → a different but still-therapeutic value.
- Remove the warfarin → a normal (~1.0) INR next run.

That is what "clinical coherence by construction" means in practice.

## Where to look in the output

| File | Contains |
| --- | --- |
| `Patient.ndjson` | Demographics, identifiers |
| `Coverage.ndjson` | Insurance (JP: 被保険者番号, on by default; `--no-jp-insurance` omits it) |
| `Encounter.ndjson` | Admissions, discharges, encounter periods |
| `Observation.ndjson` | Labs, vitals — including the PT-INR shown above |
| `MedicationRequest.ndjson` | Warfarin order that drove the INR band |
| `Condition.ndjson` | Atrial fibrillation (the indication for warfarin) |

## Next steps

- Full CLI reference: [`configuration.md`](configuration.md).
- Architecture behind the physiology model: [`../architecture/README.md`](../architecture/README.md).
- Public cohort scoring gate: [`../eval.md`](../eval.md).
