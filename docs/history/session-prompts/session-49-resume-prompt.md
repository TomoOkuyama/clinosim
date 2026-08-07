# Session 49 Resume Prompt

Session 48 で完成した baseline から、案 B(incremental cron)実装 phase A を開始する。

---

## STEP 0:状態確認(必須、順序厳守)

```bash
cd /Users/tokuyama/workspace/clinosim
git branch --show-current
git log --oneline -5 master
git log --oneline -3 origin/master
git status --short
git worktree list
```

**期待値**:
- current branch: `master`
- master HEAD: `038543aad9` = `fix(fhir): FB verify 27/27 PASS — inference 拡充 + post-emit TZ normalization`
- 1 つ手前: `b92c6e74c7` = `audit(cycle-8): imaging silent-drop fix + JP Core validator feedback 7 系統`
- origin/master: 同期済(direct-master pattern)
- status: clean
- worktrees: default のみ

異なる HEAD なら pull/rebase。

---

## STEP 1:session 48 の完了状態を把握(必読、順序厳守)

1. **Memory `project_session_48_end_state.md` を読む**
   = 21 commits の詳細 + FB verify 27/27 PASS + CIF-VS-FHIR-01 修正 + 案 B 設計方針
2. **TODO.md 冒頭の Status (2026-07-13, ★★★ session 48 CLOSED) section を読む**
   = commit ごとの 1 行サマリ + 次 session 候補
3. **Memory `feedback_clinosim_workflow.md`** — direct-master 方式、PR 不要
4. **Memory `feedback_batch_long_running_ci.md`** — long-running は session 末 batch

その他 参照候補:
- CLAUDE.md(comment lang rule / no fabrication policy)
- docs/design-guides/{project-concept-and-design,implementation-rules,data-generation-walkthrough}.md
- docs/audit-cycles/by-design-registry.md(25 entries、Cycle 9 監査時 signature 必須)
- MODULES.md / DESIGN.md
- **docs/session-49-resume-prompt.md**(このファイル)

---

## STEP 2:session 48 で何を完了したか(再作業しない)

### 21 commits direct-master push

```
038543aad9 FB verify 27/27 PASS(inference 拡充 + post-emit TZ normalization)
b92c6e74c7 imaging silent-drop fix + JP Core feedback 7 系統
95cfe443da triple-seed review (seed=200) clinical + statistical
c783e23eed cross-seed verify (seed=100) 4 regression fix
62d164faa3 by-design registry 4 additions (25 total)
b24ec1a95f Cycle 8 audit 30 findings resolved
13d0e41ef0 (c) P2-15 benchmark
a3e01ff0e4 (b) P2-14 add-your-country
13443101a5 (g) Deferred cleanup 3
766ad5c9ee (f) sub-PR-E DocumentReference wrapper
3dfa6e4c73 (e) sub-PR-C SHA256 pin + auto-fail
93d3c1b066 (d) sub-PR-B individualization
```

### 完了内容(高レベル)

- **(d/e/f/g/b/c)** sub-PR 高度化 + cleanup + P2-14 + P2-15
- **Cycle 8 audit** 30 findings 全解消(24 at 100% + 5 by-design + 1 registered)
- **Cross-seed / triple-seed / clinical + statistical review** — seed=42/100/200/201 全 invariant 保持
- **CIF-VS-FHIR-01** imaging silent-drop ratio 0.22 → **1.00** 完全解消
- **iris4h-ai feedback FB-F1..F8** HAPI FHIR JP Core validator 27/27 PASS
- **by-design registry** 21 → **25 entries**

---

## STEP 3:テスト状態(session 48 wrap 時)

- **Unit 1733 PASS**、regression 0
- **reproduce.sh PASS**(US 272 + JP 193 files byte-identical)
- **FB verify: 27/27 PASS**
- **regen baseline: 15-16 分**(JP p=10000、darwin 25.3.0, python 3.12.7)
- **iris4h-ai copy 済み**: `~/workspace/iris4h-ai/fhir_r4/`(27 files、4.7 GB、seed=201)

---

## STEP 4:Session 49 の作業内容 = 案 B incremental cron 実装 phase A

### 背景

Session 48 末に user 明示:「バッチ生成 → cron 日次追記」への refactor。フォワードシミュレーションに必要な全変数を保存し、追加データを incremental に生成できるようにしたい。

### 採択した設計:案 B(構造化 JSON + per-patient state)

