# Incremental snapshot diff design (F1 + F2 + F3 + F4)

**Date**: 2026-07-13
**Author**: session 49
**Status**: draft (design approved by user 2026-07-13、F4 memoize 追加 approved 同日)
**Target**: session 50〜 で分割実装
**Scope**: cursor 移動時の cross-cursor byte-identity 保証 + NDJSON 出力の順序安定化 + snapshot diff → FHIR Bundle transaction 生成 CLI + 前 snapshot output を cache として snapshot memoize による大規模 population 対応

## 1. Goal

`master_seed + config + snapshot_date` から決定論的に生成される FHIR スナップショット同士の差分を、
FHIR server に安全に append できるようにする。

**具体的 user story**:
1. 2025-06-01 → 2026-05-31 の 1 年分バッチを `--snapshot 2026-05-31` で生成
2. 翌日 `--snapshot 2026-06-01` で再生成
3. `clinosim diff` で 2 出力の差分を FHIR Bundle transaction として抽出
4. user 側 cron から `curl -X POST` で FHIR server に append(bundle は atomic transaction)

## 2. なぜこれは operational cover なのか — 大掛かりな state module は不要

- clinosim は既に **決定論**:同 seed + config + snapshot_date → byte-identical
- cursor 移動 = `--snapshot` の値を変えるだけ = clinosim 内部 state は不要
- 差分抽出は 2 output の diff、push は curl/httpx で運用側

したがって:
- ❌ `clinosim/state/` module 新設は不要
- ❌ `cursor.json` / `output_manifest.json` は不要
- ❌ `run_beta` の state-machine 分解は不要
- ❌ RNG state の pickle/base64 保存は不要
- ❌ per-patient state file は不要
- ❌ push 統合は不要(operational tooling)

**修正すべき点は 4 つ**(F1 / F2 / F3 / F4)。他は現行維持。

## 2.5. Scale 制約と F4 の必要性

user 想定 population は最大 500,000 級。全再走モデルの CPU コスト:

| population | 1 回走行 | 365 日 daily cron の年間 CPU |
|---|---|---|
| p=10,000 | ~16 分 | ~97 時間 |
| p=100,000 | ~2-3 時間 | ~1000 時間 |
| p=500,000 | ~13-24 時間 | ~200-350 日 CPU |
| p=1,000,000 | ~1-2 日 | 実質不可能 |

→ **daily cron を大規模 population で成立させるには F4 memoize が必須**。cursor 1 日 advance で
99.7%+ の患者は「前回 snapshot で discharge 完了 = 今回も同一 output」= simulate skip、前回 CIF から
load。p=500k, 1 日 advance が **数分**(実 sim は p≈1500 相当)に短縮。

## 3. 現状の問題(F1 が必要な理由)

`simulator/engine.py` の `run_beta` は 4 phase で master `rng` を串刺しに消費している:

| phase | 消費側 | 現状 |
|---|---|---|
| P1 monthly life event 生成 | `generate_monthly_events(pop, y, m, rng)` × N months | master rng 直接 |
| P2 hospital main loop | `_simulate_patient(patient, event, ..., rng)` × N events | master rng 直接 |
| P3 readmission 評価 | `_evaluate_readmission(record, person, ..., rng)` × N records | master rng 直接 |
| P4 post-discharge outpatient / calendar / ED | `int(rng.integers(0, 45))` 等 | master rng 直接 |

**帰結**:cursor B が cursor A より extra 月分 event を extra 生成 → master rng 消費量が違う →
共有区間 event の同 patient で違う結果 → 「diff とれば追加分」の前提が壊れる。

現行 `reproduce.sh` は **同 snapshot_date** の byte-identity しかチェックしていない。**cursor 移動時の
共有区間 byte-identity** は保証されていない。

## 4. Fix scope

### F1: cross-cursor RNG determinism (AD-16 top-level 徹底)

phase salt + per-key sub-seed で **master rng を完全に迂回**。engine.py の 4 phase を全部 sub-seed 化。

