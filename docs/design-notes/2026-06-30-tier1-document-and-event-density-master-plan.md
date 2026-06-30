# Tier 1 #3+ Document & Event Density Master Plan

**Status:** Active design memo
**Date:** 2026-06-30 セッション 25
**Scope:** Tier 1 #3 Document density chain + 連動 structured event density 拡張(複数 PR / セッション横断、マルチ chain 段階的実装)
**Audience:** clinosim contributor + 将来 session 引き継ぎ resource

---

## 0. Purpose

### 戦略 distillation(セッション 25 user 確認済)

clinosim の目的 = **EHR/EMR sample data generator**(医療現場で生成されるデータを利活用するシステム評価用大規模 dataset)。実 EHR レベル density 達成のため、本 plan は 2 dimension を同時拡張:

1. **Narrative document records 充実**(問診 / H&P / SOAP / 退院サマリ / 看護記録 etc.)
2. **Structured event records 充実**(病院 event 発火による FHIR resource emit 強化)

両 dimension とも:
- データ品質 + 臨床整合性 維持
- JP-specific は locale=JP gating
- 200 床 JP 急性期病院の typical density を benchmark

### 現状 density gap(US p=10,000 imaging chain DQR 実測)

| Resource type | clinosim/encounter | 実 EHR 200 床 JP /encounter | gap |
|---|---|---|---|
| **DocumentReference** | 0.00 | 5-15 | ★ 完全空白 |
| **Composition** | 0 | ~5 | 完全空白 |
| **QuestionnaireResponse** | 0 | ~5-10 | 完全空白(JP 様式)|
| **Procedure** | 0.02 | 1-5 | 50-250x 不足 |
| **MedicationAdmin(MAR)** | 3.86 | 30-150 | 8-40x 不足 |
| **DiagnosticReport** | 0.30 | 5-15 | 17-50x 不足 |
| **Observation** | 21.31 | 50-100 | 2-5x(nursing 高頻度不足) |
| **AllergyIntolerance** | 0 | ~1 per patient | 完全空白 |
| **ClinicalImpression** | 0 | ~5-10 | 完全空白 |
| **CareTeam** | 0 | 1 per encounter | 完全空白 |
| **Flag** | 0 | ~3-5 | 完全空白 |
| **AdverseEvent** | 0 | ~0.1-1 | 完全空白 |

---

## 1. Two-dimension 拡張計画

### Dimension A:Narrative document(40 種)

200 床 JP 病院で記録される narrative の inventory(別途整理済):

| Tier | カテゴリ | document 種数 | 200 床 daily volume |
|---|---|---|---|
| 1 | 絶対必須(全 EHR vendor 記録)| 9 | ~1,025 |
| 2 | 高頻度+高臨床重要 | 11 | ~345-455 |
| 3 | 中頻度/状況依存 | 10 | ~165-190 |
| 4 | 低頻度/特殊 | 10 | ~30-50 |

詳細表は本文書 §3 参照。clinosim 既存 `LLMTaskType` enum で stub 化済 = 7/40 = 17.5%。

### Dimension B:Structured event record(主要 15 種)

実 EHR で病院 event 発火時に自動 emit される FHIR resource:

