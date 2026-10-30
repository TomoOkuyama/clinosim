# `clinosim.modules.prophylaxis`

48 時間以上の入院に対する標準治療としての VTE (DVT) 薬物的予防。

## 概要

実際の病棟プロトコルでは、48 時間以上入院する全患者に VTE 予防の
評価が求められ、禁忌の無い大多数に対する標準治療レジメンは
Enoxaparin 40 mg SC 1 日 1 回である。本 module 以前は、32 の疾患
YAML のうち 14 しか `supportive_orders:` に DVT 予防を載せておらず、
48 時間以上の IMP encounter の約 40 % が予防投与なしになっていた
(US p=2000 seed=500 baseline: 103 件中 40 件が未カバー)。

## Scope

**In scope**: 48 時間以上の IMP encounter に対する DVT (VTE) 薬物的
予防 Order の emit。以下の場合はルールベースで skip する: 患者が
小児年齢上限 (既定 15) 未満、既に治療量の抗凝固療法中 (warfarin /
DOAC / heparin 持続点滴)、入院時診断が活動性出血 / 最近の出血性
脳卒中 / 消化管出血 / 分娩 / 活動性 DVT-PE の治療、または
Enoxaparin が有効な薬剤と major / 禁忌ペアを形成する
(`drug_safety.check_candidate_against_active`、Issue #1087)。

**Out of scope (post-MVP)**:
- ストレス潰瘍予防 (ICU での PPI) — 別プロトコル。
- VAP bundle (頭部挙上、クロルヘキシジン口腔ケア) — nursing
  enricher の担当。
- 出血禁忌の患者に対する機械的予防 (間欠的空気圧迫法) への
  fallback — 先送り。現行設計では単に skip する。
- 予防投与 order に対する MedicationAdministration 行 —
  MedicationRequest 単体が load-bearing な FHIR signal であり、MAR
  生成は sim の詳細度が必要とする場合に既存の daily-loop 経路で
  行われる。

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
orders = build_dvt_prophylaxis_orders(record=cif_record)
# → [Order(order_id="ORD-<encounter_id>-DVT-01", display_name="Enoxaparin", ...)]
```

## 決定論

純粋な YAML lookup + ルール dispatch。RNG は消費しない。
(patient, encounter, admission_dx) の組が固定であれば、出力は run 間で
byte-identical である。

## 依存

- `clinosim.types.encounter` (`Order` / `OrderType` / `OrderStatus` —
  builder は実際の `Order` dataclass を emit する)
- `clinosim.modules.drug_safety.engine.check_candidate_against_active`
  (有効な薬剤とのペアチェック。失敗は握りつぶされるため、
  drug_safety のエラーで予防投与が阻害されることは無い)
- サードパーティ: PyYAML のみ。

## 定数と設定

`reference_data/prophylaxis_rules.yaml`:
- `dvt_prophylaxis` ブロック: 薬剤 / 用量 / 経路 / 頻度 / LOS 閾値
- `skip_conditions` ブロック: 5 ルール (治療量抗凝固 / 活動性出血 /
  周産期の分娩 / 活動性 DVT-PE 治療 / 小児年齢 gate)。薬剤 needle、
  ICD prefix、または `pediatric_age_ceiling` (15) を持つ。
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
├── enricher.py            # POST_ENCOUNTER order 75 entrypoint
├── reference_data/
│   └── prophylaxis_rules.yaml
└── README.md              # this file
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

## テスト

Unit test: `tests/unit/test_prophylaxis.py` が以下をカバー
- 短 LOS / 非入院 encounter → order なし
- 治療量抗凝固中の患者 → 正しい reason で skip
- 活動性出血の診断 → skip
- 分娩の診断 (Z37/Z38) → skip
- 活動性 DVT/PE の診断 → skip (自身の治療が予防を置き換える)
- 小児 (15 歳未満) の入院 → skip (Issue #1276)
- 慢性 aspirin / encounter 内 NSAID → drug_safety ペア経由で skip (Issue #1087)
- 通常の J18 肺炎 IMP 48 時間以上 → order を emit

## Ownership

2026-09-04。Issue: #1071。

英語版: [`README.md`](README.md)。
