# `clinosim.modules.longitudinal` — 患者状態の年次 trajectory engine

## 目的

Issue #1695 以前は、`glycemic_trajectory` / `disease_stage_history` / `_advance_glycemic_trajectory` といった属性ごと・aging pass ごとの trajectory コードが散在していた。この module はそれらを 1 本の engine に集約し、少数の数学パターン (AR(1) / Markov / event) を属性別 yaml に適用する形で記述する。alive な人物 1 人・sim 年 1 年ごとに `YearSnapshot` が 1 件 `PersonRecord.longitudinal_history` に書き込まれ、encounter emit 側は `state_at(person, when)` でその年のスナップショットを引く。

Phase 1 で engine 本体と最初の属性 (HbA1c AR(1)) を導入した。以降の Phase で Markov stage transition (CKD / COPD / 心不全 / IHD / 認知症 / 肝 / Parkinson / AF / MS / 脳卒中後遺症 / 癌 stage)、event firing (成人慢性疾患 onset、DM 合併症 onset、治療エスカレーション)、追加の AR(1) latent (BMI drift、LDL、SBP) を追加済みで、3 pattern すべて稼働している。

## スコープ

- **担当**: `YearSnapshot` dataclass、trajectory の 3 pattern (AR(1) 連続・Markov stage transition・event firing)、属性別 yaml loader と依存グラフの topological sort、`advance_one_year` / `state_at` / `initial_snapshot` の 3 エントリ、Layer-1 seed + aging driver からの呼び出し。
- **担当外**: encounter 内の sub-year 補間 (Phase 4 以降)、地域死亡 (`population.aging.advance_population` が `population.mortality` 経由で 1 人 1 年 1 回 draw)、小児 growth chart (`anthropometric_reference.yaml` + per-encounter FHIR anthropometric emit が担当)。

## 公開 API

```python
from clinosim.modules.longitudinal import (
    YearSnapshot,           # 年次状態コンテナ
    advance_one_year,       # (person, year, year_rng) -> 新 YearSnapshot
    state_at,               # (person, when) -> YearSnapshot
    initial_snapshot,       # (person, year, init_rng) -> 初回 YearSnapshot
    yearsnapshot_from_dict, # dict -> YearSnapshot (deserialise helper)
)
```

`patterns/` (`ar1.py` / `markov.py` / `event.py`、`PATTERN_REGISTRY` で dispatch)、`loader.py` (yaml → `AttributeSpec`)、`med_lookup.py` (event の `emits_meds` 薬剤名 → `chronic_medications.yaml` 由来の `HomeMedication`)、`snapshot.py` (dataclass) は内部実装で、3 つの entry 関数が安定した契約。

## 決定性

- 毎年 1 本の `np.random.Generator` を caller が渡す (`advance_population` / `generate_population`)。属性は `depends_on` の topological order で逐次 draw。`rng_isolated: true` の event yaml は共有 stream を消費せず `seeding.longitudinal_event_seed(person_id, year, event_name)` の専用 generator を使う。新規 ICD 獲得時の base 常用薬追加は patient 単位の `chronic_medication_seed` を使う。
- `aging_sub_seed(person_id, year, "longitudinal")` が年次 generator を seed、`aging_sub_seed(person_id, base_year, "longitudinal:init")` が Layer-1 init を seed。
- `state_at(person, when)` は純関数 (RNG なし、`longitudinal_history` を走査して該当年を返し、無ければ `IndexError`)。
- `advance_one_year` は空 history / duplicate year / backward year で `ValueError`。前方への年 gap は許容。

## 依存

- `clinosim.modules.longitudinal.patterns` — pattern registry。
- `clinosim.modules.longitudinal.loader` — yaml → `AttributeSpec`。
- `clinosim.types.population.PersonRecord` — mutation target。
- `clinosim.locale.shared.longitudinal/` — 属性別 yaml。
- `pydantic` — yaml schema 検証。
- `numpy` — RNG + math。

## データファイル

`clinosim/locale/shared/longitudinal/` 配下の属性別 yaml (loader は `*.yaml` を再帰 glob):

- `hba1c_trajectory.yaml` — E11 / E10 成人向け HbA1c AR(1) latent。DCCT/EDIC、ADVANCE、Wu 2023 meta-analysis で calibrate。詳細は yaml 内の `source:` ブロック。
- `anthropometry/bmi_drift.yaml`、`labs/ldl_trajectory.yaml`、`vitals/sbp_trajectory.yaml` — 追加の AR(1) latent。
- `stage/*.yaml` — Markov stage 属性 19 件。
- `event/*.yaml` — event 属性 35 件 (慢性疾患 onset `*_onset.yaml` 32 件 + DM 合併症 3 件)。
- `med/*.yaml` — 治療エスカレーション event 6 件 (DM / HTN / 脂質)。

## caller 統合

- `clinosim.modules.population.engine.generate_population` — Layer-1 生成時に全 alive 人物で `initial_snapshot` を呼ぶ。
- `clinosim.modules.population.aging.advance_population` — 地域死亡 draw と残りの aging pass の後に `advance_one_year` を 1 人 1 年 1 回 (Markov 遷移率に `multiplier_fn=_comorbidity_multiplier` を渡す)。
- `clinosim.modules.physiology.engine.derive_lab_values` — `hba1c_latent` を `state_at(person, when).continuous["hba1c"]` から読み、yaml の per-encounter noise (sigma 0.20 %) を overlay。
- `clinosim.modules.patient.activator._derive_chronic_conditions` — DM stage 文字列を当該年スナップショットから構築。

## 関連 module

- `clinosim.modules.population.aging` — 残りの aging pass (`_stroke_sequela_promotion`、`_allergy_drift`) と地域死亡 draw (`population.mortality.draw_community_death`) を保持。旧 `_annual_chronic_onset` / `_disease_progression` は本 engine の event / Markov 属性に移行済み。
- `clinosim.modules.physiology.engine` — HbA1c / glucose emit。
- `clinosim.modules.patient.activator` — Layer-2 PatientProfile 構築。

## テスト

`tests/modules/longitudinal/` 配下 (39 ファイル)。詳細は英語 README 参照。

## 設計ドキュメント

[`docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md`](../../../docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md) に Phase 1-3 の全体設計。
