# `fhir_r4/medications/` — medication FHIR R4 builder

## 目的

薬剤用 FHIR R4 リソース発行: `MedicationRequest` (処方箋)、
`MedicationAdministration` (MAR — 薬剤投与記録)。JP 用の JP-CLINS
プロファイル準拠 (`MedicationRequest.status='completed'` 不変条件を含む)
を担う。

## スコープ

- **In scope**: `MedicationRequest` (US は RxNorm、JP は YJ / HOT
  コード、JP-CLINS プロファイル準拠)、`MedicationAdministration`
  (per-dose MAR 発行)。
- **Out of scope**: 処方 / MAR の *生成*
  ([`clinosim.modules.order/`](../../../order/README.ja.md)、
  [`clinosim.simulator/` (English)](../../../../simulator/README.md)、
  [`clinosim.modules.antibiotic/`](../../../antibiotic/README.ja.md))、
  薬剤コードレジストリ (`clinosim/codes/data/{rxnorm,yj,hot}`)。

## 公開 API

Builder は親 facade (`register_bundle_builder`) 経由で dispatch され、
外部から直接呼び出されない。

## JP-CLINS プロファイル不変条件

- JP-CLINS `MedicationRequest` プロファイルは `MedicationRequest.status
  = "completed"` を要求する。country が JP のとき builder はこの値を
  pin する。intent 情報 (planned / active / discontinued) は代わりに
  note / statusReason / Extension のいずれかに載せる。
- policy §4 に基づき jpfhir.jp 仕様引用は英訳 gloss を添えて日本語
  inline 保持可能。

## 依存

- `clinosim.types.encounter` — `Order` (薬剤) / `MedicationAdministration`。
- `clinosim.codes.data.{rxnorm,yj,hot}` — 薬剤コード lookup。
- `clinosim.locale.{us,jp}.code_mapping_drug.yaml` — 内部 drug key →
  国別薬剤コード解決。
- 兄弟 `lib/` — 共有ヘルパー。

## 定数と設定

- 薬剤コード system 優先順:
  - US: RxNorm。
  - JP: YJ code (製剤単位) + HOT code (包装単位)、JP-CLINS 仕様準拠。
- ID プレフィックス: `MEDICATION_REQUEST_ID_PREFIX`、
  `MEDICATION_ADMINISTRATION_ID_PREFIX`、`ABX_REGIMEN_ID_PREFIX`
  (FHIR R4 の 64 文字 id 制限に収めるため短く保持)。

## ディレクトリ構成

```
clinosim/modules/output/fhir_r4/medications/
  __init__.py               サブパッケージ facade
  medications.py            MedicationRequest + MedicationAdministration builder
```

## テスト

```bash
pytest tests/unit -k medications -q
pytest tests/integration -k medication -q
```

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md) 参照。

英語版: [`README.md`](README.md)。
