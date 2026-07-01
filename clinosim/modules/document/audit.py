"""Document chain AD-60 audit module (Tier 1 #3 α-min-1 Task 11; α-min-2 Task 13;
AD-65 Bug A Task 11; AD-65 Bug B Task 12).

AD-60 plug-in #5 (after hai, antibiotic, order_service_request, imaging).

Verifies CIF -> FHIR emission integrity for the document pipeline:
DocumentReference / Composition / AllergyIntolerance / ClinicalImpression / CareTeam.

26+ equality_checks in lift_firing_proof guard canonical constants and
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
  α-min-2 +7 equality_checks (total = 24):
    1 canonical constant (CARE_TEAM_ID_PREFIX) + 2 emission/prefix invariants +
    2 CIF→FHIR no-drop for CareTeam fields + 3 dispatch no-drop invariants
    (outpatient/emergency/inpatient specs_for_encounter_type coverage).
  AD-65 Bug A +1 equality_check (total = 25):
    `us_admission_hp_zero_ja_chars` — see `_count_us_hp_ja_chars` /
    `_proof_us_hp_ja_chars` docstrings. Companion integration test:
    `tests/integration/test_bug_a_us_hp_english_only.py`.
  AD-65 Bug B +1 equality_check (total = 26):
    `nursing_doc_author_is_nurse_ratio` — see `_nursing_author_ratio` /
    `_proof_nursing_author_ratio` docstrings. Companion unit test:
    `tests/unit/test_document_author_selection.py`; companion integration
    test: `tests/integration/test_bug_b_nurse_author.py`.

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

        with open(
            os.path.join(narrative_dir, "doc-enc-proof-hp-01.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(
                {
                    "document_id": "doc-enc-proof-hp-01",
                    "encounter_id": "enc-proof-hp",
                    "narrative": {
                        "sections": {
                            "chief_complaint": "Chest pain",
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
            )

        return _count_us_hp_ja_chars(tmp)


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
        structural_dir = os.path.join(tmp, "structural", "patients")
        os.makedirs(structural_dir, exist_ok=True)

        with open(os.path.join(structural_dir, "pt-proof-nurse.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "encounters": [
                        {
                            "encounter_id": "enc-nurse-proof",
                            "attending_physician_id": "DR-IM-001",
                            "primary_nurse_id": "NS-IM-001",
                        }
                    ],
                    "documents": [
                        {
                            "document_id": "doc-enc-nurse-proof-01",
                            "task_type": "admission_nursing_assessment",
                            "loinc_code": "78390-2",
                            "encounter_id": "enc-nurse-proof",
                            "author_practitioner_id": "NS-IM-001",
                        },
                        {
                            "document_id": "doc-enc-nurse-proof-02",
                            "task_type": "progress_note",
                            "loinc_code": "11506-3",
                            "encounter_id": "enc-nurse-proof",
                            "author_practitioner_id": "DR-IM-001",
                        },
                    ],
                },
                f,
            )

        return _nursing_author_ratio(tmp)


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
            "nursing_shift_note_per_day_per_inpatient": ">= 0.8",
            "nursing_discharge_summary_per_completed_inpatient": "== 1",
            "outpatient_soap_per_outpatient_encounter": "== 1",
            "ed_note_per_ed_encounter": "== 1",
            "ed_triage_note_per_ed_encounter": "== 1",
        },
    )
)
