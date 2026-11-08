# C refactor 後レイアウト — narrative + simulator + population engine 分割

2026-10-15 〜 2026-10-26 の間、3 本の god-class ファイルが 26 PR の
cascade (C1a-C1s + C2a-C2f + C3a-C3e) で属性別モジュールに分解された。
分割後も façade ファイルが全ての移動シンボルを re-export するため、
分割前の全 import path は byte-identical で動作し続ける。本ページは
コントリビュータが「特定の挙動が今どこにあるか」を見つけるための
地図である。

英語版: [`post-c-refactor-split.md`](post-c-refactor-split.md)。

## 1. スコアボード

| god-class ファイル | 分割前 LOC | 分割直後 LOC | 削減 | Series |
|---|---:|---:|---:|---|
| `clinosim/modules/document/narrative/template_generator.py` | 6539 | 1399 | **-78.6 %** | **C1** (`a`-`s`) |
| `clinosim/simulator/engine.py` | 2059 | 632 | **-69.3 %** | **C2** (`a`-`f`) |
| `clinosim/modules/population/engine.py` | 2066 | 1157 | **-44.0 %** | **C3** (`a`-`e`) |
| **合計** | **10664** | **3188** | **-70.1 %** | |

分割直後の列は cascade 完了時点のサイズで、その後の作業で各ファイルは
変化している (例: `simulator/engine.py` は Issue #2169 の forward loop
refactor 後 459 LOC)。

全 26 extraction PR について `scripts/engine-fingerprint.sh` の
US p=500 seed=42 + JP p=500 seed=17 で byte-identical 検証済
(full cohort sha256
`0184a8b382990915e2e04ca6c94bce2d24e105b39d6be827f705c461f8f621a8`)。

## 2. C1 — narrative template 分割 (12 section builder + 4 共有 helper)

**Façade**: `clinosim/modules/document/narrative/template_generator.py`
(分割後 1399 LOC)。cascade 時点では以下の全シンボルが façade から
re-export されていた。Issue #2531 以降、section builder は re-export も
ラップもされず、section registry に自己登録する (下の「パターン」参照)。
façade は一部の共有 helper について `_` 付きの薄い delegator メソッド
(`TemplateNarrativeGenerator()._compose_<name>()`、`_resolve_*`、`_ed_*`)
を残している。

### Section builders — `renderers/section_builders/`

12 ファイル。各ファイルは free function `(generator, ctx) -> (text, facts)`
を定義し、`section_builders/_registry.py` の `@section("<name>")`
デコレータで登録する。

| ファイル | 内容 | Phase |
|---|---|---|
| `assessment_and_plan.py` | ドキュメント種別横断の A&P セクション | C1m |
| `care_plans.py` | ACP + NCP + RP (31 メソッド) | C1e |
| `chief_complaint.py` | CC resolver + emit | C1n |
| `discharge_summary.py` | DS セクションクラスタ | C1i |
| `ed_note.py` | ED note セクションクラスタ | C1j |
| `hpi.py` | HPI 構成 + `_build_hpi_core` | C1o |
| `jp_clins.py` | JP-CLINS 3 Composition profiles | C1g |
| `mortality.py` | DC + DDS 死亡 narrative | C1f |
| `nursing.py` | 看護師 shift / assessment / discharge | C1h |
| `op_pn_notes.py` | Operative + Procedure note クラスタ (17 メソッド) | C1d |
| `outpatient_soap.py` | 外来 SOAP (4 builder + 10 composer; 1116 LOC で最大) | C1l |
| `patient_history.py` | PMH / medications / allergies / FH / SH | C1k |

### 共有 helper — `renderers/`

C1p-s 以降の 4 本の共有クラスタモジュール。section builder の後ろ盾。
モジュールレベルの関数名は公開名 (先頭 `_` なし) で、
`template_generator.py` は大半について `_` 付きの delegator メソッドを持つ。

| ファイル | 内容 |
|---|---|
| `_resolvers.py` | `resolve_physical_exam`、`resolve_daily_trajectory`、`resolve_daily_trajectory_with_source`、`generic_trajectory`、`resolve_discharge_instructions` |
| `_composers.py` | `compose_progress_subjective_from_state`、`compose_progress_assessment_from_state`、`compose_progress_plan_from_state`、`pick_stable_progress_phrase`、`compose_today_vitals_line`、`compose_pe_vitals_line`、`apply_cc_pe_consistency`、`compose_vital_signs_line` |
| `_ed_helpers.py` | `get_ed_note_template`、`ed_disposition_reason`、`ed_triage_level` |
| `_shared_helpers.py` | `pydantic_day_findings_to_dict`、`format_physical_exam`、`primary_surgical_procedure`、`resolve_procedure_display` |

