# `fhir_r4/` — FHIR R4 出力サブシステム

構成: 共有ライブラリ + 7 臨床ドメイン別 builder サブパッケージ + post-processing。

- `lib/` — 共有ヘルパー (`common` / `localization` / `reference_data` /
  `inline_bb` / `generator_metadata` / `ids`)。
- `demographics/` / `encounters/` / `medications/` / `labs/` /
  `procedures/` / `conditions/` / `documents/` — 臨床ドメイン別
  リソース builder。
- `post_process/` — bundle レベルパイプライン (PR3、Issue #556 統合)。

サブパッケージの `__init__.py` が公開 facade (`register_bundle_builder`
/ `available_builders` / `convert_cif_to_fhir` / …)。`../fhir_r4_adapter.py`
の薄い shim が同一 API を後方互換 re-export。

## FHIR リソース → ドメイン マッピング

| FHIR リソース | ドメインモジュール |
|---|---|
| Patient | `demographics/patient.py` |
| Practitioner | `demographics/practitioner.py` |
| FamilyMemberHistory | `demographics/family_history.py` |
| Observation (喫煙 / 飲酒 / social) | `demographics/smoking_alcohol.py` |
| Encounter | `encounters/encounter.py` |
| CareTeam | `encounters/care_team.py` |
| CareLevel (custom Observation) | `encounters/care_level.py` |
| Location + Organization | `encounters/facility.py` |
| Endpoint | `encounters/endpoint.py` |
| MedicationRequest / MedicationAdministration | `medications/medications.py` |
| Observation (検体検査 + バイタル) | `labs/observations.py` |
| DiagnosticReport | `labs/diagnostic_report.py` |
| ServiceRequest | `labs/service_request.py` |
| Observation (微生物) | `labs/microbiology.py` |
| ImagingStudy | `labs/imaging_study.py` |
| — (JP-CLINS 検体検査コードローダー) | `labs/coding_package.py` |
| Procedure | `procedures/procedure.py` |
| Device / DeviceUseStatement | `procedures/device.py` |
| Condition | `conditions/condition.py` |
| AllergyIntolerance | `conditions/allergy.py` |
| Immunization | `conditions/immunization.py` |
| Composition / DocumentReference | `documents/composition.py` /
  `documents/document_reference.py` |

## JP-CLINS プロファイル対応

`labs/coding_package.py` は JLAC10 検体検査コードのローダー本体で、
JP-CLINS プロファイル準拠の Observation 発行を制御する。JJ1017 手技
コードは `procedures/procedure.py` に統合済み。JP-Core プロファイル URI
と関連 canonical URL は `lib/reference_data/` 配下のデータで一元管理。

## テスト

```bash
pytest tests/unit -k fhir_r4 -q
pytest tests/integration -k fhir -q
```

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../../../CONTRIBUTING.md) 参照。

英語版: [`README.md`](README.md)。
