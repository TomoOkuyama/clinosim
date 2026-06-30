# Tier 1 #3 α-min-1 — Document Density Chain Foundation

**Date:** 2026-07-01(セッション 25 計画策定、セッション 26 で実装着手予定)
**Branch:** `feature/tier1-document-density-alpha-min-1`(セッション 26 開始時に作成)
**Tier 1 #3 α-min-1** — Document & Event Density Master Plan 第 1 phase
**Master plan:** `docs/design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md`(Appendix A 含む CIF gap 分析)
**Precedent base:** PR1 ServiceRequest for Lab Orders(AD-61)+ Imaging chain(AD-62)
**ADR:** AD-63 を本 chain で確立(Document narrative + structured event density foundation)

## 0. Purpose

セッション 25 user 戦略確認 = clinosim は **病院で発生する event 記録を実 EHR レベル density で生成する EHR/EMR sample dataset generator**。本 chain は **narrative document** + **structured event records** 両 dimension の foundation を確立。

実測 gap(US p=10k DQR):
- DocumentReference 0.00 件/encounter vs 実 EHR 5-15 件 = **完全空白**
- AllergyIntolerance 0 件 = **完全空白**
- ClinicalImpression 0 件 = **完全空白**

α-min-1 で foundation 確立 → α-min-2(看護 / 外来 / ED)→ β-JP-1(JP 厚労省必須)→ β-2 〜 ε で **84-105 PR / 12-15 セッション**かけて 200 床 JP 急性期病院 realistic density 達成(master plan §2)。

α-min-1 scope = **入院 3 doc emission + Allergy + ClinicalImpression + 統一 narrative infrastructure**。

## 1. Scope decisions(6 軸評価)

評価軸:データ品質 / 臨床整合性 / FHIR-JP Core 準拠 / メンテナンス性 / モジュール責任分解 / EHR-EMR sample dataset goal(memory `feedback_recommendation_evaluation_axes`)。

### 1.1 Vertical slice 境界

α-min-1 = **入院 3 doc + 統一 infrastructure + Allergy + ClinicalImpression**。看護(α-min-2)/ 外来 / ED(α-min-2)/ JP 厚労省必須(β-JP-1)は明示的に out-of-scope。

### 1.2 Architecture: **Approach A — 新 `document/` module + `allergy/` module(always-on near-essential cascade)**

6 軸評価結果:Module + extensions slot pattern が device/hai/antibiotic/imaging precedent と完全整合、CIF→FHIR no-drop invariant 維持、modular boundaries clean。

### 1.3 設計判断 15 件(controller 推奨、user 承認済)

| # | 判断 | 採択 |
|---|---|---|
| 1 | Chain scope | 単一 chain(splitしない) |
| 2 | Module 構造 | 新 `document/` + 新 `allergy/`、既存 narrative_generator + document_generator + _fhir_documents を merge |
| 3 | NarrativeContext location | `clinosim/types/document.py` |
| 4 | DocumentTypeSpec ownership | `clinosim/modules/document/narrative/registry.py` |
| 5 | Generator provider plugin | 既存 `llm_service.providers` を backend wrap |
| 6 | Disease YAML field placement | top-level `narrative:` block |
| 7 | Disease YAML field set | 4 field 全部(hpi_template + physical_exam_findings + course_archetypes[].daily_trajectory + discharge_instructions) |
| 8 | Disease YAML fill strategy | reference data 共通 baseline + 30 disease 手動 override |
| 9 | Allergy 範囲 | drug + food + environment 3 category |
| 10 | Allergy data source | `allergens.yaml`(sampling rule)+ `snomed-ct.yaml`(code 定義) |
| 11 | ClinicalImpression frequency | daily during stay(LOS-dependent) |
| 12 | FHIR builder file | resource ごと別 file |
| 13 | Stage 2 LLM 統合 | infrastructure + Idea D template-as-seed + Idea E cache(default OFF) |
| 14 | Locale gating 場所 | `DocumentTypeSpec.countries_supported`(registry-level filter) |
| 15 | PR slicing | 線形 12-14 PR、SDD subagent execution |

### 1.4 Module structure