B8 pilot + C1a-c の pre-section-builder 時代の renderer も
`renderers/` 配下に居る: `ed_triage_note.py`、`nursing_shift_note.py`、
`progress_note.py`、`composition_sections.py`。

### パターン

```python
# renderers/section_builders/hpi.py
from clinosim.modules.document.narrative.renderers.section_builders._registry import section


@section("hpi")
def build_hpi(generator, ctx):
    ...
    return text, facts
```

`renderers/composition_sections.py` は文書 spec の各 section 名を registry
で引き (まず `@section(name, document_type=...)` で登録された
`document_section_builders()`、次に `section_builders()`)、generator と
context を渡して builder を呼ぶ。未登録の section には汎用 fallback 文言が
入る。section の追加はデコレータ付き関数 1 つで済み、`template_generator.py`
には何も足さない。

直接 free-function import も動作:

```python
from clinosim.modules.document.narrative.renderers.section_builders.hpi import (
    build_hpi,
)
```

**narrative バグ修正時**: 該当 section の `@section("<name>")` 関数を
`renderers/section_builders/<file>.py` で探す — それが本体。(Issue #2531
以前は façade に section ごとの 2 行 `_build_<section>` delegator があったが、
削除済。)

## 3. C2 — simulator engine 分割 (setup + dispatch + 4 phase)

**Façade**: `clinosim/simulator/engine.py` (分割後 632 LOC)。
`run_beta` + `run_forced` は top-level entry のまま。

### 抽出モジュール

| ファイル | 内容 | Phase |
|---|---|---|
| `clinosim/simulator/_setup.py` | 11 シンボル — `_load_health_screening_visit_reason`、`_HEALTH_SCREENING_VISIT_REASON`、`_HEALTH_SCREENING_VISIT_REASON_FALLBACK`、`_pediatric_visit_reason`、`_parse_time_range_bound`、`_TimeRangeBounds`、`_activate_cached_person`、`_derive_time_range_bounds`、`_load_hospital_ops`、`_resolve_pop_size`、`_load_prev_admission_cache` | C2a |
| `clinosim/simulator/_dispatch.py` | 病院イベント dispatcher + overlap 処理 — `_find_active_inpatient_record`、`_find_overlapping_inpatient_record`、`_verify_no_actual_overlap`、`_handle_overlap_via_merge`、`_merge_disease_into_active_encounter`、`_replay_cached_admission_queue`、`_DispatchState`、`_dispatch_hospital_events` | C2b |
| `clinosim/simulator/phases/_healthcare_calendar.py` | `calendar_events_for_year`、`newborn_calendar_events`、`dispatch_calendar_event` | C2c |
| `clinosim/simulator/phases/_post_discharge.py` | `schedule_post_discharge`、`dispatch_post_discharge` | C2d |
| `clinosim/simulator/phases/_readmission.py` | `schedule_readmission`、`dispatch_readmission` | C2e |
| `clinosim/simulator/phases/_ed_slot.py` | `EDSlotSampler`、`dispatch_ed_slot` | C2f |
| `clinosim/simulator/phases/_forward_loop.py` | `ForwardContext`、`EventQueue`、`run_forward_loop` | #2169 |

Issue #2169 以降、4 つの phase はループ後の runner ではない。各 phase は
*schedule* と *dispatch* の 2 段を公開し、`run_forward_loop` が日付順の
イベントキュー 1 本で全 phase を月単位に進める (年境界 → 月次ライフ
イベント → ED 枠 → dispatch)。そのため出産で登録された新生児は、自身の
受診予定とライフイベントが作られる前に集団へ加わり、どの phase で記録
された死亡もその人の以後のイベントをすべて止める。

### なぜこの境界か (原案との差)

C2 前の計画書
[`../history/plans-archive/p6-god-function-split-plan.md`](../history/plans-archive/p6-god-function-split-plan.md)
は phase 名を `_run_beta_prepare` / `_run_beta_month_tick` /
`_run_beta_dispatch_window` / `_run_beta_writeback` と提案していた。
実際の分割は代わりに `_setup` + `_dispatch` + 4 本の phase runner を
選択した。これは自然なデータフロー境界 (setup → 月次 dispatch loop
→ phase runner) により直接 map し、各 phase runner を独立に推論
できる形になる。(Issue #2169 で置き換え済み: ループ後の phase runner は
廃止され、上記のとおり `run_forward_loop` が駆動する phase 別の
schedule/dispatch 関数になった。)

