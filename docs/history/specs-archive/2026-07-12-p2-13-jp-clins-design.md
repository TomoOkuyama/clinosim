# P2-13 JP-CLINS 3 文書 6 情報 FHIR profile 対応 — Design

- **Date**: 2026-07-12
- **Author**: session 47
- **Status**: Draft(user review 待ち)
- **Related**:
  - `TODO.md` §"Session 47 candidates" P2-13
  - Session 42 JP Core meta.profile 拡張(既存 `_apply_jp_core_profile`)
  - Session 33-36 chain 2 厚労省 4 帳票(退院サマリー narrative 既存 asset)
  - Memory `project_ehr_sample_dataset_roadmap`
  - Memory `feedback_cif_fhir_quality_focus`(session 41 以降の基本方針)
  - Memory `feedback_scope_discipline`

## 1. Scope

### 1.1 Goal

clinosim の JP FHIR 出力を、**厚労省「電子カルテ情報共有サービス」JP-CLINS の 3 文書 6 情報 profile 準拠形式**で emit できるようにする。急性期病院想定を維持したまま、JP EMR 研究者・開発者向けの実用サンプルデータとしての価値を最大化する。

### 1.2 In-scope

- **6 情報**(既存 resource type に JP-CLINS profile URL 追加 emit — v1.12.0 一次照会 2026-07-12):
  1. 傷病名 → Condition(`JP_Condition_eCS`)
  2. アレルギー → AllergyIntolerance(`JP_AllergyIntolerance_eCS`)
  3. 感染症 → Condition(**JP-CLINS は感染症用の別 profile を publish していない**、同 `JP_Condition_eCS` でカバー。infection マーキングが必要な場合は既存の code system で ICD-10 A/B chapter 判別のみ、profile 分岐はしない)
  4. 検査 → Observation(`JP_Observation_LabResult_eCS`、category=laboratory)。**JP-CLINS は DiagnosticReport profile を publish していない** — 検査結果は Observation のみで emit(clinosim の DiagnosticReport 出力は JP Core `JP_DiagnosticReport_Common` のまま、JP-CLINS profile は付与しない)
  5. 処方 → MedicationRequest(`JP_MedicationRequest_eCS`)
  6. 処置 → Procedure(`JP_Procedure_eCS`)
- **2 文書 Composition(default on、country=JP)**:
  1. 退院時サマリー(LOINC 18842-5)— 既存 discharge summary narrative asset 活用
  2. 診療情報提供書(LOINC 57133-1)— 新規 template、fraction 発行
- **1 文書 Composition(opt-in)**:
  3. 健康診断結果報告書(LOINC code は §6 open item 2 で確定)— `SimulatorConfig.modules["health_checkup"]=True` 時のみ
- **Conformance test**:pytest 内 structural check(default gate)+ 公式 jpfhir-validator bridge(optional CI job)
- **Docs**:`docs/jp-clins.md`(spec + validator 使い方 + 制限事項)

### 1.3 Non-goal(明示的に外す)

- 機関間連携 workflow(A 病院 → B 病院への文書送信 simulation)
- SS-MIX2 出力(別 TODO entry で延期確定)
- narrative LLM 品質改善(β-JP-1 責務、seam 保持のみ)
- JP-CLINS 3 文書以外の文書型(処方情報提供書 / 訪問看護情報提供書 等)
- 電子署名 / タイムスタンプ / PKI 認証
- 健診 default 生成(急性期病院想定と乖離、opt-in 化で解決)

### 1.4 Scope 内論拠(6 軸)

| 軸 | 判定根拠 |
|---|---|
| データ品質 | 6 情報 profile URL emit は既存 JP Core session 42 実装の自然な延長 |
| 臨床整合性 | 退院サマリーは急性期病院中核業務(既に narrative 実装済)、健診は opt-in 化で急性期想定を保つ |
| FHIR-JP Core | jpfhir.jp canonical profile 準拠、`_apply_jp_core_profile` と同 pattern の重ね emit |
| メンテ性 | `_apply_jp_clins_profile` idempotent 追加のみ、Composition builder は 1 file 集約 |
| モジュール責任 | output/ 内で完結、他モジュール影響なし(health_checkup module を除く) |
| EHR/EMR goal | JP EMR 研究者・開発者向け差別化(Synthea との違い、実 EMR 連携試験流用可能) |

