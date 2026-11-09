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
  disease spec ([`clinosim.modules.disease`](../disease/README.ja.md)
  配下の YAML)。

## Public API

`__init__.py` は docstring のみ (`__all__ = []`)。呼び出し側は `calendar` から直接
import:

```python
from clinosim.modules.pediatric.calendar import (
    load_pediatric_schedule,     # (path=None) -> {encounter_key: entry_dict}
    generate_pediatric_events,   # (person, year, prng, schedule=None, country=None) -> list[LifeEvent]
    place_vaccination_visit,     # 接種期間内の予防接種受診日 (Issue #2974)
    pediatric_presentation,      # (visit_id) -> Presentation | None (急性受診のみ)
    Presentation,                # 急性受診 1 件の臨床像を表す pydantic model
)
```

`pediatric_presentation(disease_id)` は急性受診の `Presentation`
(予防受診なら `None`) を返す。外来シミュレータはこれを使い、受診時の
vitals、stream を消費しない発熱 / 非発熱状態 (`Presentation.visit_state`、
encounter id に対する SHA Bernoulli)、対応する状態変数への影響、
持ち帰り処方を決める。

`load_pediatric_schedule` は load 時に file を validate し、schema
違反 (必須 field `age_min` / `age_max` / `visits_per_year` /
`encounter_type` / `disease_id` の欠落、`visits_per_year` が list で
ない or 空、`age_min > age_max`、`encounters` top-level が dict でない)
はすべて `ValueError` を raise。`generate_pediatric_events` は
年齢を `year - date_of_birth.year` (無ければ static `person.age`) で
算出し、schedule が空、年齢が `> 18` or `< 0` (未出生)、または
per-person 参加 draw `prng.random() < person.care_seeking_threshold`
(default 0.20) でその年全体を skip する場合 (Issue #922) に `[]` を
返す。一致 entry ごとに
`LifeEvent(event_type="pediatric_visit", severity=0.0,
condition_type="pediatric", protocol_source="pediatric:<key>")` を
年内に均等配置 (日付 jitter 付) で emit する。

## 決定論

- 本モジュールは **master RNG を使わない**。
  `generate_pediatric_events` は caller
  (`generate_healthcare_calendar` の per-person spawn 済み
  `np.random.Generator`) から `prng` を受け取るため、YAML 編集の
  影響は該当 pediatric 患者の下流 stream 位置のみに閉じ、無関係な
  成人には波及しない。
- `load_pediatric_schedule` は `path` 引数ごとに
  `@lru_cache(maxsize=8)` で cache される (以前は未 cache で
  per-patient calendar loop の hot spot だった)。schedule file を
  書き換える test は `load_pediatric_schedule.cache_clear()` で
  無効化する。

## 依存

- `numpy` — `np.random.Generator` (`prng.random`, `prng.choice`,
  `prng.integers`)。
- `pydantic` — schedule model `_PediatricSchedule` / `_Visit`。
- `clinosim.datafiles` — `load_data_yaml`。
- `clinosim.modules._shared` — `random_day_of_month` (visit ごとの
  日付 jitter)。
- `clinosim.modules.population.engine` — `LifeEvent`
  (`generate_pediatric_events` 内で遅延 import)。

## 定数と設定

[`reference_data/pediatric_schedule.yaml`](reference_data/pediatric_schedule.yaml)
は登録済みの encounter を `encounters:` map に、急性受診の臨床像を
`presentations:` map に格納する。`encounters:` の各 entry:

| キー | 意味 |
| --- | --- |
| `age_min` | 含む下限 (歳)。 |
| `age_max` | 含む上限 (歳)。 |
| `visits_per_year` | 非空 `list[int]` — 患者 × 年ごとに uniform sampling し patient 間の分散を与える。 |
| `encounter_type` | `"outpatient"` のみ (それ以外は model が拒否) — `LifeEvent.encounter_type` に copy。 |
| `disease_id` | `LifeEvent.disease_id` に copy。診療科解決と visit-reason lookup に使用。 |
| `visit_reason` | 任意。bilingual `{en, ja}` dict または文字列。`simulator/_setup.py::_pediatric_visit_reason` が読み、encounter の chief complaint に emit。 |
| `vaccination` | 任意、既定 `false`。接種のための受診 (理由 Z23)。国が渡されると `generate_pediatric_events` は、その国の予防接種スケジュールのうちその年に始まり年齢帯と重なる定期接種の接種期間内 (引いた日に最も近い日) に受診を移し、該当する期間がなければ受診を入れない。受診には必ず接種対象がある (`place_vaccination_visit`、Issue #2974)。乱数の引き方は変わらない。 |

`presentations:` の各 entry は `encounters:` の `disease_id` をキーとする
(未知のキーは load 時に失敗):

| キー | 意味 |
| --- | --- |
| `vitals` | 受診時に測定する vital field の非空 list。 |
| `febrile_probability` | 受診が発熱である確率 (0–1)。0 より大きい場合は `state_impact.febrile` block が必須。 |
| `state_impact` | 任意。`{febrile, afebrile}` → `{state_var: delta}`。状態変数名は physiology の canonical state var であること。 |
| `prescriptions` | 任意。持ち帰り処方の list: `drug_id` (薬剤カタログに存在すること)、`dose`、`route`、`frequency`、`duration_days` (年齢帯 → 正の日数)。 |

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

## Enricher 配線

該当なし — 本モジュールは population calendar loop に直接 hook する
形態で、enricher 登録は行わない。`register_builtin_enrichers` に
登録なく、`ENRICHER_SEED_OFFSETS` にも seed 未登録。

Integration は
[`clinosim/modules/population/engine.py`](../population/engine.py)
(`generate_healthcare_calendar`):
`generate_healthcare_calendar` が per-person spawn 済み `prng` と
コホートの国を渡して `generate_pediatric_events` を呼び、返却 `LifeEvent` list を
calendar `events` list に merge する。以降のパイプラインは
pediatric event を他の calendar event と同等に扱う。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
| --- | --- | --- |
| Population calendar loop | [`clinosim/modules/population/engine.py`](../population/engine.py) (`generate_healthcare_calendar` 内) | (person, year) ごとに `generate_pediatric_events(person, year, prng, country=country)` を呼び、返却 `LifeEvent` を calendar `events` list に追加。 |
| Healthcare-calendar dispatch | [`clinosim/simulator/phases/_healthcare_calendar.py`](../../simulator/phases/_healthcare_calendar.py) | `event_type == "pediatric_visit"` を外来受診に振り分け (診療科は `resolve_outpatient_department`、主訴は `_pediatric_visit_reason(disease_id)`)。 |
| Visit-reason lookup | [`clinosim/simulator/_setup.py`](../../simulator/_setup.py) (`_pediatric_visit_reason`) | `load_pediatric_schedule()` から `visit_reason` を読む。 |
| Outpatient encounter | [`clinosim/simulator/outpatient.py`](../../simulator/outpatient.py), [`outpatient_dept.py`](../../simulator/outpatient_dept.py) | `visit_type == "pediatric_visit"` 分岐。`pediatric_presentation` が急性受診の vitals・発熱状態・処方を供給。 |

## テスト

```bash
pytest tests/unit/test_pediatric_calendar.py -q
```

カバー範囲: loader の schema validation (空 schedule の round-trip、
malformed entry で fail-loud) と `generate_pediatric_events` の挙動
(空 schedule で no-op、一致 entry がある場合の event 数一致)。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
