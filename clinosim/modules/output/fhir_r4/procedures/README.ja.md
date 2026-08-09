# `fhir_r4/procedures/` — procedure / device FHIR R4 builder

## 目的

手術 / 治療手技、および ICU デバイス (CVC / カテーテル / 人工呼吸器)
用の FHIR R4 リソース発行: `Procedure`、`Device`、`DeviceUseStatement`。

## スコープ

- **In scope**: `Procedure` リソース (US は CPT、JP は JJ1017 K-code)、
  `Device`、`DeviceUseStatement`。
- **Out of scope**: 手技 / デバイスの *生成*
  ([`clinosim.modules.procedure/`](../../../procedure/README.ja.md)
  および [`clinosim.modules.device/`](../../../device/README.ja.md))、
  放射線手技用の FHIR `ImagingStudy` (兄弟の
  [`labs/`](../labs/README.ja.md) ディレクトリ)。

## 公開 API

Builder は親 facade (`register_bundle_builder`) 経由で dispatch され、
外部から直接呼び出されない。

## 依存

- `clinosim.types.procedure` — `SurgicalProcedure` / `BedsideProcedure`
  / `TherapySession`。
- `clinosim.types.device` — `DeviceRecord`。
- `clinosim.codes.data.{cpt,jj1017,snomed}` — コーディング lookup。
- 兄弟 `lib/` — 共有ヘルパー。

## 定数と設定

- 手技コード system 優先順:
  - US: CPT (Current Procedural Terminology)、ICD-10-PCS。
  - JP: JJ1017 K-code (診療報酬点数表 K分類、厚生労働省)。
- policy §4 に基づき JJ1017 仕様の日本語引用は英訳 gloss を添えて
  inline 保持可能。
- Device SNOMED CT コードは権威照合済セット
  ([`clinosim.modules.device/`](../../../device/README.ja.md) 参照)。

## ディレクトリ構成

```
clinosim/modules/output/fhir_r4/procedures/
  __init__.py               サブパッケージ facade
  procedure.py              Procedure builder (surgical + bedside + therapy)
  device.py                 Device + DeviceUseStatement builder
```

## テスト

```bash
pytest tests/unit -k procedures -q
pytest tests/integration -k procedure -q
```

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md) 参照。

英語版: [`README.md`](README.md)。
