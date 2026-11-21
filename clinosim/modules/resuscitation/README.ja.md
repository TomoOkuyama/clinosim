# `clinosim.modules.resuscitation`

蘇生処置を行う方針の患者の院内死亡に付く、死亡時刻で終わる心肺蘇生の記録 (Issue #3483)。

## 目的

コードステータスが「蘇生処置を行う」の患者が院内で死亡しても、蘇生の処置・薬剤・コードイベントの記録がなかった。そのため退院時サマリーは、蘇生を伴わない心肺停止を断定するか、記録がないと書くしかなかった。このモジュールが蘇生の試みを記録する。

## 範囲

**対象**: `code_status` が蘇生処置を行う区分 (`resuscitation_rules.yaml` の `attempt_tier`) である入院または救急の死亡レコードに、死亡時刻 (入院エンカウンターの退院時刻) で終わる CPR の `ProcedureRecord` を 1 件 (`procedure_type: cpr`、US は CPT 92950、JP は K コード J046 非開胸的心マッサージ)、その間に投与したエピネフリンの `Order` と `MedicationAdministration` を記録する。CIF に完結して入るので、FHIR の Procedure / MedicationRequest / MedicationAdministration と死亡退院サマリーは既存の経路で読む。

**行わないこと**: 蘇生処置を行わない方針 (DNAR、DNAR + DNI、緩和ケア) とコードステータスが不明な場合は蘇生を記録しない。生存した患者にも記録しない。気管挿管は追加しない (根拠にできる気道確保・リズムの記録がなく、すでに記録された気道はそのまま残す)。`epinephrine.min_age` (18) 未満の患者には CPR だけを記録し、エピネフリンは記録しない (1 mg は成人量で、小児の体重換算量はこの変更で確認していない)。

## 規則 (`reference_data/resuscitation_rules.yaml`)

| 規則 | 値 | 根拠 |
|---|---|---|
| エピネフリンの量と経路 | 1 mg 静注 | AHA 2020 成人心停止アルゴリズム: 「Epinephrine IV/IO dose: 1 mg every 3-5 minutes」 |
| 間隔 | 4 分 | ガイドラインの 3~5 分の範囲内でのモデル上の選択 |
| 初回投与 | 開始 2 分後 | モデル上の選択 (非ショック適応リズムでは「できるだけ早く」とされる) |
| 継続時間 | 入院ごとに 15~45 分 | モデル上の選択。ガイドラインに時間の記載はない。入院期間を上限とする |

## 決定性

継続時間は `clinosim.seeding.resuscitation_seed(patient_id, encounter_id)` (ID の SHA-256) で種付けした入院ごとのサブ RNG から引く。既存の乱数列は読まず、ずらさない。それ以外は死亡時刻と YAML だけで決まる。エンリッチャーは `POST_RECORDS` の order 55 で `code_status` (50) の後に走り、再実行しても重複しない。

## 公開 API

```python
from clinosim.modules.resuscitation.engine import load_rules, build_cpr_procedure, build_epinephrine
from clinosim.modules.resuscitation.enricher import enrich_resuscitation
```

## 依存

`clinosim.modules.code_status` (区分とその SNOMED コード)、`clinosim.codes.procedures` (カタログの `cpr`)、`clinosim.modules.order.placed_order_mar.stable_nurse`、`clinosim.seeding`、pydantic (ルール YAML を読み込み時に検証)。