```
clinosim/types/                            ← CIF data(AD-18 集約)
├── allergy.py                  NEW       Allergy + AllergyReaction dataclass
├── document.py                 NEW       NarrativeContext + NarrativeOutput + DocumentType + FormatType enums
└── clinical.py                  EXISTING ClinicalImpressionRecord 追加

clinosim/modules/document/                 ← NEW always-on Module
├── __init__.py
├── engine.py                              POST_ENCOUNTER enricher entry + ClinicalImpression daily generation
├── narrative/
│   ├── __init__.py
│   ├── context.py                         NarrativeContext factory(CIF → ctx)
│   ├── registry.py                        DocumentTypeSpec registry + countries_supported gate
│   ├── template_generator.py              Stage 1 default(deterministic、3 format type 対応)
│   ├── llm_generator.py                   Stage 2 hook(llm_service provider wrap、default OFF)
│   ├── cache.py                           Stage 2 deterministic cache(Idea E)
│   └── replacement_strategy.py            Idea B/D dispatch
├── reference_data/
│   ├── physical_exam_findings.yaml       疾患 × archetype × day × system catalog
│   ├── discharge_instructions.yaml       疾患横断 baseline + 疾患別 override
│   └── document_type_specs.yaml          DocumentTypeSpec registry source
├── audit.py                               AD-60 plug-in(15+ lift_firing_proof)
└── README.md

clinosim/modules/allergy/                  ← NEW always-on Module(AD-55 Base)
├── __init__.py
├── engine.py                              patient allergy sampling(POST_POPULATION enricher)
├── reference_data/
│   └── allergens.yaml                     drug + food + environment 3 category catalog
└── README.md

clinosim/modules/output/                   ← 既存 module 拡張
├── _fhir_composition.py            NEW   Composition resource(section structure)
├── _fhir_allergy_intolerance.py    NEW   AllergyIntolerance resource
├── _fhir_clinical_impression.py    NEW   ClinicalImpression resource
└── _fhir_documents.py              REFACTOR  Stage 2 default ON + document.narrative 経由
```

### 1.5 既存資産 migration

| Source | Destination | Note |
|---|---|---|
| `clinosim/modules/output/narrative_generator.py` | `clinosim/modules/document/narrative/`(分解)| 機能保全 + interface 統一 |
| `clinosim/modules/output/document_generator.py` | `clinosim/modules/document/engine.py`(enricher 化)| 951 行のリファクタ |
| `clinosim/modules/output/_fhir_documents.py` | refactor、Stage 2 default ON | 既存 Stage 1 skip pattern を update |

## 2. Architecture

### 2.1 Pipeline data flow

```
[Pass 1: population](modules/population/)
  ↓
[Pass 1.5 NEW: allergy enricher](modules/allergy/、POST_POPULATION)
  patient.allergies populated(age/sex/disease 駆動 sampling)
  ↓
[Pass 2: per-encounter loop](modules/inpatient.py)
  ↓
[Pass 3 NEW: document enricher](modules/document/、POST_ENCOUNTER order=95、after device=70/hai=80/antibiotic=85/imaging=90)
  For each encounter:
    - daily ClinicalImpressionRecord generation(LOS-dependent)
    - NarrativeContext factory builds context per (encounter, document_type, day_index)
    - TemplateNarrativeGenerator generates ADMISSION_HP / PROGRESS_NOTE / DISCHARGE_SUMMARY
    - Optional Stage 2 LLM replacement(default OFF)
  Records populated:
    - CIFPatientRecord.documents: list[ClinicalDocument]
    - CIFPatientRecord.extensions["clinical_impressions"]: list[ClinicalImpressionRecord]
  ↓
[Pass 4: FHIR builders]
  _fhir_documents       → DocumentReference(text content embedded)
  _fhir_composition     → Composition(section-structured H&P / Discharge)
  _fhir_allergy_intolerance → AllergyIntolerance(per allergy entry)
  _fhir_clinical_impression → ClinicalImpression(per daily entry)
```

### 2.2 builder 登録順

```
Patient → Practitioner → Encounter → AllergyIntolerance → 
  ClinicalImpression → Observation → ServiceRequest → 
  DiagnosticReport → ImagingStudy → DocumentReference → Composition
```

DocumentReference + Composition は最後(narrative が他 resource refs を持つ)。

### 2.3 責任分解 + 影響行数(推定)

