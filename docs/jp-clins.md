# JP-CLINS Profile Support

clinosim emits FHIR R4 resources with **JP-CLINS (電子カルテ情報共有サービス) profile URLs** for `country=JP` cohorts. This document covers the 6 information items enabled in PR1; 3-document Composition support (退院時サマリー / 診療情報提供書 / opt-in 健康診断結果報告書) lands in PR2 and PR3.

Verified against jpfhir.jp JP-CLINS **v1.12.0** (2026-02-16). See
<https://jpfhir.jp/fhir/clins/igv1/artifacts.html>.

## Scope

Acute-care hospital EHR/EMR data generation, `country=JP`.

### 6 information items / 5 profiles (PR1)

JP-CLINS v1.12.0 publishes **5 StructureDefinition profiles** covering the "6 information items" domain concept — 傷病名 and 感染症 share the same `JP_Condition_eCS` profile (no separate infection profile), and DiagnosticReport is **not** in JP-CLINS scope (lab results are emitted only as Observation.LabResult).

For every country=JP cohort, the following resource types carry the JP-CLINS eCS profile URL in `meta.profile[]` alongside the existing JP Core profile:

| Information | Resource | JP-CLINS profile URL |
|---|---|---|
| 傷病名 + 感染症 | Condition | `.../JP_Condition_eCS` |
| アレルギー | AllergyIntolerance | `.../JP_AllergyIntolerance_eCS` |
| 検査 | Observation (category=laboratory) | `.../JP_Observation_LabResult_eCS` |
| 処方 | MedicationRequest | `.../JP_MedicationRequest_eCS` |
| 処置 | Procedure | `.../JP_Procedure_eCS` |

URL root: `http://jpfhir.jp/fhir/eCS/StructureDefinition/`

**Filter:**

- Observation: only when `category.coding[].code == "laboratory"` — vital signs stay on the JP Core profile only.

**Not covered by JP-CLINS v1.12.0** (emitted with JP Core profile only, no JP-CLINS URL added):

- DiagnosticReport (any category)
- Observation vital-signs / social-history / survey / imaging
- Encounter, Patient, Organization, Practitioner, Coverage, Immunization, FamilyMemberHistory, etc. (JP Core is the applicable base)

## Example

```json
{
  "resourceType": "MedicationRequest",
  "meta": {
    "profile": [
      "http://jpfhir.jp/fhir/core/StructureDefinition/JP_MedicationRequest",
      "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_MedicationRequest_eCS"
    ]
  },
  "medicationCodeableConcept": {
    "coding": [{
      "system": "urn:oid:1.2.392.100495.20.1.72",
      "code": "6113005F1023",
      "display": "セフトリアキソンナトリウム注1g"
    }]
  }
}
```

## Reproducibility

The layer is deterministic — `scripts/reproduce.sh` continues to pass with country=JP output byte-identical across independent runs.

## Out of scope for PR1

See spec §1.3 in `docs/superpowers/specs/2026-07-12-p2-13-jp-clins-design.md`:

- 3 documents Composition (退院時サマリー / 診療情報提供書 / 健康診断結果報告書) — PR2 + PR3
- 健診 encounter generation — PR3 opt-in
- 機関間連携 workflow simulation — non-goal

## Deferred improvement candidates

Session 47 preflight review surfaced three items worth revisiting in future PRs:

- CIF `orders` list split into `medication_orders` / `lab_orders` (matches FHIR resource type separation)
- CLI verb `generate` → `simulate` rename with a deprecation alias (semantically more accurate for a physiology-driven simulator)
- `_JP_CORE_PROFILES` shape unification from `dict[str, str]` to `dict[str, list[str]]` (matches JP-CLINS shape)

Each is a small, independent refactor — best delivered as its own PR rather than folded into P2-13.
