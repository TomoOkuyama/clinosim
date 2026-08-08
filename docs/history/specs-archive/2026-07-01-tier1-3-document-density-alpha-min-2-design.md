# Tier 1 #3 α-min-2 — Nursing + Outpatient + ED + CareTeam + Triage

**Date:** 2026-07-01
**Branch:** `feature/tier1-document-density-alpha-min-2`
**Tier 1 #3 α-min-2** — Document & Event Density Master Plan 第 2 phase
**Master plan:** `docs/design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md`
**Precedent base:** α-min-1 chain(PR #128 + #129、AD-63)
**ADR:** AD-64 を本 chain で確立(Nursing + Outpatient + ED + CareTeam density foundation)

## 0. Purpose

セッション 26 でα-min-1(入院 3 doc + AllergyIntolerance + ClinicalImpression + Composition + statistical narrative + 統一 infrastructure)完全 CLOSED。α-min-2 は master plan §2 の第 2 phase:**看護 domain narrative + 外来 SOAP + ED note + 多職種初歩(CareTeam)+ triage 基礎**。

**実測 gap(post-α-min-1 US p=10k baseline、`scratchpad/doc_alpha1_us10k/`):**
- CareTeam: 0 = **完全空白**
- Nursing narrative: **完全空白**(現状 nursing 関連 module も document type もなし)
- OUTPATIENT_SOAP + ED_NOTE + ED_TRIAGE_NOTE: 0 = **完全空白**(α-min-1 は inpatient のみ対応)
- Practitioner: 85 のみ = 多職種未対応(pharmacist / nutritionist / rehab / MSW 等の practitioner 未 emit)

α-min-2 で 200 床 JP 急性期病院 realistic density の **次段階** = Nursing daily doc + 外来 encounter narrative + ED encounter narrative + primary team allocation。α-min-1 で確立した Document infrastructure(TemplateNarrativeGenerator + DocumentTypeSpec + document_enricher + FHIR builders)を **encounter_type gating で拡張**、6 新 DocumentType + CareTeam 新 resource を追加。

α-min-2 scope = **入院看護 3 doc + 外来 SOAP + ED note × 2 + CareTeam + Triage infrastructure**。

## 1. Scope decisions(brainstorming 承認済)

評価軸:データ品質 / 臨床整合性 / FHIR-JP Core 準拠 / メンテナンス性 / モジュール責任分解 / EHR-EMR sample dataset goal(memory `feedback_recommendation_evaluation_axes`)。

### 1.1 Scope 境界

α-min-2 = **看護 3 doc + 外来 SOAP + ED note × 2 + CareTeam(2 名 scope)+ Triage module + 46 encounter YAML narrative 拡張**。多職種 6 名 CareTeam(β-JP-1)/ JP 厚労省必須 doc(β-JP-1)/ 手術記録(β-2)/ MedicationDispense(β-2)は明示的に out-of-scope。

### 1.2 Architecture(brainstorming で確定)

| 決定 | 採択 | 理由 |
|---|---|---|
| Nursing domain module | **新 `clinosim/modules/nursing/`**(AD-55 always-on Module) | staff module 集約回避、AD-55 pattern 踏襲、責任分解 clean |
| Triage domain module | **新 `clinosim/modules/triage/`**(AD-55 always-on Module) | 独立 domain(JTAS/ESI + arrival_mode + acuity_score)、責任分解 clean |
| document_enricher extension | **既存 `document_enricher` に encounter_type gating 拡張** | 統一 enricher entry point、`DocumentTypeSpec.encounter_types_supported` field で dispatch |
| CareTeam scope | **主治医 + primary nurse の 2 名のみ** | scope discipline、β-JP-1 で多職種拡張 |
| Encounter YAML narrative | **46 YAML 全て narrative 拡張(5 priority detailed + 41 baseline)** | α-min-1 fill strategy 踏襲、per-condition specificity |
| NURSING_SHIFT_NOTE frequency | **daily 1**(α-min-1 progress_note pattern 踏襲) | scope discipline、shift 3 拡張は α-min-2b 検討 |
| Triage level system | **country-gated**(JP→JTAS、US→ESI) | FHIR-JP Core / US Core 両対応 |

### 1.3 Module structure

```
clinosim/types/
├── triage.py                       NEW  TriageData(level, level_system, arrival_mode, triage_time, acuity_score) dataclass
├── document.py                     EXTEND  DocumentType enum + 6 entries + FormatType 不変
├── encounter.py                    EXTEND  EncounterRecord.primary_nurse_id + triage_data slot
└── clinical.py                     EXTEND(if any nursing-specific record)

clinosim/modules/triage/            NEW always-on Module(AD-55)
├── __init__.py
├── engine.py                       Loader + validator + triage_enricher(POST_ENCOUNTER order=93, ED only)
├── reference_data/
│   └── triage_protocols.yaml       JTAS 1-5 + ESI 1-5 + arrival_mode + acuity_score distribution
└── README.md

clinosim/modules/nursing/           NEW always-on Module(AD-55)
├── __init__.py
├── engine.py                       primary_nurse assignment(inpatient/icu/rehab、persistent)+ nursing_enricher(POST_ENCOUNTER order=94)
├── reference_data/
│   └── nursing_assessment.yaml     Nursing assessment scaffolding(vital sign summary + iADL / ADL + risk assessments)
└── README.md

clinosim/modules/document/          EXTEND(既存)
├── narrative/
│   ├── registry.py                 EXTEND  DocumentTypeSpec.encounter_types_supported + specs_for_encounter_type
│   └── template_generator.py       EXTEND  6 new DocumentType sections(nursing/outpatient/ED)
├── reference_data/
│   └── document_type_specs.yaml    EXTEND  +6 spec entries(admission_nursing_assessment / nursing_shift_note / nursing_discharge_summary / outpatient_soap / ed_note / ed_triage_note)
└── engine.py                       EXTEND  encounter_type gating + generation_frequency="encounter_once" dispatch

clinosim/modules/output/            EXTEND
├── _fhir_care_team.py              NEW  CareTeam builder(participant[]=attending_physician + primary_nurse per encounter)
├── _fhir_composition.py            EXTEND  6 new DocumentType section handling
├── _fhir_documents.py              EXTEND  6 new DocumentType free_text handling
└── fhir_r4_adapter.py              EXTEND  _bb_care_teams 登録

clinosim/modules/encounter/         EXTEND
└── protocol.py                     EXTEND  EncounterProtocol.narrative field(Pydantic)

clinosim/modules/encounter/reference_data/*.yaml(× 46)
                                    EXTEND  narrative:{outpatient_soap_template / ed_note_template / ed_triage_template / physical_exam_findings / discharge_instructions} block
```

### 1.4 既存資産との関係

| Source | 影響 | Note |
|---|---|---|
| `document_enricher`(α-min-1) | encounter_type gating 拡張 | 6 new DocumentType 対応、outpatient/emergency dispatch 追加 |
| `TemplateNarrativeGenerator`(α-min-1) | 6 new DocumentType の section handling 拡張 | outpatient SOAP / ED triage template rendering 追加 |
| `AD-60 audit document_chain`(α-min-1) | 拡張(no-drop invariants + CareTeam gate) | 17 checks → 23+ checks 想定 |
| `staff module`(既存) | 不変 | nurse roster を nursing module に提供 |
| `EncounterRecord.attending_physician_id`(既存) | 不変 | CareTeam.participant[0] source |
| `EncounterType.OUTPATIENT / EMERGENCY`(既存) | 不変 | document_enricher gating 対象 |

## 2. Architecture

### 2.1 Pipeline data flow

```
[Pass 1: population + activator]
  ↓
[Pass 1.5: allergy_enricher](POST_POPULATION order=10、既存)
  ↓
[Pass 2: per-encounter simulation](inpatient/outpatient/emergency)
  ↓
[Pass 3: POST_ENCOUNTER enrichers](既存 device=70/hai=80/antibiotic=85/imaging=90)
  ↓ +NEW
[Pass 3a NEW: triage_enricher](order=93、ED encounter のみ)
  patient.encounters[i].triage_data populated
  ↓ +NEW
[Pass 3b NEW: nursing_enricher](order=94、inpatient/icu/rehab のみ)
  patient.encounters[i].primary_nurse_id assigned
  ↓
[Pass 3c: document_enricher](order=95、既存拡張)
  For each encounter:
    - encounter_type に基づいて applicable DocumentTypeSpec を specs_for_encounter_type() で取得
    - 6 new document types generation:
      - inpatient: +ADMISSION_NURSING_ASSESSMENT(admission_once) + NURSING_SHIFT_NOTE(daily) + NURSING_DISCHARGE_SUMMARY(discharge_once)
      - outpatient: +OUTPATIENT_SOAP(encounter_once)
      - emergency: +ED_NOTE(encounter_once) + ED_TRIAGE_NOTE(encounter_once)
  ↓
[Pass 4: FHIR builders]
  +_bb_care_teams → CareTeam(1/encounter with 2 participants)
  既存: _bb_document_references + _bb_compositions + _bb_allergy_intolerances + _bb_clinical_impressions + ...
```

### 2.2 FHIR builder 登録順(spec §2.2 拡張)

```
Patient → Practitioner → PractitionerRole → Encounter → CareTeam(NEW) →
  AllergyIntolerance → ClinicalImpression → Observation → ServiceRequest →
  DiagnosticReport → ImagingStudy → DocumentReference → Composition
```

CareTeam は Encounter の後、他 clinical resource より前。

### 2.3 責任分解 + 影響行数(推定)

| Layer | 責務 | 影響行数 |
|---|---|---|
| `clinosim/types/triage.py` (new) | TriageData dataclass | ~50 |
| `clinosim/types/encounter.py` (extend) | primary_nurse_id + triage_data field | ~5 |
| `clinosim/types/document.py` (extend) | 6 DocumentType enum entries | ~10 |
| `clinosim/modules/triage/` (new) | enricher + triage_protocols.yaml + validator | ~300 + ~200 YAML |
| `clinosim/modules/nursing/` (new) | primary_nurse assignment + nursing_assessment.yaml + enricher | ~350 + ~300 YAML |
| `clinosim/modules/document/narrative/registry.py` (extend) | DocumentTypeSpec.encounter_types_supported | ~30 |
| `clinosim/modules/document/narrative/template_generator.py` (extend) | 6 new DocumentType rendering | ~400 |
| `clinosim/modules/document/engine.py` (extend) | encounter_type gating + generation_frequency="encounter_once" | ~200 |
| `clinosim/modules/document/reference_data/document_type_specs.yaml` (extend) | +6 spec entries | ~150 |
| `clinosim/modules/output/_fhir_care_team.py` (new) | CareTeam builder | ~180 |
| `clinosim/modules/output/_fhir_composition.py` (extend) | 6 new DocumentType section mapping | ~100 |
| `clinosim/modules/output/_fhir_documents.py` (extend) | 6 new DocumentType free_text handling | ~50 |
| `clinosim/modules/encounter/protocol.py` (extend) | EncounterProtocol.narrative Pydantic | ~80 |
| 46 encounter YAML (extend) | narrative block(5 detailed + 41 baseline) | ~800 total |
| `clinosim/simulator/enrichers.py` (extend) | triage + nursing 登録 | ~10 |
| `clinosim/simulator/seeding.py` (extend) | ENRICHER_SEED_OFFSETS["triage"] + ["nursing"] | ~2 |
| Unit + integration tests (new + extend) | 60+ new tests | ~2500 |
| DQR + docs sync | 8-9 docs update | ~600 |

## 3. Data structures

### 3.1 `clinosim/types/triage.py`(new)

```python
@dataclass
class TriageData:
    """ED triage data(Tier 1 #3 α-min-2)."""
    level: str = ""                  # e.g., "3" for JTAS-3 or ESI-3
    level_system: str = ""           # "JTAS" | "ESI"
    arrival_mode: str = ""           # "walk-in" | "ambulance" | "police" | "helicopter"
    triage_time: datetime | None = None
    acuity_score: float | None = None  # 数値スコア(0-100 表現)、level_system の詳細スコア
    chief_complaint_summary: str = ""  # triage 時 chief complaint 短文
```

### 3.2 `clinosim/types/encounter.py` 拡張

```python
class EncounterRecord:
    # ... existing ...
    # Tier 1 #3 α-min-2 additions
    primary_nurse_id: str = ""           # nursing_enricher が set(inpatient のみ、default "")
    triage_data: TriageData | None = None  # triage_enricher が set(ED のみ)
```

### 3.3 `clinosim/types/document.py:DocumentType` 拡張

```python
class DocumentType(str, Enum):
    # α-min-1 scope(既存)
    ADMISSION_HP = "admission_hp"
    PROGRESS_NOTE = "progress_note"
    DISCHARGE_SUMMARY = "discharge_summary"
    # α-min-2 scope(new)
    ADMISSION_NURSING_ASSESSMENT = "admission_nursing_assessment"  # LOINC 34119-8(候補、Task 8 で認証)
    NURSING_SHIFT_NOTE = "nursing_shift_note"                       # LOINC 34120-6(候補、Task 8 で認証)
    NURSING_DISCHARGE_SUMMARY = "nursing_discharge_summary"         # LOINC 34745-0(候補、Task 8 で認証)
    OUTPATIENT_SOAP = "outpatient_soap"                             # LOINC 11488-4(候補、Task 8 で認証)
    ED_NOTE = "ed_note"                                             # LOINC 51841-6(Emergency department note、Task 8 で認証、NOT 34117-2 = H&P)
    ED_TRIAGE_NOTE = "ed_triage_note"                               # LOINC 54094-8(候補、Task 8 で認証)
```

### 3.4 `DocumentTypeSpec` 拡張

```python
@dataclass(frozen=True)
class DocumentTypeSpec:
    # ... existing fields ...
    encounter_types_supported: tuple[str, ...] = ()  # NEW α-min-2
                        # e.g. ("inpatient", "icu") or ("emergency",)
```

`generation_frequency` 値に `"encounter_once"` を追加。

## 4. Reference data + Encounter YAML 拡張

### 4.1 `triage_protocols.yaml`(spec §4.1、new)

```yaml
# JTAS 1-5(JP)+ ESI 1-5(US)
triage_systems:
  JTAS:
    levels:
      "1": {name_ja: "蘇生", eng: "Resuscitation", target_wait_min: 0}
      "2": {name_ja: "緊急", eng: "Emergent", target_wait_min: 15}
      "3": {name_ja: "準緊急", eng: "Urgent", target_wait_min: 30}
      "4": {name_ja: "低緊急", eng: "Less Urgent", target_wait_min: 60}
      "5": {name_ja: "非緊急", eng: "Non-Urgent", target_wait_min: 120}
  ESI:
    levels:
      "1": {name: "Level 1 — Resuscitation", target_wait_min: 0}
      "2": {name: "Level 2 — Emergent", target_wait_min: 10}
      "3": {name: "Level 3 — Urgent", target_wait_min: 30}
      "4": {name: "Level 4 — Semi-Urgent", target_wait_min: 60}
      "5": {name: "Level 5 — Non-Urgent", target_wait_min: 120}

arrival_modes:
  - walk-in
  - ambulance
  - police
  - helicopter
  - private_vehicle

# severity → triage_level 分布(country-independent)
severity_to_triage_distribution:
  mild:
    "3": 0.15
    "4": 0.55
    "5": 0.30
  moderate:
    "2": 0.15
    "3": 0.60
    "4": 0.25
  severe:
    "1": 0.20
    "2": 0.55
    "3": 0.25

# arrival_mode 分布(base rate、severity で修正)
arrival_mode_base_distribution:
  walk-in: 0.55
  ambulance: 0.35
  private_vehicle: 0.08
  police: 0.01
  helicopter: 0.01
```

### 4.2 `nursing_assessment.yaml`(new)

```yaml
# Nursing assessment scaffolding
adl_categories:
  eating: [independent, partial_assist, full_assist]
  bathing: [independent, partial_assist, full_assist]
  dressing: [independent, partial_assist, full_assist]
  toileting: [independent, partial_assist, full_assist]
  mobility: [independent, walker, wheelchair, bed_bound]

risk_assessments:
  fall_risk: [low, moderate, high]
  pressure_ulcer_risk: [low, moderate, high]
  aspiration_risk: [low, moderate, high]

# 疾患別 nursing focus(5 priority + baseline)
disease_specific_nursing_focus:
  bacterial_pneumonia:
    focus: "呼吸状態観察 / 排痰援助 / 酸素療法管理 / 発熱・脱水管理"
    interventions_ja: ["体位変換2h", "SpO2モニタリング", "痰吸引", "水分in-out管理"]
  # ... baseline for others ...

baseline:
  focus: "バイタル・意識・水分・排泄管理 / 感染予防 / 転倒予防"
  interventions_ja: ["バイタル4回/日", "食事摂取量確認", "ADL支援", "服薬確認"]
```

### 4.3 46 Encounter YAML 拡張

```yaml
# clinosim/modules/encounter/reference_data/abdominal_pain_nonspecific.yaml
# 既存 field に追加:

narrative:
  outpatient_soap_template:
    subjective_ja: "{onset_days}日前より腹痛、{location_description}"
    objective_ja: "腹部：{abdomen_finding}、圧痛：{tenderness_finding}"
    assessment_ja: "{primary_dx_display}疑い"
    plan_ja: "{workup_summary}、{treatment_summary}、{follow_up_ja}"
  ed_note_template:
    chief_complaint_ja: "腹痛"
    hpi_ja: "{onset_days}日前より{quality_ja}な腹痛、{radiation_ja}"
    physical_exam_ja:
      abdominal: "{abdomen_finding}"
      general: "{general_finding}"
    ed_workup_summary_ja: "{lab_summary}、{imaging_summary}"
    disposition_ja: "{disposition_display}"
  ed_triage_template:
    common_triage_levels: ["3", "4"]
    walk_in_probability_by_severity:
      mild: 0.75
      moderate: 0.40
      severe: 0.10
```

## 5. FHIR builder layer

### 5.1 `_fhir_care_team.py`(new)

```python
CARE_TEAM_ID_PREFIX = "careteam-"

def _bb_care_teams(ctx) -> list[dict]:
    encounters = _o(ctx.record, "encounters", []) or []
    return [_build_care_team(enc, ctx) for enc in encounters if _has_valid_team(enc)]

def _build_care_team(encounter, ctx) -> dict:
    """CareTeam per encounter with participant[]=[attending, primary_nurse]."""
    # participant[0] = attending_physician(全 encounter type)
    # participant[1] = primary_nurse(inpatient のみ、outpatient/ED は attending のみ)
    ...
```

Resource shape:status + subject + encounter + participant[] + period + name。

### 5.2 `_fhir_composition.py` 拡張

6 new DocumentType の section mapping。ADMISSION_NURSING_ASSESSMENT:
- nursing_history + adl_assessment + risk_assessments + nursing_diagnosis + care_plan

NURSING_DISCHARGE_SUMMARY:
- admission_status + nursing_interventions_provided + patient_education + discharge_readiness

OUTPATIENT_SOAP:
- subjective + objective + assessment + plan

ED_NOTE:
- chief_complaint + hpi + triage_details + physical_exam + ed_workup + assessment + disposition

### 5.3 `_fhir_documents.py` 拡張

NURSING_SHIFT_NOTE + ED_TRIAGE_NOTE の free_text handling(既存 pattern 適用)。

## 6. Snapshot semantics(AD-32)

- 入院中(snapshot 前):Nursing SHIFT_NOTE 日次 emit までを含む、NURSING_DISCHARGE_SUMMARY skip、ADMISSION_NURSING_ASSESSMENT emit
- 退院済(snapshot 前):Nursing 3 doc 全 emit
- 外来 / ED:snapshot 前完了 encounter は SOAP + ED_NOTE + ED_TRIAGE_NOTE emit、in-progress ED は ED_TRIAGE のみ(ED_NOTE の disposition 未確定)

## 7. Edge cases

| ケース | 動作 |
|---|---|
| Encounter YAML に narrative.* 不在 | 46 encounter YAML 全部に narrative block を追加(forward-coverage test) |
| ED encounter で triage_enricher が未 run | triage_data=None、ED_TRIAGE_NOTE emit skip、warning log |
| Inpatient nursing_enricher で nurse roster 不在 | primary_nurse_id=""、CareTeam participant[1] omit + audit で fail(nursing_enricher の 6-layer validator に nurse roster check) |
| Country=US で triage system=JTAS(または vice versa) | triage_protocols.yaml locale gating で US→ESI 自動選択 |
| LOS=1 nursing(既存 α-min-1 と同) | ADMISSION_NURSING_ASSESSMENT + NURSING_DISCHARGE_SUMMARY のみ、NURSING_SHIFT_NOTE skip |
| Encounter type=OUTPATIENT で nursing_enricher run(誤動作) | nursing_enricher が encounter_types_gate で skip、no-op |

## 8. Silent-no-op 7-layer 適用

| Layer | 適用 |
|---|---|
| 1. Canonical URI | `CARE_TEAM_CATEGORY_SNOMED` / `JTAS_SYSTEM_URI` / `ESI_SYSTEM_URI` |
| 2. Shared id-prefix | `CARE_TEAM_ID_PREFIX` writer↔reader |
| 3. YAML loader empty + per-bucket | triage_protocols.yaml + nursing_assessment.yaml + 46 encounter YAML(narrative block validation) |
| 4. Reverse-coverage | `DocumentType` enum ↔ `document_type_specs.yaml` keys(9 → 6 new added、reverse-coverage 拡張) |
| 5. Pre-register ordering | 46 encounter YAML の narrative validation を register_audit_module BEFORE |
| 6. Symmetric forward-coverage | 46 encounter YAML × narrative.* fields(全 46 必須) |
| 7. Cross-module URI(LOINC + SNOMED) | 6 new LOINC + CareTeam category SNOMED codes を canonical validation |

## 9. Testing strategy

### 9.1 Unit tests

| ファイル | 内容 |
|---|---|
| `tests/unit/test_types_triage.py` | TriageData dataclass |
| `tests/unit/test_types_encounter_alpha2.py` | primary_nurse_id + triage_data field |
| `tests/unit/modules/triage/test_engine.py` | triage_enricher + JTAS/ESI locale gating |
| `tests/unit/modules/triage/test_triage_protocols_yaml.py` | YAML validator |
| `tests/unit/modules/nursing/test_engine.py` | primary_nurse assignment + nursing_enricher |
| `tests/unit/modules/nursing/test_nursing_assessment_yaml.py` | YAML validator |
| `tests/unit/modules/document/narrative/test_encounter_types_supported.py` | encounter_types_supported gating |
| `tests/unit/modules/document/narrative/test_template_generator_alpha2.py` | 6 new DocumentType rendering |
| `tests/unit/modules/document/test_engine_alpha2.py` | encounter_type dispatch + 6 doc types |
| `tests/unit/output/test_fhir_care_team.py` | CareTeam builder |
| `tests/unit/output/test_fhir_composition_alpha2.py` | 6 new section rendering |
| `tests/unit/output/test_fhir_documents_alpha2.py` | 6 new DR handling |
| `tests/unit/modules/encounter/test_narrative_yaml.py` | 46 encounter YAML narrative block |
| `tests/unit/audit/test_document_audit_alpha2.py` | 拡張 lift_firing_proof(23+ checks) |

### 9.2 Integration tests

| ファイル | 内容 |
|---|---|
| `tests/integration/test_document_chain_alpha2.py` | 6 new resource type end-to-end emission |
| `tests/integration/test_care_team_basedon_coverage.py` | CareTeam ref integrity |
| `tests/integration/test_document_alpha2_determinism.py` | AD-16 byte-identical re-run |
| `tests/integration/test_document_alpha2_snapshot.py` | AD-32 mid-encounter semantics for nursing docs |
| `tests/integration/test_document_alpha2_subprocess_fullpipeline.py` | PR-90 production dict path |
| `tests/integration/test_document_alpha2_jp_localization.py` | JTAS + JP nursing section title |

### 9.3 AD-60 audit module(document_chain 拡張)

```python
ModuleAuditSpec(
    name="document_chain",  # 既存拡張
    canonical_constants=[
        # ... 既存 ...
        ("CARE_TEAM_ID_PREFIX", CARE_TEAM_ID_PREFIX),
        ("JTAS_SYSTEM_URI", JTAS_SYSTEM_URI),
        ("ESI_SYSTEM_URI", ESI_SYSTEM_URI),
    ],
    clinical_acceptance={
        # ... 既存 α-min-1 ...
        # α-min-2 additions
        "admission_nursing_assessment_per_inpatient_encounter": "== 1",
        "nursing_shift_note_per_day_per_inpatient": ">= 0.8",
        "nursing_discharge_summary_per_completed_inpatient": "== 1",
        "outpatient_soap_per_outpatient_encounter": "== 1",
        "ed_note_per_ed_encounter": "== 1",
        "ed_triage_note_per_ed_encounter": "== 1",
        "care_team_per_encounter": "== 1",
        "triage_data_per_ed_encounter": "== 1",
    },
    lift_firing_proof=lambda: [
        # ... 既存 17 checks ...
        # α-min-2 additions(6+):
        ("CARE_TEAM_ID_PREFIX", CARE_TEAM_ID_PREFIX, "careteam-"),
        ("no_drop_encounter_primary_nurse_id → CareTeam.participant[1]", ...),
        ("no_drop_encounter_triage_data.level → ED_TRIAGE_NOTE content", ...),
        ("no_drop_encounter_type='inpatient' → nursing docs emit", ...),
        ("no_drop_encounter_type='outpatient' → SOAP emit", ...),
        ("no_drop_encounter_type='emergency' → ED docs emit", ...),
        # 23+ total checks
    ],
)
```

### 9.4 DQR(production cohort)

```
clinosim run-beta --country US --population 10000 --seed 42 --output scratchpad/doc_alpha2_us10k/ --format fhir-r4
clinosim run-beta --country JP --population 5000  --seed 42 --output scratchpad/doc_alpha2_jp5k/  --format fhir-r4
clinosim audit run -d scratchpad/doc_alpha2_us10k --module document_chain
clinosim audit run -d scratchpad/doc_alpha2_jp5k  --module document_chain
```

期待:
- CareTeam: 160k+(1/encounter)
- ADMISSION_NURSING_ASSESSMENT: ~24k
- NURSING_SHIFT_NOTE: ~24k
- NURSING_DISCHARGE_SUMMARY: ~20k(non-in-progress inpatient)
- OUTPATIENT_SOAP + ED_NOTE + ED_TRIAGE_NOTE: 全 outpatient/ED encounter count 分

DQR doc:`docs/reviews/2026-07-XX-tier1-3-document-density-alpha-min-2-dqr.md`、4 軸 PASS。

### 9.5 Pre-merge gate

```
pytest tests/unit tests/integration -m "unit or integration"
```

## 10. Risks + Mitigation

| Risk | Mitigation |
|---|---|
| 46 encounter YAML × narrative.* fill が時間消費 | 5 priority disease-specific + 41 baseline template で最小化(α-min-1 fill strategy 踏襲) |
| CareTeam per-encounter で 160k 件 = 大 emit volume | resource type per NDJSON = FHIR Bulk Data pattern で自然対応、performance test(subprocess full-pipeline)で verify |
| Nursing shift 3 → daily 1 に scope 縮小(realism gap) | scope discipline 明示、α-min-2b で shift 3 拡張余地(β-JP-1 or 別 chain) |
| Nursing primary_nurse assignment で staff roster 不足 | nursing_enricher に nurse role の available_ratio check + fallback logic |
| Country gating(JTAS vs ESI)で JP US 二重 emit or drop | triage_protocols.yaml locale-gated single-emit、integration test で verify |
| Encounter YAML narrative field 追加で既存 encounter test regression | 全 field default_factory backwards-compat、既存 test 不変 |

## 11. Out-of-scope(★ TODO.md formal entry)

| 項目 | 後続予定 |
|---|---|
| NURSING_SHIFT_NOTE shift 3 交替 realism | α-min-2b or β-JP-1 |
| CareTeam 多職種 6 名(pharmacist + nutritionist + rehab + MSW) | β-JP-1 |
| Practitioner emit 拡充(nursing/pharmacy/nutrition/rehab roster) | β-JP-1 |
| 入院診療計画書 / 看護必要度 D 表(JP 厚労省必須) | β-JP-1 |
| 手術記録 / 麻酔記録(operative note) | β-2 |
| QuestionnaireResponse active emission(triage questionnaire を含む) | β-JP-1 |
| ED disposition = admit の場合 CareTeam の hand-over 記述 | β-JP-1 |
| ED_TRIAGE_NOTE の initial vitals(triage 時 vital signs) | β-JP-1 |
| ADT location transfer(ED→inpatient hand-over) | ε |
| CarePlan / Goal / EpisodeOfCare | δ |

## 12. Adversarial chain plan

10 例目の安定 chain pattern(9 例目 α-min-1 precedent):

| 段階 | 内容 | converged 判定 |
|---|---|---|
| α-min-2-original | 15 SDD task chain 完成 | audit + full test + DQR 4 軸 PASS |
| adversarial-1 | 5-lens parallel fan-out(silent-no-op / unification / FHIR-JP Core / determinism+scale / spec+memory) | findings 列挙、fix PR |
| α-min-2-adv-1 | adv-1 findings fix | audit + full test PASS |
| **converged** | Critical=0 + Important=0 + 残 cosmetic Minor only | chain CLOSED |

## 13. PR sequencing

```
α-min-2-PR1: Tier 1 #3 α-min-2 single chain(本 spec)
  scope = 2 new modules(nursing + triage)+ document extension + CareTeam + 46 encounter YAML narrative
  ├─ Internal task slice(15 tasks、SDD execution):
  │   ├─ Task 1: types(TriageData + DocumentType +6 + EncounterProtocol.narrative)
  │   ├─ Task 2: triage module + triage_protocols.yaml + validator
  │   ├─ Task 3: triage_enricher(POST_ENCOUNTER order=93)
  │   ├─ Task 4: nursing module + nursing_assessment.yaml + primary_nurse assignment
  │   ├─ Task 5: nursing_enricher(POST_ENCOUNTER order=94)
  │   ├─ Task 6: 46 encounter YAML narrative extension
  │   ├─ Task 7: DocumentTypeSpec.encounter_types_supported + specs_for_encounter_type
  │   ├─ Task 8: TemplateNarrativeGenerator 6 new DocumentType support
  │   ├─ Task 9: document_type_specs.yaml +6 entries
  │   ├─ Task 10: document_enricher encounter_type gating dispatch
  │   ├─ Task 11: _fhir_care_team.py 新 builder + fhir_r4_adapter registration
  │   ├─ Task 12: _fhir_composition.py + _fhir_documents.py 6 new DocumentType 対応
  │   ├─ Task 13: AD-60 audit 拡張(23+ lift_firing_proof)
  │   ├─ Task 14: integration tests + DQR + 8 docs sync
  │   └─ Task 15: final whole-branch review + PR open
  │
  ├─ Adversarial-1: 5-lens parallel fan-out
  └─ α-min-2-adv-1: fix
```

## 14. Docs sync(PR 内全更新)

- `README.md` + `README.ja.md`:Nursing + Outpatient + ED narrative + CareTeam 言及 + master plan link
- `MODULES.md`:`nursing` + `triage` module rows + Dependency Tree 更新(+ order=93/94 stage clarification)
- `DESIGN.md`:**AD-64**「Nursing + Outpatient + ED narrative + CareTeam density foundation」追加
- `docs/CONTRIBUTING-modules.md`:nursing + triage を always-on Module 例(第 7・8 番目)
- `clinosim/modules/nursing/README.md`:新規
- `clinosim/modules/triage/README.md`:新規
- `TODO.md`:OOS 10+ 項目 formal entry(β-JP-1 予告項目含む)
- `CLAUDE.md`:nursing + triage module DRY rule + DocumentTypeSpec.encounter_types_supported invariant
- `docs/design-guides/fhir-data-generation-logic.md`:CareTeam + 6 new DocumentType precedent

## 14.5 ★ Scope discipline(memory `feedback_scope_discipline`)

**本 chain で絶対遵守する原則**(α-min-1 と同):

> 「スコープが拡大すると、永遠に終わらないので、スコープの拡大はせずに、データ品質や臨床的整合性の観点で必要な追加のみスコープ内で対応すること」(user セッション 25 明示、α-min-1 で厳守済)

### 適用方針

1. **Spec scope = 確定**:本 spec の §1 / §11 で示した scope + OOS が contract、実装中追加禁止
2. **Implementer subagent**:brief 外項目を発見したら追加せず `DONE_WITH_CONCERNS` で報告(controller triage)
3. **Reviewer finding**:Critical/Important triage:
   - **scope 内 fix**:既存 invariant 違反 / 現 scope deliverable 成立に必須 / データ品質損なう bug / 臨床整合性違反
   - **OOS = TODO entry 化**:optimization / refactor / 新 feature / 既存 feature 拡張 / "consider adding"
4. **Adversarial fan-out**:同基準で triage、scope 拡張要望は ALL TODO 化
5. **Pre-merge 判定**:残 issue が "scope 拡張要望" のみ = ship-ready

### Master plan との関係

`docs/design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md` §2 の Phase 境界 = OOS の正規 boundary。本 chain で出る "β-JP-1 で実装すべきもの" は全部 OOS、TODO 化して後続 phase へ。

## 15. References

- Master plan:`docs/design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md`(§2 α-min-2)
- α-min-1 spec:`docs/superpowers/specs/2026-07-01-tier1-3-document-density-alpha-min-1-design.md`
- α-min-1 DQR:`docs/reviews/2026-07-01-tier1-3-document-density-alpha-min-1-dqr.md`(post-α-min-1 baseline)
- Memory:
  - `project_session_26_end_state.md`(α-min-1 完了状態 + 8 deferred TODO)
  - `project_document_density_master_plan.md`(全 7 phase roadmap)
  - `feedback_recommendation_evaluation_axes.md`(6 軸評価)
  - `feedback_cif_to_fhir_no_drop.md`(no-drop invariant)
  - `feedback_iterative_adversarial_review.md`(反復 adv chain 9→10 例目目標)
  - `feedback_scope_discipline.md`(scope 拡大禁止)
- PR precedent:
  - PR #128(α-min-1 original 15-task chain、AD-63)
  - PR #129(α-min-1 5-lens adv-1 fix)
- FHIR R4:CareTeam / Composition(6 new subtypes)/ DocumentReference / QuestionnaireResponse(infrastructure only)
- LOINC 認証(6 new codes、Task 8 で NLM clinicaltables verify + `clinosim/codes/data/loinc.yaml` 追加):34119-8 / 34120-6 / 34745-0 / 11488-4 / 51841-6 / 54094-8
- JTAS 認証:日本臨床救急医学会 JTAS 2017 実装
- ESI 認証:AHRQ ESI Version 4 Implementation Handbook
