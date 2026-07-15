# Session 53 Resume Prompt

## STEP 0:状態確認(必須、順序厳守)

```bash
cd /Users/tokuyama/workspace/clinosim
git branch --show-current
git log --oneline -12 master
git log --oneline -3 origin/master
git status --short
git worktree list
git stash list
```

**期待値**:
- current branch: `master`
- master HEAD: `894a578fd3` = `docs(session): session 52 wrap + session 53 resume prompt(direct-master 最終例外)`
- 1 つ手前:`72e1b4db33` = `docs(workflow): direct-master 方式を Issue→PR→Merge に切替(session 52 末、user 明示)`
- origin/master 同期
- status: clean(scratch cleanup 済、work tree 汚染なし)

異なる HEAD なら pull/rebase。

---

## STEP 1:session 52 wrap 状態と workflow 変更を把握(必読)

1. **Memory `project_session_52_end_state.md`** = 9 commits + Type check green + workflow 切替の詳細
2. **Memory `feedback_clinosim_workflow.md`** = Issue→PR→Merge 手順(必ず読む)
3. **CLAUDE.md § Development workflow** = 同手順の canonical source
4. **TODO.md 冒頭 Status(session 52 CLOSED)** = 全 commit + テスト状態 + 残 backlog

---

## STEP 2:★★★ 重要 workflow 変更(session 53+ 発効)

**master 直接 push 禁止**。以下必須:

1. **Issue 起票**(GitHub、tracker 化)
2. `git checkout -b <type>/<slug>`(例 `fix/valueset-p1-8`、`feat/bp-profile-magic-loinc`)
3. Commit + push to feature branch(`Co-Authored-By` + `Claude-Session` 従来通り)
4. `gh pr create` + Issue link + 検証結果(unit / mypy / ruff / reproduce)
5. **CI 全 6 job PASS(Unit 3.11/3.12 + Reproducibility + Build + Integration + Lint + Type check)**が merge blocker
6. Adversarial review(大 chain のみ推奨)= `/code-review`
7. `gh pr merge --squash --delete-branch`(基本 squash)
8. Issue close(merge SHA を post)

**scope-discipline**: 1 PR = 1 論点。
**hotfix 例外**: 本番 blocker(CI 全落ち / silent-drop 検出)のみ direct-master OK、ただし post-hoc Issue + comment 必須。

---

## STEP 3:Session 52 で完了したこと(再作業しない)

### 9 commits direct-master(session 52 開始時 `5a5a77ed42` → 終了時 `72e1b4db33`)

```
72e1b4db33 docs(workflow): direct-master 方式を Issue→PR→Merge に切替(session 52 末、user 明示)
fd3329a918 fix(typing): CI Type check 完全 green 化 — numpy stub shim + 53 real bug fix
b2f92821ad lint(session52): E501 個別 noqa + ruff format sweep — Lint job 完全 green 化
7b06759e4d lint(session52): informational lint 387→54 一括削減(auto-fix + per-file-ignores + line-length 120)
2969dff15d fix(lint,mypy): real F821/F601 バグ + mypy boto3/numpy override
4921bd6515 fix(fhir): MedicationAdministration.request reference — order_id 単体へ同期
a0854d5cca fix(fhir): iris4h-ai HAPI feedback — invalid id + no-TZ dateTime 完全解消(3 系統)
c8d7959c1d fix(session52): device test — facility-shared pump は 1:1 DUS 対象外 + SNOMED whitelist 拡張
d88ae6c357 fix(session52): integration test 5 系統解消 — order_id encounter-scoping + dangling refs + imaging inference
```

### 主要 metric

| 項目 | Before | After |
|---|---|---|
| Integration failure | 9 | **0** |
| silent-drop orders(order_id 衝突)| 1337 | **0** |
| iris4h-ai HAPI invalid id | 758,275 | **0** |
| Procedure TZ 欠如 | 262 | **0** |
| dangling reference(MA→MR + Device + Location)| 1,050+ | **0** |
| CI Lint errors | 387 | **0** |
| CI Type check errors | 1(checking prevented)| **0** |
| Unit tests | 2704 | 2704 PASS |

---

## STEP 4:Session 53 で優先すべき候補

### 候補 A(Recommended):iris4h-ai HAPI feedback Tier B chain

user 主導で PR chain 化(1 PR = 1 subcategory):