## 2. Architecture

### 2.1 Layer 図

```
Population generation
  ├── (opt-in) health_checkup: 対象 subset 選定 + 検診 encounter 挿入
  └── その他既存 module 群
        ↓
Simulation loop(既存 inpatient / outpatient / emergency)
  └── (opt-in) health_checkup encounter simulator
        ↓ CIF(structural)
POST_ENCOUNTER enrichers(既存 chain 継続)
        ↓
Two-pass narrative(既存 AD-65)
  └── ClinicalDocument stub:退院サマリー既存 / 診療情報提供書 新規 / 健診結果報告書 opt-in
        ↓ CIF final
FHIR Bulk Export
  ├── 既存 builder 群(_apply_jp_core_profile + _apply_jp_clins_profile 両方 idempotent)
  ├── _fhir_composition_jp_clins.build_discharge_summary
  ├── _fhir_composition_jp_clins.build_referral_note
  └── _fhir_composition_jp_clins.build_checkup_report(opt-in)
        ↓
NDJSON per resource type(Composition.ndjson に merge)
        ↓
[Optional CI] jpfhir-validator bridge
```

### 2.2 Module 責任分解点

| Module | 責任 | 依存 | 変更 impact |
|---|---|---|---|
| `output/fhir_r4_adapter.py` | `_JP_CLINS_PROFILES` map + `_apply_jp_clins_profile` 追加 | 既存 `_apply_jp_core_profile` と同構造 | idempotent → profile 追加分の byte 変化(intentional) |
| `output/_fhir_composition_jp_clins.py`(新規) | 2 文書 Composition builder(opt-in 時 3 文書目) | ctx.records / ctx.country / ClinicalDocument narrative | Composition resource 追加 = byte 変化(intentional) |
| `types/`(既存 `EncounterRecord` / `ClinicalDocument`) | 変更なし想定 | — | — |
| `modules/health_checkup/`(新規、opt-in) | encounter 挿入 + observation 生成 + Composition | population subset + reference range 既存活用 | default off → byte 変化なし |
| `modules/document/`(既存 narrative) | 診療情報提供書 template 追加 | 既存 `TemplateNarrativeGenerator` | 対象 subset にのみ narrative 生成、byte 変化(intentional) |
| `tests/unit/test_jp_clins_*.py`(新規複数) | structural check | small cohort p=100 country=JP | — |
| `docs/jp-clins.md`(新規) | ユーザー向け仕様 + validator 手順 | — | — |
| CI `.github/workflows/jp-clins-validate.yml` | optional job(default trigger off) | jpfhir-validator jar | 通常 PR に影響なし |

### 2.3 Determinism / seed 管理

新規 sub-seed(AD-16、`simulator/seeding.py:ENRICHER_SEED_OFFSETS` に追加):

- `"jp_clins_referral"` = `0x4A43`("JC")— 診療情報提供書発行判定 RNG
- `"health_checkup"` = `0x4843`("HC")— opt-in module 全般

既存 module の seed は変更しない = byte-diff invariant 保護(default 経路 = 6 情報 profile URL 追加 + 2 文書 Composition 追加のみ、これは intentional な output 変化として reproduce.sh の新 baseline を確立)。

### 2.4 CIF→FHIR no-drop invariant

- 新規 Composition は CIF 側 `ClinicalDocument` stub + 6 情報 resource 参照から機械的に構築
- CIF 側 field 追加なし(既存 `EncounterRecord.diagnosis` / `record.observations` / `record.medications` / `person.allergies` を集約)
- 健診 encounter は `EncounterRecord.encounter_type` に新規 value `"checkup"` 追加のみ → Encounter.class 別 code に mapping、既存 no-drop 保証

## 3. PR 分割(3-PR chain)

### 3.1 PR1: 6 情報 JP-CLINS profile URL layer + structural test

**目的**:country=JP 時に 6 resource type へ JP-CLINS profile URL を追加 emit。

