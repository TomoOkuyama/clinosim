# `clinosim.modules.natural_death` — 生命表からの自然死サンプリング (Issue #1114 C11g-2)

## 目的

母集団生成時に、各人物に対して国別の完全生命表 (US CDC / JP MHLW) から
自然死日を 1 度だけサンプリングし、`PersonRecord.date_of_death` に
セットする。下流のイベント生成器が `PersonRecord.is_alive_at(t)` で
gate できる。C11g-2 は「サンプリング側」のみ担い、実際の filter 配線は
後続 PR (C11g-3、#1114 の 5-part 分解) が実施する。

## Scope

- **In scope**: `locale/shared/actuarial_life_table.yaml` からの
  age × sex × country 年間 qx 参照; sim 窓の各年ごとの
  per-person Bernoulli; 初発火年からのランダム日抽出;
  `sim_log` へのコホート死亡率サマリ出力。
- **Out of scope**: `is_alive_at(t)` を使ったイベント dispatcher の
  filter 配線 (C11g-3); 自然死患者の FHIR `Patient.deceasedDateTime`
  emit (C11g-4/5); 院内死亡 (既存
  [`discharge_gate.py`](../../simulator/discharge_gate.py) が
  `PatientProfile.deceased` を flip する経路)。

## Public API

```python
from clinosim.modules.natural_death import sample_natural_deaths  # POST_POPULATION enricher entrypoint
```

登録先: [`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)、
`POST_POPULATION order=20` (identity=10 の直後、event 生成の直前)。
US / JP どちらも常時有効。actuarial YAML が欠けている場合は no-op。

## Determinism

- **Sub-seed offset**: `0x4E44` (`"ND"`)、
  [`clinosim/seeding.py`](../../seeding.py) に登録。
  `derive_sub_seed(master_seed, offset, person_id)` で person 毎に
  分離された sub-RNG を使うため、メイン sim ストリームには影響しない
  (AD-16)。
- Byte-shape: 新規 per-person RNG cursor を 1 個追加。
  非-death 系のイベント stream (calendar / inpatient / perinatal / …)
  は C11g-2 前と byte-identical。

## Data source

- `clinosim/locale/shared/actuarial_life_table.yaml`
  - US 2020: CDC NCHS NVSR 71-01 Table 2/3 の 1歳刻み qx を 5年帯で平均。
  - JP 2020: 厚生労働省 第23回生命表 (完全生命表) 生命表(男)+(女)、
    同 5年帯構造。
- `provenance` block に URL を保持。後年の生命表更新時に grep 可能。

## Sampling model

各 person P に対して:

1. sim 窓の各年 `y` を巡回 (`config.time_range`)。
2. `age_at_y = P.age + (y - sim_start_year)` を算出。
3. 5年帯 lookup で `qx(country, sex, age_at_y)` を取得。
4. P の sub-RNG で `qx` に対して Bernoulli。
5. 最初に発火した年を死亡年とし、その年の中で一様に日を選択
   (sim 窓の境界内 clamp)。
6. `P.date_of_death` にセット。以後年 loop を抜ける。

一度も発火しなかった人は `date_of_death = None` のまま、
sim 窓全期間生存扱い。

## C11g-2 が「まだ」やらないこと

- `date_of_death` を持つ患者への encounter emit は依然として
  従来通り生成される (`generate_monthly_events` /
  `generate_healthcare_calendar` / 慢性 followup / 定期健診
  はまだ naive `is_alive` boolean を見ている)。C11g-3 で
  日付対応 filter を配線。
- FHIR `Patient.deceasedDateTime` は `date_of_death` から
  populate されない。院内死亡は既存 `PatientProfile.deceased`
  ブールで discharge_gate から反映される。C11g-4/5 で
  経路を統合。
- `Observation-death-summary` や SSDMF 相当の FHIR
  resource emit も未対応。

部分配線 (フィールドは埋めるが一部のみ filter する) は
#1114 の defer コメントが警告した「impossible data」regression
に直結するため、C11g-2 の scope を意図的に狭く保つ。

## 検証

- Unit test: `tests/unit/test_natural_death.py` (9 cases)。
  `is_alive_at(t)` 正常系、同一 seed の決定性、コホート死亡率が
  現実バンド (8-40 /kyr、一様年齢 1000 人 cohort。CDC 8.7 は US
  人口ピラミッド重み付けで、この test cohort は一様なので老年裾に
  重みが厚くバンドを広めに取っている) 内、死亡日 sim 窓内、
  年齢単調性 (elderly > 5× young)。
- Cohort log: sim ごとに
  `{"module": "natural_death", "event": "cohort_mortality_sampled",
  "n_total": ..., "n_dead": ..., "per_kyr": ...}` を emit、grep 可能。

## 関連

- [`clinosim/modules/discharge_gate.py`](../../simulator/discharge_gate.py)
  — 院内死亡経路 (`PatientProfile.deceased`)。
- Issue [#1114](https://github.com/TomoOkuyama/clinosim/issues/1114)
  — C11g 5-part 分解 tracker。
- [`clinosim/locale/shared/actuarial_life_table.yaml`](../../locale/shared/actuarial_life_table.yaml)
  — qx データソース (C11g-1、PR #1147)。
