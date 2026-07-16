# Session 54 Resume Prompt

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
- master HEAD: session 53 wrap docs commit(#162 merge SHA、この resume prompt 自身の commit)
- 直上に `7c4b2a2626` = `docs(readme): add architecture pipeline SVG(#148) (#161)`
- origin/master 同期
- status: clean
- open PRs = 0、open Issues = 0(session 53 末で全 close 済み)

異なる HEAD なら pull/rebase。

---

## STEP 1:Session 53 の到達点を把握(必読)

1. **Memory `project_session_53_end_state.md`** = session 53 で merged した 8 PR の詳細 + iris4h-ai regen swap 状態
2. **Memory `project_clinosim`** = 全体概要 + Tier 状態
3. **Memory `feedback_clinosim_workflow`** = Issue → PR → Merge workflow
4. **Memory `feedback_git_commit_signoff`** = DCO check 必須(全 commit `--signoff`)
5. **Memory `feedback_issue_pr_self_contained`** = Issue/PR body に local file 参照禁止
6. **Memory `feedback_verify_fhir_profile_uri_from_spec`** = spec fixedUri 直接引用
7. **CLAUDE.md § Development workflow** = canonical workflow reference
8. **TODO.md 冒頭 Status(session 53 CLOSED)** = 全 PR merge SHA + テスト状態 + 残 backlog

---

## STEP 2:★★★ workflow rules(session 53+ = 継続)

**master 直接 push 禁止**、必ず以下:

1. **Issue 起票**(GitHub、tracker 化、body は self-contained = 実 JSON + spec URL のみ、local file 参照禁止)
2. `git checkout -b <type>/<slug>`(例 `fix/valueset-p1-8`、`feat/bp-profile-magic-loinc`)
3. Commit `--signoff` 必須(DCO check)+ `Co-Authored-By` + `Claude-Session`
4. `gh pr create` + Issue link + 検証結果(unit / mypy / ruff / reproduce)
5. **CI 全 job PASS(Unit 3.11/3.12 + Reproducibility + Build + Integration + Lint + Type check + mkdocs + Signed-off-by)**が merge blocker
6. `gh pr merge --squash --delete-branch`
7. Issue close(merge SHA post、`Fixes #NNN` trailer で自動 close)

**scope-discipline**: 1 PR = 1 論点。
**hotfix 例外**: 本番 blocker(CI 全落ち / silent-drop 検出)のみ direct-master OK、post-hoc Issue + comment 必須。
**signoff 忘れ recovery**: `git commit --amend --signoff --no-edit` + `git push --force-with-lease origin <branch>`(feature branch のみ、master への force push 絶対禁止)

---

## STEP 3:Session 53 で完了したこと(再作業しない)

### 8 PR merged via Issue→PR→Merge workflow

**HAPI feedback chain**:

| PR | Issue | 主要成果 | Merge SHA |
|---|---|---|---|
| #151 | #150 | F-2+B Observation.category → JP CS in-place replace | `85f091a538` |
| #153 | #152 | F-1 Medication OID → HOT7/9/13/YJ URI dispatch | `d992a86211` |
| #155 | #154 | F-4 Condition.severity JP CS primary | `bda4904f37` |
| #157 | #156 | D CLINS document-section canonical URL 訂正 | `502361326c` |

**Backlog chain**:

| PR | Issue | 主要成果 | Merge SHA |
|---|---|---|---|
| #158 | #144 | ClinicalImpression test を snapshot-in-progress by-design 対応 + CI deselect 除去 | `27b04e39be` |
| #160 | #145 | JP Core meta.profile 14→18 resource(ServiceRequest / DocumentReference / FamilyMemberHistory / ImagingStudy_Radiology) | `6b798138a4` |
| #159 | #149 | US locale JP text leak sibling sweep(hpi + physical_exam + daily_trajectory 3 系統)、eval `no_japanese_leakage: PASS` 実測 | `b29cc06c10` |
| #161 | #148 | architecture pipeline SVG 作成(light/dark、self-contained、accessibility) | `7c4b2a2626` |

**Legacy issue close**:#142(ruff check)/ #143(ruff format)/ #146(mypy stubs)は session 52 fix 実効 verify で close、#147(demo GIF)は user 判断で defer close(手順は close comment 保存)。

### iris4h-ai/fhir_r4 regen swap

- **元**:2026-07-14 10:53(session 51 前)
- **現**:2026-07-16 10:12:34(**session 53 中**、regen 時点 master `502361326c`)
- 反映:session 51 + 52 + 53 の #151/#153/#155/#157(**F+D 系 4 PR**)
- 未反映:**#158/#159/#160/#161(regen 後 merge のため次回 regen で反映)**
- 属性:JP p=10000 seed=300、4.6GB、26 resource types

### 主要 metric

| 項目 | Before session 53 | After session 53 |
|---|---:|---:|
| Unit tests | 2704 PASS | **2727 PASS**(+23 new) |
| mypy strict errors | 0 | **0**(維持) |
| ruff check errors | 0 | **0**(維持) |
| open Issues | 8(#142-#149) | **0** |
| open PRs | 0 | **0** |
| HAPI feedback 期待減 | 0 | **~134k**(F+D 系 4 PR 分) |

---

## STEP 4:Session 54 で優先すべき候補

### 候補 A(Recommended):iris4h-ai HAPI Validator 再走

session 53 で iris4h-ai/fhir_r4 が 2026-07-16 10:12 swap 済み。**期待**:
- session 51 P1-4 URI 訂正(3.06M件)= 完全解消
- session 51 P1-3 dose 欠落(134件)= 解消
- session 51 imgst/imgrpt double-prefix(pre-existing)= 解消
- session 52 Tier A HAPI feedback(invalid id 758k / TZ 262 / dangling 1050+)= 完全解消
- session 53 F-2+B(~75k)+ F-1(~53k)+ F-4(~5k)+ D(~1.3k)= 合計 **~134k 削減**

user 側で HAPI Validator + JP Core 1.2.0 + jpfhir-terminology 2.2606.0 + JP-CLINS 1.12.0 再走 → 結果を新 Issue 起票、または diff report として TODO.md に記録。

### 候補 B(高価値):P3-P4 大 chain(user 判断待ち)

iris4h-ai feedback V4 の残 P3-P4(scope 大、Option 判断必要):

- **P3 E** eCS profile 制約違反 ~334k = **Option 1**(identifier + lastUpdated + category max=1 + specimen + referenceRange.extension emit)/ **Option 2**(profile 撤去)= CLINS 5情報送信対象なら Option 1、それ以外 Option 2
- **P3 A** 標準 CodeSystem 日本語 display ~785k = **Option 1**(display 省略、terminology server 補完)/ **Option 2**(英語固定、辞書必要)/ **Option 3**(translation extension、日本語残す)
- **P3 G-2** JLAC10 5桁 → 17桁化 ~23k = MEDIS master-JLAC10-17digits migration
- **P4 F-3** LOINC → JLAC bilingual ~23k = LOINC 継続 or JLAC 追加
- **P4 C** LOINC LA prefix code 有効性 ~31k = LOINC 2.82 有効 code に置換

### 候補 C:未反映 4 PR 反映 2 回目 regen

iris4h-ai の 2026-07-16 10:12 swap には #158/#159/#160/#161 が未反映。特に **#160 の JP Core profile 4 追加**は HAPI validation の profile 検証差分に直結。もう 1 回 regen(~16 min)+ swap で更に fix 効果 measurable にする案。

### 候補 D:CI mypy strict 化 chain

session 52 で 4 rule 抑制(type-arg / no-untyped-def / no-any-return / no-untyped-call)して 0 error。目標:全 rule 有効化(404 annotation-noise の分野別消化)。approach:module 単位(`clinosim/modules/<name>/` 毎に per-file-ignores → 削除 + annotation 追加 → PR)。5-10 PR chain。

### 候補 E:E501 54 line 手動 reflow

現在 `# noqa: E501` で silence 済(24 files)。将来的にきれいに reflow して noqa 削除。scope-clarity chain(1 PR 分)。

### 候補 F:実 demo GIF 録画(#147 の後日対応)

`asciinema rec docs/assets/demo.cast` or VHS `docs/assets/demo.tape` → `agg` で GIF 化。~30s demo、README placeholder 差替。手順は #147 close comment に記録済み。

---

## STEP 5:再開時の作業順序

1. STEP 0 状態確認 + CI 最新 status 確認
2. STEP 1-3 memory / docs / rule 読解
3. Session 54 で進める候補を user と相談(A/B/C/D/E/F)
4. 選定後:
   - **Issue 起票**(self-contained body、GitHub tracker)
   - `git checkout -b <type>/<slug>`
   - 実装 → commit `--signoff` → push
   - `gh pr create`
   - CI 全 job PASS 確認(hotfix でない限り Integration も)
   - `gh pr merge --squash --delete-branch`
   - Issue close(自動 or manual)

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
   └─ session 52 で silent-drop / dangling / invalid-id 全解消、
      session 53 で F-2+B / F-1 / F-4 / D の HAPI feedback 4 系統解消
```

### 6-3 主要 architecture rules(AD = Architecture Decision)

- **AD-11** LLM calls only via `llm_service`(他 module 禁止)
- **AD-16** Deterministic with seed(per-module sub-seed、session 49 F1 で 4-phase 化 = engine.py の run_beta 内で population/simulation/postrecords/output の各 phase 独立 seed)
- **AD-17** CIF is the only simulation output(format adapters は CIF 読取のみ)
- **AD-18** Types は `clinosim/types/`、Pydantic (YAML config) + dataclass (runtime)
- **AD-30** CIF stores codes only, not display text(display は output 時 lookup)
- **AD-31** FHIR = Bulk Data Access compliant(NDJSON + manifest.json、Bundle 禁止)
- **AD-32** `--end` snapshot semantics(in-progress Encounter に discharge なし、ClinicalImpression も status=in-progress、session 53 で by-design 化)
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

### 6-5 FHIR output rules(session 51-53 で強化)

- **Multilingual coding**:Condition/Procedure は primary + interop language の dual coding[]
- **Multilingual localization**:JP 出力は 100% ja(`_localize_display()` 経由)、US は 100% en(session 53 #159 で narrative EN locale の JP text leak 完全解消)
- **referenceRange + interpretation**:数値 Observation は両方必須で互いに consistent
- **★ JP Core / JP-CLINS / JP-eCheckup profile URI は必ず spec fixedUri 引用**(session 50 adv-1 + session 51 制定、session 53 で全 8 PR 遵守)= 推測 URI 禁止 = HAPI validator silent-no-op で fix 完全無効化リスク。module-level 定数 + URI pin test 必須
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
- reader/writer 両側同期(imgst/imgrpt double-prefix session 51、MA→MR reference session 52、Observation.category 単一化 session 53 の class)
- HAI_EVENT_ID_SYSTEM canonical URI shared writer↔reader
- panel-eligible denominator NHSN definition 一致
- per-validator 6-layer(empty + per-bucket + forward-coverage + range + authoritative cross-validation + type check)
- **spec fixedUri 直接引用**(session 51 制定、session 53 で全 PR 遵守):推測 URI 禁止

### 6-7 主要 file/dir cheat sheet

```
clinosim/
  codes/            ★ 国際 code system(locale-independent、EN-first)
    data/           ← icd-10-cm.yaml / loinc.yaml / rxnorm.yaml / snomed-ct.yaml /
                      jpfhir-doc-section.yaml (session 53 D で URI 訂正) / ...
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
      narrative/    ← template_generator(session 53 #149 EN locale short-circuit)
      audit.py      ← Bug A residual gap = closed(session 53 #149)、docstring 履歴保存
    output/         ← CIF→format adapters + 30+ _fhir_*.py builders
      fhir_r4_adapter.py  ← 主 dispatcher(_BUNDLE_BUILDERS registry)+ _JP_CORE_PROFILES
                            (session 53 #160 で 14→18 resource)+ Observation.category
                            replace(session 53 #151)
      _fhir_composition.py       ← JP-CLINS 3 文書 + document-section canonical URL
                                    (session 53 #157 訂正)
      _fhir_medications.py       ← MedicationRequest + MedicationAdministration
                                    + _resolve_jp_drug_system_uri(session 53 #153)
      _fhir_common.py            ← _severity_coding(session 53 #155 で JP CS primary
                                    + SNOMED secondary)
      _fhir_endpoint.py + _fhir_imaging_study.py + _fhir_diagnostic_report.py
      _fhir_observations.py      ← vital signs + lab results
      _fhir_facility.py          ← Organization + Location + facility Device
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
                      (session 53 #149 で us-100 no_japanese_leakage PASS 実測)
typing-stubs/       ← session 52 新設 numpy shim(PEP 695 blocker 排除)
docs/
  assets/
    pipeline.svg    ← session 53 #148 で新規追加(6 stage、light/dark、accessibility)
  session-resume/
    next.md         ← ★ 本 file
  audit-cycles/
    by-design-registry.md  ← 17+ entries(session 53 #144 で
                             snapshot-in-progress-clinical-impression-status
                             を code 側で respect)
scripts/
  reproduce.sh      ← byte-identity CI 検証
.github/workflows/
  ci.yml            ← session 53 #158 で ClinicalImpression test deselect 除去
tests/
  unit/             ← 2727 tests、~2 分(session 53 で +23 new)
  integration/      ← ~300 tests、~40 分 CI
  e2e/              ← 37 tests、~8 分
  fixtures/patient_profiles/  ← AD-66 canonical profile YAML
```

### 6-8 session 53 で強化された点(前 session からの delta)

- **HAPI feedback F/D 系 4 PR 完了**:F-2+B(Observation.category)/ F-1(Medication OID → HOT/YJ)/ F-4(Condition.severity JP CS)/ D(CLINS URL 訂正)= ~134k issue 削減見込み
- **JP Core profile coverage 14 → 18**:ServiceRequest / DocumentReference / FamilyMemberHistory / ImagingStudy_Radiology(spec `.url` 直接引用、JP Core が profile 未 publish の CareTeam / Composition / ClinicalImpression / Endpoint は base FHIR R4 維持)
- **US locale integrity 完全化**:narrative EN locale で JP YAML source を読取していた 3 系統(hpi_template / physical_exam_findings / daily_trajectory)を short-circuit、eval `no_japanese_leakage: PASS` 実測
- **CI test hardening**:ClinicalImpression by-design(snapshot-in-progress)を code で respect + CI deselect 除去
- **Workflow full flow**:Issue → PR → Merge を 8 PR で完遂、DCO check + PR body self-contained + spec fixedUri 直接引用の 3 rule 遵守
- **iris4h-ai regen swap**:JP p=10000 seed=300 → 4.6GB → 2026-07-16 10:12 完全 swap 済み

---

## STEP 7:再開時ユーザーへの最初の一言例

「Session 53 wrap 状態確認済(master `<HEAD>`、Unit 2727 PASS、mypy strict 0 error、Lint/Type/Format 全 green、reproduce.sh PASS、eval `no_japanese_leakage: PASS` on us-100、open PRs/Issues = 0、iris4h-ai/fhir_r4 = 2026-07-16 10:12 regen swap 済み)。CI final status を確認します。

Session 53 で 8 PR merged(HAPI feedback F/D 系 4 + backlog 4)。session 54 の chain を以下から選択したいです:

- **(A)** iris4h-ai HAPI Validator 再走(session 51-53 fix ~134k issue 削減の実効検証、Recommended)
- **(B)** P3-P4 大 chain(E eCS profile 334k / A CodeSystem 日本語 display 785k / G-2 JLAC10 17桁 23k / F-3 LOINC→JLAC / C LOINC LA)
- **(C)** 未反映 4 PR(#158/#159/#160/#161)反映 2 回目 regen(次回 HAPI 検証差分測定用)
- **(D)** CI mypy strict 化 chain(4 rule 段階再有効化、5-10 PR 規模)
- **(E)** E501 54 line 手動 reflow(scope-clarity 1 PR 分)
- **(F)** 実 demo GIF 録画(#147 defer close 分、asciinema/VHS)
- **(G)** その他(user 主導の新 chain / 案内)

どれで進めるか判断お願いします。」

---

## 参考:重要 workflow rules(session 53+ 継続)

- **★★★ Issue → PR → Merge 必須**(session 52 末制定、session 53 で初フル運用):CLAUDE.md § Development workflow / feedback_clinosim_workflow.md 参照
- **★★★ DCO check(全 commit `--signoff`)**(session 53 制定):feedback_git_commit_signoff.md
- **★★★ Issue/PR body は self-contained**(session 53 制定):feedback_issue_pr_self_contained.md
- **★ JP-only 日本語コメント / 共通英語**(session 47 制定)
- **★ FHIR profile URI は spec fixedUri 引用**(session 51 制定、session 53 で全 8 PR 遵守、pin test 必須):feedback_verify_fhir_profile_uri_from_spec.md
- **★ long-running は session-end batch**(feedback_batch_long_running_ci):PR ごとに 30 分待たない、integration/e2e は次 session 開始時 or 別 batch
- **★ 同 class バグ 1 件 → 全 sibling sweep**(feedback_check_sibling_bugs_across_modules、session 53 #149 で hpi/physical_exam/daily_trajectory 3 系統適用)
- **★ 観測前に語らない**(feedback_verify_before_asserting)
- **★ scope discipline**(feedback_scope_discipline):1 PR = 1 論点

---

## 補足:session 53 の technical 気付き

- **DCO check は途中で有効化された可能性**:PR #153 で初検出、以前の commit 群には signoff がなかった。amend + force-with-lease で全 PR 復旧、以降は commit 時 `--signoff` 徹底
- **lint noqa 位置破壊**:session 52 で確認された `ruff format` が noqa 位置を破壊する現象は session 53 でも継続、noqa 追加後は format 再走で確認
- **prefer-color-scheme SVG dark 対応**:GitHub / MkDocs は個別に light/dark を反映するが SVG 側で完結できる。`@media (prefers-color-scheme: dark)` を SVG `<style>` に含める(#161)
- **iris4h-ai swap は完全上書き**:`rm -rf iris4h-ai/fhir_r4 && mv scratchpad/... iris4h-ai/fhir_r4`。~4.7GB 削除 + 移動で数秒
- **CI Integration 40 分待ちの並行化**:session 53 では複数 PR の Integration を並行で走らせ、squash merge 順を SUCCESS 順に整理。個別に blocking 待ちしない
