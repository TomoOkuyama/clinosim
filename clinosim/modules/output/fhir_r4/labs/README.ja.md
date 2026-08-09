# `fhir_r4/labs/` — 検体検査 FHIR R4 builder

## 目的

FHIR R4 の Laboratory / Vital-Signs Observation、微生物培養、画像検査、
および関連する DiagnosticReport / ServiceRequest を発行するサブパッケージ。
本サブパッケージは JP locale 特化が最も濃い領域 (JLAC10 検体検査コード、
JP-CLINS `Observation-LabResult-eCS` プロファイル、JJ1017 手技コード)。

## スコープ

- **In scope**: `Observation` (検体検査 + バイタル + 微生物)、
  `DiagnosticReport`、`ServiceRequest`、`ImagingStudy`、JLAC10 検体検査
  コードローダー (`coding_package`)、全 `Observation.category = laboratory`
  についての JP-CLINS プロファイル準拠。
- **Out of scope**: 非検査ドメインの FHIR リソース発行 (兄弟ディレクトリ
  `encounters/` / `conditions/` / `procedures/` / `demographics/` /
  `documents/` / `medications/` を参照)、検査結果の *生成*
  ([`clinosim.modules.observation/` (English)](../../../observation/README.md))、
  微生物の *organism サンプリング*
  ([`clinosim.modules.hai/` (English)](../../../hai/README.md))。

## 公開 API

Builder は親 facade (`register_bundle_builder`) 経由で dispatch され、
外部から直接呼び出されない。

## JP-Core / JP-CLINS プロファイル対応

本サブパッケージが発行する `Observation.category = laboratory` は全て
以下を対象とする:

- プロファイル URI: `http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_LabResult`
- 追加 JP-CLINS eCS プロファイル:
  `http://jpfhir.jp/fhir/clins/StructureDefinition/JP_Observation_LabResult_eCS`

同一検体の code system 優先順位:

1. JLAC10 (17 桁、存在時) — `urn:oid:1.2.392.200119.4.504`。
2. LOINC — `http://loinc.org`。

`coding_package.py` が JLAC10 ローダー本体。policy §4 に基づき、日本語
権威ソース (JSLM 公式マスター、JAHIS 技術文書、jpfhir.jp 実装ガイド)
の引用は英訳 gloss を添えて日本語のまま inline 保持可能。

## 依存

- `clinosim.types.encounter` — `Order` / `ObservationResult` /
  `VitalSignRecord`。
- `clinosim.types.microbiology` — `MicrobiologyResult` / `Specimen`。
- `clinosim.types.imaging` — `ImagingStudyRecord` / `RadiologyReport`。
- `clinosim.codes.data.{jlac10,loinc,snomed}` — コーディング lookup。
- 兄弟 `lib/` — 共有ヘルパー。

## 定数と設定

- JLAC10 権威ソース: [JSLM (日本臨床検査医学会) 公式マスター](https://www.jslm.org/)
  および [jpfhir.jp](https://jpfhir.jp/)。
- Vital-sign reference / critical bounds — 現状 `observations.py` の
  positional tuple。定数監査 Hotspot B
  ([`docs/reviews/2026-08-09-constants-audit.md`](../../../../../docs/reviews/2026-08-09-constants-audit.md))。
- `RADIOLOGY_DR_ID_PREFIX` 等のリソース ID プレフィックスは `lib/ids.py`
  由来。

## ディレクトリ構成

```
clinosim/modules/output/fhir_r4/labs/
  __init__.py               サブパッケージ facade
  observations.py           検体検査 + バイタル Observation builder (Hotspot B)
  microbiology.py           微生物 Observation + culture chain
  diagnostic_report.py      DiagnosticReport builder (放射線 + 検査 variant)
  service_request.py        ServiceRequest builder
  imaging_study.py          ImagingStudy builder
  coding_package.py         JLAC10 ローダー + per-context 検体材料コーディング
  coding_strategy.py        code system 選択ロジック
```

## テスト

```bash
pytest tests/unit -k labs -q
pytest tests/integration -k labs -q
```

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md) 参照。

英語版: [`README.md`](README.md)。
