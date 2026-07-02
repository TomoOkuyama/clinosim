"""Document chain AD-60 audit module (Tier 1 #3 α-min-1 Task 11; α-min-2 Task 13;
AD-65 Bug A Task 11; AD-65 Bug B Task 12; PR #131 adv-1 F-6/F-6b; α-min-3 3-shift).

AD-60 plug-in #5 (after hai, antibiotic, order_service_request, imaging).

Verifies CIF -> FHIR emission integrity for the document pipeline:
DocumentReference / Composition / AllergyIntolerance / ClinicalImpression / CareTeam.

37 equality_checks in lift_firing_proof guard canonical constants and
no-drop emission paths against PR-90 class silent-no-op regression.

Registered checks:
- canonical_constants: DOC_REFERENCE_ID_PREFIX / COMPOSITION_ID_PREFIX /
  ALLERGY_ID_PREFIX / CLINICAL_IMPRESSION_ID_PREFIX / CARE_TEAM_ID_PREFIX
  (5 constants, import-time ownership enforced via import from module writers).
- clinical_acceptance: per-encounter doc count + ClinicalImpression daily
  emission + AllergyIntolerance distribution targets + CareTeam/triage/nursing/
  outpatient/ED per-encounter targets for Task 12+ DQR gate (13 keys total).
- lift_firing_proof (_build_document_proof): exercises FHIR builders on
  synthetic CIF inputs.
  α-min-1 17 equality_checks:
    4 canonical constants + 4 emission counts + 3 ID-prefix invariants +
    5 no-drop invariants (Section 3.4 CIF→FHIR emission matrix) + 1 extra.
  α-min-2 +9 equality_checks (total = 26):
    1 canonical constant (CARE_TEAM_ID_PREFIX) + 2 emission/prefix invariants +
    2 CIF→FHIR no-drop for CareTeam fields + 4 dispatch no-drop invariants
    (outpatient/emergency/inpatient specs_for_encounter_type coverage +
    LOINC 54094-8 dispatch gate).
  AD-65 Bug A +1 equality_check (total = 27):
    `us_admission_hp_zero_ja_chars` — see `_count_us_hp_ja_chars` /
    `_proof_us_hp_ja_chars` docstrings. Companion integration test:
    `tests/integration/test_bug_a_us_hp_english_only.py`.
  AD-65 Bug B +1 equality_check (total = 28):
    `nursing_doc_author_is_nurse_ratio` — see `_nursing_author_ratio` /
    `_proof_nursing_author_ratio` docstrings. Companion unit test:
    `tests/unit/test_document_author_selection.py`; companion integration
    test: `tests/integration/test_bug_b_nurse_author.py`.
  PR #131 adv-1 F-6 + F-6b (+6, total = 34):
    F-6 (spec §5.5 named gates): `narrative_pass_populated_narrative_ratio` /
      `structural_cif_zero_narrative_content` /
      `triage_levels_1_and_5_ratio_min` (delegate to triage_chain proof) /
      `explicit_population_respected` (Bug D).
    F-6b (fixture-strengthening — Bug A / Bug B proofs were happy-path only):
      `us_hp_ja_gate_detects_contamination` verifies the count helper
      actually FAILS on a contaminated fixture (not just returns 0 for
      clean input); `nursing_author_fallback_fires_on_missing_nurse`
      verifies the fallback branch actually picks the attending id when
      the encounter has no primary_nurse_id.
  α-min-3 nursing 3-shift cadence (+3, total = 37):
    `nursing_shift_note_3_per_day_count` (LOS=3 → 9 stubs, proving the
    daily_3shift dispatch actually fires — a silently-unknown frequency
    value would emit 0), `nursing_shift_note_shift_keys_complete`
    (neutral keys night/day/evening on every stub) and
    `nursing_shift_note_shift_hour_offsets` (authored at 00:00/08:00/16:00).
    See `_proof_nursing_shift_3_per_day`.

TODO(jp_language_audit): jp_language_checks not implemented — ModuleAuditSpec
does not have a jp_language_checks field. Deferred to a follow-up sweep
(see TODO.md: "document chain JP language axis"). When the field is added,
verify: DocumentReference.type.coding[].display in ja / Composition.section[].title
in ja / AllergyIntolerance.code.text in ja / ClinicalImpression.description in ja.

TODO(AD-65 Bug A residual gap): `hpi_template.onset_pattern` (disease YAML) and
`physical_exam_findings` (disease YAML + `reference_data/physical_exam_findings.yaml`)
carry no per-language split at all — a data-authoring gap across all 32 disease
YAMLs, out of scope for the Task 9 code fix / Task 10 YAML `_en` population sweep
(both explicitly deferred this; see task-9-report.md / task-10-report.md). Until
closed, `KNOWN_JA_ONLY_FALLBACK_SECTIONS` intentionally excludes `hpi` +
`physical_examination` from the ja-char count so this gate tracks the actual
Bug-A locale-routing fix rather than perpetually failing on a known, tracked,
separate issue. See TODO.md "disease YAML English narrative content" entry.
"""

from __future__ import annotations

import glob
import json
import os
import re
import tempfile
from typing import Any

from clinosim.audit.registry import ModuleAuditSpec, register_audit_module
from clinosim.modules.document import (
    ALLERGY_ID_PREFIX,
    CLINICAL_IMPRESSION_ID_PREFIX,
    COMPOSITION_ID_PREFIX,
    DOC_REFERENCE_ID_PREFIX,
    NURSING_LOINCS,
)
from clinosim.modules.output._fhir_care_team import CARE_TEAM_ID_PREFIX
from clinosim.modules.output.cif_reader import resolve_current_narrative_dir