#### 実装(seeding.py 拡張)

```python
# clinosim/simulator/seeding.py に追加
PHASE_LIFE_EVENT      = 0x504C4556  # "PLEV"
PHASE_INPATIENT_SIM   = 0x50494E50  # "PINP"
PHASE_READMISSION     = 0x50524541  # "PREA"
PHASE_OUTPATIENT_CAL  = 0x504F5054  # "POPT"
PHASE_ED_VISIT        = 0x50454456  # "PEDV"

_PHASE_OFFSETS = {
    "life_event": PHASE_LIFE_EVENT,
    "inpatient_sim": PHASE_INPATIENT_SIM,
    "readmission": PHASE_READMISSION,
    "outpatient_calendar": PHASE_OUTPATIENT_CAL,
    "ed_visit": PHASE_ED_VISIT,
}
assert len(set(_PHASE_OFFSETS.values())) == len(_PHASE_OFFSETS), \
    f"phase offset collision: {_PHASE_OFFSETS!r}"


def derive_phase_rng(master_seed: int, phase_salt: int, key: str) -> np.random.Generator:
    """AD-16 徹底: phase 内 key ごとに独立 sub-stream を返す。"""
    return np.random.default_rng(derive_sub_seed(master_seed, phase_salt, key))
```

#### engine.py 書き換え箇所

```python
# P1: life event 生成(月ごと)
for y, m in month_iter:
    month_rng = derive_phase_rng(master, PHASE_LIFE_EVENT, f"{y:04d}-{m:02d}")
    all_events.extend(generate_monthly_events(population, y, m, month_rng, ...))

# P2: hospital main loop(event ごと)
for event in hospital_events:
    event_key = f"{event.person_id}|{event.timestamp.isoformat()}|{event.disease_id}"
    event_rng = derive_phase_rng(master, PHASE_INPATIENT_SIM, event_key)
    record = _simulate_patient(..., rng=event_rng)

# P3: readmission
for record in patient_records:
    re_key = f"{record.patient.patient_id}|{record.encounters[0].encounter_id}"
    re_rng = derive_phase_rng(master, PHASE_READMISSION, re_key)
    ...

# P4: outpatient calendar
for event in calendar_events:
    ev_key = f"{event.person_id}|{event.timestamp.isoformat()}|{event.event_type}"
    ev_rng = derive_phase_rng(master, PHASE_OUTPATIENT_CAL, ev_key)
    ...

# P4': ED (slot index を key に)
for slot in range(n_ed):
    slot_rng = derive_phase_rng(master, PHASE_ED_VISIT, f"slot-{slot:06d}")
    ...
```

#### F1 の副作用

- **既存 golden 破壊**:reproduce.sh の 272 US + 193 JP files が全部変わる
- 対策:golden を PR で **一括再生成**(session 30 AD-66 と同じパターン)
- 以降は new baseline

#### F1 の invariant test

```python
# tests/unit/test_engine_cross_cursor.py
def test_cross_cursor_shared_window_byte_identical():
    """F1 core: cursor A の全 record が cursor B の共有区間と bytewise 一致。"""
    config_a = SimulatorConfig(random_seed=42, catchment_population=200,
                               time_range=("2025-01", "2026-01"),
                               snapshot_date="2025-06-30")
    config_b = replace(config_a, snapshot_date="2025-07-31")
    ds_a = run_beta(config_a)
    ds_b = run_beta(config_b)

    # cursor A に居た patient は cursor B にも同 record で存在
    a_by_pid = {r.patient.patient_id: r for r in ds_a.patients}
    b_by_pid = {r.patient.patient_id: r for r in ds_b.patients}
    for pid, a_rec in a_by_pid.items():
        assert pid in b_by_pid, f"{pid} missing in cursor B"
        # admission が cursor A 内の record は B でも同 content
        if a_rec.encounters[0].admission_datetime.date() <= date(2025, 6, 30):
            b_rec = b_by_pid[pid]
            assert asdict(a_rec) == asdict(b_rec), f"cross-cursor drift for {pid}"
```

