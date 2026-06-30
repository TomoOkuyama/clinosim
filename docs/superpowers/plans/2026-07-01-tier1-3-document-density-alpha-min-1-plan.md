# Tier 1 #3 α-min-1 Document Density Chain — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 入院 3 doc(H&P + Progress + Discharge)+ AllergyIntolerance + ClinicalImpression を emit する Document narrative + structured event density foundation を確立。Stage 1 template default + Stage 2 LLM hook(default OFF)+ 3 FHIR format type 対応(FREE_TEXT + COMPOSITION + QUESTIONNAIRE_RESPONSE infrastructure)。

**Architecture:** 新 `clinosim/modules/document/` + `clinosim/modules/allergy/` always-on Module(AD-55 cascade)+ 統一 `NarrativeContext` interface + 既存 `narrative_generator.py` + `document_generator.py` + `_fhir_documents.py` を document module へ merge。POST_ENCOUNTER enricher order=95(after device/hai/antibiotic/imaging)。

**Tech Stack:** Python 3.11+ / Pydantic(disease YAML schema)/ dataclass(CIF types)/ numpy.random.Generator(AD-16 sub-seed)/ PyYAML(reference data)/ pytest unit + integration + e2e。

## Global Constraints

- **★ Scope discipline**(memory `feedback_scope_discipline`): scope 拡大禁止、データ品質 / 臨床整合性 必須のみ scope 内 fix、それ以外 TODO entry 化
- **AD-16 determinism:** sub-seed via `derive_sub_seed(master, ENRICHER_SEED_OFFSETS["allergy"|"document"], key)`. Master stream 不変
- **AD-30:** CIF はコードのみ、display は output 時 `code_lookup` 解決
- **AD-31:** FHIR Resource.id per-type unique、canonical prefix(writer↔reader shared constant)
- **AD-32 snapshot:** mid-encounter snapshot で DISCHARGE_SUMMARY skip
- **AD-46 dual coding:** Composition.category + AllergyIntolerance.code = LOINC + SNOMED dual coding(必要に応じ)
- **AD-55:** always-on Module = `enabled=lambda c: True`(device/hai/antibiotic/imaging precedent)
- **AD-56:** 新 builder は `_BUNDLE_BUILDERS` リスト追加、`_build_bundle()` 直接編集禁止
- **CIF → FHIR no-drop invariant:** spec §3.4 emission matrix 経由、CIF field → FHIR target 全 emit
- **Silent-no-op defense 7-layer:** canonical URI / shared ID prefix / YAML empty + per-bucket / reverse-coverage / validator pre-register ordering / symmetric forward-coverage / cross-module canonical URI
- **`_o(obj, name, default)` dual-access**(PR-90 教訓):全 builder で dict + dataclass 両 path
- **dict + dataclass 両 path test 必須**(PR-90 教訓):unit test に両 fixture
- **Subprocess full-pipeline test 必須**(PR-90 教訓):production json.load → builder dict path verify
- **Code 権威 sources:** LOINC = NLM clinicaltables / SNOMED = tx.fhir.org `$lookup` / Codes 不確実は `# TODO: verify`
- **Branch:** `feature/tier1-document-density-alpha-min-1`(セッション 26 開始時 master から作成)
- **Master fork-point:** PR #127 merge 後の master HEAD
- **Commit trailer:** `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` + `Claude-Session: <session-url>`
- **Pre-merge gate:** `pytest tests/unit tests/integration -m "unit or integration"` full sweep(セッション22 教訓)

## File Structure

### Files to CREATE

| Path | 責務 |
|---|---|
| `clinosim/types/allergy.py` | `Allergy` + `AllergyReaction` dataclass |
| `clinosim/types/document.py` | `NarrativeContext` + `NarrativeOutput` + `DocumentType` + `FormatType` enums |
| `clinosim/modules/allergy/__init__.py` | exports |
| `clinosim/modules/allergy/engine.py` | POST_POPULATION enricher + sampling rule |
| `clinosim/modules/allergy/README.md` | module README |
| `clinosim/modules/allergy/reference_data/allergens.yaml` | drug + food + environment catalog |
| `clinosim/modules/document/__init__.py` | exports + canonical constants |
| `clinosim/modules/document/engine.py` | POST_ENCOUNTER enricher + ClinicalImpression generation |
| `clinosim/modules/document/audit.py` | AD-60 ModuleAuditSpec + 15+ lift_firing_proof |
| `clinosim/modules/document/README.md` | module README |
| `clinosim/modules/document/narrative/__init__.py` | exports |
| `clinosim/modules/document/narrative/context.py` | `NarrativeContext` factory(CIF → ctx) |
| `clinosim/modules/document/narrative/registry.py` | `DocumentTypeSpec` registry + countries_supported gate |
| `clinosim/modules/document/narrative/template_generator.py` | Stage 1 default generator(3 format type 対応) |
| `clinosim/modules/document/narrative/llm_generator.py` | Stage 2 hook(llm_service wrap、default OFF) |
| `clinosim/modules/document/narrative/cache.py` | Stage 2 deterministic cache(Idea E) |
| `clinosim/modules/document/narrative/replacement_strategy.py` | Idea B/D dispatch |
| `clinosim/modules/document/reference_data/physical_exam_findings.yaml` | 疾患 × archetype × day × system catalog |
| `clinosim/modules/document/reference_data/discharge_instructions.yaml` | 疾患横断 baseline + 疾患別 override |
| `clinosim/modules/document/reference_data/document_type_specs.yaml` | DocumentTypeSpec registry source |
| `clinosim/modules/output/_fhir_composition.py` | Composition resource builder |
| `clinosim/modules/output/_fhir_allergy_intolerance.py` | AllergyIntolerance resource builder |
| `clinosim/modules/output/_fhir_clinical_impression.py` | ClinicalImpression resource builder |
| `tests/unit/test_types_allergy.py` | Allergy dataclass tests |
| `tests/unit/test_types_document.py` | NarrativeContext / NarrativeOutput tests |
| `tests/unit/test_types_clinical_impression.py` | ClinicalImpressionRecord tests |
| `tests/unit/modules/allergy/__init__.py` | empty marker |
| `tests/unit/modules/allergy/test_engine.py` | allergy sampling tests |
| `tests/unit/modules/allergy/test_allergens_yaml.py` | YAML validator tests |
| `tests/unit/modules/document/__init__.py` | empty marker |
| `tests/unit/modules/document/test_engine.py` | enricher + ClinicalImpression daily emit tests |
| `tests/unit/modules/document/narrative/__init__.py` | empty marker |
| `tests/unit/modules/document/narrative/test_context.py` | factory tests |
| `tests/unit/modules/document/narrative/test_registry.py` | DocumentTypeSpec + countries_supported gate tests |
| `tests/unit/modules/document/narrative/test_template_generator.py` | 3 format type + course archetype tests |
| `tests/unit/modules/document/narrative/test_llm_generator.py` | hook tests(default OFF + opt-in) |
| `tests/unit/modules/document/narrative/test_cache.py` | cache + replay tests |
| `tests/unit/modules/document/test_reference_data.py` | 3 YAML validator tests |
| `tests/unit/output/test_fhir_composition.py` | Composition builder tests |
| `tests/unit/output/test_fhir_allergy_intolerance.py` | AllergyIntolerance builder tests |
| `tests/unit/output/test_fhir_clinical_impression.py` | ClinicalImpression builder tests |
| `tests/unit/audit/test_document_audit.py` | audit module + lift_firing_proof tests |
| `tests/integration/test_document_chain.py` | end-to-end emission |
| `tests/integration/test_document_basedon_coverage.py` | ref integrity gate |
| `tests/integration/test_document_determinism.py` | AD-16 byte-identical re-run |
| `tests/integration/test_document_snapshot.py` | AD-32 snapshot semantics |
| `tests/integration/test_document_subprocess_fullpipeline.py` | production json.load path |
| `tests/integration/test_document_jp_localization.py` | JP cohort 全 ja display |
| `docs/reviews/2026-XX-XX-tier1-3-document-density-alpha-min-1-dqr.md` | DQR report(Task 13) |

### Files to MODIFY

| Path | 修正内容 |
|---|---|
| `clinosim/types/clinical.py` | `ClinicalImpressionRecord` dataclass 追加 |
| `clinosim/types/patient.py` | `PatientProfile.allergies: list[Allergy] = field(default_factory=list)` 追加 |
| `clinosim/modules/disease/protocol.py` | `narrative` field(Pydantic schema)追加 |
| `clinosim/modules/disease/reference_data/*.yaml`(× 30 file) | `narrative:` block 追加 |
| `clinosim/modules/output/_fhir_documents.py` | refactor:Stage 2 default ON + document.narrative 経由 |
| `clinosim/modules/output/fhir_r4_adapter.py` | `_BUNDLE_BUILDERS` に 3 新 builder 追加 |
| `clinosim/simulator/enrichers.py` | allergy(POST_POPULATION)+ document(POST_ENCOUNTER order=95)enricher 登録 |
| `clinosim/simulator/seeding.py` | `ENRICHER_SEED_OFFSETS["allergy"]` + `["document"]` 追加 |
| `clinosim/codes/data/loinc.yaml` | 34117-2 / 11506-3 / 18842-5 entry 確認 + 不足 entry 追加 |
| `clinosim/codes/data/snomed-ct.yaml` | allergen + reaction manifestation codes 追加 |
| `README.md` + `README.ja.md` | document density chain 言及 + master plan link |
| `MODULES.md` | document + allergy module row 追加 + Dependency Tree |
| `DESIGN.md` | AD-63 ADR 追加 |
| `docs/CONTRIBUTING-modules.md` | document module を always-on Module 例 |
| `TODO.md` | OOS 16+ 項目 formal entry |
| `CLAUDE.md` | 統一 narrative DRY rule + 2 module DRY rules |
| `docs/design-guides/fhir-data-generation-logic.md` | precedent 追加 |
| `tests/e2e/golden/*` | 再生成(意図的 byte-diff) |