## 4. C3 — population engine 分割 (5 クラスタ)

**Façade**: `clinosim/modules/population/engine.py` (分割後 1157 LOC)。

### 抽出モジュール

| ファイル | 内容 | Phase |
|---|---|---|
| `clinosim/modules/population/_chronic.py` | `ChronicConditionSpec`、`_bmi_category_probabilities`、`_smoking_status_probabilities`、`_expected_lifestyle_multiplier`、`_expected_comorbidity_multiplier`、`_target_prev_at_age_legacy`、`_parse_chronic_prevalence` | C3a |
| `clinosim/modules/population/_demographics.py` | `_load_demographics`、`_parse_age_distribution`、`_disease_monthly_rate_from_locale`、`_sample_age_band`、`_sex_ratio_male_probability`、`_care_seeking_threshold_mean`、`_RH_POSITIVE_FRACTION`、`_derive_race`、`_derive_ethnicity`、`_derive_rh_factor`、`_sample_blood_type` | C3b |
| `clinosim/modules/population/_identity.py` | `_load_name_data`、`_sample_surname`、`_sample_given_name`、`_sample_occupation`、`_generate_household_address`、`_generate_phone` | C3c |
| `clinosim/modules/population/_pregnancy.py` | `_PREGNANCY_ELIGIBLE_MIN_AGE`、`_PREGNANCY_ELIGIBLE_MAX_AGE`、`_PERINATAL_STAGE_COUNTERS`、`_annual_conception_rate`、`_perinatal_stage_incr`、`_pregnancy_lifecycle_events` | C3d |
| `clinosim/modules/population/_chemo.py` | `pick_active_chemo_regimen` (public helper)、`_chemo_cycle_events` | C3e |

### Lazy local import

`_chemo.py` / `_pregnancy.py` 下のいくつかは
`clinosim.locale.loader` + `clinosim.seeding` +
`clinosim.simulator.perinatal` に対し lazy local import を使い
PR 間の依存連鎖を解く。これにより
`python -c "import clinosim.modules.population"` が cheap に保たれ、
façade 経由の import サイクルを回避する。

## 5. 薄い delegator re-export パターン (全モジュール共通)

全ての抽出モジュールは façade を通して同一形状で配線される:

```python
# engine.py (façade)
from clinosim.modules.population._chemo import (
    pick_active_chemo_regimen as pick_active_chemo_regimen,
    _chemo_cycle_events as _chemo_cycle_events,
)
```

`as <name>` 形式は **必須** — そうでないと
`ruff --select F401` が unused import として検出する。`as` export は
re-export を type-checker に可視化し、F401 gate をクリーンに保つ。

外部 caller:

```python
# 変更なしで動作 (歴史的 import)
from clinosim.modules.population.engine import pick_active_chemo_regimen

# 権威的 source を直接 import することもできる
from clinosim.modules.population._chemo import pick_active_chemo_regimen
```

## 6. 検証契約

全 extraction PR について以下を pass:

- **Full `tests/unit/` suite**: 7092 passed、16 skipped、1 xfailed。
- **byte-identical cohort fingerprint**: US p=500 seed=42 + JP p=500
  seed=17 window `2025-01..04`、`scripts/engine-fingerprint.sh`
  経由。branch + `origin/master` baseline 両方で
  `TOTAL sha256 0184a8b382990915e2e04ca6c94bce2d24e105b39d6be827f705c461f8f621a8`。
- `ruff check`、`ruff format`、`ruff --select F401,F841`、
  `mypy --strict`、`vulture --min-confidence 60` — 全 green。

**RNG 消費順の reorder なし**: caller 提供の `np.random.Generator` を
触る helper は sequence をそのまま維持。新サブ RNG が現れる場合
(例: `perinatal_delivery_seed(person_id, year)`、
`chemotherapy_regimen_seed(person_id, cancer_code)`) は patient / code
単位の決定論的サブ seed で、master stream を触らない。これにより
これらの helper が読む yaml データファイルの編集が無関係な患者の
カレンダーに波及することはない。

## 7. 次に見る場所

- [`module-architecture.md`](module-architecture.md) — top-level パッケージツリー。post-C2 simulator レイアウトを反映。
- [`../history/plans-archive/p6-god-function-split-plan.md`](../history/plans-archive/p6-god-function-split-plan.md) — 実行前の原案 + 実行結果 callout を inline で追記済。
- 各抽出モジュールのファイル先頭 docstring — 「RNG-neutrality contract」「cross-year state」等の属性別設計ノートが元の engine から verbatim で移植されている。
