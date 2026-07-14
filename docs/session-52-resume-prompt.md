# Session 52 Resume Prompt

## STEP 0:状態確認(必須、順序厳守)

```bash
cd /Users/tokuyama/workspace/clinosim
git branch --show-current
git log --oneline -6 master
git log --oneline -3 origin/master
git status --short
git worktree list
git stash list
```

**期待値**:
- current branch: `master`
- master HEAD: `5a5a77ed42` = `fix(fhir): imaging test fixtures + audit synthetic follow session 51 prefix rule`
- 1 つ手前:`8c1fb45ff9` = `fix(P1-3): split dose_quantity/dose_unit in medication orders (session 51)`
- origin/master: 完全同期(direct-master pattern、PR/merge なし)
- status: clean
- worktrees: default のみ
- stash list: 空

異なる HEAD なら pull/rebase。

---

## STEP 1:session 51 の完了状態を把握(必読、順序厳守)

1. **Memory `project_session_51_end_state.md` を読む**
   = P1-4 URI 訂正 chain closure + P1-3 dose fix + imgst/imgrpt double-prefix fix の詳細
2. **Memory `feedback_verify_fhir_profile_uri_from_spec.md`** = session 51 で制定した FHIR profile URI verification rule
3. **TODO.md 冒頭の Status (2026-07-14, ★★★ session 51 CLOSED) section を読む**
4. **`docs/audit-cycles/by-design-registry.md`** = 25 entries、次サイクル監査時に signature match 必須

その他 参照候補:
- `CLAUDE.md`(FHIR output rules に URI 引用ルール追記済、JP-only 日本語コメント rule)
- `docs/design-guides/implementation-rules.md`(§ 6.5 に URI 引用ルール詳細版)
- `MODULES.md` / `DESIGN.md`

---

## STEP 2:session 51 で何を完了したか(再作業しない)

### 6 commits direct-master push

```
5a5a77ed42 fix(fhir): imaging test fixtures + audit synthetic follow session 51 prefix rule
8c1fb45ff9 fix(P1-3): split dose_quantity/dose_unit in medication orders (session 51)
139d604db2 docs: session 50 adv-1 lesson on JP Core profile URI spec compliance
6455441c99 docs(session): update session 50 status with adv-1 CRITICAL URI fix + gitignore anchor
131e58f2d1 fix(gitignore): anchor `output/` pattern to repo root + add missing pin test file
e36a714624 fix(fhir-jp): correct Observation.category:first CodeSystem URI per JP Core 1.2.0 spec
```

### 主要成果

1. **P1-4 URI 訂正 closure**:
   - `_JP_OBSERVATION_CATEGORY_SYSTEM` を実 spec fixedUri `http://jpfhir.jp/fhir/core/CodeSystem/JP_SimpleObservationCategory_CS` へ訂正(初版は推測 URI で HAPI validator silent-no-op だった)
   - 13 pin tests で URI 差し戻し規制(`tests/unit/output/test_fhir_jp_core_p14_slices.py`)
   - `.gitignore` anchor bug 副次発見・修正
2. **Docs rule 制定**:
   - CLAUDE.md § FHIR output rules に「spec fixedUri 直接引用 + URI pin test 必須」
   - implementation-rules.md § 6.5 canonical helpers に詳細 4 step 手順
   - memory `feedback_verify_fhir_profile_uri_from_spec.md` 新規
3. **P1-3 dose 欠落 fix**:`Order.dose_unit` に raw dose string("1g" 等)問題 → parse_dose_string() 適用(order/engine.py supportive + antibiotic/enricher.py の empirical + narrow)、134 orders 修正
4. **imgst/imgrpt double-prefix bug fix**(pre-existing 2026-06-30 以降、audit `startswith` で masked):`_fhir_imaging_study.py` + `_fhir_diagnostic_report.py` の builder が engine.py 側で既に prefix を付与した id を再 prepend していた bug → builder は as-is 使用(`_fhir_endpoint.py:61` パターンと統一)+ 5 test fixture 更新

---

## STEP 3:テスト状態(session 51 wrap 時)

- **Unit 2704 PASS**(session 50 の 2691 + 13 URI pin tests)
- **mypy strict PASS**、reproduce.sh PASS(US 105 + JP 72 files byte-identical seed=42 pop=30)
- **Regression (AD-66) 12/12 PASS**
- **Integration**:9 件失敗 → 2 系統 fix 済(imgst/imgrpt double-prefix + P1-3 dose)、残 5 件 = session 52 backlog
- **CI(29316588160)** post-close 確認:Unit 3.11+3.12 / Reproducibility / Build sdist+wheel すべて SUCCESS、Type check + Lint は informational failure(pre-existing 非 blocker)、**Integration は cancelled**(session 52 開始時 push `7321c0d374` の CI 経過も要確認)
- **Local integration full run**(23 分 58 秒、fix 適用時点跨ぎで信頼度低)= 288 passed / 9 failed。session 52 開始時に `pytest tests/integration -q --tb=no --deselect tests/integration/test_document_jp_localization.py::test_jp_clinical_impression_structural_fields_present` で post-fix 状態確認すること