| 既存 / 拡張要 | Resource | event source | 現状/encounter |
|---|---|---|---|
| ✅ | Observation(vital + lab) | measurement / order result | 21.31 |
| ✅ | Condition | diagnosis update | 3.45 |
| ✅ | MedicationRequest | prescription order | 0.54 |
| ✅ | MedicationAdministration | per-dose 投与 | 3.86(unrealistic、PR-α-MAR で改善)|
| ✅ | ServiceRequest(lab+imaging)| order placement | 2.38(PR1+Imaging 改善済)|
| ✅ | Procedure | bedside / surgical event | 0.02 ★ 大不足 |
| ✅ | DiagnosticReport | lab panel + radiology report | 0.30 ★ 大不足 |
| ✅ | Encounter | 入院 / 外来 / ED visit | 1 |
| ✅ | Patient + Practitioner | demographics + roster | static |
| ✅ | ImagingStudy + Endpoint | imaging exam | 0.03(PR #127 で追加)|
| ❌ | **AllergyIntolerance** | アレルギー検出 / 確認 | 0 |
| ❌ | **ClinicalImpression** | clinical reasoning update | 0 |
| ❌ | **CareTeam** | 多職種 staff 割当 | 0 |
| ❌ | **Goal + CarePlan** | care planning | 0 |
| ❌ | **Flag** | chart alert(DNR / allergy / falls)| 0 |
| ❌ | **DetectedIssue** | drug interaction / abnormal | 0 |
| ❌ | **AdverseEvent** | 医療事故 / 副作用 / fall | 0 |
| ❌ | **MedicationDispense** | pharmacy 払出 | 0 |
| ❌ | **NutritionOrder** | 食事指示 | 0 |
| ❌ | **Specimen**(独立 resource) | 採取 event | implicit in lab |
| ❌ | **AppointmentResponse** | 予約応答 | 0 |
| ❌ | **Communication** | 電話 / 家族連絡 | 0 |
| ❌ | **EpisodeOfCare** | 慢性疾患長期管理 | 0 |
| ❌ | **Claim + ChargeItem + Account**| billing event | 0 |

---

## 2. Phase 別 master roadmap

### Phase α-min-1 = Infrastructure + 入院 3 doc(初回 PR chain、最 minimal vertical slice)

**Document(narrative)**:
- ADMISSION_HP(入院時記録、COMPOSITION format)
- PROGRESS_NOTE(daily、FREE_TEXT format)
- DISCHARGE_SUMMARY(退院時、COMPOSITION format)

**Structured event 連動(同 chain で添加)**:
- AllergyIntolerance(allergy module 連動)
- ClinicalImpression(progress note と並行 emit、working diagnosis 更新)

**Infrastructure 確立**:
- `clinosim/modules/document/` 新 always-on Module(narrative_generator + document_generator + _fhir_documents の merge + 再構成)
- `NarrativeContext` 統一 dataclass(types/document.py)
- `DocumentTypeSpec` registry + `format_type` enum(FREE_TEXT / COMPOSITION / QUESTIONNAIRE_RESPONSE)
- `NarrativeGenerator` Protocol + `TemplateGenerator`(default)+ `LLMGenerator` plugin
- 既存 `llm_service/providers/` (Ollama / Bedrock / Anthropic) 流用
- Disease YAML 拡張(narrative.* field × 30 disease):
  - `hpi_template`
  - `physical_exam_findings`(severity 別)
  - `course_archetypes[].daily_trajectory`(★ progress note 核)
  - `discharge_instructions`
- Encounter YAML 拡張(narrative.* field × 46 condition、本 phase は ED + outpatient は α-min-2 で対応 — 入院用拡張のみ)
- 新 `clinosim/modules/allergy/`(AD-55 Base)
- 新 reference data:`physical_exam_findings.yaml` + `discharge_instructions.yaml`
- 新 FHIR builders:`_fhir_composition.py` + `_fhir_allergy_intolerance.py` + `_fhir_clinical_impression.py`
- 既存 `_fhir_documents.py` を Stage 2 default ON 化

**Tests + audit + DQR + docs**:
- 3 doc type × 2 format type unit tests
- Integration: chain emit + ref integrity + JP localization + determinism + subprocess full-pipeline
- AD-60 audit module `document_chain` + 15+ lift_firing_proof
- US p=10k + JP p=5k 4-axis DQR

**推定 PR**: 12-14
**セッション規模**: 1.5-2
**Deliverable**: 200 床 daily volume **~150 件**(入院 H&P+Progress+Discharge baseline 確保)
**Density 改善**: DocumentReference 0 → 4-5 / inpatient encounter

---

### Phase α-min-2 = Inpatient 看護 + 外来 / ED(残 Tier 1 主要)

**Document(narrative)**:
- ADMISSION_NURSING_ASSESSMENT(入院時看護アセスメント、COMPOSITION)
- NURSING_SHIFT_NOTE(看護経過記録 shift×3/day、FREE_TEXT)
- NURSING_DISCHARGE_SUMMARY(退院時看護サマリ、COMPOSITION)
- OUTPATIENT_SOAP(外来 SOAP、COMPOSITION)
- ED_NOTE(ER 受診記録、COMPOSITION)
- ED_TRIAGE_NOTE(ER トリアージ記録、FREE_TEXT)

**Structured event 連動**:
- CareTeam(担当看護師 + 主治医 allocation)
- Triage-derived data:JTAS level + arrival mode

**Infrastructure 拡張**:
- 新 `clinosim/modules/triage/`(ED 用、JTAS / ESI sampling)
- 新 reference data:`triage_protocols.yaml`
- Encounter YAML 拡張(outpatient + ED):
  - `narrative.outpatient_soap_template`
  - `narrative.ed_triage`(JTAS level + arrival_mode)
  - `narrative.ed_disposition_narrative`
- 既存 nursing module 拡張(`care_plan_field` + `discharge_assessment` schema)
- 新 FHIR builders:`_fhir_care_team.py`

**推定 PR**: 10-12
**セッション規模**: 1-1.5
**Density 改善**: DocumentReference 4-5 → 12-15(全 Tier 1 docs)、CareTeam 0 → 1/encounter

---

### Phase β-JP-1 = JP 厚労省必須書類(JP-only docs)

**Document(narrative、全 QuestionnaireResponse format)**:
- INPATIENT_TREATMENT_PLAN(入院診療計画書、QUESTIONNAIRE_RESPONSE)
- NUTRITION_CARE_PLAN(栄養管理計画書、QUESTIONNAIRE_RESPONSE)
- REHAB_TREATMENT_PLAN(リハビリ実施計画書、QUESTIONNAIRE_RESPONSE)
- NURSING_NECESSITY_D_TABLE(看護必要度 D 表、QUESTIONNAIRE_RESPONSE × daily)

**Structured event 連動**:
- 多職種 staff allocation(主治医 / 看護師 / 薬剤師 / 栄養士 / リハ / MSW)→ CareTeam 拡張
- 看護必要度 score → Observation(A/B/C 別 LOINC)
- NutritionOrder(食事指示)

**Infrastructure 拡張**:
- 新 `clinosim/modules/multidisciplinary_team/`(staff allocation rule per encounter)
- 新 `clinosim/modules/care_planning/`(JP only、4 厚労省 forms generation)
- 新 reference data:
  - `koroku_forms.yaml`(厚労省様式 template)
  - `nutrition_plans.yaml`(疾患別)
  - `rehab_goals.yaml`(疾患別)
- 新 FHIR builders:`_fhir_questionnaire_response.py` + `_fhir_nutrition_order.py`
- locale gating logic in `DocumentTypeSpec.countries_supported`

**JP-only filtering**(AD-55 PR3b-1 supplement pattern):
- US cohort では skip
- JP cohort で 4 doc + CareTeam + NutritionOrder emit

**推定 PR**: 12-15
**セッション規模**: 2
**Density 改善 JP only**: 看護必要度 daily +1/inpatient day(LOS 12 で +12)、入院診療計画書 +1/admission、栄養 / リハ 計画書 適用 disease で +1 each

---

### Phase β-2 = 手術 / 麻酔 / 多職種(残 Tier 2 docs + 拡張 Procedure / Procedure note 完成)

**Document(narrative)**:
- OPERATIVE_NOTE(手術記録、COMPOSITION)
- ANESTHESIA_RECORD(麻酔記録、COMPOSITION + Observation 連動)
- IC_DOCUMENT(同意書、QUESTIONNAIRE_RESPONSE)
- PHARMACY_COUNSEL_NOTE(薬剤管理指導、FREE_TEXT)
- REHAB_SESSION_NOTE(リハ実施記録、FREE_TEXT × session)
- MULTI_D_CONFERENCE_NOTE(多職種カンファ、COMPOSITION)
- FAMILY_CONFERENCE_NOTE(家族説明、FREE_TEXT)

**Structured event 連動**:
- Procedure density 大幅増加(bedside catalog: IV / NGT / catheter / 嚥下評価 + surgical workflow)
- MedicationDispense(pharmacy 払出 event)

**Infrastructure 拡張**:
- 新 reference data:`ic_scripts.yaml`(手術 / 化療 / Bx 説明 script)
- procedure module 拡張(bedside procedure catalog + surgical workflow)
- 新 `clinosim/modules/anesthesia/`(or procedure module 拡張)
- 新 FHIR builders:`_fhir_medication_dispense.py`

**推定 PR**: 14-18
**セッション規模**: 2-3
**Density 改善**: Procedure 0.02 → 1-3/encounter、MedicationDispense 0 → 5-10/encounter

---

### Phase γ = Tier 3 connectivity + Tier 1 #5/#6 統合

**Document(narrative)**:
- MSW_DISCHARGE_PLANNING(退院支援計画書、COMPOSITION)
- REFERRAL_LETTER_OUT(紹介状送り、COMPOSITION)
- REFERRAL_LETTER_IN(紹介状受け、COMPOSITION)
- CARE_OPINION_LETTER(主治医意見書、QUESTIONNAIRE_RESPONSE × JP-only)
- FIRST_VISIT_NOTE(初診時記録、COMPOSITION)

**Structured event 連動**(Tier 1 #6 統合):
- Appointment + Schedule(post-discharge follow-up)
- AppointmentResponse
- Communication(電話 / 家族連絡)
- Flag(慢性疾患 alert + allergy alert)

**Infrastructure 拡張**:
- 新 `clinosim/modules/family_dynamics/`(同居 + 主介護者 + 経済 SDOH 拡張)
- 新 `clinosim/modules/appointment/`(Tier 1 #6 統合)
- 新 reference data:`referral_letter_templates.yaml`(科別 + 疾患別)
- 新 FHIR builders:`_fhir_appointment.py` + `_fhir_communication.py` + `_fhir_flag.py`

**推定 PR**: 12-15
**セッション規模**: 2

---

### Phase δ = Tier 4 specialty + Tier 1 #7 統合

**Document(narrative)**:
- PATHOLOGY_REPORT(病理診断、COMPOSITION × 癌 cohort)
- CYTOLOGY_REPORT(細胞診、COMPOSITION × 癌 screening)
- PRE_OP_EVALUATION(術前評価、COMPOSITION)
- POST_OP_EVALUATION(術後評価、COMPOSITION)
- OR_NURSING_RECORD(手術看護記録、COMPOSITION)
- DEATH_CERTIFICATE(死亡診断書、QUESTIONNAIRE_RESPONSE × JP-only)
- HOME_VISIT_NOTE(訪問診療記録、COMPOSITION × 在宅医療)

**Structured event 連動**(Tier 1 #7 統合):
- CarePlan + Goal(慢性疾患長期管理)
- EpisodeOfCare(慢性疾患 multi-encounter chain)
- AdverseEvent(医療事故 / 副作用 / fall)
- DetectedIssue(drug interaction / abnormal)

**Infrastructure 拡張**:
- 新 `clinosim/modules/care_plan/`(Tier 1 #7 統合)
- 新 `clinosim/modules/pathology/`(癌 cohort 拡張、Tier 4)
- 新 FHIR builders:`_fhir_care_plan.py` + `_fhir_goal.py` + `_fhir_episode_of_care.py` + `_fhir_adverse_event.py` + `_fhir_detected_issue.py`

**推定 PR**: 14-18
**セッション規模**: 2-3

---

### Phase ε = ADT + Vital + Specimen density(Tier 1 #4 統合)

**Structured event(narrative なし、density 強化)**:
- Encounter.location[] history(ward → ICU → ward の物理移動 timeline、Tier 1 #4 統合)
- Vital sign 高頻度化(every-4h → every-1h ICU、every-2-4h ward)
- Specimen 独立 resource emit(採取 event timeline)
- Per-dose MedicationAdministration(現在 order-level → per-dose 展開)

**Infrastructure 拡張**:
- 新 `clinosim/modules/adt/`(Tier 1 #4 統合)
- 既存 inpatient simulator timing engine 拡張(vital frequency + ADT events)
- 新 FHIR builders:`_fhir_specimen.py`(独立 resource emit)
- MedicationAdministration per-dose 展開 logic refactor

**推定 PR**: 10-13
**セッション規模**: 1.5-2
**Density 改善**: Observation 21 → 60-100、MAR 3.86 → 30-100、Specimen 0 → 5-15

---

### Phase 計画合計

| Phase | scope | 推定 PR | セッション |
|---|---|---|---|
| α-min-1 | Infrastructure + 入院 3 doc + AllergyIntolerance + ClinicalImpression | 12-14 | 1.5-2 |
| α-min-2 | 看護 3 doc + 外来 SOAP + ED note + CareTeam + triage | 10-12 | 1-1.5 |
| β-JP-1 | JP 厚労省 4 doc + NutritionOrder + multidisciplinary_team | 12-15 | 2 |
| β-2 | 手術 7 doc + Procedure density + MedicationDispense | 14-18 | 2-3 |
| γ | Tier 3 connectivity 5 doc + Appointment + Flag + Communication | 12-15 | 2 |
| δ | Tier 4 specialty 7 doc + CarePlan + EpisodeOfCare + AdverseEvent | 14-18 | 2-3 |
| ε | ADT + Vital density + Specimen 独立 + MAR per-dose | 10-13 | 1.5-2 |
| **合計** | 200 床 JP EHR realistic density 達成 | **84-105** | **12-15** |

---

## 3. ★ Narrative 生成 architecture(統一 interface + 差し替え設計)

### 3.1 統一 interface(User 指示の core)

```python
# clinosim/types/document.py
@dataclass
class NarrativeContext:
    """全 narrative 生成の統一 input。"""
    
    # === Patient 軸 ===
    patient: PatientProfile
    
    # === Encounter 軸 ===
    encounter: EncounterRecord
    encounter_type: EncounterType  # INPATIENT / EMERGENCY / OUTPATIENT
    
    # === Scenario source(疾患 / 外来 YAML)===
    disease_protocol: DiseaseProtocol | None
    encounter_protocol: EncounterProtocol | None
    
    # === Scenario flow(continuous narrative の核)===
    clinical_course_archetype: str
    severity: str
    day_index: int       # 入院 day 0 = admission
    los_days: int
    
    # === 生成済 clinical data ===
    vitals: list[VitalSignRecord]
    lab_results: list[OrderResult]
    medications: list[MedicationAdministration]
    diagnoses: list[ClinicalDiagnosis]
    procedures: list[ProcedureRecord]
    allergies: list[Allergy]
    devices: list[Any]
    
    # === Document-specific ===
    document_type: DocumentType
    target_lang: str          # "en" or "ja"
    locale: str               # "us" or "jp"
    
    # === Multi-disciplinary ===
    care_team: CareTeam | None
    attending_physician: Practitioner | None
    primary_nurse: Practitioner | None
```

```python
# clinosim/modules/document/registry.py
class FormatType(str, Enum):
    FREE_TEXT = "free_text"
    COMPOSITION = "composition"
    QUESTIONNAIRE_RESPONSE = "questionnaire_response"

class GenerationFrequency(str, Enum):
    ADMISSION_ONCE = "admission_once"
    DAILY = "daily"
    DISCHARGE_ONCE = "discharge_once"
    SHIFT_3X = "shift_3x_per_day"
    PER_VISIT = "per_visit"
    AS_NEEDED = "as_needed"

@dataclass
class DocumentTypeSpec:
    type_key: str
    loinc_code: str
    display_en: str
    display_ja: str
    format_type: FormatType
    countries_supported: tuple[str, ...]           # ("us", "jp") or ("jp",)
    generation_frequency: GenerationFrequency
    prompt_template_id: str
    composition_sections: tuple[str, ...]          # for COMPOSITION
    structured_form_yaml: str | None               # for QUESTIONNAIRE_RESPONSE
    
    # ★ Stage 2 LLM 差し替え control
    llm_enabled_sections: tuple[str, ...] = ()    # section-level 制御
    llm_replacement_strategy: str = "template_only"  # template_only / full_replace / template_seed / polish

class DocumentTypeRegistry:
    """Canonical registry of all document types."""
    @staticmethod
    def for_country(country: str) -> list[DocumentTypeSpec]:
        return [s for s in _ALL_SPECS if country in s.countries_supported]
```

```python
# clinosim/modules/document/generator.py
class NarrativeGenerator(Protocol):
    def generate(
        self,
        ctx: NarrativeContext,
        spec: DocumentTypeSpec,
    ) -> NarrativeOutput:
        """
        Returns NarrativeOutput with:
          - text: str (for FREE_TEXT)
          - sections: dict[str, str] (for COMPOSITION)
          - structured: dict (for QUESTIONNAIRE_RESPONSE)
        """

class TemplateNarrativeGenerator:
    """Default, always-on, deterministic.
    
    全 3 format type 対応。Disease/Encounter YAML の narrative.* field を読み、
    Jinja2-like template で展開。Clinical course archetype + day_index で
    daily_trajectory を選択。
    """

class LLMNarrativeGenerator:
    """Stage 2 opt-in. 既存 llm_service provider を呼び出し。
    
    Strategy:
      - template_only: 何もしない(Stage 1 と同じ)
      - full_replace: テンプレートの結果を完全に LLM 生成に置き換え
      - template_seed: テンプレート出力を seed として LLM に渡し再構成
      - polish: テンプレート出力を LLM が編集 / 校正
    """
```

### 3.2 Stage 1 default template / Stage 2 LLM 差し替え(User 指示)

**Default(全 cohort)**:
- TemplateNarrativeGenerator のみ動作
- Deterministic、CI safe、no LLM dependency
- 200 床 JP cohort で完全 narrative 生成

**Stage 2 LLM 差し替え trigger**:
- ENV `CLINOSIM_NARRATIVE_LLM=on` で全体切替
- Config file `narrative_llm: { enabled_doc_types: [...] }` で document-level 細粒度制御
- `DocumentTypeSpec.llm_enabled_sections` で section-level 制御

### 3.3 ★ 差し替え戦略(User 質問への回答)

**User 提案 = (A) Stage 1 template + (B) Stage 2 LLM-specified replacement**

これに加え、検討すべき alternative ideas:

#### Idea A: Document-level 全置換(粗粒度、最 simple)
```yaml
narrative_llm:
  enabled_doc_types: [DISCHARGE_SUMMARY, IC_DOCUMENT, FAMILY_CONFERENCE_NOTE]
```
- メリット:設定簡単、運用 simple
- デメリット:section ごとの細粒度制御不可、LLM 不適切な部分(structured form section)も full replace = リスク

#### Idea B: Section-level 置換(★ 推奨、Composition format との親和性高)
```yaml
narrative_llm:
  document_types:
    ADMISSION_HP:
      enabled_sections: [chief_complaint, hpi, assessment_plan]   # 自由文 section のみ
      template_only_sections: [allergies, medications, vital]      # structured data 由来 section
    DISCHARGE_SUMMARY:
      enabled_sections: [hospital_course_summary, discharge_instructions]
```
- メリット:細粒度、適材適所、structured section は template で保護
- デメリット:設定行数増加

#### Idea C: 統計的 mix(per-encounter 確率的 sampling)
```yaml
narrative_llm:
  encounter_sample_rate: 0.20    # 20% encounters get LLM
```
- メリット:実 EHR realism(boilerplate + 自然文混在)
- デメリット:cohort-wise inconsistency

#### Idea D: ★ Template-as-seed(★★ 最推奨、hallucination risk 最小化)
```python
# LLM workflow
template_output = TemplateGenerator.generate(ctx, spec)
prompt = f"""
Below is a template-generated H&P narrative. Rewrite it to sound more natural
while preserving ALL facts. Do NOT add information not present.

{template_output}
"""
final_text = LLM.generate(prompt)
```
- メリット:LLM がテンプレートを補強、事実は template で確定 → hallucination 最小
- デメリット:cost(LLM 1 回追加)、generation 時間増
- ★ User 指定の「指定したものを差し替える」と最も親和性高

#### Idea E: Cache + replay(deterministic + cost-efficient)
```python
cache_key = hash((disease, archetype, day, severity, demographics_bucket, lang))
if cache_key in narrative_cache:
    return narrative_cache[cache_key]
else:
    text = LLM.generate(...)
    narrative_cache[cache_key] = text
    return text
```
- メリット:同 context 再現性、cost 削減、CI 用 cache 配布可能
- デメリット:cache size、cache invalidation 複雑
- ★ Stage 2 LLM 運用に必須(production cost 抑制)

#### Idea F: Quality control overlay(LLM as editor / polish)
```python
# Two-pass:
text_v1 = TemplateGenerator.generate(ctx, spec)
text_v2 = LLM.review_and_polish(text_v1, ctx)  # 校正 only、新事実追加禁止
```
- メリット:medical accuracy 保持 + 文体自然化
- デメリット:LLM 2 call(cost 2x)

#### Idea G: Cost-tiered pipeline(★ production 推奨)
```yaml
narrative_llm:
  document_strategy:
    PROGRESS_NOTE:        { provider: template, fallback: ollama }     # local cheap
    DISCHARGE_SUMMARY:    { provider: bedrock-sonnet-4 }                # cloud quality
    IC_DOCUMENT:          { provider: bedrock-sonnet-4 }                # high stakes
    NURSING_SHIFT_NOTE:   { provider: template }                        # template 十分
```
- メリット:cost 最適化、important doc は high-quality LLM
- デメリット:provider 設定複雑

#### Idea H: Few-shot few-prompt + RAG(高度)
- Disease YAML の trajectory + 過去 progress notes を retrieval context として LLM に
- メリット:cross-document consistency、cumulative narrative 自然
- デメリット:複雑、retrieval store 必要

#### Idea I: Multi-lang switch
- JP cohort = JP template、必要時 LLM で英文翻訳
- メリット:bilingual dataset 生成可能
- デメリット:translation quality variance

#### Idea J: Validation overlay(★ data quality 保証)
```python
text = NarrativeGenerator.generate(...)
validation_result = NarrativeValidator.check(text, ctx)
# - 事実整合性: 述べた数値 vs CIF 数値
# - 用語: 標準医療用語使用 / non-existent drug name 検出
# - JP grammar: 医療文書らしさ
if validation_result.has_issues:
    text = NarrativeGenerator.regenerate(...)
```
- メリット:data quality 保証(user emphasis)
- デメリット:validation logic 開発負担

#### Idea K: 統一 NarrativeOutput format + post-process
```python
@dataclass
class NarrativeOutput:
    raw_text: str                          # generator が返す
    metadata: dict                         # generator が tag(e.g. {generator: template})
    sections: dict[str, str]               # COMPOSITION 用
    structured: dict                       # QUESTIONNAIRE_RESPONSE 用
    facts_used: list[str]                  # ★ 使用した CIF fact の list(audit 用)
    
def emit_fhir(output: NarrativeOutput, spec: DocumentTypeSpec):
    # DocumentReference / Composition / QuestionnaireResponse builder へ
```
- メリット:audit + traceability + facts_used で fact-check 可能
- デメリット:NarrativeOutput schema 維持

### 3.4 推奨組み合わせ(α-min-1 から実装)

**Phase α-min-1 採用**:
- Default = Idea (template_only)
- Stage 2 = Idea **D template-as-seed** + Idea **E cache** + Idea **B section-level control**
- Future = Idea **G cost-tiered** + Idea **J validation**

```yaml
# clinosim/config/narrative.yaml(初回 PR 提案)
narrative:
  default_provider: template               # always-on
  stage2_provider: ollama                  # opt-in、CLINOSIM_NARRATIVE_LLM=on で発火
  cache_dir: "/var/cache/clinosim/narrative"
  
  # Document-type / section レベル制御(Idea B)
  document_types:
    ADMISSION_HP:
      stage2_strategy: template_seed       # Idea D
      enabled_sections: [chief_complaint, hpi, assessment_plan]
    PROGRESS_NOTE:
      stage2_strategy: template_only       # template default 十分
    DISCHARGE_SUMMARY:
      stage2_strategy: template_seed
      enabled_sections: [hospital_course, discharge_instructions]
    NURSING_SHIFT_NOTE:
      stage2_strategy: template_only
    OUTPATIENT_SOAP:
      stage2_strategy: template_seed
      enabled_sections: [subjective, assessment, plan]
    ED_NOTE:
      stage2_strategy: template_seed
      enabled_sections: [hpi, ed_course]
```

### 3.5 ★ Determinism + audit

- Template default = 完全 deterministic、seed 駆動
- LLM 切替時 = `temperature=0` + same seed = 准 deterministic だが LLM 本質的に non-deterministic
- Cache(Idea E)で reproducibility 保証
- AD-60 audit:Stage 1 template だけは byte-identical re-run 要求、Stage 2 LLM は分散許容(template fallback path で deterministic re-run)

---

## 4. 拡張すべき YAML / file / module(Phase 別 summary)

### α-min-1 拡張

| Target | 内容 |
|---|---|
| Disease YAML × 30 | `narrative.hpi_template` + `physical_exam_findings` + `course_archetypes[].daily_trajectory` + `discharge_instructions` |
| `patient` schema | `allergies: list[Allergy]` field |
| 新 module | `clinosim/modules/document/`(narrative_generator + document_generator + audit + reference_data 集約) |
| 新 module | `clinosim/modules/allergy/`(AD-55 Base) |
| 新 reference data | `clinosim/modules/document/reference_data/physical_exam_findings.yaml`(疾患 × archetype × day × system) |
| 新 reference data | `clinosim/modules/document/reference_data/discharge_instructions.yaml`(疾患横断 baseline + 疾患別 override)|
| 新 FHIR builders | `_fhir_composition.py` + `_fhir_allergy_intolerance.py` + `_fhir_clinical_impression.py` |
| 既存 builder 拡張 | `_fhir_documents.py` を Stage 2 default ON 化 + 3 format type dispatch |

### α-min-2 拡張

| Target | 内容 |
|---|---|
| Encounter YAML × 46 | `narrative.outpatient_soap_template` + `narrative.ed_triage` + `narrative.ed_disposition_narrative` |
| 既存 nursing module | `care_plan_field` + `admission_assessment_field` + `discharge_assessment_field` schema |
| 新 module | `clinosim/modules/triage/`(JTAS / ESI / KTAS sampling) |
| 新 reference data | `clinosim/modules/triage/reference_data/triage_protocols.yaml` |
| 新 FHIR builder | `_fhir_care_team.py` |

### β-JP-1 拡張(JP only)

| Target | 内容 |
|---|---|
| 新 module | `clinosim/modules/multidisciplinary_team/`(staff allocation rule) |
| 新 module | `clinosim/modules/care_planning/`(JP 厚労省 4 forms generation、JP-only) |
| 新 reference data | `koroku_forms.yaml`(様式 template) |
| 新 reference data | `nutrition_plans.yaml`(疾患別 nutrition plan) |
| 新 reference data | `rehab_goals.yaml`(疾患別 rehab goal) |
| 既存 nursing module | 看護必要度 D 表 A/B/C scoring logic |
| 新 FHIR builders | `_fhir_questionnaire_response.py` + `_fhir_nutrition_order.py` |

### β-2 〜 δ + ε:詳細は本文書 §2 参照

---

## 5. 設計原則(canonical patterns 継承)

PR1 LAB chain + Imaging chain で確立した patterns:

1. **YAML schema = canonical owner**:Pydantic schema が data structure、YAML が data source
2. **Reference data 集中**:`<module>/reference_data/*.yaml`、validators で forward + reverse coverage
3. **Provider plugin pattern**:既存 `llm_service/providers/` 流用(Ollama / Bedrock / Anthropic / Template)
4. **AD-55 always-on Module**:document module は near-essential clinical cascade
5. **Locale gating**:`countries_supported: tuple = ("us", "jp")` field で JP-only docs filter
6. **Canonical constants writer↔reader**:`DOC_REFERENCE_ID_PREFIX` / `COMPOSITION_ID_PREFIX` / `QUESTIONNAIRE_RESPONSE_ID_PREFIX` 各 owner
7. **`_o(obj, name, default)` dual-access**:全 builder で
8. **5-lens adversarial fan-out**:各 chain で
9. **AD-60 audit + 15+ lift_firing_proof + 4 軸 DQR**:US p=10k + JP p=5k
10. **CIF → FHIR no-drop invariant**:全 CIF field の FHIR target emission matrix を spec に書面化

---

## 6. Risks + Mitigation

| Risk | Mitigation |
|---|---|
| Phase 数大、scope creep | 各 phase 末で converged 宣言 + memory update + 次 phase decision gate |
| 30 disease YAML × 4 narrative field 拡張で fill 効率課題 | Phase α-min-1 で initial fill は LLM 補完 OK(再現性は template が保証)、出力は human review |
| Stage 2 LLM 切替時の determinism 喪失 | Cache(Idea E)+ template fallback path での deterministic re-run 担保 |
| JP-only docs の US cohort 誤 emit | DocumentTypeRegistry.countries_supported field で statically filter、audit gate で verify |
| 大量 narrative emit による NDJSON size 爆発(200 床日 ~1500 docs)| Per-resource NDJSON file size limit + bulk export per-encounter chunking 検討 |
| Multi-disciplinary team allocation の臨床整合性 | Disease YAML + encounter context から team membership rule 駆動、固定 / random でない |
| 看護必要度 D 表 / 厚労省様式の最新規定追随 | reference data に厚労省告示 version + 改訂時 update workflow を documentation |
| LLM hallucination(invented drug name 等) | Template-as-seed(Idea D)+ validation overlay(Idea J)+ facts_used tracking(Idea K) |
| Cross-document consistency(progress notes 連続性) | Clinical course archetype + day-by-day trajectory で template 駆動、LLM seed としても traje 渡し |

---

## 7. 参照 + cross-link

- Memory:
  - `project_event_density_strategy.md`(セッション25 戦略軸転換)
  - `project_ehr_event_emphasis.md`(セッション25 第一段階)
  - `project_ehr_sample_dataset_roadmap.md`(セッション23 元 roadmap)
  - `feedback_recommendation_evaluation_axes.md`(6 軸評価)
  - `feedback_unify_data_logic.md`(canonical single source)
  - `feedback_cif_to_fhir_no_drop.md`(no-drop invariant)
- 既存 PR:
  - PR #126 ServiceRequest LAB(AD-61)
  - PR #127 Imaging chain α-min(AD-62)
- 既存 docs:
  - `MODULES.md`(現 25 module + audit)
  - `DESIGN.md`(ADR 62+ entries)
  - `docs/design-guides/fhir-data-generation-logic.md`
  - `docs/CONTRIBUTING-modules.md`
- 既存 module 流用:
  - `clinosim/modules/llm_service/`(Stage 2 provider plugin)
  - `clinosim/modules/output/narrative_generator.py`(Stage 1 generator、移行先 = `clinosim/modules/document/`)
  - `clinosim/modules/output/document_generator.py`(Stage 1 generator)
  - `clinosim/modules/output/_fhir_documents.py`(Stage 1 builder)
  - `clinosim/types/clinical.py:ClinicalDocument`

## 8. 次手 sequence

1. **PR #127 imaging chain merge**(user)
2. **PR #127 post-merge 5-lens adversarial fan-out**(controller、TODO #3 close)
3. **Phase α-min-1 chain 着手**:
   - brainstorming(本 plan + 追加質問あれば)
   - spec writing(spec doc)
   - writing-plans(implementation plan)
   - SDD execution(12-14 task)
   - 5-lens adversarial fan-out
   - converged → PR open

---

**This document is the master plan for the entire document + event density chain.**
**It is intentionally exhaustive — future sessions can read it cold and resume.**
