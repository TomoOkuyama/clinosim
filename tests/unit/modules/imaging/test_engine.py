"""Unit tests for imaging enricher (Tier 1 #2 PR1)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from clinosim.modules.imaging.engine import imaging_enricher
from clinosim.types.encounter import Order, OrderStatus, OrderType


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
        patient_id="pt1",
        orders=[],
        extensions={},
        disease_id="bacterial_pneumonia",
        severity="moderate",
    )
    ctx = _make_ctx(record)
    imaging_enricher(ctx)
    assert record.extensions.get("imaging", []) == []


def test_enricher_emits_one_study_per_imaging_order():
    record = SimpleNamespace(
        patient_id="pt1",
        orders=[_make_cr_chest_order()],
        extensions={},
        disease_id="bacterial_pneumonia",
        severity="moderate",
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
        patient_id="pt1",
        orders=[cancelled],
        extensions={},
        disease_id="bacterial_pneumonia",
        severity="moderate",
    )
    ctx = _make_ctx(record)
    imaging_enricher(ctx)
    assert record.extensions.get("imaging", []) == []


def test_enricher_populates_report_from_template():
    record = SimpleNamespace(
        patient_id="pt1",
        orders=[_make_cr_chest_order()],
        extensions={},
        disease_id="bacterial_pneumonia",
        severity="moderate",
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
    record1 = SimpleNamespace(
        patient_id="pt1",
        orders=[_make_cr_chest_order()],
        extensions={},
        disease_id="bacterial_pneumonia",
        severity="moderate",
    )
    record2 = SimpleNamespace(
        patient_id="pt1",
        orders=[_make_cr_chest_order()],
        extensions={},
        disease_id="bacterial_pneumonia",
        severity="moderate",
    )
    imaging_enricher(_make_ctx(record1, master_seed=42))
    imaging_enricher(_make_ctx(record2, master_seed=42))
    s1, s2 = record1.extensions["imaging"][0], record2.extensions["imaging"][0]
    assert s1.study_instance_uid == s2.study_instance_uid
    assert [x.series_uid for x in s1.series] == [x.series_uid for x in s2.series]
    assert s1.report.findings_text == s2.report.findings_text


def test_enricher_ct_head_emits_axial_series_with_instance_range():
    ct_order = Order(
        order_id="ORD-pt1-enc1-I01",
        encounter_id="enc1",
        patient_id="pt1",
        order_type=OrderType.IMAGING,
        order_code="30799-1",
        display_name="CT Head without contrast",
        urgency="stat",
        clinical_intent="Suspected ICH",
        ordered_datetime=datetime(2026, 6, 30, 8, 30),
        status=OrderStatus.PLACED,
        imaging_modality="CT",
        imaging_body_site_code="69536005",
        imaging_views=["axial"],
        imaging_spec_meta={"abnormal_rate_by_severity": {"any": 1.0}},
    )
    record = SimpleNamespace(
        patient_id="pt1", orders=[ct_order], extensions={}, disease_id="hemorrhagic_stroke", severity="severe"
    )
    ctx = _make_ctx(record)
    imaging_enricher(ctx)
    s = record.extensions["imaging"][0]
    assert len(s.series) == 1
    series = s.series[0]
    assert series.modality_code == "CT"
    # CT head instance range = [180, 280]
    assert 180 <= series.instance_count <= 280


def test_stub_only_path_emits_generic_negative_report():
    """P1-11 (session 88j): orders whose modality/body-site inference fails
    fall into the stub_only path. Prior to the fix these studies had
    ``report=None`` and were silent-dropped by ``_bb_diagnostic_reports``
    (``if report:`` gate); 2,559/2,559 studies in JP p=10000 output had
    zero corresponding DR (RAD). The fix populates a generic negative-
    findings RadiologyReport so every ImagingStudy carries a report.
    """
    unin_order = Order(
        order_id="ORD-unin-01",
        encounter_id="enc1",
        patient_id="pt1",
        order_type=OrderType.IMAGING,
        order_code="XX-UNK",
        display_name="Nonsense unrelated imaging label",  # inference will miss
        urgency="routine",
        clinical_intent="",
        ordered_datetime=datetime(2026, 6, 30, 8, 30),
        status=OrderStatus.PLACED,
        # imaging_modality + imaging_body_site_code intentionally absent
    )
    record = SimpleNamespace(
        patient_id="pt1", orders=[unin_order], extensions={}, disease_id="bacterial_pneumonia", severity="moderate"
    )
    ctx = _make_ctx(record)
    imaging_enricher(ctx)
    studies = record.extensions.get("imaging", [])
    assert len(studies) == 1, "stub-only study must still be emitted"
    s = studies[0]
    # stub path leaves modality/body_site empty (inference failed)
    assert s.modality_code == ""
    assert s.body_site_snomed == ""
    assert s.series == []
    # New contract: report is populated with a generic negative-findings
    # RadiologyReport (never None), so consumers see a matching DR (RAD).
    assert s.report is not None, "stub-only path must emit generic radiology report (P1-11)"
    assert s.report.status == "final"
    assert s.report.findings_text  # non-empty EN
    assert s.report.findings_text_ja  # non-empty JA
    assert s.report.impression_text
    assert s.report.impression_text_ja
    # No acuity claim beyond "no acute findings" — factual only.
    assert "acute" in s.report.impression_text.lower()
    assert "急性期" in s.report.impression_text_ja


def test_template_lookup_valueerror_emits_generic_negative_report():
    """P1-11 (session 88j): unregistered ``disease_id × modality_body_site``
    hits ``_select_report_template``'s forward-coverage ValueError guard.
    Prior behaviour set ``report=None`` (silent drop of DR (RAD)); fix
    populates the same generic negative-findings report used by the
    stub_only path.
    """
    # unknown_condition + CR chest is intentionally NOT in
    # impression_templates.yaml → _select_report_template raises ValueError.
    order = _make_cr_chest_order(order_id="ORD-unreg-01")
    record = SimpleNamespace(
        patient_id="pt1",
        orders=[order],
        extensions={},
        disease_id="unknown_condition_no_template",
        severity="moderate",
    )
    ctx = _make_ctx(record)
    imaging_enricher(ctx)
    studies = record.extensions.get("imaging", [])
    assert len(studies) == 1
    s = studies[0]
    # Modality/body_site are populated (inference succeeded) but the
    # template lookup missed → we still get a generic report.
    assert s.modality_code == "CR"
    assert s.body_site_snomed == "51185008"
    assert s.report is not None, "template-missing path must emit generic radiology report (P1-11)"
    assert s.report.status == "final"
    assert s.report.findings_text
    assert s.report.findings_text_ja
    assert s.report.impression_text
    assert s.report.impression_text_ja


def test_generic_negative_report_content_is_stable():
    """P1-11: the fallback text is a fixed constant, not sampled from a
    template pool — determinism check keeps it in sync between the two
    fallback paths."""
    from clinosim.modules.imaging.engine import _build_generic_negative_report

    r1 = _build_generic_negative_report("enc1", 1)
    r2 = _build_generic_negative_report("enc2", 2)
    assert r1.findings_text == r2.findings_text
    assert r1.impression_text == r2.impression_text
    assert r1.findings_text_ja == r2.findings_text_ja
    assert r1.impression_text_ja == r2.impression_text_ja
    # ids differ (per-encounter/per-order suffix)
    assert r1.report_id != r2.report_id
    assert r1.report_id == "imgrpt-enc1-1"


def _make_head_ct_order(order_id: str, minute_offset: int) -> Order:
    return Order(
        order_id=order_id,
        encounter_id="enc-shared",
        patient_id="pt1",
        order_type=OrderType.IMAGING,
        order_code="30799-1",
        display_name="CT Head without contrast",
        urgency="stat",
        clinical_intent="Suspected ICH",
        ordered_datetime=datetime(2026, 6, 30, 8, minute_offset),
        status=OrderStatus.PLACED,
        imaging_modality="CT",
        imaging_body_site_code="69536005",
        imaging_views=["axial"],
        imaging_spec_meta={"abnormal_rate_by_severity": {"any": 1.0}},
    )


def test_issue_918_head_ct_within_60min_consolidates_to_single_study():
    """Issue #918: 3 head-CT orders in ~20 min on the same encounter
    (audit's `pt-02ee09c03138` shape — 21:20 / 21:37 / 21:40) represent one
    physical scan whose series were fanned out by overlapping order sources
    (admission block + disease protocol + ED workup). Enricher must emit
    exactly one ImagingStudyRecord.
    """
    record = SimpleNamespace(
        patient_id="pt1",
        orders=[
            _make_head_ct_order("ORD-1", 20),
            _make_head_ct_order("ORD-2", 37),
            _make_head_ct_order("ORD-3", 40),
        ],
        extensions={},
        disease_id="hemorrhagic_stroke",
        severity="severe",
    )
    imaging_enricher(_make_ctx(record))
    studies = record.extensions["imaging"]
    assert len(studies) == 1
    assert studies[0].order_id == "ORD-1"
    assert studies[0].modality_code == "CT"


def test_issue_918_head_ct_over_60min_apart_keeps_both_studies():
    """Issue #918: 6-hour-apart head CTs (baseline vs post-intervention
    control) are legitimate repeat imaging and must both survive."""
    record = SimpleNamespace(
        patient_id="pt1",
        orders=[
            Order(
                order_id="ORD-baseline",
                encounter_id="enc-shared",
                patient_id="pt1",
                order_type=OrderType.IMAGING,
                order_code="30799-1",
                display_name="CT Head without contrast",
                urgency="stat",
                clinical_intent="Baseline",
                ordered_datetime=datetime(2026, 6, 30, 8, 30),
                status=OrderStatus.PLACED,
                imaging_modality="CT",
                imaging_body_site_code="69536005",
                imaging_views=["axial"],
                imaging_spec_meta={"abnormal_rate_by_severity": {"any": 1.0}},
            ),
            Order(
                order_id="ORD-control",
                encounter_id="enc-shared",
                patient_id="pt1",
                order_type=OrderType.IMAGING,
                order_code="30799-1",
                display_name="CT Head without contrast",
                urgency="stat",
                clinical_intent="Control",
                ordered_datetime=datetime(2026, 6, 30, 14, 30),
                status=OrderStatus.PLACED,
                imaging_modality="CT",
                imaging_body_site_code="69536005",
                imaging_views=["axial"],
                imaging_spec_meta={"abnormal_rate_by_severity": {"any": 1.0}},
            ),
        ],
        extensions={},
        disease_id="hemorrhagic_stroke",
        severity="severe",
    )
    imaging_enricher(_make_ctx(record))
    studies = record.extensions["imaging"]
    assert len(studies) == 2


def test_issue_918_chest_xray_same_shift_not_consolidated():
    """Issue #918: chest X-ray legitimately repeats within a shift on ICU
    / pneumonia patients (daily portable film). CR is excluded from
    consolidation by design — same-modality same-body-site CR orders at
    different minutes must both survive."""

    def _cr(order_id, minute):
        return Order(
            order_id=order_id,
            encounter_id="enc-icu",
            patient_id="pt1",
            order_type=OrderType.IMAGING,
            order_code="36572-6",
            display_name="Chest X-ray PA",
            urgency="routine",
            clinical_intent="Follow-up",
            ordered_datetime=datetime(2026, 6, 30, 8, minute),
            status=OrderStatus.PLACED,
            imaging_modality="CR",
            imaging_body_site_code="51185008",
            imaging_views=["PA"],
            imaging_spec_meta={"abnormal_rate_by_severity": {"moderate": 0.5}},
        )

    record = SimpleNamespace(
        patient_id="pt1",
        orders=[_cr("ORD-cr1", 15), _cr("ORD-cr2", 30)],
        extensions={},
        disease_id="bacterial_pneumonia",
        severity="moderate",
    )
    imaging_enricher(_make_ctx(record))
    studies = record.extensions["imaging"]
    assert len(studies) == 2


def test_issue_918_different_body_site_not_consolidated():
    """Same modality but different body_site = distinct scans, both preserved."""
    head_ct = _make_head_ct_order("ORD-head", 20)
    chest_ct = Order(
        order_id="ORD-chest",
        encounter_id="enc-shared",
        patient_id="pt1",
        order_type=OrderType.IMAGING,
        order_code="24628-0",
        display_name="CT Chest without contrast",
        urgency="stat",
        clinical_intent="Screen",
        ordered_datetime=datetime(2026, 6, 30, 8, 30),
        status=OrderStatus.PLACED,
        imaging_modality="CT",
        imaging_body_site_code="51185008",
        imaging_views=["axial"],
        imaging_spec_meta={"abnormal_rate_by_severity": {"any": 1.0}},
    )
    record = SimpleNamespace(
        patient_id="pt1",
        orders=[head_ct, chest_ct],
        extensions={},
        disease_id="hemorrhagic_stroke",
        severity="severe",
    )
    imaging_enricher(_make_ctx(record))
    studies = record.extensions["imaging"]
    assert len(studies) == 2


def test_enricher_infers_imaging_metadata_from_legacy_orders():
    """Legacy IMAGING orders without imaging_body_site_code/imaging_modality
    are now imputed via inference module (session 48 CIF-VS-FHIR-01 fix).

    Pre-session-48: silently skipped → 78% of ImagingStudy silent-drop.
    Session 48 added `clinosim/modules/imaging/inference.py` (40+ patterns,
    JP/EN + underscore) so legacy emission sites (inpatient.py + emergency.py)
    produce inferred metadata; silent-drop ratio dropped from 0.22 to 1.00.
    Test updated to reflect the new contract:legacy orders are now included,
    not skipped.
    """
    legacy_order = Order(
        order_id="ORD-legacy",
        encounter_id="enc1",
        patient_id="pt1",
        order_type=OrderType.IMAGING,
        order_code="CT-HEAD",
        display_name="CT Head",
        urgency="stat",
        clinical_intent="Stroke workup",
        ordered_datetime=datetime(2026, 6, 30, 8, 30),
        status=OrderStatus.PLACED,
        # imaging_modality and imaging_body_site_code intentionally absent
    )
    record = SimpleNamespace(
        patient_id="pt1",
        orders=[legacy_order],
        extensions={},
        disease_id="hemorrhagic_stroke",
        severity="severe",
    )
    ctx = _make_ctx(record)
    imaging_enricher(ctx)
    imaging = record.extensions.get("imaging", [])
    assert len(imaging) == 1, "legacy CT-HEAD order must be inferred to one ImagingStudy"
    study = imaging[0]
    # Inference module resolved CT-HEAD → modality CT + body site head
    assert study.modality_code == "CT"
    assert study.encounter_id == "enc1"
    assert study.patient_id == "pt1"
