"""Unit tests for imaging enricher (Tier 1 #2 PR1)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.imaging.engine import imaging_enricher
from clinosim.types.encounter import Order, OrderStatus, OrderType
from clinosim.types.imaging import ImagingStudyRecord


def _make_ctx(record, master_seed=42):
    """Build a minimal EnricherContext-like stub."""
    return SimpleNamespace(
        master_seed=master_seed,
        records=[record],
        config=SimpleNamespace(modules=SimpleNamespace()),
    )


def _make_cr_chest_order(order_id="ORD-pt1-enc1-I01"):
    return Order(
        order_id=order_id,
        encounter_id="enc1",
        patient_id="pt1",
        order_type=OrderType.IMAGING,
        order_code="36572-6",
        display_name="Chest X-ray PA and Lateral",
        urgency="routine",
        clinical_intent="Suspected pneumonia",
        ordered_datetime=datetime(2026, 6, 30, 8, 30),
        status=OrderStatus.PLACED,
        imaging_modality="CR",
        imaging_body_site_code="51185008",
        imaging_views=["PA", "Lateral"],
        imaging_spec_meta={"abnormal_rate_by_severity": {"moderate": 0.7, "severe": 0.9}},
    )


def test_enricher_no_op_when_no_imaging_orders():
    record = SimpleNamespace(
        patient_id="pt1", orders=[],
        extensions={}, disease_id="bacterial_pneumonia", severity="moderate",
    )
    ctx = _make_ctx(record)
    imaging_enricher(ctx)
    assert record.extensions.get("imaging", []) == []


def test_enricher_emits_one_study_per_imaging_order():
    record = SimpleNamespace(
        patient_id="pt1", orders=[_make_cr_chest_order()],
        extensions={}, disease_id="bacterial_pneumonia", severity="moderate",
    )
    ctx = _make_ctx(record)
    imaging_enricher(ctx)
    studies = record.extensions["imaging"]
    assert len(studies) == 1
    s = studies[0]
    assert s.order_id == "ORD-pt1-enc1-I01"
    assert s.modality_code == "CR"
    assert s.body_site_snomed == "51185008"
    assert s.status == "available"
    # CR with 2 views → 2 series, 1 instance each (typical_instances_per_view_range=[1,1])
    assert len(s.series) == 2
    assert {sr.description for sr in s.series} == {"PA view", "Lateral view"}
    assert all(sr.instance_count == 1 for sr in s.series)
    assert s.endpoint_id.startswith("endpoint-")


def test_enricher_skips_cancelled_orders():
    cancelled = _make_cr_chest_order()
    cancelled.status = OrderStatus.CANCELLED
    record = SimpleNamespace(
        patient_id="pt1", orders=[cancelled],
        extensions={}, disease_id="bacterial_pneumonia", severity="moderate",
    )
    ctx = _make_ctx(record)
    imaging_enricher(ctx)
    assert record.extensions.get("imaging", []) == []


def test_enricher_populates_report_from_template():
    record = SimpleNamespace(
        patient_id="pt1", orders=[_make_cr_chest_order()],
        extensions={}, disease_id="bacterial_pneumonia", severity="moderate",
    )
    ctx = _make_ctx(record)
    imaging_enricher(ctx)
    s = record.extensions["imaging"][0]
    assert s.report is not None
    assert s.report.status == "final"
    # Either normal or abnormal template populated — both have non-empty findings + impression.
    assert s.report.findings_text
    assert s.report.impression_text
    # ja copies also populated from template.
    assert s.report.findings_text_ja
    assert s.report.impression_text_ja
    # findings_codes is forward-compat slot (PR1 unpopulated).
    assert s.report.findings_codes == []


def test_enricher_is_deterministic_for_same_seed():
    """Same seed + same order → same Study UID + same series UIDs + same report text."""
    record1 = SimpleNamespace(patient_id="pt1", orders=[_make_cr_chest_order()],
                              extensions={}, disease_id="bacterial_pneumonia",
                              severity="moderate")
    record2 = SimpleNamespace(patient_id="pt1", orders=[_make_cr_chest_order()],
                              extensions={}, disease_id="bacterial_pneumonia",
                              severity="moderate")
    imaging_enricher(_make_ctx(record1, master_seed=42))
    imaging_enricher(_make_ctx(record2, master_seed=42))
    s1, s2 = record1.extensions["imaging"][0], record2.extensions["imaging"][0]
    assert s1.study_instance_uid == s2.study_instance_uid
    assert [x.series_uid for x in s1.series] == [x.series_uid for x in s2.series]
    assert s1.report.findings_text == s2.report.findings_text


def test_enricher_ct_head_emits_axial_series_with_instance_range():
    ct_order = Order(
        order_id="ORD-pt1-enc1-I01",
        encounter_id="enc1", patient_id="pt1",
        order_type=OrderType.IMAGING,
        order_code="30799-1", display_name="CT Head without contrast",
        urgency="stat", clinical_intent="Suspected ICH",
        ordered_datetime=datetime(2026, 6, 30, 8, 30),
        status=OrderStatus.PLACED,
        imaging_modality="CT", imaging_body_site_code="69536005",
        imaging_views=["axial"],
        imaging_spec_meta={"abnormal_rate_by_severity": {"any": 1.0}},
    )
    record = SimpleNamespace(patient_id="pt1", orders=[ct_order],
                             extensions={}, disease_id="hemorrhagic_stroke",
                             severity="severe")
    ctx = _make_ctx(record)
    imaging_enricher(ctx)
    s = record.extensions["imaging"][0]
    assert len(s.series) == 1
    series = s.series[0]
    assert series.modality_code == "CT"
    # CT head instance range = [180, 280]
    assert 180 <= series.instance_count <= 280
