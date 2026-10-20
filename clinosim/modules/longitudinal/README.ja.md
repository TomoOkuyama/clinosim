# `clinosim.modules.longitudinal` — 患者状態の年次 trajectory engine

## 目的

Issue #1695 以前は、`glycemic_trajectory` / `disease_stage_history` / `_advance_glycemic_trajectory` といった属性ごと・aging pass ごとの trajectory コードが散在していた。この module はそれらを 1 本の engine に集約し、少数の数学パターン (AR(1) / Markov / event) を属性別 yaml に適用する形で記述する。alive な人物 1 人・sim 年 1 年ごとに `YearSnapshot` が 1 件 `PersonRecord.longitudinal_history` に書き込まれ、encounter emit 側は `state_at(person, when)` でその年のスナップショットを引く。

Phase 1 (本リリース) は engine 本体と最初の属性 (HbA1c AR(1)) を含む。Phase 2 で Markov transition (CKD / CCS / NYHA / CDR / GOLD)、Phase 3 で event firing (DM 合併症 onset、治療エスカレーション、BMI drift) を追加する。

## スコープ

- **担当**: `YearSnapshot` dataclass、trajectory の 3 pattern (AR(1) 連続・Markov stage transition・event firing)、属性別 yaml loader と依存グラフの topological sort、`advance_one_year` / `state_at` / `initial_snapshot` の 3 エントリ、Layer-1 seed + aging driver からの呼び出し。
- **担当外**: encounter 内の sub-year 補間 (Phase 4 以降)、死亡 trajectory (`aging._condition_reactive_mortality` が担当)、小児 growth chart (`anthropometric_reference.yaml` + per-encounter FHIR anthropometric emit が担当)。

## 公開 API

```python
from clinosim.modules.longitudinal import (
    YearSnapshot,           # 年次状態コンテナ
    advance_one_year,       # (person, year, year_rng) -> 新 YearSnapshot
    state_at,               # (person, when) -> YearSnapshot
    initial_snapshot,       # (person, year, init_rng) -> 初回 YearSnapshot
)
```

`patterns/` (AR(1))、`loader.py` (yaml → `AttributeSpec`)、`snapshot.py` (dataclass) は内部実装で、3 つの entry 関数が安定した契約。

## 決定性

- 毎年 1 本の `np.random.Generator` を caller が渡す (`advance_population` / `generate_population`)。属性は `depends_on` の topological order で逐次 draw。Phase 1 では内部に別の sub-seed namespace を作らない。
- `aging_sub_seed(person_id, year, "longitudinal")` が年次 generator を seed、`aging_sub_seed(person_id, base_year, "longitudinal:init")` が Layer-1 init を seed。
- `state_at(person, when)` は純関数 (RNG なし、年単位 O(1) lookup)。
- `advance_one_year` は duplicate year / backward year で `ValueError` — 単調性契約。

## 依存

- `clinosim.modules.longitudinal.patterns` — pattern registry。
- `clinosim.modules.longitudinal.loader` — yaml → `AttributeSpec`。
- `clinosim.types.population.PersonRecord` — mutation target。
- `clinosim.locale.shared.longitudinal/` — 属性別 yaml。
- `pydantic` — yaml schema 検証。
- `numpy` — RNG + math。

## データファイル

`clinosim/locale/shared/longitudinal/` 配下の属性別 yaml:

- `hba1c_trajectory.yaml` — E11 / E10 成人向け HbA1c AR(1) latent。DCCT/EDIC、ADVANCE、Wu 2023 meta-analysis で calibrate。詳細は yaml 内の `source:` ブロック。

Phase 2 / 3 では追加の yaml が同ディレクトリに追加される。loader は全 `*.yaml` を glob。

## caller 統合

- `clinosim.modules.population.engine.generate_population` — Layer-1 生成時に全 alive 人物で `initial_snapshot` を呼ぶ。
- `clinosim.modules.population.aging.advance_population` — 既存 aging pass 完了後に `advance_one_year` を 1 人 1 年 1 回。
- `clinosim.modules.physiology.engine.derive_lab_values` — `hba1c_latent` を `state_at(person, when).continuous["hba1c"]` から読み、yaml の per-encounter noise (sigma 0.20 %) を overlay。
- `clinosim.modules.patient.activator._derive_chronic_conditions` — DM stage 文字列を当該年スナップショットから構築。

## 関連 module

- `clinosim.modules.population.aging` — DM 以外の aging pass (`_annual_chronic_onset` 等) を保持。
- `clinosim.modules.physiology.engine` — HbA1c / glucose emit。
- `clinosim.modules.patient.activator` — Layer-2 PatientProfile 構築。

## テスト

`tests/modules/longitudinal/` 配下 (10 ファイル、合計 60+ テスト)。詳細は英語 README 参照。

## 設計ドキュメント

[`docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md`](../../../docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md) に Phase 1-3 の全体設計。