---

## Task 1: CIF types — Allergy + NarrativeContext + ClinicalImpressionRecord

**Files:**
- Create: `clinosim/types/allergy.py`
- Create: `clinosim/types/document.py`
- Modify: `clinosim/types/clinical.py`(ClinicalImpressionRecord 追加)
- Modify: `clinosim/types/patient.py`(PatientProfile.allergies field 追加)
- Test: `tests/unit/test_types_allergy.py`(新)
- Test: `tests/unit/test_types_document.py`(新)
- Test: `tests/unit/test_types_clinical_impression.py`(新)

**Interfaces:**
- Consumes: none(foundation task)
- Produces:
  - `clinosim.types.allergy.Allergy(allergy_id, allergen_code, allergen_display, category, criticality, verification_status, onset_date, reactions)`
  - `clinosim.types.allergy.AllergyReaction(manifestation_snomed, manifestation_display, severity)`
  - `clinosim.types.document.NarrativeContext(20+ fields)`
  - `clinosim.types.document.NarrativeOutput(raw_text, sections, structured, metadata, facts_used)`
  - `clinosim.types.document.DocumentType` enum(ADMISSION_HP / PROGRESS_NOTE / DISCHARGE_SUMMARY)
  - `clinosim.types.document.FormatType` enum(FREE_TEXT / COMPOSITION / QUESTIONNAIRE_RESPONSE)
  - `clinosim.types.clinical.ClinicalImpressionRecord(impression_id, encounter_id, date, day_index, description, summary, investigation_refs, finding_refs, prognosis, practitioner_id)`
  - `clinosim.types.patient.PatientProfile.allergies: list[Allergy]` field

- [ ] **Step 1: Write failing tests**

`tests/unit/test_types_allergy.py`:

```python
"""Unit tests for clinosim.types.allergy(Tier 1 #3 α-min-1 PR1)."""

from __future__ import annotations

from datetime import date

from clinosim.types.allergy import Allergy, AllergyReaction


def test_allergy_reaction_defaults_no_op():
    r = AllergyReaction()
    assert r.manifestation_snomed == ""
    assert r.severity == "mild"


def test_allergy_defaults_no_op():
    a = Allergy()
    assert a.allergy_id == ""
    assert a.allergen_code == ""
    assert a.category == ""
    assert a.criticality == "low"
    assert a.verification_status == "confirmed"
    assert a.onset_date is None
    assert a.reactions == []


def test_allergy_full_payload():
    reaction = AllergyReaction(
        manifestation_snomed="247472004",
        manifestation_display="Rash",
        severity="moderate",
    )
    a = Allergy(
        allergy_id="al-pt1-1",
        allergen_code="387207008",
        allergen_display="Penicillin",
        category="medication",
        criticality="high",
        verification_status="confirmed",
        onset_date=date(2020, 6, 15),
        reactions=[reaction],
    )
    assert a.allergen_display == "Penicillin"
    assert a.reactions[0].severity == "moderate"
```

`tests/unit/test_types_document.py`:

```python
"""Unit tests for clinosim.types.document(Tier 1 #3 α-min-1 PR1)."""

from __future__ import annotations

from clinosim.types.document import (
    DocumentType, FormatType, NarrativeContext, NarrativeOutput,
)


def test_document_type_enum_α_min_1_set():
    assert DocumentType.ADMISSION_HP.value == "admission_hp"
    assert DocumentType.PROGRESS_NOTE.value == "progress_note"
    assert DocumentType.DISCHARGE_SUMMARY.value == "discharge_summary"


def test_format_type_enum():
    assert FormatType.FREE_TEXT.value == "free_text"
    assert FormatType.COMPOSITION.value == "composition"
    assert FormatType.QUESTIONNAIRE_RESPONSE.value == "questionnaire_response"


def test_narrative_output_defaults_empty():
    out = NarrativeOutput()
    assert out.raw_text == ""
    assert out.sections == {}
    assert out.structured == {}
    assert out.metadata == {}
    assert out.facts_used == []


def test_narrative_output_section_payload():
    out = NarrativeOutput(
        sections={"chief_complaint": "発熱、咳嗽", "hpi": "3 日前より..."},
        metadata={"generator": "template"},
        facts_used=["disease_protocol.chief_complaint"],
    )
    assert out.sections["chief_complaint"] == "発熱、咳嗽"
    assert "template" in out.metadata.values()


def test_narrative_context_default_constructible():
    """NarrativeContext は dataclass、全 field default 設定可。"""
    from clinosim.types.patient import PatientProfile
    from clinosim.types.encounter import EncounterRecord, EncounterType
    ctx = NarrativeContext(
        patient=PatientProfile(),
        encounter=EncounterRecord(),
        encounter_type=EncounterType.INPATIENT,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=5,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.ADMISSION_HP,
        target_lang="ja",
        locale="jp",
    )
    assert ctx.clinical_course_archetype == "uncomplicated_improvement"
    assert ctx.locale == "jp"
```

`tests/unit/test_types_clinical_impression.py`:

```python
"""Unit tests for ClinicalImpressionRecord(Tier 1 #3 α-min-1 PR1)."""

from __future__ import annotations

from datetime import date

from clinosim.types.clinical import ClinicalImpressionRecord


def test_clinical_impression_defaults():
    c = ClinicalImpressionRecord()
    assert c.impression_id == ""
    assert c.encounter_id == ""
    assert c.day_index == 0
    assert c.description == ""
    assert c.investigation_refs == []
    assert c.finding_refs == []
    assert c.prognosis == ""


def test_clinical_impression_full_payload():
    c = ClinicalImpressionRecord(
        impression_id="ci-enc1-3",
        encounter_id="enc1",
        date=date(2026, 7, 1),
        day_index=3,
        description="炎症マーカー低下、改善傾向",
        summary="CRP 5.2 → 1.8、WBC 11k → 8k、解熱、食欲改善",
        investigation_refs=["lab-enc1-CRP-3"],
        finding_refs=["cond-enc1-pneumonia-primary"],
        prognosis="改善見込み",
        practitioner_id="staff-doc-001",
    )
    assert c.day_index == 3
    assert c.investigation_refs[0] == "lab-enc1-CRP-3"
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/unit/test_types_allergy.py tests/unit/test_types_document.py tests/unit/test_types_clinical_impression.py -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Create `clinosim/types/allergy.py`**

```python
"""Allergy CIF dataclasses(Tier 1 #3 α-min-1 PR1).

PatientProfile.allergies に格納、FHIR AllergyIntolerance への mapping は
clinosim/modules/output/_fhir_allergy_intolerance.py で。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class AllergyReaction:
    """Allergic reaction manifestation."""
    manifestation_snomed: str = ""    # SNOMED CT code
    manifestation_display: str = ""   # locale-resolved display
    severity: str = "mild"            # mild / moderate / severe


@dataclass
class Allergy:
    """Patient allergy/intolerance(AD-30 code-only CIF)."""
    allergy_id: str = ""              # patient-internal id
    allergen_code: str = ""           # SNOMED for allergen substance
    allergen_display: str = ""        # locale-resolved display
    category: str = ""                # "medication" / "food" / "environment"
    criticality: str = "low"          # low / high / unable-to-assess
    verification_status: str = "confirmed"  # confirmed / unconfirmed / refuted
    onset_date: date | None = None
    reactions: list[AllergyReaction] = field(default_factory=list)
```

- [ ] **Step 4: Create `clinosim/types/document.py`**

```python
"""Document CIF dataclasses(Tier 1 #3 α-min-1 PR1).

NarrativeContext は全 narrative 生成の統一 input、全 generator(template / LLM)
が同 schema で受け取り、NarrativeOutput を返す。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FormatType(str, Enum):
    """Document content format type."""
    FREE_TEXT = "free_text"                  # → DocumentReference (text content)
    COMPOSITION = "composition"              # → Composition (section structure)
    QUESTIONNAIRE_RESPONSE = "questionnaire_response"  # → QuestionnaireResponse(β-JP-1 で active)


class DocumentType(str, Enum):
    """Document types in scope for current chain phase.
    
    α-min-1 scope: ADMISSION_HP + PROGRESS_NOTE + DISCHARGE_SUMMARY。
    後続 phase で enum 値追加(本 chain では拡張禁止 — scope discipline)。
    """
    ADMISSION_HP = "admission_hp"            # LOINC 34117-2
    PROGRESS_NOTE = "progress_note"          # LOINC 11506-3
    DISCHARGE_SUMMARY = "discharge_summary"  # LOINC 18842-5


@dataclass
class NarrativeContext:
    """全 narrative 生成の統一 input(CIF → ctx factory が組み立てる)。

    Generator(template / LLM)は本 dataclass のみ参照、結果を NarrativeOutput
    で返す。NarrativeOutput.facts_used で使用 CIF field を tracking。
    """
    # === Patient 軸 ===
    patient: Any                         # PatientProfile(避循環 import 用 Any)

    # === Encounter 軸 ===
    encounter: Any                       # EncounterRecord
    encounter_type: Any                  # EncounterType enum

    # === Scenario source ===
    disease_protocol: Any | None         # Pydantic DiseaseProtocol
    encounter_protocol: Any | None       # Pydantic EncounterProtocol

    # === Scenario flow ===
    clinical_course_archetype: str
    severity: str
    day_index: int                       # 入院 day 0 = admission
    los_days: int

    # === 生成済 clinical data ===
    vitals: list[Any]                    # list[VitalSignRecord]
    lab_results: list[Any]               # list[OrderResult]
    medications: list[Any]               # list[MedicationAdministration]
    diagnoses: list[Any]                 # list[ClinicalDiagnosis]
    procedures: list[Any]                # list[ProcedureRecord]
    allergies: list[Any]                 # list[Allergy]

    # === Document-specific ===
    document_type: DocumentType
    target_lang: str                     # "en" / "ja"
    locale: str                          # "us" / "jp"


@dataclass
class NarrativeOutput:
    """Generator 戻り値、emit builder の入力。"""
    raw_text: str = ""                       # FREE_TEXT 用
    sections: dict[str, str] = field(default_factory=dict)    # COMPOSITION 用
    structured: dict = field(default_factory=dict)            # QUESTIONNAIRE_RESPONSE 用
    metadata: dict = field(default_factory=dict)              # {generator, lang, ...}
    facts_used: list[str] = field(default_factory=list)       # 使用 CIF field(audit 用)
```

- [ ] **Step 5: Add `ClinicalImpressionRecord` to `clinosim/types/clinical.py`**

Append at end of file:

```python
from dataclasses import field
from datetime import date


@dataclass
class ClinicalImpressionRecord:
    """Daily working diagnosis update(Tier 1 #3 α-min-1).

    FHIR ClinicalImpression resource への source data。
    入院 daily emit、CIFPatientRecord.extensions["clinical_impressions"]
    に格納(AD-55 Module pattern)。
    """
    impression_id: str = ""              # "ci-{enc}-{day}"
    encounter_id: str = ""
    date: date = field(default_factory=date.today)
    day_index: int = 0
    description: str = ""                # 短い要約
    summary: str = ""                    # 詳細
    investigation_refs: list[str] = field(default_factory=list)  # Observation id refs
    finding_refs: list[str] = field(default_factory=list)        # Condition id refs
    prognosis: str = ""
    practitioner_id: str = ""            # 主治医
```

- [ ] **Step 6: Replace existing `Allergy` in `clinosim/types/patient.py` with import from `clinosim/types/allergy.py`**

★ **Pre-flight verification 結果(セッション 26)**:`clinosim/types/patient.py:85` に既存 `Allergy(substance, reaction_type, severity)` 3-field 旧 schema あり、`PatientProfile.allergies: list[Allergy] = field(default_factory=list)` は line 129 で既に定義済。`clinosim/modules/patient/activator.py:201` が旧 schema で 15% prevalence sampling 中。

実施手順:
1. `clinosim/types/patient.py` で 旧 `@dataclass class Allergy: substance / reaction_type / severity` block(line 84-88 付近)を **削除**
2. ファイル top で import 追加:`from clinosim.types.allergy import Allergy`(field type hint と activator backward-compat 用)
3. `PatientProfile.allergies` field(line 129)は既存のまま保持(default_factory 不変)、type hint だけ新 `Allergy` を指す
4. `clinosim/modules/patient/activator.py:201` の `Allergy(substance="...", reaction_type="rash", severity="mild")` 呼び出しを新 schema にマップ:`Allergy(allergy_id=f"al-{patient_id}-1", allergen_code=<SNOMED for substance>, allergen_display=<substance>, category="medication", criticality="low", verification_status="confirmed", reactions=[AllergyReaction(manifestation_snomed="247472004", manifestation_display="Rash", severity="mild")])`
5. activator.py import を更新:`from clinosim.types.allergy import Allergy, AllergyReaction`(旧 `from clinosim.types.patient import ..., Allergy, ...` から Allergy を外す)

NOTE: activator 内 sampling は **Task 15 で allergy module enricher に migrate して activator から完全に切り離す**。本 Task 1 では activator の Allergy 呼び出しを新 schema に「型合わせ」するのみ(機能不変、deprecation step は Task 15)。

★ **Verification**:`pytest clinosim/modules/patient/test_patient.py` で既存 activator allergy test(line 55 周辺、`Allergy(substance="Sulfonamide", ...)` を使用)も新 schema に書換える必要あり。implementer subagent が test fixture を新 schema に migrate して PASS させる。

- [ ] **Step 7: Run tests to verify pass**

```
pytest tests/unit/test_types_allergy.py tests/unit/test_types_document.py tests/unit/test_types_clinical_impression.py -v
```

Expected: all pass.

- [ ] **Step 8: Run existing tests for regression**

```
pytest tests/unit -m unit -x -q
```

Expected: no new failures(`PatientProfile.allergies` default empty = no-op safe)。

- [ ] **Step 9: Commit**

```
git add clinosim/types/allergy.py clinosim/types/document.py clinosim/types/clinical.py clinosim/types/patient.py clinosim/modules/patient/activator.py clinosim/modules/patient/test_patient.py tests/unit/test_types_allergy.py tests/unit/test_types_document.py tests/unit/test_types_clinical_impression.py
git commit -m "$(cat <<'EOF'
feat(types): add Allergy + NarrativeContext + ClinicalImpressionRecord CIF types + replace legacy Allergy

Tier 1 #3 α-min-1 Document Density Chain foundation:
- Allergy + AllergyReaction (clinosim/types/allergy.py) — 8-field SNOMED-coded
  schema, replaces legacy 3-field (substance/reaction_type/severity) in
  clinosim/types/patient.py:85 (pre-flight verification: legacy emits 15.3%
  prevalence but JP-Core / US-Core unconformant)
- NarrativeContext + NarrativeOutput + DocumentType + FormatType
  (clinosim/types/document.py) — 統一 narrative generator interface
- ClinicalImpressionRecord (extends clinosim/types/clinical.py)
- PatientProfile.allergies: list[Allergy] type hint upgraded to new schema
- activator.py:201 Allergy() call mapped to new schema (機能不変、Task 15 で
  enricher に migrate して activator から切り離す)
- test_patient.py fixture migrated to new Allergy schema

DocumentType enum α-min-1 scope: ADMISSION_HP + PROGRESS_NOTE +
DISCHARGE_SUMMARY only (後続 phase で拡張、本 chain で追加禁止 = scope
discipline)。

NarrativeContext.facts_used で使用 CIF field を tracking、audit + LLM
hallucination 防御の foundation。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CcmzXRy4w3YQt9jxi5QYom
EOF
)"
```

---

## Task 2: Allergy module + allergens.yaml + sampling

**Files:**
- Create: `clinosim/modules/allergy/__init__.py`
- Create: `clinosim/modules/allergy/engine.py`
- Create: `clinosim/modules/allergy/README.md`
- Create: `clinosim/modules/allergy/reference_data/allergens.yaml`
- Modify: `clinosim/simulator/seeding.py`(add `ENRICHER_SEED_OFFSETS["allergy"]`)
- Modify: `clinosim/simulator/enrichers.py`(register allergy enricher at POST_POPULATION)
- Modify: `clinosim/codes/data/snomed-ct.yaml`(add allergen + reaction SNOMED entries)
- Test: `tests/unit/modules/allergy/__init__.py`(empty)
- Test: `tests/unit/modules/allergy/test_engine.py`
- Test: `tests/unit/modules/allergy/test_allergens_yaml.py`

**Interfaces:**
- Consumes: `Allergy` from Task 1
- Produces:
  - `clinosim.modules.allergy.engine.load_allergens() -> dict` (`@lru_cache(maxsize=1)`)
  - `clinosim.modules.allergy.engine.allergy_enricher(ctx: EnricherContext) -> None`(POST_POPULATION)
  - `clinosim.modules.allergy.engine.SUPPORTED_ALLERGEN_CATEGORIES = frozenset({"medication", "food", "environment"})`

- [ ] **Step 1: Write failing test**

`tests/unit/modules/allergy/test_engine.py`:

```python
"""Unit tests for allergy enricher(Tier 1 #3 α-min-1 PR1)."""

from __future__ import annotations

from types import SimpleNamespace

from clinosim.modules.allergy.engine import allergy_enricher, load_allergens


def _make_ctx(patients, master_seed=42):
    return SimpleNamespace(
        master_seed=master_seed,
        population=SimpleNamespace(patients=patients),
        records=[],
        config=SimpleNamespace(modules=SimpleNamespace()),
    )


def test_load_allergens_returns_3_categories():
    a = load_allergens()
    assert "medication" in a
    assert "food" in a
    assert "environment" in a


def test_medication_allergen_has_penicillin():
    a = load_allergens()
    med = a["medication"]
    pen = [e for e in med if e["allergen_display_en"] == "Penicillin"]
    assert pen
    assert pen[0]["allergen_code"] == "387207008"


def test_enricher_populates_allergies_per_patient():
    p1 = SimpleNamespace(patient_id="pt1", age=45, sex="F", allergies=[])
    p2 = SimpleNamespace(patient_id="pt2", age=30, sex="M", allergies=[])
    ctx = _make_ctx([p1, p2])
    allergy_enricher(ctx)
    # Determinism: 同 seed で同結果(prevalence-driven sampling、人によって 0 件もありうる)
    assert hasattr(p1, "allergies")
    assert hasattr(p2, "allergies")


def test_enricher_deterministic_same_seed():
    p1a = SimpleNamespace(patient_id="pt1", age=45, sex="F", allergies=[])
    p1b = SimpleNamespace(patient_id="pt1", age=45, sex="F", allergies=[])
    allergy_enricher(_make_ctx([p1a], master_seed=42))
    allergy_enricher(_make_ctx([p1b], master_seed=42))
    assert len(p1a.allergies) == len(p1b.allergies)
    if p1a.allergies:
        assert p1a.allergies[0].allergen_code == p1b.allergies[0].allergen_code
```

`tests/unit/modules/allergy/test_allergens_yaml.py`:

```python
"""YAML validator tests for allergens.yaml."""

from __future__ import annotations

from clinosim.modules.allergy.engine import load_allergens


def test_allergens_yaml_loads():
    a = load_allergens()
    assert isinstance(a, dict)


def test_each_entry_has_required_fields():
    a = load_allergens()
    for category, entries in a.items():
        for e in entries:
            assert "allergen_code" in e
            assert "allergen_display_en" in e
            assert "allergen_display_ja" in e
            assert "prevalence" in e


def test_cached_lru():
    """@lru_cache(maxsize=1) — 2 calls same object."""
    assert load_allergens() is load_allergens()