| Layer | 責務 | 影響行数 |
|---|---|---|
| `clinosim/types/allergy.py` (new) | `Allergy` + `AllergyReaction` dataclass | ~50 |
| `clinosim/types/document.py` (new) | `NarrativeContext` + `NarrativeOutput` + `DocumentType` enum + `FormatType` enum | ~120 |
| `clinosim/types/clinical.py` (extend) | `ClinicalImpressionRecord` 追加 | ~40 |
| `clinosim/types/output.py` (extend) | `CIFPatientRecord.extensions["clinical_impressions"]` slot 確立 | ~5 |
| `clinosim/types/patient.py` (extend) | `PatientProfile.allergies: list[Allergy]` field | ~3 |
| `clinosim/modules/allergy/` (new) | enricher + allergens.yaml + 6-layer validator + sampling | ~250 + ~200 (YAML) |
| `clinosim/modules/document/engine.py` (new) | POST_ENCOUNTER enricher + ClinicalImpression generation | ~300 |
| `clinosim/modules/document/narrative/` (new + migration) | context factory + registry + template generator + LLM hook + cache | ~600 |
| `clinosim/modules/document/reference_data/*.yaml` (new) | 3 YAML(physical_exam + discharge + document_type_specs) | ~600 |
| `clinosim/modules/document/audit.py` (new) | AD-60 plug-in | ~280 |
| `clinosim/modules/output/_fhir_composition.py` (new) | section-structured DR + Composition emit | ~250 |
| `clinosim/modules/output/_fhir_allergy_intolerance.py` (new) | AllergyIntolerance emit | ~150 |
| `clinosim/modules/output/_fhir_clinical_impression.py` (new) | ClinicalImpression emit | ~180 |
| `clinosim/modules/output/_fhir_documents.py` (refactor) | Stage 2 default ON、document.narrative 経由 | ~120 |
| `clinosim/modules/output/fhir_r4_adapter.py` (extend) | 3 new builder 登録 | ~5 |
| `clinosim/simulator/enrichers.py` (extend) | allergy + document enricher 登録 | ~10 |
| `clinosim/simulator/seeding.py` (extend) | ENRICHER_SEED_OFFSETS["allergy"] + ["document"] | ~2 |
| Disease YAML × 30 file (extend) | `narrative:` block 追加 | ~30 × 30 = ~900 行 |
| Disease YAML Pydantic schema (extend) | `narrative` field 追加 | ~50 |

## 3. Data structures

### 3.1 `clinosim/types/allergy.py`(new)

```python
@dataclass
class AllergyReaction:
    manifestation_snomed: str = ""    # SNOMED reaction code
    manifestation_display: str = ""
    severity: str = "mild"            # mild / moderate / severe

@dataclass
class Allergy:
    allergy_id: str = ""              # patient-internal id
    allergen_code: str = ""           # SNOMED for substance
    allergen_display: str = ""
    category: str = ""                # "medication" / "food" / "environment"
    criticality: str = "low"          # low / high / unable-to-assess
    verification_status: str = "confirmed"  # confirmed / unconfirmed / refuted
    onset_date: date | None = None
    reactions: list[AllergyReaction] = field(default_factory=list)
```

### 3.2 `clinosim/types/document.py`(new)

```python
class FormatType(str, Enum):
    FREE_TEXT = "free_text"             # → DocumentReference (text content)
    COMPOSITION = "composition"          # → Composition (section structure)
    QUESTIONNAIRE_RESPONSE = "questionnaire_response"  # → QuestionnaireResponse (β-JP-1 で active)

class DocumentType(str, Enum):
    # α-min-1 scope
    ADMISSION_HP = "admission_hp"        # H&P, LOINC 34117-2, COMPOSITION
    PROGRESS_NOTE = "progress_note"      # LOINC 11506-3, FREE_TEXT
    DISCHARGE_SUMMARY = "discharge_summary"  # LOINC 18842-5, COMPOSITION
    # α-min-2 以降 enum 追加(infrastructure 拡張なし)

@dataclass
class NarrativeContext:
    """全 narrative 生成の統一 input(CIF → ctx factory が組み立てる)。"""
    patient: PatientProfile
    encounter: EncounterRecord
    encounter_type: EncounterType
    disease_protocol: Any | None        # DiseaseProtocol (Pydantic)
    encounter_protocol: Any | None       # EncounterProtocol (Pydantic)
    clinical_course_archetype: str
    severity: str
    day_index: int
    los_days: int
    vitals: list[VitalSignRecord]
    lab_results: list[OrderResult]
    medications: list[MedicationAdministration]
    diagnoses: list[ClinicalDiagnosis]
    procedures: list[ProcedureRecord]
    allergies: list[Allergy]
    document_type: DocumentType
    target_lang: str                    # "en" / "ja"
    locale: str                         # "us" / "jp"

@dataclass
class NarrativeOutput:
    """generator 戻り値(emit builder の入力)。"""
    raw_text: str = ""                  # FREE_TEXT 用
    sections: dict[str, str] = field(default_factory=dict)  # COMPOSITION 用
    structured: dict = field(default_factory=dict)          # QUESTIONNAIRE_RESPONSE 用
    metadata: dict = field(default_factory=dict)            # {generator, lang, ...}
    facts_used: list[str] = field(default_factory=list)     # 使用 CIF field 追跡(audit 用)
```

