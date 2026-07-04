"""Unit tests for clinosim.types.imaging dataclasses (Tier 1 #2 PR1)."""

from __future__ import annotations

from datetime import datetime

from clinosim.types.imaging import ImagingSeries, ImagingStudyRecord, RadiologyReport


def test_imaging_series_defaults_are_no_op():
    s = ImagingSeries()
    assert s.series_uid == ""
    assert s.series_number == 1
    assert s.modality_code == ""
    assert s.body_site_snomed == ""
    assert s.description == ""
    assert s.instance_count == 0


def test_radiology_report_defaults_carry_empty_findings():
    r = RadiologyReport()
    assert r.report_id == ""
    assert r.status == "final"
    assert r.findings_text == ""
    assert r.findings_text_ja == ""
    assert r.impression_text == ""
    assert r.impression_text_ja == ""
    assert r.findings_codes == []


def test_imaging_study_record_carries_series_and_report():
    series = [ImagingSeries(series_uid="2.25.1", series_number=1,
                            modality_code="CR", body_site_snomed="51185008",
                            description="PA view", instance_count=1)]
    report = RadiologyReport(report_id="imgrpt-enc1-1", status="final",
                             findings_text="Lungs clear.",
                             impression_text="No acute findings.")
    s = ImagingStudyRecord(
        study_id="imgst-enc1-1",
        study_instance_uid="2.25.42",
        encounter_id="enc1",
        patient_id="pt1",
        order_id="ord1",
        status="available",
        started_datetime=datetime(2026, 6, 30, 10, 0),
        modality_code="CR",
        body_site_snomed="51185008",
        series=series,
        endpoint_id="endpoint-2.25.42",
        report=report,
    )
    assert s.study_id == "imgst-enc1-1"
    assert s.report.findings_text == "Lungs clear."
    assert len(s.series) == 1
    assert s.series[0].description == "PA view"


def test_order_imaging_fields_default_no_op():
    """Order 既存 dataclass に imaging_* field 追加 — 既存 disease で no-op."""
    from clinosim.types.encounter import Order, OrderType
    o = Order(order_id="ord1", order_type=OrderType.LAB)
    assert o.imaging_modality == ""
    assert o.imaging_body_site_code == ""
    assert o.imaging_views == []


def test_order_imaging_fields_populated_for_imaging_order():
    from clinosim.types.encounter import Order, OrderType
    o = Order(
        order_id="ord1", order_type=OrderType.IMAGING,
        imaging_modality="CR", imaging_body_site_code="51185008",
        imaging_views=["PA", "Lateral"],
    )
    assert o.imaging_modality == "CR"
    assert o.imaging_views == ["PA", "Lateral"]