```

- [ ] **Step 2: Run test to verify failure**

```
pytest tests/unit/modules/allergy/ -v
```

Expected: FAIL — module not exists.

- [ ] **Step 3: Create `clinosim/modules/allergy/__init__.py`**

```python
"""Allergy module(Tier 1 #3 α-min-1 always-on Module, AD-55 Base).

Patient allergy sampling、PatientProfile.allergies に populate。
POST_POPULATION enricher、age/sex-driven prevalence sampling。
"""

from __future__ import annotations

from clinosim.types.allergy import Allergy, AllergyReaction

__all__ = ["Allergy", "AllergyReaction"]
```

- [ ] **Step 4: Create `clinosim/modules/allergy/reference_data/allergens.yaml`**

★ **Prevalence calibration**(pre-flight verification 反映):baseline(activator path)= 24,763 patients 中 3,781 件 = **15.3% prevalence at patient level**。Task 13 DQR で同等を gate(±0.05 = 10.3% 〜 20.3%)。Plan Step 5 sampling rule で **two-stage**:(1)patient-level overall prevalence gate = 15% bernoulli、(2)gate 成立した patient のみで category-weighted sampling。

Sampling formula(Step 5 で実装):
```
overall_prob = 0.15   # baseline 一致
if rng.random() >= overall_prob: return []   # 85% は no allergy
# 15% の patient のみ:category-weighted single-allergy(将来 multi-allergy へ拡張可)
category = rng.choice(["medication", "food", "environment"],
                      p=[0.50, 0.25, 0.25])
entry = rng.choice(allergens[category])  # uniform within category
```

YAML 内 `prevalence.adult` field は documentation 目的(category-level base rate 参考)、actual sampling は overall_prob で gate される設計。Implementer subagent は本 calibration を verify(US p=500 cohort test で 14-17% 範囲を assertion)。

```yaml
# Allergen catalog(PR1 scope = medication + food + environment 3 category)
# Each entry: allergen_code(SNOMED) + display + prevalence(age-group reference)+ reactions
# Sampling: 15% patient overall_prob gate → category-weighted single allergy
# 6-layer validator は engine.py で適用

allergens:
  medication:
    - allergen_code: "387207008"
      allergen_display_en: "Penicillin"
      allergen_display_ja: "ペニシリン"
      prevalence:
        adult: 0.08              # 8% population
      criticality: high
      common_reactions:
        - manifestation_snomed: "247472004"
          manifestation_display_en: "Rash"
          manifestation_display_ja: "発疹"
          severity: mild
        - manifestation_snomed: "39579001"
          manifestation_display_en: "Anaphylaxis"
          manifestation_display_ja: "アナフィラキシー"
          severity: severe
    - allergen_code: "372687004"
      allergen_display_en: "Aspirin"
      allergen_display_ja: "アスピリン"
      prevalence:
        adult: 0.03
      criticality: low
      common_reactions:
        - manifestation_snomed: "247472004"
          manifestation_display_en: "Rash"
          manifestation_display_ja: "発疹"
          severity: mild
    - allergen_code: "303408005"
      allergen_display_en: "Sulfa drugs"
      allergen_display_ja: "サルファ剤"
      prevalence:
        adult: 0.03
      criticality: high
      common_reactions:
        - manifestation_snomed: "247472004"
          manifestation_display_en: "Rash"
          manifestation_display_ja: "発疹"
          severity: moderate

  food:
    - allergen_code: "227037002"
      allergen_display_en: "Eggs"
      allergen_display_ja: "卵"
      prevalence:
        adult: 0.02
      criticality: low
      common_reactions:
        - manifestation_snomed: "247472004"
          manifestation_display_en: "Rash"
          manifestation_display_ja: "発疹"
          severity: mild
    - allergen_code: "256349002"
      allergen_display_en: "Wheat"
      allergen_display_ja: "小麦"
      prevalence:
        adult: 0.01
      criticality: low
      common_reactions:
        - manifestation_snomed: "21522001"
          manifestation_display_en: "Abdominal pain"
          manifestation_display_ja: "腹痛"
          severity: mild

  environment:
    - allergen_code: "256262001"
      allergen_display_en: "Pollen"
      allergen_display_ja: "花粉"
      prevalence:
        adult: 0.20             # 20% — 高頻度
      criticality: low
      common_reactions:
        - manifestation_snomed: "21719001"
          manifestation_display_en: "Allergic rhinitis"
          manifestation_display_ja: "アレルギー性鼻炎"
          severity: mild
    - allergen_code: "260219005"
      allergen_display_en: "House dust mite"
      allergen_display_ja: "ハウスダスト・ダニ"
      prevalence:
        adult: 0.15
      criticality: low
      common_reactions:
        - manifestation_snomed: "21719001"
          manifestation_display_en: "Allergic rhinitis"
          manifestation_display_ja: "アレルギー性鼻炎"
          severity: mild
```

- [ ] **Step 5: Create `clinosim/modules/allergy/engine.py`**

```python
"""Allergy module engine(Tier 1 #3 α-min-1 PR1).

Loader + validator(silent-no-op defense)+ POST_POPULATION enricher。
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed
from clinosim.types.allergy import Allergy, AllergyReaction

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"

SUPPORTED_ALLERGEN_CATEGORIES: frozenset[str] = frozenset(
    {"medication", "food", "environment"}
)


def _validate_allergens(data: dict[str, Any]) -> None:
    """Fail-loud validation of allergens.yaml(silent-no-op defense Layer 3-6)."""
    if not data:
        raise ValueError("allergens.yaml: empty top-level")
    allergens = data.get("allergens")
    if not allergens or not isinstance(allergens, dict):
        raise ValueError("allergens.yaml: missing or empty 'allergens' key")
    yaml_keys = set(allergens.keys())
    if yaml_keys != set(SUPPORTED_ALLERGEN_CATEGORIES):
        missing = SUPPORTED_ALLERGEN_CATEGORIES - yaml_keys
        extra = yaml_keys - SUPPORTED_ALLERGEN_CATEGORIES
        raise ValueError(
            f"allergens.yaml ↔ SUPPORTED_ALLERGEN_CATEGORIES drift: "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )
    required_entry_fields = (
        "allergen_code", "allergen_display_en", "allergen_display_ja",
        "prevalence", "criticality", "common_reactions",
    )
    for cat, entries in allergens.items():
        if not entries or not isinstance(entries, list):
            raise ValueError(f"allergens.yaml[{cat}]: empty list")
        for i, e in enumerate(entries):
            for f in required_entry_fields:
                if f not in e:
                    raise ValueError(
                        f"allergens.yaml[{cat}][{i}]: missing {f}"
                    )
            prev = e["prevalence"]
            if not isinstance(prev, dict) or "adult" not in prev:
                raise ValueError(
                    f"allergens.yaml[{cat}][{i}].prevalence: must have 'adult' key"
                )
            if not isinstance(prev["adult"], (int, float)) or not (0 <= prev["adult"] <= 1):
                raise ValueError(
                    f"allergens.yaml[{cat}][{i}].prevalence.adult: 0..1 expected"
                )


@lru_cache(maxsize=1)
def load_allergens() -> dict[str, Any]:
    """Load allergens.yaml + validate. Cached singleton."""
    with (_REF_DIR / "allergens.yaml").open() as f:
        data = yaml.safe_load(f)
    _validate_allergens(data)
    return data["allergens"]


OVERALL_ALLERGY_PREVALENCE = 0.15   # baseline calibrated(see Step 4 prevalence calibration)
CATEGORY_WEIGHTS = {"medication": 0.50, "food": 0.25, "environment": 0.25}


def allergy_enricher(ctx) -> None:
    """POST_POPULATION enricher: sample allergies per patient.

    Determinism via derive_sub_seed(master, ENRICHER_SEED_OFFSETS["allergy"],
    patient_id)。Master stream 不変。

    Sampling rule(α-min-1 baseline-calibrated):
      1. patient-level overall prob gate (15%、activator baseline 一致)
      2. gate 成立 patient のみ category-weighted single allergy(後続 phase で
         multi-allergy に拡張可)
    """
    allergens = load_allergens()
    categories = list(CATEGORY_WEIGHTS.keys())
    weights = [CATEGORY_WEIGHTS[c] for c in categories]
    for patient in ctx.population.patients:
        sub_seed = derive_sub_seed(
            ctx.master_seed, ENRICHER_SEED_OFFSETS["allergy"], patient.patient_id
        )
        rng = np.random.default_rng(sub_seed)
        if rng.random() >= OVERALL_ALLERGY_PREVALENCE:
            patient.allergies = []   # 85% は no allergy
            continue
        category = str(rng.choice(categories, p=weights))
        entries = allergens[category]
        entry = entries[int(rng.integers(0, len(entries)))]
        reaction_entry = entry["common_reactions"][0]
        patient.allergies = [Allergy(
            allergy_id=f"al-{patient.patient_id}-1",
            allergen_code=entry["allergen_code"],
            allergen_display=entry["allergen_display_en"],
            category=category,
            criticality=entry["criticality"],
            verification_status="confirmed",
            onset_date=None,
            reactions=[AllergyReaction(
                manifestation_snomed=reaction_entry["manifestation_snomed"],
                manifestation_display=reaction_entry["manifestation_display_en"],
                severity=reaction_entry["severity"],
            )],
        )]
```

- [ ] **Step 6: Add `ENRICHER_SEED_OFFSETS["allergy"]` to seeding.py**

In `clinosim/simulator/seeding.py:ENRICHER_SEED_OFFSETS` dict:

```python
ENRICHER_SEED_OFFSETS = {
    "identity": 540054,
    # ... 既存 entries ...
    "imaging": 0x4947,  # "IG"
    "allergy": 0x414C,  # "AL" — Tier 1 #3 α-min-1
}
```

Module-level assert で no duplicates 確認。

- [ ] **Step 7: Register allergy enricher in `clinosim/simulator/enrichers.py`**

Add in `register_builtin_enrichers()`:

```python
from clinosim.modules.allergy.engine import allergy_enricher

register_enricher(Enricher(
    name="allergy",
    stage=POST_POPULATION,
    order=10,
    run=allergy_enricher,
    enabled=lambda config: True,    # always-on Base
))
```

- [ ] **Step 8: Add allergen + reaction SNOMED codes to snomed-ct.yaml**

Read existing `clinosim/codes/data/snomed-ct.yaml`、append entries for:
- 387207008 Penicillin / ペニシリン
- 372687004 Aspirin / アスピリン
- 303408005 Sulfa drugs / サルファ剤
- 227037002 Eggs / 卵
- 256349002 Wheat / 小麦
- 256262001 Pollen / 花粉
- 260219005 House dust mite / ハウスダスト
- 247472004 Rash / 発疹
- 39579001 Anaphylaxis / アナフィラキシー
- 21719001 Allergic rhinitis / アレルギー性鼻炎
- 21522001 Abdominal pain / 腹痛

Each entry has `en:` + `ja:`(verify NLM RxNav / tx.fhir.org $lookup for canonical text)。

- [ ] **Step 9: Create `clinosim/modules/allergy/README.md`**

```markdown
# allergy module

## 役割

Tier 1 #3 α-min-1 always-on Module(AD-55 Base)。`PatientProfile.allergies`
を populate(POST_POPULATION enricher、age-driven prevalence sampling)。

## Dependencies

- `clinosim/types/allergy.py` — `Allergy` + `AllergyReaction` dataclass
- `clinosim/simulator/seeding.py` — `ENRICHER_SEED_OFFSETS["allergy"] = 0x414C`

## Reference data

- `reference_data/allergens.yaml` — 3 category(medication / food / environment)allergen catalog with prevalence + criticality + common reactions

## Consumers

- `clinosim/modules/output/_fhir_allergy_intolerance.py` — AllergyIntolerance FHIR resource
- `clinosim/modules/document/` — NarrativeContext.allergies に渡し、narrative 内で言及

## 関連

- Spec: `docs/superpowers/specs/2026-07-01-tier1-3-document-density-alpha-min-1-design.md`
- Master plan: `docs/design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md`
```

- [ ] **Step 10: Run tests**

```
pytest tests/unit/modules/allergy/ tests/unit/test_types_allergy.py -v
```

Expected: all pass.

- [ ] **Step 11: Commit**

```
git add clinosim/modules/allergy/ clinosim/simulator/seeding.py clinosim/simulator/enrichers.py clinosim/codes/data/snomed-ct.yaml tests/unit/modules/allergy/
git commit -m "$(cat <<'EOF'
feat(allergy): new AD-55 Base module + allergens.yaml + POST_POPULATION enricher

Tier 1 #3 α-min-1 PR1 Task 2:
- allergy module skeleton + engine.py(loader + validator + enricher)
- allergens.yaml(3 category × 8 entries with prevalence + criticality +
  common reactions)— canonical authoritative SNOMED CT codes
- ENRICHER_SEED_OFFSETS["allergy"] = 0x414C("AL")
- POST_POPULATION enricher order=10、bernoulli sampling per (patient,
  allergen) with master stream isolation
- 11 new SNOMED entries to snomed-ct.yaml(allergens + reactions、verified)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CcmzXRy4w3YQt9jxi5QYom
EOF
)"
```

---

## Task 3: Document module skeleton + NarrativeContext factory + DocumentTypeSpec registry

**Files:**
- Create: `clinosim/modules/document/__init__.py`
- Create: `clinosim/modules/document/narrative/__init__.py`
- Create: `clinosim/modules/document/narrative/context.py`
- Create: `clinosim/modules/document/narrative/registry.py`
- Create: `clinosim/modules/document/reference_data/document_type_specs.yaml`
- Create: `clinosim/modules/document/README.md`
- Modify: `clinosim/simulator/seeding.py`(add `ENRICHER_SEED_OFFSETS["document"]`)
- Test: `tests/unit/modules/document/__init__.py`
- Test: `tests/unit/modules/document/narrative/__init__.py`
- Test: `tests/unit/modules/document/narrative/test_context.py`
- Test: `tests/unit/modules/document/narrative/test_registry.py`

**Interfaces:**
- Consumes: `NarrativeContext`、`DocumentType`、`FormatType`、`PatientProfile`、`EncounterRecord`、Pydantic disease/encounter protocols
- Produces:
  - `clinosim.modules.document.narrative.context.build_narrative_context(record, encounter, document_type, day_index, ...) -> NarrativeContext`
  - `clinosim.modules.document.narrative.registry.load_document_type_specs() -> dict[DocumentType, DocumentTypeSpec]`
  - `clinosim.modules.document.narrative.registry.DocumentTypeSpec` dataclass
  - `clinosim.modules.document.narrative.registry.specs_for_country(country: str) -> list[DocumentTypeSpec]`

- [ ] **Step 1: Write failing tests**

`tests/unit/modules/document/narrative/test_context.py`:

```python
"""NarrativeContext factory tests."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from clinosim.modules.document.narrative.context import build_narrative_context
from clinosim.types.document import DocumentType
from clinosim.types.patient import PatientProfile