### F2: FHIR NDJSON 出力安定 sort

各 `_fhir_*.py` builder が返す `list[dict]` を、集約後 id 昇順で sort してから NDJSON emit。

#### 実装(fhir_r4_adapter.py)

```python
# fhir_r4_adapter.py 内、NDJSON 書き出しループの直前:
for resource_type, resources in grouped.items():
    resources_sorted = sorted(resources, key=lambda r: r.get("id", ""))
    (out_dir / f"{resource_type}.ndjson").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in resources_sorted)
    )
```

#### F2 の副作用

- 既存 golden line order が全部変わる → **F1 と同 PR で golden 再生成することで合流**、追加影響ゼロ
- 内容は unchanged、行順序のみ

#### F2 の invariant test

```python
# tests/unit/test_fhir_ndjson_stable_sort.py
def test_ndjson_files_id_sorted(tmp_path):
    """F2 core: 各 NDJSON が id 昇順で emit される。"""
    dataset = run_beta(SimulatorConfig(random_seed=42, catchment_population=50))
    out = tmp_path / "fhir"
    write_fhir_r4(dataset, out)
    for ndjson_file in out.glob("*.ndjson"):
        ids = [json.loads(line)["id"] for line in ndjson_file.read_text().splitlines()]
        assert ids == sorted(ids), f"{ndjson_file.name} not id-sorted"
```

### F4: Snapshot memoize(前 output を cache として利用)

cursor 移動時、「前 snapshot で全 encounter 完了した患者」は今回も **必ず bit-identical** な
output になる(snapshot semantics + F1 の cross-cursor determinism の帰結)。よって
simulate を skip して前回 CIF から load。

#### 原理

```
cursor_prev = 2026-05-31(前回 snapshot、cache_dir)
cursor_new  = 2026-06-01(今回)

∀ patient X:
  if all X.encounters.discharge_datetime <= cursor_prev:
    # X は前回 snapshot で完全に「過去」→ cursor が動いても bit-identical
    → 前回 CIF から load、simulate skip
  else:
    # in-progress or 期間跨ぎ or 新規 event → simulate
    → 通常の run_beta path(F1 済みなので cursor 独立)
```

#### 実装(engine.py + 新規 loader)

```python
# engine.py の run_beta signature に cache_dir 追加
def run_beta(config, hospital_config_path=None, cache_dir=None):
    prev_cache = load_prev_snapshot(cache_dir) if cache_dir else None

    if prev_cache:
        # 決定性 gate:seed / config / hospital_config が同一でなければ全再走(cache 無効)
        assert prev_cache.master_seed == config.random_seed
        assert prev_cache.config_hash == compute_config_hash(config)
        prev_cursor = prev_cache.snapshot_date

        # eligible: 全 encounter が prev_cursor 以前に完了
        eligible_pids = {
            pid for pid, recs in prev_cache.patient_records.items()
            if _all_encounters_completed(recs, prev_cursor)
        }
    else:
        eligible_pids = set()

    # main loop:eligible patient は cache hit
    for event in hospital_events:
        if (event.person_id in eligible_pids
            and event.timestamp <= prev_cache.snapshot_date):
            # Cache hit — 前回 CIF から load
            record = prev_cache.patient_records[event.person_id]
        else:
            # Cache miss — full sim
            event_rng = derive_phase_rng(master, PHASE_INPATIENT_SIM, event_key)
            record = _simulate_patient(..., rng=event_rng)
        patient_records.append(record)
```

#### `_cache_manifest.json`(前 output directory に併存)

```json
{
  "schema_version": 1,
  "master_seed": 42,
  "config_hash": "sha256:...",
  "snapshot_date": "2026-05-31",
  "country": "JP",
  "population_size": 500000
}
```