### 3.3 `clinosim/types/clinical.py` 拡張

```python
@dataclass
class ClinicalImpressionRecord:
    """Daily working diagnosis update。"""
    impression_id: str = ""             # "ci-{enc}-{day}"
    encounter_id: str = ""
    date: date = field(default_factory=date.today)
    day_index: int = 0
    description: str = ""               # 短い要約
    summary: str = ""                   # 詳細
    investigation_refs: list[str] = field(default_factory=list)  # Observation refs
    finding_refs: list[str] = field(default_factory=list)        # Condition refs
    prognosis: str = ""
    practitioner_id: str = ""           # 主治医
```

### 3.4 既存 type 拡張

```python
# clinosim/types/patient.py:PatientProfile
class PatientProfile:
    # ... existing ...
    allergies: list[Allergy] = field(default_factory=list)
```

```python
# clinosim/types/output.py:CIFPatientRecord
class CIFPatientRecord:
    # ... existing ...
    # ClinicalImpressionRecord は extensions["clinical_impressions"] に格納(AD-55 Module pattern)
    # documents は既存 ClinicalDocument 構造を流用
```

## 4. Reference data + disease YAML extension

### 4.1 `physical_exam_findings.yaml`

```yaml
# 疾患 × archetype × day × system × severity → finding 句
findings:
  bacterial_pneumonia:
    uncomplicated_improvement:
      day_0:
        general:
          mild: "意識清明、軽度倦怠感"
          moderate: "意識清明、倦怠感"
          severe: "JCS I-1、呼吸促迫"
        respiratory:
          mild: "右下肺野に軽度水泡音"
          moderate: "両下肺野に水泡音"
          severe: "両肺に水泡音、補助呼吸筋使用"
        cardiovascular:
          all: "整、心雑音なし"
        abdominal: "平坦、軟、圧痛なし"
        neurological: "麻痺なし、項部硬直なし"
      day_3:
        general: "改善傾向"
        respiratory: "右下肺野水泡音残存するも減少"
        ...
    ...
```

### 4.2 `discharge_instructions.yaml`

```yaml
baseline:
  hydrate:
    en: "Drink plenty of fluids."
    ja: "十分な水分摂取を心がけてください。"
  rest:
    en: "Get adequate rest."
    ja: "十分な休息をとってください。"

disease_specific:
  bacterial_pneumonia:
    follow_up:
      en: "Follow up with PCP in 7-10 days for chest X-ray reassessment."
      ja: "退院後 1-2 週間以内に外来受診、胸部 X-P 再検をお願いします。"
    activity:
      en: "Gradual return to normal activity, avoid strenuous exercise for 2 weeks."
      ja: "徐々に通常活動再開、激しい運動は 2 週間禁止。"
    medications:
      en: "Complete prescribed antibiotics course."
      ja: "処方された抗菌薬を最後まで内服してください。"
    emergency:
      en: "Return to ER if fever recurs, breathing worsens, or chest pain develops."
      ja: "発熱再出現 / 呼吸困難悪化 / 胸痛があれば速やかに救急受診してください。"
  ...
```

### 4.3 `document_type_specs.yaml`(registry source)

```yaml
specs:
  admission_hp:
    loinc_code: "34117-2"
    display_en: "History and physical note"
    display_ja: "入院時記録"
    format_type: composition
    countries_supported: [us, jp]
    generation_frequency: admission_once
    composition_sections:
      - chief_complaint
      - hpi
      - past_medical_history
      - medications_at_home
      - allergies
      - social_history
      - family_history
      - physical_examination
      - assessment_and_plan
    stage2_strategy: template_seed
    llm_enabled_sections: [hpi, assessment_and_plan]
  progress_note:
    loinc_code: "11506-3"
    display_en: "Progress note"
    display_ja: "経過記録"
    format_type: free_text
    countries_supported: [us, jp]
    generation_frequency: daily
    stage2_strategy: template_only
  discharge_summary:
    loinc_code: "18842-5"
    display_en: "Discharge summary"
    display_ja: "退院サマリ"
    format_type: composition
    countries_supported: [us, jp]
    generation_frequency: discharge_once
    composition_sections:
      - admission_summary
      - hospital_course
      - discharge_diagnoses
      - discharge_medications
      - discharge_instructions
      - follow_up
    stage2_strategy: template_seed
    llm_enabled_sections: [hospital_course, discharge_instructions]
```

### 4.4 Disease YAML 拡張(例)

