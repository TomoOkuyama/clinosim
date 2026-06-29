"""Tests for DiagnosticReport.basedOn linkage to ServiceRequest (PR1).

Both Order-dataclass and dict-style fixtures are required (PR-90 lesson,
Task 6 教訓): the basedOn code uses _o() for dual access, and both fixture
types must produce correct basedOn references to prevent a silent-no-op
regression where one access style works but the other is ignored.
"""

from datetime import datetime

from clinosim.modules.output._fhir_common import BundleContext
from clinosim.modules.output._fhir_diagnostic_report import build_lab_panel_reports
from clinosim.types.encounter import Order, OrderResult, OrderStatus, OrderType

# CBC components matching lab_panel_groups.yaml
_CBC_MEMBERS = ["WBC", "Hb", "Hct", "Plt"]
_ENC_ID = "enc1"
_PATIENT_ID = "pt1"
_T = datetime(2026, 6, 29, 8, 5)
_T_ISO = "2026-06-29T08:05:00"


def _make_panel_orders_dataclass(
    panel_key: str, members: list[str], t: datetime
) -> list[Order]:
    """Create Order dataclass instances with results (direct-object path)."""
    out = []
    for i, name in enumerate(members):
        o = Order(
            order_id=f"O{i}",
            encounter_id=_ENC_ID,
            patient_id=_PATIENT_ID,
            order_type=OrderType.LAB,
            order_code="X",
            display_name=name,
            ordered_datetime=t,
            ordered_by="doc1",
            status=OrderStatus.RESULTED,
            panel_key=panel_key,
        )
        o.result = OrderResult(
            result_datetime=t,
            performed_by="tech1",
            lab_name=name,
            value=6.0,
            unit="u",
        )
        out.append(o)
    return out


def _make_panel_orders_dict(
    panel_key: str, members: list[str], t_iso: str
) -> list[dict]:
    """Create dict-style orders with results (JSON-deserialized production path)."""
    return [
        {
            "order_id": f"D{i}",
            "encounter_id": _ENC_ID,
            "patient_id": _PATIENT_ID,
            "order_type": "lab",
            "order_code": "X",
            "display_name": name,
            "urgency": "routine",
            "clinical_intent": "",
            "ordered_datetime": t_iso,
            "ordered_by": "doc1",
            "status": "resulted",
            "panel_key": panel_key,
            "result": {
                "result_datetime": t_iso,
                "performed_by": "tech1",
                "lab_name": name,
                "value": 6.0,
                "unit": "u",
            },
        }
        for i, name in enumerate(members)
    ]


def _make_ctx(orders: list, enc_id: str = _ENC_ID) -> BundleContext:
    """Minimal BundleContext for build_lab_panel_reports testing."""
    return BundleContext(
        record={"orders": orders},
        country="us",
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id=_PATIENT_ID,
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id=enc_id,
        patient_sex="",
    )


# === Dataclass-fixture tests (direct-object path) ===


def test_diagnostic_report_basedon_single_panel_dataclass():
    """CBC panel (Order dataclass) → basedOn = [sr-enc1-CBC-1]."""
    orders = _make_panel_orders_dataclass("CBC", _CBC_MEMBERS, _T)
    ctx = _make_ctx(orders)
    reports = build_lab_panel_reports(ctx)
    cbc_reports = [r for r in reports if "cbc" in r.get("id", "").lower()]
    assert len(cbc_reports) == 1, f"Expected 1 CBC DR, got {len(cbc_reports)}"
    assert "basedOn" in cbc_reports[0], "basedOn missing from CBC DiagnosticReport"
    assert cbc_reports[0]["basedOn"] == [
        {"reference": f"ServiceRequest/sr-{_ENC_ID}-CBC-1"}
    ]


def test_diagnostic_report_basedon_present_on_all_panels_dataclass():
    """Every emitted DiagnosticReport carries basedOn (dataclass path)."""
    orders = _make_panel_orders_dataclass("CBC", _CBC_MEMBERS, _T)
    ctx = _make_ctx(orders)
    reports = build_lab_panel_reports(ctx)
    for r in reports:
        assert "basedOn" in r, f"basedOn missing from {r.get('id')}"
        assert len(r["basedOn"]) >= 1


# === Dict-fixture tests (production JSON-deserialized path) ===


def test_diagnostic_report_basedon_single_panel_dict():
    """CBC panel (dict orders, production path) → basedOn = [sr-enc1-CBC-1]."""
    orders = _make_panel_orders_dict("CBC", _CBC_MEMBERS, _T_ISO)
    ctx = _make_ctx(orders)
    reports = build_lab_panel_reports(ctx)
    cbc_reports = [r for r in reports if "cbc" in r.get("id", "").lower()]
    assert len(cbc_reports) == 1, f"Expected 1 CBC DR, got {len(cbc_reports)}"
    assert "basedOn" in cbc_reports[0], "basedOn missing from CBC DiagnosticReport"
    assert cbc_reports[0]["basedOn"] == [
        {"reference": f"ServiceRequest/sr-{_ENC_ID}-CBC-1"}
    ]


def test_diagnostic_report_basedon_present_on_all_panels_dict():
    """Every emitted DiagnosticReport carries basedOn (dict path)."""
    orders = _make_panel_orders_dict("CBC", _CBC_MEMBERS, _T_ISO)
    ctx = _make_ctx(orders)
    reports = build_lab_panel_reports(ctx)
    for r in reports:
        assert "basedOn" in r, f"basedOn missing from {r.get('id')}"
        assert len(r["basedOn"]) >= 1


def test_diagnostic_report_no_orders_returns_empty():
    """No lab orders → no DiagnosticReports."""
    ctx = _make_ctx([])
    assert build_lab_panel_reports(ctx) == []


def test_diagnostic_report_empty_enc_id_returns_empty():
    """Missing primary_enc_id → no DiagnosticReports (existing guard)."""
    orders = _make_panel_orders_dict("CBC", _CBC_MEMBERS, _T_ISO)
    ctx = _make_ctx(orders, enc_id="")
    assert build_lab_panel_reports(ctx) == []


def test_diagnostic_report_basedon_multi_day_two_srs_dict():
    """Same panel ordered on two days → 2 DRs, each referencing its own SR."""
    t1 = "2026-06-29T08:05:00"
    t2 = "2026-06-30T08:05:00"
    orders = _make_panel_orders_dict("CBC", _CBC_MEMBERS, t1) + _make_panel_orders_dict(
        "CBC", _CBC_MEMBERS, t2
    )
    ctx = _make_ctx(orders)
    reports = build_lab_panel_reports(ctx)
    cbc_reports = [r for r in reports if "cbc" in r.get("id", "").lower()]
    assert len(cbc_reports) == 2, f"Expected 2 CBC DRs (one per day), got {len(cbc_reports)}"
    # Each report has exactly one basedOn reference
    # Day-1 report references sr-enc1-CBC-1; day-2 references sr-enc1-CBC-2
    sr_refs = {r["basedOn"][0]["reference"] for r in cbc_reports}
    assert "ServiceRequest/sr-enc1-CBC-1" in sr_refs
    assert "ServiceRequest/sr-enc1-CBC-2" in sr_refs