- 前 snapshot 生成時に `run_beta` が自動で書く
- 次回 `run_beta` が `cache_dir` 引数で受け取り、manifest 検証して cache hit path 有効化
- state module 不要、CIF directory 自体が cache

#### F4 の invariant test

```python
# tests/unit/test_engine_memoize.py
def test_memoize_hit_bit_identical():
    """F4 core: cache hit patient の record は前回 snapshot と bit-identical。"""
    config = SimulatorConfig(random_seed=42, catchment_population=200,
                             time_range=("2025-01", "2026-01"),
                             snapshot_date="2025-06-30")
    ds_a = run_beta(config, cache_dir=None)  # cold run
    _save_as_cache(ds_a, tmp / "snap_a")

    # cursor advance
    config_b = replace(config, snapshot_date="2025-07-31")
    ds_b_cold = run_beta(config_b, cache_dir=None)  # 参照 baseline
    ds_b_memo = run_beta(config_b, cache_dir=tmp / "snap_a")  # memoize

    # eligible patient は cold と memo で完全一致
    for pid in eligible_patient_ids(ds_a, cursor="2025-06-30"):
        assert asdict(ds_b_cold.patients[pid]) == asdict(ds_b_memo.patients[pid])

def test_memoize_config_change_invalidates():
    """F4 safety: seed / config が変わったら cache 無視して全再走。"""
    ...

def test_memoize_hit_ratio_realistic():
    """F4 performance: cursor 1 日 advance で 95%+ hit(小 population)."""
    ...
```

#### F4 の副作用

- 既存 golden 影響ゼロ(F1+F2 完了後の再生成不要)
- `run_beta` signature に `cache_dir=None` 追加(既存 callers は unchanged)
- 前 snapshot に `_cache_manifest.json` が併存(既存 file には影響なし)

### F3: `clinosim diff` CLI

2 output dir の差分を FHIR Bundle transaction として抽出。

#### CLI

```bash
clinosim diff \
  --old /var/clinosim/snapshots/2026-05-31 \
  --new /var/clinosim/snapshots/2026-06-01 \
  --output-bundle bundle/2026-06-01.json \
  --output-summary summary/2026-06-01.txt
```

#### semantics(3 状態分類)

各 resource type について:

- NEW(new_by_id にあり、old_by_id にない):`Bundle.entry.request.method = POST`, `url = <ResourceType>`
- UPDATED(両方にあり、hash が異なる):`method = PUT`, `url = <ResourceType>/<id>`
- UNCHANGED(両方にあり、hash 同一):bundle に含めない
- DELETED(旧にあり、新にない):snapshot cumulative なので通常発生しない;発生時は warning ログのみ(bundle 非包含)

canonical hash = resource dict 全体を sorted keys で JSON dump した sha256。
`meta.lastUpdated` は cursor 依存で変わる可能性があるので、hash 前に除外する
(Open question 参照)。

#### output_bundle 形式

```json
{
  "resourceType": "Bundle",
  "id": "clinosim-diff-2026-05-31-to-2026-06-01",
  "meta": {"lastUpdated": "2026-06-01T00:00:00+09:00"},
  "type": "transaction",
  "entry": [
    {
      "fullUrl": "urn:uuid:...",
      "resource": {...},
      "request": {"method": "POST", "url": "Encounter"}
    },
    {
      "fullUrl": "urn:uuid:...",
      "resource": {...},
      "request": {"method": "PUT", "url": "Encounter/enc-abc123"}
    }
  ]
}
```

Bundle transaction は FHIR spec 上 atomic(全成功 or 全 rollback)。

#### summary

```
Diff 2026-05-31 → 2026-06-01

New resources:
  Patient                    : 3
  Encounter                  : 12
  Observation                : 187
  Condition                  : 5

Modified resources:
  Encounter                  : 4  (in-progress → finished)
  Condition                  : 2  (active → resolved)

Total bundle size: 213 entries, 421 KB

Recommended action:
  curl -X POST -H "Content-Type: application/fhir+json" \
    -d @bundle/2026-06-01.json https://fhir.example.com/fhir
```