# AD-65 Bug A (US H&P Japanese contamination, Task 11): ja char range used by
# both this module's gate and tests/integration/test_bug_a_us_hp_english_only.py.
_JA_CHAR_RE = re.compile(r"[぀-ゟ゠-ヿ一-鿿]")

# Two ADMISSION_HP composition_sections ("hpi", "physical_examination") draw
# from disease-YAML source data (`hpi_template.onset_pattern` /
# `physical_exam_findings`) that carries no per-language split at all — a
# separate, tracked, deferred data-authoring gap discovered while
# implementing the AD-65 Bug A code fix (see
# .superpowers/sdd/task-9-report.md §6 concern 2 and task-10-report.md §7;
# TODO.md follow-up entry). Both builder sites tag `facts_used` with the
# module's documented `:ja_only_fallback` suffix at generation time
# (`clinosim/modules/document/narrative/template_generator.py`
# `_build_hpi` / `_build_physical_examination`). These two sections are
# therefore excluded from the ja-char count below; Japanese chars in any
# OTHER ADMISSION_HP section indicate a genuine Bug-A-class locale-routing
# regression and ARE counted.
KNOWN_JA_ONLY_FALLBACK_SECTIONS = frozenset({"hpi", "physical_examination"})


def _count_us_hp_ja_chars(cif_dir: str) -> int:
    """Count (regression-relevant) Japanese chars in US ADMISSION_HP narrative sections.

    Walks `cif_dir/structural/patients/*.json` to find every document stub
    with `task_type == "admission_hp"`, then reads the matching file under
    `cif_dir/narratives/template/documents/<encounter_id>/<document_id>.json`
    (Stage 1 template narrative tree — AD-65 two-pass architecture;
    `NarrativePass._filename_for` keys files by `document_id`, NOT
    `task_type`, so a naive `documents/<enc>/admission_hp.json` guess would
    silently match nothing). Sums `_JA_CHAR_RE` matches across every section
    text EXCEPT `KNOWN_JA_ONLY_FALLBACK_SECTIONS` (see module-level comment).

    Returns 0 if the CIF directory doesn't have the expected structural or
    narrative subtree (defensive default, mirrors other loader helpers in
    this codebase — e.g. `load_hai_antibiogram`'s no-panel-eligible default).
    """
    structural_dir = os.path.join(cif_dir, "structural", "patients")
    # F-3 fix: `narratives/current_version.txt` pointer 経由で解決するので、
    # LLMNarrativePass 導入(β-JP-1)後は "template" 以外の version にも
    # 追従する。pointer 無 → "template" fallback で後方互換。
    narrative_dir = resolve_current_narrative_dir(cif_dir)
    if not os.path.isdir(structural_dir) or not os.path.isdir(narrative_dir):
        return 0

    total = 0
    for patient_path in glob.glob(os.path.join(structural_dir, "*.json")):
        with open(patient_path, encoding="utf-8") as f:
            patient = json.load(f)
        encounters = patient.get("encounters") or []
        encounter_id = encounters[0].get("encounter_id", "") if encounters else ""
        for doc in patient.get("documents") or []:
            if doc.get("task_type") != "admission_hp":
                continue
            document_id = doc.get("document_id", "")
            narrative_path = os.path.join(narrative_dir, encounter_id, f"{document_id}.json")
            if not os.path.exists(narrative_path):
                continue
            with open(narrative_path, encoding="utf-8") as f:
                narrative_doc = json.load(f)
            sections = (narrative_doc.get("narrative") or {}).get("sections") or {}
            for section_name, text in sections.items():
                if section_name in KNOWN_JA_ONLY_FALLBACK_SECTIONS:
                    continue
                total += len(_JA_CHAR_RE.findall(text or ""))
    return total


def _proof_us_hp_ja_chars() -> int:
    """Zero-arg synthetic fixture exercising `_count_us_hp_ja_chars` end to end.

    `lift_firing_proof` is a zero-arg factory (called with no arguments by
    `clinosim/audit/axes/silent_no_op.py:_check_proof`) so it cannot receive
    a real cohort's `cif_dir`. This builds a minimal on-disk structural +
    narrative-tree pair for one synthetic admission_hp document (same
    pattern as `_build_document_proof`'s in-memory synthetic ClinicalDocument
    dicts, extended to disk since `_count_us_hp_ja_chars` is a file-walking
    helper): clean English text in every counted section, PLUS intentional
    Japanese text in the excluded `physical_examination` section. A naive
    "count every section" implementation would return > 0 here — proving
    the known-gap exclusion (and the document_id/task_type cross-reference)
    is load-bearing, not just a happy-path count of 0.
    """
    with tempfile.TemporaryDirectory() as tmp:
        _write_us_hp_fixture(tmp, contaminate_counted_section=False)
        return _count_us_hp_ja_chars(tmp)


def _proof_us_hp_ja_gate_detects_contamination() -> bool:
    """F-6b adv-1: verify the Bug A gate can FAIL on a regression.

    The clean fixture in `_proof_us_hp_ja_chars` returns 0 whether or not
    the count logic actually excludes JA-only fallback sections. A second
    synthetic case with Japanese in a COUNTED section (`chief_complaint`,
    not in `KNOWN_JA_ONLY_FALLBACK_SECTIONS`) should return > 0. If both
    fixtures return 0, the counter is silent-no-op and this gate must fail.

    Returns True when contamination is correctly detected (count > 0).
    """
    with tempfile.TemporaryDirectory() as tmp:
        _write_us_hp_fixture(tmp, contaminate_counted_section=True)
        return _count_us_hp_ja_chars(tmp) > 0