- **PR #1**:coding が ValueSet 外(clinicalStatus / verificationStatus / Coverage Class 系、12 pattern 327件)= spec ValueSet 内 coding へ切替 + pin test
- **PR #2**:CodeSystem 内 code 不明(SNOMED 424535000 / LOINC 30794-3 / v2-0360 RD / v3-RoleCode OUTPT / UCUM mmHg / Encounter serviceType custom / SNOMED 303408005 / ICD-10 I84)= 有効 code へ差替 + pin test
- **PR #3**:SNOMED inactive concept 更新(227037002 / 256349002 / 103693007)+ inactive-check unit test
- **PR #4**:LOINC 対応 profile 未指定(BMI / BP)= meta.profile 付与
- **PR #5**(大)**BP profile magic LOINC 85354-9**(13,766件)= FHIR BP profile 準拠、component slice + magic LOINC。既存 Observation.vital_signs から BP を分離した combined-BP Observation emit
- **PR #6**(大)**referenceRange.extension 欠如**(89,238件)= JP_Observation_Common で必須の extension emit(全 lab Observation に relative to reference range 属性追加)

### 候補 B:iris4h-ai/fhir_r4 再生成 + HAPI validator 再走

session 52 fix 群を反映した実効検証:
1. `clinosim simulate -o output-p10000-seed<X> --population 10000 --seed <new> --country JP --start 2025-04-01 --end 2026-03-31 --format fhir-r4`(16 分)
2. iris4h-ai/fhir_r4 に copy
3. iris4h-ai 側で HAPI Validator + JP Core 1.2.0 再走
4. 期待:P1-4 slice 3.06M / invalid id 758k / TZ 262 / dangling 1050+ が全て 0
5. 結果を Issue で報告 → Tier B chain と紐付け

### 候補 C:mypy strict 化 chain(Type check level up)

現状:strict + 4 rule 抑制(type-arg / no-untyped-def / no-any-return / no-untyped-call)で 0 error
目標:全 rule 有効化(404 annotation-noise の分野別消化)
approach:module 単位(clinosim/modules/<name>/ 毎に per-file-ignores → 削除 + annotation 追加 → PR)。5-10 PR chain。

### 候補 D:E501 54 line 手動 reflow

現在 `# noqa: E501` で silence 済(24 files)。将来的にきれいに reflow して noqa 削除。scope-clarity chain(1 PR 分)。

---

## STEP 5:再開時の作業順序

1. STEP 0 状態確認 + CI(72e1b4db33)final status 確認
2. STEP 1-3 memory / docs / rule 読解
3. Session 53 で進める候補を user と相談(A/B/C/D)
4. 選定後:
   - **Issue 起票**(GitHub、tracker として)
   - `git checkout -b <type>/<slug>`
   - 実装 → commit → push
   - `gh pr create`
   - CI 全 6 job PASS 確認
   - `gh pr merge --squash --delete-branch`
   - Issue close

---

## STEP 6:プロジェクトコンセプト + ロジックデザイン(cold-start 必読)

### 6-1 プロジェクトのゴール

**clinosim** = 母集団駆動・生理学ベースの合成 EHR/EMR データ生成器(v0.3.x)。
差別化点(vs Synthea 等):
- **JP Core / JP-CLINS / JP-eCheckup Full 準拠**(日本の医療 IT 基準対応が第一級)
- **実クリニカルワークフロー**(inpatient / outpatient / ED / health checkup)を生理学 state で駆動 = 検査値・バイタルは全て hidden physiological state から derive
- **決定論的**(seed + config 固定 → byte-identical output、reproduce.sh CI で常時検証)
- **cron 日次追記対応**(session 49 F1-F4、`--cache-dir` で snapshot memoize)

### 6-2 データ流れ(pipeline)