**変更**:
- `clinosim/modules/output/fhir_r4_adapter.py`:
  - `_JP_CLINS_PROFILES` dict 追加(下記 3.1.1)
  - `_apply_jp_clins_profile(resource: dict) -> None` 追加、idempotent、`_apply_jp_core_profile` 直後に呼ぶ
  - Observation / DiagnosticReport は **category = laboratory の場合のみ** JP-CLINS profile 追加(検査以外の Observation は対象外)
  - Condition は感染症判別で **2 profile 分岐**:通常 = `JP_Condition_eCS`、感染症 = `JP_Condition_Infection_eCS`
- `tests/unit/test_jp_clins_profile_emit.py`(新規):
  - p=100 seed=42 country=JP 生成
  - 各 resource type ごとに profile URL 存在 + JP Core URL 併存 + idempotency 検証
  - 感染症判別分岐が両方 emit されること
  - country=US では JP-CLINS profile emit されないこと
- `tests/unit/test_completeness_invariants.py` に「JP-CLINS profile emit gate」追加

**Conformance test(structural)**:
1. Condition.clinicalStatus 必須(全 emit で存在)
2. AllergyIntolerance.type 必須(allergy / intolerance)
3. Observation.effective[x] 必須(lab)
4. Procedure.performedDateTime 必須
5. MedicationRequest.dosageInstruction 必須(dosage instruction 詳細)

**確定済**(session 47 一次照会 2026-07-12):
- URL canonical form: `http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_<Type>_eCS`(underscore、`/fhir/eCS/` path)、jpfhir.jp v1.12.0(2026-02-16)
- 感染症別 profile / DiagnosticReport 別 profile は JP-CLINS v1.12.0 で publish されていないため、それぞれ scope から削除(§1.2 参照)

### 3.1.1 `_JP_CLINS_PROFILES` 定義(URL 一次照会確定、jpfhir.jp v1.12.0 2026-02-16)

```python
# JP-CLINS eCS profile URLs — verified against jpfhir.jp igv1 artifacts.html
# on 2026-07-12. Canonical URLs use /fhir/eCS/ path, NOT /fhir/clins/. See
# https://jpfhir.jp/fhir/clins/igv1/artifacts.html
#
# JP-CLINS v1.12.0 publishes 5 profiles covering the "6 information items"
# domain concept — 傷病名 and 感染症 share the same JP_Condition_eCS profile,
# and DiagnosticReport is NOT published (lab results are emitted only as
# Observation.LabResult in JP-CLINS).
_JP_CLINS_PROFILES: dict[str, list[str]] = {
    "Condition": [
        "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Condition_eCS",
    ],
    "AllergyIntolerance": [
        "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_AllergyIntolerance_eCS",
    ],
    "Observation": [
        # laboratory category のみ
        "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Observation_LabResult_eCS",
    ],
    "MedicationRequest": [
        "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_MedicationRequest_eCS",
    ],
    "Procedure": [
        "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Procedure_eCS",
    ],
}
# NOTE: DiagnosticReport は JP-CLINS profile 未 publish → 既存 JP Core
# JP_DiagnosticReport_Common のまま(_JP_CORE_PROFILES に既存)。
# NOTE: 感染症も別 profile 未 publish → JP_Condition_eCS で共通カバー。
```

### 3.2 PR2: 2 文書 Full JP-CLINS 準拠 Composition emit(2 sub-PR chain)

**Session 47 追加調査**(2026-07-12 jpfhir.jp v1.12.0 一次照会)により、JP-CLINS 準拠 Composition は既存 clinosim 出力とは以下の点で非互換であり、単なる profile URL 追加では不十分と判明:

- **専用 base path**:退院時サマリー = `/fhir/eDischargeSummary/`、診療情報提供書 = `/fhir/eReferral/`
- **専用 CodeSystem**(既存 codes/data/ に未登録、追加必須):
  - `http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes` — Composition.type LOINC 表現
  - `http://jpfhir.jp/fhir/clins/CodeSystem/jp-codeSystem-clins-document-section` — section coding(300/312/322/342/352/360/910/920/950 等 3 桁数値)
- **必須 section 群**:
  - 退院時サマリー = 300(構造情報)配下に 312(入院理由)/322(入院時詳細)/342(入院時診断)/352(主訴)/360(現病歴)
  - 診療情報提供書 = 920(紹介元)/910(紹介先)/300 配下に 950(紹介目的)/340(傷病名・主訴)/360(現病歴)
