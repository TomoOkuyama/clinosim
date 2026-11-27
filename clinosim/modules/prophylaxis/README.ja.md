# `clinosim.modules.prophylaxis`

48 時間以上の入院に対する標準治療としての VTE (DVT) 薬物的予防。

## 概要

実際の病棟プロトコルでは、48 時間以上入院する全患者に VTE 予防の
評価が求められ、米国で禁忌の無い大多数に対する標準治療レジメンは
Enoxaparin 40 mg SC 1 日 1 回 (Cockcroft-Gault のクレアチニン
クリアランスが 30 mL/min 未満なら 30 mg 1 日 1 回) である。日本では
エノキサパリンの適応は整形外科・腹部手術に限られるため、内科入院患者には
低用量未分画ヘパリン (5,000 単位 SC 12 時間ごと) を用いる。本 module 以前は、32 の疾患
YAML のうち 14 しか `supportive_orders:` に DVT 予防を載せておらず、
48 時間以上の IMP encounter の約 40 % が予防投与なしになっていた
(US p=2000 seed=500 baseline: 103 件中 40 件が未カバー)。

## Scope

**In scope**: 48 時間以上の IMP encounter に対する DVT (VTE) 薬物的
予防 Order の emit と、その日次 MedicationAdministration 行 (Issue
#2607 — order から退院まで (用量変更で次の order に置き換わる場合はその時点まで)、
レジメンの `administration_hours` の各時刻に 1 回、
`order.placed_order_mar.stable_nurse` で選んだ病棟看護師が投与)。
以下の場合はルールベースで skip する: 患者が
小児年齢上限 (既定 15) 未満、既に治療量の抗凝固療法中 (warfarin /
DOAC / heparin 持続点滴)、入院時診断が活動性出血 / 最近の出血性
脳卒中 / 消化管出血 / 分娩 / 活動性 DVT-PE の治療、または
Enoxaparin が有効な薬剤と major / 禁忌ペアを形成する
(`drug_safety.check_candidate_against_active`、Issue #1087)。
入院中に合併症が開始した治療量の抗凝固薬(id に `-COMPTX-`、Issue #3864)は、それ以前の予防投与を取り消さない。予防投与はその指示の時刻で終わる(それより前に始まっていた場合は投与しない)。出血性の合併症が書いた予防薬の中止マーカーは、退院後に `order.supersede.drop_doses_after_hold` がそれ以降の投与を除く。

**Out of scope (post-MVP)**:
- ストレス潰瘍予防 (ICU での PPI) — 別プロトコル。
- VAP bundle (頭部挙上、クロルヘキシジン口腔ケア) — nursing
  enricher の担当。
- 出血禁忌の患者に対する機械的予防 (間欠的空気圧迫法) への
  fallback — 先送り。現行設計では単に skip する。

## Public API

```python
from clinosim.modules.prophylaxis import (
    build_dvt_prophylaxis_orders,
    should_skip_dvt_prophylaxis,
)

# Skip-decision helper (pure function on patient / encounter state)
skip, reason = should_skip_dvt_prophylaxis(
    patient=patient_profile,
    encounter=encounter,
    admission_dx_code="J18.1",
    active_medications=["Warfarin 3mg PO daily"],
)
# → (True, "therapeutic_anticoagulant_active")

# Order builder for a CIF record
orders = build_dvt_prophylaxis_orders(record=cif_record, country="US")
# → [Order(order_id="ORD-<encounter_id>-DVT-01", display_name="Enoxaparin", ...)]
```

## 国別・腎機能別のレジメン (Issue #3449)

YAML の `dvt_prophylaxis.regimens` が国ごとのレジメンを持つ (無い国は
`default_country` を使う):

- **US**: Enoxaparin 40 mg SC 1 日 1 回 (Lovenox 添付文書 2.2、急性疾患時の内科患者)。
  **Cockcroft-Gault の CrCl が 30 mL/min 未満の間は 30 mg 1 日 1 回**
  (添付文書 2.3 Table 1、8.7)。30 mL/min 以上は調整しない。
- **JP**: ヘパリン 5,000 IU (単位) SC 12 時間ごと (`q12h`、09:00 と 21:00)。
  エノキサパリン (クレキサン) は日本では下肢整形外科手術と高リスク腹部手術
  にのみ承認され、CrCl 30 mL/min 未満は禁忌 (添付文書 2.4、4.) のため、
  内科入院患者には使わない。未分画ヘパリンの添付文書は血栓塞栓症の治療及び
  予防を効能とし、日本循環器学会 2017 年 PTE/DVT ガイドライン (3.4) は基礎疾患を
  問わず 5,000 単位を 8 または 12 時間ごととしている。手術時のエノキサパリン
  (2,000 IU 1 日 2 回) は扱わない: order は手術時刻に関わらず入院 6 時間後に
  置かれるが、添付文書は術後 24〜36 時間から開始とする。

クレアチニンクリアランス (`renal_dose.crcl_cockcroft_gault`、項は YAML の
`creatinine_clearance`) には、その入院で記録された体重、入院時年齢、order 時刻
以前の直近のクレアチニンを使う (クレアチニンが無ければ標準用量)。その後の
クレアチニンが CrCl を閾値の反対側へ動かしたら、その結果時刻で order を中止し、
もう一方の用量の新しい order (`...-DVT-02`、`prior_order_id` 設定) を置く。
減量は一度だけで、以後は退院まで減量のまま (その後の値の揺れで増量に戻さない)。

## 決定論

純粋な YAML lookup + ルール dispatch。RNG は消費しない — MAR の
時刻は固定 (`daily_times`)、投与看護師は order id の安定関数
(`stable_nurse`)。
(patient, encounter, admission_dx) の組が固定であれば、出力は run 間で
byte-identical である。

## 依存

- `clinosim.types.encounter` (`Order` / `OrderType` / `OrderStatus` —
  builder は実際の `Order` dataclass を emit する)
- `clinosim.modules.drug_safety.engine.check_candidate_against_active`
  (有効な薬剤とのペアチェック。失敗は握りつぶされるため、
  drug_safety のエラーで予防投与が阻害されることは無い)
- `clinosim.modules.order.placed_order_mar` — `daily_times`、
  `stable_nurse`、`administrations_for` (enricher の MAR 行)、
  `clinosim.modules.order.absolute_dose.is_continuous_infusion`
- `clinosim.codes.drugs.medication_matches`、
  `clinosim.datafiles.load_data_yaml`、
  `clinosim.locale.localized` (`language_slot`, `localized_field`)
- サードパーティ: pydantic (`_ProphylaxisRules`, `_SkipRule` が load
  時に rules yaml を検証)。

## 定数と設定

`reference_data/prophylaxis_rules.yaml`:
- `dvt_prophylaxis` ブロック: LOS 閾値、intent 文、国別の `regimens`
  (薬剤 / 用量 / 経路 / 頻度 / `administration_hours` (MAR の投与時刻、Issue #2607) /
  任意の `renal_adjustment`: `crcl_below_ml_min` と減量後の `dose_quantity`、Issue #3449)
- `creatinine_clearance` ブロック: Cockcroft-Gault の項 (年齢オフセット、分母、
  女性係数、クレアチニン単位)
- `skip_conditions` ブロック: 5 ルール (治療量抗凝固 / 活動性出血 /
  周産期の分娩 / 活動性 DVT-PE 治療 / 小児年齢 gate)。薬剤 needle、
  ICD prefix、または `pediatric_age_ceiling` (18) を持つ。
  drug_safety のペアチェックはコードのみ (yaml ブロック無し)。

スキーマレベルの指針: すべての skip 条件は臨床的根拠を記述しなければ
ならず (MUST)、`engine.should_skip_dvt_prophylaxis` 内のコードに対応
しなければならない (MUST)。新しい skip 条件の追加は 2 段階の変更
(yaml + Python dispatch) であり、yaml だけではルールは有効化されない。

## ディレクトリ構造

```
clinosim/modules/prophylaxis/
├── __init__.py            # public API re-export
├── engine.py              # rule loader + skip dispatch + order builder
├── renal_dose.py          # Cockcroft-Gault、クレアチニン系列、用量期間 (純関数)
├── enricher.py            # POST_ENCOUNTER order 75 entrypoint + 日次 MAR 行
├── reference_data/
│   └── prophylaxis_rules.yaml
├── README.md
└── README.ja.md           # 本ファイル
```

## Enricher 配線

`clinosim/simulator/enrichers.py` に以下で登録:

- Stage: POST_ENCOUNTER
- Order: 75 (`device` 70 の後、`hai` 80 の前)
- Sub-seed: `0x5052` ("PR") が
  `clinosim/seeding.py::ENRICHER_SEED_OFFSETS` に予約されているが、
  enricher は RNG を消費せず、これを読まない
- Enabled: always-on (DVT 予防が普遍的な標準治療であることに合わせる)

## Output surface

- 対象となる encounter ごとに、`record.orders` に `Order` dataclass が
  1 件追記される。order は新たな adapter 無しに標準の FHIR
  `MedicationRequest` builder を通って流れる。
- `record.medication_administrations` に order の日次
  `MedicationAdministration` 行 (status `given`、`administered_by`
  設定済み) が追記され、FHIR `MedicationAdministration` として emit
  される。

## テスト

Unit test: `tests/unit/test_prophylaxis.py` が以下をカバー
- 短 LOS / 非入院 encounter → order なし
- 治療量抗凝固中の患者 → 正しい reason で skip
- 活動性出血の診断 → skip
- 分娩の診断 (O 章 / Z37 / Z38) → skip
- 活動性 DVT/PE の診断 → skip (自身の治療が予防を置き換える)
- 小児 (18 歳未満) の入院 → skip (Issue #1276, #3082)
- 慢性 aspirin / encounter 内 NSAID → drug_safety ペア経由で skip (Issue #1087)
- 通常の J18 肺炎 IMP 48 時間以上 → order を emit

`tests/unit/test_prophylaxis_renal_dose_3449.py` は Cockcroft-Gault の値、US の
40 mg / 30 mg の CrCl 別用量、クレアチニン上昇による order 分割 (減量は一度、回復しても維持)、order 期間ごとの
MAR 用量、JP のヘパリンレジメンをカバーする。

## Ownership

2026-09-04。Issue: #1071。

英語版: [`README.md`](README.md)。