#### 実装 scope

- `clinosim/simulator/diff.py`(pure logic、100-150 行)
- `clinosim/simulator/cli.py` に subcommand 追加(30 行)
- push は含めない(operational)

## 5. Testing

| test | 目的 | 場所 |
|---|---|---|
| `test_cross_cursor_shared_window_byte_identical` | F1 core invariant | `tests/unit/test_engine_cross_cursor.py`(新規) |
| `test_phase_seed_offsets_unique` | phase salt 衝突なし | `tests/unit/test_seeding.py`(1 行追加) |
| `test_ndjson_files_id_sorted` | F2 core invariant | `tests/unit/test_fhir_ndjson_stable_sort.py`(新規) |
| `test_diff_bundle_new_only` | F3 全 new | `tests/unit/test_diff_bundle.py`(新規) |
| `test_diff_bundle_modified_only` | F3 全 modified | 同上 |
| `test_diff_bundle_mixed` | F3 3 状態混合 | 同上 |
| `test_diff_bundle_fhir_r4_conformance` | Bundle transaction spec 準拠 | 同上 |
| `test_memoize_hit_bit_identical` | F4 core:cache hit の record が cold run と bit-identical | `tests/unit/test_engine_memoize.py`(新規) |
| `test_memoize_config_change_invalidates` | F4 safety:seed/config 変化で cache 無効化 | 同上 |
| `test_memoize_hit_ratio_realistic` | F4 performance:cursor 1 日 advance で 95%+ hit | 同上 |
| `test_incremental_snapshot_workflow` | F1+F2+F3+F4 e2e:snapshot A → memoize snapshot B → diff → bundle 検証 | `tests/integration/`(新規) |
| `reproduce.sh` update | F1+F2 で golden 全再生成後の new baseline | `scripts/reproduce.sh`(更新) |

## 6. 実装 order(sub-PR 分割)

```
PR-1 (F1 + F2, session N):
  - seeding.py に phase constants + derive_phase_rng
  - engine.py の 4 phase refactor
  - fhir_r4_adapter.py に id-sort
  - golden 一括再生成(reproduce.sh の new baseline 確定)
  - cross-cursor invariant test 追加
  - 既存 test 全 pass 確認

PR-2 (F3, session N+1):
  - simulator/diff.py(pure logic)
  - simulator/cli.py に diff subcommand 登録
  - unit test 4 個
  - integration e2e test 1 個
  - golden 影響ゼロ、pure addition

PR-3 (F4, session N+2):
  - _cache_manifest.json read/write helper
  - engine.py の run_beta に cache_dir 引数 + eligibility 判定 + cache hit path
  - CIF loader helper(前 output から patient record 復元)
  - F4 invariant / safety / performance test 3 個
  - integration e2e workflow test 拡張(F1+F2+F3+F4 合流)
  - golden 影響ゼロ、既存 caller 全て unchanged(cache_dir デフォルト None)
```

F1 と F2 は golden 再生成コストが共通なので 1 PR で合流(セッション内で `regen_baseline` を 1 度だけ回せる)。
F3 と F4 は golden 影響ゼロで独立 PR。F4 は F1 の cross-cursor determinism に依存するので F1 完了後。

## 7. 6 軸評価(実装後の想定状態)

| 軸 | 評価 |
|---|---|
| データ品質 | ◎ AD-16 が top-level まで徹底、cross-cursor byte-identity 保証、cache hit も bit-identical |
| 臨床整合性 | ◎ 現行 unchanged(値の意味は変わらない、rng stream の派生元だけが変わる) |
| FHIR-JP Core | ◎ Bundle transaction spec 準拠、既存 profile 保持 |
| メンテ性 | ◎ AD-55/56 変更ゼロ、責任分解 clear(decisive snapshot generator vs operational tooling) |
| モジュール責任分解 | ◎ 各 module 変更ゼロ、engine.py の 5-10 箇所 + adapter の sort + 新 diff.py + memoize path のみ |
| EHR-EMR goal | ◎ 実 EHR 統合 + p=500k daily cron 実用(数分 advance)、user は既存 curl / httpx で push |