```yaml
# clinosim/modules/disease/reference_data/bacterial_pneumonia.yaml
# 既存 field に追加:

narrative:
  hpi_template:
    onset_pattern:
      mild: "{onset_days_ago} 日前より発熱、咳嗽出現"
      moderate: "{onset_days_ago} 日前より発熱、咳嗽出現、徐々に呼吸困難増悪"
      severe: "{onset_days_ago} 日前より発熱、咳嗽急速に増悪、本日受診"
    trigger_options:
      - "季節性"
      - "風邪症状先行"
      - "肺炎球菌ワクチン未接種"

  course_archetypes:                  # 既存だが daily_trajectory 追加
    - name: uncomplicated_improvement
      probability: 0.65
      daily_trajectory:
        day_0:
          subjective: "発熱、咳嗽、呼吸困難の訴え"
          objective: "発熱継続、CRP↑、WBC↑"
          assessment: "細菌性肺炎、抗菌薬開始"
          plan: "CTRX 開始、対症療法"
        day_1:
          subjective: "症状緩和、解熱傾向"
          objective: "発熱低下、SpO2 改善"
          assessment: "抗菌薬反応良好"
          plan: "経過観察、CTRX 継続"
        day_3:
          subjective: "咳嗽軽快、食欲↑"
          objective: "解熱、CRP↓、WBC normalization"
          assessment: "改善傾向"
          plan: "経口抗菌薬切替検討"
        day_5:
          subjective: "症状ほぼ消失"
          objective: "炎症マーカー normal range"
          assessment: "改善"
          plan: "退院準備、外来 follow up"
```

### 4.5 `allergens.yaml`

```yaml
# 3 category × prevalence + age/sex distribution
allergens:
  medication:
    - allergen_code: "387207008"      # SNOMED: Penicillin
      allergen_display_en: "Penicillin"
      allergen_display_ja: "ペニシリン"
      prevalence:
        adult: 0.08    # 8% population
      common_reactions:
        - manifestation_snomed: "247472004"
          manifestation_display_en: "Rash"
          manifestation_display_ja: "発疹"
          severity: mild
    - allergen_code: "372687004"      # Aspirin
      ...
  food:
    - allergen_code: "256349002"      # Eggs
      ...
  environment:
    - allergen_code: "256262001"      # Pollen
      ...
```

## 5. FHIR builder layer

### 5.1 `_fhir_composition.py`(new)

```python
COMPOSITION_ID_PREFIX = "comp-"
COMPOSITION_TYPE_SYSTEM = "http://loinc.org"

def _bb_compositions(ctx: BundleContext) -> list[dict]:
    docs = ctx.record.get("documents", []) or []
    composition_docs = [d for d in docs 
                       if _o(d, "format_type") == FormatType.COMPOSITION]
    return [_build_composition(d, ctx) for d in composition_docs]
```

Resource shape:section structure for H&P + Discharge summary、各 section に narrative text + entry refs。

### 5.2 `_fhir_allergy_intolerance.py`(new)

```python
ALLERGY_ID_PREFIX = "allergy-"

def _bb_allergy_intolerances(ctx: BundleContext) -> list[dict]:
    allergies = _o(ctx.record.get("patient", {}), "allergies", []) or []
    return [_build_allergy_intolerance(a, ctx) for a in allergies]
```

Resource shape:clinicalStatus / verificationStatus / category / criticality / code / patient / onsetDateTime / reaction[]。

### 5.3 `_fhir_clinical_impression.py`(new)

```python
CLINICAL_IMPRESSION_ID_PREFIX = "ci-"

def _bb_clinical_impressions(ctx: BundleContext) -> list[dict]:
    impressions = _o(ctx.record, "extensions", {}).get("clinical_impressions") or []
    return [_build_clinical_impression(c, ctx) for c in impressions]
```

Resource shape:status / subject / encounter / date / description / summary / investigation / finding。

### 5.4 `_fhir_documents.py` refactor

Stage 2 default ON、template_generator 経由で narrative 生成、`format_type=FREE_TEXT` の DocumentReference emit。COMPOSITION format は `_fhir_composition.py` に dispatch。

## 6. Snapshot semantics(AD-32)

- 入院中(snapshot 前):ClinicalImpression daily emit までを含む、DISCHARGE_SUMMARY skip
- 退院済(snapshot 前):H&P + 全 PROGRESS_NOTE + DISCHARGE_SUMMARY emit
- ED / 外来:該当なし(α-min-1 scope 外)

## 7. Edge cases