def _make_record():
    record = SimpleNamespace(
        patient=PatientProfile(patient_id="pt1"),
        encounters=[],
        documents=[],
        extensions={},
    )
    return record


def test_build_context_for_admission_hp():
    record = _make_record()
    encounter = SimpleNamespace(
        encounter_id="enc1",
        encounter_type=SimpleNamespace(value="inpatient"),
        admission_datetime=datetime(2026, 7, 1, 10, 0),
    )
    ctx = build_narrative_context(
        record=record,
        encounter=encounter,
        document_type=DocumentType.ADMISSION_HP,
        day_index=0,
        country="jp",
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        los_days=5,
    )
    assert ctx.document_type == DocumentType.ADMISSION_HP
    assert ctx.day_index == 0
    assert ctx.target_lang == "ja"
    assert ctx.locale == "jp"
    assert ctx.allergies == []
```

`tests/unit/modules/document/narrative/test_registry.py`:

```python
"""DocumentTypeSpec registry tests."""

from __future__ import annotations

from clinosim.modules.document.narrative.registry import (
    DocumentTypeSpec, load_document_type_specs, specs_for_country,
)
from clinosim.types.document import DocumentType, FormatType


def test_registry_covers_α_min_1_doc_types():
    specs = load_document_type_specs()
    assert DocumentType.ADMISSION_HP in specs
    assert DocumentType.PROGRESS_NOTE in specs
    assert DocumentType.DISCHARGE_SUMMARY in specs


def test_admission_hp_spec_metadata():
    specs = load_document_type_specs()
    hp = specs[DocumentType.ADMISSION_HP]
    assert hp.loinc_code == "34117-2"
    assert hp.format_type == FormatType.COMPOSITION
    assert "us" in hp.countries_supported
    assert "jp" in hp.countries_supported


def test_progress_note_is_free_text():
    specs = load_document_type_specs()
    pn = specs[DocumentType.PROGRESS_NOTE]
    assert pn.format_type == FormatType.FREE_TEXT


def test_country_gating_for_us():
    us_specs = specs_for_country("us")
    types = [s.type_key for s in us_specs]
    assert "admission_hp" in types
    assert "progress_note" in types
    assert "discharge_summary" in types
    # JP-only docs(後続 phase で追加)はこの時点では未登録、フィルタ対象なし
```

- [ ] **Step 2: Run tests to verify failure**

```
pytest tests/unit/modules/document/ -v
```

Expected: FAIL — module not exist.

- [ ] **Step 3: Create `clinosim/modules/document/__init__.py`**

```python
"""Document module(Tier 1 #3 α-min-1 always-on Module、AD-55 near-essential cascade)。

統一 narrative generation interface + ClinicalImpression daily generation。

Public exports:
- DocumentTypeSpec / load_document_type_specs / specs_for_country
- NarrativeContext / NarrativeOutput / DocumentType / FormatType(re-export from types)
"""

from __future__ import annotations

from clinosim.modules.document.narrative.registry import (
    DocumentTypeSpec,
    load_document_type_specs,
    specs_for_country,
)
from clinosim.types.document import (
    DocumentType,
    FormatType,
    NarrativeContext,
    NarrativeOutput,
)

# Canonical constants(writer-owned、readers import)
DOC_REFERENCE_ID_PREFIX = "doc-"
COMPOSITION_ID_PREFIX = "comp-"
ALLERGY_ID_PREFIX = "allergy-"
CLINICAL_IMPRESSION_ID_PREFIX = "ci-"