**却下した案**:
- **案 A**(monolithic pickle):opaque、schema 進化難
- **案 C**(CIF as state):AD-30 違反(CIF は codes only / output only)
- **案 D**(event-sourcing):schema 複雑、実装コスト高

**案 B 採択理由**:
1. AD-17/30/56 準拠(既存アーキテクチャ整合)
2. 決定性維持(numpy Generator の getstate/setstate で完全復元)
3. cron 実運用(per-patient file 並列書込 + journal.log idempotency)
4. schema 進化容易(version field + migration path)
5. auditable(JSON で state を目視 debug 可能)
6. 既存 CIF/FHIR は output-only 責任分解を維持

### Phase A スコープ(1 session、~10 tasks)

1. **`clinosim/state/` module 新設**
   - `state/__init__.py`(public API 公開)
   - `state/world.py`(WorldState dataclass + JSON serialize)
   - `state/hospital.py`(HospitalState:ward occupancy / staff queue / event calendar)
   - `state/patient.py`(PatientState:PhysiologicalState + trajectory + pending orders)
   - `state/serialize.py`(RNG state を base64-encoded getstate/setstate で JSON-safe)

2. **既存 dataclass に `to_dict() / from_dict()` 追加**
   - `PhysiologicalState`
   - `HospitalOpState`
   - `EventCalendarEntry`(pending admission / outpatient / immunization / health_checkup)

3. **`run_beta()` を state-machine 分解**
   - `WorldState.initialize(config)` — cohort demographics + world state 初期化
   - `WorldState.advance(world, days=1)` — 1 day tick、new events + state 更新
   - `WorldState.emit(world, output_dir)` — 差分 CIF + FHIR append
   - 既存 `run_beta()` は互換シム:internal で `initialize → advance × N → emit`

4. **State file 出力**
   ```
   <world_dir>/
   ├── state/
   │   ├── world.json           # schema_version, current_date, seed, RNG state, sequence_counters
   │   ├── hospital.json        # ward occupancy, staff queue, event calendar
   │   └── patients/
   │       ├── POP-000001.json  # per-patient state
   │       └── ...
   ├── cif/                     # 既存 output(不変)
   └── fhir_r4/                 # 既存 output(不変)
   ```

5. **Unit test 30-50 個**
   - state round-trip(serialize → deserialize → 等価)
   - RNG state restoration(numpy Generator.__getstate__/__setstate__ の base64 経由)
   - PhysiologicalState 復元(inflammation_level, renal_function, cardiac_function 等)
   - Schema version field 検証(version mismatch で明示 error)

6. **Integration smoke test**
   - `WorldState.initialize + advance × 3 + emit` の一連呼び出しで CIF/FHIR が生成される
   - 決定性:同 seed + 同期間 → 同 output(既存 reproduce.sh 相当)

### Phase A で扱わないこと(scope discipline)

- **cron CLI**(`clinosim advance`)= Phase B
- **journal.log idempotency** = Phase B
- **FHIR NDJSON append-only 保証** = Phase C
- **batch=incremental golden test**(30-day 分割 = 30 × 1-day)= Phase D
- **schema evolution migration** = Phase E
- **storage optimization**(gzip、trimming)= Phase F

### 7 主要 Challenge(Phase A で解決するもの)

1. **RNG state pickle vs JSON 互換**:numpy Generator の `__getstate__()` → base64 encode → JSON string、`__setstate__()` で完全復元(unit test 必須)
2. **既存 dataclass の JSON serialize**:`asdict()` は datetime 型を str に変換しない → custom serialize
3. **Enum の JSON 保存**:OrderType / OrderStatus / EncounterType(既存 str Enum なら値保存で OK)
4. **numpy array の JSON 保存**:`.tolist()` + `np.array()` 復元
5. **Sequence counter の完全保存**:`sequence_counter: dict[str, int]` は JSON-native

### Phase A で扱わない Challenge(Phase B..F)

- Day-tick idempotency(Phase B)
- Batch = incremental 決定性 verify(Phase D、golden test)
- Schema evolution(Phase E)
- Storage cost(Phase F)
- AD-32 snapshot semantics 再定義(Phase E)
- FHIR resource id 衝突 guard(Phase C)

---

## STEP 5:プロジェクトコンセプト + ロジックデザイン把握

**clinosim** = population-driven, physiology-based synthetic EHR data simulator。

