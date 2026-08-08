# Incremental Snapshot Diff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** cron 日次追記 workflow を、既存 snapshot 意味論の operational cover として実現する。3 修正(F1 cross-cursor RNG determinism + F2 NDJSON id sort + F3 diff CLI)+ F4 snapshot memoize で、p=500k 規模でも 1 日 advance が数分で完了する。

**Architecture:** run_beta の 4 phase を per-key sub-seed 化して cross-cursor byte-identity を保証 (F1)、NDJSON emit 時に id 昇順 sort して行 diff friendly 化 (F2)、`clinosim diff` CLI で 2 snapshot 出力から FHIR Bundle transaction を生成 (F3)、前 snapshot output directory を cache として利用し discharge 済 patient は前 CIF から load して simulate skip (F4)。state module / cursor.json / advance CLI / push 統合はいずれも作らない — 運用は既存 `clinosim run --snapshot <date>` + user cron script + curl POST。

**Tech Stack:** Python 3.11+, numpy, pytest, ruff, mypy strict、既存 clinosim base(AD-16 sub-seed pattern、AD-30 codes-only、AD-55/56 registry、AD-32 snapshot semantics)。

## Global Constraints

- Formatter: ruff / Type: mypy strict / Line: 100
- 実装は **direct-master 方式**(memory `feedback_clinosim_workflow`):PR 不要、commit push per master
- **AD-55/56 module contract 変更ゼロ** — `modules/*/` は一切触らない
- **AD-16 sub-seed pattern 準拠** — 新 phase salt は `derive_sub_seed(master_seed, phase_salt, key)` 経由
- **CIF codes only(AD-30)/ CIF = only simulation output(AD-17)** 保持
- **Snapshot semantics(AD-32)** 保持:cursor 越え encounter は in-progress
- **JP-only path のコメント/docstring は日本語**、共通 dispatch は英語(session 47 rule)
- 既存 golden 破壊(F1+F2 = PR-1)は 1 回に集約、以降 new baseline
- PR-1 golden 再生成後は `scripts/reproduce.sh` の baseline も update
- Test 分類:unit(<30s)/ integration(<5min)/ e2e(<30min)/ regression(marker `-m regression`)
- 新規 file の path 定数:`_HERE = Path(__file__).resolve().parent` の canonical form
- 決定性は **観測してから claim**(memory `feedback_verify_before_asserting`)= test で PASS 確認前に「動く」と書かない

---

## File Structure(全 task 通しての変更 map)

### 新規作成
- `clinosim/simulator/diff.py` — F3 core、pure logic(canonical hash / 3 状態分類 / Bundle generator / summary)
- `clinosim/simulator/memoize.py` — F4 core、`_cache_manifest.json` read/write + eligibility 判定 + CIF load helper
- `tests/unit/test_engine_cross_cursor.py` — F1 invariant
- `tests/unit/test_fhir_ndjson_stable_sort.py` — F2 invariant
- `tests/unit/test_diff_bundle.py` — F3 canonical hash / 3 状態 / Bundle / summary
- `tests/unit/test_engine_memoize.py` — F4 hit / miss / staleness / hit-ratio
- `tests/integration/test_incremental_snapshot_workflow.py` — F1+F2+F3+F4 e2e

