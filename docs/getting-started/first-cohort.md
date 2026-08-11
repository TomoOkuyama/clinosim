# Your first cohort — reading the FHIR output

This walkthrough shows what one physiology-driven lab value looks like in clinosim's FHIR R4 output. It follows on from [`quick-start.md`](quick-start.md).

## Generate the JP warfarin cohort

```bash
clinosim simulate --country JP --population 100 --seed 42 \
  --output ./out-jp --format fhir-r4
```

Pick a patient on chronic warfarin for atrial fibrillation. Their `Observation.ndjson` will contain a PT-INR entry like:

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

## Why this matters

Notice: the INR value `2.7` was not sampled from a "PT-INR normal range". The physiology engine detected warfarin from the chronic-medication list, placed this patient in the 2.0 – 3.0 therapeutic band, and picked the reference range and interpretation to match.

- Change the seed → a different but still-therapeutic value.
- Remove the warfarin → a normal (~1.0) INR next run.

That is what "clinical coherence by construction" means in practice.

## Where to look in the output

| File | Contains |
| --- | --- |
| `Patient.ndjson` | Demographics, identifiers, insurance |
| `Encounter.ndjson` | Admissions, discharges, encounter periods |
| `Observation.ndjson` | Labs, vitals — including the PT-INR shown above |
| `MedicationRequest.ndjson` | Warfarin order that drove the INR band |
| `Condition.ndjson` | Atrial fibrillation as the reason for warfarin |

## Next steps

- Full CLI reference: [`configuration.md`](configuration.md).
- Architecture behind the physiology model: [`../architecture/README.md`](../architecture/README.md).
- Public cohort scoring gate: [`../eval.md`](../eval.md).