| ケース | 動作 |
|---|---|
| Disease YAML に `narrative.*` field 不在 | Pydantic schema default = empty、template generator が generic fallback narrative |
| Patient.allergies 空 | AllergyIntolerance 0 件 emit(no-op safe)|
| LOS = 1(同日 admission + discharge) | H&P + Discharge のみ emit、PROGRESS_NOTE skip |
| Allergen SNOMED が snomed-ct.yaml に不在 | YAML loader fail-loud(silent-no-op defense Layer 6) |
| Course archetype に `day_N` daily_trajectory 不在 | Template fallback、deterministic 句生成 |
| CLINOSIM_NARRATIVE_LLM=on but provider 不在 | template_generator fallback + 警告 log |

## 8. Silent-no-op 7-layer 適用

| Layer | 適用 |
|---|---|
| 1. Canonical URI | `COMPOSITION_TYPE_SYSTEM` / `ALLERGY_CATEGORY_*` 定数化 |
| 2. Shared id-prefix | `COMPOSITION_ID_PREFIX` / `ALLERGY_ID_PREFIX` / `CLINICAL_IMPRESSION_ID_PREFIX` writer↔reader |
| 3. YAML loader empty + per-bucket | 3 reference YAML(physical_exam + discharge + document_type_specs)+ allergens.yaml |
| 4. Reverse-coverage | `DocumentType` enum ↔ `document_type_specs.yaml` keys + `SUPPORTED_ALLERGEN_CATEGORIES` ↔ `allergens.yaml` keys |
| 5. Pre-register ordering | `_validate_*` を `register_audit_module` BEFORE に hoist |
| 6. Symmetric forward-coverage | 30 disease YAML × narrative.* fields(全 disease 必須) |
| 7. Cross-module URI(LOINC `http://loinc.org`) | 既存 codes/data/loinc.yaml への entry(各 doc LOINC) |

## 9. Testing strategy

### 9.1 Unit tests

| ファイル | 内容 |
|---|---|
| `tests/unit/test_types_allergy.py` | Allergy / AllergyReaction dataclass |
| `tests/unit/test_types_document.py` | NarrativeContext / NarrativeOutput / DocumentType / FormatType |
| `tests/unit/test_types_clinical_impression.py` | ClinicalImpressionRecord |
| `tests/unit/modules/allergy/test_engine.py` | sampling rule(age/sex/disease 駆動) |
| `tests/unit/modules/allergy/test_allergens_yaml.py` | YAML validator |
| `tests/unit/modules/document/test_engine.py` | enricher + ClinicalImpression daily emit |
| `tests/unit/modules/document/narrative/test_registry.py` | DocumentTypeSpec + countries_supported gate |
| `tests/unit/modules/document/narrative/test_template_generator.py` | 3 format type 対応 + course archetype daily_trajectory |
| `tests/unit/modules/document/narrative/test_llm_generator.py` | hook(default OFF + opt-in path) |
| `tests/unit/modules/document/narrative/test_cache.py` | Idea E cache + replay |
| `tests/unit/output/test_fhir_composition.py` | Composition resource shape + section dispatch |
| `tests/unit/output/test_fhir_allergy_intolerance.py` | AllergyIntolerance shape |
| `tests/unit/output/test_fhir_clinical_impression.py` | ClinicalImpression shape |
| `tests/unit/output/test_fhir_documents_refactor.py` | refactored Stage 2 default ON |
| `tests/unit/audit/test_document_audit.py` | lift_firing_proof 15+ |

★ dict + dataclass 両 path test 必須(PR-90 教訓)。

### 9.2 Integration tests

| ファイル | 内容 |
|---|---|
| `tests/integration/test_document_chain.py` | end-to-end:US + JP cohort で 5 resource type 全 emission + ref integrity |
| `tests/integration/test_document_basedon_coverage.py` | composition / DR / clinical_impression refs resolve |
| `tests/integration/test_document_determinism.py` | seed 固定 2 回 sha256 一致(AD-16)|
| `tests/integration/test_document_snapshot.py` | mid-encounter snapshot で DISCHARGE skip |
| `tests/integration/test_document_subprocess_fullpipeline.py` | production json.load → builder dict path verify |
| `tests/integration/test_document_jp_localization.py` | JP cohort 全 ja display + section title |

### 9.3 AD-60 audit module(★ primary gate)