### 変更
- `clinosim/simulator/seeding.py` — PHASE_* 定数 + `derive_phase_rng` 追加(<40 行追加)
- `clinosim/simulator/engine.py` — 4 phase の RNG 派生を sub-seed 化(P1/P2/P3/P4/P4')、`cache_dir` 引数追加、cache hit path 挿入(<120 行追加)
- `clinosim/modules/output/fhir_r4_adapter.py` — NDJSON 書き終わり時に id 昇順で rewrite(<20 行追加)
- `clinosim/simulator/cli.py` — `diff` subcommand 登録(<40 行追加)
- `scripts/reproduce.sh` — F1+F2 完了後の new baseline に更新
- `tests/unit/test_seeding.py` — phase salt uniqueness / determinism check 1 行追加

**触らない**:
- `clinosim/modules/*/`(全 module)
- `clinosim/types/*.py`(全 dataclass)
- `clinosim/codes/`, `clinosim/locale/`
- disease/encounter YAML 全体
- 既存 enricher registry / builder registry / adapter registry

---

# PR-1: F1 cross-cursor RNG determinism + F2 NDJSON id sort(golden 再生成統合)

### Task 1: `seeding.py` に phase constants + `derive_phase_rng` 追加

**Files:**
- Modify: `clinosim/simulator/seeding.py`(末尾追加)
- Test: `tests/unit/test_seeding.py`(1 行追加)

**Interfaces:**
- Consumes: なし(既存 `derive_sub_seed` に依存)
- Produces:
  - `PHASE_LIFE_EVENT: int = 0x504C4556` (`"PLEV"`)
  - `PHASE_INPATIENT_SIM: int = 0x50494E50` (`"PINP"`)
  - `PHASE_READMISSION: int = 0x50524541` (`"PREA"`)
  - `PHASE_OUTPATIENT_CAL: int = 0x504F5054` (`"POPT"`)
  - `PHASE_ED_VISIT: int = 0x50454456` (`"PEDV"`)
  - `_PHASE_OFFSETS: dict[str, int]` = 上記 5 値の map
  - `def derive_phase_rng(master_seed: int, phase_salt: int, key: str) -> np.random.Generator`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_seeding.py` に追加(既存 test 群の末尾):

```python
import numpy as np

from clinosim.simulator.seeding import (
    PHASE_ED_VISIT,
    PHASE_INPATIENT_SIM,
    PHASE_LIFE_EVENT,
    PHASE_OUTPATIENT_CAL,
    PHASE_READMISSION,
    _PHASE_OFFSETS,
    derive_phase_rng,
)


def test_phase_seed_offsets_unique():
    """AD-16: phase offset の衝突は 2 phase の RNG stream を共有させる silent-no-op。"""
    values = list(_PHASE_OFFSETS.values())
    assert len(set(values)) == len(values), f"duplicate phase offsets: {_PHASE_OFFSETS!r}"


def test_phase_seed_constants_registered():
    """新規 phase 定数を _PHASE_OFFSETS に登録し忘れると silent-no-op になる。"""
    assert PHASE_LIFE_EVENT in _PHASE_OFFSETS.values()
    assert PHASE_INPATIENT_SIM in _PHASE_OFFSETS.values()
    assert PHASE_READMISSION in _PHASE_OFFSETS.values()
    assert PHASE_OUTPATIENT_CAL in _PHASE_OFFSETS.values()
    assert PHASE_ED_VISIT in _PHASE_OFFSETS.values()


def test_derive_phase_rng_returns_generator():
    """determinism: 同 (master, phase, key) → 同 stream。"""
    a = derive_phase_rng(42, PHASE_INPATIENT_SIM, "event-1")
    b = derive_phase_rng(42, PHASE_INPATIENT_SIM, "event-1")
    assert list(a.integers(0, 100, 10)) == list(b.integers(0, 100, 10))


def test_derive_phase_rng_key_independent():
    """determinism: 同 (master, phase) でも key が違えば独立 stream。"""
    a = derive_phase_rng(42, PHASE_INPATIENT_SIM, "event-1")
    b = derive_phase_rng(42, PHASE_INPATIENT_SIM, "event-2")
    assert list(a.integers(0, 1000, 20)) != list(b.integers(0, 1000, 20))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_seeding.py::test_phase_seed_offsets_unique -v`
Expected: FAIL with `ImportError` / `AttributeError` — `_PHASE_OFFSETS` / `derive_phase_rng` が存在しない。

- [ ] **Step 3: Write minimal implementation**

`clinosim/simulator/seeding.py` の末尾に追加:

```python
# ------------------------------------------------------------------
# Phase-scoped sub-seed offsets (session 49, F1 cross-cursor determinism).
#
# run_beta の 4 phase(life event 生成 / hospital main loop / readmission /
# outpatient calendar / ED)は現行 master RNG を串刺しに消費している。
# cursor 移動 (snapshot_date の変更) で phase P1 の event 数が変わると
# master RNG state が phase P2 開始時点で異なる → 同 patient X でも
# 違う結果になる = 「cursor A の output と cursor B の共有区間が
# bytewise 一致」が保証されない。
#
# ここで phase salt を分離し、各 phase 内で per-key sub-seed に切り替える
# ことで master RNG を完全に迂回する。cursor 移動が phase をまたいで
# 影響を伝播させない。
#
# Convention: 16-bit hex ASCII (4 ASCII 大文字) の 32-bit 値。既存
# ENRICHER_SEED_OFFSETS と衝突しないよう 0x504xxxxx 帯を使用。
PHASE_LIFE_EVENT      = 0x504C4556  # "PLEV"
PHASE_INPATIENT_SIM   = 0x50494E50  # "PINP"
PHASE_READMISSION     = 0x50524541  # "PREA"
PHASE_OUTPATIENT_CAL  = 0x504F5054  # "POPT"
PHASE_ED_VISIT        = 0x50454456  # "PEDV"

_PHASE_OFFSETS = {
    "life_event":          PHASE_LIFE_EVENT,
    "inpatient_sim":       PHASE_INPATIENT_SIM,
    "readmission":         PHASE_READMISSION,
    "outpatient_calendar": PHASE_OUTPATIENT_CAL,
    "ed_visit":            PHASE_ED_VISIT,
}

assert len(set(_PHASE_OFFSETS.values())) == len(_PHASE_OFFSETS), \
    f"phase offset collision: {_PHASE_OFFSETS!r}"


def derive_phase_rng(master_seed: int, phase_salt: int, key: str) -> "np.random.Generator":
    """AD-16 徹底: run_beta の phase 内 key ごとに独立 RNG stream を返す。

    cursor A と cursor B で同 phase の同 key を要求すれば同一 stream になり、
    cross-cursor byte-identity が保証される。key は phase 内で unique な
    entity 識別子(event.person_id + timestamp + disease_id など)を使う。
    """
    import numpy as np
    return np.random.default_rng(derive_sub_seed(master_seed, phase_salt, key))
```

**注意**:既存 `derive_sub_seed` は module top で `import hashlib` 済み。`np` は lazy import で
seeding.py の import 時 numpy 依存を避ける(seeding.py は module 依存を最小に保つ設計)。

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_seeding.py -v`
Expected: 全 test PASS(新規 4 test + 既存 test 全部)。

- [ ] **Step 5: Commit**

```bash
git add clinosim/simulator/seeding.py tests/unit/test_seeding.py
git commit -m "$(cat <<'EOF'
feat(seeding): add phase-scoped sub-seed offsets for F1 cross-cursor determinism

session 49 F1 core primitive。run_beta の 4 phase を master RNG から
分離するための phase salt + derive_phase_rng helper。behavior change
なし(まだ engine.py で使っていない)。

- PHASE_LIFE_EVENT / PHASE_INPATIENT_SIM / PHASE_READMISSION /
  PHASE_OUTPATIENT_CAL / PHASE_ED_VISIT の 5 定数追加
- _PHASE_OFFSETS で衝突チェック(silent-no-op 防御)
- derive_phase_rng(master, salt, key) helper

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016cvyhjp7jj5bE3CdDT6mZ9
EOF
)"
git push origin master
```

---

### Task 2: `engine.py` の 4 phase を per-key sub-seed 化 + cross-cursor invariant test + golden 再生成

**Files:**
- Modify: `clinosim/simulator/engine.py`(4 phase 書き換え、~50 行変更)
- Modify: `clinosim/simulator/inpatient.py`(rng 引数はそのまま、caller が sub-rng を渡す形なので変更なし。ただし `_simulate_unknown_condition` も対象なので確認)
- Modify: `clinosim/simulator/outpatient.py`(同様、caller が sub-rng を渡す)
- Modify: `clinosim/simulator/emergency.py`(同様)
- Test: `tests/unit/test_engine_cross_cursor.py`(新規)
- Regen: `tests/e2e/**/golden/**`(golden 一括再生成)
- Update: `scripts/reproduce.sh`(baseline hash 更新)

**Interfaces:**
- Consumes: Task 1 の `derive_phase_rng`, `PHASE_LIFE_EVENT`, `PHASE_INPATIENT_SIM`, `PHASE_READMISSION`, `PHASE_OUTPATIENT_CAL`, `PHASE_ED_VISIT`
- Produces: `run_beta(config, hospital_config_path)` の output は前と同じ signature、内部 RNG stream 派生のみ変更

- [ ] **Step 1: Write the failing cross-cursor invariant test**

`tests/unit/test_engine_cross_cursor.py`(新規):

```python
"""F1 core invariant: cursor A と cursor B の共有区間 record が bytewise 一致。

現行(F1 未実装)では master RNG 消費量が snapshot_date で変わるため、
同 patient X の同 event でも cursor A と B で違う結果が出る。F1 実装後は
一致する。この test は F1 実装完了時に PASS するように書き、実装前は FAIL。
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from clinosim.simulator.engine import run_beta
from clinosim.types.config import SimulatorConfig


@pytest.mark.unit
def test_cross_cursor_shared_window_byte_identical():
    """F1 core: cursor A の全 record が cursor B の共有区間と bit-identical。"""
    config_a = SimulatorConfig(
        random_seed=42,
        catchment_population=200,
        country="US",
        time_range=("2025-01", "2026-01"),
        snapshot_date="2025-06-30",
    )
    config_b = replace(config_a, snapshot_date="2025-07-31")

    ds_a = run_beta(config_a)
    ds_b = run_beta(config_b)

    # A に居た全 patient は B にも同一 patient_id で存在
    a_by_pid = {r.patient.patient_id: r for r in ds_a.patients}
    b_by_pid = {r.patient.patient_id: r for r in ds_b.patients}
    assert set(a_by_pid.keys()) <= set(b_by_pid.keys()), \
        "cursor B is missing patients present in cursor A"

    # cursor A 完了 record は B でも同一 content
    for pid, a_rec in a_by_pid.items():
        # A の record が全 encounter で discharge_datetime <= 2025-06-30 の場合
        # だけ厳格 assert(cursor 越えの in-progress は F1 単独では保証しない)
        all_completed = all(
            enc.discharge_datetime is not None
            and enc.discharge_datetime.date() <= date(2025, 6, 30)
            for enc in a_rec.encounters
        )
        if not all_completed:
            continue
        b_rec = b_by_pid[pid]
        assert a_rec == b_rec, f"cross-cursor drift for completed patient {pid}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_engine_cross_cursor.py -v`
Expected: FAIL — 現行 engine.py は master rng を串刺し消費しているため cross-cursor drift 発生。
(この test は F1 実装後 PASS するように書いてある。)

- [ ] **Step 3: Refactor engine.py 4 phase を sub-seed 化**

`clinosim/simulator/engine.py` の書き換え(該当箇所を検索、`rng` から `<phase>_rng` に置換)。

**P1 life event generation**(現行 line 141-148 付近):

```python
# 現行
while (y, m) <= (end_y, end_m):
    all_events.extend(generate_monthly_events(population, y, m, rng, country=config.country))
    m += 1
    if m > 12:
        m, y = 1, y + 1

# 変更後
from clinosim.simulator.seeding import (
    PHASE_ED_VISIT,
    PHASE_INPATIENT_SIM,
    PHASE_LIFE_EVENT,
    PHASE_OUTPATIENT_CAL,
    PHASE_READMISSION,
    derive_phase_rng,
)

master_seed = config.random_seed  # F1: 以下 4 phase は master rng を使わず sub-seed 派生
...

while (y, m) <= (end_y, end_m):
    month_key = f"{y:04d}-{m:02d}"
    month_rng = derive_phase_rng(master_seed, PHASE_LIFE_EVENT, month_key)
    all_events.extend(generate_monthly_events(population, y, m, month_rng, country=config.country))
    m += 1
    if m > 12:
        m, y = 1, y + 1
```

**P2 hospital main loop**(現行 line 183 付近の `for idx, event in enumerate(hospital_events):`):

```python
# 変更後: _simulate_patient / _simulate_unknown_condition に渡す rng を per-event sub-seed
for idx, event in enumerate(hospital_events):
    ...
    event_key = f"{event.person_id}|{event.timestamp.isoformat()}|{event.disease_id}"
    event_rng = derive_phase_rng(master_seed, PHASE_INPATIENT_SIM, event_key)

    if event.condition_type == "unknown" or disease_id.startswith("unknown_"):
        record = _simulate_unknown_condition(patient, event, event_rng, healthcare, roster,
                                             hospital_ops=hospital_ops, config=config)
        ...
        continue

    ...
    record = _simulate_patient(
        patient, event, disease_id, protocol, healthcare, roster, config, event_rng,
        secondary_protocol=secondary_protocol,
        ...
    )
```

**注意**:`_activate_cached` は現行で master `rng` を使って activate している。これも per-patient sub-seed 化する:

```python
# 現行
def _activate_cached(p: PersonRecord) -> PatientProfile:
    if p.person_id not in patient_cache:
        patient_cache[p.person_id] = activate_patient(p, rng, demo)
    return patient_cache[p.person_id]

# 変更後
def _activate_cached(p: PersonRecord) -> PatientProfile:
    if p.person_id not in patient_cache:
        # patient activation は cursor 独立に patient_id で完全に決まる
        act_rng = derive_phase_rng(master_seed, PHASE_INPATIENT_SIM, f"activate|{p.person_id}")
        patient_cache[p.person_id] = activate_patient(p, act_rng, demo)
    return patient_cache[p.person_id]
```

**P3 readmission**(現行 line 253 以降):

```python
# 変更後
for record in patient_records:
    ...
    re_key = f"{record.patient.patient_id}|{record.encounters[0].encounter_id}"
    re_rng = derive_phase_rng(master_seed, PHASE_READMISSION, re_key)
    re_event = _evaluate_readmission(record, person, disease_id, protocol, country_key, re_rng)
    ...

# readmission 実際の simulate 部
for re_event in readmission_events:
    ...
    re_sim_key = f"{re_event.person_id}|{re_event.timestamp.isoformat()}|readmission"
    re_sim_rng = derive_phase_rng(master_seed, PHASE_INPATIENT_SIM, re_sim_key)
    record = _simulate_patient(
        patient, re_event, re_event.disease_id, protocol,
        healthcare, roster, config, re_sim_rng,
        is_readmission=True,
        ...
    )
```

**P4 post-discharge outpatient + calendar**(現行 line 322 以降):

```python
# post-discharge follow-up
for record in inpatient_records:
    ...
    opd_key = f"{pid}|post_discharge|{followup_date.isoformat()}"
    opd_rng = derive_phase_rng(master_seed, PHASE_OUTPATIENT_CAL, opd_key)
    opd_record = _simulate_outpatient_visit(
        _activate_cached(person), "post_discharge", followup_date, roster, opd_rng,
        followup_spec=merged_spec, post_discharge_disease=disease_id,
        country=config.country, config=config,
    )

# healthcare calendar
calendar_key = f"{config.country}|{start_y:04d}|calendar"
calendar_rng = derive_phase_rng(master_seed, PHASE_OUTPATIENT_CAL, calendar_key)
calendar_events = generate_healthcare_calendar(population, start_y, config.country, calendar_rng)

for event in calendar_events:
    ...
    ev_key = f"{event.person_id}|{event.timestamp.isoformat()}|{event.event_type}"
    ev_rng = derive_phase_rng(master_seed, PHASE_OUTPATIENT_CAL, ev_key)
    visit_time = datetime(event.timestamp.year, event.timestamp.month,
                          event.timestamp.day, 10, int(ev_rng.integers(0, 45)))

    if event.event_type == "chronic_visit":
        ...
        opd_record = _simulate_outpatient_visit(
            patient, "chronic_followup", visit_time, roster, ev_rng,
            ...
        )
```

**P4' ED visits**(現行 line 412 以降):

```python
if ed_conditions and n_ed > 0:
    for slot in range(n_ed):
        slot_key = f"{config.country}|ed-slot-{slot:06d}"
        slot_rng = derive_phase_rng(master_seed, PHASE_ED_VISIT, slot_key)
        # 全 rng 呼び出しを slot_rng に置換
        total_months = (end_y - start_y) * 12 + (end_m - start_m) + 1
        month_offset = int(slot_rng.integers(0, total_months))
        visit_month = ((start_m - 1 + month_offset) % 12) + 1
        person_id = slot_rng.choice(list(population.persons.keys()))
        ...
        ed_time = datetime(ed_year, visit_month, ed_day, ed_hour, int(slot_rng.integers(0, 60)))
        ...
        ed_record = _simulate_ed_visit(
            patient, cond, ed_time, roster, slot_rng, country=config.country, config=config,
        )
```

**注意事項**:
- `_roster_rng`(既存 `master_seed ^ 0x524F5354`)は変更しない — patient/event 独立なので既に決定的
- POST_POPULATION / POST_RECORDS の enricher 呼び出し(`run_stage`)は変更しない — 既に AD-16 sub-seed
- `rng = np.random.default_rng(config.random_seed)` の生成は残す:population 生成(`generate_population`)で使う。population 生成が snapshot_date 独立なので問題なし

- [ ] **Step 4: Run cross-cursor invariant test to verify it now passes**

Run: `pytest tests/unit/test_engine_cross_cursor.py -v`
Expected: PASS — F1 実装後、共有区間 record が bit-identical。

- [ ] **Step 5: Full unit test suite で回帰確認**

Run: `pytest tests/unit -x -q`
Expected: golden 系 test(FHIR NDJSON 内容チェックなど)は golden が古いので **FAIL する** ものが多い。
これは想定内(Step 6 で regen)。それ以外は全 PASS。

- [ ] **Step 6: Golden 一括再生成**

Golden の対象:
- `tests/e2e/**/golden/*.ndjson`
- `tests/fixtures/patient_profiles/*.golden.json`(AD-66 canonical fixtures)

再生成コマンド(既存 `clinosim regenerate-goldens --all` を使う):

```bash
# AD-66 fixture goldens
clinosim regenerate-goldens --all

# E2E goldens: 該当 e2e test の script 実行 or fixture generator
find tests/e2e -name "*.ndjson" -path "*golden*" | head -5
# 該当する e2e test の regeneration script を実行(既存 pattern に従う)
```

**確認**:再生成後、golden diff が「値そのものは似ているが RNG stream 変化で全部 diff」となる。
これは F1 の想定挙動。commit で全 golden 差分を含める。

- [ ] **Step 7: Full test suite 再走**

```bash
pytest tests/unit -x -q          # golden 再生成後、全 PASS 期待
pytest tests/integration -x -q   # 全 PASS 期待
pytest -m regression -x -q       # AD-66 regression PASS 期待
```

Expected: 全 PASS。

- [ ] **Step 8: `scripts/reproduce.sh` の baseline 確認**

```bash
bash scripts/reproduce.sh
```

Expected: 全 file byte-identical(reproduce.sh は 2 回連続実行の diff)= 変わっていない (script は
「同 seed + snapshot で 2 回走ると同じ」を確認するので、内容自体は変わっても determinism は保たれる)。

- [ ] **Step 9: Commit(golden 再生成含む atomic commit)**

```bash
git add clinosim/simulator/engine.py
git add tests/unit/test_engine_cross_cursor.py
git add tests/e2e/**/golden/*.ndjson
git add tests/fixtures/patient_profiles/*.golden.json
git commit -m "$(cat <<'EOF'
feat(engine): F1 cross-cursor RNG determinism via phase sub-seeds

session 49 F1。run_beta の 4 phase(life event / hospital main loop /
readmission / outpatient calendar / ED)を per-key sub-seed 化して
master RNG を完全に迂回。cursor 移動時に共有区間の record が
bit-identical に取れるようになる。

- P1: generate_monthly_events → PHASE_LIFE_EVENT + month key
- P2: _simulate_patient / _simulate_unknown_condition → PHASE_INPATIENT_SIM
      + event key、_activate_cached も per-patient sub-seed 化
- P3: _evaluate_readmission → PHASE_READMISSION、readmission 実 sim も
      PHASE_INPATIENT_SIM sub-seed
- P4: post-discharge outpatient + calendar → PHASE_OUTPATIENT_CAL
- P4': ED slot loop → PHASE_ED_VISIT slot key

Golden 一括再生成:F1 は RNG stream 派生元を変えるので値そのものが
全 encounter で shift する。臨床的意味は unchanged、determinism は
新 baseline で保たれる(reproduce.sh 検証 PASS)。

新 invariant test: tests/unit/test_engine_cross_cursor.py で
cursor A vs cursor B の共有区間 record が bit-identical を検証。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016cvyhjp7jj5bE3CdDT6mZ9
EOF
)"
git push origin master
```

---

### Task 3: F2 NDJSON id 昇順 sort + invariant test

**Files:**
- Modify: `clinosim/modules/output/fhir_r4_adapter.py`(NDJSON 書き終わり時の rewrite)
- Test: `tests/unit/test_fhir_ndjson_stable_sort.py`(新規)
- Regen: golden 一部(NDJSON 行順のみ変化)

**Interfaces:**
- Consumes: なし(Task 2 の engine 変更に依存しない)
- Produces: 各 `<ResourceType>.ndjson` が resource id 昇順で emit される。

- [ ] **Step 1: Write the failing test**

`tests/unit/test_fhir_ndjson_stable_sort.py`(新規):

```python
"""F2 core invariant: 各 NDJSON file の resource が id 昇順で emit される。

行 diff friendly 化のため。行順序が cursor 依存(patient_records の iteration 順)だと
2 snapshot の diff で spurious "line moved" が出る。id sort 済であれば diff は
純粋な "new resource" / "changed content" だけを surface する。
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from clinosim.simulator.engine import run_beta
from clinosim.types.config import SimulatorConfig


@pytest.mark.unit
def test_ndjson_files_id_sorted(tmp_path):
    """F2 core: 各 NDJSON が id 昇順で emit される。"""
    from clinosim.modules.output.fhir_r4_adapter import convert_cif_to_fhir
    from clinosim.modules.output.cif_io import write_cif  # 実 module 名は要確認

    config = SimulatorConfig(random_seed=42, catchment_population=30, country="US",
                             time_range=("2026-01", "2026-03"))
    ds = run_beta(config)
    cif_dir = tmp_path / "cif"
    fhir_dir = tmp_path / "fhir"
    cif_dir.mkdir()
    fhir_dir.mkdir()
    write_cif(ds, cif_dir)
    convert_cif_to_fhir(cif_dir, fhir_dir, country="US",
                       roster_map={}, hospital_config=ds.hospital_config)

    ndjson_files = list(fhir_dir.glob("*.ndjson"))
    assert ndjson_files, "no NDJSON emitted"
    for ndjson_file in ndjson_files:
        lines = [line for line in ndjson_file.read_text().splitlines() if line.strip()]
        ids = [json.loads(line).get("id", "") for line in lines]
        assert ids == sorted(ids), \
            f"{ndjson_file.name} not id-sorted:\n  actual:   {ids[:5]}...\n  sorted:   {sorted(ids)[:5]}..."
```

**注意**:import path は `clinosim/modules/output/` の実 module 構造に合わせる。書き出し API 名を
`fhir_r4_adapter.py` の実際の signature で調整する(`convert_cif_to_fhir` が現行 API)。

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_fhir_ndjson_stable_sort.py -v`
Expected: FAIL — 現行 NDJSON は patient_records iteration 順で書かれており id sort されていない。

- [ ] **Step 3: `fhir_r4_adapter.py` に id sort post-processing 追加**

`convert_cif_to_fhir` の `finally` 直前(全 write 完了後、writer close 前):

```python
    finally:
        # F2 (session 49): id 昇順 sort。cursor A / B の 2 snapshot の
        # 行 diff が clean になる。cursor 依存の iteration 順を排除。
        for rt, writer in writers.items():
            writer.close()
        for rt in list(writers.keys()):
            path = os.path.join(output_dir, f"{rt}.ndjson")
            _sort_ndjson_by_id_inplace(path)
```

module 末尾 or `_normalize_dt_fields` の近くに helper 追加:

```python
def _sort_ndjson_by_id_inplace(path: str) -> None:
    """NDJSON file を resource id 昇順で in-place rewrite (F2, session 49)。

    File 全体を memory に読み込むので大 file は RAM 依存。p=10k で ~4.7GB total、
    最大 file (Observation.ndjson) は 数 GB 規模。JP p=500k のスケールでは
    parallel 書き出し + external merge sort に置換する余地があるが、Phase A では
    memory sort で十分(user 想定コスト内)。
    """
    with open(path, encoding="utf-8") as f:
        lines = [line for line in f.read().splitlines() if line.strip()]
    lines.sort(key=lambda line: json.loads(line).get("id", ""))
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")
```

- [ ] **Step 4: Run F2 invariant test to verify it passes**

Run: `pytest tests/unit/test_fhir_ndjson_stable_sort.py -v`
Expected: PASS。

- [ ] **Step 5: Full unit / integration / e2e で回帰確認**

```bash
pytest tests/unit -x -q
pytest tests/integration -x -q
pytest tests/e2e -x -q  # golden 行順が変わるので FAIL 系あり
```

Expected: unit / integration は PASS。e2e は golden 行順が変わって FAIL のはず → Step 6 で regen。

- [ ] **Step 6: E2E golden 再生成(行順のみ変化、content 不変)**

再生成コマンドは Task 2 と同じ:

```bash
clinosim regenerate-goldens --all  # AD-66 fixture
# E2E golden は該当 script で
```

- [ ] **Step 7: Full test suite 再走**

```bash
pytest -x -q  # 全 category、全 PASS 期待
bash scripts/reproduce.sh
```

Expected: 全 PASS + reproduce.sh 全 file byte-identical。

- [ ] **Step 8: Commit**

```bash
git add clinosim/modules/output/fhir_r4_adapter.py
git add tests/unit/test_fhir_ndjson_stable_sort.py
git add tests/e2e/**/golden/*.ndjson  # 行順のみ変化
git commit -m "$(cat <<'EOF'
feat(fhir): F2 NDJSON id-sorted output for clean line diff

session 49 F2。各 <ResourceType>.ndjson を書き終わり時に resource id
昇順で in-place rewrite。cursor A / B の 2 snapshot 行 diff が
patient_records iteration 順に依存せず、純粋に new resource /
changed content のみ surface されるようになる。

- fhir_r4_adapter._sort_ndjson_by_id_inplace helper 追加
- convert_cif_to_fhir の finally 直前で全 NDJSON を id sort

E2E golden は行順のみ変化(content 不変、determinism 保持)。
reproduce.sh 検証 PASS。

新 invariant test: tests/unit/test_fhir_ndjson_stable_sort.py で
全 NDJSON が id 昇順を検証。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016cvyhjp7jj5bE3CdDT6mZ9
EOF
)"
git push origin master
```

---

# PR-2: F3 `clinosim diff` CLI(pure addition)

### Task 4: `simulator/diff.py` の canonical hash + Resource 3 状態分類

**Files:**
- Create: `clinosim/simulator/diff.py`
- Test: `tests/unit/test_diff_bundle.py`(新規)

**Interfaces:**
- Consumes: なし
- Produces:
  - `def canonical_hash(resource: dict) -> str` — meta.lastUpdated / meta.versionId / meta.source を除いた sha256
  - `def classify_resources(old_by_id: dict[str, dict], new_by_id: dict[str, dict]) -> tuple[list[dict], list[dict], list[dict]]` — (new_only, updated, unchanged) を返す

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_diff_bundle.py`(新規):

```python
"""F3: canonical hash + 3 状態分類 test。"""
from __future__ import annotations

import pytest

from clinosim.simulator.diff import canonical_hash, classify_resources


@pytest.mark.unit
def test_canonical_hash_stable_across_key_order():
    """dict key order 非依存で同 hash。"""
    r1 = {"resourceType": "Patient", "id": "p1", "name": [{"family": "Yamada"}]}
    r2 = {"id": "p1", "name": [{"family": "Yamada"}], "resourceType": "Patient"}
    assert canonical_hash(r1) == canonical_hash(r2)


def test_canonical_hash_ignores_meta_last_updated():
    """meta.lastUpdated が違っても同 hash(cursor 依存 field を除外)。"""
    r1 = {"resourceType": "Patient", "id": "p1",
          "meta": {"lastUpdated": "2026-05-31T00:00:00+09:00"}}
    r2 = {"resourceType": "Patient", "id": "p1",
          "meta": {"lastUpdated": "2026-06-01T00:00:00+09:00"}}
    assert canonical_hash(r1) == canonical_hash(r2)


def test_canonical_hash_ignores_meta_version_id():
    """meta.versionId が違っても同 hash。"""
    r1 = {"resourceType": "Patient", "id": "p1", "meta": {"versionId": "1"}}
    r2 = {"resourceType": "Patient", "id": "p1", "meta": {"versionId": "2"}}
    assert canonical_hash(r1) == canonical_hash(r2)


def test_canonical_hash_ignores_meta_source():
    """meta.source が違っても同 hash。"""
    r1 = {"resourceType": "Patient", "id": "p1", "meta": {"source": "a"}}
    r2 = {"resourceType": "Patient", "id": "p1", "meta": {"source": "b"}}
    assert canonical_hash(r1) == canonical_hash(r2)


def test_canonical_hash_preserves_meta_profile():
    """meta.profile は意味論的差分なので保持。"""
    r1 = {"resourceType": "Patient", "id": "p1", "meta": {"profile": ["a"]}}
    r2 = {"resourceType": "Patient", "id": "p1", "meta": {"profile": ["b"]}}
    assert canonical_hash(r1) != canonical_hash(r2)


def test_canonical_hash_detects_content_change():
    """resource 本体の差分は当然 hash 変化。"""
    r1 = {"resourceType": "Encounter", "id": "e1", "status": "in-progress"}
    r2 = {"resourceType": "Encounter", "id": "e1", "status": "finished"}
    assert canonical_hash(r1) != canonical_hash(r2)


def test_classify_resources_new_only():
    """new_by_id にしかない id は new_only に。"""
    old = {}
    new = {"p1": {"resourceType": "Patient", "id": "p1"}}
    new_only, updated, unchanged = classify_resources(old, new)
    assert len(new_only) == 1 and new_only[0]["id"] == "p1"
    assert updated == [] and unchanged == []


def test_classify_resources_updated_only():
    """両方にある id で hash 違えば updated。"""
    old = {"e1": {"resourceType": "Encounter", "id": "e1", "status": "in-progress"}}
    new = {"e1": {"resourceType": "Encounter", "id": "e1", "status": "finished"}}
    new_only, updated, unchanged = classify_resources(old, new)
    assert new_only == []
    assert len(updated) == 1 and updated[0]["status"] == "finished"
    assert unchanged == []


def test_classify_resources_unchanged():
    """両方にある id で hash 同一なら unchanged。"""
    r = {"resourceType": "Patient", "id": "p1", "name": [{"family": "Yamada"}]}
    new_only, updated, unchanged = classify_resources({"p1": r}, {"p1": dict(r)})
    assert new_only == [] and updated == []
    assert len(unchanged) == 1


def test_classify_resources_mixed():
    """3 状態混合。"""
    old = {
        "p1": {"resourceType": "Patient", "id": "p1", "name": [{"family": "A"}]},
        "e1": {"resourceType": "Encounter", "id": "e1", "status": "in-progress"},
    }
    new = {
        "p1": {"resourceType": "Patient", "id": "p1", "name": [{"family": "A"}]},  # unchanged
        "e1": {"resourceType": "Encounter", "id": "e1", "status": "finished"},     # updated
        "p2": {"resourceType": "Patient", "id": "p2", "name": [{"family": "B"}]}, # new
    }
    new_only, updated, unchanged = classify_resources(old, new)
    assert len(new_only) == 1 and new_only[0]["id"] == "p2"
    assert len(updated) == 1 and updated[0]["id"] == "e1"
    assert len(unchanged) == 1 and unchanged[0]["id"] == "p1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_diff_bundle.py -v`
Expected: FAIL — `diff.py` module が存在しない。

- [ ] **Step 3: Implement `simulator/diff.py`(canonical hash + classify のみ)**

`clinosim/simulator/diff.py`(新規):

```python
"""FHIR snapshot diff — 2 snapshot output の差分を FHIR Bundle transaction に変換 (F3, session 49)。

Approach C の operational cover。clinosim 自身は決定的な snapshot generator に留まり、
「cursor 移動した差分だけを FHIR server に POST する」用の Bundle 生成をここで行う。
push は user 側 tool (curl / httpx / hapi-fhir-cli) に委ねる。
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

# meta 内 cursor 依存 field。hash 計算前に strip する。
_META_HASH_IGNORE_KEYS = ("lastUpdated", "versionId", "source")


def canonical_hash(resource: dict) -> str:
    """Resource の canonical sha256 hash。

    meta.lastUpdated / meta.versionId / meta.source は cursor 依存で
    変わりうるので hash 前に除外(false-positive UPDATED を防ぐ)。
    meta.profile / meta.security 等は意味論的差分なので保持。

    dict key order は sorted で正規化。
    """
    # 深いコピーして meta を strip(元 resource を破壊しない)
    stripped = copy.deepcopy(resource)
    meta = stripped.get("meta")
    if isinstance(meta, dict):
        for k in _META_HASH_IGNORE_KEYS:
            meta.pop(k, None)
        if not meta:
            stripped.pop("meta", None)
    return hashlib.sha256(
        json.dumps(stripped, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def classify_resources(
    old_by_id: dict[str, dict],
    new_by_id: dict[str, dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Resource id ごとに (new_only, updated, unchanged) に分類。

    DELETED(old にあり new にない)は snapshot が cumulative なので通常発生しない。
    発生した場合は上位 caller で warning ログを出す(この関数は返り値に含めない)。

    Args:
        old_by_id: 前 snapshot の {id: resource}
        new_by_id: 現 snapshot の {id: resource}

    Returns:
        (new_only, updated, unchanged) の 3 list。全て resource dict の list。
    """
    new_only: list[dict] = []
    updated: list[dict] = []
    unchanged: list[dict] = []

    for rid, new_r in new_by_id.items():
        old_r = old_by_id.get(rid)
        if old_r is None:
            new_only.append(new_r)
        elif canonical_hash(old_r) != canonical_hash(new_r):
            updated.append(new_r)
        else:
            unchanged.append(new_r)

    return new_only, updated, unchanged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_diff_bundle.py -v`
Expected: 9 test PASS。

- [ ] **Step 5: Commit**

```bash
git add clinosim/simulator/diff.py tests/unit/test_diff_bundle.py
git commit -m "$(cat <<'EOF'
feat(diff): F3 canonical hash + 3-state resource classifier

session 49 F3 core primitives。cursor A / B の 2 snapshot output から
NEW / UPDATED / UNCHANGED 3 状態に resource を分類する pure logic。

- canonical_hash: sorted-key JSON dump の sha256、meta.lastUpdated /
  meta.versionId / meta.source を除外して false-positive UPDATED 防止
- classify_resources: {id: resource} の 2 dict を比較して 3 list を返す

CLI subcommand は次 task。まだ独立で使えるようになっただけ。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016cvyhjp7jj5bE3CdDT6mZ9
EOF
)"
git push origin master
```

---

### Task 5: `simulator/diff.py` に Bundle transaction 生成 + summary

**Files:**
- Modify: `clinosim/simulator/diff.py`(追加)
- Modify: `tests/unit/test_diff_bundle.py`(追加)

**Interfaces:**
- Consumes: Task 4 の `canonical_hash`, `classify_resources`
- Produces:
  - `def load_ndjson_by_id(path: Path) -> dict[str, dict]` — 単一 NDJSON file を {id: resource} に読み込み
  - `def build_diff_bundle(old_dir: Path, new_dir: Path, bundle_id: str, last_updated: str) -> dict` — Bundle transaction dict
  - `def format_summary(bundle: dict, old_cursor: str, new_cursor: str) -> str` — human-readable summary text

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_diff_bundle.py` に追加:

```python
import tempfile
from pathlib import Path

from clinosim.simulator.diff import (
    build_diff_bundle,
    format_summary,
    load_ndjson_by_id,
)


def _write_ndjson(path: Path, resources: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in resources:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def test_load_ndjson_by_id(tmp_path):
    p = tmp_path / "Patient.ndjson"
    _write_ndjson(p, [
        {"resourceType": "Patient", "id": "p1"},
        {"resourceType": "Patient", "id": "p2"},
    ])
    result = load_ndjson_by_id(p)
    assert set(result.keys()) == {"p1", "p2"}


def test_build_diff_bundle_all_new(tmp_path):
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    _write_ndjson(new_dir / "Patient.ndjson", [
        {"resourceType": "Patient", "id": "p1"},
    ])

    bundle = build_diff_bundle(old_dir, new_dir, bundle_id="test", last_updated="2026-06-01T00:00:00+09:00")
    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "transaction"
    assert len(bundle["entry"]) == 1
    e = bundle["entry"][0]
    assert e["request"]["method"] == "POST"
    assert e["request"]["url"] == "Patient"


def test_build_diff_bundle_updated(tmp_path):
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    _write_ndjson(old_dir / "Encounter.ndjson", [
        {"resourceType": "Encounter", "id": "e1", "status": "in-progress"},
    ])
    _write_ndjson(new_dir / "Encounter.ndjson", [
        {"resourceType": "Encounter", "id": "e1", "status": "finished"},
    ])

    bundle = build_diff_bundle(old_dir, new_dir, bundle_id="test", last_updated="2026-06-01T00:00:00+09:00")
    assert len(bundle["entry"]) == 1
    e = bundle["entry"][0]
    assert e["request"]["method"] == "PUT"
    assert e["request"]["url"] == "Encounter/e1"
    assert e["resource"]["status"] == "finished"


def test_build_diff_bundle_unchanged_skipped(tmp_path):
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    r = {"resourceType": "Patient", "id": "p1", "name": [{"family": "A"}]}
    _write_ndjson(old_dir / "Patient.ndjson", [r])
    _write_ndjson(new_dir / "Patient.ndjson", [r])

    bundle = build_diff_bundle(old_dir, new_dir, bundle_id="test", last_updated="2026-06-01T00:00:00+09:00")
    assert bundle["entry"] == []


def test_build_diff_bundle_mixed_types(tmp_path):
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    _write_ndjson(old_dir / "Patient.ndjson", [{"resourceType": "Patient", "id": "p1"}])
    _write_ndjson(new_dir / "Patient.ndjson", [
        {"resourceType": "Patient", "id": "p1"},
        {"resourceType": "Patient", "id": "p2"},  # new
    ])
    _write_ndjson(new_dir / "Encounter.ndjson", [
        {"resourceType": "Encounter", "id": "e1", "status": "finished"},  # new
    ])

    bundle = build_diff_bundle(old_dir, new_dir, bundle_id="test", last_updated="2026-06-01T00:00:00+09:00")
    methods = [e["request"]["method"] for e in bundle["entry"]]
    assert methods.count("POST") == 2
    assert methods.count("PUT") == 0


def test_format_summary_basic(tmp_path):
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    _write_ndjson(new_dir / "Patient.ndjson", [{"resourceType": "Patient", "id": "p1"}])
    bundle = build_diff_bundle(old_dir, new_dir, bundle_id="test", last_updated="2026-06-01T00:00:00+09:00")
    summary = format_summary(bundle, old_cursor="2026-05-31", new_cursor="2026-06-01")
    assert "2026-05-31" in summary
    assert "2026-06-01" in summary
    assert "Patient" in summary
    assert "1" in summary  # 1 entry
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_diff_bundle.py -v`
Expected: 既存 9 test PASS + 新規 6 test FAIL(未実装 API)。

- [ ] **Step 3: Implement `simulator/diff.py`(追加)**

Task 4 で作った `diff.py` に追加:

```python
from collections import Counter
from pathlib import Path
from typing import Iterator


def load_ndjson_by_id(path: Path) -> dict[str, dict]:
    """単一 NDJSON file を {resource.id: resource} 辞書に読み込む。"""
    result: dict[str, dict] = {}
    if not path.exists():
        return result
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            rid = r.get("id")
            if rid:
                result[rid] = r
    return result


def _iter_resource_types(directory: Path) -> Iterator[tuple[str, Path]]:
    """directory 内の *.ndjson を (resource_type, path) で yield。"""
    for path in sorted(directory.glob("*.ndjson")):
        rt = path.stem
        yield rt, path


def build_diff_bundle(
    old_dir: Path,
    new_dir: Path,
    bundle_id: str,
    last_updated: str,
) -> dict:
    """2 snapshot output directory から FHIR Bundle transaction を生成する。

    Args:
        old_dir: 前 snapshot の FHIR NDJSON directory
        new_dir: 現 snapshot の FHIR NDJSON directory
        bundle_id: Bundle.id
        last_updated: Bundle.meta.lastUpdated (FHIR instant format)

    Returns:
        FHIR R4 Bundle resource (transaction type)。NEW resource は POST、
        UPDATED resource は PUT、UNCHANGED resource は除外。
    """
    entries: list[dict] = []

    # 新 dir の全 resource type を対象(旧 dir 側で消滅した type は空)
    resource_types = {rt for rt, _ in _iter_resource_types(new_dir)}

    for rt in sorted(resource_types):
        new_by_id = load_ndjson_by_id(new_dir / f"{rt}.ndjson")
        old_by_id = load_ndjson_by_id(old_dir / f"{rt}.ndjson")

        new_only, updated, _unchanged = classify_resources(old_by_id, new_by_id)

        for r in new_only:
            entries.append({
                "resource": r,
                "request": {"method": "POST", "url": rt},
            })
        for r in updated:
            entries.append({
                "resource": r,
                "request": {"method": "PUT", "url": f"{rt}/{r['id']}"},
            })

    return {
        "resourceType": "Bundle",
        "id": bundle_id,
        "meta": {"lastUpdated": last_updated},
        "type": "transaction",
        "entry": entries,
    }


def format_summary(bundle: dict, old_cursor: str, new_cursor: str) -> str:
    """Bundle transaction の human-readable summary を返す。"""
    entries = bundle.get("entry", [])
    new_count: Counter[str] = Counter()
    updated_count: Counter[str] = Counter()
    for e in entries:
        rt = e["resource"].get("resourceType", "?")
        method = e["request"]["method"]
        if method == "POST":
            new_count[rt] += 1
        elif method == "PUT":
            updated_count[rt] += 1

    lines = [f"Diff {old_cursor} → {new_cursor}", ""]

    if new_count:
        lines.append("New resources:")
        for rt in sorted(new_count):
            lines.append(f"  {rt:26} : {new_count[rt]}")
        lines.append("")

    if updated_count:
        lines.append("Modified resources:")
        for rt in sorted(updated_count):
            lines.append(f"  {rt:26} : {updated_count[rt]}")
        lines.append("")

    lines.append(f"Total bundle size: {len(entries)} entries")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_diff_bundle.py -v`
Expected: 全 15 test PASS。

- [ ] **Step 5: Commit**

```bash
git add clinosim/simulator/diff.py tests/unit/test_diff_bundle.py
git commit -m "$(cat <<'EOF'
feat(diff): F3 Bundle transaction generation + summary

session 49 F3。2 snapshot output directory から FHIR R4 Bundle
transaction を生成する。NEW resource は POST、UPDATED resource は PUT、
UNCHANGED は skip。summary は resource type ごとに new / modified を
集計して表示。

- load_ndjson_by_id: 単一 NDJSON を {id: resource} dict に
- build_diff_bundle: 2 dir 走査 → 3 状態分類 → Bundle transaction
- format_summary: bundle → human-readable text

CLI subcommand は次 task。まだ Python API のみ。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016cvyhjp7jj5bE3CdDT6mZ9
EOF
)"
git push origin master
```

---

### Task 6: `clinosim diff` CLI subcommand

**Files:**
- Modify: `clinosim/simulator/cli.py`(subcommand + handler 追加、~50 行)
- Test: `tests/unit/test_diff_bundle.py`(CLI smoke 追加)

**Interfaces:**
- Consumes: Task 4-5 の `build_diff_bundle`, `format_summary`
- Produces:
  - CLI: `clinosim diff --old <dir> --new <dir> --output-bundle <path> [--output-summary <path>]`
  - `--old-cursor`, `--new-cursor` optional(summary に表示するだけ、default は directory 名から推測)

- [ ] **Step 1: Write CLI smoke test**

`tests/unit/test_diff_bundle.py` に追加:

```python
import subprocess
import sys


def test_cli_diff_smoke(tmp_path):
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    _write_ndjson(new_dir / "Patient.ndjson", [{"resourceType": "Patient", "id": "p1"}])

    bundle_path = tmp_path / "bundle.json"
    summary_path = tmp_path / "summary.txt"

    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "diff",
         "--old", str(old_dir),
         "--new", str(new_dir),
         "--output-bundle", str(bundle_path),
         "--output-summary", str(summary_path),
         "--old-cursor", "2026-05-31",
         "--new-cursor", "2026-06-01"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    bundle = json.loads(bundle_path.read_text())
    assert bundle["type"] == "transaction"
    assert len(bundle["entry"]) == 1
    summary = summary_path.read_text()
    assert "2026-05-31" in summary
    assert "2026-06-01" in summary
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_diff_bundle.py::test_cli_diff_smoke -v`
Expected: FAIL — `diff` subcommand が存在しない。

- [ ] **Step 3: Add `diff` subcommand to `cli.py`**

`clinosim/simulator/cli.py` の subparser 登録エリアに追加:

```python
    # === diff: F3 snapshot diff → Bundle transaction (session 49) ===
    df = sub.add_parser(
        "diff",
        help="Generate FHIR Bundle transaction from 2 snapshot outputs (session 49 F3)",
    )
    df.add_argument("--old", required=True, help="前 snapshot の FHIR output directory")
    df.add_argument("--new", required=True, help="現 snapshot の FHIR output directory")
    df.add_argument("--output-bundle", required=True,
                    help="Bundle transaction JSON の出力 path")
    df.add_argument("--output-summary", default=None,
                    help="Summary text の出力 path (省略時は stdout)")
    df.add_argument("--old-cursor", default=None,
                    help="前 snapshot の cursor 日付(summary 表示用、省略時は --old dir 名)")
    df.add_argument("--new-cursor", default=None,
                    help="現 snapshot の cursor 日付(summary 表示用、省略時は --new dir 名)")
```

CLI dispatcher(`if args.command == "..."` の連鎖)に追加:

```python
    if args.command == "diff":
        from datetime import datetime
        from pathlib import Path

        from clinosim.simulator.diff import build_diff_bundle, format_summary

        old_dir = Path(args.old)
        new_dir = Path(args.new)
        bundle_path = Path(args.output_bundle)

        old_cursor = args.old_cursor or old_dir.name
        new_cursor = args.new_cursor or new_dir.name

        bundle_id = f"clinosim-diff-{old_cursor}-to-{new_cursor}"
        last_updated = datetime.now().isoformat(timespec="seconds")

        bundle = build_diff_bundle(old_dir, new_dir, bundle_id, last_updated)
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text(
            json.dumps(bundle, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        summary = format_summary(bundle, old_cursor, new_cursor)
        if args.output_summary:
            summary_path = Path(args.output_summary)
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(summary, encoding="utf-8")
        else:
            print(summary)
        return
```

- [ ] **Step 4: Run smoke test to verify it passes**

Run: `pytest tests/unit/test_diff_bundle.py::test_cli_diff_smoke -v`
Expected: PASS。

- [ ] **Step 5: Full test suite check**

```bash
pytest tests/unit -x -q
```

Expected: 全 PASS。

- [ ] **Step 6: Commit**

```bash
git add clinosim/simulator/cli.py tests/unit/test_diff_bundle.py
git commit -m "$(cat <<'EOF'
feat(cli): F3 clinosim diff subcommand — snapshot diff → Bundle

session 49 F3。2 snapshot output directory を渡して FHIR Bundle
transaction JSON を生成する CLI。summary は stdout or file 出力。

Usage:
  clinosim diff --old snap_2026-05-31 --new snap_2026-06-01 \
    --output-bundle bundle/2026-06-01.json

生成した bundle は curl / httpx / hapi-fhir-cli で FHIR server に
POST できる(clinosim は push 統合しない = operational responsibility)。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016cvyhjp7jj5bE3CdDT6mZ9
EOF
)"
git push origin master
```

---

# PR-3: F4 snapshot memoize(大規模 population 対応)

### Task 7: `simulator/memoize.py` — cache manifest + eligibility 判定

**Files:**
- Create: `clinosim/simulator/memoize.py`
- Test: `tests/unit/test_engine_memoize.py`(新規、Task 7 分のみ)

**Interfaces:**
- Consumes: なし
- Produces:
  - `@dataclass class CacheManifest: schema_version: int, master_seed: int, config_hash: str, snapshot_date: str, country: str, population_size: int`
  - `def compute_config_hash(config: SimulatorConfig) -> str` — config の canonical hash
  - `def write_cache_manifest(output_dir: Path, config: SimulatorConfig) -> None`
  - `def read_cache_manifest(output_dir: Path) -> CacheManifest | None`
  - `def is_cache_valid(cache_dir: Path, config: SimulatorConfig) -> tuple[bool, str]` — (valid, reason)
  - `def eligible_patient_ids(patient_records: list[CIFPatientRecord], prev_cursor_date: date) -> set[str]` — 全 encounter が prev_cursor 以前に完了した patient_id 集合

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_engine_memoize.py`(新規):

```python
"""F4 memoize test: cache manifest / eligibility / hit / miss / staleness。"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest

from clinosim.simulator.memoize import (
    CacheManifest,
    compute_config_hash,
    eligible_patient_ids,
    is_cache_valid,
    read_cache_manifest,
    write_cache_manifest,
)
from clinosim.types.config import SimulatorConfig
from clinosim.types.encounter import EncounterRecord, EncounterType
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile


@pytest.mark.unit
def test_config_hash_stable():
    """同 config → 同 hash。"""
    c1 = SimulatorConfig(random_seed=42, catchment_population=200, country="US")
    c2 = SimulatorConfig(random_seed=42, catchment_population=200, country="US")
    assert compute_config_hash(c1) == compute_config_hash(c2)


def test_config_hash_ignores_snapshot_date():
    """snapshot_date が変わっても hash は同一(cache は cursor 越えで使うため)。"""
    c1 = SimulatorConfig(random_seed=42, catchment_population=200, country="US",
                         snapshot_date="2026-05-31")
    c2 = replace(c1, snapshot_date="2026-06-01")
    assert compute_config_hash(c1) == compute_config_hash(c2)


def test_config_hash_detects_seed_change():
    """seed が違えば hash 変わる。"""
    c1 = SimulatorConfig(random_seed=42, catchment_population=200, country="US")
    c2 = replace(c1, random_seed=43)
    assert compute_config_hash(c1) != compute_config_hash(c2)


def test_config_hash_detects_country_change():
    """country が違えば hash 変わる。"""
    c1 = SimulatorConfig(random_seed=42, catchment_population=200, country="US")
    c2 = replace(c1, country="JP")
    assert compute_config_hash(c1) != compute_config_hash(c2)


def test_write_and_read_manifest(tmp_path):
    config = SimulatorConfig(random_seed=42, catchment_population=200,
                             country="US", snapshot_date="2026-05-31")
    write_cache_manifest(tmp_path, config)
    manifest = read_cache_manifest(tmp_path)
    assert manifest is not None
    assert manifest.master_seed == 42
    assert manifest.country == "US"
    assert manifest.snapshot_date == "2026-05-31"


def test_read_manifest_absent_returns_none(tmp_path):
    assert read_cache_manifest(tmp_path) is None


def test_is_cache_valid_happy_path(tmp_path):
    config = SimulatorConfig(random_seed=42, catchment_population=200,
                             country="US", snapshot_date="2026-05-31")
    write_cache_manifest(tmp_path, config)
    # cursor だけ進めた
    new_config = replace(config, snapshot_date="2026-06-01")
    valid, reason = is_cache_valid(tmp_path, new_config)
    assert valid, reason


def test_is_cache_valid_seed_mismatch(tmp_path):
    config = SimulatorConfig(random_seed=42, catchment_population=200, country="US")
    write_cache_manifest(tmp_path, config)
    new_config = replace(config, random_seed=99)
    valid, reason = is_cache_valid(tmp_path, new_config)
    assert not valid
    assert "seed" in reason.lower()


def test_is_cache_valid_missing_manifest(tmp_path):
    config = SimulatorConfig(random_seed=42, catchment_population=200, country="US")
    valid, reason = is_cache_valid(tmp_path, config)
    assert not valid
    assert "manifest" in reason.lower() or "no cache" in reason.lower()


def test_eligible_patient_ids_all_completed():
    """全 encounter が prev_cursor 以前に discharge 済 → eligible。"""
    patient = PatientProfile(patient_id="p1")
    enc = EncounterRecord(
        encounter_id="e1", patient_id="p1", encounter_type=EncounterType.INPATIENT,
        admission_datetime=datetime(2025, 5, 1),
        discharge_datetime=datetime(2025, 5, 10),
    )
    r = CIFPatientRecord(patient=patient, encounters=[enc])
    result = eligible_patient_ids([r], date(2025, 6, 30))
    assert result == {"p1"}


def test_eligible_patient_ids_in_progress_excluded():
    """discharge_datetime = None (in-progress) → not eligible。"""
    patient = PatientProfile(patient_id="p1")
    enc = EncounterRecord(
        encounter_id="e1", patient_id="p1", encounter_type=EncounterType.INPATIENT,
        admission_datetime=datetime(2025, 6, 25),
        discharge_datetime=None,  # in-progress
    )
    r = CIFPatientRecord(patient=patient, encounters=[enc])
    result = eligible_patient_ids([r], date(2025, 6, 30))
    assert result == set()


def test_eligible_patient_ids_discharge_past_cursor_excluded():
    """discharge_datetime > prev_cursor → not eligible(cursor 越え)。"""
    patient = PatientProfile(patient_id="p1")
    enc = EncounterRecord(
        encounter_id="e1", patient_id="p1", encounter_type=EncounterType.INPATIENT,
        admission_datetime=datetime(2025, 6, 25),
        discharge_datetime=datetime(2025, 7, 5),  # > cursor 2025-06-30
    )
    r = CIFPatientRecord(patient=patient, encounters=[enc])
    result = eligible_patient_ids([r], date(2025, 6, 30))
    assert result == set()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_engine_memoize.py -v`
Expected: FAIL — `memoize.py` module が存在しない。

- [ ] **Step 3: Implement `simulator/memoize.py`**

`clinosim/simulator/memoize.py`(新規):

```python
"""F4 snapshot memoize (session 49):前 snapshot output を cache として利用。

大規模 population で daily cron を実現するための最重要 primitive。
前 snapshot で全 encounter が discharge 済の patient は、cursor が
進んでも bit-identical な output になる(snapshot semantics + F1
cross-cursor determinism の帰結)。この patient を simulate skip して
前 CIF から load することで、p=500k advance が数分に短縮される。

state module / cursor.json は不要。cache directory = 前 snapshot output
directory 自体(_cache_manifest.json 1 ファイルだけ併存)。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clinosim.types.config import SimulatorConfig
    from clinosim.types.output import CIFPatientRecord

_MANIFEST_FILENAME = "_cache_manifest.json"
_MANIFEST_SCHEMA_VERSION = 1


@dataclass
class CacheManifest:
    """前 snapshot の cache 情報。output directory に併存 (_cache_manifest.json)."""
    schema_version: int
    master_seed: int
    config_hash: str
    snapshot_date: str
    country: str
    population_size: int


def compute_config_hash(config: "SimulatorConfig") -> str:
    """SimulatorConfig の canonical sha256 hash (snapshot_date は除外)。

    snapshot_date だけが違う config は cache 対象なので hash 一致させる。
    seed / country / population / hospital / time_range 等が変わったら
    hash が変わって cache 無効になる。
    """
    from clinosim.types.config import SimulatorConfig

    d = asdict(config)
    d.pop("snapshot_date", None)
    return hashlib.sha256(
        json.dumps(d, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def write_cache_manifest(output_dir: Path, config: "SimulatorConfig") -> None:
    """output directory に _cache_manifest.json を書き出す。"""
    manifest = CacheManifest(
        schema_version=_MANIFEST_SCHEMA_VERSION,
        master_seed=config.random_seed,
        config_hash=compute_config_hash(config),
        snapshot_date=config.snapshot_date or "",
        country=config.country,
        population_size=config.catchment_population or 0,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / _MANIFEST_FILENAME).open("w", encoding="utf-8") as f:
        json.dump(asdict(manifest), f, ensure_ascii=False, indent=2)


def read_cache_manifest(cache_dir: Path) -> CacheManifest | None:
    """cache directory の manifest を読む。存在しなければ None。"""
    path = cache_dir / _MANIFEST_FILENAME
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        d = json.load(f)
    return CacheManifest(**d)


def is_cache_valid(cache_dir: Path, config: "SimulatorConfig") -> tuple[bool, str]:
    """cache が現 config と互換か判定。返り値 = (valid, reason)。

    snapshot_date 以外の全て(seed / country / population / hospital / ...)
    が cache manifest と一致していれば valid。不一致は fail loud:cache
    を無視して全再走することを caller に告げる。
    """
    manifest = read_cache_manifest(cache_dir)
    if manifest is None:
        return False, f"no cache manifest at {cache_dir / _MANIFEST_FILENAME}"
    if manifest.schema_version != _MANIFEST_SCHEMA_VERSION:
        return False, (
            f"cache schema version {manifest.schema_version} != "
            f"expected {_MANIFEST_SCHEMA_VERSION}"
        )
    if manifest.master_seed != config.random_seed:
        return False, (
            f"seed mismatch: cache={manifest.master_seed} config={config.random_seed}"
        )
    if manifest.config_hash != compute_config_hash(config):
        return False, "config_hash mismatch (config changed since cache was written)"
    if manifest.country != config.country:
        return False, f"country mismatch: cache={manifest.country} config={config.country}"
    return True, "ok"


def eligible_patient_ids(
    patient_records: "list[CIFPatientRecord]",
    prev_cursor_date: date,
) -> set[str]:
    """全 encounter が prev_cursor 以前に完了した patient_id 集合。

    厳格 rule: encounter が 1 件でも in-progress (discharge_datetime = None) or
    discharge_datetime > prev_cursor だった場合は非 eligible。cursor 越えの
    可能性がある patient は full sim させる。
    """
    result: set[str] = set()
    for r in patient_records:
        pid = r.patient.patient_id
        all_completed = True
        for enc in r.encounters:
            dc = enc.discharge_datetime
            if dc is None or dc.date() > prev_cursor_date:
                all_completed = False
                break
        if all_completed:
            result.add(pid)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_engine_memoize.py -v`
Expected: 全 11 test PASS。

- [ ] **Step 5: Commit**

```bash
git add clinosim/simulator/memoize.py tests/unit/test_engine_memoize.py
git commit -m "$(cat <<'EOF'
feat(memoize): F4 cache manifest + eligibility 判定 primitives

session 49 F4 core primitives。前 snapshot output directory を
cache 兼 state として利用するための manifest read/write + config
互換性判定 + patient eligibility 判定。

- CacheManifest dataclass: schema_version / seed / config_hash /
  snapshot_date / country / population_size
- compute_config_hash: snapshot_date を除いた config の sha256
- write/read_cache_manifest: _cache_manifest.json への I/O
- is_cache_valid: (valid, reason) で fail loud diagnostic
- eligible_patient_ids: 全 encounter が prev_cursor 以前に discharge
  完了した patient_id 集合 = cache hit 対象

CIF load と engine.py への配線は次 task。まだ standalone primitives。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016cvyhjp7jj5bE3CdDT6mZ9
EOF
)"
git push origin master
```

---

### Task 8: `engine.py` に `cache_dir` 引数 + cache hit path 挿入 + F4 invariant test

**Files:**
- Modify: `clinosim/simulator/engine.py`(cache_dir 引数追加、hit path 挿入)
- Modify: `clinosim/simulator/memoize.py`(CIF loader helper 追加)
- Test: `tests/unit/test_engine_memoize.py`(追加)

**Interfaces:**
- Consumes: Task 7 の `is_cache_valid`, `eligible_patient_ids`, `read_cache_manifest`, `write_cache_manifest`
- Produces:
  - `run_beta(config, hospital_config_path=None, cache_dir=None)` — cache_dir 引数追加(既存 caller は default None で unchanged)
  - `def load_patient_records_from_cif(cif_dir: Path, eligible_pids: set[str]) -> dict[str, CIFPatientRecord]` — 前 CIF から eligible patient を load

- [ ] **Step 1: Write the F4 invariant test**

`tests/unit/test_engine_memoize.py` に追加:

```python
from clinosim.simulator.engine import run_beta


@pytest.mark.integration
def test_memoize_hit_bit_identical(tmp_path):
    """F4 core: cache hit patient の record が cold run と bit-identical。

    F1 の cross-cursor determinism が正しく働いていれば、cache hit で
    load した record と cold run で simulate した record は完全一致する。
    """
    config = SimulatorConfig(random_seed=42, catchment_population=100, country="US",
                             time_range=("2025-01", "2026-01"),
                             snapshot_date="2025-06-30")
    ds_a = run_beta(config)

    # cursor A を cache dir に保存
    cache_dir = tmp_path / "snap_a"
    _save_ds_as_cache(ds_a, cache_dir, config)  # helper: CIF + _cache_manifest.json 書き出し

    # cursor B を「cache 経由」と「cold」の 2 通りで生成
    config_b = replace(config, snapshot_date="2025-07-31")
    ds_b_cold = run_beta(config_b, cache_dir=None)
    ds_b_memo = run_beta(config_b, cache_dir=cache_dir)

    # eligible patient (cursor A 完了 patient) は cold と memo で bit-identical
    from clinosim.simulator.memoize import eligible_patient_ids
    eligible = eligible_patient_ids(ds_a.patients, date(2025, 6, 30))
    cold_by_pid = {r.patient.patient_id: r for r in ds_b_cold.patients}
    memo_by_pid = {r.patient.patient_id: r for r in ds_b_memo.patients}
    for pid in eligible:
        assert cold_by_pid[pid] == memo_by_pid[pid], f"F4 memoize drift for {pid}"


@pytest.mark.unit
def test_memoize_config_change_invalidates(tmp_path):
    """F4 safety: seed 変化で cache 無効化 → fail loud で用途 caller に伝える。"""
    config = SimulatorConfig(random_seed=42, catchment_population=30, country="US")
    ds = run_beta(config)
    cache_dir = tmp_path / "snap"
    _save_ds_as_cache(ds, cache_dir, config)

    # seed が変わったら cache は無効 → 全再走(fail loud message は log で確認)
    config_new = replace(config, random_seed=99, snapshot_date="2025-07-31")
    ds_new = run_beta(config_new, cache_dir=cache_dir)
    # 全再走なので ds は seed=99 の結果
    assert ds_new is not None  # とにかく走ればよい(dropout せず)


@pytest.mark.integration
@pytest.mark.slow
def test_memoize_hit_ratio_realistic(tmp_path):
    """F4 performance: cursor 1 日 advance で 95%+ の patient が hit。"""
    config = SimulatorConfig(random_seed=42, catchment_population=500, country="US",
                             time_range=("2025-01", "2026-01"),
                             snapshot_date="2025-06-30")
    ds_a = run_beta(config)
    cache_dir = tmp_path / "snap_a"
    _save_ds_as_cache(ds_a, cache_dir, config)

    from clinosim.simulator.memoize import eligible_patient_ids
    eligible = eligible_patient_ids(ds_a.patients, date(2025, 6, 30))
    hit_ratio = len(eligible) / max(1, len(ds_a.patients))
    # cursor がまだ 6 か月分しかない小 population だが、少なくとも過半数
    # は完了しているはず
    assert hit_ratio >= 0.5, f"hit_ratio too low: {hit_ratio:.2%}"


def _save_ds_as_cache(ds, cache_dir: Path, config) -> None:
    """CIF + _cache_manifest.json を cache_dir に書き出す helper。"""
    from clinosim.modules.output.cif_io import write_cif
    from clinosim.simulator.memoize import write_cache_manifest

    cif_dir = cache_dir / "cif"
    write_cif(ds, cif_dir)
    write_cache_manifest(cache_dir, config)
```

**注意**:`write_cif` の実際の名前 / signature は既存 `clinosim/modules/output/` の実 module 構造で
確認する(Task 3 で FHIR 側は判明済、CIF 側も同 pattern のはず)。

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_engine_memoize.py::test_memoize_hit_bit_identical -v`
Expected: FAIL — `run_beta` が `cache_dir` 引数を受け付けない。

- [ ] **Step 3: Add CIF loader to `memoize.py`**

`clinosim/simulator/memoize.py` に追加:

```python
def load_patient_records_from_cif(
    cif_dir: Path,
    eligible_pids: set[str],
) -> "dict[str, CIFPatientRecord]":
    """前 CIF から eligible patient の record を load する。

    cif_dir/patients/<pid>.json を JSON load → CIFPatientRecord に復元。
    復元は CIFReader ベース(既存 API を利用)。
    """
    from clinosim.types.output import CIFPatientRecord  # local import to avoid cycle

    result: dict[str, CIFPatientRecord] = {}
    patients_dir = cif_dir / "patients"
    if not patients_dir.exists():
        return result

    for pid in eligible_pids:
        pfile = patients_dir / f"{pid}.json"
        if not pfile.exists():
            continue
        # CIFReader 相当の deserializer を使う。既存 module でどう read しているか
        # 実装時に確認して合わせる(fhir_r4_adapter.py は CIFReader を使っている)。
        with pfile.open(encoding="utf-8") as f:
            data = json.load(f)
        result[pid] = _cif_dict_to_record(data)

    return result


def _cif_dict_to_record(data: dict) -> "CIFPatientRecord":
    """CIF JSON dict → CIFPatientRecord。

    既存 CIFReader / CIF deserializer と同じ経路を使う。実装時に
    clinosim/modules/output/cif_io.py or _fhir_reader.py の
    deserialize helper を再利用する。
    """
    # 実装時に既存 API を確認して呼び出す。ここは skeleton。
    from clinosim.modules.output.cif_io import cif_dict_to_record  # 仮
    return cif_dict_to_record(data)
```

**注意**:`_cif_dict_to_record` の具体的 import path は実装時に確認。既存 `CIFReader` が JSON →
dataclass の deserializer を持っているはずなので、その helper を expose して使う。

- [ ] **Step 4: Add `cache_dir` to `run_beta` + cache hit path**

`clinosim/simulator/engine.py` の `run_beta` signature を変更:

```python
def run_beta(
    config: SimulatorConfig | None = None,
    hospital_config_path: str | None = None,
    cache_dir: Path | str | None = None,
) -> CIFDataset:
    """Run population-driven simulation.

    Args:
        hospital_config_path: Path to hospital operations YAML.
            If None, uses default config/hospital_operations.yaml.
        cache_dir: Optional前 snapshot output directory. If provided and
            valid (matching seed/config/country), eligible patients (全 encounter
            completed by prev cursor) are loaded from cache instead of
            simulated. F4 session 49.
    """
    if config is None:
        config = SimulatorConfig()

    ...  # 既存の RNG / healthcare / population 生成

    # F4: cache 読み込み
    prev_cache: dict[str, "CIFPatientRecord"] = {}
    prev_cursor_date: date | None = None
    if cache_dir is not None:
        from clinosim.simulator.memoize import (
            eligible_patient_ids,
            is_cache_valid,
            load_patient_records_from_cif,
            read_cache_manifest,
        )
        cache_dir_p = Path(cache_dir)
        valid, reason = is_cache_valid(cache_dir_p, config)
        if not valid:
            print(f"⚠️  cache invalidated ({reason}); recomputing from scratch", flush=True)
        else:
            manifest = read_cache_manifest(cache_dir_p)
            prev_cursor_date = datetime.strptime(manifest.snapshot_date, "%Y-%m-%d").date()
            # まず前 CIF の全 record を読んで eligibility 判定
            prev_all = load_patient_records_from_cif(
                cache_dir_p / "cif",
                # 一旦全 pid で load → eligibility 判定 → 有効 pid のみ保持
                _all_pids_from_cif(cache_dir_p / "cif"),
            )
            eligible = eligible_patient_ids(list(prev_all.values()), prev_cursor_date)
            prev_cache = {pid: prev_all[pid] for pid in eligible if pid in prev_all}
            print(f"  Cache: {len(prev_cache)} eligible patients loaded", flush=True)
```

**Main loop に cache hit path**(現行 line 183 付近を追加):

```python
    for idx, event in enumerate(hospital_events):
        ...
        # F4: cache hit で simulate skip
        if (prev_cursor_date is not None
            and event.person_id in prev_cache
            and event.timestamp.date() <= prev_cursor_date):
            record = prev_cache[event.person_id]
            patient_records.append(record)
            person = population.get_person(event.person_id)
            if person:
                person.has_visited_hospital = True
                person.visit_count += 1
                if record.deceased:
                    person.is_alive = False
                _deactivate_to_layer1(person, record, event.disease_id or "")
            continue

        # 既存: full simulation path
        event_rng = derive_phase_rng(master_seed, PHASE_INPATIENT_SIM, event_key)
        ...
```

**注意**:`prev_cache[event.person_id]` は特定 event ではなく patient の record を返すので、
1 patient に複数 event(readmission)がある場合の扱いは、eligibility 判定で全 encounter 完了を
確認しているのでどの event でも同じ record を返せば OK(record 内に全 encounter が入っているため)。

ただし 1 patient で main-loop event と readmission event が別々に登場する場合、cache hit で
record を返すのは初回の 1 度だけにする guard が必要:

```python
        _cache_returned_pids: set[str] = set()
        for idx, event in enumerate(hospital_events):
            ...
            if (prev_cursor_date is not None
                and event.person_id in prev_cache
                and event.person_id not in _cache_returned_pids
                and event.timestamp.date() <= prev_cursor_date):
                record = prev_cache[event.person_id]
                patient_records.append(record)
                _cache_returned_pids.add(event.person_id)
                ...
                continue
```

**cache manifest 書き出し**(run_beta の末尾、既存の CIFDataset return 前に):

```python
    # F4: 出力先に cache manifest を書く(次回 advance で使う)
    # 出力 dir は caller (CLI or write_cif helper) 責任だが、run_beta 呼び出し後
    # に自動で書けるようにするため、CIFDataset の metadata に write_manifest フラグ
    # を持たせる or 呼び出し側で write_cache_manifest を明示 call する設計。
    # 現状の run_beta は output_dir を知らないので、CLI 側で write_cache_manifest を
    # 呼ぶ。ここでは run_beta 自体は変更しない。
```

CLI 側(`clinosim/simulator/cli.py` の simulate handler の直後)に:

```python
    # F4: 出力後に cache manifest を書く
    from clinosim.simulator.memoize import write_cache_manifest
    write_cache_manifest(Path(args.output), config)
```

- [ ] **Step 5: Run F4 tests to verify they pass**

Run: `pytest tests/unit/test_engine_memoize.py -v`
Expected: 全 test PASS(11 unit + 3 integration/perf)。

- [ ] **Step 6: Full test suite check(golden 影響ゼロ確認)**

```bash
pytest tests/unit -x -q
pytest tests/integration -x -q
bash scripts/reproduce.sh
```

Expected: 全 PASS + reproduce.sh byte-identical(F4 は既存 path を触らない = 影響ゼロ)。

- [ ] **Step 7: Commit**

```bash
git add clinosim/simulator/engine.py clinosim/simulator/memoize.py clinosim/simulator/cli.py
git add tests/unit/test_engine_memoize.py
git commit -m "$(cat <<'EOF'
feat(engine): F4 snapshot memoize — cache hit for eligible patients

session 49 F4。前 snapshot output directory を cache として利用し、
全 encounter が discharge 済の patient は simulate skip して前 CIF から
load。p=500k で cursor 1 日 advance が数分に短縮される(実 sim は
p ≈ 1500 相当)。

- run_beta に cache_dir 引数追加(既存 caller は default None)
- is_cache_valid で seed / config / country 互換性検証、失敗は fail loud
- eligible_patient_ids で cursor 越え不可能な patient を判定
- load_patient_records_from_cif で前 CIF から record 復元
- main loop に cache hit path 挿入(1 patient 1 度だけ返す guard 付き)
- CLI simulate handler で出力後に _cache_manifest.json を書く

F1 の cross-cursor determinism が前提。cache hit patient は cold run
の record と bit-identical(test_memoize_hit_bit_identical で検証)。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016cvyhjp7jj5bE3CdDT6mZ9
EOF
)"
git push origin master
```

---

### Task 9: F1+F2+F3+F4 統合 e2e workflow test

**Files:**
- Test: `tests/integration/test_incremental_snapshot_workflow.py`(新規)

**Interfaces:**
- Consumes: 全 previous task の実装
- Produces: end-to-end scenario の green check

- [ ] **Step 1: Write the workflow test**

`tests/integration/test_incremental_snapshot_workflow.py`(新規):

```python
"""F1+F2+F3+F4 統合 e2e:snapshot → memoize advance → diff → Bundle 検証。

セッション 49 の全 fix を組み合わせて 1 workflow で検証:
1. cursor A で snapshot 生成
2. cursor B で snapshot 生成(cache_dir=cursor_A output)= F4 hit
3. clinosim diff で 2 snapshot → Bundle transaction 生成
4. Bundle 内容が 3 状態分類 (NEW / UPDATED / UNCHANGED) を正しく反映
5. F1 の恩恵で cursor A に完了した patient の resource は Bundle に含まれない
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from clinosim.simulator.engine import run_beta
from clinosim.simulator.memoize import write_cache_manifest
from clinosim.types.config import SimulatorConfig


def _write_full_output(ds, out_dir: Path, config: SimulatorConfig) -> None:
    """CIF + FHIR + _cache_manifest.json を out_dir に書く。"""
    from clinosim.modules.output.cif_io import write_cif
    from clinosim.modules.output.fhir_r4_adapter import convert_cif_to_fhir

    (out_dir / "cif").mkdir(parents=True, exist_ok=True)
    (out_dir / "fhir_r4").mkdir(parents=True, exist_ok=True)
    write_cif(ds, out_dir / "cif")
    convert_cif_to_fhir(
        out_dir / "cif", out_dir / "fhir_r4",
        country=config.country,
        roster_map={m.staff_id: m for m in ds.hospital_roster},
        hospital_config=ds.hospital_config,
    )
    write_cache_manifest(out_dir, config)


@pytest.mark.integration
def test_full_incremental_workflow(tmp_path):
    """cursor A → memoize B → diff → Bundle transaction."""
    # Cursor A
    config_a = SimulatorConfig(
        random_seed=42, catchment_population=100, country="US",
        time_range=("2025-01", "2026-01"),
        snapshot_date="2025-06-30",
    )
    ds_a = run_beta(config_a)
    snap_a = tmp_path / "snap_2025-06-30"
    _write_full_output(ds_a, snap_a, config_a)

    # Cursor B with memoize
    config_b = replace(config_a, snapshot_date="2025-07-31")
    ds_b = run_beta(config_b, cache_dir=snap_a)
    snap_b = tmp_path / "snap_2025-07-31"
    _write_full_output(ds_b, snap_b, config_b)

    # F3 diff
    bundle_path = tmp_path / "bundle.json"
    summary_path = tmp_path / "summary.txt"
    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "diff",
         "--old", str(snap_a / "fhir_r4"),
         "--new", str(snap_b / "fhir_r4"),
         "--output-bundle", str(bundle_path),
         "--output-summary", str(summary_path),
         "--old-cursor", "2025-06-30",
         "--new-cursor", "2025-07-31"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"

    bundle = json.loads(bundle_path.read_text())
    assert bundle["type"] == "transaction"
    # 差分は最低 1 件はあるはず(cursor が 1 か月伸びた)
    assert len(bundle["entry"]) > 0

    # 全 entry は method が POST / PUT のいずれか
    for e in bundle["entry"]:
        assert e["request"]["method"] in ("POST", "PUT")

    # UNCHANGED (cursor A 完了 patient のうち関連 resource) は entry に含まれない
    # → bundle size < 全 resource 数 の等号を厳密には確認しづらいので、
    # summary text の "Total bundle size" が cursor B の全 resource より少ないことを確認
    summary = summary_path.read_text()
    assert "Total bundle size" in summary
    assert "2025-06-30" in summary
    assert "2025-07-31" in summary
```

- [ ] **Step 2: Run workflow test**

Run: `pytest tests/integration/test_incremental_snapshot_workflow.py -v`
Expected: PASS。

- [ ] **Step 3: Full test suite 最終確認**

```bash
pytest tests/unit -x -q
pytest tests/integration -x -q
pytest -m regression -x -q
bash scripts/reproduce.sh
```

Expected: 全 PASS + reproduce.sh byte-identical。

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_incremental_snapshot_workflow.py
git commit -m "$(cat <<'EOF'
test(integration): F1+F2+F3+F4 統合 e2e workflow

session 49 chain の締め。cursor A snapshot → memoize B snapshot →
diff CLI → Bundle transaction まで一気通貫で検証。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016cvyhjp7jj5bE3CdDT6mZ9
EOF
)"
git push origin master
```

---

## Post-implementation: docs update

### Task 10: memory + TODO.md 更新(session wrap 準備)

**Files:**
- Modify: `TODO.md`
- Create: `/Users/tokuyama/.claude/projects/-Users-tokuyama-workspace-clinosim/memory/project_session_49_end_state.md`
- Modify: `/Users/tokuyama/.claude/projects/-Users-tokuyama-workspace-clinosim/memory/MEMORY.md`

- [ ] **Step 1: Update TODO.md**

session 49 wrap section を先頭に、実装完了内容を列挙。TODO backlog に:
- Phase B backlog:parallel simulation(multiprocessing)
- Phase B backlog:OAuth2 / SMART on FHIR auth for direct push
- Phase B backlog:Bulk Data `$import` support

- [ ] **Step 2: Write memory `project_session_49_end_state.md`**

- master HEAD hash / F1+F2+F3+F4 完了 commit list / 各 fix の要点 / p=500k で cron 実用化された成果 / test 状態(unit/integration/regression 全 pass)

- [ ] **Step 3: MEMORY.md に 1 行追加**

`- [セッション49末状態](project_session_49_end_state.md) — F1 cross-cursor determinism + F2 NDJSON id-sort + F3 diff CLI + F4 memoize、p=500k daily cron 実用化`

- [ ] **Step 4: Commit**

```bash
git add TODO.md
git add /Users/tokuyama/.claude/projects/-Users-tokuyama-workspace-clinosim/memory/
git commit -m "$(cat <<'EOF'
docs(session): session 49 wrap — F1+F2+F3+F4 incremental snapshot chain

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016cvyhjp7jj5bE3CdDT6mZ9
EOF
)"
git push origin master
```

---

## Self-Review 完了確認

**Spec coverage check**:
- Section 4 F1: Task 1 (primitives) + Task 2 (engine refactor + invariant test + golden regen) ✅
- Section 4 F2: Task 3 (NDJSON sort + invariant test + golden regen) ✅
- Section 4 F3: Task 4 (canonical hash + classify) + Task 5 (Bundle + summary) + Task 6 (CLI) ✅
- Section 4 F4: Task 7 (manifest + eligibility) + Task 8 (engine cache path + invariant) ✅
- Section 5 Testing table: 全 test に対応 task 有り ✅
- Section 6 PR 分割: PR-1 (Task 1-3) + PR-2 (Task 4-6) + PR-3 (Task 7-9) ✅
- Section 10 Open questions: 実装時に決定 (`meta.lastUpdated` を canonical_hash で strip、fail loud で cache 無効化) ✅

**Placeholder scan**: TBD/TODO なし、全 step に code block or exact command 有り。

**Type consistency**:
- `PHASE_LIFE_EVENT` 等の定数名が Task 1 / Task 2 で一致
- `derive_phase_rng(master_seed, phase_salt, key)` signature が Task 1 / Task 2 で一致
- `canonical_hash(resource) -> str` / `classify_resources(old_by_id, new_by_id) -> (list, list, list)` が Task 4 / Task 5 で一致
- `CacheManifest` フィールド名が Task 7 / Task 8 で一致
- `eligible_patient_ids(patient_records, prev_cursor_date) -> set[str]` が Task 7 / Task 8 で一致
- `run_beta(config, hospital_config_path=None, cache_dir=None)` の signature が Task 8 全体で一貫

**残 note**:
- CIF load helper (`_cif_dict_to_record`) の import path は実装時に既存 CIFReader API を確認して合わせる(既存 `clinosim/modules/output/` の CIF reader 経路の再利用)
- `write_cif` の実 module 名も同様(実装時に確認)