## 8. 前提と非目標

**前提**:
- `master_seed + config + snapshot_date` から純関数として output が決まる(AD-16、実際は F1 で完成)
- FHIR resource id は client-assigned(clinosim が決定的に生成)、server 生成 UUID は使わない
- Bundle transaction を受け付ける FHIR server が対象(HAPI FHIR / Firely / Google Cloud Healthcare API 等)

**非目標**(Phase B 以降 / 別 backlog):
- OAuth2 / SMART on FHIR auth
- Bulk Data `$import` support
- retry queue の robust 化 / server 失敗時の recovery
- 実 FHIR server に対する CI smoke test
- schema evolution / migration path
- parallel simulation(multiprocessing)による更なる高速化

## 9. 関連 ADR / memory

- AD-16(Deterministic with seed)= F1 で top-level まで徹底
- AD-17(CIF is only simulation output)= F2 で NDJSON writer 変更、CIF は unchanged
- AD-30(CIF is codes only)= 変更なし
- AD-32(snapshot semantics)= 変更なし、diff は既存 snapshot semantics の上に乗る
- AD-55/56(module registry)= 変更なし
- memory `feedback_verify_before_asserting`= cross-cursor invariant を test で観測してから claim
- memory `project_ehr_event_emphasis`= EHR event 記録の充実 goal と整合

## 10. Open questions(実装時に決定)

- **`meta.lastUpdated` の hash 扱い**:現行 FHIR builder は `meta.lastUpdated` を cursor
  依存(例:snapshot 日付や実行時)に設定している可能性がある。もしそうなら cursor A と B
  で同 encounter でも lastUpdated が違い、UNCHANGED が全部 UPDATED になる = false-positive。
  → F3 実装時に実 output を確認、`meta.lastUpdated` は hash 前に **strip して除外**、
  ただし bundle に emit する resource には保持(server 側は無視 or override 可)。
  同様に `meta.versionId` / `meta.source` も除外候補。この rule を `diff.py` 内で
  canonical form 関数として定義。
- **DELETED resource** の扱い:snapshot は cumulative なので通常発生しないが、
  patient が死亡して followup encounter が消えるケースがある。→ 実装時に決定(bundle 非包含
  + warning ログを default に)
- **Bundle 分割 threshold**:1 日で数万 resource が新規となる cursor 移動でも 1 bundle か。
  → 実装時に決定(Phase A は無制限、Phase B で `--max-bundle-size` option 検討)
- **Reference integrity(bundle 内部)**:bundle 内で新規 Encounter が新規 Patient を参照する
  場合、FHIR server は `fullUrl` の `urn:uuid:...` ↔ `request.url` の解決を transaction 中に
  行う。ただし clinosim の resource id は client-assigned なので `Patient/POP-000001` を
  `resource.subject.reference` に埋めれば足りる(fullUrl は informational)。→ 実装時に
  FHIR conformance test で確認。
- **F4 cache staleness 判定**:seed / config_hash / hospital_config が変わったら cache 無効化
  = 全再走。ただし cache は前 output directory 自体なので、user が「気付かず古い cache_dir を
  指した」時に silent fallback ではなく **fail loud**(明示 error + 再度 --no-cache で回すよう
  guidance)にすべき。→ 実装時に決定。default = fail loud + `--force-recompute` で override 可。
- **F4 in-progress encounter の cache 扱い**:前 snapshot で in-progress だった encounter は
  cache eligible 対象外(discharge 未確定なので今回 cursor で確定する可能性)。**eligibility 判定
  は "全 encounter が discharge_datetime <= prev_cursor" の厳格 rule**。in-progress が 1 件でも
  あれば全 patient を cache miss 扱い(再 sim)。実装 sketch でこの rule を明示化。
