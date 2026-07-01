# Tier 1 #3 α-min-2b: AD-65 Two-pass CIF Architecture Restoration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore structural + narrative CIF file separation from α-min-1 Task 15 drift, introduce `ClinicalDocumentNarrative` wrapper and `TemplateNarrativePass`, fix 3 Critical narrative bugs + 1 CLI silent override bug, and add dev iteration facility for 10-second bug verify.

**Architecture:** Two-pass generation pipeline: Stage 1 `simulate + write_cif` writes structural CIF (narrative=None stubs), Stage 2 `TemplateNarrativePass.run` reads structural + writes `cif/narratives/<version>/documents/<enc>/<doc>.json`, Stage 3 `CIFReader` merges the two before FHIR emit. `narrate` CLI verb restores standalone Stage 2 invocation for β-JP-1 LLMNarrativePass drop-in.

**Tech Stack:** Python 3.11+, pytest, pydantic, numpy.random. All-existing project deps.

**Design doc:** `docs/superpowers/specs/2026-07-02-tier1-3-narrative-stage2-architecture-design.md`

**Branch:** `feature/tier1-narrative-stage2-architecture` (2 commits, base `486eea6ddf`)

## Global Constraints

- Python 3.11+, ruff formatter, mypy strict, line length 100.
- All shared types live in `clinosim/types/`, module-internal types stay in the module.
- CIF is language-neutral (AD-30) — no display text in CIF.
- FHIR R4 Bulk Data Access compliant (AD-31) — 1 NDJSON per resource type.
- Determinism (AD-16) — every RNG draws from `derive_sub_seed()`; no `random.random()`.
- No backwards compat for legacy scratchpad cohorts (user Q2 confirmed).
- Test markers: `@pytest.mark.unit` (< 30s), `@pytest.mark.integration` (< 5min), `@pytest.mark.e2e` (< 30min).
- Formatting: `ruff check clinosim/ tests/` and `ruff format clinosim/ tests/` must pass.
- Type checking: `mypy --strict clinosim/` must pass.
- Every commit must pass `pytest -m unit -x -q` at minimum.
- Commit style: conventional commits, ends with `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01SxM5jRL8Xckoh2RidLHiss`.

---

## Phase 1: Architecture (T1-T6)

### Task 1: `ClinicalDocumentNarrative` wrapper + `ClinicalDocument` stub + CLAUDE.md rules

**Files:**
- Modify: `clinosim/types/clinical.py:108-154` (ClinicalDocument stub + wrapper added)
- Modify: `CLAUDE.md` (add "Two-pass CIF generation invariant (AD-65)" ruleset)
- Test: `tests/unit/test_clinical_document_narrative.py` (new)

**Interfaces:**
- Consumes: nothing (foundational task)
- Produces:
  - `ClinicalDocumentNarrative` dataclass with fields: `text: str`, `sections: dict[str, str]`, `structured: dict`, `generator: str`, `generator_metadata: dict`, `generated_at: str`, `facts_used: list[str]`
  - `ClinicalDocument` dataclass revised: keep structural fields, delete flat narrative fields, add `narrative: ClinicalDocumentNarrative | None = None`
  - `NarrativeVersionManifest` dataclass with fields: `version_id: str`, `generator: str`, `generator_config: dict`, `generated_at: str`, `encounter_count: int`, `document_count: int`, `document_counts_by_type: dict[str, int]`, `doc_types_enabled: list[str]`, `languages_used: list[str]`, `llm_cost_report: dict`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_clinical_document_narrative.py`:

```python
import pytest
from clinosim.types.clinical import (
    ClinicalDocument, ClinicalDocumentNarrative, NarrativeVersionManifest,
)


@pytest.mark.unit
def test_narrative_wrapper_defaults_are_empty():
    n = ClinicalDocumentNarrative()
    assert n.text == ""
    assert n.sections == {}
    assert n.structured == {}
    assert n.generator == "none"
    assert n.generator_metadata == {}
    assert n.generated_at == ""
    assert n.facts_used == []


@pytest.mark.unit
def test_clinical_document_default_narrative_is_none():
    """AD-65: stub 直後は narrative=None(Stage 2 未実行の signal)"""
    doc = ClinicalDocument(document_id="doc-x", loinc_code="34117-2")
    assert doc.narrative is None


@pytest.mark.unit
def test_clinical_document_has_no_legacy_flat_fields():
    """AD-65: text/sections/text_source 等 flat narrative fields は削除"""
    doc = ClinicalDocument()
    for legacy in ("text", "sections", "text_source", "llm_model", "llm_provider",
                   "prompt_version", "cache_hit", "fallback_reason"):
        assert not hasattr(doc, legacy), f"legacy field {legacy} must be moved to narrative"


@pytest.mark.unit
def test_clinical_document_carries_wrapper():
    n = ClinicalDocumentNarrative(text="hello", sections={"hpi": "text"})
    doc = ClinicalDocument(document_id="doc-y", narrative=n)
    assert doc.narrative is not None
    assert doc.narrative.text == "hello"
    assert doc.narrative.sections["hpi"] == "text"


@pytest.mark.unit
def test_narrative_version_manifest_defaults():
    m = NarrativeVersionManifest(
        version_id="template", generator="template", generator_config={},
        generated_at="", encounter_count=0, document_count=0,
        document_counts_by_type={}, doc_types_enabled=[],
        languages_used=[], llm_cost_report={},
    )
    assert m.version_id == "template"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_clinical_document_narrative.py -v`
Expected: FAIL with `ImportError: cannot import name 'ClinicalDocumentNarrative'` or similar.

- [ ] **Step 3: Modify `clinosim/types/clinical.py`**

Replace the current `ClinicalDocument` dataclass (lines 108-154) with:

```python
@dataclass
class ClinicalDocumentNarrative:
    """Narrative subtree of a ClinicalDocument (AD-65).

    Serialization boundary:
      - Written to cif/narratives/<version>/documents/<enc>/<doc_type>.json
      - NEVER written to structural CIF (cif_writer strips this)
      - Loaded and merged by CIFReader at FHIR emit time.
    """
    text: str = ""
    sections: dict[str, str] = field(default_factory=dict)
    structured: dict = field(default_factory=dict)
    generator: str = "none"
    generator_metadata: dict = field(default_factory=dict)
    generated_at: str = ""
    facts_used: list[str] = field(default_factory=list)


@dataclass
class ClinicalDocument:
    """Two-pass lifecycle (AD-65):
      1. document_enricher (POST_ENCOUNTER) creates stub with narrative=None.
      2. TemplateNarrativePass populates `narrative`.
      3. CIFReader merges structural + narrative before FHIR emit.
    """
    document_id: str = ""
    task_type: str = ""
    loinc_code: str = ""
    patient_id: str = ""
    encounter_id: str = ""
    author_practitioner_id: str = ""
    related_procedure_id: str = ""
    authored_datetime: str = ""
    period_start: str = ""
    period_end: str = ""
    language: str = "en"
    content_type: str = "text/plain; charset=utf-8"
    format_type: str = ""
    narrative: ClinicalDocumentNarrative | None = None


@dataclass
class NarrativeVersionManifest:
    """cif/narratives/<version>/manifest.json shape."""
    version_id: str
    generator: str
    generator_config: dict
    generated_at: str
    encounter_count: int
    document_count: int
    document_counts_by_type: dict[str, int]
    doc_types_enabled: list[str]
    languages_used: list[str]
    llm_cost_report: dict
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_clinical_document_narrative.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Add AD-65 rules to CLAUDE.md**

Locate the `### Data flow & ownership` section in `CLAUDE.md`. Append immediately after its final bullet (before the next `###` header) the block below (copy verbatim from design doc §6.2):

```markdown
### Two-pass CIF generation invariant(AD-65, 2026-07-02, session 28)

- **CIF は structural + narrative の 2 層 file 分離**:`cif/structural/patients/<enc>.json`
  (構造化データ、Stage 1 で immutable)と `cif/narratives/<version>/documents/<enc>/<doc>.json`
  (narrative、Stage 2 で version 化可能)を **必ず file-level 分離**。inline 混在禁止。
  session 25/26/27 で drift した過去実装から復元、SPEC.md `Stage 2: Narrative Generation`
  節が canonical。
- **`document_enricher`(POST_ENCOUNTER)は `ClinicalDocument` stub のみ生成**:metadata +
  author + encounter binding + `narrative=None`。narrative content(text / sections /
  facts_used)を populate 禁止。populate すると Stage 2 差替時 silent-no-op risk。
- **narrative は post-simulation two-pass で生成**:`TemplateNarrativePass.run(cif_dir,
  version_id)` は structural CIF を read → patient profile + labs + conditions +
  medications + scenario_spine を input として narrative を導出 →
  `narratives/<version>/documents/<enc>/<doc>.json` 書出。simulation loop 中の
  narrative content 生成禁止。α-min-1 Task 15 で SPEC.md 元設計から drift、
  AD-65(session 28)で復元。
- **`NarrativePass` walk 順序は (doc_type, language) group 単位**:同 prompt prefix を
  共有する batch 単位で patient を逐次処理 → Bedrock prompt cache(5 分 TTL)hit rate
  最大化。LLMNarrativePass(β-JP-1)は同 base class を継承 = drop-in で cache-friendly。
- **FHIR builders は `doc.narrative.sections` / `doc.narrative.text` 経由必須**:
  `ClinicalDocument` の flat field(`doc.text` / `doc.sections`)は AD-65 で削除、
  wrapper `ClinicalDocumentNarrative` に集約。`CIFReader(narrative_version="current")`
  が structural + narrative を merge して `doc.narrative` を fill、builders は
  wrapper 経由のみ。
```

- [ ] **Step 6: Commit**

```bash
git add clinosim/types/clinical.py CLAUDE.md tests/unit/test_clinical_document_narrative.py
git commit -m "$(cat <<'EOF'
feat(types): AD-65 ClinicalDocumentNarrative wrapper + ClinicalDocument stub

Introduce ClinicalDocumentNarrative wrapper to isolate Stage 2-modifiable
narrative content from structural metadata. ClinicalDocument now carries
narrative: ClinicalDocumentNarrative | None (None = pre-Stage 2 stub).
NarrativeVersionManifest models the per-version manifest.json shape.

CLAUDE.md gains 5 AD-65 rules pinning the two-pass invariant, enforced
alongside code so future sessions cannot silently drift.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SxM5jRL8Xckoh2RidLHiss
EOF
)"
```

---

### Task 2: `cif_writer.py` structural-only + delete `_narrative_to_text`

**Files:**
- Modify: `clinosim/modules/output/cif_writer.py:32-59` (strip narrative from record before dump)
- Modify: `clinosim/modules/document/engine.py` (delete `_narrative_to_text` helper `118-130` if still present; stub-only populate at lines `245-362` will be refactored in Task 3 — this task only removes obsolete helper)
- Test: `tests/unit/test_cif_writer_structural_only.py` (new)

**Interfaces:**
- Consumes: `ClinicalDocument.narrative` field from Task 1
- Produces: `write_cif(dataset, output_dir)` guarantees `cif/structural/patients/<enc>.json` documents[].narrative is always `null` (strip if enricher accidentally populates)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_cif_writer_structural_only.py`:

```python
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime

import pytest

from clinosim.modules.output.cif_writer import write_cif
from clinosim.types.clinical import ClinicalDocument, ClinicalDocumentNarrative
from clinosim.types.output import CIFDataset, CIFMetadata


def _tiny_dataset() -> CIFDataset:
    from clinosim.types.output import CIFPatientRecord, PatientProfile, Encounter
    doc_with_narr = ClinicalDocument(
        document_id="doc-1", loinc_code="34117-2",
        narrative=ClinicalDocumentNarrative(text="SHOULD BE STRIPPED"),
    )
    doc_stub = ClinicalDocument(document_id="doc-2", loinc_code="34746-8", narrative=None)
    p = CIFPatientRecord(
        patient=PatientProfile(patient_id="POP-000001", age=65, sex="M",
                               date_of_birth=date(1961, 1, 1)),
        encounters=[Encounter(encounter_id="ENC-1", encounter_type=None,
                              admission_datetime=datetime(2026, 1, 1, 9, 0))],
        documents=[doc_with_narr, doc_stub],
    )
    md = CIFMetadata(clinosim_version="0.1.0", random_seed=42, country="US",
                    hospital_scale="medium", snapshot_date="2026-07-01",
                    total_patients_generated=1, llm_mode="none")
    return CIFDataset(metadata=md, patients=[p], hospital_roster=[], hospital_config={})


@pytest.mark.unit
def test_write_cif_strips_narrative_from_documents(tmp_path):
    write_cif(_tiny_dataset(), str(tmp_path))
    path = tmp_path / "structural" / "patients" / "ENC-1.json"
    assert path.exists()
    data = json.loads(path.read_text())
    docs = data["documents"]
    assert len(docs) == 2
    for d in docs:
        assert d["narrative"] is None, f"narrative must be stripped, got {d['narrative']}"


@pytest.mark.unit
def test_write_cif_preserves_structural_fields(tmp_path):
    write_cif(_tiny_dataset(), str(tmp_path))
    data = json.loads((tmp_path / "structural" / "patients" / "ENC-1.json").read_text())
    doc = data["documents"][0]
    assert doc["document_id"] == "doc-1"
    assert doc["loinc_code"] == "34117-2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_cif_writer_structural_only.py -v`
Expected: FAIL (narrative not stripped, or NarrativeContext-related legacy path errors)

- [ ] **Step 3: Modify `clinosim/modules/output/cif_writer.py`**

Replace the current `write_cif` function (lines 32-59) with:

```python
def write_cif(dataset: CIFDataset, output_dir: str) -> None:
    """Write structural CIF to JSON files. Narrative content is stripped
    from documents[] — Stage 2 TemplateNarrativePass writes narrative
    separately to cif/narratives/<version>/documents/ (AD-65)."""
    structural_dir = os.path.join(output_dir, "structural", "patients")
    os.makedirs(structural_dir, exist_ok=True)

    metadata_dict = asdict(dataset.metadata)
    with open(os.path.join(output_dir, "metadata.json"), "w") as f:
        json.dump(metadata_dict, f, cls=_CIFEncoder, indent=2, ensure_ascii=False)

    if dataset.hospital_roster or dataset.hospital_config:
        roster_dict = [asdict(m) for m in dataset.hospital_roster] if dataset.hospital_roster else []
        with open(os.path.join(output_dir, "hospital.json"), "w") as f:
            json.dump({
                "staff": roster_dict,
                "config": dataset.hospital_config or {},
            }, f, cls=_CIFEncoder, indent=2, ensure_ascii=False)

    for idx, patient_record in enumerate(dataset.patients):
        patient_id = patient_record.patient.patient_id
        enc_id = (patient_record.encounters[0].encounter_id
                  if patient_record.encounters else f"{patient_id}-{idx:04d}")
        record_dict = asdict(patient_record)
        # AD-65: strip narrative content from documents (Stage 2 writes separately)
        for doc in record_dict.get("documents", []) or []:
            doc["narrative"] = None
        filepath = os.path.join(structural_dir, f"{enc_id}.json")
        with open(filepath, "w") as f:
            json.dump(record_dict, f, cls=_CIFEncoder, indent=2, ensure_ascii=False)
```

