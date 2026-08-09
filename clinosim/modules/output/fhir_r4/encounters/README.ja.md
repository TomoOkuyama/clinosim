# `fhir_r4/encounters/` — encounter FHIR R4 builder

## 目的

encounter 本体とその運用コンテキスト用の FHIR R4 リソース発行:
`Encounter`、`CareTeam`、`Location`、`Organization`、`Endpoint`、
および JP-locale 介護度データを載せる custom `CareLevel` Observation。

## スコープ

- **In scope**: `Encounter` リソース構築、encounter practitioners から
  `CareTeam` 組み立て、facility 用 `Location` + `Organization` 発行、
  imaging WADO base URL 用 `Endpoint`、`CareLevel` custom Observation。
- **Out of scope**: encounter *シミュレーション*
  ([`clinosim.simulator/` (English)](../../../../simulator/README.md))、
  facility モデル
  ([`clinosim.modules.facility/`](../../../facility/README.ja.md))、
  practitioner identity
  ([`clinosim.modules.staff/`](../../../staff/README.ja.md))。

## 公開 API

Builder は親 facade (`register_bundle_builder`) 経由で dispatch され、
外部から直接呼び出されない。

## 依存

- `clinosim.types.encounter` — `Encounter` / `EncounterType` /
  `EncounterStatus`。
- 兄弟 `lib/` — 共有ヘルパー。

## 定数と設定

- Encounter-status FHIR mapping は `encounter.py` 内。
- CareLevel Observation コーディングは `clinosim.modules.care_level` の
  JP-locale 介護度参照データを使用。

## ディレクトリ構成

```
clinosim/modules/output/fhir_r4/encounters/
  __init__.py               サブパッケージ facade
  encounter.py              Encounter リソース builder
  care_team.py              CareTeam builder
  facility.py               Location + Organization emitter
  endpoint.py               Endpoint (WADO base URL) emitter
  care_level.py             CareLevel custom Observation
```

## テスト

```bash
pytest tests/unit -k encounters -q
pytest tests/integration -k encounter -q
```

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md) 参照。

英語版: [`README.md`](README.md)。