```
1. Population generation
   ├─ demographics (locale/<c>/demographics.yaml 由来)
   ├─ chronic conditions (age/sex band × prevalence)
   └─ allergies (allergy_enricher, POST_POPULATION)
2. Simulation loop (per (year, month) walk)
   ├─ disease event 発火 → encounter simulator dispatch:
   │    ├─ inpatient.py   (physiology state 更新 × 毎日)
   │    ├─ emergency.py   (単一 encounter)
   │    ├─ outpatient.py  (chronic follow-up)
   │    └─ health_checkup (opt-in、JP only)
   ├─ Order 発行 → panel grouping → 検査値 derive
   └─ 各 encounter 単位で CIFPatientRecord 生成
3. POST_ENCOUNTER enricher chain(order 70-95)
   ├─ device (70)     — ICU 器械留置 (CVC/urinary catheter/ventilator)
   ├─ hai (80)        — CDC NHSN HAI サンプリング + lab lift
   ├─ antibiotic (85) — 経験療法 + S/I/R 感受性 → narrow/de-escalation
   ├─ imaging (90)    — Order(IMAGING) → ImagingStudyRecord + Endpoint + report
   ├─ triage (93)     — ED-only、triage acuity
   ├─ nursing (94)    — inpatient/ICU/rehab の primary nurse 割当
   └─ document (95)   — ClinicalDocument stub + ClinicalImpression
4. POST_RECORDS enricher chain(order 10-60)
   ├─ nursing_flowsheets (20) — NEWS2/GCS/Braden/Morse
   ├─ immunization (30)
   ├─ family_history (40)
   ├─ code_status (50)  — DNR/CMO
   └─ care_level (60)   — JP 要介護度
5. CIF 書き出し
   ├─ structural JSON per patient (cif/structural/patients/<enc>.json)
   └─ narrative subtree separate versioned (cif/narratives/<v>/documents/)
6. Two-pass narrative(AD-65、session 28 で復元)
   └─ TemplateNarrativePass が structural CIF を読み Composition section populate
7. FHIR R4 Bulk Data Export
   ├─ 1 NDJSON per resource type + manifest.json
   ├─ Resource.id は encounter-scoped で globally unique
   └─ session 52 で silent-drop / dangling / invalid-id 全解消
```

### 6-3 主要 architecture rules(AD = Architecture Decision)

- **AD-11** LLM calls only via `llm_service`(他 module 禁止)
- **AD-16** Deterministic with seed(per-module sub-seed、session 49 F1 で 4-phase 化 = engine.py の run_beta 内で population/simulation/postrecords/output の各 phase 独立 seed)
- **AD-17** CIF is the only simulation output(format adapters は CIF 読取のみ)
- **AD-18** Types は `clinosim/types/`、Pydantic (YAML config) + dataclass (runtime)
- **AD-30** CIF stores codes only, not display text(display は output 時 lookup)
- **AD-31** FHIR = Bulk Data Access compliant(NDJSON + manifest.json、Bundle 禁止)
- **AD-32** `--end` snapshot semantics(in-progress Encounter に discharge なし)
- **AD-55** Base vs opt-in Module(near-essential → always-on、specialized → opt-in)
- **AD-56** register_bundle_builder + register_output_adapter + register_enricher(edit-free extension)
- **AD-57** BNP-pattern surgical(`derive_lab_values` に scenario/medication flags を helper 経由で splat)
- **AD-58** OutputAdapter registry(`_BUNDLE_BUILDERS` dict / `register_output_adapter()`)
- **AD-59** Per-order lab RNG isolation(specimen-rejection/hemolysis/technician を per-order sub-rng で分離)
- **AD-60** Audit framework(`clinosim audit run` = structural / clinical / jp_language / silent_no_op 4 axis、new-feature ship-gate)
- **AD-61** classify_lab_specs helper(panel grouping single edit point)
- **AD-62** Imaging chain(`place_imaging_orders` single edit point、`_expand_views_to_series` multi-view expansion)
- **AD-63** document 6th always-on Module(ClinicalDocument stub + ClinicalImpression)
- **AD-64** triage + nursing_assignment 7th/8th always-on Module + CareTeam 2-name scope
- **AD-65** Two-pass narrative separation(structural CIF file × narrative subtree、Stage 2 で populate、session 28 復元)
- **AD-66** Canonical patient profile fixture library(narrative regression testing、golden vs snapshot 12/12 PASS)
- **AD-67/68/69** Severity/archetype/YAML forbid model(FHIR completeness chain、session 38)

### 6-4 Module 独立性

- 各 `clinosim/modules/<name>/` は `types/` / `codes/` / `locale/` + 宣言済 module のみ import(README Dependencies で定義)
- **Public API surface** = `__init__.py` export のみ、`_` prefix は module-internal
- **LLM calls only via llm_service**(AD-11)、他 module から直接 Ollama/Anthropic 禁止
- **Locale-independent code system**:`clinosim/codes/` (ICD/LOINC/RxNorm/SNOMED-CT/JLAC10 等) は EN-first、`clinosim/locale/` (names/addresses/reference_range/code_mapping) は country-specific