---

## STEP 4:Session 52 で優先すべき候補 3 択

### 候補 A:Integration test 残 5 件 root cause 追跡 fix(session 51 継続)

user が「全 9 test root cause 追跡 fix」を選択(session 51 中)。session 51 で 2 系統 fix 済、残 5 件:

1. **AllergyIntolerance rate 7.8% vs 8-27% 期待**(p=200):session 49 F1 RNG stream 派生変更による small-cohort 統計変動
   - **Fix 候補**:(A) tolerance を 5-30% に緩和、(B) test 母集団を p=1000+ に拡大(統計変動吸収)、(C) F1 前 rate と比較して root cause 特定
2. **Reference integrity(Device/dev-infusion-pump 122 dangling)**:F1 encounter_id hash 化で Device 側 id 生成が同期漏れ
   - **調査**:`clinosim/modules/device/engine.py` の id 生成 pattern を確認、`dev-infusion-pump` reference が何処から emit されているか grep
3. **Reference integrity(Location/loc-hospital-main 38 dangling)**:同上、`loc-hospital-main` が Location resource として emit されていない
   - **調査**:`clinosim/modules/output/_fhir_facility.py` の Location emit + Encounter の location reference 生成を確認
4. **ImagingStudy vs Endpoint 1:1(180 vs 167)+ Radiology DR vs ImagingStudy 1:1(69 vs 180)**:session 48 imaging inference の**意図的**な stub-only(endpoint/report なし)path
   - **Fix 候補**:test 期待値を「stub-only を除いた ImagingStudy のみ 1:1」に relax、または engine 側で stub にも minimum endpoint/report emit
5. **ImagingStudy missing modality**:imaging inference で一部 legacy order が incomplete metadata
   - **調査**:`clinosim/modules/imaging/inference.py` の modality inference で fallback 追加

### 候補 B:iris4h-ai HAPI Validator 再走(P1-4 fix 実効検証)

session 51 で iris4h-ai/fhir_r4 に copy 済のデータは **cd33b33dd2(誤 URI 時点)の生成物**。URI 訂正済 master(e36a714624 以降)で:
1. `clinosim simulate -o output-p10000-seed<X> --population 10000 --seed <new> --country JP --start 2025-04-01 --end 2026-03-31 --format fhir-r4`(16 分)
2. `rm -rf ~/workspace/iris4h-ai/fhir_r4 && cp -r output-p10000-seed<X>/fhir_r4 ~/workspace/iris4h-ai/fhir_r4`
3. iris4h-ai 側で HAPI Validator + JP Core 1.2.0 再走
4. P1-4 の 3.06M miss が 0 になったか + 残 P1-3/P1-8/P2 の実件数集計

### 候補 C:P1-8 ValueSet 準拠(327件)

JP Core 独自 ValueSet coding への切替(現状 HL7 標準 CodeSystem 使用箇所を JP CodeSystem に置換):
- Coverage Class / AllergyIntolerance ClinicalStatus / Condition Category / MaritalStatus / Specimen condition / Observation Interpretation 等
- session 51 制定の「spec fixedUri 直接引用ルール」に従い、iris4h-ai/jp_core/package/ の StructureDefinition + ValueSet JSON から実 URI 取得
- 実装コスト:中(各 resource type ごとに ValueSet member の code 差替 + pin test)

---

## STEP 5:プロジェクトコンセプト + ロジックデザイン把握

**clinosim** = population-driven, physiology-based synthetic EHR data simulator。

**目的**:JP EHR/EMR sample data generator、Synthea(US 中心)との差別化ポイント =
- JP Core / JP-CLINS / JP-eCheckup Full 準拠
- 実クリニカルワークフロー(inpatient/outpatient/ED/health checkup)を physiology で駆動
- 決定的(seed + config 固定 → byte-identical output)
- **cron 日次追記対応**(session 49 完成、F1-F4 chain)

**データ流れ**:
1. **Population generation**(demographics + chronic conditions + allergies)
2. **Simulation loop**:disease event → encounter simulator(inpatient/outpatient/emergency)
3. **POST_ENCOUNTER enricher chain**(device / hai / antibiotic / imaging / triage / nursing / document)
4. **POST_RECORDS enricher**(nursing / immunization / family_history / code_status / care_level / health_checkup opt-in)
5. **CIF 書き出し**(structural JSON per patient + narrative subtree separate versioned)
6. **Two-pass narrative**(AD-65、Stage 2 TemplateNarrativePass、Composition section populate)
7. **FHIR R4 Bulk Data Export**(1 NDJSON per resource type + manifest.json)

