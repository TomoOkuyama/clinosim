# `fhir_r4/conditions/` — condition / allergy / immunization FHIR R4 builder

## 目的

臨床状態、アレルギー、予防接種の FHIR R4 リソース発行:
`Condition`、`AllergyIntolerance`、`Immunization`、および対応コーディング
(US は ICD-10-CM、JP は ICD-10-JP、アレルゲンは RxNorm / SNOMED、
ワクチンは CVX)。

## スコープ

- **In scope**: `Condition` (primary + secondary 診断、慢性状態)、
  `AllergyIntolerance`、`Immunization`。
- **Out of scope**: 診断 / アレルギー / 予防接種の *生成*
  ([`clinosim.modules.diagnosis/`](../../../diagnosis/README.ja.md)、
  [`clinosim.modules.allergy/`](../../../allergy/README.ja.md)、
  [`clinosim.modules.immunization/`](../../../immunization/README.ja.md))、
  コードレジストリ本体 (`clinosim/codes/`)。

## 公開 API

Builder は親 facade (`register_bundle_builder`) 経由で dispatch され、
外部から直接呼び出されない。

## 依存

- `clinosim.types.diagnosis` — `DiagnosisRecord`。
- `clinosim.types.allergy` — `Allergy` / `AllergyReaction`。
- `clinosim.types.encounter` — `ImmunizationRecord`。
- `clinosim.codes.data.{icd10cm,icd10-jp,snomed,cvx}` — コーディング
  lookup。
- 兄弟 `lib/` — 共有ヘルパー。

## 定数と設定

- ICD-10 dispatch ルール: US は ICD-10-CM (billable) 発行、JP は
  WHO ICD-10 (3-4 桁、JP-Core 慣例) 発行。詳細は
  [`clinosim.locale/`](../../../../locale/README.ja.md) の
  `code_mapping_diagnosis.yaml` 参照。
- アレルゲンコーディング: RxNorm (US 薬剤アレルギー)、SNOMED (食物 +
  環境)。
- ワクチンコーディング: CVX (国横断)。

## ディレクトリ構成

```
clinosim/modules/output/fhir_r4/conditions/
  __init__.py               サブパッケージ facade
  condition.py              Condition builder
  allergy.py                AllergyIntolerance builder
  immunization.py           Immunization builder
```

## テスト

```bash
pytest tests/unit -k conditions -q
pytest tests/integration -k condition -q
```

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md) 参照。

英語版: [`README.md`](README.md)。
