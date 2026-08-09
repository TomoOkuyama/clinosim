# `fhir_r4/demographics/` — demographics FHIR R4 builder

## 目的

患者 demographics、practitioner demographics、家族歴、
social-history Observation (喫煙 / 飲酒) 用の FHIR R4 リソース発行。

## スコープ

- **In scope**: `Patient`、`Practitioner`、`FamilyMemberHistory`、
  および social-history `Observation` (喫煙状態、飲酒量)。
- **Out of scope**: patient / practitioner の *生成*
  ([`clinosim.modules.population/`](../../../population/README.ja.md)、
  [`clinosim.modules.identity/`](../../../identity/README.ja.md)、
  [`clinosim.modules.staff/`](../../../staff/README.ja.md))、家族歴の
  *生成* ([`clinosim.modules.family_history/`](../../../family_history/README.ja.md))、
  SDOH の *生成* ([`clinosim.modules.sdoh/`](../../../sdoh/README.ja.md))。

## 公開 API

Builder は親 facade (`register_bundle_builder`) 経由で dispatch され、
外部から直接呼び出されない。

## 依存

- `clinosim.types.patient` — `PatientProfile` / `Address` /
  `ContactInfo`。
- `clinosim.types.staff` — `Practitioner`。
- `clinosim.types.family_history` — `FamilyMemberHistoryRecord`。
- `clinosim.codes.data.{snomed,loinc}` — social-history Observation
  コーディング。
- 兄弟 `lib/` — 共有ヘルパー。

## 定数と設定

- Patient MRN / 保険者識別子の system URI は
  [`clinosim.modules.identity/`](../../../identity/README.ja.md) の
  providers 由来。
- Practitioner の資格 / role コーディング — `demographics/practitioner.py`
  参照。
- JP 患者には JP-Core `Patient` プロファイル URI を打刻。

## ディレクトリ構成

```
clinosim/modules/output/fhir_r4/demographics/
  __init__.py               サブパッケージ facade
  patient.py                Patient builder
  practitioner.py           Practitioner builder
  family_history.py         FamilyMemberHistory builder
  smoking_alcohol.py        social-history Observation builder
```

## テスト

```bash
pytest tests/unit -k demographics -q
pytest tests/integration -k demographic -q
```

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md) 参照。

英語版: [`README.md`](README.md)。