- **現行 clinosim** の `_fhir_composition.py` は 6 doc types 対応済だが section 構造は英語 snake_case + LOINC section codes(既存 `discharge_summary` の 6 sections `admission_summary/hospital_course/discharge_diagnoses/discharge_medications/discharge_instructions/follow_up` は JP-CLINS 必須 section と 1:1 対応せず)

**PR2 を 2 sub-PR に分割**:

- **PR2a**:退院時サマリー Full JP-CLINS 準拠(既存 discharge_summary emit の JP variant として別 builder + 新 CodeSystem + section 再構造)
- **PR2b**:診療情報提供書 新規 emit(新 doc type + narrative template + Composition builder + 紹介元/紹介先 情報 CIF 拡張 + fraction 発行)

各 sub-PR は独立に user 確認 + plan + 実装 + adversarial review + push を経る。

### 3.2 (deprecated) 2 文書 Composition builder(退院サマリー + 診療情報提供書)

**目的**:country=JP の inpatient encounter に対して 2 文書 Composition を emit。

**変更**:
- `clinosim/modules/output/_fhir_composition_jp_clins.py`(新規):
  - `build_jp_clins_discharge_summary(ctx) -> list[dict]`
  - `build_jp_clins_referral_note(ctx) -> list[dict]`
  - section builder helper 共通化(`_build_section(title, entries, text=None)`)
  - `register_bundle_builder` で `_BUNDLE_BUILDERS` に追加
- `clinosim/modules/document/` に referral note template 追加(日本語 template、既存 narrative pass の flow に merge)
- `clinosim/modules/output/reference_data/jp_clins_config.yaml`(新規):
  - `referral_note.rate`: default 0.20(急性期退院患者比率、v0.3 = ±5% 目安)
  - `referral_note.purpose_options`:「継続加療」「転院」「精査」「他科紹介」など
- `tests/unit/test_jp_clins_composition_ds.py`(新規)
- `tests/unit/test_jp_clins_composition_referral.py`(新規)
- `clinosim/simulator/seeding.py:ENRICHER_SEED_OFFSETS` に `"jp_clins_referral": 0x4A43` 追加

### 3.2.1 退院時サマリー Composition(LOINC 18842-5)

| Composition section | Populated from |
|---|---|
| 主要傷病名 | `Encounter.diagnosis` primary |
| 入院期間 | `Encounter.period.start/end` |
| 経過 / 治療内容 | 既存 `record.documents[type=DISCHARGE_SUMMARY].narrative.text` |
| 検査 | `record.observations` 異常値 subset、Observation reference |
| 処方 | `record.medications` discharge 日以降、MedicationRequest reference |
| アレルギー | `person.allergies`、AllergyIntolerance reference |
| 感染症 | `record.conditions` category=infection、Condition reference |
| 処置 | `record.procedures`、Procedure reference |

FHIR mapping:
- `resourceType` = `Composition`
- `type.coding` = `{system: "http://loinc.org", code: "18842-5"}`
- `meta.profile` = `[JP-CLINS discharge summary Composition profile URL]`(URL 一次照会必要)
- `subject` = `Patient/{id}`
- `encounter` = `Encounter/{enc-id}`
- `author` = `Practitioner/{attending-id}`
- `section[]` = 上記 8 セクション、`section.entry[]` = 既存 resource への reference
- `section.text.div` = short narrative snippet(既存 template 出力から extract)or entry-only

### 3.2.2 診療情報提供書 Composition(LOINC 57133-1)

**発行 trigger**:inpatient 退院時に fraction(YAML `referral_note.rate` default 0.20)発行 = 実 EHR 統計(急性期退院患者 15-30% で発行)に近い、population-driven 原則整合。

| section | Populated from |
|---|---|
| 紹介目的 | YAML `purpose_options` から seed 決定的に pick |
| 主要傷病名 | `Encounter.diagnosis` primary |
| 現病歴 / 入院経過 | 退院サマリー narrative 再利用 or 短縮版 template |
| 検査結果(主要) | key labs subset |
| 処方内容(現在) | 退院処方 |
| アレルギー | 全アレルギー |
| 処置(実施済) | 主要処置 |