**主要 Architecture rules**(session 51 で強化された点)
- **CIF is the only simulation output**(AD-17)+ codes only, no display text(AD-30)
- **LLM calls only via `llm_service`**(AD-11)
- **Deterministic with seed**(AD-16、per-module sub-seed + F1 phase sub-seed で cross-cursor 保証)
- **Module independence**(each depends only on types/codes/locale + declared modules)
- **AD-55/56 opt-in module = extensions dict**
- **AD-65 two-pass narrative**
- **AD-32 snapshot semantics**
- **★ session 47 JP-only 日本語コメント rule**:JP-CLINS builder / JP section renderer / JP-only YAML など JP-only path のコメント + docstring は日本語、共通 dispatch/framework は英語
- **★ session 51 FHIR profile URI 引用 rule**:JP Core / JP-CLINS / JP-eCheckup / SS-MIX2 の profile URI・slice system URI は spec の StructureDefinition-*.json fixedUri を直接引用(推測禁止)+ URI pin test 必須
- **★ session 51 direct-master workflow**:PR/merge なし、commit push per master、integration/e2e は session-end batch

**F1-F4 chain(session 49)成果**:
- F1 cross-cursor RNG determinism(engine.py 4 phase を per-key sub-seed 化)+ sibling fixes(encounter counter → hash / calendar spawn / readmission anchor)
- F2 FHIR NDJSON id 昇順 sort
- F3 `clinosim diff` CLI(canonical hash + Bundle transaction 生成)
- F4 snapshot memoize(前 output = cache、`--cache-dir` CLI 経由で p=500k advance が 15-16h → 数分)

---

## STEP 6:再開時の作業順序

**Order**:
1. STEP 0 状態確認 + CI (29316588160) final status 確認
2. STEP 1-2 memory / TODO / rule 読解
3. 候補 A / B / C から user と相談して選択
4. 選択後は候補に応じた実装:
   - **A 選択**:各 test を root cause から追跡、直近 fix で `imgst-`/`imgrpt-` パターン踏襲(pre-existing bug + F1 induced 併存)
   - **B 選択**:regeneration + iris4h-ai copy → HAPI Validator 実行(user 手動 or 別 process)
   - **C 選択**:iris4h-ai spec JSON から fixedUri 抽出 → 実装 + URI pin test 追加

---

## STEP 7:再開時ユーザーへの最初の一言例

「Session 51 wrap 状態確認済(master `5a5a77ed42`、Unit 2704 PASS、reproduce.sh PASS)。CI(29316588160)の final status を確認します。

その後、session 51 未完の Integration test 残 5 件(候補 A)、iris4h-ai URI 訂正版 regeneration(候補 B)、P1-8 ValueSet 準拠(候補 C)のどれで進めるか判断したいです。ゆっくり相談させてください。

代替 order:
- (A) Integration 残 5 件 root cause 追跡 fix(session 51 継続)
- (B) iris4h-ai URI 訂正版 regeneration + HAPI Validator 再走(session 50/51 backlog)
- (C) P1-8 ValueSet 準拠 chain(iris4h-ai feedback 未着手)
- (D) その他(user 主導の新 chain / 案内)」

---

## 参考:重要 workflow rules

- **★ direct-master 方式**(feedback-clinosim-workflow):PR 不要、commit push per master
- **★ JP-only 日本語コメント / 共通英語**(session 47 制定、CLAUDE.md 明文化)
- **★ long-running は session-end batch**(feedback-batch-long-running-ci):PR ごとに 30 分待たない、integration/e2e は次 session 開始時にまとめて回す
- **★ FHIR profile URI 引用**(session 51 制定):spec fixedUri を直接引用、推測 URI 禁止、URI pin test 必須
- **★ 同 class バグ 1 件 → 全 sibling sweep**(feedback-check-sibling-bugs-across-modules):session 51 で imgst → imgrpt へ横展開して同 double-prefix fix
- **★ 観測前に語らない**(feedback-verify-before-asserting):ツール結果を見る前に成功と書かない
- **★ scope discipline**(feedback-scope-discipline):session 51 で integration 9 件中 2 系統に絞って session-end wrap

---

## 補足:session 51 の technical 気付き

- **Bash `git commit` は timeout 傾向**:非常に長い heredoc + push chain だと 2-3 min timeout → `commit` と `push` を分離した方が安定
- **Edit tool の silently no-op**(session 51 中盤で複数回発生、再現条件不明):`python3 write_text()` の direct write で確実に apply
- **.gitignore の pattern `output/`** は `/output/` にすること(subdir `tests/unit/output/` を誤 match しないよう root anchor)
- **audit の `startswith` check は double-prefix bug を通す**:`assert id.startswith(prefix)` は弱い invariant、`assert not id.startswith(f"{prefix}{prefix}")` も併記すべき
- **並行 subagent 稼働可能性**:別 AI process が独立に fix を implement することがある(commit author "Claude Haiku 4.5" 等)。予期しない diff を見たら他 subagent を疑う

## Working directory の scratch

- `/Users/tokuyama/workspace/clinosim/output-p10000-seed300/`(6.4 GB):**cd33b33dd2 時点(誤 URI)** の生成物。次 session で削除 or 再生成
- `~/workspace/iris4h-ai/fhir_r4/`:同じく誤 URI 時点の copy、e36a714624 以降で再生成必要