**目的**:JP EHR/EMR sample data generator、Synthea(US 中心)との差別化ポイント =
- JP Core / JP-CLINS / JP-eCheckup Full 準拠
- 実クリニカルワークフロー(inpatient/outpatient/ED/health checkup)を physiology で駆動
- 決定的(seed + config 固定 → byte-identical output)
- **cron 日次追記対応**(session 49 で追加、案 B 実装)

**データ流れ**(現行 = batch):
1. **Population generation**(demographics + chronic conditions + allergies)
2. **Simulation loop**:disease event → encounter simulator(inpatient/outpatient/emergency)
3. **POST_ENCOUNTER enricher chain**(device / hai / antibiotic / imaging / triage / nursing / document)
4. **POST_RECORDS enricher**(nursing / immunization / family_history / code_status / care_level / health_checkup opt-in)
5. **CIF 書き出し**(structural JSON per patient + narrative subtree separate versioned)
6. **Two-pass narrative**(AD-65、Stage 2 TemplateNarrativePass、Composition section populate)
7. **FHIR R4 Bulk Data Export**(1 NDJSON per resource type + manifest.json)

**session 49 で追加する data flow**(案 B incremental):
1. **initialize**(cohort + world state 初期化、state/*.json 書出)
2. **advance × N**(day tick、state 更新、差分 CIF + FHIR emit)
3. **cron 実運用**(daily cron で `clinosim advance --days 1`、既存 output に追記)

**主要 Architecture rules**:
- **CIF is the only simulation output**(AD-17)+ codes only, no display text(AD-30)
- **LLM calls only via `llm_service`**(AD-11)
- **Deterministic with seed**(AD-16、per-module sub-seed、numpy Generator 使用)
- **Module independence**(each depends only on types/codes/locale + declared modules)
- **Opt-in module = extensions dict**(AD-55/56、health_checkup は JP-only 6 番目 opt-in)
- **Two-pass narrative**(AD-65、structural CIF + narrative separate files)
- **AD-32 snapshot semantics**:`--end` で in-progress encounter を切断(案 B の advance でも継承)

**Session 48 で追加された state 対象**:
- Imaging inference module(`modules/imaging/inference.py`)
- Post-emit TZ normalization(`_fhir_common.to_fhir_instant()` + `fhir_r4_adapter._normalize_dt_fields()`)
- 全 25 by-design registry entries

---

## STEP 6:再開時の作業順序

**Order**:
1. STEP 0 状態確認
2. STEP 1-2 memory / TODO 読解
3. TaskCreate で Phase A の 10 tasks を作成:
   - state module 骨組み
   - PhysiologicalState serialize
   - HospitalState serialize
   - PatientState serialize
   - RNG state base64 encoding
   - `run_beta` state-machine 分解
   - state file directory 出力
   - Unit test round-trip
   - Unit test RNG restoration
   - Integration smoke test
4. brainstorming skill を経由してから phase A の設計最終 spec を書出(scope 拡大防止)
5. 実装開始

---

## STEP 7:再開時ユーザーへの最初の一言例

「Session 48 wrap 状態確認済(master `038543aad9`、Unit 1733 PASS、FB verify 27/27、CIF-VS-FHIR-01 ratio 1.00)。案 B incremental cron phase A を開始します。

まず現状の `run_beta()` の state 依存(RNG + hospital ops + per-patient physiology + event calendar)を精査してから、`clinosim/state/` module の骨組み設計を brainstorming で最終化します。10-task の作業リストで進める予定でよいですか?

代替 order:
- (A) いきなり実装開始(brainstorming skip)
- (B) 別 approach 検討(案 D event-sourcing の再評価等)
- (C) Phase A の scope を絞る(state serialize のみ、`run_beta` 分解は Phase A2 に)
- (D) その他」

---

## 参考:重要 workflow rules

- **★ direct-master 方式**(feedback-clinosim-workflow):PR 不要、commit push per master
- **★ JP-only 日本語コメント / 共通英語**(session 47 制定、CLAUDE.md 明文化)
- **★ long-running is session-end batch**(memory feedback-batch-long-running-ci):PR ごとに 30 分待たない
- **★ 推奨提示時 6 軸評価**(データ品質 / 臨床整合 / FHIR-JP Core / メンテ性 / モジュール責任 / EHR-EMR goal)
- **★ 同 class バグ 1 件 → 全 sibling sweep**(feedback-check-sibling-bugs-across-modules)
- **★ 観測前に語らない**(feedback-verify-before-asserting):ツール結果を見る前に成功と書かない
- **★ scope discipline**(feedback-scope-discipline):Phase A は state 基盤のみ、cron CLI は Phase B