### 6-5 FHIR output rules(session 51-52 で強化)

- **Multilingual coding**:Condition/Procedure は primary + interop language の dual coding[]
- **Multilingual localization**:JP 出力は 100% ja(`_localize_display()` 経由)、US は 100% en
- **referenceRange + interpretation**:数値 Observation は両方必須で互いに consistent
- **★ JP Core / JP-CLINS / JP-eCheckup profile URI は必ず spec fixedUri 引用**(session 50 adv-1 + session 51 制定)= 推測 URI 禁止 = HAPI validator silent-no-op で fix 完全無効化リスク。module-level 定数 + URI pin test 必須
- **Resource id は FHIR 型準拠**(`[A-Za-z0-9\-\.]{1,64}`)= session 52 で `sanitize_id_token` helper に一元化
- **encounter-scoped order_id**(session 52 sweep):writer id-dedup による silent-drop 防止

### 6-6 Silent-no-op defense(setup 累積)

**4 層防御**:
1. **canonical constants**(HAI_TYPES / SUPPORTED_MODALITIES / ANTIBIOTIC_DRUGS 等)を module-level に定義
2. **_validate_*(data) -> None** を YAML loader に配線(import 時 fail-loud)
3. **normalize_probabilities(..., fallback="raise")** を全 15 YAML-sourced callsites に適用
4. **reverse-coverage(forward + staleness)** を canonical set 側にも(HAI_TYPES / SUPPORTED_BODY_SITES 等)

**PR-90 教訓**(2026-06 hai lab lift silent-no-op)以降、以下の 7 chain pattern を確立:
- lift firing proof(equality_checks + tolerance で "fired count > 0" 保証)
- 4-stage adversarial chain(original → adv-1 → adv-2 → adv-3 で converged)
- reader/writer 両側同期(imgst/imgrpt double-prefix session 51、MA→MR reference session 52 の class)
- HAI_EVENT_ID_SYSTEM canonical URI shared writer↔reader
- panel-eligible denominator NHSN definition 一致
- per-validator 6-layer(empty + per-bucket + forward-coverage + range + authoritative cross-validation + type check)
- **spec fixedUri 直接引用**(session 51 制定):推測 URI 禁止

### 6-7 主要 file/dir cheat sheet

```
clinosim/
  codes/            ★ 国際 code system(locale-independent、EN-first)
    data/           ← icd-10-cm.yaml / loinc.yaml / rxnorm.yaml / snomed-ct.yaml / ...
    loader.py       ← lookup(system, code, lang) canonical API
  locale/<c>/       ← 国別 demographics / names / addresses / code_mapping / reference_range
  config/           ← hospital_*.yaml + llm_service*.yaml
  types/            ← Pydantic (YAML config) + dataclass (runtime)
  modules/          ← 各 module 1 dir、README で dependencies 宣言
    identity/       ← JP 被保険者番号(opt-in、AD-54)
    device/         ← CVC/urinary catheter/ventilator(POST_ENCOUNTER 70)
    hai/            ← CLABSI/CAUTI/VAP + lab lift + S/I/R(POST_ENCOUNTER 80)
    antibiotic/     ← 経験療法 + narrow/de-escalation(POST_ENCOUNTER 85)
    imaging/        ← ImagingStudy + Endpoint + radiology DR(POST_ENCOUNTER 90)
    triage/         ← ED triage acuity(POST_ENCOUNTER 93、ED-only)
    nursing/        ← primary nurse (assignment、94) + flowsheets (POST_RECORDS 20)
    document/       ← ClinicalDocument stub + ClinicalImpression(POST_ENCOUNTER 95)
    output/         ← CIF→format adapters + 30+ _fhir_*.py builders
      fhir_r4_adapter.py         ← 主 dispatcher(_BUNDLE_BUILDERS registry)
      _fhir_common.py            ← to_fhir_datetime / to_fhir_instant / sanitize
      _fhir_composition.py       ← JP-CLINS 3 文書
      _fhir_endpoint.py + _fhir_imaging_study.py + _fhir_diagnostic_report.py
      _fhir_medications.py       ← MedicationRequest + MedicationAdministration
      _fhir_observations.py      ← vital signs + lab results
      _fhir_facility.py          ← Organization + Location + facility Device(hospital-main/dev-infusion-pump)
      ...(30+ theme 別 builder)
  simulator/
    engine.py       ← run_beta 主 loop(session 49 F1 で 4-phase seeding)
    inpatient.py    ← _simulate_patient + _run_daily_loop(2200+ lines)
    emergency.py + outpatient.py
    enrichers.py    ← POST_POPULATION / POST_ENCOUNTER / POST_RECORDS registry
    seeding.py      ← ENRICHER_SEED_OFFSETS + panel_specimen_seed + individual_lab_seed
    cli.py          ← generate / simulate / audit / diff / test-disease etc.
  audit/            ← 4-axis audit framework(structural / clinical / jp_language / silent_no_op)
  eval/             ← 3-axis eval framework + synthea_adapter + preset test
typing-stubs/       ← ★ session 52 新設 numpy shim(PEP 695 blocker 排除)
scripts/
  reproduce.sh      ← byte-identity CI 検証
tests/
  unit/             ← 2704 tests、~2 分
  integration/      ← ~300 tests、~40 分 CI
  e2e/              ← 37 tests、~8 分
  fixtures/patient_profiles/  ← AD-66 canonical profile YAML
```