```python
ModuleAuditSpec(
    name="document_chain",
    canonical_constants=[...],
    structural_checks=[
        "every Composition.id starts with COMPOSITION_ID_PREFIX",
        "every AllergyIntolerance.id starts with ALLERGY_ID_PREFIX",
        "every ClinicalImpression.id starts with CLINICAL_IMPRESSION_ID_PREFIX",
        "every Composition.subject resolves",
        "every ClinicalImpression.encounter resolves",
        "every AllergyIntolerance.patient resolves",
    ],
    clinical_acceptance={
        "h_and_p_per_inpatient_encounter": "== 1",
        "progress_note_per_day_per_inpatient": ">= 0.8",
        "discharge_summary_per_completed_inpatient": "== 1",
        "clinical_impression_per_day_per_inpatient": ">= 0.8",
        "allergy_per_patient_distribution": "matches allergens.yaml prevalence ±0.05",
    },
    jp_language_checks=[
        "Composition.section[].title in ja for JP cohort",
        "DocumentReference.content.attachment.title in ja for JP cohort",
        "AllergyIntolerance.code.coding[].display in ja for JP cohort",
    ],
    lift_firing_proof=lambda: [
        # 15+ equality checks:canonical constants + emission counts + ref integrity + no-drop
        ("COMPOSITION_TYPE_SYSTEM == 'http://loinc.org'", ...),
        ("ALLERGY_ID_PREFIX == 'allergy-'", ...),
        ...
    ],
)
```

### 9.4 DQR(production cohort)

```
clinosim run-beta --country US --population 10000 --seed 42 --output scratchpad/doc_alpha1_us10k/ --format fhir-r4
clinosim run-beta --country JP --population 5000  --seed 42 --output scratchpad/doc_alpha1_jp5k/  --format fhir-r4
clinosim audit run scratchpad/doc_alpha1_us10k/ --module document_chain
clinosim audit run scratchpad/doc_alpha1_jp5k/  --module document_chain
```

DQR doc:`docs/reviews/2026-XX-XX-tier1-3-document-density-alpha-min-1-dqr.md`、4 軸 PASS。

### 9.5 Pre-merge gate

```
pytest tests/unit tests/integration -m "unit or integration"
```

セッション 22 教訓 full sweep。

## 10. Risks + Mitigation

| Risk | Mitigation |
|---|---|
| 30 disease YAML × narrative.* fill が時間消費 | reference data 共通 baseline で boilerplate 削減、per-disease override は最小 |
| narrative_generator + document_generator + _fhir_documents の migration で regression | 既存 e2e golden で byte-diff verify、不変保証 |
| LLM hook の future 統合が refactor 大 | Idea D template-as-seed + Protocol-based interface で最小 refactor 保証 |
| ClinicalImpression daily emit で resource 数爆発 | 200 床 US 10k で ~480k 件、acceptable per imaging chain precedent(SR 18k 経験あり) |
| Template が disease YAML field 不在で fallback 多発 | 6-layer validator が absent を fail-loud 検出、disease YAML 拡張 PR(Task 4)で全 30 disease populate |
| JP language axis verification 失敗 | DQR pre-merge gate + dictionary completeness check |
| Test fixture が dataclass-only で production dict path bug | PR-90 教訓 = dict + dataclass 両 path test 必須 |
| LOINC code が codes/data/loinc.yaml に不在 | 既存 entry 確認(34117-2 / 11506-3 / 18842-5 verified existing)、不足は事前追加 |
| 既存 e2e golden 変動 | 新 resource 追加 = 意図的 byte-diff、golden 再生成 |

## 11. Out-of-scope(★ TODO.md formal entry)

| 項目 | 後続予定 |
|---|---|
| 看護 narrative(Admission nursing assessment / Nursing shift / Discharge nursing) | α-min-2 |
| 外来 SOAP note | α-min-2 |
| ED note + ED triage note | α-min-2 |
| CareTeam(多職種) | α-min-2 |
| QuestionnaireResponse active emission | β-JP-1 |
| 入院診療計画書 / 看護必要度 D 表 / 栄養管理計画書 / リハ計画書(JP 厚労省必須) | β-JP-1 |
| 多職種 staff allocation(主治医 / 看護師 / 薬剤師 / 栄養士 / リハ / MSW) | β-JP-1 |
| 手術記録 / 麻酔記録 / IC document / 薬剤管理指導 / リハ実施記録 / 多職種カンファ / 家族説明 | β-2 |
| MedicationDispense(pharmacy 払出) | β-2 |
| Procedure density 強化(bedside + surgical catalog) | β-2 |
| MSW / Discharge planning / 紹介状 / 主治医意見書 / 初診時記録 | γ |
| Appointment + AppointmentResponse + Communication + Flag(慢性疾患) | γ |
| Pathology / Cytology / CarePlan / Goal / EpisodeOfCare / AdverseEvent / DetectedIssue | δ |
| 死亡診断書(JP) + Pre/Post-op evaluation / OR nursing | δ |
| ADT location transfer + Vital frequency 拡張 + Specimen 独立 + per-dose MAR refactor | ε |
| LLM provider integration(Bedrock / Ollama / Anthropic 実装) | infrastructure 用意済、別 chain で integration |

