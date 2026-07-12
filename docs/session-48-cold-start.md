# Session 48 cold-start prompt

以下を丸ごと user prompt として貼り付けて session 48 を開始してください。

```
Session 48 cold-start(session 47 CLOSED、2026-07-13 wrap)

★★★ STEP 0:状態確認(必須、順序厳守)

cd /Users/tokuyama/workspace/clinosim
git branch --show-current
git log --oneline -5 master
git log --oneline -3 origin/master
git status --short
git worktree list

期待値:
- current branch: master
- master HEAD: 89e689bd27 = docs(todo): session 47 wrap — P2-13 v0.3 flagship 完成
- 1 つ手前: a9b9efbab1 = feat(fhir): P2-13 PR3 sub-PR-D age-based JP-eCheckup type dispatch
- origin/master: 同期済(direct-master pattern)
- status: clean
- worktrees: default のみ

異なる HEAD なら pull/rebase。

---
STEP 1:session 47 の完了状態を把握(必読、順序厳守)

1. Memory `project_session_47_end_state.md` を読む
   = P2-13 v0.3 flagship 完成の詳細、多locale bug 3 件 fix、comment lang rule 制定
2. TODO.md 冒頭の Status (2026-07-13, session 47 CLOSED) section を読む
   = commit ごとの 1 行サマリ + 次 session 候補
3. `docs/jp-clins.md` を読む
   = JP-CLINS + JP-eCheckup の全体像(6 情報 profile + 3 文書 Composition + 3 健診種別)
4. Memory `feedback_jp_only_comments_japanese.md` を読む
   = session 47 で確立、次 session 以降も継続:JP-only コード = 日本語コメント
5. Memory `feedback_batch_long_running_ci_at_session_end.md` を読む
   = long-running(integration/e2e/full CI)は session 末 batch、PR ごとに 30 分待たない

その他 参照候補:
- CLAUDE.md(Language conventions に comment lang rule 明文化済)
- docs/design-guides/{project-concept-and-design,implementation-rules,data-generation-walkthrough}.md
- docs/audit-cycles/by-design-registry.md(22 entries、Cycle 8 監査時 signature 必須)
- MODULES.md / DESIGN.md

---
STEP 2:session 47 で何を完了したか(再作業しない)

**28 commits を master direct push(session 46 wrap → session 47 wrap)**:

【Design + spec】
- 37b388f8d1 design spec、c36137abf6 PR1 plan、1d764a9bba preflight fixes

【PR1:6 情報 JP-CLINS profile URL layer】
- be23499600 URL verification(v1.12.0、/fhir/eCS/ path 確定)
- 772e32dd18 `_JP_CLINS_PROFILES` + `_apply_jp_clins_profile` helper
- 50d06b3e05 `_build_bundle` wiring
- c00a10f9f5 completeness invariant(AD-66 canonical fixture)
- edec444273 integration test(p=100 JP)
- c459335cc7 docs/jp-clins.md + TODO tick

【PR2a:退院時サマリー Full JP-CLINS 準拠】
- 78b306dbd6 PR2 split(PR2a + PR2b)
- 7dc085b3ba doc-typecodes + doc-section CodeSystems(48 codes)
- 52f210349b `composition_sections_jp` override + accessor
- 6fb370eb5b 4 JP section renderer(admission_reason/details/diagnoses/present_illness)
- 05bed4c28e `_build_jp_clins_discharge_summary_composition` builder
- 1107536202 integration + **多locale bug fix:_build_reference_range**
- 96f6241587 docs + 4 test migration
- 297c78b591 **多locale bug fix:apply_replacement_strategy + semantic_check**

【PR2b:診療情報提供書 Full JP-CLINS 準拠】
- 6b79397dec REFERRAL_NOTE doc type + 20% fraction 発行 + Composition builder

【Comment lang rule】
- b804967a3f JP-only 日本語コメント適用(PR2a + PR2b)
- d145a2206a CLAUDE.md 明文化

【PR3:JP-eCheckup Composition infra + sub-PRs】
- 005fa9f17a infra(HEALTH_CHECKUP_REPORT + LOINC 53576-5 修正 + Composition builder)
- 07d2d638c3 sub-PR-A health_checkup enricher module
- 087f52dd75 sub-PR-B renderer 個別化 + 新 CIFPatientRecord pattern
- c895e9b9d1 sub-PR-C HL7 Validator bridge(script + workflow_dispatch)
- a9b9efbab1 sub-PR-D 3 種別 age-based dispatch

【wrap】
- 89e689bd27 TODO wrap header

---
STEP 3:実バグ検出+fix(3 件)

user 明示の「他モジュールへの影響」チェック per、integration test 実行で 3 多locale bug 検出+修正:

1. `_build_reference_range`:JP Core extension URL が US Observation にリーク → country gate 追加
2. `apply_replacement_strategy`:US-only `llm_enabled_sections` が JP output で ghost sections → country-aware accessor
3. `semantic_check._check_expectations` / `_check_structure`:US-only section list で validation → JP variant union

---
STEP 4:テスト状態(session 47 wrap 時)

- **Unit 2578 PASS**(session 46 wrap 2487 + PR1 17 + PR2a 34 + PR2b 7 + PR3 9 + sub-PR-A 5 + sub-PR-B 6 + sub-PR-D 13)、regression 0
- reproduce.sh PASS(US 272 + JP 192 files byte-identical)
- Integration:session 末 batch 実行済(#144 = test_jp_clinical_impression_structural_fields_present pre-existing known-fail、by-design ci-in-progress)
- e2e:37 PASS(既知安定)

---
STEP 5:Empirical 検証結果(session 47 中に確認済み)

**p=500 seed=42 JP end=2026-06-30 health_checkup opt-in**:
- 事業者健診: 29 encounters(40-64 中年層)
- 特定健診: 30 encounters(65-74 歳層、退職前後)
- 広域連合健診: 24 encounters(75+ 高齢層)
- 3 種類すべての section code(01031/01032, 01011/01012, 01021/01022)実出力確認

**p=100 seed=42 JP e2e**(sub-PR-B):
- Composition `comp-CHK-POP-000013-001-01` に個別化 section text.div 完全 populate
- 01031「BMI 22.5 標準 / 118/76 mmHg 基準内 / HbA1c 5.4% 基準内 / LDL 118 mg/dL 基準内 / 総合判定 A」
- 01032「既往歴 = 脂質異常症（E78）/ 服薬 Atorvastatin 10mg / 現在喫煙中 / 継続経過観察を要す」

---
STEP 6:重要 workflow rules(session 47 で継続 or 制定)

- **★ direct-master 方式**:PR 不要、コミット push per master、feedback-clinosim-workflow per
- **★ JP-only 日本語コメント / 共通英語**(session 47 制定、CLAUDE.md 明文化):
  - JP-CLINS builder / JP section renderer / _build_jp_clins_* / _JP_CLINS_* maps / codes/data/jpfhir-*.yaml → 日本語
  - _apply_jp_clins_profile / _referral_note_fires / _build_composition dispatcher → 英語
- **★ long-running is session-end batch**(memory feedback-batch-long-running-ci、feedback per):
  integration/e2e は次 blocker でない限り session 末 1 回。PR ごとに 30 分待つのは無駄。
- **推奨提示時 6 軸評価**(データ品質/臨床整合/FHIR-JP Core/メンテ性/モジュール責任/EHR-EMR goal)
- **同 class バグ 1 件 → 全 sibling sweep**(feedback-check-sibling-bugs-across-modules)
- **観測前に語らない**(feedback-verify-before-asserting)

---
STEP 7:次 session 候補

【新規高価値タスク】
1. **Cycle 8 監査**:2578 unit 通過後の JP p=10000 監査再開
   - memory `feedback_audit_cycle_workflow` per(30 問題点、by-design registry 参照必須、22 entries 既存)
   - focus:P2-13 で追加された JP-CLINS/JP-eCheckup output の品質・整合性
2. **P2-14 "Add your country" ガイド + 国パック scaffold**:session 46 backlog
3. **P2-15 Benchmark**:sepsis / AKI 予測タスク + baseline eval script
4. **β-JP-1 実 LLM narrative**:現状 template-based、seam 準備済(Ollama/Bedrock 実行未)

【P2-13 高度化】
5. **PR3 sub-PR-B 高度化**:実 ObservationRecord を Age/BMI/性別で個別化(現状の 22.5/118/76/5.4/118 固定値は決定的 replay 用)
6. **PR3 sub-PR-C 高度化**:jpfhir IG package `.tgz` の SHA256 pinning + CI auto-fail gate 化
7. **PR3 sub-PR-E 候補**:健診 encounter 周辺 FHIR resource(Coverage-Insurance / DocumentReference-eCheckup 等)

【Deferred cleanup(3 件、docs/jp-clins.md にも記載)】
8. CIF `orders` list 分離(`medication_orders` / `lab_orders` field 化、FHIR resource type separation 反映)
9. CLI `generate` → `simulate` rename(deprecation alias 経由、docs/README 全更新必要)
10. `_JP_CORE_PROFILES: dict[str, str]` → `dict[str, list[str]]` unification(JP-CLINS shape と統一)

---
STEP 8:プロジェクトコンセプト+ロジックデザイン把握(cold-start 用サマリ)

**clinosim** = population-driven, physiology-based synthetic EHR data simulator。

**目的**:JP EHR/EMR sample data generator、Synthea(US 中心)との差別化ポイント =
- JP Core / JP-CLINS / JP-eCheckup Full 準拠
- 実クリニカルワークフロー(inpatient/outpatient/ED/health checkup)を physiology で駆動
- 決定的(seed + config 固定 → byte-identical output)

**データ流れ**:
1. **Population generation**(demographics + chronic conditions + allergies)
2. **Simulation loop**:disease event → encounter simulator(inpatient/outpatient/emergency)
   - inpatient:日次 progress、POST_ENCOUNTER enricher chain(device/hai/antibiotic/imaging/triage/nursing/document)
3. **POST_RECORDS enricher**(nursing/immunization/family_history/code_status/care_level/health_checkup(opt-in))
4. **CIF 書き出し**(structural JSON per patient + narrative subtree separate versioned)
5. **Two-pass narrative**(Stage 2 TemplateNarrativePass、Composition section populate)
6. **FHIR R4 Bulk Data Export**(1 NDJSON per resource type + manifest.json)

**主要 Architecture rules**:
- **CIF is the only simulation output**(AD-17)+ codes only, no display text(AD-30)
- **LLM calls only via `llm_service`**(AD-11)
- **Deterministic with seed**(AD-16、per-module sub-seed)
- **Module independence**(each depends only on types/codes/locale + declared modules)
- **Opt-in module = extensions dict**(AD-55/56、health_checkup が JP-only 6 番目 opt-in)
- **Two-pass narrative**(AD-65、structural CIF + narrative separate files)

**JP-CLINS + JP-eCheckup 対応(session 47)の architecture**:
- **CodeSystem 3 新 yaml**:
  - `jpfhir-doc-typecodes.yaml`(5 codes、Composition.type 用)
  - `jpfhir-doc-section.yaml`(43 codes、JP-CLINS section)
  - `jpfhir-eCheckup-section.yaml`(7 codes、JP-eCheckup section)
- **Composition builder dispatch**(`_fhir_composition.py:_build_composition`):
  - lang="ja" + LOINC 18842-5 → 退院時サマリー(300 nesting 5 sections)
  - lang="ja" + LOINC 57133-1 → 診療情報提供書(2-level tree 920+910+300→950/340/360)
  - lang="ja" + LOINC 53576-5 → 健診結果報告書(flat 2 sections、checkup_type で dispatch)
- **DocumentTypeSpec 拡張**:`composition_sections_jp` + `llm_enabled_sections_jp` + accessor(PR2a)
- **ClinicalDocument 拡張**:`checkup_type: str = ""`(sub-PR-D、age-based dispatch 用)
- **PATIENT PROFILE 参照**:health_checkup renderer が chronic_conditions/current_medications/smoking_status/alcohol_use を読取り
- **health_checkup enricher pattern**(POST_RECORDS):既存 record に append せず新規 CIFPatientRecord を append(narrative pass が record.encounters[0] で spec applicability 判定するため、健診専用 record で isolation)

**多locale 隔離原則**(session 47 で強化):
- US bundle は JP CodeSystem URI / JP-CLINS profile URL / 日本語 tokens ゼロ
- integration test `test_us_p50_has_no_japanese_language_leakage` が byte-scan で強制(session 47 で bug 3 件検出)

---
STEP 9:再開時ユーザーへの最初の一言例

「Session 47 wrap 状態確認済(master 89e689bd27、P2-13 v0.3 flagship 完成、
JP-CLINS 3文書 + 6情報 + JP-eCheckup 3種別 opt-in + HL7 Validator bridge、
2578 unit + reproduce PASS)。次に何を進めますか?

候補:
(a) Cycle 8 監査(JP p=10000、by-design registry 22 entries 参照)
(b) P2-14 add-your-country ガイド + 国パック scaffold
(c) P2-15 benchmark(sepsis/AKI 予測 + baseline eval)
(d) PR3 sub-PR-B 高度化(実 Observation Age/BMI 個別化)
(e) PR3 sub-PR-C 高度化(IG package pinning + CI auto-fail)
(f) PR3 sub-PR-E(Coverage-Insurance / DocumentReference 等)
(g) Deferred cleanup 3 件(CIF orders 分離 / CLI rename / _JP_CORE_PROFILES unify)
(h) β-JP-1 実 LLM narrative(Ollama/Bedrock 実行)
(i) その他」

---
参考:session 47 で使用した pattern(session 48 で再利用可)

- **URL 一次照会**(WebFetch):jpfhir.jp の canonical URL は必ず fetch で確認、guess しない
  - 例:健診の LOINC が JPGCHKUP01 だと思っていたが実際は 53576-5(session 47 PR3 で発覚)
  - 例:JP-CLINS Composition profile の base path は `/fhir/eDischargeSummary/` `/fhir/eReferral/` `/fhir/eCheckup/`(`/fhir/clins/` ではない)
- **Preflight review pattern**:plan 実行前に既存コードとの矛盾を batch check(user 明示 per)
- **spec + plan → 実行 chain**:大 scope は brainstorming skill → spec → plan → sub-agent 実行(または inline 実行)
- **6 軸推奨評価**:データ品質 / 臨床整合 / FHIR-JP Core / メンテ性 / モジュール責任 / EHR-EMR goal
- **byte-diff invariant**:US bundle は変更 0、JP bundle は intentional な profile URL 追加のみ、reproduce.sh 継続 PASS
- **AD-66 canonical fixture 活用**(PR2a Task 6):subprocess でなく in-process run_forced + convert_cif_to_fhir で unit test 高速化
- **健診 dedicated CIFPatientRecord pattern**(sub-PR-B fix):既存 record に append すると narrative pass が spec applicability 判定失敗、新規 record で isolation
```

以上を貼り付けて session 48 開始。