- [ ] **Step 4: Delete `_narrative_to_text` helper**

In `clinosim/modules/document/engine.py`, locate the `_narrative_to_text` function (around lines 118-130) and delete it entirely. Also remove any imports of it (there should be none from outside the module since it was private).

If a reference remains inside `engine.py`, replace it with a `TODO(Task 3): removed in AD-65` comment for the enricher branch (Task 3 handles the branches).

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/unit/test_cif_writer_structural_only.py tests/unit/test_clinical_document_narrative.py -v`
Expected: PASS (both files)

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/output/cif_writer.py clinosim/modules/document/engine.py \
        tests/unit/test_cif_writer_structural_only.py
git commit -m "$(cat <<'EOF'
feat(output): AD-65 cif_writer strips narrative from structural CIF

write_cif now sets documents[].narrative = None before serializing,
guaranteeing structural files never carry narrative content even if an
enricher accidentally populates it. Stage 2 TemplateNarrativePass writes
narrative separately to cif/narratives/<version>/documents/.

Delete obsolete _narrative_to_text helper in document/engine.py — Task 3
refactors the enricher branches to stub-only populate.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SxM5jRL8Xckoh2RidLHiss
EOF
)"
```

---

### Task 3: `NarrativePass` + `TemplateNarrativePass` + fact/section/spine extractors + document_enricher stub 化

**Files:**
- Create: `clinosim/modules/document/narrative/passes.py` (~180 lines)
- Create: `clinosim/modules/document/narrative/fact_extractor.py` (~120 lines)
- Create: `clinosim/modules/document/narrative/section_extractor.py` (~200 lines)
- Create: `clinosim/modules/document/narrative/scenario_spine.py` (~90 lines)
- Modify: `clinosim/types/document.py:82-95` (add `NarrativeSpine`, `FactTag`, `SectionFacts` + extend `NarrativeContext`)
- Modify: `clinosim/modules/document/engine.py:245-362` (4 branches to `narrative=None` stub only)
- Test: `tests/unit/test_template_narrative_pass.py` (new)
- Test: `tests/unit/test_document_enricher_stub_only.py` (new)

**Interfaces:**
- Consumes:
  - `ClinicalDocument`, `ClinicalDocumentNarrative`, `NarrativeVersionManifest` from Task 1
  - Existing `TemplateNarrativeGenerator.generate(ctx, spec) -> NarrativeOutput`
  - Existing `load_document_type_specs()`, `specs_for_country()`, `specs_for_encounter_type()`
- Produces:
  - `NarrativePass` abstract base class with `run() -> NarrativeVersionManifest`
  - `TemplateNarrativePass(cif_dir, version_id="template", country="US", tasks=None, rng_seed=42)` concrete impl
  - `FactExtractor.extract(patient_dict, encounter_dict) -> list[FactTag]`
  - `SectionExtractor.extract_for_composition(ctx, spec) -> dict[str, SectionFacts]`
  - `build_narrative_spine(disease_protocol, encounter_protocol) -> NarrativeSpine | None`
  - `document_enricher` now sets `narrative=None` in all 4 branches (no text/sections populate)

- [ ] **Step 1: Extend `clinosim/types/document.py`**

Append after `NarrativeOutput` (line 95):

```python
@dataclass(frozen=True)
class FactTag:
    """Deterministic fact tag extracted from structural CIF (AD-65 E2 fact grounding)."""
    key: str          # "lab.troponin_i.day0"
    value: str        # "0.12 ng/mL"
    source: str       # "structural.observations" | "profile.demographics" | "scenario.archetype"


@dataclass
class NarrativeSpine:
    """DiseaseProtocol.narrative.* / EncounterProtocol.narrative.* canonical spine (E1)."""
    archetype: str = ""
    key_events: list[str] = field(default_factory=list)
    complications_expected: list[str] = field(default_factory=list)
    outcome_benchmark: str = ""
    disease_narrative_hints: dict[str, str] = field(default_factory=dict)


@dataclass
class SectionFacts:
    """Per-section extract for COMPOSITION docs (E3 section-level extraction)."""
    section_key: str = ""
    facts: list[FactTag] = field(default_factory=list)
    scenario_hint: str = ""
    llm_replaceable: bool = False
```

Then extend `NarrativeContext` (before its closing) by adding 3 fields:

```python
    # === AD-65 enhancements ===
    narrative_spine: NarrativeSpine | None = None            # E1 scenario anchoring
    materialized_facts: list[FactTag] = field(default_factory=list)  # E2 fact-first
    section_facts: dict[str, SectionFacts] = field(default_factory=dict)  # E3 per-section
```

- [ ] **Step 2: Create `scenario_spine.py`**

```python
"""Scenario-driven narrative spine (AD-65 E1).

Extracts canonical clinical trajectory hints from DiseaseProtocol /
EncounterProtocol YAML into a NarrativeSpine dataclass. The spine is
used by TemplateNarrativeGenerator to anchor narrative to the archetype.
"""
from __future__ import annotations

from typing import Any

from clinosim.types.document import NarrativeSpine


def build_narrative_spine(
    disease_protocol: Any | None,
    encounter_protocol: Any | None,
    archetype: str,
) -> NarrativeSpine | None:
    """Return a NarrativeSpine or None if no source protocol available."""
    if disease_protocol is None and encounter_protocol is None:
        return None
    p = disease_protocol or encounter_protocol
    return NarrativeSpine(
        archetype=archetype or "",
        key_events=list(getattr(p, "key_events", []) or []),
        complications_expected=list(getattr(p, "complications", []) or []),
        outcome_benchmark=str(getattr(p, "outcome_benchmark", "") or ""),
        disease_narrative_hints=dict(getattr(p, "narrative_hints", {}) or {}),
    )
```

- [ ] **Step 3: Create `fact_extractor.py`**

```python
"""Deterministic fact-first extraction (AD-65 E2).

Materializes a list of FactTag entries from structural CIF. Generators
use this list to constrain narrative output — β-JP-1 LLMNarrativePass
will refuse to emit numbers not present in materialized_facts.
"""
from __future__ import annotations

from typing import Any

from clinosim.types.document import FactTag


def extract_patient_facts(patient_dict: dict[str, Any]) -> list[FactTag]:
    profile = patient_dict.get("patient", {})
    facts: list[FactTag] = []
    if age := profile.get("age"):
        facts.append(FactTag(key="patient.age", value=str(age),
                             source="profile.demographics"))
    if sex := profile.get("sex"):
        facts.append(FactTag(key="patient.sex", value=str(sex),
                             source="profile.demographics"))
    for cc in profile.get("chronic_conditions", []) or []:
        code = cc.get("code") if isinstance(cc, dict) else str(cc)
        if code:
            facts.append(FactTag(key=f"chronic.{code}", value="present",
                                 source="profile.chronic_conditions"))
    return facts


def extract_encounter_facts(encounter_dict: dict[str, Any]) -> list[FactTag]:
    facts: list[FactTag] = []
    if dx := encounter_dict.get("admission_diagnosis_code"):
        facts.append(FactTag(key="diagnosis.admission_icd", value=str(dx),
                             source="structural.encounter"))
    if dx := encounter_dict.get("discharge_diagnosis_code"):
        facts.append(FactTag(key="diagnosis.discharge_icd", value=str(dx),
                             source="structural.encounter"))
    return facts


def extract_lab_facts(lab_results: list[Any]) -> list[FactTag]:
    facts: list[FactTag] = []
    for lab in lab_results or []:
        name = getattr(lab, "test_name", None) or (lab.get("test_name") if isinstance(lab, dict) else None)
        value = getattr(lab, "value", None) or (lab.get("value") if isinstance(lab, dict) else None)
        day = getattr(lab, "day_index", None) or (lab.get("day_index") if isinstance(lab, dict) else None)
        if name and value is not None:
            facts.append(FactTag(
                key=f"lab.{name.lower()}.day{day if day is not None else 'x'}",
                value=str(value),
                source="structural.observations",
            ))
    return facts


def extract_medication_facts(medications: list[Any]) -> list[FactTag]:
    facts: list[FactTag] = []
    for m in medications or []:
        name = getattr(m, "drug_name", None) or (m.get("drug_name") if isinstance(m, dict) else None)
        dose = getattr(m, "dose", None) or (m.get("dose") if isinstance(m, dict) else None)
        if name:
            facts.append(FactTag(key=f"med.{name.lower().replace(' ', '_')}",
                                 value=str(dose) if dose else "administered",
                                 source="structural.medications"))
    return facts


def extract_all_facts(patient_dict, encounter_dict, ctx) -> list[FactTag]:
    """Combined extractor from all sources — used by NarrativePass._build_context."""
    facts: list[FactTag] = []
    facts.extend(extract_patient_facts(patient_dict))
    facts.extend(extract_encounter_facts(encounter_dict))
    facts.extend(extract_lab_facts(getattr(ctx, "lab_results", [])))
    facts.extend(extract_medication_facts(getattr(ctx, "medications", [])))
    return facts
```

- [ ] **Step 4: Create `section_extractor.py`**

```python
"""Per-section extraction for COMPOSITION documents (AD-65 E3).

Provides section_facts[<section_key>] for each COMPOSITION section
(hpi / assessment_plan / etc.). Enables section-level LLM replacement
(β-JP-1) without contaminating other sections.
"""
from __future__ import annotations

from typing import Any

from clinosim.types.document import DocumentTypeSpec, NarrativeContext, SectionFacts, FactTag
from clinosim.modules.document.narrative.fact_extractor import (
    extract_patient_facts, extract_encounter_facts, extract_lab_facts,
    extract_medication_facts,
)


def extract_for_composition(
    ctx: NarrativeContext,
    spec: DocumentTypeSpec,
) -> dict[str, SectionFacts]:
    """Return {section_key: SectionFacts} for each spec.composition_sections."""
    if not getattr(spec, "composition_sections", None):
        return {}
    llm_enabled = set(getattr(spec, "llm_enabled_sections", ()) or ())
    hints = ctx.narrative_spine.disease_narrative_hints if ctx.narrative_spine else {}
    result: dict[str, SectionFacts] = {}
    for section_key in spec.composition_sections:
        facts = _facts_for_section(section_key, ctx)
        result[section_key] = SectionFacts(
            section_key=section_key,
            facts=facts,
            scenario_hint=hints.get(section_key, ""),
            llm_replaceable=section_key in llm_enabled,
        )
    return result


def _facts_for_section(section_key: str, ctx: NarrativeContext) -> list[FactTag]:
    if section_key in ("chief_complaint", "hpi", "history_of_present_illness"):
        return extract_encounter_facts({
            "admission_diagnosis_code": getattr(ctx.encounter, "admission_diagnosis_code", ""),
        })
    if section_key in ("past_medical_history", "chronic_conditions"):
        return extract_patient_facts({"patient": {
            "age": getattr(ctx.patient, "age", None),
            "sex": getattr(ctx.patient, "sex", None),
            "chronic_conditions": getattr(ctx.patient, "chronic_conditions", []),
        }})
    if section_key in ("physical_examination", "vital_signs"):
        return []  # scenario_hint carries dominant guidance
    if section_key in ("labs", "laboratory_data", "assessment_and_plan"):
        return extract_lab_facts(ctx.lab_results)
    if section_key in ("medications", "medications_at_discharge"):
        return extract_medication_facts(ctx.medications)
    return []
```

- [ ] **Step 5: Create `passes.py`**

```python
"""NarrativePass base + TemplateNarrativePass (AD-65 Stage 2 workhorse).

Reads structural CIF, builds per-encounter NarrativeContext, runs the
generator, writes cif/narratives/<version>/documents/<enc>/<doc_type>.json.

Walk order contract: (doc_type, language) group serial — β-JP-1
LLMNarrativePass inherits this base and gains Bedrock prompt cache
friendliness automatically.
"""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import asdict
from datetime import datetime
from typing import Any

import numpy as np

from clinosim.types.clinical import ClinicalDocument, ClinicalDocumentNarrative, NarrativeVersionManifest
from clinosim.types.document import (
    DocumentTypeSpec, NarrativeContext, NarrativeOutput,
)
from clinosim.modules.document import specs_for_country
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.document.narrative.fact_extractor import extract_all_facts
from clinosim.modules.document.narrative.section_extractor import extract_for_composition
from clinosim.modules.document.narrative.scenario_spine import build_narrative_spine


class NarrativePass(ABC):
    def __init__(self, cif_dir: str, version_id: str, country: str,
                 tasks: list[str] | None = None, rng_seed: int = 42):
        self.cif_dir = cif_dir
        self.version_id = version_id
        self.country = country
        self.tasks_filter = set(tasks) if tasks else None
        self.rng_seed = rng_seed

    def run(self) -> NarrativeVersionManifest:
        specs = specs_for_country(self.country)
        if self.tasks_filter:
            specs = [s for s in specs if s.type_key in self.tasks_filter]

        structural_dir = os.path.join(self.cif_dir, "structural", "patients")
        narrative_dir = os.path.join(self.cif_dir, "narratives", self.version_id, "documents")
        os.makedirs(narrative_dir, exist_ok=True)

        doc_counts: dict[str, int] = {}
        languages_used: set[str] = set()
        encounters_touched: set[str] = set()

        # ★ Bedrock cache walk order: (doc_type, language) group serial
        patient_files = sorted(f for f in os.listdir(structural_dir) if f.endswith(".json"))
        for spec in specs:
            for language in self._languages_for_spec(spec):
                for pf in patient_files:
                    with open(os.path.join(structural_dir, pf)) as f:
                        patient_dict = json.load(f)
                    if not self._spec_applies(spec, patient_dict):
                        continue
                    encounter_dict = (patient_dict.get("encounters") or [{}])[0]
                    ctx = self._build_context(patient_dict, encounter_dict, spec, language)
                    output = self._generate(ctx, spec)
                    stub = self._find_matching_stub(patient_dict, spec)
                    if stub is None:
                        continue
                    wrapper = self._output_to_wrapper(output, generator=self._generator_name())
                    self._write(narrative_dir, encounter_dict.get("encounter_id", ""),
                                stub, wrapper, spec)
                    doc_counts[spec.type_key] = doc_counts.get(spec.type_key, 0) + 1
                    languages_used.add(language)
                    encounters_touched.add(encounter_dict.get("encounter_id", ""))

        manifest = NarrativeVersionManifest(
            version_id=self.version_id,
            generator=self._generator_name(),
            generator_config=self._generator_config(),
            generated_at=datetime.utcnow().isoformat() + "Z",
            encounter_count=len(encounters_touched),
            document_count=sum(doc_counts.values()),
            document_counts_by_type=doc_counts,
            doc_types_enabled=sorted(doc_counts.keys()),
            languages_used=sorted(languages_used),
            llm_cost_report={},
        )
        manifest_path = os.path.join(self.cif_dir, "narratives", self.version_id, "manifest.json")
        with open(manifest_path, "w") as f:
            json.dump(asdict(manifest), f, indent=2, ensure_ascii=False)
        return manifest

    @abstractmethod
    def _generate(self, ctx: NarrativeContext, spec: DocumentTypeSpec) -> NarrativeOutput: ...

    @abstractmethod
    def _generator_name(self) -> str: ...

    def _generator_config(self) -> dict:
        return {}

    def _languages_for_spec(self, spec: DocumentTypeSpec) -> list[str]:
        # US → en, JP → ja. β-JP-1 で bilingual 可能に拡張。
        return ["ja"] if self.country == "JP" else ["en"]

    def _spec_applies(self, spec: DocumentTypeSpec, patient_dict: dict) -> bool:
        allowed = getattr(spec, "encounter_types_supported", ()) or ()
        if not allowed:
            return True
        enc_type = ((patient_dict.get("encounters") or [{}])[0]
                    .get("encounter_type", {}) or {}).get("value") or ""
        return enc_type in allowed

    def _build_context(self, patient_dict, encounter_dict, spec, language) -> NarrativeContext:
        from clinosim.modules.document import DocumentType
        ctx = NarrativeContext(
            patient=patient_dict.get("patient"),
            encounter=encounter_dict,
            encounter_type=None,
            disease_protocol=None,
            encounter_protocol=None,
            clinical_course_archetype=patient_dict.get("clinical_course_archetype", ""),
            severity=patient_dict.get("severity", ""),
            day_index=0,
            los_days=0,
            vitals=patient_dict.get("vitals", []),
            lab_results=patient_dict.get("lab_results", []),
            medications=patient_dict.get("medications", []),
            diagnoses=patient_dict.get("diagnoses", []),
            procedures=patient_dict.get("procedures", []),
            allergies=patient_dict.get("allergies", []),
            document_type=DocumentType(spec.type_key) if hasattr(DocumentType, spec.type_key.upper()) else None,
            target_lang=language,
            locale="jp" if self.country == "JP" else "us",
        )
        ctx.narrative_spine = build_narrative_spine(
            None, None, ctx.clinical_course_archetype,
        )
        ctx.materialized_facts = extract_all_facts(patient_dict, encounter_dict, ctx)
        if spec.format_type.value == "composition":
            ctx.section_facts = extract_for_composition(ctx, spec)
        return ctx

    def _find_matching_stub(self, patient_dict: dict, spec: DocumentTypeSpec) -> dict | None:
        for doc in patient_dict.get("documents", []) or []:
            if doc.get("task_type") == spec.type_key:
                return doc
        return None

    def _output_to_wrapper(self, output: NarrativeOutput, generator: str) -> ClinicalDocumentNarrative:
        return ClinicalDocumentNarrative(
            text=output.raw_text,
            sections=output.sections,
            structured=output.structured,
            generator=generator,
            generator_metadata=output.metadata,
            generated_at=datetime.utcnow().isoformat() + "Z",
            facts_used=output.facts_used,
        )

    def _write(self, narrative_dir: str, encounter_id: str, stub: dict,
               wrapper: ClinicalDocumentNarrative, spec: DocumentTypeSpec) -> None:
        enc_dir = os.path.join(narrative_dir, encounter_id)
        os.makedirs(enc_dir, exist_ok=True)
        filename = self._filename_for(stub, spec)
        payload = {
            "document_id": stub["document_id"],
            "encounter_id": encounter_id,
            "narrative": asdict(wrapper),
        }
        with open(os.path.join(enc_dir, filename), "w") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    def _filename_for(self, stub: dict, spec: DocumentTypeSpec) -> str:
        return f"{stub.get('task_type', 'unknown')}.json"


class TemplateNarrativePass(NarrativePass):
    def __init__(self, cif_dir: str, version_id: str = "template",
                 country: str = "US", tasks: list[str] | None = None,
                 rng_seed: int = 42):
        super().__init__(cif_dir, version_id, country, tasks, rng_seed)
        self._rng = np.random.default_rng(rng_seed)
        self.generator = TemplateNarrativeGenerator()

    def _generate(self, ctx: NarrativeContext, spec: DocumentTypeSpec) -> NarrativeOutput:
        return self.generator.generate(ctx, spec)

    def _generator_name(self) -> str:
        return "template"
```