## 12. Adversarial chain plan

9 例目の安定 chain pattern(PR1 LAB / Imaging chain precedent):

| 段階 | 内容 | converged 判定 |
|---|---|---|
| docalpha1-original | vertical slice 完成 | audit + full test + DQR 4 軸 PASS |
| adversarial-1 | 5-lens parallel fan-out | findings 列挙、fix PR |
| docalpha1-adv-1 | adv-1 findings fix | audit + full test PASS |
| adversarial-2 | adv-1 fix に同 5-lens fan-out | 次段 findings 列挙 |
| docalpha1-adv-2 | adv-2 findings fix | audit + full test PASS |
| **converged** | Critical=0 + Important=0 + 残 cosmetic only | chain CLOSED |

## 13. PR sequencing

```
docalpha1-PR1: Tier 1 #3 α-min-1 single chain(本 spec)
  scope = Allergy + ClinicalImpression + Document infrastructure + 3 inpatient doc
  ├─ Internal task slice(12-14 tasks、SDD execution):
  │   ├─ Task 1: types/allergy.py + types/document.py + ClinicalImpressionRecord
  │   ├─ Task 2: clinosim/modules/allergy/ + allergens.yaml + 6-layer validator
  │   ├─ Task 3: clinosim/modules/document/ skeleton + NarrativeContext + DocumentTypeSpec
  │   ├─ Task 4: Disease YAML 拡張(narrative.* × 30 disease + Pydantic schema)
  │   ├─ Task 5: physical_exam_findings.yaml + discharge_instructions.yaml + validators
  │   ├─ Task 6: TemplateNarrativeGenerator(3 format type)
  │   ├─ Task 7: LLMNarrativeGenerator hook + cache + Idea D template-as-seed
  │   ├─ Task 8: document module engine.py(enricher + ClinicalImpression generation)
  │   ├─ Task 9: _fhir_composition.py + _fhir_allergy_intolerance.py + _fhir_clinical_impression.py
  │   ├─ Task 10: _fhir_documents.py refactor + builder registration
  │   ├─ Task 11: audit.py + lift_firing_proof(15+)
  │   ├─ Task 12: integration tests + e2e golden + subprocess + JP localization + determinism
  │   ├─ Task 13: DQR + 9 doc sync(README + MODULES + DESIGN AD-63 + CLAUDE + others)
  │   └─ Task 14: final whole-branch review + PR open
  │
  ├─ Adversarial-1: 5-lens parallel fan-out
  ├─ docalpha1-adv-1: fix
  └─ docalpha1-adv-2: fix(or converged)

docalpha1-2 〜 ε:後続 chain(master plan §2 参照)
```

## 14. Docs sync(PR 内全更新)

- `README.md` + `README.ja.md`:document density chain 言及 + master plan link
- `MODULES.md`:`document` + `allergy` module row 追加 + Dependency Tree 更新
- `DESIGN.md`:**AD-63**「Document narrative + structured event density foundation」追加
- `docs/CONTRIBUTING-modules.md`:document module を always-on Module 例として追加
- `clinosim/modules/document/README.md`:新規(template + 詳細)
- `clinosim/modules/allergy/README.md`:新規
- `TODO.md`:OOS 16+ 項目 formal entry
- `CLAUDE.md`:統一 narrative interface DRY rule + Allergy module + Document module DRY rules
- `docs/design-guides/fhir-data-generation-logic.md`:Composition + AllergyIntolerance + ClinicalImpression precedent 追加

## 15. References

- Master plan:`docs/design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md`(本 chain の上位戦略 + Appendix A CIF gap)
- Memory:
  - `project_event_density_strategy.md`
  - `project_ehr_event_emphasis.md`
  - `project_document_density_master_plan.md`
  - `feedback_recommendation_evaluation_axes.md`
  - `feedback_cif_to_fhir_no_drop.md`
  - `feedback_unify_data_logic.md`
- PR precedent:
  - PR #126 ServiceRequest LAB(AD-61)
  - PR #127 Imaging chain α-min(AD-62)
- 既存 module:`narrative_generator.py` / `document_generator.py` / `_fhir_documents.py` / `llm_service/`
- FHIR R4:Composition / DocumentReference / AllergyIntolerance / ClinicalImpression
- US Core / JP Core profile:対応 conformance
- LOINC 認証:34117-2 / 11506-3 / 18842-5(NLM clinicaltables verified)
- SNOMED 認証:tx.fhir.org `$lookup`(allergen codes + reaction manifestation codes)