### 6-8 session 52 で強化された点

- **CI 全 6 job green**(Unit 3.11/3.12 + Reproducibility + Build + Integration + Lint + Type check)= session 46 informational marker 導入以来の初完全 green
- **workflow Issue → PR → Merge**(session 53+ 必須、hotfix 例外あり)
- **typing-stubs/numpy shim** = numpy 2.5+ PEP 695 stub blocker 排除、mypy strict 0 error
- **sanitize_id_token helper** = FHIR id 型互換 token single source
- **order_id encounter-scoping** 24 site sweep = silent-drop 1337 orders 根治
- **iris4h-ai HAPI Tier A 完全解消**(invalid id 758k + TZ 262 + dangling 1050+ → 0)
- **`_interpolate` int() cast bug** 発見+ fix(mypy 化で露呈、physiology speed_factor > 1.0 で deterioration timing silent shift bug)

---

## STEP 7:再開時ユーザーへの最初の一言例

「Session 52 wrap 状態確認済(master `894a578fd3`、Unit 2704 PASS、mypy strict 0 error、Lint/Type/Format 全 green、reproduce.sh PASS、Regression 12/12 PASS)。CI(894a578fd3 = session 52 wrap docs)の final status を確認します。

session 52 wrap で workflow が **direct-master → Issue/PR/Merge 必須**に切替済み。session 53 の chain を以下から選択したいです:

- **(A)** iris4h-ai HAPI feedback Tier B chain(6 PR 規模、Recommended)
- **(B)** iris4h-ai 再生成 + HAPI validator 再走(session 51/52 fix の実効検証)
- **(C)** mypy strict 化 chain(4 rule 段階再有効化、5-10 PR 規模)
- **(D)** E501 54 line 手動 reflow(1 PR 分)
- **(E)** その他(user 主導の新 chain / 案内)

どれで進めるか判断お願いします。」

---

## 参考:重要 workflow rules(session 53+)

- **★★★ Issue → PR → Merge 必須**(session 52 末制定、user 明示):CLAUDE.md § Development workflow / feedback_clinosim_workflow.md 参照
- **★ JP-only 日本語コメント / 共通英語**(session 47 制定)
- **★ FHIR profile URI は spec fixedUri 引用**(session 51 制定、pin test 必須)
- **★ long-running は session-end batch**(feedback-batch-long-running-ci):PR ごとに 30 分待たない、integration/e2e は次 session 開始時 or 別 batch
- **★ 同 class バグ 1 件 → 全 sibling sweep**(feedback-check-sibling-bugs-across-modules)
- **★ 観測前に語らない**(feedback-verify-before-asserting)
- **★ scope discipline**(feedback-scope-discipline):1 PR = 1 論点

---

## 補足:session 52 の technical 気付き

- **ruff format は noqa 位置を破壊する**:閉じ括弧が改行された結果、`)  # noqa: E501` が 1 行上の long f-string を cover しなくなる → post-format で再 noqa が必要
- **mypy python_version bump は 456 error surface**:numpy stub の PEP 695 syntax error で checking prevented だった 456 error が一気に露出。shim + strict rule 抑制の 2 段策で管理可能に
- **Integration CI は前 run が preempt cancelled されることがある**:master に短時間で連続 push すると github actions が前 run を cancel
- **並行 subagent の存在**:別 AI process の commit が挟まる場合あり、予期しない diff 出現時は他 subagent を疑う