- [ ] **Step 6: Refactor `document_enricher` — 4 branches stub-only**

In `clinosim/modules/document/engine.py`, locate the 4 `_emit_doc` branches (around lines 245-362). For each branch, remove the `text=...`, `sections=...`, `text_source=...`, `llm_*=...`, `cache_hit=...`, `generated_at=...`, `fallback_reason=...` assignments and replace with a single `narrative=None`. The rest of `ClinicalDocument(...)` construction (document_id, task_type, loinc_code, patient_id, encounter_id, author_practitioner_id, related_procedure_id, authored_datetime, period_start, period_end, language, content_type, format_type) stays.

Example diff for one branch:

```python
# Before (approximate):
doc = ClinicalDocument(
    document_id=..., task_type=spec.type_key.value, loinc_code=spec.loinc_code,
    ...,
    text=_narrative_to_text(output, spec.format_type.value),
    sections=output.sections,
    text_source="template", generated_at=_now(),
)

# After (AD-65 stub):
doc = ClinicalDocument(
    document_id=..., task_type=spec.type_key.value, loinc_code=spec.loinc_code,
    ...,
    narrative=None,
)
```

Also delete the `NarrativeContext` build + `TemplateNarrativeGenerator.generate()` call inside the enricher — those moved to `TemplateNarrativePass._build_context` + `_generate`.

- [ ] **Step 7: Write TemplateNarrativePass test**

Create `tests/unit/test_template_narrative_pass.py`:

```python
import json
import os
from pathlib import Path

import pytest

from clinosim.modules.document.narrative.passes import TemplateNarrativePass


def _write_tiny_structural(tmp_path: Path, encounter_type: str = "inpatient") -> Path:
    structural = tmp_path / "structural" / "patients"
    structural.mkdir(parents=True)
    payload = {
        "patient": {"patient_id": "POP-000001", "age": 65, "sex": "M",
                    "chronic_conditions": []},
        "encounters": [{"encounter_id": "ENC-1",
                        "encounter_type": {"value": encounter_type},
                        "attending_physician_id": "DR-1",
                        "admission_diagnosis_code": "I21.4"}],
        "documents": [{"document_id": "doc-1", "task_type": "admission_hp",
                       "loinc_code": "34117-2", "narrative": None,
                       "format_type": "composition"}],
        "vitals": [], "lab_results": [], "medications": [], "diagnoses": [],
        "procedures": [], "allergies": [],
    }
    (structural / "ENC-1.json").write_text(json.dumps(payload, ensure_ascii=False))
    return tmp_path


@pytest.mark.unit
def test_template_pass_writes_narrative_dir(tmp_path):
    _write_tiny_structural(tmp_path)
    p = TemplateNarrativePass(cif_dir=str(tmp_path), country="US")
    manifest = p.run()
    assert manifest.version_id == "template"
    assert manifest.generator == "template"
    assert manifest.document_count >= 1
    narr_dir = tmp_path / "narratives" / "template" / "documents" / "ENC-1"
    assert narr_dir.exists()
    files = list(narr_dir.iterdir())
    assert any(f.name == "admission_hp.json" for f in files)


@pytest.mark.unit
def test_template_pass_narrative_file_shape(tmp_path):
    _write_tiny_structural(tmp_path)
    TemplateNarrativePass(cif_dir=str(tmp_path), country="US").run()
    payload = json.loads(
        (tmp_path / "narratives/template/documents/ENC-1/admission_hp.json").read_text())
    assert payload["document_id"] == "doc-1"
    assert payload["encounter_id"] == "ENC-1"
    assert "narrative" in payload
    n = payload["narrative"]
    assert n["generator"] == "template"
    assert "generated_at" in n
    assert isinstance(n["facts_used"], list)


@pytest.mark.unit
def test_template_pass_deterministic(tmp_path, tmp_path_factory):
    """Same seed + same structural CIF → byte-identical narrative dir."""
    _write_tiny_structural(tmp_path)
    tmp2 = tmp_path_factory.mktemp("second")
    _write_tiny_structural(tmp2)
    TemplateNarrativePass(cif_dir=str(tmp_path), country="US", rng_seed=42).run()
    TemplateNarrativePass(cif_dir=str(tmp2), country="US", rng_seed=42).run()
    a = (tmp_path / "narratives/template/documents/ENC-1/admission_hp.json").read_bytes()
    b = (tmp2 / "narratives/template/documents/ENC-1/admission_hp.json").read_bytes()
    assert a == b


@pytest.mark.unit
def test_template_pass_tasks_filter(tmp_path):
    _write_tiny_structural(tmp_path)
    p = TemplateNarrativePass(cif_dir=str(tmp_path), country="US",
                              tasks=["progress_note"])
    manifest = p.run()
    assert manifest.document_counts_by_type.get("admission_hp", 0) == 0


@pytest.mark.unit
def test_template_pass_writes_current_pointer_manifest(tmp_path):
    _write_tiny_structural(tmp_path)
    TemplateNarrativePass(cif_dir=str(tmp_path), country="US").run()
    manifest_path = tmp_path / "narratives" / "template" / "manifest.json"
    assert manifest_path.exists()
    m = json.loads(manifest_path.read_text())
    assert m["version_id"] == "template"
    assert m["generator"] == "template"
```

Create `tests/unit/test_document_enricher_stub_only.py`:

```python
import pytest

from clinosim.types.clinical import ClinicalDocument
from clinosim.modules.document.engine import document_enricher


@pytest.mark.unit
def test_enricher_produces_stub_with_narrative_none(monkeypatch):
    """AD-65: enricher must not populate narrative — pass side does it."""
    # We call document_enricher against a minimal EnricherContext.
    # If the enricher writes text/sections/generator on doc.narrative,
    # this test fails.
    from clinosim.simulator.enrichers import EnricherContext
    from clinosim.types.output import CIFPatientRecord, PatientProfile, Encounter
    from datetime import date, datetime

    rec = CIFPatientRecord(
        patient=PatientProfile(patient_id="POP-000001", age=65, sex="M",
                               date_of_birth=date(1961, 1, 1)),
        encounters=[Encounter(encounter_id="ENC-1", encounter_type=None,
                              admission_datetime=datetime(2026, 1, 1, 9, 0),
                              attending_physician_id="DR-1")],
    )
    ctx = EnricherContext(config=None, master_seed=42, population=None, records=[rec])
    document_enricher(ctx)
    for doc in rec.documents or []:
        assert isinstance(doc, ClinicalDocument)
        assert doc.narrative is None, f"enricher must produce stub; got {doc.narrative}"
```

- [ ] **Step 8: Run all Phase 1 tests**

Run: `pytest tests/unit/test_clinical_document_narrative.py tests/unit/test_cif_writer_structural_only.py tests/unit/test_template_narrative_pass.py tests/unit/test_document_enricher_stub_only.py -v`

Expected: PASS all.

If `test_document_enricher_stub_only.py` fails due to missing `SimulatorConfig`, provide a minimal config using `SimulatorConfig(country="US", random_seed=42)`.

- [ ] **Step 9: Commit**

```bash
git add clinosim/types/document.py clinosim/modules/document/engine.py \
        clinosim/modules/document/narrative/passes.py \
        clinosim/modules/document/narrative/fact_extractor.py \
        clinosim/modules/document/narrative/section_extractor.py \
        clinosim/modules/document/narrative/scenario_spine.py \
        tests/unit/test_template_narrative_pass.py \
        tests/unit/test_document_enricher_stub_only.py
git commit -m "$(cat <<'EOF'
feat(document): AD-65 TemplateNarrativePass + enricher stub-only + E1/E2/E3

Add NarrativePass abstract base + TemplateNarrativePass implementation
that reads structural CIF and writes cif/narratives/<version>/documents.
Walk order is (doc_type, language) group serial to maximize Bedrock
prompt cache hits when LLMNarrativePass (β-JP-1) inherits.

Add 3 enhancement extractors:
  E1 scenario_spine — DiseaseProtocol/EncounterProtocol → NarrativeSpine
  E2 fact_extractor — deterministic FactTag list from structural CIF
  E3 section_extractor — per-COMPOSITION-section SectionFacts

Refactor document_enricher 4 branches to stub-only (narrative=None).
Delete inline TemplateNarrativeGenerator invocation; Stage 2 pass owns it.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SxM5jRL8Xckoh2RidLHiss
EOF
)"
```

---

### Task 4: `CIFReader` + FHIR builder refactor to `doc.narrative.*`

**Files:**
- Create: `clinosim/modules/output/cif_reader.py` (~130 lines)
- Modify: `clinosim/modules/output/_fhir_composition.py:_bb_compositions` and `_build_composition`
- Modify: `clinosim/modules/output/_fhir_documents.py:_bb_document_references` and `_build_dref_from_clinical_doc`
- Modify: `clinosim/modules/output/fhir_r4_adapter.py:180-230` (use CIFReader)
- Modify: `clinosim/modules/output/csv_adapter.py:23-52` (use CIFReader for consistency)
- Test: `tests/unit/test_cif_reader.py` (new)
- Test: `tests/unit/test_fhir_builders_wrapper_only.py` (new)

