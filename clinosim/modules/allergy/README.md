# allergy module

## 役割

Tier 1 #3 α-min-1 always-on Module (AD-55 Base)。`PatientProfile.allergies`
を populate (POST_POPULATION enricher、prevalence-calibrated sampling)。

## サンプリング設計

2段階サンプリング (baseline calibration: activator path 15.3% 一致):

1. **patient-level overall gate**: `OVERALL_ALLERGY_PREVALENCE = 0.15` bernoulli
   (85% の患者は no allergy)
2. **gate 成立 patient のみ**: `CATEGORY_WEIGHTS = {medication: 0.50, food: 0.25, environment: 0.25}`
   で category を選択 → category 内 uniform でアレルゲン 1 件を選択

`allergens.yaml` の `prevalence.adult` フィールドは documentation 目的
(category-level base rate 参考)。actual sampling は overall_prob で gate される設計。

## Dependencies

- `clinosim/types/allergy.py` — `Allergy` + `AllergyReaction` dataclass
- `clinosim/simulator/seeding.py` — `ENRICHER_SEED_OFFSETS["allergy"] = 0x414C` ("AL")

## Reference data

- `reference_data/allergens.yaml` — 3 category (medication / food / environment)
  allergen catalog with prevalence + criticality + common reactions

## エンリッチャー登録

`clinosim/simulator/enrichers.py` に POST_POPULATION order=10 で登録。
Identity (order=10, name="identity") とのタイブレークは名前順 ("allergy" < "identity")
で allergy が先に実行される。

## Consumers (予定)

- `clinosim/modules/output/_fhir_allergy_intolerance.py` — AllergyIntolerance FHIR resource (Task 3 以降)
- `clinosim/modules/document/` — NarrativeContext.allergies に渡し narrative 内で言及 (後続 Phase)

## 関連

- Spec: `docs/superpowers/specs/2026-07-01-tier1-3-document-density-alpha-min-1-design.md`
- Master plan: `docs/design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md`
- Task brief: `.superpowers/sdd/task-2-brief.md`
