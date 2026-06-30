"""Document chain AD-60 audit module (Tier 1 #3 α-min-1 Task 11).

AD-60 plug-in #5 (after hai, antibiotic, order_service_request, imaging).

Verifies CIF -> FHIR emission integrity for the document pipeline:
DocumentReference / Composition / AllergyIntolerance / ClinicalImpression.

15+ equality_checks in lift_firing_proof guard canonical constants and
no-drop emission paths against PR-90 class silent-no-op regression.

Registered checks:
- canonical_constants: DOC_REFERENCE_ID_PREFIX / COMPOSITION_ID_PREFIX /
  ALLERGY_ID_PREFIX / CLINICAL_IMPRESSION_ID_PREFIX
  (4 constants, import-time ownership enforced via import from clinosim.modules.document).
- clinical_acceptance: per-encounter doc count + ClinicalImpression daily
  emission + AllergyIntolerance distribution targets for Task 12 DQR gate.
- lift_firing_proof (_build_document_proof): exercises _bb_document_references,
  _bb_compositions, _bb_allergy_intolerances, _bb_clinical_impressions on
  synthetic ClinicalDocument / Allergy / ClinicalImpressionRecord inputs.
  17 equality_checks:
    4 canonical constants + 4 emission counts + 3 ID-prefix invariants +
    5 no-drop invariants (Section 3.4 CIF→FHIR emission matrix) + 1 extra.

TODO(jp_language_audit): jp_language_checks not implemented — ModuleAuditSpec
does not have a jp_language_checks field. Deferred to a follow-up sweep
(see TODO.md: "document chain JP language axis"). When the field is added,
verify: DocumentReference.type.coding[].display in ja / Composition.section[].title
in ja / AllergyIntolerance.code.text in ja / ClinicalImpression.description in ja.
"""

from __future__ import annotations

from typing import Any

from clinosim.audit.registry import ModuleAuditSpec, register_audit_module
from clinosim.modules.document import (
    ALLERGY_ID_PREFIX,
    CLINICAL_IMPRESSION_ID_PREFIX,
    COMPOSITION_ID_PREFIX,
    DOC_REFERENCE_ID_PREFIX,
)


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
    from clinosim.modules.output._fhir_clinical_impression import _bb_clinical_impressions
    from clinosim.modules.output._fhir_composition import _bb_compositions
    from clinosim.modules.output._fhir_documents import _bb_document_references
    from clinosim.modules.output._fhir_common import BundleContext

    # Synthetic free-text ClinicalDocument (ADMISSION_HP, LOINC 34117-2).
    # document_id already carries DOC_REFERENCE_ID_PREFIX so _build_dref_from_clinical_doc
    # returns id == document_id (Stage 1 path; resource_id = _o(doc, "document_id", "")),
    # which starts with "doc-" (DOC_REFERENCE_ID_PREFIX).
    free_text_doc = {
        "document_id": f"{DOC_REFERENCE_ID_PREFIX}enc-proof-hp",
        "task_type": "admission_hp",
        "loinc_code": "34117-2",
        "patient_id": "pt-proof",
        "encounter_id": "enc-proof",
        "author_practitioner_id": "dr-proof",
        "authored_datetime": "2026-01-10T08:00:00",
        "language": "en",
        "text": "Chief complaint: chest pain. History of present illness: ...",
        "text_source": "template",
        "format_type": "free_text",
        "content_type": "text/plain; charset=utf-8",
    }

    # Synthetic composition ClinicalDocument (DISCHARGE_SUMMARY, LOINC 18842-5).
    # _build_composition constructs id = f"{COMPOSITION_ID_PREFIX}{doc_id}"
    # so document_id should NOT include the prefix (to avoid "comp-comp-...").
    composition_doc = {
        "document_id": "enc-proof-ds",
        "task_type": "discharge_summary",
        "loinc_code": "18842-5",
        "patient_id": "pt-proof",
        "encounter_id": "enc-proof",
        "author_practitioner_id": "dr-proof",
        "authored_datetime": "2026-01-15T10:00:00",
        "language": "en",
        "text": "",
        "sections": {
            "Discharge Diagnosis": "Community-acquired pneumonia",
            "Disposition": "Home with oral antibiotics",
        },
        "text_source": "template",
        "format_type": "composition",
        "content_type": "text/plain; charset=utf-8",
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

    # Build BundleContext with dict record (production JSON-deserialized CIF path).
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

    # Run all four builders.
    dref_out = _bb_document_references(ctx)
    comp_out = _bb_compositions(ctx)
    allergy_out = _bb_allergy_intolerances(ctx)
    ci_out = _bb_clinical_impressions(ctx)

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

    dref = dref_out[0]
    comp = comp_out[0]
    allergy = allergy_out[0]
    ci = ci_out[0]

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
                "no_drop: ClinicalDocument.text -> DocumentReference.content.attachment.data (base64)",
                bool(dref.get("content", [{}])[0].get("attachment", {}).get("data")),
                True,
            ),
            (
                "no_drop: ClinicalDocument.sections -> Composition.section[] non-empty",
                len(comp.get("section", [])) > 0,
                True,
            ),
            (
                "no_drop: ClinicalDocument.loinc_code -> DocumentReference.type.coding[0].code",
                dref["type"]["coding"][0]["code"],
                "34117-2",
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
        },
        lift_firing_proof=_build_document_proof,
        clinical_acceptance={
            "doc_count_per_encounter": (
                "Each inpatient encounter emits >= 1 DocumentReference (ADMISSION_HP or "
                "PROGRESS_NOTE) and >= 1 Composition (DISCHARGE_SUMMARY); "
                "n<30 DocumentReference count -> WARN per rare-event acceptance pattern."
            ),
            "clinical_impression_daily_coverage": (
                "ClinicalImpression emitted for each inpatient day (day_index 0..LOS-1); "
                "verified by Task 12 DQR gate audit run."
            ),
            "allergy_intolerance_distribution": (
                "AllergyIntolerance emitted for each Allergy in patient.allergies; "
                "medication category expected in >= 70% of allergy records."
            ),
        },
    )
)
