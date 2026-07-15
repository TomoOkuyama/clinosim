"""Imaging chain AD-60 audit module (Tier 1 #2 PR1).

AD-60 plug-in #4 (after hai, antibiotic, order_service_request).

Verifies CIF -> FHIR emission integrity for the imaging pipeline:
ImagingStudy / Endpoint / radiology DiagnosticReport / ServiceRequest.

15 equality_checks in lift_firing_proof guard canonical constants and
no-drop emission paths against PR-90 class silent-no-op regression.

Registered checks:
- canonical_constants: IMAGING_STUDY_ID_PREFIX / ENDPOINT_ID_PREFIX /
  RADIOLOGY_REPORT_ID_PREFIX / IMAGING_CATEGORY_SNOMED /
  IMAGING_CATEGORY_V2_0074 / DICOM_UID_SYSTEM / DICOM_WADO_RS_CONNECTION_TYPE
  (7 constants, import-time ownership enforced via import from canonical owners).
- clinical_acceptance["imaging_basedon_coverage"]: triggers clinical axis
  _check_imaging_basedon gate (100% of ImagingStudy.basedOn SR refs +
  ImagingStudy.endpoint Endpoint refs must resolve; n<30 -> WARN per
  rare-event acceptance pattern).
- lift_firing_proof (_build_imaging_proof): exercises _bb_imaging_studies,
  _bb_endpoints, _build_radiology_dr on a synthetic ImagingStudyRecord.
  15 equality_checks:
    4 canonical constants + 3 emission counts + 3 ref integrity +
    5 no-drop invariants (Section 3.4 emission matrix).

TODO(jp_language_audit): jp_language_checks not implemented — ModuleAuditSpec
does not have a jp_language_checks field. Deferred to a follow-up sweep
(see TODO.md: "imaging chain JP language axis"). When the field is added,
verify: modality / bodySite / DR.code / conclusion / text.div / SR.code in ja.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from clinosim.audit.registry import ModuleAuditSpec, register_audit_module
from clinosim.modules.imaging.engine import (
    ENDPOINT_ID_PREFIX,
    IMAGING_STUDY_ID_PREFIX,
    RADIOLOGY_REPORT_ID_PREFIX,
)
from clinosim.modules.output._fhir_diagnostic_report import _bb_diagnostic_reports
from clinosim.modules.output._fhir_endpoint import DICOM_WADO_RS_CONNECTION_TYPE
from clinosim.modules.output._fhir_imaging_study import DICOM_UID_SYSTEM
from clinosim.modules.output._fhir_service_request import (
    IMAGING_CATEGORY_SNOMED,
    IMAGING_CATEGORY_V2_0074,
    SR_ID_PREFIX,
)
from clinosim.types.imaging import ImagingSeries, ImagingStudyRecord, RadiologyReport


def _build_imaging_proof() -> dict[str, Any]:
    """Zero-arg factory: run imaging FHIR builders on synthetic data.

    Exercises _bb_imaging_studies, _bb_endpoints, _build_radiology_dr on a
    synthetic ImagingStudyRecord (CXR chest, CR modality) so that a builder
    that silently returns [] without raising would produce count=0 failures
    instead of a green audit (PR-90 class of bug, order_service_request
    precedent).

    Returns equality_checks format: list[tuple[label, actual, expected]].
    The silent_no_op axis iterates and asserts hard equality on each tuple.
    """
    # Lazy imports: defer FHIR builder import to proof time (avoids import-time
    # overhead; same pattern as antibiotic/audit.py _build_combined_proof).
    from clinosim.modules.output._fhir_common import BundleContext
    from clinosim.modules.output._fhir_endpoint import _bb_endpoints
    from clinosim.modules.output._fhir_imaging_study import _bb_imaging_studies

    study_uid = "1.2.840.10008.5.1.4.1.1.1.proof.1"
    endpoint_id = f"{ENDPOINT_ID_PREFIX}{study_uid}"
    order_id = "o-cxr-proof"

    study = ImagingStudyRecord(
        study_id=f"{IMAGING_STUDY_ID_PREFIX}enc-proof-0",  # session 51
        study_instance_uid=study_uid,
        encounter_id="enc-proof",
        patient_id="pt-proof",
        order_id=order_id,
        status="available",
        started_datetime=datetime(2026, 1, 10, 8, 0),
        modality_code="CR",
        body_site_snomed="51185008",  # Chest (body_sites.yaml; snomed validated)
        series=[
            ImagingSeries(
                series_uid="1.2.3.4.series-proof-1",
                series_number=1,
                modality_code="CR",
                body_site_snomed="51185008",
                description="PA view",
                instance_count=1,
            )
        ],
        endpoint_id=endpoint_id,
        report=RadiologyReport(
            report_id=f"{RADIOLOGY_REPORT_ID_PREFIX}enc-proof-0",  # session 51
            status="final",
            findings_text="No acute cardiopulmonary process.",
            impression_text="Clear lungs bilaterally.",
            findings_codes=[],  # PR1 default empty -> conclusionCode gate skipped
        ),
    )

    # Use dict form for ctx.record to exercise the production JSON-deserialized
    # path (same as _bb_service_requests proof in order/audit.py).
    ctx = BundleContext(
        record={"extensions": {"imaging": [study]}},
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

    studies_out = _bb_imaging_studies(ctx)
    endpoints_out = _bb_endpoints(ctx)
    all_drs = _bb_diagnostic_reports(ctx)
    radiology_drs = [r for r in all_drs if r.get("id", "").startswith(RADIOLOGY_REPORT_ID_PREFIX)]
    assert radiology_drs, "imaging proof: _bb_diagnostic_reports returned no radiology DR for the synthetic input"
    dr = radiology_drs[0]

    # Collect sets for reference integrity checks.
    endpoint_ids: set[str] = {e["id"] for e in endpoints_out}
    endpoint_refs: set[str] = {ref["reference"].split("/", 1)[1] for s in studies_out for ref in s.get("endpoint", [])}

    return {
        "equality_checks": [
            # --- 4 canonical constants (silent-no-op defense Layer 1-2) ---
            (
                "IMAGING_CATEGORY_SNOMED",
                IMAGING_CATEGORY_SNOMED,
                "363679005",
            ),
            (
                "IMAGING_CATEGORY_V2_0074",
                IMAGING_CATEGORY_V2_0074,
                "RAD",
            ),
            (
                "DICOM_UID_SYSTEM",
                DICOM_UID_SYSTEM,
                "urn:dicom:uid",
            ),
            (
                "DICOM_WADO_RS_CONNECTION_TYPE",
                DICOM_WADO_RS_CONNECTION_TYPE,
                "dicom-wado-rs",
            ),
            # --- 3 emission count invariants ---
            (
                "ImagingStudy count > 0 when ImagingStudyRecord in extensions[imaging]",
                len(studies_out) > 0,
                True,
            ),
            (
                "Endpoint count == ImagingStudy count (1:1 invariant)",
                len(endpoints_out),
                len(studies_out),
            ),
            (
                "Radiology DR emitted when study.report is non-None",
                dr is not None,
                True,
            ),
            # --- 3 reference integrity invariants ---
            (
                "ImagingStudy.basedOn ref starts with ServiceRequest/SR_ID_PREFIX",
                studies_out[0]["basedOn"][0]["reference"].startswith(f"ServiceRequest/{SR_ID_PREFIX}"),
                True,
            ),
            (
                "ImagingStudy.endpoint refs resolve in _bb_endpoints output",
                endpoint_refs.issubset(endpoint_ids),
                True,
            ),
            (
                "ImagingStudy.id starts with IMAGING_STUDY_ID_PREFIX",
                studies_out[0]["id"].startswith(IMAGING_STUDY_ID_PREFIX),
                True,
            ),
            # --- 5 no-drop invariants (Section 3.4 emission matrix) ---
            (
                "findings_text non-empty -> DR.text.div non-empty (no silent drop)",
                bool(dr.get("text", {}).get("div")),
                True,
            ),
            (
                "impression_text non-empty -> DR.conclusion non-empty",
                bool(dr.get("conclusion")),
                True,
            ),
            (
                "ImagingStudy.identifier[0].system == DICOM_UID_SYSTEM",
                studies_out[0]["identifier"][0]["system"],
                DICOM_UID_SYSTEM,
            ),
            (
                "body_site_snomed populated -> series[].bodySite.code emitted",
                studies_out[0]["series"][0]["bodySite"]["code"],
                "51185008",
            ),
            (
                "findings_codes empty -> conclusionCode = Normal SNOMED default (CY8-14 session 48)",
                # findings_codes 空でも normal/abnormal default emit されるように改修。
                # conclusionCode は必ず 1 件、code = 17621005 (Normal) or 263654008 (Abnormal)。
                dr.get("conclusionCode", [{}])[0].get("coding", [{}])[0].get("code") in ("17621005", "263654008"),
                True,
            ),
        ]
    }


register_audit_module(
    ModuleAuditSpec(
        name="imaging_chain",
        canonical_constants={
            "imaging_study_id_prefix": (IMAGING_STUDY_ID_PREFIX,),
            "endpoint_id_prefix": (ENDPOINT_ID_PREFIX,),
            "radiology_report_id_prefix": (RADIOLOGY_REPORT_ID_PREFIX,),
            "imaging_category_snomed": (IMAGING_CATEGORY_SNOMED,),
            "imaging_category_v2": (IMAGING_CATEGORY_V2_0074,),
            "dicom_uid_system": (DICOM_UID_SYSTEM,),
            "dicom_wado_rs_type": (DICOM_WADO_RS_CONNECTION_TYPE,),
        },
        lift_firing_proof=_build_imaging_proof,
        clinical_acceptance={
            "imaging_basedon_coverage": (
                "100% of ImagingStudy.basedOn refs resolve to existing ServiceRequest "
                "and 100% of ImagingStudy.endpoint refs resolve to existing Endpoint "
                "(n<30 ImagingStudy count -> WARN; rare-event tolerated)."
            ),
        },
    )
)
