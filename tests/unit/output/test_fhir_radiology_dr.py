"""Unit tests for _fhir_diagnostic_report radiology variant (Tier 1 #2 PR1).

Tests cover:
- _bb_diagnostic_reports dispatch: radiology DR emitted per ImagingStudy with report.
- category: SNOMED 394914008 + HL7 v2-0074 RAD dual coding (AD-46).
- basedOn → ServiceRequest, imagingStudy → ImagingStudy references.
- conclusion sourced from impression_text.
- text.div carries findings_text + impression_text (no-drop invariant).
- conclusionCode absent when findings_codes empty (conditional gate active).
- JP cohort uses findings_text_ja / impression_text_ja for conclusion + text.div.
- Dict-path coverage (production JSON-deserialized CIF path).
- Existing LAB panel DR path regression: _bb_diagnostic_reports still delegates
  to build_lab_panel_reports for LAB orders (tested implicitly via empty-imaging
  test that confirms zero radiology DRs when no studies present).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from clinosim.modules.output._fhir_diagnostic_report import (
    RADIOLOGY_CATEGORY_SNOMED,
    RADIOLOGY_CATEGORY_V2_0074,
    RADIOLOGY_DR_ID_PREFIX,
    _bb_diagnostic_reports,
    _escape_html,
)
from clinosim.types.imaging import ImagingSeries, ImagingStudyRecord, RadiologyReport


def _make_ctx(studies, orders=None, country="us"):
    return SimpleNamespace(
        record={"extensions": {"imaging": studies}, "orders": orders or []},
        country=country,
        patient_id="pt1",
        primary_enc_id="enc1",
        roster_map={},
        hospital_config={},
        patient_data={},
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
    )


def _sample_study():
    return ImagingStudyRecord(
        study_id="imgst-enc1-1",
        study_instance_uid="2.25.42",  # session 51 prefix production 準拠
        encounter_id="enc1",
        patient_id="pt1",
        order_id="ord1",
        status="available",
        started_datetime=datetime(2026, 6, 30, 10, 0),
        modality_code="CR",
        body_site_snomed="51185008",
        series=[
            ImagingSeries(
                series_uid="2.25.43",
                series_number=1,
                modality_code="CR",
                body_site_snomed="51185008",
                description="PA view",
                instance_count=1,
            )
        ],
        endpoint_id="endpoint-2.25.42",
        report=RadiologyReport(
            report_id="imgrpt-enc1-1",
            status="final",  # session 51
            findings_text="Right lower lobe consolidation.",
            impression_text="Pneumonia.",
        ),
    )


def _rad_drs(ctx):
    return [r for r in _bb_diagnostic_reports(ctx) if r["id"].startswith(RADIOLOGY_DR_ID_PREFIX)]


def test_empty_imaging_emits_no_radiology_dr():
    """No ImagingStudy → no radiology DR (LAB DR may still emit; not tested here)."""
    ctx = _make_ctx([])
    assert _rad_drs(ctx) == []


def test_study_without_report_emits_no_radiology_dr():
    """ImagingStudy with report=None (snapshot mid-study) → no DR."""
    study = _sample_study()
    study.report = None
    ctx = _make_ctx([study])
    assert _rad_drs(ctx) == []


def test_emits_one_radiology_dr_per_study_with_report():
    ctx = _make_ctx([_sample_study()])
    drs = _rad_drs(ctx)
    assert len(drs) == 1
    dr = drs[0]
    assert dr["resourceType"] == "DiagnosticReport"
    assert dr["id"].startswith(RADIOLOGY_DR_ID_PREFIX)


def test_radiology_dr_id_uses_report_id():
    ctx = _make_ctx([_sample_study()])
    dr = _rad_drs(ctx)[0]
    assert dr["id"] == f"{RADIOLOGY_DR_ID_PREFIX}enc1-1"


def test_radiology_dr_category_dual_coding():
    """category must carry SNOMED 394914008 + HL7 v2-0074 RAD (AD-46)."""
    ctx = _make_ctx([_sample_study()])
    dr = _rad_drs(ctx)[0]
    cat_coding = dr["category"][0]["coding"]
    assert any(c["code"] == RADIOLOGY_CATEGORY_SNOMED for c in cat_coding)
    assert any(c["code"] == RADIOLOGY_CATEGORY_V2_0074 for c in cat_coding)


def test_radiology_dr_basedon_and_imaging_study_refs():
    ctx = _make_ctx([_sample_study()])
    dr = _rad_drs(ctx)[0]
    assert dr["basedOn"] == [{"reference": "ServiceRequest/sr-ord1"}]
    assert dr["imagingStudy"] == [{"reference": "ImagingStudy/imgst-enc1-1"}]


def test_radiology_dr_conclusion_from_impression_text():
    ctx = _make_ctx([_sample_study()])
    dr = _rad_drs(ctx)[0]
    assert dr["conclusion"] == "Pneumonia."


def test_radiology_dr_text_div_carries_findings():
    """No-drop invariant: findings_text MUST land in text.div."""
    ctx = _make_ctx([_sample_study()])
    dr = _rad_drs(ctx)[0]
    text = dr["text"]
    assert text["status"] == "generated"
    assert "Right lower lobe consolidation" in text["div"]
    assert "Pneumonia." in text["div"]


def test_radiology_dr_text_div_has_xhtml_ns():
    """FHIR Narrative text.div MUST carry XHTML namespace."""
    ctx = _make_ctx([_sample_study()])
    dr = _rad_drs(ctx)[0]
    assert 'xmlns="http://www.w3.org/1999/xhtml"' in dr["text"]["div"]


def test_radiology_dr_conclusion_code_normal_when_findings_codes_empty():
    """findings_codes empty → conclusionCode = SNOMED 17621005 (Normal).

    Session 48 (FB verify): empty findings_codes semantically means "no abnormal
    findings observed", which is affirmatively emitted as SNOMED 17621005
    (Normal) so downstream consumers can distinguish "unread" from "read-normal".
    Previously (PR1) findings_codes empty → conclusionCode omitted, but that
    conflated the two states and caused JP Core validation to flag missing code.
    """
    ctx = _make_ctx([_sample_study()])
    dr = _rad_drs(ctx)[0]
    assert dr["conclusionCode"] == [
        {
            "coding": [
                {
                    "system": "http://snomed.info/sct",
                    "code": "17621005",
                    "display": "Normal",
                }
            ],
        }
    ]


def test_radiology_dr_conclusion_code_when_findings_codes_set():
    """findings_codes non-empty → conclusionCode emitted (forward-compat gate)."""
    study = _sample_study()
    study.report.findings_codes = ["233604007"]  # Pneumonia (SNOMED)
    ctx = _make_ctx([study])
    dr = _rad_drs(ctx)[0]
    assert "conclusionCode" in dr
    assert dr["conclusionCode"][0]["coding"][0]["code"] == "233604007"


def test_radiology_dr_effective_datetime_from_started():
    ctx = _make_ctx([_sample_study()])
    dr = _rad_drs(ctx)[0]
    assert dr.get("effectiveDateTime", "").startswith("2026-06-30T10:00")


def test_radiology_dr_jp_uses_ja_fields():
    """JP cohort: conclusion + text.div use ja content when ja fields populated."""
    study = _sample_study()
    study.report.findings_text_ja = "右下葉に浸潤影を認める。"
    study.report.impression_text_ja = "肺炎像。"
    ctx = _make_ctx([study], country="jp")
    dr = _rad_drs(ctx)[0]
    assert "肺炎像" in dr["conclusion"]
    assert "浸潤影" in dr["text"]["div"]


def test_radiology_dr_jp_falls_back_to_en_when_ja_empty():
    """JP cohort: when ja fields are empty, fall back to en text."""
    study = _sample_study()
    # findings_text_ja and impression_text_ja are empty (default)
    ctx = _make_ctx([study], country="jp")
    dr = _rad_drs(ctx)[0]
    assert "Pneumonia" in dr["conclusion"]
    assert "consolidation" in dr["text"]["div"]


def test_multiple_studies_emit_multiple_drs():
    """Each study with a report → one DR."""
    study2 = _sample_study()
    study2.study_id = "imgst-enc1-2"
    study2.order_id = "ord2"
    study2.report.report_id = "imgrpt-enc1-2"
    ctx = _make_ctx([_sample_study(), study2])
    drs = _rad_drs(ctx)
    assert len(drs) == 2
    ids = {dr["id"] for dr in drs}
    assert f"{RADIOLOGY_DR_ID_PREFIX}enc1-1" in ids
    assert f"{RADIOLOGY_DR_ID_PREFIX}enc1-2" in ids


# ---------------------------------------------------------------------------
# Dict-path coverage (production CIF is JSON-deserialized → plain dicts)
# ---------------------------------------------------------------------------


def test_radiology_dr_from_dict_path():
    """Production path: ImagingStudyRecord + RadiologyReport as plain dicts."""
    study_dict = {
        "study_id": "imgst-enc1-1",  # session 51
        "study_instance_uid": "2.25.42",
        "encounter_id": "enc1",
        "patient_id": "pt1",
        "order_id": "ord1",
        "status": "available",
        "started_datetime": "2026-06-30T10:00:00",
        "modality_code": "CR",
        "body_site_snomed": "51185008",
        "series": [],
        "endpoint_id": "endpoint-2.25.42",
        "report": {
            "report_id": "imgrpt-enc1-1",  # session 51
            "status": "final",
            "findings_text": "Right lower lobe consolidation.",
            "findings_text_ja": "",
            "impression_text": "Pneumonia.",
            "impression_text_ja": "",
            "findings_codes": [],
        },
    }
    ctx = _make_ctx([study_dict])
    drs = _rad_drs(ctx)
    assert len(drs) == 1
    dr = drs[0]
    assert dr["resourceType"] == "DiagnosticReport"
    assert dr["id"] == f"{RADIOLOGY_DR_ID_PREFIX}enc1-1"
    assert dr["conclusion"] == "Pneumonia."
    assert "consolidation" in dr["text"]["div"]
    cat_coding = dr["category"][0]["coding"]
    assert any(c["code"] == RADIOLOGY_CATEGORY_SNOMED for c in cat_coding)


# ---------------------------------------------------------------------------
# _escape_html unit tests
# ---------------------------------------------------------------------------


def test_escape_html_ampersand():
    assert _escape_html("a&b") == "a&amp;b"


def test_escape_html_angle_brackets():
    assert _escape_html("a < b > c") == "a &lt; b &gt; c"


def test_escape_html_quotes():
    assert _escape_html('say "hi"') == "say &quot;hi&quot;"


def test_escape_html_passthrough_plain():
    assert _escape_html("Normal finding. No acute changes.") == "Normal finding. No acute changes."