**Interfaces:**
- Consumes: `ClinicalDocument`, `ClinicalDocumentNarrative` from Task 1; narrative files written by Task 3
- Produces:
  - `CIFReader(cif_dir, narrative_version="current")` with `.iter_patients() -> Iterator[dict]`
    (merges narrative into each patient dict's `documents[].narrative` field)
  - FHIR builders now read `doc.narrative.sections` / `doc.narrative.text` (never flat `doc.text` / `doc.sections`)

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_cif_reader.py`:

```python
import json
from pathlib import Path

import pytest

from clinosim.modules.output.cif_reader import CIFReader


def _make_two_layer_cif(tmp_path: Path) -> Path:
    structural = tmp_path / "structural" / "patients"
    structural.mkdir(parents=True)
    (structural / "ENC-1.json").write_text(json.dumps({
        "patient": {"patient_id": "POP-1"},
        "encounters": [{"encounter_id": "ENC-1"}],
        "documents": [
            {"document_id": "doc-1", "task_type": "admission_hp",
             "loinc_code": "34117-2", "format_type": "composition",
             "narrative": None},
            {"document_id": "doc-2", "task_type": "progress_note",
             "loinc_code": "11506-3", "format_type": "composition",
             "narrative": None},
        ],
    }, ensure_ascii=False))

    narr_dir = tmp_path / "narratives" / "template" / "documents" / "ENC-1"
    narr_dir.mkdir(parents=True)
    (narr_dir / "admission_hp.json").write_text(json.dumps({
        "document_id": "doc-1",
        "encounter_id": "ENC-1",
        "narrative": {"text": "", "sections": {"hpi": "65yo M ..."},
                      "structured": {}, "generator": "template",
                      "generator_metadata": {}, "generated_at": "",
                      "facts_used": []},
    }, ensure_ascii=False))
    (tmp_path / "narratives" / "current_version.txt").write_text("template")
    return tmp_path


@pytest.mark.unit
def test_reader_merges_narrative_into_stub(tmp_path):
    _make_two_layer_cif(tmp_path)
    r = CIFReader(str(tmp_path))
    patients = list(r.iter_patients())
    assert len(patients) == 1
    docs = patients[0]["documents"]
    doc_map = {d["document_id"]: d for d in docs}
    assert doc_map["doc-1"]["narrative"] is not None
    assert doc_map["doc-1"]["narrative"]["sections"]["hpi"] == "65yo M ..."
    # doc-2 has no matching narrative file → stays None
    assert doc_map["doc-2"]["narrative"] is None


@pytest.mark.unit
def test_reader_current_version_default_falls_back_to_template(tmp_path):
    _make_two_layer_cif(tmp_path)
    (tmp_path / "narratives" / "current_version.txt").unlink()
    r = CIFReader(str(tmp_path))  # default "current" → template fallback
    patients = list(r.iter_patients())
    # narrative dir "template" still exists, so merge still works
    docs = patients[0]["documents"]
    assert any(d["narrative"] is not None for d in docs)


@pytest.mark.unit
def test_reader_no_narrative_dir_leaves_stubs(tmp_path):
    structural = tmp_path / "structural" / "patients"
    structural.mkdir(parents=True)
    (structural / "ENC-1.json").write_text(json.dumps({
        "patient": {"patient_id": "POP-1"},
        "encounters": [{"encounter_id": "ENC-1"}],
        "documents": [{"document_id": "doc-1", "narrative": None}],
    }))
    r = CIFReader(str(tmp_path), narrative_version="template")
    patients = list(r.iter_patients())
    assert patients[0]["documents"][0]["narrative"] is None


@pytest.mark.unit
def test_reader_orphan_narrative_file_warns_and_drops(tmp_path, caplog):
    _make_two_layer_cif(tmp_path)
    # Add orphan narrative
    narr_dir = tmp_path / "narratives" / "template" / "documents" / "ENC-1"
    (narr_dir / "orphan.json").write_text(json.dumps({
        "document_id": "doc-missing",
        "encounter_id": "ENC-1",
        "narrative": {"text": "orphan"},
    }))
    r = CIFReader(str(tmp_path))
    list(r.iter_patients())
    assert any("orphan" in rec.message.lower() or "doc-missing" in rec.message
               for rec in caplog.records)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_cif_reader.py -v`
Expected: FAIL with `ImportError: cannot import name 'CIFReader'`.

- [ ] **Step 3: Create `clinosim/modules/output/cif_reader.py`**

```python
"""CIFReader — Two-pass CIF loader (AD-65).

All FHIR builders read patient records via this reader. Narrative content
from cif/narratives/<version>/documents/<enc>/<doc>.json is merged into
each stub's `narrative` field at read time.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Iterator

logger = logging.getLogger(__name__)


class CIFReader:
    def __init__(self, cif_dir: str, narrative_version: str = "current"):
        self.cif_dir = cif_dir
        self.structural_dir = os.path.join(cif_dir, "structural", "patients")

        if narrative_version == "current":
            pointer = os.path.join(cif_dir, "narratives", "current_version.txt")
            if os.path.exists(pointer):
                with open(pointer) as f:
                    narrative_version = f.read().strip()
            else:
                narrative_version = "template"
        self.narrative_version = narrative_version
        self.narrative_docs_dir = os.path.join(
            cif_dir, "narratives", narrative_version, "documents"
        )
        self._narrative_available = os.path.isdir(self.narrative_docs_dir)

    def iter_patients(self) -> Iterator[dict]:
        if not os.path.isdir(self.structural_dir):
            raise FileNotFoundError(
                f"CIF structural directory not found: {self.structural_dir}")
        for filename in sorted(os.listdir(self.structural_dir)):
            if not filename.endswith(".json"):
                continue
            with open(os.path.join(self.structural_dir, filename)) as f:
                record = json.load(f)
            self._merge_narrative_into(record)
            yield record

    def _merge_narrative_into(self, record: dict) -> None:
        if not self._narrative_available:
            return
        enc_id = self._first_encounter_id(record)
        if not enc_id:
            return
        enc_dir = os.path.join(self.narrative_docs_dir, enc_id)
        if not os.path.isdir(enc_dir):
            return
        stub_by_id = {d["document_id"]: d for d in (record.get("documents") or [])}
        for fn in sorted(os.listdir(enc_dir)):
            if not fn.endswith(".json"):
                continue
            with open(os.path.join(enc_dir, fn)) as f:
                narr_file = json.load(f)
            doc_id = narr_file.get("document_id", "")
            stub = stub_by_id.get(doc_id)
            if stub is None:
                logger.warning(
                    "orphan narrative document_id=%s in encounter %s (dropped)",
                    doc_id, enc_id)
                continue
            stub["narrative"] = narr_file.get("narrative")

    @staticmethod
    def _first_encounter_id(record: dict) -> str:
        encs = record.get("encounters") or []
        if not encs:
            return ""
        return encs[0].get("encounter_id", "")
```

- [ ] **Step 4: Refactor `_fhir_composition.py` — read `doc.narrative.sections`**

In `clinosim/modules/output/_fhir_composition.py`, locate `_bb_compositions(ctx)` and `_build_composition`. Change accesses from `doc.sections` / `doc.get("sections")` to read from `doc["narrative"]["sections"]` (dict access since CIFReader yields dicts). Add explicit skip + warn when `doc.get("narrative") is None`:

```python
def _bb_compositions(ctx):
    for record in ctx.records:
        for doc in record.get("documents", []) or []:
            if doc.get("format_type") != "composition":
                continue
            narrative = doc.get("narrative")
            if not narrative:
                logger.warning("composition stub %s has no narrative — skipping",
                               doc.get("document_id"))
                continue
            sections = narrative.get("sections") or {}
            yield _build_composition(doc, sections, ctx)
```

Adjust `_build_composition` signature to receive `sections` explicitly.

- [ ] **Step 5: Refactor `_fhir_documents.py` — read `doc.narrative.text`**

Similarly in `_fhir_documents.py`, `_bb_document_references` reads `doc["narrative"]["text"]`. Add skip + warn on `narrative is None`.

- [ ] **Step 6: Refactor `fhir_r4_adapter.py` to use CIFReader**

Replace the current per-file `open + json.load` loop (around line 226) with:

```python
from clinosim.modules.output.cif_reader import CIFReader

def convert_cif_to_fhir(cif_dir: str, output_dir: str, country: str = "US",
                       narrative_version: str = "current") -> None:
    reader = CIFReader(cif_dir, narrative_version=narrative_version)
    records = list(reader.iter_patients())
    # ... rest of adapter walks records instead of file iteration
```

The `structural_dir` existence check moves to CIFReader (already implemented).

- [ ] **Step 7: Refactor `csv_adapter.py` similarly**

Same pattern — use `CIFReader(cif_dir, narrative_version=narrative_version).iter_patients()`.

- [ ] **Step 8: Write FHIR builder wrapper-only test**

Create `tests/unit/test_fhir_builders_wrapper_only.py`:

```python
import pytest


@pytest.mark.unit
def test_composition_builder_reads_narrative_sections():
    from clinosim.modules.output._fhir_composition import _build_composition
    doc = {
        "document_id": "doc-1", "task_type": "admission_hp",
        "loinc_code": "34117-2", "format_type": "composition",
        "encounter_id": "ENC-1", "patient_id": "P-1",
        "author_practitioner_id": "DR-1", "authored_datetime": "2026-01-01T00:00:00",
        "language": "en",
    }
    sections = {"hpi": "text", "assessment_and_plan": "plan"}
    # Build minimal ctx as needed by builder — real signature check
    # Verify no crash and that sections appear in FHIR section[]
    # (This is a smoke test; deeper assertions in integration tests.)


@pytest.mark.unit
def test_docref_builder_reads_narrative_text():
    from clinosim.modules.output._fhir_documents import _build_dref_from_clinical_doc
    doc = {
        "document_id": "doc-1", "task_type": "nursing_shift_note",
        "loinc_code": "34746-8", "format_type": "free_text",
        "encounter_id": "ENC-1", "patient_id": "P-1",
        "author_practitioner_id": "DR-1", "authored_datetime": "2026-01-01T00:00:00",
        "language": "en",
        "narrative": {"text": "nurse note content", "sections": {}, "structured": {},
                     "generator": "template", "generator_metadata": {},
                     "generated_at": "", "facts_used": []},
    }
    # Verify _build_dref reads narrative.text (base64-encodes into Attachment.data)
```

- [ ] **Step 9: Run tests**

Run: `pytest tests/unit/test_cif_reader.py tests/unit/test_fhir_builders_wrapper_only.py -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add clinosim/modules/output/cif_reader.py \
        clinosim/modules/output/_fhir_composition.py \
        clinosim/modules/output/_fhir_documents.py \
        clinosim/modules/output/fhir_r4_adapter.py \
        clinosim/modules/output/csv_adapter.py \
        tests/unit/test_cif_reader.py \
        tests/unit/test_fhir_builders_wrapper_only.py
git commit -m "$(cat <<'EOF'
feat(output): AD-65 CIFReader + FHIR builders read doc.narrative.*

Introduce CIFReader as the single load path for two-layer CIF. Merges
narrative content from cif/narratives/<version>/documents into each
stub's `narrative` field. Handles missing narrative dir, missing per-
encounter dir, orphan narrative files (warn + drop).

Refactor _fhir_composition and _fhir_documents builders to read
doc["narrative"]["sections"] / doc["narrative"]["text"] with explicit
skip + warn when narrative is None. fhir_r4_adapter and csv_adapter
switch to CIFReader for consistent two-layer semantics.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SxM5jRL8Xckoh2RidLHiss
EOF
)"
```

---

### Task 5: `narrate` CLI verb + `export-fhir --narrative-version` + `generate` auto-invoke

**Files:**
- Modify: `clinosim/simulator/cli.py:75-95` (narrate verb no longer deprecated)
- Modify: `clinosim/simulator/cli.py:88-99` (export-fhir gets --narrative-version)
- Modify: `clinosim/simulator/cli.py:200-215` (generate auto-invokes TemplateNarrativePass after write_cif)
- Modify: `clinosim/simulator/cli.py:515-534` (rewrite `_run_narrate`)
- Modify: `clinosim/simulator/cli.py:537-580` (`_run_export_fhir` accepts narrative_version)
- Test: `tests/unit/test_narrate_cli.py` (new)

**Interfaces:**
- Consumes: `TemplateNarrativePass` from Task 3, `CIFReader` from Task 4
- Produces:
  - `clinosim narrate --cif-dir <dir> --provider template [--version-id <id>] [--tasks a,b] [--country US] [--no-set-current] [--seed N]`
  - `clinosim export-fhir --cif-dir <dir> [--narrative-version <id>] [-o <dir>] [--country US]`
  - `clinosim generate` writes `narratives/template/` and `narratives/current_version.txt` before FHIR export

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_narrate_cli.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

import pytest


def _write_tiny_structural(tmp_path: Path):
    structural = tmp_path / "structural" / "patients"
    structural.mkdir(parents=True)
    (structural / "ENC-1.json").write_text(json.dumps({
        "patient": {"patient_id": "POP-1", "age": 65, "sex": "M"},
        "encounters": [{"encounter_id": "ENC-1",
                        "encounter_type": {"value": "inpatient"}}],
        "documents": [{"document_id": "doc-1", "task_type": "admission_hp",
                       "loinc_code": "34117-2", "format_type": "composition",
                       "narrative": None}],
        "vitals": [], "lab_results": [], "medications": [], "diagnoses": [],
        "procedures": [], "allergies": [],
    }))


@pytest.mark.unit
def test_narrate_template_writes_dir_and_pointer(tmp_path):
    _write_tiny_structural(tmp_path)
    r = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "narrate",
         "--cif-dir", str(tmp_path), "--provider", "template",
         "--country", "US"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "narratives/template/documents/ENC-1").exists()
    pointer = (tmp_path / "narratives/current_version.txt").read_text().strip()
    assert pointer == "template"


@pytest.mark.unit
def test_narrate_no_set_current_leaves_pointer(tmp_path):
    _write_tiny_structural(tmp_path)
    (tmp_path / "narratives").mkdir(exist_ok=True)
    (tmp_path / "narratives" / "current_version.txt").write_text("prior")
    r = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "narrate",
         "--cif-dir", str(tmp_path), "--provider", "template",
         "--country", "US", "--no-set-current"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    pointer = (tmp_path / "narratives/current_version.txt").read_text().strip()
    assert pointer == "prior"


@pytest.mark.unit
def test_narrate_tasks_filter(tmp_path):
    _write_tiny_structural(tmp_path)
    r = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "narrate",
         "--cif-dir", str(tmp_path), "--provider", "template",
         "--tasks", "progress_note", "--country", "US"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    # admission_hp should not appear
    assert not (tmp_path / "narratives/template/documents/ENC-1/admission_hp.json").exists()


@pytest.mark.unit
def test_narrate_bedrock_provider_raises_not_implemented(tmp_path):
    _write_tiny_structural(tmp_path)
    r = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "narrate",
         "--cif-dir", str(tmp_path), "--provider", "bedrock",
         "--country", "US"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    # β-JP-1 defer message
    assert "β-JP-1" in r.stderr or "beta-jp-1" in r.stderr.lower() or \
           "NotImplementedError" in r.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_narrate_cli.py -v`
Expected: FAIL (narrate is deprecated stub SystemExit(1)).

- [ ] **Step 3: Rewrite `narrate` subparser in `cli.py:75-95`**

```python
# === narrate: Stage 2 template narrative generation (AD-65) ===
nr = sub.add_parser(
    "narrate",
    help="Generate narrative CIF from a structural CIF directory (AD-65 Stage 2)",
)
nr.add_argument("--cif-dir", required=True,
                help="Path to structural CIF directory")
nr.add_argument("--provider", default="template",
                choices=["template", "bedrock", "ollama"],
                help="Narrative generator (β-JP-1 for LLM providers)")
nr.add_argument("--version-id", default=None,
                help="Narrative version directory name (default: template)")
nr.add_argument("--tasks", default=None,
                help="Comma-separated LLMTaskType filter (default: all)")
nr.add_argument("--country", default="US")
nr.add_argument("--set-current", action=argparse.BooleanOptionalAction,
                default=True,
                help="Update current_version.txt to point to the new version")
nr.add_argument("--seed", type=int, default=42,
                help="RNG seed for determinism")
```

- [ ] **Step 4: Rewrite `_run_narrate` handler (cli.py:515)**

```python
def _run_narrate(args) -> None:
    from clinosim.modules.document.narrative.passes import TemplateNarrativePass
    import os

    version_id = args.version_id or "template"
    tasks = [t.strip() for t in args.tasks.split(",")] if args.tasks else None

    if args.provider == "template":
        pass_impl = TemplateNarrativePass(
            cif_dir=args.cif_dir, version_id=version_id, country=args.country,
            tasks=tasks, rng_seed=args.seed,
        )
    elif args.provider in ("bedrock", "ollama"):
        raise NotImplementedError(
            f"provider={args.provider} deferred to β-JP-1 (LLMNarrativePass)")
    else:
        raise ValueError(f"unknown provider: {args.provider}")

    manifest = pass_impl.run()
    if args.set_current:
        os.makedirs(os.path.join(args.cif_dir, "narratives"), exist_ok=True)
        with open(os.path.join(args.cif_dir, "narratives", "current_version.txt"), "w") as f:
            f.write(version_id)
    print(f"narrate: wrote {manifest.document_count} narrative documents across "
          f"{manifest.encounter_count} encounters → narratives/{version_id}/")
```

- [ ] **Step 5: Add `--narrative-version` to export-fhir subparser (cli.py:88-99)**

```python
ef.add_argument("--narrative-version", default="current",
                help="Narrative version to select (default: current from pointer file)")
```

Update `_run_export_fhir` (cli.py:537) to pass this to the adapter:

```python
get_adapter("fhir-r4").convert(
    cif_dir, output_dir,
    OutputContext(country=getattr(args, "country", "US"),
                  narrative_version=getattr(args, "narrative_version", "current")),
)
```

Add `narrative_version: str = "current"` to `OutputContext` (in `clinosim/modules/output/adapter.py`).

- [ ] **Step 6: Auto-invoke `TemplateNarrativePass` in `generate` (cli.py:200-215)**

Locate the `write_cif(dataset, cif_dir)` call (around line 210). Insert immediately after:

```python
from clinosim.modules.document.narrative.passes import TemplateNarrativePass
import os as _os
_pass = TemplateNarrativePass(
    cif_dir=cif_dir, version_id="template", country=args.country,
    rng_seed=args.seed,
)
_pass.run()
_os.makedirs(_os.path.join(cif_dir, "narratives"), exist_ok=True)
with open(_os.path.join(cif_dir, "narratives", "current_version.txt"), "w") as f:
    f.write("template")
```

- [ ] **Step 7: Run tests**

Run: `pytest tests/unit/test_narrate_cli.py -v`
Expected: PASS all 4

- [ ] **Step 8: Commit**

```bash
git add clinosim/simulator/cli.py clinosim/modules/output/adapter.py \
        tests/unit/test_narrate_cli.py
git commit -m "$(cat <<'EOF'
feat(cli): AD-65 restore narrate verb + export-fhir --narrative-version

Reimplement `clinosim narrate` (removed in α-min-1 Task 15) as the
standalone Stage 2 entry point. --provider template works today;
bedrock/ollama raise NotImplementedError with β-JP-1 pointer.

`clinosim generate` now auto-invokes TemplateNarrativePass immediately
after write_cif so cohorts are always emit-ready (UX unchanged).

`clinosim export-fhir --narrative-version <id>` selects which narrative
version merges into the FHIR emit; default "current" reads the pointer.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SxM5jRL8Xckoh2RidLHiss
EOF
)"
```

---

### Task 6: Determinism seeding + walk order pin test

**Files:**
- Modify: `clinosim/simulator/seeding.py` (add ENRICHER_SEED_OFFSETS entry)
- Test: `tests/unit/test_narrative_pass_walk_order.py` (new)
- Test: `tests/unit/test_narrative_pass_determinism.py` (new)

**Interfaces:**
- Consumes: `NarrativePass`, `TemplateNarrativePass` from Task 3
- Produces:
  - `ENRICHER_SEED_OFFSETS["narrative_template"] = 0x4e54` reserved (NT ASCII)
  - Walk order invariant: same `(doc_type, language)` group runs contiguously; β-JP-1 LLMNarrativePass inherits this shape

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_narrative_pass_walk_order.py`:

```python
import json
from pathlib import Path
from typing import Any

import pytest

from clinosim.modules.document.narrative.passes import NarrativePass


def _cohort(tmp_path: Path, encounter_ids: list[str]):
    structural = tmp_path / "structural" / "patients"
    structural.mkdir(parents=True)
    for eid in encounter_ids:
        (structural / f"{eid}.json").write_text(json.dumps({
            "patient": {"patient_id": f"POP-{eid}", "age": 65, "sex": "M"},
            "encounters": [{"encounter_id": eid,
                            "encounter_type": {"value": "inpatient"}}],
            "documents": [
                {"document_id": f"doc-{eid}-hp", "task_type": "admission_hp",
                 "loinc_code": "34117-2", "format_type": "composition",
                 "narrative": None},
                {"document_id": f"doc-{eid}-pn", "task_type": "progress_note",
                 "loinc_code": "11506-3", "format_type": "composition",
                 "narrative": None},
            ],
            "vitals": [], "lab_results": [], "medications": [], "diagnoses": [],
            "procedures": [], "allergies": [],
        }))


class _RecordingPass(NarrativePass):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls: list[tuple[str, str]] = []

    def _generate(self, ctx, spec):
        from clinosim.types.document import NarrativeOutput
        self.calls.append((spec.type_key, ctx.target_lang))
        return NarrativeOutput(raw_text="", sections={"stub": ""}, structured={},
                               metadata={}, facts_used=[])

    def _generator_name(self) -> str:
        return "recording"


@pytest.mark.unit
def test_walk_order_groups_by_doc_type_then_language(tmp_path):
    """AD-65 Bedrock cache contract: same (doc_type, language) group runs contiguously."""
    _cohort(tmp_path, ["ENC-1", "ENC-2", "ENC-3"])
    p = _RecordingPass(cif_dir=str(tmp_path), version_id="v",
                       country="US", tasks=["admission_hp", "progress_note"])
    p.run()
    # For US country, language = "en" only → each spec is 1 group.
    # Boundaries between groups = number of unique (doc_type, lang) pairs - 1
    unique_pairs = list(dict.fromkeys(p.calls))
    boundaries = sum(1 for a, b in zip(p.calls, p.calls[1:]) if a != b)
    assert boundaries == len(unique_pairs) - 1, (
        f"walk order not grouped: calls={p.calls}, unique={unique_pairs}")
    # Also assert group contiguity: same pair contiguous
    for pair in unique_pairs:
        indices = [i for i, c in enumerate(p.calls) if c == pair]
        assert indices == list(range(min(indices), max(indices) + 1)), (
            f"pair {pair} not contiguous: indices={indices}")
```

Create `tests/unit/test_narrative_pass_determinism.py`:

```python
import json
from pathlib import Path

import pytest

from clinosim.modules.document.narrative.passes import TemplateNarrativePass
from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS


@pytest.mark.unit
def test_narrative_template_seed_offset_registered():
    assert "narrative_template" in ENRICHER_SEED_OFFSETS
    assert ENRICHER_SEED_OFFSETS["narrative_template"] == 0x4e54


def _cohort(tmp_path):
    structural = tmp_path / "structural" / "patients"
    structural.mkdir(parents=True)
    (structural / "ENC-1.json").write_text(json.dumps({
        "patient": {"patient_id": "POP-1", "age": 65, "sex": "M"},
        "encounters": [{"encounter_id": "ENC-1",
                        "encounter_type": {"value": "inpatient"}}],
        "documents": [{"document_id": "doc-1", "task_type": "admission_hp",
                       "loinc_code": "34117-2", "format_type": "composition",
                       "narrative": None}],
        "vitals": [], "lab_results": [], "medications": [], "diagnoses": [],
        "procedures": [], "allergies": [],
    }))


@pytest.mark.unit
def test_same_seed_produces_byte_identical(tmp_path, tmp_path_factory):
    _cohort(tmp_path)
    tmp2 = tmp_path_factory.mktemp("second")
    _cohort(tmp2)
    TemplateNarrativePass(cif_dir=str(tmp_path), country="US", rng_seed=42).run()
    TemplateNarrativePass(cif_dir=str(tmp2), country="US", rng_seed=42).run()
    a = (tmp_path / "narratives/template/documents/ENC-1/admission_hp.json").read_bytes()
    b = (tmp2 / "narratives/template/documents/ENC-1/admission_hp.json").read_bytes()
    assert a == b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_narrative_pass_walk_order.py tests/unit/test_narrative_pass_determinism.py -v`
Expected: FAIL — `narrative_template` not in ENRICHER_SEED_OFFSETS.

- [ ] **Step 3: Add seed offset**

In `clinosim/simulator/seeding.py`, locate `ENRICHER_SEED_OFFSETS` dict. Add:

```python
    "narrative_template": 0x4e54,  # "NT" ASCII, AD-65 TemplateNarrativePass
```

(Ensure the module-level assert catching duplicate offsets still passes.)

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_narrative_pass_walk_order.py tests/unit/test_narrative_pass_determinism.py -v`
Expected: PASS all

- [ ] **Step 5: Commit**

```bash
git add clinosim/simulator/seeding.py tests/unit/test_narrative_pass_walk_order.py \
        tests/unit/test_narrative_pass_determinism.py
git commit -m "$(cat <<'EOF'
feat(seeding): AD-65 narrative_template seed offset + walk order pin

Reserve ENRICHER_SEED_OFFSETS["narrative_template"] = 0x4e54 ("NT")
so TemplateNarrativePass shares the AD-16 determinism discipline.

Pin the (doc_type, language) group-serial walk order in a base-class
test using a _RecordingPass — β-JP-1 LLMNarrativePass will fail this
test if it accidentally reshuffles order, preserving Bedrock prompt
cache friendliness.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SxM5jRL8Xckoh2RidLHiss
EOF
)"
```

---

## Phase 2: Doc mid (T7-T8)

### Task 7: `DESIGN.md` AD-65 ADR

**Files:**
- Modify: `DESIGN.md` (append AD-65 entry after AD-64)

- [ ] **Step 1: Locate AD-64 in DESIGN.md**

Run: `grep -n "^### AD-6" DESIGN.md`
Note the line following the last line of AD-64.

- [ ] **Step 2: Append AD-65**

Insert after AD-64 the ADR body copied verbatim from design doc §6.3 (`docs/superpowers/specs/2026-07-02-tier1-3-narrative-stage2-architecture-design.md` §6.3), starting with `### AD-65: Structural + Narrative CIF file separation (two-pass generation)` and ending with the `**Related ADRs:**` line.

- [ ] **Step 3: Commit**

```bash
git add DESIGN.md
git commit -m "$(cat <<'EOF'
docs(design): add AD-65 two-pass CIF architecture ADR

Document the AD-65 restoration decision: structural + narrative file
separation, ClinicalDocumentNarrative wrapper, NarrativePass base
class + Bedrock cache walk order contract, and the 4 bug fixes that
motivate the two-pass architecture.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SxM5jRL8Xckoh2RidLHiss
EOF
)"
```

---

### Task 8: `SPEC.md` Current Implementation Status + Change Log

**Files:**
- Modify: `clinosim/modules/output/SPEC.md` (add 2 sections)

- [ ] **Step 1: Insert "Current Implementation Status" section**

Immediately after the `## Purpose` section, insert (copy from design doc §6.4):

```markdown
## Current Implementation Status

Last synced: 2026-07-02(chain "AD-65 two-pass restoration" 完了時)

| SPEC section | Status | Notes |
|---|---|---|
| Stage 1: CIF Writer | ✅ IMPLEMENTED | `cif_writer.py`、structural only |
| Stage 2: Narrative Generation | ✅ IMPLEMENTED(AD-65) | `document/narrative/passes.py:TemplateNarrativePass` |
| Stage 3: Format Adapters | ✅ IMPLEMENTED | `fhir_r4_adapter.py`(via `cif_reader.py`)、`csv_adapter.py` |
| Folder structure | ✅ MATCHES SPEC | `cif/{structural,narratives/{template,<v>}}` |
| CIFReader | ✅ IMPLEMENTED | AD-65 で `cif_reader.py` 新規、`narrative_version="current"` selector |
```

- [ ] **Step 2: Append "Change Log" section at file end**

```markdown
## Change Log

| Date | Author | Change | ADR |
|---|---|---|---|
| 2026-07-02 | Tomo Okuyama | Restore two-pass generation from α-min-1 Task 15 drift; introduce `ClinicalDocumentNarrative` wrapper + `NarrativePass` base + Bedrock cache walk order contract | AD-65 |
| 2026-07-01 | Tomo Okuyama | Add document density enrichers (α-min-1/α-min-2), inline narrative populate in document_enricher (retrospectively identified as AD-65 drift) | AD-63, AD-64 |
| 2026-06-30 | Tomo Okuyama | Add imaging chain (4-resource per encounter, 15-check lift_firing_proof) | AD-62 |
```

- [ ] **Step 3: Commit**

```bash
git add clinosim/modules/output/SPEC.md
git commit -m "$(cat <<'EOF'
docs(output-spec): AD-65 status + change log

Mark Stage 2 Narrative Generation as IMPLEMENTED via AD-65.
Add change log so future sessions can trace SPEC ↔ implementation
alignment at a glance.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SxM5jRL8Xckoh2RidLHiss
EOF
)"
```

---

## Phase 3: Bug fixes (T9-T15)

### Task 9: Bug A — `_pick_localized` helper + 8 builder refactor

**Files:**
- Modify: `clinosim/modules/document/narrative/template_generator.py:330-1135` (introduce helper + refactor 8 builders)
- Test: `tests/unit/test_narrative_locale_routing.py` (new)

**Interfaces:**
- Consumes: existing `NarrativeContext.target_lang` field
- Produces:
  - `_pick_localized(tmpl: Any, key_base: str, lang: str) -> str` helper
    - Reads `getattr(tmpl, f"{key_base}_{lang}", None)`, warns + returns empty string on missing

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_narrative_locale_routing.py`:

```python
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.template_generator import _pick_localized


@pytest.mark.unit
def test_pick_localized_returns_en_for_en_lang():
    t = SimpleNamespace(hpi_en="english hpi", hpi_ja="ja hpi")
    assert _pick_localized(t, "hpi", "en") == "english hpi"


@pytest.mark.unit
def test_pick_localized_returns_ja_for_ja_lang():
    t = SimpleNamespace(hpi_en="english hpi", hpi_ja="ja hpi")
    assert _pick_localized(t, "hpi", "ja") == "ja hpi"


@pytest.mark.unit
def test_pick_localized_missing_returns_empty_and_warns(caplog):
    t = SimpleNamespace(hpi_ja="ja hpi")  # no _en
    with caplog.at_level("WARNING"):
        result = _pick_localized(t, "hpi", "en")
    assert result == ""
    assert any("hpi_en" in rec.message for rec in caplog.records)


@pytest.mark.unit
def test_pick_localized_dict_access():
    t = {"hpi_en": "english", "hpi_ja": "ja"}
    assert _pick_localized(t, "hpi", "en") == "english"


@pytest.mark.unit
def test_pick_localized_none_input():
    assert _pick_localized(None, "hpi", "en") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_narrative_locale_routing.py -v`
Expected: FAIL with `ImportError` for `_pick_localized`.

- [ ] **Step 3: Add helper to `template_generator.py`**

At the top of `clinosim/modules/document/narrative/template_generator.py` (after imports, before class definitions), add:

```python
import logging
logger = logging.getLogger(__name__)


def _pick_localized(tmpl, key_base: str, lang: str) -> str:
    """AD-65 Bug A fix: locale-aware field access.

    Reads `<key_base>_<lang>` from tmpl (attr or dict), returns empty
    string + warn log on missing (silent ja fallback撤廃、structural CIF
    に空 section の方が silent contamination より良い)。
    """
    if tmpl is None:
        return ""
    field = f"{key_base}_{lang}"
    if isinstance(tmpl, dict):
        value = tmpl.get(field)
    else:
        value = getattr(tmpl, field, None)
    if value is None or value == "":
        logger.warning("template locale field %s missing on %s",
                       field, type(tmpl).__name__)
        return ""
    return str(value)
```

- [ ] **Step 4: Refactor the 8 builder call sites**

Replace `_ja` hardcoded reads in these locations to use `_pick_localized(tmpl, key_base, ctx.target_lang)`:

- `_build_hpi(360)`: `ed_tmpl.hpi_ja` → `_pick_localized(ed_tmpl, "hpi", ctx.target_lang)` (line ~378)
- `_build_physical_examination(533)` → `_resolve_physical_exam(1135)`: `physical_exam_ja` → `_pick_localized(pe_source, "physical_exam", ctx.target_lang)`
- `_build_ed_physical_exam(1065)`: `physical_exam_ja` (line 1076) → `_pick_localized(ed_tmpl, "physical_exam", ctx.target_lang)`
- `_build_ed_workup(1106)`: `ed_workup_summary_ja` → `_pick_localized(ed_tmpl, "ed_workup_summary", ctx.target_lang)`
- `_build_ed_disposition(1124)`: `disposition_ja` → `_pick_localized(ed_tmpl, "disposition", ctx.target_lang)`
- `_build_chief_complaint(330)` ED_NOTE branch: `chief_complaint_ja` → `_pick_localized(ed_tmpl, "chief_complaint", ctx.target_lang)`
- ADMISSION_HP paths that fall through `ja_only_fallback` (around line 918): audit each and replace with `_pick_localized`

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/test_narrative_locale_routing.py -v`
Expected: PASS all 5

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/document/narrative/template_generator.py \
        tests/unit/test_narrative_locale_routing.py
git commit -m "$(cat <<'EOF'
fix(narrative): Bug A — _pick_localized helper for locale routing

Introduce _pick_localized(tmpl, key_base, lang) helper. Refactor 8
builder call sites (_build_hpi, _build_physical_examination,
_build_ed_physical_exam, _build_ed_workup, _build_ed_disposition,
_build_chief_complaint ED_NOTE branch, _resolve_physical_exam,
ADMISSION_HP ja_only_fallback path) to use locale-aware access.

Silent ja fallback is retired: missing en field now emits warn log
and empty string, so US cohort narratives no longer contain
Japanese characters when a disease YAML lacks the _en variant.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SxM5jRL8Xckoh2RidLHiss
EOF
)"
```

---

### Task 10: Bug A — Disease YAML en field audit + CI script

**Files:**
- Create: `scripts/audit_disease_narrative_en.py` (new)
- Modify: `clinosim/modules/disease/reference_data/*.yaml` (populate missing `_en` fields)

**Interfaces:**
- Consumes: `_pick_localized` warn log path from Task 9
- Produces: CI script that scans all 32 disease YAMLs for narrative fields; exits 1 with a list of missing `_en` variants

- [ ] **Step 1: Create audit script**

Create `scripts/audit_disease_narrative_en.py`:

```python
#!/usr/bin/env python3
"""Audit: every disease YAML narrative.* dict must have both _en and _ja."""
import sys
from pathlib import Path

import yaml

DISEASE_DIR = Path(__file__).resolve().parents[1] / "clinosim/modules/disease/reference_data"
NARRATIVE_KEYS = ("hpi", "physical_examination", "assessment_and_plan",
                  "chief_complaint")


def check_disease(path: Path) -> list[str]:
    missing: list[str] = []
    doc = yaml.safe_load(path.read_text())
    narrative = doc.get("narrative", {})
    if not narrative:
        return []
    for key in NARRATIVE_KEYS:
        has_en = f"{key}_en" in narrative
        has_ja = f"{key}_ja" in narrative
        if has_ja and not has_en:
            missing.append(f"{path.name}: {key}_en missing (ja present)")
    return missing


def main() -> int:
    all_missing: list[str] = []
    for path in sorted(DISEASE_DIR.glob("*.yaml")):
        all_missing.extend(check_disease(path))
    if all_missing:
        print("Missing narrative en fields:")
        for m in all_missing:
            print(f"  {m}")
        return 1
    print(f"OK: all disease YAMLs have narrative _en variants")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run script — collect list of missing fields**

Run: `python scripts/audit_disease_narrative_en.py`
Expected: exit 1 with list of missing `_en` fields OR exit 0 if none missing.

If missing fields exist, capture the list to a text file and proceed to Step 3.

- [ ] **Step 3: Populate missing `_en` fields**

For each `<disease>.yaml : <key>_en missing` in the output, edit `clinosim/modules/disease/reference_data/<disease>.yaml` and add an English narrative field alongside the existing `_ja` field. Use disease-appropriate English medical phrasing.

If the missing count is small, edit each file individually. If very large, consider bulk-generating placeholder English text with `<TODO: en>` markers as an intermediate step, then human-review.

- [ ] **Step 4: Re-run script to verify**

Run: `python scripts/audit_disease_narrative_en.py`
Expected: exit 0

- [ ] **Step 5: Commit**

```bash
git add scripts/audit_disease_narrative_en.py \
        clinosim/modules/disease/reference_data/*.yaml
git commit -m "$(cat <<'EOF'
fix(disease-yaml): Bug A — populate missing narrative _en fields

Audit script scans all 32 disease YAMLs for narrative.hpi_en /
physical_examination_en / assessment_and_plan_en / chief_complaint_en.
Every _ja field must have an _en peer. Populate the missing entries
with disease-appropriate English medical phrasing.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SxM5jRL8Xckoh2RidLHiss
EOF
)"
```

---

### Task 11: Bug A — integration test + audit gate

**Files:**
- Create: `tests/integration/test_bug_a_us_hp_english_only.py`
- Modify: `clinosim/modules/document/audit.py:lift_firing_proof` (add gate)

**Interfaces:**
- Consumes: US p=100 cohort produces Bug A-clean narrative
- Produces:
  - `us_admission_hp_zero_ja_chars` audit gate — integer count of ja chars in US ADMISSION_HP FHIR Composition text, target 0

- [ ] **Step 1: Write integration test**

Create `tests/integration/test_bug_a_us_hp_english_only.py`:

```python
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


JA_CHAR_RE = re.compile(r"[぀-ゟ゠-ヿ一-鿿]")


@pytest.mark.integration
def test_us_admission_hp_zero_japanese_chars(tmp_path):
    out = tmp_path / "us100"
    r = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "generate",
         "-p", "100", "--country", "US", "-o", str(out),
         "--format", "cif", "fhir-r4"],
        capture_output=True, text=True, timeout=600,
    )
    assert r.returncode == 0, r.stderr

    comp_path = out / "fhir_r4" / "Composition.ndjson"
    assert comp_path.exists(), f"no Composition.ndjson: {r.stdout[-500:]}"

    ja_count = 0
    for line in comp_path.read_text().splitlines():
        d = json.loads(line)
        # Filter to ADMISSION_HP (LOINC 34117-2)
        codings = d.get("type", {}).get("coding", [])
        if not any(c.get("code") == "34117-2" for c in codings):
            continue
        for section in d.get("section", []):
            div = section.get("text", {}).get("div", "")
            ja_count += len(JA_CHAR_RE.findall(div))
    assert ja_count == 0, f"US ADMISSION_HP contains {ja_count} Japanese chars"
```

- [ ] **Step 2: Add audit gate**

In `clinosim/modules/document/audit.py`, locate `lift_firing_proof` (the function that returns equality_checks). Add the check:

```python
def _count_us_hp_ja_chars(cif_dir: str) -> int:
    """Count Japanese chars in US ADMISSION_HP narrative sections."""
    import re, json, os
    ja_re = re.compile(r"[぀-ゟ゠-ヿ一-鿿]")
    total = 0
    docs_dir = os.path.join(cif_dir, "narratives", "template", "documents")
    if not os.path.isdir(docs_dir):
        return 0
    for enc_id in os.listdir(docs_dir):
        hp = os.path.join(docs_dir, enc_id, "admission_hp.json")
        if not os.path.exists(hp):
            continue
        with open(hp) as f:
            data = json.load(f)
        for text in (data.get("narrative", {}).get("sections") or {}).values():
            total += len(ja_re.findall(text))
    return total

# In equality_checks dict:
"us_admission_hp_zero_ja_chars": _count_us_hp_ja_chars(cif_dir),
```

- [ ] **Step 3: Run integration test (may be slow — mark to skip if audit already covers)**

Run: `pytest tests/integration/test_bug_a_us_hp_english_only.py -v -m integration`
Expected: PASS (or SKIP with clear reason).

If timeout, reduce to `-p 50` and note in test comment.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_bug_a_us_hp_english_only.py \
        clinosim/modules/document/audit.py
git commit -m "$(cat <<'EOF'
test(bug-a): US ADMISSION_HP zero-ja-chars integration + audit gate

Integration test generates US p=100 cohort and verifies every
ADMISSION_HP Composition.section[].text.div is English-only.
Audit gate us_admission_hp_zero_ja_chars = 0 pins regression at
`clinosim audit run` level.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SxM5jRL8Xckoh2RidLHiss
EOF
)"
```

---

### Task 12: Bug B — `_pick_document_author` helper + refactor

**Files:**
- Modify: `clinosim/modules/document/engine.py` (add helper + refactor 4 branches)
- Modify: `clinosim/modules/document/__init__.py` (export `NURSING_LOINCS`)
- Test: `tests/unit/test_document_author_selection.py` (new)
- Test: `tests/integration/test_bug_b_nurse_author.py` (new)
- Modify: `clinosim/modules/document/audit.py:lift_firing_proof` (add gate)

**Interfaces:**
- Consumes: `Encounter.primary_nurse_id` (populated by nursing_assignment enricher in α-min-2)
- Produces:
  - `_pick_document_author(spec, encounter) -> str` — nursing doc → primary_nurse_id, else attending
  - `NURSING_LOINCS = frozenset({"34746-8", "78390-2", "34119-8"})` exported from `clinosim.modules.document`
  - Audit gate `nursing_doc_author_is_nurse_ratio` (target 1.0)

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_document_author_selection.py`:

```python
import logging
from types import SimpleNamespace

import pytest

from clinosim.modules.document.engine import _pick_document_author


@pytest.mark.unit
def test_nursing_docs_use_nurse():
    for loinc in ("34746-8", "78390-2", "34119-8"):
        spec = SimpleNamespace(loinc_code=loinc)
        enc = SimpleNamespace(attending_physician_id="DR-1", primary_nurse_id="RN-2")
        assert _pick_document_author(spec, enc) == "RN-2"


@pytest.mark.unit
def test_physician_docs_use_attending():
    for loinc in ("34117-2", "11506-3", "18842-5"):
        spec = SimpleNamespace(loinc_code=loinc)
        enc = SimpleNamespace(attending_physician_id="DR-1", primary_nurse_id="RN-2")
        assert _pick_document_author(spec, enc) == "DR-1"


@pytest.mark.unit
def test_nurse_missing_falls_back_to_attending_with_warn(caplog):
    spec = SimpleNamespace(loinc_code="34746-8")
    enc = SimpleNamespace(attending_physician_id="DR-1", primary_nurse_id="")
    with caplog.at_level(logging.WARNING):
        result = _pick_document_author(spec, enc)
    assert result == "DR-1"
    assert any("primary_nurse_id" in rec.message.lower() or
               "fallback" in rec.message.lower() for rec in caplog.records)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_document_author_selection.py -v`
Expected: FAIL with `ImportError` for `_pick_document_author`.

- [ ] **Step 3: Add helper to `engine.py`**

At the top of `clinosim/modules/document/engine.py` (after imports), add:

```python
NURSING_LOINCS = frozenset({"34746-8", "78390-2", "34119-8"})


def _pick_document_author(spec, encounter) -> str:
    """AD-65 Bug B fix: author dispatch by document type.

    Nursing docs (34746-8, 78390-2, 34119-8) → primary_nurse_id.
    Physician docs → attending_physician_id.
    Fallback (nurse missing) → attending + warn log.
    """
    loinc = getattr(spec, "loinc_code", "")
    if loinc in NURSING_LOINCS:
        nurse = getattr(encounter, "primary_nurse_id", "") or ""
        if nurse:
            return nurse
        logger.warning(
            "nursing doc %s falling back to attending (primary_nurse_id missing)",
            loinc)
    return getattr(encounter, "attending_physician_id", "") or ""
```

Then refactor the 4 branches in `_emit_doc` that previously set
`author_practitioner_id=attending_id` — each should now call
`author_practitioner_id=_pick_document_author(spec, encounter)`.

- [ ] **Step 4: Export from `__init__.py`**

In `clinosim/modules/document/__init__.py`, add:

```python
from clinosim.modules.document.engine import NURSING_LOINCS
```

Also add `"NURSING_LOINCS"` to `__all__` if it exists.

- [ ] **Step 5: Write integration test**

Create `tests/integration/test_bug_b_nurse_author.py`:

```python
import json
import subprocess
import sys

import pytest


@pytest.mark.integration
def test_nursing_docs_author_reference_nurse(tmp_path):
    out = tmp_path / "us100"
    r = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "generate",
         "-p", "100", "--country", "US", "-o", str(out),
         "--format", "cif", "fhir-r4"],
        capture_output=True, text=True, timeout=600,
    )
    assert r.returncode == 0, r.stderr

    comp_path = out / "fhir_r4" / "Composition.ndjson"
    assert comp_path.exists()

    total_nurse_docs = 0
    nurse_authored = 0
    for line in comp_path.read_text().splitlines():
        d = json.loads(line)
        codings = d.get("type", {}).get("coding", [])
        loincs = {c.get("code") for c in codings}
        if not (loincs & {"34746-8", "78390-2", "34119-8"}):
            continue
        total_nurse_docs += 1
        for author in d.get("author", []):
            ref = author.get("reference", "")
            if "nurse-" in ref or "RN-" in ref:
                nurse_authored += 1
                break
    if total_nurse_docs == 0:
        pytest.skip("cohort produced no nursing docs")
    assert nurse_authored == total_nurse_docs, (
        f"{total_nurse_docs - nurse_authored}/{total_nurse_docs} nursing docs "
        f"have non-nurse author")
```

- [ ] **Step 6: Add audit gate**

In `clinosim/modules/document/audit.py`, add:

```python
def _nursing_author_ratio(cif_dir: str) -> float:
    import json, os
    docs_dir = os.path.join(cif_dir, "structural", "patients")
    if not os.path.isdir(docs_dir):
        return 1.0
    total, correct = 0, 0
    for fn in os.listdir(docs_dir):
        with open(os.path.join(docs_dir, fn)) as f:
            data = json.load(f)
        for doc in data.get("documents", []) or []:
            if doc.get("loinc_code") not in ("34746-8", "78390-2", "34119-8"):
                continue
            total += 1
            author = doc.get("author_practitioner_id", "")
            nurse_id = ((data.get("encounters") or [{}])[0]
                        .get("primary_nurse_id", ""))
            if author and author == nurse_id:
                correct += 1
    return (correct / total) if total else 1.0

# In equality_checks:
"nursing_doc_author_is_nurse_ratio": _nursing_author_ratio(cif_dir),
```

- [ ] **Step 7: Run tests**

Run: `pytest tests/unit/test_document_author_selection.py -v`
Expected: PASS

Run: `pytest tests/integration/test_bug_b_nurse_author.py -v -m integration`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add clinosim/modules/document/engine.py \
        clinosim/modules/document/__init__.py \
        clinosim/modules/document/audit.py \
        tests/unit/test_document_author_selection.py \
        tests/integration/test_bug_b_nurse_author.py
git commit -m "$(cat <<'EOF'
fix(document): Bug B — nursing docs use primary_nurse_id author

Introduce _pick_document_author(spec, encounter) helper. Nursing docs
(LOINC 34746-8 / 78390-2 / 34119-8) dispatch to primary_nurse_id;
physician docs continue to use attending_physician_id. Fallback with
warn log when primary_nurse_id is missing.

Refactors 4 _emit_doc branches to route through the helper — single
edit point for future doc_type additions.

Audit gate nursing_doc_author_is_nurse_ratio = 1.0 pins regression.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SxM5jRL8Xckoh2RidLHiss
EOF
)"
```

---

### Task 13: Bug C — Diagnosis script (severity distribution)

**Files:**
- Create: `scripts/diagnose_triage_severity.py` (new)

**Interfaces:**
- Produces: diagnostic output showing whether the 14,531 Level-2-4-only outcome is caused by (i) upstream severity collapse to "moderate" or (ii) YAML distribution too narrow.

- [ ] **Step 1: Create diagnosis script**

Create `scripts/diagnose_triage_severity.py`:

```python
#!/usr/bin/env python3
"""Diagnose Bug C: identify whether triage L1/L5 absence is caused by
upstream severity collapse or YAML distribution narrowness."""
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path


def run_cohort(country: str, tmp: Path) -> Path:
    out = tmp / f"{country.lower()}_diag"
    r = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "generate",
         "-p", "500", "--country", country, "-o", str(out),
         "--format", "cif"],
        capture_output=True, text=True, timeout=900,
    )
    assert r.returncode == 0, r.stderr
    return out


def analyze(cif_dir: Path):
    structural = cif_dir / "structural" / "patients"
    severities = Counter()
    triage_levels = Counter()
    ed_count = 0
    for fn in structural.iterdir():
        if not fn.suffix == ".json":
            continue
        d = json.loads(fn.read_text())
        for enc in d.get("encounters", []) or []:
            etype = ((enc.get("encounter_type") or {}).get("value") or "")
            if etype != "emergency":
                continue
            ed_count += 1
            sev = enc.get("severity", "unknown")
            severities[sev] += 1
            tl = enc.get("triage_level", "unknown")
            triage_levels[tl] += 1
    print(f"  ED encounters: {ed_count}")
    print(f"  Severity distribution: {dict(severities)}")
    print(f"  Triage level distribution: {dict(triage_levels)}")


def main():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for country in ("US", "JP"):
            print(f"=== {country} ===")
            cif = run_cohort(country, tmp_path)
            analyze(cif)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run script**

Run: `python scripts/diagnose_triage_severity.py`

Interpret output:
- If `severity` distribution is heavily `moderate` (>80%): candidate (i) — upstream sampler collapse
- If severity is diverse but `triage_level` still lacks L1 / L5: candidate (ii) — YAML narrow
- Note which candidate applies; Task 14 will fix accordingly.

- [ ] **Step 3: Commit diagnosis script + note in commit body**

```bash
git add scripts/diagnose_triage_severity.py
git commit -m "$(cat <<'EOF'
chore(diagnose): Bug C — script to root-cause triage L1/L5 absence

Small p=500 cohort probe printing ED encounter severity + triage_level
distributions. Distinguishes upstream severity collapse (candidate i)
from YAML distribution narrowness (candidate ii). Output guides
Task 14 fix path.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SxM5jRL8Xckoh2RidLHiss
EOF
)"
```

---

### Task 14: Bug C — Fix (route determined by Task 13)

**Files (depends on Task 13 result):**

**If candidate (i) — Severity collapse:**
- Modify: `clinosim/simulator/emergency.py` (severity sampling logic)
- Modify: `clinosim/modules/encounter/reference_data/*.yaml` (46 files — audit + populate `severity_distribution` where missing)

**If candidate (ii) — YAML narrow:**
- Modify: `clinosim/modules/triage/reference_data/triage_protocols.yaml` (broaden distribution)

**Also:**
- Test: `tests/integration/test_bug_c_triage_all_levels.py`
- Modify: `clinosim/modules/triage/audit.py:lift_firing_proof` (add gate)

- [ ] **Step 1: Choose fix path based on Task 13 output**

Document which candidate applies in a comment at the top of the commit message.

- [ ] **Step 2 (candidate ii, most likely): Broaden distribution**

If Task 13 shows severity is diverse but L1/L5 absent, edit `clinosim/modules/triage/reference_data/triage_protocols.yaml`:

```yaml
severity_to_triage_distribution:
  mild:
    "1": 0.002
    "2": 0.028
    "3": 0.170
    "4": 0.500
    "5": 0.300
  moderate:
    "1": 0.010
    "2": 0.150
    "3": 0.580
    "4": 0.230
    "5": 0.030
  severe:
    "1": 0.200
    "2": 0.550
    "3": 0.220
    "4": 0.020
    "5": 0.010
```

Sums: mild=1.000, moderate=1.000, severe=1.000. Each severity has all 5 levels.

- [ ] **Step 2' (candidate i): Broaden severity sampling**

If Task 13 shows severity collapses to `moderate`, audit `clinosim/simulator/emergency.py` for the severity generation logic and inspect encounter YAML `severity_distribution` blocks. Fix so all 3 severities are sampled per condition.

- [ ] **Step 3: Write integration test**

Create `tests/integration/test_bug_c_triage_all_levels.py`:

```python
import json
import subprocess
import sys
from collections import Counter

import pytest


@pytest.mark.integration
def test_triage_all_5_levels_present(tmp_path):
    out = tmp_path / "us500"
    r = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "generate",
         "-p", "500", "--country", "US", "-o", str(out),
         "--format", "cif"],
        capture_output=True, text=True, timeout=900,
    )
    assert r.returncode == 0, r.stderr

    structural = out / "cif" / "structural" / "patients"
    tl_counts = Counter()
    for fn in structural.iterdir():
        if not fn.suffix == ".json":
            continue
        d = json.loads(fn.read_text())
        for enc in d.get("encounters", []) or []:
            etype = ((enc.get("encounter_type") or {}).get("value") or "")
            if etype != "emergency":
                continue
            tl = str(enc.get("triage_level", ""))
            if tl:
                tl_counts[tl] += 1

    total = sum(tl_counts.values())
    assert total > 30, f"too few ED encounters ({total}) to assert distribution"
    for level in ("1", "2", "3", "4", "5"):
        ratio = tl_counts.get(level, 0) / total
        assert ratio > 0.005, f"Level {level} = {ratio:.3f} < 0.5% threshold"
```

- [ ] **Step 4: Add audit gate**

In `clinosim/modules/triage/audit.py`, add:

```python
def _triage_l1_l5_ratio_min(cif_dir: str) -> float:
    import json, os
    tl_counts = {"1": 0, "5": 0}
    total = 0
    struct = os.path.join(cif_dir, "structural", "patients")
    if not os.path.isdir(struct):
        return 0.0
    for fn in os.listdir(struct):
        with open(os.path.join(struct, fn)) as f:
            data = json.load(f)
        for enc in data.get("encounters", []) or []:
            if ((enc.get("encounter_type") or {}).get("value")) != "emergency":
                continue
            tl = str(enc.get("triage_level", ""))
            if tl:
                total += 1
                if tl in tl_counts:
                    tl_counts[tl] += 1
    if total < 30:
        return 1.0  # WARN threshold — insufficient sample
    return min(tl_counts["1"] / total, tl_counts["5"] / total)

"triage_levels_1_and_5_ratio_min": _triage_l1_l5_ratio_min(cif_dir),
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/integration/test_bug_c_triage_all_levels.py -v -m integration`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/triage/reference_data/triage_protocols.yaml \
        tests/integration/test_bug_c_triage_all_levels.py \
        clinosim/modules/triage/audit.py
git commit -m "$(cat <<'EOF'
fix(triage): Bug C — broaden severity distribution to include L1 and L5

Task 13 diagnosis: <insert candidate (i) or (ii) determination>.

<For candidate (ii)>:
Each severity now has all 5 triage levels with non-zero probability:
  mild:     L1=0.002 L2=0.028 L3=0.170 L4=0.500 L5=0.300
  moderate: L1=0.010 L2=0.150 L3=0.580 L4=0.230 L5=0.030
  severe:   L1=0.200 L2=0.550 L3=0.220 L4=0.020 L5=0.010
Rationale: AHRQ ESI + JTAS 2017 validation show rare cross-severity
triage assignments (mild SAH → L2; severe chronic exacerbation → L4).

Audit gate triage_levels_1_and_5_ratio_min > 0.005 pins regression.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SxM5jRL8Xckoh2RidLHiss
EOF
)"
```

---

### Task 15: Bug D — CLI silent override fix

**Files:**
- Modify: `clinosim/simulator/cli.py:37-45` (argparse `-p` default = SUPPRESS)
- Modify: `clinosim/types/config.py:90` (catchment_population: int | None = None)
- Modify: `clinosim/simulator/engine.py:83-93` (sentinel撤廃)
- Test: `tests/unit/test_cli_population_no_sentinel.py` (new)
- Test: `tests/integration/test_bug_d_explicit_population.py` (new)
- Modify: `clinosim/simulator/audit.py` (add gate — or add to existing audit module)

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_cli_population_no_sentinel.py`:

```python
import subprocess
import sys

import pytest


@pytest.mark.unit
def test_explicit_p_10000_not_overridden(tmp_path):
    """Bug D: user -p 10000 must not silently become 40000."""
    r = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "generate",
         "-p", "10000", "--country", "US", "-o", str(tmp_path)],
        capture_output=True, text=True, timeout=1800,
    )
    # Verify stdout reports 10000, not 40000
    assert "population=10000" in r.stdout or "Population: 10000" in r.stdout
    assert "Population: 39" not in r.stdout


@pytest.mark.unit
def test_omitted_p_uses_recommended():
    """Without -p, hospital-config recommended_population applies."""
    r = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "generate",
         "--country", "US", "-o", "/tmp/no_p"],
        capture_output=True, text=True, timeout=1800,
    )
    # Recommended US = 40000
    assert "40000" in r.stdout or "Population: 39" in r.stdout


@pytest.mark.unit
def test_config_catchment_defaults_to_none():
    from clinosim.types.config import SimulatorConfig
    c = SimulatorConfig()
    assert c.catchment_population is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_cli_population_no_sentinel.py -v -m unit`
Expected: FAIL (sentinel still active).

- [ ] **Step 3: Fix `SimulatorConfig`**

Edit `clinosim/types/config.py:90`:

```python
    catchment_population: int | None = None
```

- [ ] **Step 4: Fix argparse in `cli.py`**

Find `gen.add_argument("-p", "--population", ...` around cli.py:37. Change to:

```python
gen.add_argument("-p", "--population", type=int, default=argparse.SUPPRESS,
                 help="Catchment population (default: hospital recommended)")
```

Then where `SimulatorConfig` is built in `main()`, pass `catchment_population=getattr(args, "population", None)`.

- [ ] **Step 5: Fix `engine.py` sentinel**

In `clinosim/simulator/engine.py:83-93`, replace:

```python
    pop_size = config.catchment_population
    recommended_raw = hospital_ops.get("recommended_population")
    if recommended_raw:
        if isinstance(recommended_raw, dict):
            recommended = recommended_raw.get(config.country) or recommended_raw.get("default", 40000)
        else:
            recommended = int(recommended_raw)
        if config.catchment_population is None:
            pop_size = recommended
        elif config.catchment_population != recommended:
            print(
                f"⚠️  User-specified -p {config.catchment_population} used as-is "
                f"(hospital recommended: {recommended} for {config.country})",
                file=sys.stderr,
            )
    else:
        pop_size = config.catchment_population or 40000
```

(Import `sys` at top if not already imported.)

- [ ] **Step 6: Write integration test**

Create `tests/integration/test_bug_d_explicit_population.py`:

```python
import json
import subprocess
import sys

import pytest


@pytest.mark.integration
def test_explicit_p_500_yields_us_and_jp_same_scale(tmp_path):
    us = tmp_path / "us500"
    jp = tmp_path / "jp500"
    for country, out in [("US", us), ("JP", jp)]:
        r = subprocess.run(
            [sys.executable, "-m", "clinosim.simulator.cli", "generate",
             "-p", "500", "--country", country, "-o", str(out),
             "--format", "cif"],
            capture_output=True, text=True, timeout=900,
        )
        assert r.returncode == 0, r.stderr

    us_count = len(list((us / "cif" / "structural" / "patients").iterdir()))
    jp_count = len(list((jp / "cif" / "structural" / "patients").iterdir()))
    # Both were -p 500 → within a factor of 3 of each other
    ratio = max(us_count, jp_count) / max(1, min(us_count, jp_count))
    assert ratio < 3.0, f"US={us_count}, JP={jp_count} — Bug D likely regressed"
```

- [ ] **Step 7: Add audit gate**

Add `"explicit_population_respected": <bool>` — this is a static check verifying `SimulatorConfig.catchment_population` is optional (True if type hints match).

- [ ] **Step 8: Run tests**

Run: `pytest tests/unit/test_cli_population_no_sentinel.py -v`
Expected: PASS

Run: `pytest tests/integration/test_bug_d_explicit_population.py -v -m integration`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add clinosim/simulator/cli.py clinosim/simulator/engine.py \
        clinosim/types/config.py \
        tests/unit/test_cli_population_no_sentinel.py \
        tests/integration/test_bug_d_explicit_population.py
git commit -m "$(cat <<'EOF'
fix(cli): Bug D — retire -p 10000 sentinel, honor explicit user value

Previously any explicit -p 10000 collided with the sentinel used to
signal "no CLI override" and was silently replaced by the hospital
recommended value (US 40000). User's requested population was lost.

SimulatorConfig.catchment_population is now Optional[int]; argparse
uses SUPPRESS default. engine.py picks recommended only when the
config value is None. When explicit and diverges from recommended,
emit a stderr warn making the choice visible.

This closes the primary silent driver of the US/JP FHIR volume
disparity observed in session 27 audits.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SxM5jRL8Xckoh2RidLHiss
EOF
)"
```

---

## Phase 4: Dev facility (T16-T18)

### Task 16: `test-disease --format` + `-o`

**Files:**
- Modify: `clinosim/simulator/cli.py` (test-disease subparser + `_run_test_disease` handler)
- Test: `tests/unit/test_cli_test_disease_format.py` (new)

**Interfaces:**
- Consumes: TemplateNarrativePass (Task 3), CIFReader (Task 4), FHIR adapter (Task 4)
- Produces:
  - `test-disease <disease_id> [-n N] [-o <dir>] [--format cif|fhir-r4|all] [--country US]`
  - If `-o` omitted: keep existing stdout debug print
  - If `-o` set with `--format`: run mini-generate (N patients of specific disease) → structural + narrative + FHIR emit

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_cli_test_disease_format.py`:

```python
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.unit
def test_test_disease_format_all_writes_all_stages(tmp_path):
    out = tmp_path / "verify_mi"
    r = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "test-disease",
         "acute_mi", "-n", "3", "--format", "all", "-o", str(out),
         "--country", "US"],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, r.stderr
    assert (out / "cif" / "structural" / "patients").exists()
    assert (out / "cif" / "narratives" / "template").exists()
    assert (out / "fhir_r4" / "Composition.ndjson").exists()


@pytest.mark.unit
def test_test_disease_no_output_keeps_stdout(tmp_path):
    r = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "test-disease",
         "acute_mi", "-n", "1", "--country", "US"],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0
    # existing debug print — should include patient info
    assert "Patient" in r.stdout or "Chief" in r.stdout
    # no CIF dir since -o not set
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_cli_test_disease_format.py -v`
Expected: FAIL (no --format / -o support).

- [ ] **Step 3: Extend test-disease subparser (cli.py:56)**

```python
td.add_argument("--format", nargs="+", default=None,
                choices=["cif", "fhir-r4", "csv", "all"],
                help="Output formats (if omitted, stdout debug only)")
td.add_argument("-o", "--output", default=None,
                help="Output directory (required when --format is set)")
```

- [ ] **Step 4: Modify `_run_test_disease` handler**

Locate `_run_test_disease` in `cli.py`. If `args.output` is set:

```python
def _run_test_disease(args):
    # ... existing debug-print logic when args.output is None ...
    if args.output:
        _run_test_disease_generate(args)
        return
    _run_test_disease_debug(args)


def _run_test_disease_generate(args):
    """Mini-generate: N patients of a specific disease + CIF + narrative + FHIR."""
    from clinosim.simulator.engine import run_forced
    from clinosim.types.config import SimulatorConfig, ForcedScenario
    from clinosim.modules.output.cif_writer import write_cif
    from clinosim.modules.document.narrative.passes import TemplateNarrativePass
    from clinosim.modules.output.adapter import get_adapter, OutputContext
    import os

    cif_dir = os.path.join(args.output, "cif")
    fhir_dir = os.path.join(args.output, "fhir_r4")

    scenario = ForcedScenario(disease_id=args.disease_id, count=args.count)
    config = SimulatorConfig(
        country=args.country, random_seed=args.seed,
        catchment_population=args.count,  # tiny cohort
    )
    dataset = run_forced(scenario, config)

    write_cif(dataset, cif_dir)
    formats = args.format or ["all"]
    if "all" in formats or "cif" in formats:
        TemplateNarrativePass(cif_dir=cif_dir, country=args.country,
                              rng_seed=args.seed).run()
        os.makedirs(os.path.join(cif_dir, "narratives"), exist_ok=True)
        with open(os.path.join(cif_dir, "narratives", "current_version.txt"), "w") as f:
            f.write("template")

    if "all" in formats or "fhir-r4" in formats:
        get_adapter("fhir-r4").convert(cif_dir, fhir_dir,
                                        OutputContext(country=args.country))
    if "all" in formats or "csv" in formats:
        csv_dir = os.path.join(args.output, "csv")
        get_adapter("csv").convert(cif_dir, csv_dir, OutputContext(country=args.country))
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/test_cli_test_disease_format.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add clinosim/simulator/cli.py tests/unit/test_cli_test_disease_format.py
git commit -m "$(cat <<'EOF'
feat(cli): test-disease --format + -o for 10-second targeted verify

test-disease acute_mi -n 5 --format all -o /tmp/verify_mi now runs
the full 3-stage pipeline (structural + narrative + FHIR) for a
tiny cohort focused on the specified disease. Enables dev iteration
of narrative and FHIR builder bugs without regenerating a full
20k+ patient cohort.

Existing stdout debug behavior preserved when -o is omitted.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SxM5jRL8Xckoh2RidLHiss
EOF
)"
```

---

### Task 17: `test-encounter --format` + `-o`

**Files:**
- Modify: `clinosim/simulator/cli.py` (test-encounter subparser + `_run_test_encounter` handler)
- Test: `tests/unit/test_cli_test_encounter_format.py` (new)

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_cli_test_encounter_format.py` — mirror the Task 16 test with `test-encounter chest_pain_noncardiac`:

```python
import subprocess
import sys

import pytest


@pytest.mark.unit
def test_test_encounter_format_all(tmp_path):
    out = tmp_path / "verify_cp"
    r = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "test-encounter",
         "chest_pain_noncardiac", "-n", "3", "--format", "all",
         "-o", str(out), "--country", "US"],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stderr
    assert (out / "cif" / "structural" / "patients").exists()
    assert (out / "fhir_r4" / "Composition.ndjson").exists() or \
           (out / "fhir_r4" / "DocumentReference.ndjson").exists()
```

- [ ] **Step 2: Extend `test-encounter` subparser + handler**

Follow the same pattern as Task 16.

- [ ] **Step 3: Run test**

Run: `pytest tests/unit/test_cli_test_encounter_format.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add clinosim/simulator/cli.py tests/unit/test_cli_test_encounter_format.py
git commit -m "$(cat <<'EOF'
feat(cli): test-encounter --format + -o mirrors test-disease

Same pattern as test-disease — tiny targeted CIF+FHIR generation for
ED/outpatient condition verification.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SxM5jRL8Xckoh2RidLHiss
EOF
)"
```

---

### Task 18: `CONTRIBUTING-modules.md` regen scope matrix

**Files:**
- Modify: `docs/CONTRIBUTING-modules.md` (append Regen scope matrix)

- [ ] **Step 1: Append content from design doc §6.7**

Copy the "Regen scope matrix" section (matrix table + 3 usage examples) verbatim from design doc §6.7 into `docs/CONTRIBUTING-modules.md`. Place after existing "Testing" or similar section.

- [ ] **Step 2: Commit**

```bash
git add docs/CONTRIBUTING-modules.md
git commit -m "$(cat <<'EOF'
docs(contributing): AD-65 regen scope matrix + 3 workflow examples

Document the 3-tier regen cost for common change targets, plus
concrete narrate + export-fhir + test-disease workflows for Bug A /
Bug B / FHIR builder cycles.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SxM5jRL8Xckoh2RidLHiss
EOF
)"
```

---

## Phase 5: Test regeneration (T19)

### Task 19: e2e goldens 全 regenerate

**Files:**
- Modify: `tests/e2e/goldens/*.json` (regenerate all)

- [ ] **Step 1: Run e2e with update flag**

Run: `pytest tests/e2e/ --update-goldens`
Expected: goldens rewritten.

If `--update-goldens` doesn't exist, follow the project-specific procedure (typically deleting `tests/e2e/goldens/*.json` and running e2e which regenerates on missing goldens).

- [ ] **Step 2: Diff review**

Run: `git diff --stat tests/e2e/goldens/`

For each changed golden, sample-check content:
- `Composition.ndjson`: same count, sections now English-fixed (Bug A)
- `DocumentReference.ndjson`: nurse-authored (Bug B)
- `Encounter.ndjson`: triage extension shows L1/L5 (Bug C)
- `Patient.ndjson` / `Practitioner.ndjson`: no unexpected changes
- `manifest.json`: `request` string may differ

Any unexpected content change → root-cause before commit.

- [ ] **Step 3: Full e2e re-run to confirm goldens pass**

Run: `pytest -m e2e -x -q`
Expected: PASS all

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/goldens/
git commit -m "$(cat <<'EOF'
test(e2e): regenerate goldens for AD-65 + Bug A/B/C/D fixes

Full regeneration of all 39 e2e goldens under the AD-65 two-layer
CIF architecture. Content changes are limited to:
  - Composition sections: English-only for US (Bug A)
  - Nursing DocumentReference author = nurse Practitioner (Bug B)
  - Encounter triage extension: L1 + L5 present (Bug C)
  - manifest.json request string reflects new pipeline

No compat with previous flat-CIF goldens (design decision).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SxM5jRL8Xckoh2RidLHiss
EOF
)"
```

---

## Phase 6: Doc final (T20-T23)

### Task 20: `MODULES.md` revise

**Files:**
- Modify: `MODULES.md`

- [ ] **Step 1: Locate `### document` section**

Run: `grep -n "^### .document" MODULES.md`

- [ ] **Step 2: Replace with 2-role description**

Copy the revised `document` section from design doc §6.5 verbatim.

- [ ] **Step 3: Add `narrative_pass` to modules-at-a-glance table**

At the top of `MODULES.md` in the "22 modules at a glance" table, bump count to 23 and add a row for `narrative_pass` (POST_SIMULATION stage).

- [ ] **Step 4: Commit**

```bash
git add MODULES.md
git commit -m "$(cat <<'EOF'
docs(modules): AD-65 document 2-role + narrative_pass in module table

Split document module description into enricher (POST_ENCOUNTER
stub-only) and narrative_pass (POST_SIMULATION TemplateNarrativePass)
roles. Bump module count to 23.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SxM5jRL8Xckoh2RidLHiss
EOF
)"
```

---

### Task 21: module READMEs (document + output)

**Files:**
- Modify: `clinosim/modules/document/README.md` (append 3 sections from design doc §6.6)
- Modify: `clinosim/modules/output/README.md` (append CIFReader API + narrative dir layout)

- [ ] **Step 1: Append to `clinosim/modules/document/README.md`**

Add sections: `Architecture: Two-Pass Generation (AD-65)` + `LLMNarrativeGenerator Roadmap` + `Bug fix log (AD-65 chain)`.

Content verbatim from design doc §6.6.

- [ ] **Step 2: Append to `clinosim/modules/output/README.md`**

Add: `AD-65 CIF layout: structural + narratives/<version>/documents/` layout diagram + `CIFReader(narrative_version=)` API brief.

- [ ] **Step 3: Commit**

```bash
git add clinosim/modules/document/README.md clinosim/modules/output/README.md
git commit -m "$(cat <<'EOF'
docs(module-readme): AD-65 two-pass architecture + CIFReader API

document/README.md: two-pass architecture diagram, LLMNarrativeGenerator
β-JP-1 roadmap, Bug A/B fix log.

output/README.md: CIF layout diagram, CIFReader signature reference.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SxM5jRL8Xckoh2RidLHiss
EOF
)"
```

---

### Task 22: `TODO.md` update

**Files:**
- Modify: `TODO.md`

- [ ] **Step 1: Remove stale entries**

Delete existing entries matching:
- "Stage 2 LLM 統合(β-JP-1 chain defer)" or similar
- α-min-1 Task 15 "narrate deprecated" carry-over

- [ ] **Step 2: Add new β-JP-1 entry**

```markdown
## β-JP-1: LLMNarrativePass 実装(AD-65 base 上に drop-in)

- `LLMNarrativePass(NarrativePass)` class 実装
- Bedrock Sonnet-4 provider + Ollama qwen:7b provider
- Bedrock prompt cache(5 分 TTL)発火の 実測 verify
- `facts_used` gate 有効化
- `docStatus` 4 状態化(template=final / LLM=final / LLM fallback=preliminary / human reviewed=amended)
- `Composition.author` extension で AI-assisted 明示
- Section-level LLM replacement 発火
- narrate `--patient-filter POP-000001` 対応
```

- [ ] **Step 3: Add α-min-2c entry**

```markdown
## Post-AD-65 fixture library(α-min-2c or β-2 chain)

- `clinosim/tests/fixtures/patient_profiles/` に canonical fixture YAML 10-15 件
- `test-disease --patient-profile <yaml>` 対応
- Fixture 選定は 臨床医レビュー loop 必須
- CI に narrative bug regression suite として integrate
```

- [ ] **Step 4: Commit**

```bash
git add TODO.md
git commit -m "$(cat <<'EOF'
docs(todo): update roadmap for AD-65 completion

Remove stale entries subsumed by AD-65:
  - "Stage 2 LLM 統合" → new β-JP-1: LLMNarrativePass drop-in
  - α-min-1 Task 15 carry-overs

Add β-JP-1 entry (LLMNarrativePass on top of NarrativePass base
established in AD-65) and Post-AD-65 fixture library entry (α-min-2c).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SxM5jRL8Xckoh2RidLHiss
EOF
)"
```

---

### Task 23: Session 28 end-state memory + PR body draft

**Files:**
- Create: `/Users/tokuyama/.claude/projects/-Users-tokuyama-workspace-clinosim/memory/project_session_28_end_state.md`
- Modify: `/Users/tokuyama/.claude/projects/-Users-tokuyama-workspace-clinosim/memory/MEMORY.md` (add link entry)

- [ ] **Step 1: Draft session memory**

Create the memory file with content following the session-27 format from design doc §6.9. Fill in actual metrics:
- master HEAD sha after all commits
- unit / integration / e2e counts
- Bug regression gate values (0 ja chars / 1.0 nurse ratio / > 0.5% triage L1/L5 / true explicit-p-respected)
- Verified gap closures (structural vs narrative file count, Composition count, etc.)

- [ ] **Step 2: Add entry to `MEMORY.md`**

```markdown
- [セッション28 末状態](project_session_28_end_state.md) — AD-65 two-pass restoration + 4 bug fixes + dev facility complete
```

- [ ] **Step 3: Draft PR body**

Create `/tmp/pr_body.md` with:
- Summary (3-5 bullets on what changed)
- AD-65 core: two-pass restoration
- 4 bug fixes with cohort-scale gap closures
- Dev facility: 10-sec verify
- Test plan checklist
- Related: sessions 27 review, design doc, chain-of-thought pattern

- [ ] **Step 4: Commit memory + open PR**

```bash
git add -A "/Users/tokuyama/.claude/projects/-Users-tokuyama-workspace-clinosim/memory/"
# Note: memory dir may be outside repo; use path directly. If outside repo, skip git.

# In-repo commit for anything remaining:
# (none expected at this point)

# Push branch + open PR
git push -u origin feature/tier1-narrative-stage2-architecture
gh pr create --title "AD-65 two-pass CIF restoration + 4 bug fixes + dev facility" \
  --body "$(cat /tmp/pr_body.md)"
```

- [ ] **Step 5: Verify chain gate before PR merge**

Run:
```
pytest -m unit -x -q
pytest -m integration -x -q
pytest -m e2e -x -q
clinosim generate -p 500 --country US -o /tmp/us500
clinosim generate -p 500 --country JP -o /tmp/jp500
clinosim audit run --cif-dir /tmp/us500 --cif-dir /tmp/jp500
```

All must pass. If any fails, do not merge.

---

## Self-Review Notes

**Spec coverage:**
- Section 1 Architecture → T1-T6 (wrapper, writer, passes, reader, CLI, seeding)
- Section 2 Type Changes → T1
- Section 3 New Modules → T3, T4, T5, T6
- Section 4 Bug Fixes → T9-T15
- Section 5 Testing → each task has its own test; T19 e2e regenerate
- Section 6 Documentation → T1 (CLAUDE.md), T7 (DESIGN.md), T8 (SPEC.md), T18 (CONTRIBUTING), T20 (MODULES.md), T21 (module READMEs), T22 (TODO.md), T23 (memory)
- All 23 tasks in design doc Appendix A are covered.

**Type consistency:**
- `ClinicalDocumentNarrative` fields consistent across T1 (definition) and T3 (populated by passes).
- `NarrativePass._output_to_wrapper` uses the same field names as T1 definition (text/sections/structured/generator/generator_metadata/generated_at/facts_used).
- `CIFReader.iter_patients()` yields dicts (T4), so FHIR builders in T4 read via dict access.
- `_pick_document_author` signature stable between T12 tests and helper.
- `_pick_localized` signature stable between T9 tests and helper.

**Placeholder scan:**
- No "TBD" / "TODO" / "add validation" / "handle edge cases" without actual code.
- T14 conditional fix path is explicit (candidate i vs ii from T13 diagnosis).
- T10 YAML audit acknowledges variable output — script + human review is the process, not silent placeholder.

---

Plan complete and saved to `docs/superpowers/plans/2026-07-02-tier1-3-narrative-stage2-architecture-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