- `type.coding` = `{system: "http://loinc.org", code: "57133-1"}`
- `meta.profile` = `[JP-CLINS referral note Composition profile URL]`(URL 一次照会必要)
- 発行判定は sub-seed `jp_clins_referral` から

**未確定 → PR2 実装前に確定**:
- JP-CLINS 上の Composition profile canonical URL(3 文書分)
- LOINC 18842-5 / 57133-1 が JP-CLINS で alias されているか(そのまま使用が有力)
- referral_note.rate の default(15% / 20% / 30%、v0.3 は 20% を仮採用、統計文献確認)

### 3.3 PR3: 健診 opt-in module + validator bridge + docs

**目的**:opt-in で健診 encounter + Composition emit + 公式 validator bridge + docs 整備。

**変更**:
- `clinosim/modules/health_checkup/`(新規 module):
  - `encounter_planner.py`:対象 subset 選定 + 検診 encounter 挿入
  - `observation_generator.py`:法定健診項目セット観測値生成
  - `composition_builder.py`:健康診断結果報告書 Composition emit
  - `reference_data/checkup_config.yaml`:対象比率、検査項目、判定基準
- `clinosim/simulator/seeding.py:ENRICHER_SEED_OFFSETS` に `"health_checkup": 0x4843` 追加
- `SimulatorConfig` opt-in 登録(既存 identity module と同 pattern)
- CLI:既存 `--enable-module` があれば拡張、なければ `--enable-health-checkup` 追加(既存 CLI 調査後決定)
- `docs/jp-clins.md`(新規):spec 参照 / 対応範囲表 / sample resource JSON / validator 使い方 / 制限事項
- `docs/audit-cycles/by-design-registry.md` に「健診 default off = 急性期病院想定」entry 追加
- `README.md`:"What clinosim generates" セクションに JP-CLINS 3 文書 6 情報準拠を追加
- `scripts/validate_jp_clins.sh`(新規):jar cache、p=100 JP 生成 → Bundle 再構成 → validator 実行
- `.github/workflows/jp-clins-validate.yml`(新規):`workflow_dispatch` + `label:jp-clins-validate` trigger、default off
- `tests/unit/test_jp_clins_health_checkup.py`(新規):opt-in enabled/disabled、encounter_type=checkup、Composition LOINC(§6 open item 2 で確定)、判定 A/B/C/D

### 3.3.1 健診項目セット(v0.3 = 労安衛法定健診 minimal)

- 身長 / 体重 / BMI
- 血圧(収縮期 / 拡張期)
- 視力 / 聴力(placeholder value)
- 尿検査(尿糖 / 尿蛋白 定性)
- 血液:AST / ALT / γ-GTP / 総コレステロール / HDL / LDL / 中性脂肪 / HbA1c / 血糖
- 胸部 X 線(所見 placeholder)
- 心電図(所見 placeholder)

判定は生成観測値 vs 基準値から機械的に A/B/C/D 導出。

## 4. Testing

### 4.1 Unit(per-PR、fast gate)

- `test_jp_clins_profile_emit.py`(PR1)
- `test_jp_clins_composition_ds.py`(PR2)
- `test_jp_clins_composition_referral.py`(PR2)
- `test_jp_clins_health_checkup.py`(PR3)
- `test_completeness_invariants.py` 拡張(PR1-PR3 各追加)

### 4.2 Integration(session 末 batch)

- `test_jp_clins_end_to_end.py`:p=1000 country=JP、6 resource type profile 存在率 100%、Composition emit rate 想定通り、reference integrity 全解決
- 健診 opt-in enabled 版:対象 subset の Composition emit + 判定分布

### 4.3 Reproducibility

- `scripts/reproduce.sh` は現状 US + JP × 2run で byte-identical 検証済み
- PR1-PR3 各 land 後、新規 profile URL / Composition が含まれた **新 baseline** で byte-identical 維持(seed 決定的)
- 健診 opt-in は default off で既存 output に影響なし、opt-in on は別 golden として追加

### 4.4 Bridge validator(optional、PR3)