def _write_us_hp_fixture(tmp: str, *, contaminate_counted_section: bool) -> None:
    """内部: on-disk fixture (structural + narrative)を書き出す。

    contaminate_counted_section=True で `chief_complaint`(counted section)に
    日本語を注入し、gate の sensitivity を検証する(F-6b adv-1)。
    """
    structural_dir = os.path.join(tmp, "structural", "patients")
    narrative_dir = os.path.join(tmp, "narratives", "template", "documents", "enc-proof-hp")
    os.makedirs(structural_dir, exist_ok=True)
    os.makedirs(narrative_dir, exist_ok=True)

    with open(os.path.join(structural_dir, "pt-proof-hp.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "encounters": [{"encounter_id": "enc-proof-hp"}],
                "documents": [
                    {"document_id": "doc-enc-proof-hp-01", "task_type": "admission_hp"}
                ],
            },
            f,
        )

    # `chief_complaint` は counted section — clean 時は ASCII のみ、
    # contaminate 時は日本語混入で Bug A regression 相当。
    chief_complaint = "胸痛" if contaminate_counted_section else "Chest pain"

    with open(
        os.path.join(narrative_dir, "doc-enc-proof-hp-01.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(
            {
                "document_id": "doc-enc-proof-hp-01",
                "encounter_id": "enc-proof-hp",
                "narrative": {
                    "sections": {
                        "chief_complaint": chief_complaint,
                        "hpi": "Patient presented with chest pain.",
                        "physical_examination": (
                            "General: 意識清明. "
                            "Cardiovascular: regular rate, no murmurs."
                        ),
                        "assessment_and_plan": "Assessment: stable. Plan: monitor.",
                    }
                },
            },
            f,
            ensure_ascii=False,
        )


def _nursing_author_ratio(cif_dir: str) -> float:
    """AD-65 Bug B (Task 12): fraction of nursing docs authored by the assigned nurse.

    Walks `cif_dir/structural/patients/*.json` and, for every
    `ClinicalDocument` whose `loinc_code` is in `NURSING_LOINCS`
    (admission_nursing_assessment 78390-2 / nursing_shift_note 34746-8 /
    nursing_discharge_summary 34745-0), checks whether
    `author_practitioner_id` equals that document's encounter's
    `primary_nurse_id`. Non-nursing documents are ignored entirely (they
    are expected to be authored by `attending_physician_id`, unchanged).

    Returns 1.0 (vacuously) if the CIF directory doesn't have the expected
    structural subtree, or if the cohort has no nursing documents at all —
    same defensive-default convention as `_count_us_hp_ja_chars` /
    `load_hai_antibiogram`'s no-panel-eligible default.
    """
    structural_dir = os.path.join(cif_dir, "structural", "patients")
    if not os.path.isdir(structural_dir):
        return 1.0

    total = 0
    correct = 0
    for patient_path in glob.glob(os.path.join(structural_dir, "*.json")):
        with open(patient_path, encoding="utf-8") as f:
            patient = json.load(f)
        nurse_by_encounter = {
            enc.get("encounter_id", ""): enc.get("primary_nurse_id", "") or ""
            for enc in (patient.get("encounters") or [])
        }
        for doc in patient.get("documents") or []:
            if doc.get("loinc_code") not in NURSING_LOINCS:
                continue
            total += 1
            author = doc.get("author_practitioner_id", "") or ""
            nurse_id = nurse_by_encounter.get(doc.get("encounter_id", ""), "")
            if author and author == nurse_id:
                correct += 1
    return (correct / total) if total else 1.0


def _proof_nursing_author_ratio() -> float:
    """Zero-arg synthetic fixture exercising `_nursing_author_ratio` end to end.

    `lift_firing_proof` is a zero-arg factory (see `_proof_us_hp_ja_chars`
    docstring for the same constraint), so this builds a minimal on-disk
    structural CIF fixture directly (same pattern) rather than receiving a
    real cohort's `cif_dir`.

    Fixture has ONE encounter with a nurse assigned (`NS-IM-001`) and TWO
    documents:
      - a nursing doc (LOINC 78390-2) correctly authored by the nurse
      - a physician doc (LOINC 11506-3, progress note) authored by the
        attending (`DR-IM-001`) — included specifically to prove the ratio
        helper actually FILTERS by `NURSING_LOINCS` rather than checking
        every document's author against the nurse: a naive
        "check all docs" implementation would count the physician doc as a
        mismatch and return 0.5, not 1.0.
    Expected ratio: 1.0.
    """
    with tempfile.TemporaryDirectory() as tmp:
        _write_nursing_author_fixture(
            tmp, encounter_id="enc-nurse-proof", nurse_id="NS-IM-001",
        )
        return _nursing_author_ratio(tmp)


def _proof_nursing_author_fallback_fires_on_missing_nurse() -> bool:
    """F-6b adv-1: verify _pick_document_author falls back to attending when nurse missing.

    Bug B fix relies on a fallback: nursing doc with empty
    `primary_nurse_id` on the encounter should log a warning and use
    `attending_physician_id` — not blank. This proof exercises the
    fallback branch directly (importing `_pick_document_author`) rather
    than round-tripping through fixture files, since the ratio helper
    counts an empty-nurse case as a mismatch (denominator counts, author
    != nurse). Returns True iff fallback picks the attending id.
    """
    from clinosim.modules.document.engine import _pick_document_author

    spec = {"loinc_code": "78390-2"}  # nursing spec
    enc = {
        "encounter_id": "enc-fallback-proof",
        "attending_physician_id": "DR-IM-002",
        "primary_nurse_id": "",  # 欠損 nurse → 落ちるはず
    }
    author = _pick_document_author(spec, enc)
    return author == "DR-IM-002"


def _write_nursing_author_fixture(
    tmp: str, *, encounter_id: str, nurse_id: str,
) -> None:
    """内部: nurse assignment 有 fixture(1 nursing doc + 1 physician doc)を書き出す。"""
    structural_dir = os.path.join(tmp, "structural", "patients")
    os.makedirs(structural_dir, exist_ok=True)

    with open(
        os.path.join(structural_dir, f"pt-{encounter_id}.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(
            {
                "encounters": [
                    {
                        "encounter_id": encounter_id,
                        "attending_physician_id": "DR-IM-001",
                        "primary_nurse_id": nurse_id,
                    }
                ],
                "documents": [
                    {
                        "document_id": f"doc-{encounter_id}-01",
                        "task_type": "admission_nursing_assessment",
                        "loinc_code": "78390-2",
                        "encounter_id": encounter_id,
                        "author_practitioner_id": nurse_id,
                    },
                    {
                        "document_id": f"doc-{encounter_id}-02",
                        "task_type": "progress_note",
                        "loinc_code": "11506-3",
                        "encounter_id": encounter_id,
                        "author_practitioner_id": "DR-IM-001",
                    },
                ],
            },
            f,
        )


def _proof_narrative_pass_populated_ratio() -> float:
    """F-6 adv-1 gate: TemplateNarrativePass populates ClinicalDocument stubs
    with actual narrative content.

    Builds a minimal structural CIF (1 US inpatient patient with 1
    admission_hp stub), runs TemplateNarrativePass, then reads back the
    resulting narrative file and verifies it has either `text` or
    `sections` populated. Returns the ratio populated / total.

    silent-no-op regression: a future refactor that leaves narrative
    generation returning empty NarrativeOutput would produce 0.0 here.
    """
    from clinosim.modules.document.narrative.passes import TemplateNarrativePass

    with tempfile.TemporaryDirectory() as tmp:
        structural = os.path.join(tmp, "structural", "patients")
        os.makedirs(structural, exist_ok=True)
        with open(
            os.path.join(structural, "ENC-narrate-proof.json"),
            "w", encoding="utf-8",
        ) as f:
            json.dump(
                {
                    "patient": {"patient_id": "POP-narrate", "age": 65, "sex": "M"},
                    "encounters": [
                        {
                            "encounter_id": "ENC-narrate-proof",
                            "encounter_type": {"value": "inpatient"},
                        }
                    ],
                    "documents": [
                        {
                            "document_id": "doc-narrate-01",
                            "task_type": "admission_hp",
                            "loinc_code": "34117-2",
                            "format_type": "composition",
                            "narrative": None,
                        }
                    ],
                    "vitals": [],
                    "lab_results": [],
                    "medications": [],
                    "diagnoses": [],
                    "procedures": [],
                    "allergies": [],
                },
                f, ensure_ascii=False,
            )

        TemplateNarrativePass(cif_dir=tmp, country="US", rng_seed=42).run()

        narr_path = os.path.join(
            tmp, "narratives", "template", "documents",
            "ENC-narrate-proof", "doc-narrate-01.json",
        )
        if not os.path.exists(narr_path):
            return 0.0

        with open(narr_path, encoding="utf-8") as f:
            data = json.load(f)
        narrative = data.get("narrative") or {}
        # composition ADMISSION_HP は sections が primary、text は empty のことが多い
        populated = bool(narrative.get("text") or narrative.get("sections"))
        return 1.0 if populated else 0.0


def _proof_structural_cif_zero_narrative_content() -> int:
    """F-6 adv-1 gate: structural CIF must have zero narrative content leak.

    write_cif strips `narrative` from every ClinicalDocument stub (AD-65
    two-pass invariant). Runs write_cif on a synthetic CIFDataset with a
    populated narrative field and counts leaks (should be 0).
    """
    from datetime import date, datetime

    from clinosim.modules.output.cif_writer import write_cif
    from clinosim.types.clinical import ClinicalDocument, ClinicalDocumentNarrative
    from clinosim.types.encounter import Encounter
    from clinosim.types.output import CIFDataset, CIFMetadata, CIFPatientRecord
    from clinosim.types.patient import PatientProfile

    with tempfile.TemporaryDirectory() as tmp:
        doc = ClinicalDocument(
            document_id="doc-leak-01",
            task_type="admission_hp",
            loinc_code="34117-2",
            encounter_id="ENC-leak-1",
            format_type="composition",
            narrative=ClinicalDocumentNarrative(
                text="このテキストは structural CIF に leak してはならない。",
                sections={"hpi": "leak content should not appear"},
                generator="template",
            ),
        )
        patient = PatientProfile(
            patient_id="POP-leak",
            age=65, sex="M",
            date_of_birth=date(1961, 1, 1),
        )
        enc = Encounter(encounter_id="ENC-leak-1")
        record = CIFPatientRecord(
            patient=patient,
            encounters=[enc],
            documents=[doc],
        )
        dataset = CIFDataset(
            metadata=CIFMetadata(
                clinosim_version="0.2",
                generation_timestamp=datetime.now(),
                random_seed=42,
                country="US",
                hospital_scale="medium",
                total_patients_generated=1,
            ),
            patients=[record],
            hospital_roster=[],
            hospital_config={},
        )
        write_cif(dataset, tmp)

        leak_count = 0
        struct_dir = os.path.join(tmp, "structural", "patients")
        for fn in os.listdir(struct_dir):
            with open(os.path.join(struct_dir, fn), encoding="utf-8") as f:
                data = json.load(f)
            for d in data.get("documents") or []:
                # narrative is None (stripped) OR key missing altogether — both OK.
                if d.get("narrative") is not None:
                    leak_count += 1
        return leak_count


def _proof_triage_levels_1_and_5_ratio_min() -> bool:
    """F-6 adv-1 alias gate: canonical named key for triage L1+L5 sensitivity.

    Delegates to the triage_chain audit spec's proof — this key exists so
    a grep for `triage_levels_1_and_5_ratio_min` finds the gate in the
    document_chain proof output too (spec §5.5 promised name). The actual
    L1/L5 computation lives in `clinosim/modules/triage/audit.py:
    _build_triage_severity_proof`; here we just call that helper and
    verify both L1 (severe → level 1) and L5 (mild → level 5) fire.
    """
    from clinosim.modules.triage.audit import _build_triage_severity_proof

    proof = _build_triage_severity_proof()
    checks = {label: actual for label, actual, _expected in proof["equality_checks"]}
    severe_l1 = any("level '1'" in k and checks[k] for k in checks)
    mild_l5 = any("level '5'" in k and checks[k] for k in checks)
    return severe_l1 and mild_l5


def _proof_explicit_population_respected() -> bool:
    """F-6 adv-1 gate (Bug D): SimulatorConfig honors explicit catchment_population.

    Bug D root cause: pre-fix engine.py had a `== 10_000` sentinel that
    silently replaced any explicit CLI value equalling the argparse
    default. The fix removed the sentinel — this proof pins the fixed
    behavior by constructing a SimulatorConfig with an unusual population
    value and asserting the model preserves it untouched.
    """
    from clinosim.types.config import SimulatorConfig

    cfg = SimulatorConfig(random_seed=42, country="US", catchment_population=1234)
    return cfg.catchment_population == 1234


def _proof_nursing_shift_3_per_day() -> dict[str, Any]:
    """α-min-3: prove the daily_3shift dispatch fires with the 3-per-day cadence.

    Runs `document_enricher` on a synthetic LOS=3 completed inpatient
    encounter (dict record — production JSON-deserialized CIF path) and
    summarizes the emitted nursing_shift_note stubs. A regression that
    leaves `daily_3shift` unhandled in the engine dispatch would silently
    emit 0 stubs (PR-90 class: unknown frequency values fall through the
    if/elif with no error) — the count check catches exactly that.

    Returns {"count", "shift_keys", "hours", "ids_unique"} consumed by the
    equality_checks in `_build_document_proof`.
    """
    from datetime import datetime
    from types import SimpleNamespace

    from clinosim.modules.document.engine import document_enricher

    record: dict[str, Any] = {
        "patient": {"patient_id": "pt-3shift-proof"},
        "encounters": [
            {
                "encounter_id": "enc-3shift-proof",
                "encounter_type": "inpatient",
                "status": "completed",
                "admission_datetime": datetime(2026, 7, 1, 10, 0),
                "discharge_datetime": datetime(2026, 7, 4, 10, 0),
                "attending_physician_id": "dr-3shift-proof",
                "primary_nurse_id": "ns-3shift-proof",
            }
        ],
        "documents": [],
        "extensions": {},
        "physiological_states": [],
    }
    ctx = SimpleNamespace(
        master_seed=42,
        records=[record],
        config=SimpleNamespace(country="us"),
    )
    document_enricher(ctx)

    notes = [
        d for d in record["documents"]
        if getattr(d, "task_type", "") == "nursing_shift_note"
    ]
    ids = [d.document_id for d in notes]
    return {
        "count": len(notes),
        "shift_keys": sorted({d.shift for d in notes}),
        "hours": sorted({
            datetime.fromisoformat(d.authored_datetime).hour for d in notes
        }),
        "ids_unique": len(ids) == len(set(ids)),
    }


def _build_document_proof() -> dict[str, Any]:
    """Zero-arg factory: run document FHIR builders on synthetic data.

    Exercises _bb_document_references, _bb_compositions,
    _bb_allergy_intolerances, and _bb_clinical_impressions on synthetic
    ClinicalDocument / Allergy / ClinicalImpressionRecord dicts so that a
    builder silently returning [] without raising would produce count=0
    failures instead of a green audit (PR-90 class of bug; imaging chain
    precedent in modules/imaging/audit.py).

    Uses dict form for ctx.record to exercise the production
    JSON-deserialized CIF path (same as imaging/audit.py _build_imaging_proof).

    Returns equality_checks format: list[tuple[label, actual, expected]].
    The silent_no_op axis iterates and asserts hard equality on each tuple.
    """
    # Lazy imports: defer FHIR builder imports to proof time (avoids import-time
    # overhead; same pattern as imaging/audit.py _build_imaging_proof).
    from clinosim.modules.output._fhir_allergy_intolerance import _bb_allergy_intolerances
    from clinosim.modules.output._fhir_care_team import _bb_care_teams
    from clinosim.modules.output._fhir_clinical_impression import _bb_clinical_impressions
    from clinosim.modules.output._fhir_composition import _bb_compositions
    from clinosim.modules.output._fhir_documents import _bb_document_references
    from clinosim.modules.output._fhir_common import BundleContext
    from clinosim.modules.document import specs_for_encounter_type

    # Synthetic free-text ClinicalDocument (PROGRESS_NOTE, LOINC 11506-3).
    # This is the actual production free_text format (DocumentReference path).
    # admission_hp is composition format in production (→ Composition, not DocumentReference).
    # document_id already carries DOC_REFERENCE_ID_PREFIX so _build_dref_from_clinical_doc
    # returns id == document_id (Stage 1 path; resource_id = _o(doc, "document_id", "")),
    # which starts with "doc-" (DOC_REFERENCE_ID_PREFIX).
    free_text_doc = {
        "document_id": f"{DOC_REFERENCE_ID_PREFIX}enc-proof-hp",
        "task_type": "progress_note",
        "loinc_code": "11506-3",
        "patient_id": "pt-proof",
        "encounter_id": "enc-proof",
        "author_practitioner_id": "dr-proof",
        "authored_datetime": "2026-01-10T08:00:00",
        "language": "en",
        "format_type": "free_text",
        "content_type": "text/plain; charset=utf-8",
        # AD-65 Task 4: content lives in the narrative subtree (merged in by
        # CIFReader in production); the proof supplies it directly so the
        # builder is exercised on a "narrative already generated" stub, same
        # as what CIFReader hands to builders after a NarrativePass has run.
        "narrative": {
            "text": "Chief complaint: chest pain. History of present illness: ...",
            "sections": {},
            "structured": {},
            "generator": "template",
            "generator_metadata": {},
            "generated_at": "2026-01-10T08:00:00Z",
            "facts_used": [],
        },
    }

    # Synthetic composition ClinicalDocument (DISCHARGE_SUMMARY, LOINC 18842-5).
    # Production document_id carries DOC_REFERENCE_ID_PREFIX ("doc-enc-proof-ds").
    # _build_composition strips the "doc-" prefix before prepending COMPOSITION_ID_PREFIX,
    # so Composition.id = "comp-enc-proof-ds" (I-3 fix verifies no double-prefix).
    composition_doc = {
        "document_id": f"{DOC_REFERENCE_ID_PREFIX}enc-proof-ds",
        "task_type": "discharge_summary",
        "loinc_code": "18842-5",
        "patient_id": "pt-proof",
        "encounter_id": "enc-proof",
        "author_practitioner_id": "dr-proof",
        "authored_datetime": "2026-01-15T10:00:00",
        "language": "en",
        "format_type": "composition",
        "content_type": "text/plain; charset=utf-8",
        # AD-65 Task 4: sections live in the narrative subtree (see free_text_doc
        # comment above for the CIFReader-parity rationale).
        "narrative": {
            "text": "",
            "sections": {
                "Discharge Diagnosis": "Community-acquired pneumonia",
                "Disposition": "Home with oral antibiotics",
            },
            "structured": {},
            "generator": "template",
            "generator_metadata": {},
            "generated_at": "2026-01-15T10:00:00Z",
            "facts_used": [],
        },
    }

    # Synthetic Allergy (Penicillin SNOMED 372687004, in clinosim/codes/data/snomed-ct.yaml).
    allergy_data = {
        "allergy_id": "a001",
        "allergen_code": "372687004",
        "allergen_display": "Penicillin",
        "category": "medication",
        "criticality": "high",
        "verification_status": "confirmed",
        "onset_date": None,
        "reactions": [
            {
                "manifestation_snomed": "",
                "manifestation_display": "Rash",
                "severity": "mild",
            }
        ],
    }

    # Synthetic ClinicalImpressionRecord (Day 1 working assessment).
    clinical_impression = {
        "impression_id": f"{CLINICAL_IMPRESSION_ID_PREFIX}enc-proof-1",
        "encounter_id": "enc-proof",
        "date": "2026-01-11",
        "day_index": 1,
        "description": "Patient improving on antibiotics",
        "summary": "Day 1: Fever trending down, WBC improving.",
        "investigation_refs": [],
        "finding_refs": [],
        "prognosis": "Good",
        "practitioner_id": "dr-proof",
    }

    # Synthetic encounter for CareTeam proof (α-min-2 Task 13).
    # nurse_id is non-empty so _bb_care_teams emits participant[1] (nurse slot).
    proof_encounter = {
        "encounter_id": "enc-ct-proof",
        "attending_physician_id": "dr-attending-proof",
        "primary_nurse_id": "nurse-001-proof",
        "admission_datetime": "2026-01-10T08:00:00",
        "discharge_datetime": None,
    }

    # Build BundleContext with dict record (production JSON-deserialized CIF path).
    # encounters list is added for CareTeam builder proof; existing builders
    # (documents / allergy / clinical_impressions) ignore it.
    ctx = BundleContext(
        record={
            "documents": [free_text_doc, composition_doc],
            "patient": {
                "patient_id": "pt-proof",
                "allergies": [allergy_data],
            },
            "extensions": {
                "clinical_impressions": [clinical_impression],
            },
            "encounters": [proof_encounter],
        },
        country="US",
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="pt-proof",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        primary_enc_id="enc-proof",
        patient_sex="M",
    )

    # Run all five builders.
    dref_out = _bb_document_references(ctx)
    comp_out = _bb_compositions(ctx)
    allergy_out = _bb_allergy_intolerances(ctx)
    ci_out = _bb_clinical_impressions(ctx)
    ct_out = _bb_care_teams(ctx)

    # Validate builder outputs before building equality_checks
    # (assert early so failures are surfaced as errors, not silent list-index failures).
    assert dref_out, (
        "document proof: _bb_document_references returned empty list for synthetic input; "
        "builder may be silently no-op (PR-90 class)"
    )
    assert comp_out, (
        "document proof: _bb_compositions returned empty list for synthetic input; "
        "builder may be silently no-op (PR-90 class)"
    )
    assert allergy_out, (
        "document proof: _bb_allergy_intolerances returned empty list for synthetic input; "
        "builder may be silently no-op (PR-90 class)"
    )
    assert ci_out, (
        "document proof: _bb_clinical_impressions returned empty list for synthetic input; "
        "builder may be silently no-op (PR-90 class)"
    )
    assert ct_out, (
        "document proof: _bb_care_teams returned empty list for synthetic encounter input; "
        "builder may be silently no-op (PR-90 class)"
    )

    dref = dref_out[0]
    comp = comp_out[0]
    allergy = allergy_out[0]
    ci = ci_out[0]
    ct = ct_out[0]

    # α-min-2: encounter-type dispatch proof via specs_for_encounter_type.
    outpatient_type_keys = {s.type_key for s in specs_for_encounter_type("outpatient")}
    emergency_type_keys = {s.type_key for s in specs_for_encounter_type("emergency")}
    inpatient_type_keys = {s.type_key for s in specs_for_encounter_type("inpatient")}
    _nursing_type_keys: set[str] = {
        "admission_nursing_assessment",
        "nursing_shift_note",
        "nursing_discharge_summary",
    }

    # α-min-3: nursing 3-shift cadence proof (synthetic LOS=3 → 9 stubs).
    _shift_proof = _proof_nursing_shift_3_per_day()

    return {
        "equality_checks": [
            # --- 4 canonical constants (silent-no-op defense Layer 1-2) ---
            (
                "DOC_REFERENCE_ID_PREFIX",
                DOC_REFERENCE_ID_PREFIX,
                "doc-",
            ),
            (
                "COMPOSITION_ID_PREFIX",
                COMPOSITION_ID_PREFIX,
                "comp-",
            ),
            (
                "ALLERGY_ID_PREFIX",
                ALLERGY_ID_PREFIX,
                "allergy-",
            ),
            (
                "CLINICAL_IMPRESSION_ID_PREFIX",
                CLINICAL_IMPRESSION_ID_PREFIX,
                "ci-",
            ),
            # --- 4 emission count invariants ---
            (
                "DocumentReference emitted when free_text ClinicalDocument in record.documents",
                len(dref_out) > 0,
                True,
            ),
            (
                "Composition emitted when composition ClinicalDocument in record.documents",
                len(comp_out) > 0,
                True,
            ),
            (
                "AllergyIntolerance emitted when patient.allergies non-empty",
                len(allergy_out) > 0,
                True,
            ),
            (
                "ClinicalImpression emitted when extensions.clinical_impressions non-empty",
                len(ci_out) > 0,
                True,
            ),
            # --- 3 ID-prefix reference integrity invariants ---
            (
                "DocumentReference.id starts with DOC_REFERENCE_ID_PREFIX",
                dref["id"].startswith(DOC_REFERENCE_ID_PREFIX),
                True,
            ),
            (
                "Composition.id starts with COMPOSITION_ID_PREFIX",
                comp["id"].startswith(COMPOSITION_ID_PREFIX),
                True,
            ),
            (
                "AllergyIntolerance.id starts with ALLERGY_ID_PREFIX",
                allergy["id"].startswith(ALLERGY_ID_PREFIX),
                True,
            ),
            # --- 5 no-drop invariants (Section 3.4 CIF→FHIR emission matrix) ---
            (
                "no_drop: doc.narrative.text -> DocumentReference.content.attachment.data (base64)",
                bool(dref.get("content", [{}])[0].get("attachment", {}).get("data")),
                True,
            ),
            (
                "no_drop: doc.narrative.sections -> Composition.section[] non-empty",
                len(comp.get("section", [])) > 0,
                True,
            ),
            (
                "no_drop: ClinicalDocument.loinc_code -> DocumentReference.type.coding[0].code",
                dref["type"]["coding"][0]["code"],
                "11506-3",
            ),
            (
                "no_drop: patient.allergies[].allergen_code -> AllergyIntolerance.code.coding[0].code",
                allergy["code"]["coding"][0]["code"],
                "372687004",
            ),
            (
                "no_drop: ClinicalImpressionRecord.description -> ClinicalImpression.description (preserved)",
                ci.get("description"),
                "Patient improving on antibiotics",
            ),
            # --- 1 extra invariant (total = 17) ---
            (
                "ClinicalImpression.id starts with CLINICAL_IMPRESSION_ID_PREFIX",
                ci["id"].startswith(CLINICAL_IMPRESSION_ID_PREFIX),
                True,
            ),
            # === α-min-2 additions (Task 13) — 7 new checks; total = 24 ===
            # --- 1 canonical constant: CARE_TEAM_ID_PREFIX ---
            (
                "CARE_TEAM_ID_PREFIX",
                CARE_TEAM_ID_PREFIX,
                "careteam-",
            ),
            # --- 2 emission + ID-prefix invariants for CareTeam ---
            (
                "CareTeam emitted when encounter in record.encounters",
                len(ct_out) > 0,
                True,
            ),
            (
                "no_drop: encounter.encounter_id → CareTeam.id starts with CARE_TEAM_ID_PREFIX",
                ct["id"].startswith(CARE_TEAM_ID_PREFIX),
                True,
            ),
            # --- 2 CIF → FHIR no-drop invariants for CareTeam fields ---
            (
                "no_drop: encounter.attending_physician_id → CareTeam.participant[0].member.reference",
                ct["participant"][0]["member"]["reference"],
                "Practitioner/dr-attending-proof",
            ),
            (
                "no_drop: encounter.primary_nurse_id → CareTeam.participant[1].member.reference",
                len(ct["participant"]) >= 2,
                True,
            ),
            # --- 3 encounter-type dispatch no-drop invariants ---
            (
                "no_drop: encounter_type='outpatient' → OUTPATIENT_SOAP spec dispatched",
                "outpatient_soap" in outpatient_type_keys,
                True,
            ),
            (
                "no_drop: encounter_type='emergency' → ED_NOTE + ED_TRIAGE_NOTE dispatched",
                {"ed_note", "ed_triage_note"}.issubset(emergency_type_keys),
                True,
            ),
            (
                "no_drop: triage_data.level → ED_TRIAGE_NOTE LOINC 54094-8 in emergency dispatch",
                any(
                    s.loinc_code == "54094-8"
                    for s in specs_for_encounter_type("emergency")
                ),
                True,
            ),
            (
                "no_drop: encounter_type='inpatient' → 3 nursing doc types dispatched",
                _nursing_type_keys.issubset(inpatient_type_keys),
                True,
            ),
            # === AD-65 Bug A addition (Task 11) — 1 new check; total = 25 ===
            (
                "us_admission_hp_zero_ja_chars",
                _proof_us_hp_ja_chars(),
                0,
            ),
            # === AD-65 Bug B addition (Task 12) — 1 new check; total = 26 ===
            (
                "nursing_doc_author_is_nurse_ratio",
                _proof_nursing_author_ratio(),
                1.0,
            ),
            # === adv-1 F-6 additions (spec §5.5 promised gates) ===
            # 4 named gates so grep-by-canonical-name finds them:
            (
                "narrative_pass_populated_narrative_ratio",
                _proof_narrative_pass_populated_ratio(),
                1.0,
            ),
            (
                "structural_cif_zero_narrative_content",
                _proof_structural_cif_zero_narrative_content(),
                0,
            ),
            (
                "triage_levels_1_and_5_ratio_min",
                _proof_triage_levels_1_and_5_ratio_min(),
                True,
            ),
            (
                "explicit_population_respected",
                _proof_explicit_population_respected(),
                True,
            ),
            # === adv-1 F-6b fixture-strengthening gates ===
            # Prove the existing Bug A / Bug B proofs are actually load-bearing,
            # not tautologies that pass regardless of implementation.
            (
                "us_hp_ja_gate_detects_contamination",
                _proof_us_hp_ja_gate_detects_contamination(),
                True,
            ),
            (
                "nursing_author_fallback_fires_on_missing_nurse",
                _proof_nursing_author_fallback_fires_on_missing_nurse(),
                True,
            ),
            # === α-min-3 nursing 3-shift cadence (+3, total = 37) ===
            (
                "nursing_shift_note_3_per_day_count",
                _shift_proof["count"],
                9,  # LOS=3 days × 3 shifts
            ),
            (
                "nursing_shift_note_shift_keys_complete",
                _shift_proof["shift_keys"],
                ["day", "evening", "night"],
            ),
            (
                "nursing_shift_note_shift_hour_offsets",
                _shift_proof["hours"],
                [0, 8, 16],
            ),
        ]
    }


register_audit_module(
    ModuleAuditSpec(
        name="document_chain",
        canonical_constants={
            "doc_reference_id_prefix": (DOC_REFERENCE_ID_PREFIX,),
            "composition_id_prefix": (COMPOSITION_ID_PREFIX,),
            "allergy_id_prefix": (ALLERGY_ID_PREFIX,),
            "clinical_impression_id_prefix": (CLINICAL_IMPRESSION_ID_PREFIX,),
            # α-min-2 addition (Task 13)
            "care_team_id_prefix": (CARE_TEAM_ID_PREFIX,),
        },
        lift_firing_proof=_build_document_proof,
        clinical_acceptance={
            # α-min-1 (5 keys)
            "h_and_p_per_inpatient_encounter": "== 1",
            "progress_note_per_day_per_inpatient": ">= 0.8",
            "discharge_summary_per_completed_inpatient": "== 1",
            "clinical_impression_per_day_per_inpatient": ">= 0.8",
            "allergy_per_patient_distribution": (
                "matches allergens.yaml prevalence ±0.05 (overall 15% ±0.05 baseline-calibrated Task 2)"
            ),
            # α-min-2 additions (8 keys, Task 13 per spec §9.3)
            "care_team_per_encounter": "== 1",
            "triage_data_per_ed_encounter": "== 1",
            "admission_nursing_assessment_per_inpatient_encounter": "== 1",
            # α-min-3: daily_3shift cadence = 3 notes/day (night/day/evening);
            # 0.8 tolerance factor retained from the 1/day era → 3 × 0.8 = 2.4.
            "nursing_shift_note_per_day_per_inpatient": ">= 2.4",
            "nursing_discharge_summary_per_completed_inpatient": "== 1",
            "outpatient_soap_per_outpatient_encounter": "== 1",
            "ed_note_per_ed_encounter": "== 1",
            "ed_triage_note_per_ed_encounter": "== 1",
        },
    )
)
