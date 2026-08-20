# `clinosim.modules.pediatric` — 小児 encounter 発生

## 概要

年齢に応じて小児 encounter (well-child / 予防接種 / 小児 acute /
adolescent 行動) を年間 healthcare calendar に emit する。
Issue #760 META 対応: population sampler は US Census の under-20 年齢
重みを正しく反映しているのに、emitted cohort では成人が大部分を占める
(成人向け disease incidence YAML が pediatric 患者に対してほぼ発火しない
ため) というギャップを **encounter-emission layer** で埋め、年齢帯別
pediatric 訪問 schedule を追加する。

## Scope

- **In scope**: pediatric encounter registry YAML の load、load 時の
  schema validation、(person, year) ペアに対する caller 供給
  per-person サブ RNG での `LifeEvent` 生成。現在登録済みの encounter
  ファミリ: well-child (infant / early / school)、予防接種 (infant /
  kindergarten / adolescent)、pediatric acute (bronchiolitis、
  otitis media、URI × 3 年齢帯)、pediatric 傷害 (school /
  adolescent)、pediatric 行動 (adolescent)。
- **Out of scope**: 新生児 ICU-level physiology (別 campaign)、
  成人 encounter engine 本体 (本モジュールは既存 population calendar
  loop に plug-in する)、emit される `disease_id` 各値に対応する
  disease spec ([`clinosim.modules.disease`](../disease/README.md)
  配下の YAML)。

## Public API

`__init__.py` は docstring のみ。呼び出し側は `calendar` から直接
import:

```python
from clinosim.modules.pediatric.calendar import (
    load_pediatric_schedule,     # (path=None) -> {encounter_key: entry_dict}
    generate_pediatric_events,   # (person, year, prng, schedule=None) -> list[LifeEvent]
)
```

`load_pediatric_schedule` は load 時に file を validate し、schema
違反 (必須 field 欠落、`visits_per_year` が list でない、`age_min >
age_max`、`encounters` top-level が dict でない) はすべて `ValueError`
を raise。`generate_pediatric_events` は schedule が空、または person
の年齢がどの entry の band にも一致しないときに no-op。

## 決定論

- 本モジュールは **master RNG を使わない**。
  `generate_pediatric_events` は caller
  (`generate_healthcare_calendar` の per-person spawn 済み
  `np.random.Generator`) から `prng` を受け取るため、YAML 編集の
  影響は該当 pediatric 患者の下流 stream 位置のみに閉じ、無関係な
  成人には波及しない。
- `load_pediatric_schedule` は意図的に **`@lru_cache` 無し** —
  test の hot-reload に配慮。反復コストが気になる caller は自身で
  cache する。

## 依存

- `numpy` — `np.random.Generator` (`prng.choice`, `prng.integers`)。
- `yaml` — YAML パーサ。
- `clinosim.modules.population.engine` — `LifeEvent`
  (`generate_pediatric_events` 内で遅延 import)。
- import 時点では他の `clinosim.modules.*` に依存しない。

## 定数と設定

[`reference_data/pediatric_schedule.yaml`](reference_data/pediatric_schedule.yaml)
は登録済みの encounter を単一 `encounters:` map に格納する。各 entry:

| キー | 意味 |
|---|---|
| `age_min` | 含む下限 (歳)。 |
| `age_max` | 含む上限 (歳)。 |
| `visits_per_year` | 非空 `list[int]` — 患者 × 年ごとに uniform sampling し patient 間の分散を与える。 |
| `encounter_type` | `"outpatient"` / `"emergency"` / `"inpatient"` — engine dispatch key。 |
| `disease_id` | engine dispatch で visit の clinical protocol を識別するのに再利用。 |
| `visit_reason` | human-readable、encounter の chief complaint に emit。 |

schedule 拡張は **純粋 YAML 編集** — code 変更不要。不正 entry は
load 時に `ValueError` として顕在化する。

## ディレクトリ構造

```
clinosim/modules/pediatric/
  __init__.py                     package docstring のみ
  calendar.py                     load_pediatric_schedule + generate_pediatric_events
  reference_data/
    pediatric_schedule.yaml       登録済み encounter entry
```

**`engine.py` / `enricher.py` / `audit.py` は存在しない**。
`register_builtin_enrichers` にも登録なく `ENRICHER_SEED_OFFSETS`
にも seed 未登録 — population calendar loop に hook する形態。

## 配線

Integration は
[`clinosim/modules/population/engine.py`](../population/engine.py)
(`L807-815` 付近):
`generate_healthcare_calendar` が per-person spawn 済み `prng` を
渡して `generate_pediatric_events` を呼び、返却 `LifeEvent` list を
calendar `events` list に merge する。以降のパイプラインは
pediatric event を他の calendar event と同等に扱う。

## テスト

```bash
pytest tests/unit/test_pediatric_calendar.py -q
```

カバー範囲: loader の schema validation (空 schedule の round-trip、
malformed entry で fail-loud) と `generate_pediatric_events` の挙動
(空 schedule で no-op、一致 entry がある場合の event 数一致)。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