- **Validator**:jpfhir-validator(jpfhir.jp 公式、Java + Sushi ベース)
- **配布**:GitHub Release asset を SHA256 hash verify で download(初回のみ、以降 cache)
- **CI trigger**:`workflow_dispatch` + label `jp-clins-validate`(default off で CI 時間浪費防止)
- **手順**:small cohort(p=100 JP)生成 → jar download → NDJSON を Bundle 再構成 → validator 実行 → output parse → PASS/FAIL 判定 → fail 時 specific rule violation を PR コメントで surface
- **Local run**:`scripts/validate_jp_clins.sh` 同手順、jar cache

## 5. Audit / DQR

### 5.1 Per-PR DQR(`feedback-pr-merge-dqr-required`)

- **構造**:profile URL 準拠率、Composition section 完全性、reference 整合
- **臨床整合**:退院サマリー主病名 = Encounter.diagnosis primary 一致、referral rate は clinical benchmark 20% ±5% 内、健診項目は労安衛法定カバー
- **JP 言語**:section title + narrative snippet 100% ja、code display JP、profile URL は英字 canonical

### 5.2 Cycle 監査回帰

- Cycle 8+ で JP-CLINS specific 観点(profile URL 準拠 / Composition 完全性 / 6 情報 category 分類)を audit query に追加
- `by-design-registry.md` に以下 entry 化:
  - 「診療情報提供書 non-referral inpatient は emit なし」
  - 「健診 default off(急性期病院想定)」
  - 「narrative は template-based(β-JP-1 で LLM 差替)」

## 6. Open decision items(PR1 実装前に確定)

以下は spec 実装前に一次照会必要:

1. **jpfhir.jp v2025.4 JP-CLINS eCS 各 profile canonical URL**(fetch + 一次リンクを `docs/jp-clins.md` に記録)
2. **各文書の LOINC code 一次確認**:
   - 退院時サマリー = **LOINC 18842-5** "Discharge summary"(v0.3 確定候補、実装前に再確認)
   - 診療情報提供書 = **LOINC 57133-1** "Referral note"(v0.3 確定候補、実装前に再確認)
   - 健康診断結果報告書 = **未確定**(LOINC 68604-8 = "Case management note" で不適合、正しい code は jpfhir.jp v2025.4 の CodeSystem 参照。候補: LOINC 34117-2 "History and physical note" 系ではなく 健診 report 固有 code、PR3 実装前に確定)
3. **感染症の判別基準**(ICD-10 A/B chapter 全域 vs SNOMED category、v0.3 = ICD-10 A/B chapter 判定)
4. **診療情報提供書 default rate**(急性期病院退院患者比率統計文献確認、v0.3 仮採用 = 0.20)
5. **健診項目セット**(労安衛法定健診 = v0.3 採用、特定健診 / 人間ドックは future scope)
6. **CLI flag naming**(既存 `--enable-module X` 拡張 vs 専用 `--enable-health-checkup`、既存 CLI 調査後確定)
7. **jpfhir-validator jar 配布方式**(公式 GitHub Release / Maven central / mirror、SHA256 verify 済み channel を採用)

## 7. Rollback / risk

- **Rollback**:PR chain は独立 = PR3 のみ revert 可、PR2 のみ revert 可(PR1 は base)
- **Byte-diff invariant 変化**:PR1 = JP profile URL 追加 = 意図的 byte 変化、reproduce.sh baseline 更新。PR2 = Composition NDJSON 追加 = 意図的、baseline 更新。PR3 opt-in on = 別 golden、default off は既存 baseline 維持
- **反復 adversarial review**:各 PR 単独で adversarial pass、chain converge 目標(feedback `iterative_adversarial_review`)

## 8. 参考

- 厚労省 電子カルテ情報共有サービス:https://www.mhlw.go.jp/stf/newpage_39122.html(spec 実装前に latest URL 再確認)
- jpfhir.jp JP-CLINS:https://jpfhir.jp/fhir/clins/
- jpfhir-validator:https://github.com/jpfhir/(公式リポジトリ URL 実装前に再確認)
- 既存 spec:
  - `docs/superpowers/specs/2026-07-03-tier1-3-alpha-min-2c-fixture-library-design.md`(canonical fixture pattern)
  - `docs/superpowers/specs/2026-07-04-jp-microbiology-jlac10-mapping-design.md`(JP-CLINS JLAC10 code 対応)
