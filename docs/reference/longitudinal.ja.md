# 経年状態進展 (Longitudinal state evolution)

clinosim 0.6.5 は年次 trajectory engine を搭載し、各生存患者の
臨床状態をシミュレーション期間にわたって進展させる — HbA1c は
AR(1) で drift し、慢性 staging ladder は Markov 遷移で進行、
治療はガイドライン trigger で escalation、新規慢性疾患は年齢 /
性別 / 併存疾患 yaml に対して発症する。各 encounter emit site
(lab 値、慢性薬リスト、TNM stage、GOLD / NYHA / CKD stage、入院
疾患活性化) は毎回静的分布から resample するのではなく、
`state_at(person, when)` 経由で年マッチした `YearSnapshot` を読む。

英語版: [`longitudinal.md`](longitudinal.md)。

## 1. 現在搭載されているもの

Phase 4a-4d 機能は 2026-10-20〜2026-10-21 に landed し、
[`clinosim/locale/shared/longitudinal/`](https://github.com/TomoOkuyama/clinosim/tree/master/clinosim/locale/shared/longitudinal/)
配下の属性別 yaml 宣言に対して 1 つのエンジンで合成される。

| パターン | Driver yaml | 内容 |
|---|---|---|
| **AR(1) 連続 latent** | `hba1c_trajectory.yaml` (他に `labs/ldl_trajectory.yaml`、`vitals/sbp_trajectory.yaml`、`anthropometry/bmi_drift.yaml`) | E11 / E10 成人の within-individual HbA1c drift (phi 0.75、DCCT/EDIC、UKPDS 10y、Wu 2023 meta-analysis で校正)。encounter 単位の測定ノイズオーバーレイ (sigma 0.20 %) は emit 時に適用。廃止された `PersonRecord.glycemic_trajectory` proxy を置換。 |
| **Markov stage ladder** | `stage/<disease>.yaml` (19 ladder) | CKD (`n18`)、心不全 (`i50` → NYHA I-IV)、虚血性心疾患 (`i25` → CCS I-IV)、心房細動 (`i48` paroxysmal → persistent → permanent)、COPD (`j44` → GOLD 1-4)、認知症 (`f00` → CDR 0.5-3)、Parkinson (`g20`)、多発性硬化症 (`g35`)、アルコール性 / 線維性肝疾患、脳卒中後遺症 (`i69` / `i69_1` / `i69_3`)、6 本の癌 staging ladder (`c16` 胃 / `c18` 大腸 / `c22` 肝 / `c34` 肺 / `c50` 乳 / `c61` 前立腺) を AJCC + BCLC で。 |
| **イベント発火** | `event/<code>_onset.yaml` (30+ ファイル) | 慢性発症の年次 Bernoulli roll — DM E11 合併症 (`dm_nephropathy_e11_21`、`dm_neuropathy_e11_42`、`dm_retinopathy_e11_311`)、20+ 本の成人慢性 ICD を locale 別の rate yaml で、年齢 / 性別 gating + `has_chronic_prefix` + `requires_sex` trigger (Phase 4b.2.β) 付きでサンプリング。 |
| **治療 escalation イベント** | `med/<regimen>.yaml` | HTN 第 3 剤 / 第 4 剤 step-up (`htn_escalate_third_agent_i10`、`htn_escalate_fourth_agent_i10`)、脂質 high-intensity / ezetimibe step-up (`lipid_escalate_high_intensity_e78`、`lipid_escalate_ezetimibe_e78`)、DM SGLT2i / insulin step-up (`dm_escalate_sglt2i_e11`、`dm_escalate_insulin_e11`)。ガイドライン trigger (例: HbA1c target 超過が N 年連続) で発火。Phase 4a は DM 合併症を T2DM (E11) 限定にスコープ — T1DM (E10) は除外。 |

エンジン本体は
[`clinosim/modules/longitudinal/`](https://github.com/TomoOkuyama/clinosim/tree/master/clinosim/modules/longitudinal/):

- `engine.py` — `advance_one_year(person, year, year_rng)` + `state_at(person, when)` + `initial_snapshot(person, year, init_rng)`。
- `patterns/{ar1,markov,event}.py` — 3 本の合成可能プリミティブ。
- `loader.py` — yaml → `AttributeSpec`、`depends_on` エッジの topological sort。
- `snapshot.py` — `YearSnapshot` dataclass (`PersonRecord.longitudinal_history` に患者毎に年 1 本)。

## 2. Public API

```python
from clinosim.modules.longitudinal import (
    YearSnapshot,     # per-year state コンテナ
    advance_one_year, # (person, year, year_rng) -> new YearSnapshot
    state_at,         # (person, when) -> YearSnapshot
    initial_snapshot, # (person, year, init_rng) -> 初回 YearSnapshot
)
```

`patterns/` + `loader.py` + `snapshot.py` の内部は安定 surface で
なく、これら 4 本のエントリポイントが契約。encounter consumer は
`state_at(person, when).continuous["hba1c"]` (AR(1) latent) や
`state_at(person, when).stage["n18"]` (Markov stage) を読み、
resample しない。

## 3. 呼び出し統合

エンジンは Layer-1 seam 2 本に配線され、encounter emit site 3 本
で読まれる:

- **Layer-1 初期化** — `clinosim.modules.population.engine.generate_population`
  が生成時に全生存患者に対して `initial_snapshot` を呼ぶ。
- **年次 advance** — forward month loop
  (`clinosim/simulator/phases/_forward_loop.py`) が年の境目ごとに
  `clinosim.modules.population.aging.advance_population` を呼び、これが
  sim 年毎に全生存患者に対して `advance_one_year` を呼ぶ。
  **その年の院外死亡 draw と aging passes が `chronic_conditions` を
  finalise した後。**
- **Lab emit** — `clinosim.modules.physiology.engine.derive_lab_values`
  が `state_at(person, when).continuous["hba1c"]` を読み、yaml から
  encounter 単位の測定ノイズオーバーレイを適用。
- **慢性薬導出** — `clinosim.modules.patient.activator._derive_chronic_conditions`
  が現年の snapshot を読み DM stage 文字列を構築。
- **癌 stage emit** — oncology service line が
  `state_at(person, when).stage["<code>"]` を読み、encounter 単位の
  CIF payload の AJCC / BCLC stage field を populate。

## 4. 決定論契約

- 各年、エンジンは `advance_population` / `generate_population` から
  渡される単一の `np.random.Generator` を取る。属性別 draw は
  `depends_on` エッジの topological 順で実行。
- `aging_sub_seed(person_id, year, "longitudinal")` が `advance_one_year`
  の per-患者 per-年 generator を seed; `aging_sub_seed(person_id, base_year, "longitudinal:init")`
  が Layer-1 `initial_snapshot` を seed。両方とも決定論的 sub-RNG
  stream なので、同 seed の 2 コホートは byte-identical な longitudinal
  history を生成。
- `state_at(person, when)` は純粋 (RNG なし、年による O(1) lookup)。
- `advance_one_year` は重複または逆順の年で raise — 単調性不変条件
  は caller が守る。

## 5. チューニング / 無効化

`clinosim/locale/shared/longitudinal/` 配下の各 yaml は Pydantic
検証付きの plain config。パラメタ (例: HbA1c AR(1) phi、癌 stage
遷移確率、HTN escalation threshold) をチューニングするには yaml を
編集 — ローダは import 時に `*.yaml` を全 glob する。

特定コホートでパターンを無効化するには driver yaml を削除または
空にする (例: `dm_nephropathy_e11_21.yaml` の rate block を clear)。
サブシステム全体を無効化する CLI フラグは無い — エンジンは critical
cohort-generation path 上にあり、省略すると Layer-1 fingerprint が
変わる。

新属性を追加するには、該当サブディレクトリ (`stage/` / `event/`
/ `med/` または新 AR(1) latent 用の sibling) に新 yaml を書き、
`attribute_id`、`pattern`、`depends_on`、pattern 固有ブロックを
宣言。ローダ + topological sort が次回 import で拾う。

## 6. 設計ドキュメント

完全な phased architecture (Phase 1 shipping、Phase 2 Markov、Phase 3
event、Phase 4a-4d features):
[`docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md`](https://github.com/TomoOkuyama/clinosim/blob/master/docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md)。
Phase 別実装計画は隣の
[`docs/superpowers/plans/`](https://github.com/TomoOkuyama/clinosim/tree/master/docs/superpowers/plans/)。

## 7. 関連 reference

- [`clinosim/modules/longitudinal/README.ja.md`](https://github.com/TomoOkuyama/clinosim/blob/master/clinosim/modules/longitudinal/README.ja.md) — コントリビュータ向けモジュール README (purpose / scope / API / dependencies / testing)。
- [`oncology-obstetric-service-lines.ja.md`](oncology-obstetric-service-lines.ja.md) — stage ladder を消費する癌 AJCC/BCLC emit path。
- [`code-systems.ja.md`](code-systems.ja.md) — `event/*.yaml` trigger で使う ICD-10 code。