__all__ = [
    "DocumentType",
    "FormatType",
    "DocumentTypeSpec",
    "NarrativeContext",
    "NarrativeOutput",
    "load_document_type_specs",
    "specs_for_country",
    "DOC_REFERENCE_ID_PREFIX",
    "COMPOSITION_ID_PREFIX",
    "ALLERGY_ID_PREFIX",
    "CLINICAL_IMPRESSION_ID_PREFIX",
]
```

- [ ] **Step 4: Create `clinosim/modules/document/narrative/__init__.py`**

Empty marker.

- [ ] **Step 5: Create `clinosim/modules/document/narrative/registry.py`**

```python
"""DocumentTypeSpec registry(α-min-1 PR1)。

Source = document_type_specs.yaml。countries_supported field で locale gating
(AD-55 PR3b-1 supplement pattern)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from clinosim.types.document import DocumentType, FormatType

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE.parent / "reference_data"


@dataclass(frozen=True)
class DocumentTypeSpec:
    """Document type registry entry."""
    type_key: str
    loinc_code: str
    display_en: str
    display_ja: str
    format_type: FormatType
    countries_supported: tuple[str, ...]
    generation_frequency: str
    composition_sections: tuple[str, ...] = ()
    structured_form_yaml: str | None = None
    stage2_strategy: str = "template_only"
    llm_enabled_sections: tuple[str, ...] = ()


# α-min-1 scope = 3 doc types(本 chain では追加禁止 — scope discipline)
SUPPORTED_DOCUMENT_TYPES: frozenset[DocumentType] = frozenset({
    DocumentType.ADMISSION_HP,
    DocumentType.PROGRESS_NOTE,
    DocumentType.DISCHARGE_SUMMARY,
})


def _validate_document_type_specs(data: dict[str, Any]) -> None:
    """Fail-loud validation."""
    if not data:
        raise ValueError("document_type_specs.yaml: empty top-level")
    specs = data.get("specs")
    if not specs:
        raise ValueError("document_type_specs.yaml: missing 'specs' key")
    yaml_keys = {DocumentType(k) for k in specs.keys()}
    if yaml_keys != SUPPORTED_DOCUMENT_TYPES:
        missing = SUPPORTED_DOCUMENT_TYPES - yaml_keys
        extra = yaml_keys - SUPPORTED_DOCUMENT_TYPES
        raise ValueError(
            f"document_type_specs.yaml ↔ SUPPORTED_DOCUMENT_TYPES drift: "
            f"missing={sorted(m.value for m in missing)}, "
            f"extra={sorted(e.value for e in extra)}"
        )
    required = ("loinc_code", "display_en", "display_ja", "format_type",
                "countries_supported", "generation_frequency")
    for key, entry in specs.items():
        for f in required:
            if f not in entry:
                raise ValueError(f"document_type_specs.yaml[{key}]: missing {f}")
        if not entry["countries_supported"]:
            raise ValueError(f"document_type_specs.yaml[{key}]: countries_supported empty")


@lru_cache(maxsize=1)
def load_document_type_specs() -> dict[DocumentType, DocumentTypeSpec]:
    """Load + validate document_type_specs.yaml。Cached singleton。"""
    with (_REF_DIR / "document_type_specs.yaml").open() as f:
        data = yaml.safe_load(f)
    _validate_document_type_specs(data)
    result: dict[DocumentType, DocumentTypeSpec] = {}
    for key, entry in data["specs"].items():
        result[DocumentType(key)] = DocumentTypeSpec(
            type_key=key,
            loinc_code=entry["loinc_code"],
            display_en=entry["display_en"],
            display_ja=entry["display_ja"],
            format_type=FormatType(entry["format_type"]),
            countries_supported=tuple(entry["countries_supported"]),
            generation_frequency=entry["generation_frequency"],
            composition_sections=tuple(entry.get("composition_sections") or ()),
            structured_form_yaml=entry.get("structured_form_yaml"),
            stage2_strategy=entry.get("stage2_strategy", "template_only"),
            llm_enabled_sections=tuple(entry.get("llm_enabled_sections") or ()),
        )
    return result


def specs_for_country(country: str) -> list[DocumentTypeSpec]:
    """Locale gating: return only specs supporting given country。"""
    return [s for s in load_document_type_specs().values()
            if country.lower() in s.countries_supported]
```

- [ ] **Step 6: Create `clinosim/modules/document/reference_data/document_type_specs.yaml`**

```yaml
# DocumentTypeSpec registry source(α-min-1 scope = 3 doc types)
# 後続 phase で追加(本 chain では拡張禁止)

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
    llm_enabled_sections: []

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

- [ ] **Step 7: Create `clinosim/modules/document/narrative/context.py`**

```python
"""NarrativeContext factory(CIF → ctx)。"""

from __future__ import annotations

from typing import Any

from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.types.document import DocumentType, NarrativeContext


def build_narrative_context(
    record: Any,
    encounter: Any,
    document_type: DocumentType,
    day_index: int,
    country: str,
    disease_protocol: Any | None = None,
    encounter_protocol: Any | None = None,
    clinical_course_archetype: str = "uncomplicated_improvement",
    severity: str = "moderate",
    los_days: int = 1,
) -> NarrativeContext:
    """CIF record + encounter → NarrativeContext。

    Generator(template / LLM)は本 ctx のみ参照。Day_index で daily generation
    の段階を渡す(progress note は 0..LOS、H&P = 0、Discharge = LOS-1)。
    """
    lang = "ja" if country.lower() == "jp" else "en"
    locale = country.lower()
    patient = _o(record, "patient", None)
    allergies = _o(patient, "allergies", []) if patient else []
    return NarrativeContext(
        patient=patient,
        encounter=encounter,
        encounter_type=_o(encounter, "encounter_type", None),
        disease_protocol=disease_protocol,
        encounter_protocol=encounter_protocol,
        clinical_course_archetype=clinical_course_archetype,
        severity=severity,
        day_index=day_index,
        los_days=los_days,
        vitals=_o(record, "vital_signs", []) or [],
        lab_results=_o(record, "lab_results", []) or [],
        medications=_o(record, "medication_administrations", []) or [],
        diagnoses=_o(record, "diagnoses", []) or [],
        procedures=_o(record, "procedures", []) or [],
        allergies=allergies,
        document_type=document_type,
        target_lang=lang,
        locale=locale,
    )
```

- [ ] **Step 8: Add `ENRICHER_SEED_OFFSETS["document"]` to seeding.py**

```python
ENRICHER_SEED_OFFSETS = {
    # ... existing ...
    "allergy": 0x414C,
    "document": 0x444F,  # "DO" — Tier 1 #3 α-min-1
}
```

- [ ] **Step 9: Run tests**

```
pytest tests/unit/modules/document/ -v
```

Expected: all pass.

- [ ] **Step 10: Commit**

```
git add clinosim/modules/document/ clinosim/simulator/seeding.py tests/unit/modules/document/
git commit -m "$(cat <<'EOF'
feat(document): module skeleton + DocumentTypeSpec registry + NarrativeContext factory

Tier 1 #3 α-min-1 PR1 Task 3:
- clinosim/modules/document/ skeleton + canonical constants(DOC_REFERENCE_ID_PREFIX
  / COMPOSITION_ID_PREFIX / ALLERGY_ID_PREFIX / CLINICAL_IMPRESSION_ID_PREFIX)
- narrative/registry.py: DocumentTypeSpec + load_document_type_specs +
  specs_for_country with 6-layer YAML validation(forward + reverse coverage
  against SUPPORTED_DOCUMENT_TYPES = {ADMISSION_HP, PROGRESS_NOTE, DISCHARGE_SUMMARY})
- narrative/context.py: build_narrative_context factory(CIF → ctx)
- reference_data/document_type_specs.yaml: 3 doc type specs with countries_supported
  + stage2_strategy + composition_sections
- ENRICHER_SEED_OFFSETS["document"] = 0x444F("DO")

Scope discipline: SUPPORTED_DOCUMENT_TYPES = α-min-1 scope のみ、本 chain で
追加禁止。後続 phase で enum + YAML 拡張。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CcmzXRy4w3YQt9jxi5QYom
EOF
)"
```

---

## Task 4: Disease YAML extension(narrative.* × 30 disease + Pydantic schema)

**Files:**
- Modify: `clinosim/modules/disease/protocol.py`(Pydantic schema + ImagingOrderSpec sibling pattern)
- Modify: 30 disease YAML files at `clinosim/modules/disease/reference_data/*.yaml`
- Test: `tests/unit/modules/disease/test_narrative_yaml.py`(新)

**Interfaces:**
- Consumes: existing `DiseaseProtocol` Pydantic
- Produces:
  - `DiseaseProtocol.narrative: NarrativeSpec | None`(optional default)
  - `NarrativeSpec(hpi_template + physical_exam_findings + discharge_instructions)`
  - `course_archetypes[].daily_trajectory: dict[str, DailyTrajectoryEntry] | None`

- [ ] **Step 1: Write failing test**

`tests/unit/modules/disease/test_narrative_yaml.py`:

```python
"""Disease YAML narrative.* field tests."""

from __future__ import annotations

from clinosim.modules.disease.protocol import load_disease_protocol


def test_bacterial_pneumonia_has_narrative_block():
    p = load_disease_protocol("bacterial_pneumonia")
    assert p.narrative is not None
    assert p.narrative.hpi_template
    assert p.narrative.physical_exam_findings
    assert p.narrative.discharge_instructions


def test_bacterial_pneumonia_archetype_has_daily_trajectory():
    p = load_disease_protocol("bacterial_pneumonia")
    arch = [a for a in p.course_archetypes if a.name == "uncomplicated_improvement"]
    assert arch
    assert arch[0].daily_trajectory
    assert "day_0" in arch[0].daily_trajectory
    assert arch[0].daily_trajectory["day_0"].subjective


def test_existing_30_diseases_all_have_narrative():
    """All 30 disease YAMLs must have narrative.* block(forward coverage)."""
    import os
    disease_dir = "clinosim/modules/disease/reference_data"
    yaml_files = [f for f in os.listdir(disease_dir) if f.endswith(".yaml")]
    for yf in yaml_files:
        name = yf.replace(".yaml", "")
        p = load_disease_protocol(name)
        assert p.narrative is not None, f"{name}: narrative block missing"
```

- [ ] **Step 2: Add Pydantic schema to disease/protocol.py**

```python
from pydantic import BaseModel, Field


class PhysicalExamSystemFindings(BaseModel):
    """severity → finding 句(mild / moderate / severe / all)."""
    mild: str = ""
    moderate: str = ""
    severe: str = ""
    all: str | None = None      # severity 共通


class PhysicalExamDayFindings(BaseModel):
    """system → severity 別 finding。"""
    general: PhysicalExamSystemFindings = Field(default_factory=PhysicalExamSystemFindings)
    cardiovascular: PhysicalExamSystemFindings = Field(default_factory=PhysicalExamSystemFindings)
    respiratory: PhysicalExamSystemFindings = Field(default_factory=PhysicalExamSystemFindings)
    abdominal: str = ""
    neurological: str = ""


class HpiTemplate(BaseModel):
    onset_pattern: dict[str, str] = Field(default_factory=dict)   # mild/moderate/severe
    trigger_options: list[str] = Field(default_factory=list)


class DischargeInstructions(BaseModel):
    follow_up: dict[str, str] = Field(default_factory=dict)        # en/ja
    activity: dict[str, str] = Field(default_factory=dict)
    medications: dict[str, str] = Field(default_factory=dict)
    emergency: dict[str, str] = Field(default_factory=dict)
    diet_lifestyle: dict[str, str] = Field(default_factory=dict)


class NarrativeSpec(BaseModel):
    """Disease YAML narrative.* block(α-min-1)。"""
    hpi_template: HpiTemplate = Field(default_factory=HpiTemplate)
    physical_exam_findings: dict[str, dict[str, PhysicalExamDayFindings]] = Field(
        default_factory=dict
    )    # archetype → day_str → PhysicalExamDayFindings
    discharge_instructions: DischargeInstructions = Field(default_factory=DischargeInstructions)


class DailyTrajectoryEntry(BaseModel):
    subjective: str = ""
    objective: str = ""
    assessment: str = ""
    plan: str = ""


# Extend CourseArchetype:
class CourseArchetype(BaseModel):
    # ... existing fields ...
    daily_trajectory: dict[str, DailyTrajectoryEntry] = Field(default_factory=dict)


# Extend DiseaseProtocol:
class DiseaseProtocol(BaseModel):
    # ... existing fields ...
    narrative: NarrativeSpec | None = None
```

- [ ] **Step 3: Add `narrative:` block to each of 30 disease YAMLs**

For each disease YAML(template、30 file):

```yaml
narrative:
  hpi_template:
    onset_pattern:
      mild: "{disease-specific 句}"
      moderate: "..."
      severe: "..."
    trigger_options:
      - "..."
  physical_exam_findings:
    uncomplicated_improvement:
      day_0:
        general:
          mild: "..."
          moderate: "..."
          severe: "..."
        cardiovascular:
          all: "整、心雑音なし"
        respiratory:
          mild: "..."
          moderate: "..."
          severe: "..."
        abdominal: "平坦、軟、圧痛なし"
        neurological: "麻痺なし、項部硬直なし"
      day_3:
        # ...
  discharge_instructions:
    follow_up:
      en: "Follow up with PCP in 7-10 days."
      ja: "退院後 1-2 週間以内に外来受診をお願いします。"
    activity:
      en: "..."
      ja: "..."
    medications:
      en: "..."
      ja: "..."
    emergency:
      en: "..."
      ja: "..."
    diet_lifestyle:
      en: "..."
      ja: "..."

course_archetypes:
  - name: uncomplicated_improvement
    # ... existing fields ...
    daily_trajectory:
      day_0:
        subjective: "..."
        objective: "..."
        assessment: "..."
        plan: "..."
      day_3:
        # ...
```

★ **Fill efficiency strategy**(scope discipline 維持):
1. 30 disease 全部にまず baseline template skeleton 適用(共通 phrase)
2. 5 priority disease(bacterial_pneumonia、aspiration_pneumonia、hemorrhagic_stroke、acute_MI、heart_failure)に手動 disease-specific override
3. 残 25 disease は generic template fallback で template_generator が deterministic generate

= 全 30 disease に `narrative:` block 存在 + 5 disease は detailed、残 25 は minimum-viable で narrative emission 成立。

- [ ] **Step 4: Run test**

```
pytest tests/unit/modules/disease/test_narrative_yaml.py -v
```

Expected: 3 tests pass。

- [ ] **Step 5: Run full disease regression**

```
pytest tests/unit/modules/disease/ -v
```

Expected: all pass(既存 disease YAML test 不変)。

- [ ] **Step 6: Commit**

```
git add clinosim/modules/disease/ tests/unit/modules/disease/test_narrative_yaml.py
git commit -m "$(cat <<'EOF'
feat(disease): NarrativeSpec Pydantic + 30 disease YAML narrative.* blocks

Tier 1 #3 α-min-1 PR1 Task 4:
- DiseaseProtocol.narrative: NarrativeSpec | None(optional default、既存 disease
  not loading 不変)
- 30 disease YAML に narrative.{hpi_template, physical_exam_findings,
  discharge_instructions} 追加
- CourseArchetype.daily_trajectory: dict[day_str, DailyTrajectoryEntry]
  (SOAP-structured per day)

Fill strategy: 5 priority disease(pneumonia × 2 + stroke + MI + HF)に詳細
disease-specific values、残 25 に baseline template skeleton。template_generator
が deterministic generate するため、全 30 disease で narrative emission 成立。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CcmzXRy4w3YQt9jxi5QYom
EOF
)"
```

---

## (Plan continues — Tasks 5-14)

**The plan is intentionally split here for token efficiency.** The remaining 10 tasks(Task 5-14)follow the same SDD pattern established by Tasks 1-4 + imaging chain precedent。

### Task 5: `physical_exam_findings.yaml` + `discharge_instructions.yaml` reference data + validators(6-layer)

Standalone reference data files for disease-agnostic baselines + per-disease overrides。Pattern follows allergens.yaml(Task 2 Step 4-5)。

### Task 6: TemplateNarrativeGenerator(Stage 1 default、3 format type 対応)

`clinosim/modules/document/narrative/template_generator.py`。

Class with `generate(ctx, spec) -> NarrativeOutput`。Dispatch by `spec.format_type`:
- FREE_TEXT → `_render_free_text(ctx, spec)`
- COMPOSITION → `_render_composition_sections(ctx, spec)` (uses `spec.composition_sections`)
- QUESTIONNAIRE_RESPONSE → `_render_structured_form(ctx, spec)`(infrastructure only、α-min-1 では active 化せず)

Templates use Jinja2-like substitution with `disease_protocol.narrative.*`、`course_archetypes[archetype].daily_trajectory[day]` etc。

15+ tests covering 3 format types + JP/EN locale + disease YAML driven + missing field fallback。

### Task 7: LLMNarrativeGenerator hook + cache + replacement_strategy(default OFF)

`clinosim/modules/document/narrative/llm_generator.py` + `cache.py` + `replacement_strategy.py`。

Hook into existing `clinosim.modules.llm_service.providers`(template_seed strategy = Idea D)。Cache by `(disease+archetype+day+severity+demographics_bucket+lang)` hash(Idea E)。Default OFF via `os.environ.get("CLINOSIM_NARRATIVE_LLM")` ≠ "on"。

10+ tests covering default OFF path + opt-in path(mocked provider) + cache hit/miss + replacement strategy dispatch。

### Task 8: Document module engine.py(POST_ENCOUNTER enricher + ClinicalImpression generation)

`clinosim/modules/document/engine.py:document_enricher(ctx)`:
1. Per encounter、build `NarrativeContext` for each applicable DocumentTypeSpec(`specs_for_country(ctx.country)`)
2. Determine which docs to emit based on `generation_frequency`(`admission_once` / `daily` / `discharge_once`)
3. TemplateNarrativeGenerator generate → ClinicalDocument records
4. Generate ClinicalImpressionRecord per day(LOS-dependent)
5. Append to `record.documents` + `record.extensions["clinical_impressions"]`

Register at POST_ENCOUNTER order=95(after imaging=90)。

8 tests covering enricher invocation + ClinicalImpression daily emit + skip cancelled encounter + locale gating(JP-only docs absent in US ctx)。

### Task 9: 3 new FHIR builders(_fhir_composition + _fhir_allergy_intolerance + _fhir_clinical_impression)

`clinosim/modules/output/_fhir_composition.py`:
- `_bb_compositions(ctx) -> list[dict]` — reads `record.documents` where `format_type=COMPOSITION`
- Resource shape:type(LOINC)+ status + subject + encounter + date + author + title + section(title + text + entry)
- 15+ unit tests(dict + dataclass path、JP/EN、section coverage、basedOn refs)

`clinosim/modules/output/_fhir_allergy_intolerance.py`:
- `_bb_allergy_intolerances(ctx) -> list[dict]` — reads `record.patient.allergies`
- Resource shape:clinicalStatus + verificationStatus + category + criticality + code(SNOMED)+ patient + onsetDateTime + reaction[]
- 10+ tests

`clinosim/modules/output/_fhir_clinical_impression.py`:
- `_bb_clinical_impressions(ctx) -> list[dict]` — reads `record.extensions["clinical_impressions"]`
- Resource shape:status + subject + encounter + date + description + summary + investigation + finding + prognosis
- 10+ tests

### Task 10: `_fhir_documents.py` refactor + builder registration

Refactor existing `_fhir_documents.py` to Stage 2 default ON、document.narrative 経由で `record.documents` の FREE_TEXT format を emit。COMPOSITION format は Task 9 の `_fhir_composition.py` に dispatch(record.documents 直接読み、format_type で filter)。

Modify `clinosim/modules/output/fhir_r4_adapter.py:_BUNDLE_BUILDERS` で 3 new builder 追加。

3-5 regression tests(既存 _fhir_documents の Stage 1 stub 互換性 + 新 path 動作)。

### Task 11: AD-60 audit module + 15+ lift_firing_proof

`clinosim/modules/document/audit.py`:`document_chain` ModuleAuditSpec with:
- 8+ structural checks(ID prefix + canonical URI + ref integrity)
- 5+ clinical acceptance(per-encounter doc count + ClinicalImpression daily + allergy distribution)
- 5+ JP language checks(section.title + display + conclusion in ja)
- 15+ `lift_firing_proof` equality_checks(canonical constants + emission counts + ref integrity + 5 no-drop invariants per spec §3.4)

6+ unit tests including stub-proof self-check。

### Task 12: Integration tests + e2e golden regen + subprocess full-pipeline + JP localization + determinism

6 integration tests(pattern follows imaging chain Task 10):
- `test_document_chain.py` — end-to-end 5 resource emission
- `test_document_basedon_coverage.py` — ref integrity gate(fail-loud assert before iterate)
- `test_document_determinism.py` — AD-16 byte-identical re-run
- `test_document_snapshot.py` — AD-32 mid-encounter DISCHARGE skip
- `test_document_subprocess_fullpipeline.py` — PR-90 production dict path
- `test_document_jp_localization.py` — JP cohort CJK char verification

E2E golden regen(if existing golden affected = property-based not byte-equal、likely no regen needed per imaging chain Task 11 precedent)。

### Task 13: DQR(US 10k + JP 5k)+ 9 doc sync

DQR doc:`docs/reviews/<date>-tier1-3-document-density-alpha-min-1-dqr.md`、4-axis verification(structural / clinical integrity / JP language / silent_no_op)。

9 doc sync:
- README.md + README.ja.md: document density chain 言及 + master plan link
- MODULES.md: document + allergy module row + Dependency Tree
- DESIGN.md: AD-63 ADR(本 chain で初登場)
- docs/CONTRIBUTING-modules.md: document module を always-on Module 例
- clinosim/modules/order/README.md: 既存内容不変
- TODO.md: OOS 16+ formal entry
- CLAUDE.md: narrative DRY rule + 2 module DRY rules
- docs/design-guides/fhir-data-generation-logic.md: 3 new builder precedent

### Task 14: Final whole-branch review + PR open

Same pattern as imaging chain Task 12:
- Final test sweep
- Lint + type-check
- Verify branch commits
- Push + `gh pr create`

---

### Task 15: Generator migration — narrative_generator + document_generator + activator allergy → 新 module

**Pre-flight verification 結果反映**(Conflict #2 = B 採択):本 chain では 951 行 `clinosim/modules/output/document_generator.py` + 205 行 `clinosim/modules/output/narrative_generator.py` + `clinosim/modules/patient/activator.py:201` allergy 部分 を新 module(`clinosim/modules/document/` + `clinosim/modules/allergy/`)に migrate。`_fhir_documents.py` は Task 10 で refactor 済、本 Task では generator 側を統一。

**Files:**
- Delete: `clinosim/modules/output/narrative_generator.py`(機能を `clinosim/modules/document/narrative/` に分解 + Task 6 template_generator に統合済)
- Delete: `clinosim/modules/output/document_generator.py`(機能を `clinosim/modules/document/engine.py` に enricher 化 + Task 8 完了済)
- Modify: `clinosim/modules/patient/activator.py`(allergy 生成 5-10 行 block を削除 — Task 2 allergy_enricher が POST_POPULATION で生成)
- Modify: `clinosim/simulator/cli.py:_run_narrate`(削除済 generator path を新 module の Stage 2 hook に dispatch、または narrate subcommand 自体を deprecate して Stage 1 enricher 経由のみに統一 — implementer subagent が判断)
- Modify: `clinosim/modules/output/fhir_r4_adapter.py:225-260`(narrative_docs_dir walk path を新 module 経由に refactor。Stage 1 enricher 生成 `record.documents` を直接読む path に切替)
- Update: 既存 `tests/integration/test_narrate_*.py` + `tests/unit/test_document_generator.py` 等を新 module test に migrate or delete
- Update: `docs/CONTRIBUTING-modules.md`、`README.md` 内 `narrate` subcommand 言及を更新

**Migration strategy:**
1. **Verify equivalence first**:Task 8 完了後の `record.documents` 出力(Stage 1 template_generator 経由)が、旧 path(`narrate` subcommand → `document_generator.generate_documents`)の出力と clinical content として同等であることを確認。同等であれば旧 path は dead code として削除可。
2. **Activator allergy block deletion**:Task 1 で新 schema にマップ済、Task 2 で allergy_enricher が同 prevalence で生成可。activator 生成タイミング(population 生成内)と enricher 生成タイミング(POST_POPULATION)で差異あり = enricher pass 完了時に patient.allergies に最終値が入る。activator 側 block 削除で重複 sampling を排除。
3. **`narrate` CLI subcommand handling**:
   - Option A: subcommand 維持、Stage 2 LLM hook 経由で document module の llm_generator を再呼び出し(re-generation path)
   - Option B: subcommand deprecate、Stage 1 enricher の出力のみを使う(LLM 統合は別 chain)
   - **Implementer subagent 判断**:本 chain scope discipline 重視なら Option B(deprecate)が推奨、TODO に「Stage 2 LLM provider 統合別 chain」記載
4. **DQR equivalence**:Task 13 DQR で AllergyIntolerance 件数が baseline 15.3% (±0.05)以内、DocumentReference + Composition + ClinicalImpression 件数が plan 期待値以上(現状 0 件)を確認。

**Test plan(本 Task で追加 + 既存 test migration):**
- `tests/unit/modules/patient/test_activator.py`:既存 allergy block test を削除(allergy_enricher test に統合済)
- `tests/integration/test_allergy_baseline_equivalence.py`(NEW):activator path 削除前後で AllergyIntolerance 件数 ±0.05 同等を verify。**Pre-condition**:Task 15 開始時に master + branch 両方で US p=500 cohort 生成し件数差を計測、`<5%` 内であることを assertion。
- `tests/unit/test_narrate_cli.py`:`narrate` subcommand deprecate(Option B 採択)なら xfail or skip。Option A なら新 module hook 経由動作を verify。
- 既存 `tests/integration/test_narrative_*.py` 系:Stage 2 LLM 関連 test を新 module path に migrate。

**Commit message template:**
```
refactor(document,allergy): migrate legacy narrative_generator + document_generator + activator allergy to new modules

Tier 1 #3 α-min-1 PR1 Task 15 - generator unification:
- Delete clinosim/modules/output/narrative_generator.py (機能 → clinosim/modules/document/narrative/)
- Delete clinosim/modules/output/document_generator.py (機能 → clinosim/modules/document/engine.py enricher)
- Remove allergy generation block from clinosim/modules/patient/activator.py
  (now handled by clinosim/modules/allergy/engine.py:allergy_enricher at POST_POPULATION)
- Refactor clinosim/modules/output/fhir_r4_adapter.py to read record.documents directly
  (Stage 1 enricher 経由、narrate subcommand 経由でない)
- `narrate` CLI subcommand: <Option A: 新 module hook 経由維持 / Option B: deprecate + TODO 化>

Migration verifies AllergyIntolerance baseline 同等(15.3% ±0.05)+ Document
density 0 → expected emission per spec。CLAUDE.md "データロジック統一" 規則
遵守、1 source of truth 達成。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CcmzXRy4w3YQt9jxi5QYom
```

**Risk + Mitigation:**
- 旧 `narrate` subcommand 使用 user(downstream)が breaking change を受ける → TODO に migration guide 作成
- AllergyIntolerance count drift → integration test `test_allergy_baseline_equivalence.py` で fail-loud gate
- e2e golden 変動 → 既存 test 修正 or property-based assertion で対応(imaging chain Task 11 precedent)

---

## Plan Self-Review

**1. Spec coverage:** Each spec section maps to a task:
- Section 0-1(Purpose / Scope decisions) → all tasks
- Section 1.4(Module structure) → Tasks 2 + 3 + 6 + 7 + 8 + 9
- Section 1.5(既存資産 migration) → Task 10
- Section 2(Architecture) → Tasks 1 + 3 + 8 + 9 + 10
- Section 3(Data structures) → Tasks 1
- Section 4(Reference data + disease YAML) → Tasks 4 + 5
- Section 5(FHIR builder layer) → Tasks 9 + 10
- Section 6-8(Snapshot / Edge cases / Silent-no-op) → distributed across tasks
- Section 9(Testing) → Tasks 1, 4, 6, 7, 8, 9, 11(unit) + Task 12(integration/e2e)
- Section 10(Risks) → Mitigations distributed
- Section 11(OOS) → Task 13(TODO.md formal entry)
- Section 12(Adversarial chain) → post-PR
- Section 13(PR sequencing) → tasks 1-14 align
- Section 14(Docs sync) → Task 13
- Section 14.5(Scope discipline) → Global Constraints + all task briefs
- Section 15(References) → embedded

All sections covered ✓。

**2. Placeholder scan:** Tasks 1-4 are exhaustive with full code; Tasks 5-14 are summarized with structure outline + test count expectations。Implementer subagent will use spec §1-§15 as authoritative reference for Tasks 5-14 details。

**3. Type consistency:**
- `Allergy` / `NarrativeContext` / `NarrativeOutput` / `DocumentType` / `FormatType` / `ClinicalImpressionRecord` defined Task 1 → consumed Tasks 2, 3, 6-11 ✓
- `DocumentTypeSpec` defined Task 3 → consumed Tasks 6, 8, 11 ✓
- Canonical constants `DOC_REFERENCE_ID_PREFIX` / `COMPOSITION_ID_PREFIX` / `ALLERGY_ID_PREFIX` / `CLINICAL_IMPRESSION_ID_PREFIX` defined Task 3 `__init__.py` → consumed Tasks 9, 10, 11 ✓
- `ENRICHER_SEED_OFFSETS["allergy"] = 0x414C` + `["document"] = 0x444F` defined Tasks 2, 3 → consumed Tasks 2, 8 ✓
- `SUPPORTED_DOCUMENT_TYPES` / `SUPPORTED_ALLERGEN_CATEGORIES` defined Tasks 2, 3 → validators consumed ✓

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-01-tier1-3-document-density-alpha-min-1-plan.md`。

**Next session 26** で execution:

1. PR #127 imaging chain merge(user)
2. Branch creation:`git checkout -b feature/tier1-document-density-alpha-min-1` from updated master
3. SDD execution(superpowers:subagent-driven-development):15 task chain(Task 15 = generator migration、pre-flight verification 反映)
4. 5-lens adversarial fan-out
5. PR open

**Master plan reference**(全体 7 phase コンテキスト):
`docs/design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md`

**Scope discipline reminder**(memory `feedback_scope_discipline`):
Implementation 中、新 finding は data quality / clinical integrity 必須のみ scope 内 fix、それ以外 TODO entry 化。
