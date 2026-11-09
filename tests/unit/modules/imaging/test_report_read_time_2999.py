"""Issue #2999: a radiology report is issued after the study is read.

The imaging enricher gives every report a read time after the study start
(``RadiologyReport.issued_datetime``), from the modality's read-time range in
``modalities.yaml``. The DiagnosticReport emits it as ``issued`` (the study
start stays ``effectiveDateTime``) and the imaging report Composition is
dated at it.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from clinosim.modules.imaging.engine import imaging_enricher, load_modalities, stub_report_read_minutes
from clinosim.modules.output.fhir_r4.documents.imaging_report import _bb_imaging_report_compositions
from clinosim.modules.output.fhir_r4.labs.diagnostic_report import RADIOLOGY_DR_ID_PREFIX, _bb_diagnostic_reports
from clinosim.types.encounter import Order, OrderStatus, OrderType

pytestmark = pytest.mark.unit

_STARTED = datetime(2023, 9, 26, 14, 59)


def _ct_order(order_id: str = "ORD-pt1-enc1-I01", display: str = "CT abdomen and pelvis with contrast") -> Order:
    return Order(
        order_id=order_id,
        encounter_id="enc1",
        patient_id="pt1",
        order_type=OrderType.IMAGING,
        display_name=display,
        urgency="stat",
        ordered_datetime=_STARTED,
        status=OrderStatus.PLACED,
        imaging_modality="CT",
        imaging_body_site_code="818982008",
        imaging_views=["axial"],
        imaging_spec_meta={"abnormal_rate_by_severity": {"moderate": 0.5}, "contrast": True},
    )


def _enrich(*orders: Order) -> list:
    record = SimpleNamespace(
        patient_id="pt1", orders=list(orders), extensions={}, disease_id="appendicitis", severity="moderate"
    )
    imaging_enricher(SimpleNamespace(master_seed=42, records=[record], config=SimpleNamespace()))
    return record.extensions["imaging"]


def _minutes(study) -> float:
    return (study.report.issued_datetime - study.started_datetime).total_seconds() / 60


def test_ct_report_is_issued_within_the_ct_read_time() -> None:
    [study] = _enrich(_ct_order())
    lo, hi = load_modalities()["CT"]["report_read_minutes"]
    assert lo <= _minutes(study) <= hi
    assert study.report.issued_datetime > study.started_datetime


def test_read_time_is_deterministic_per_order() -> None:
    a = _enrich(_ct_order())[0].report.issued_datetime
    b = _enrich(_ct_order())[0].report.issued_datetime
    assert a == b


def test_every_modality_has_a_positive_read_time() -> None:
    for code, mod in load_modalities().items():
        lo, hi = mod["report_read_minutes"]
        assert 1 <= lo <= hi, code


def test_a_study_of_unknown_modality_is_read_after_it_starts() -> None:
    order = _ct_order(display="Unrecognised imaging exam")
    order.imaging_modality = ""
    order.imaging_body_site_code = ""
    [study] = _enrich(order)
    lo, hi = stub_report_read_minutes()
    assert lo <= _minutes(study) <= hi


def _radiology_dr_and_composition(study, country: str = "us") -> tuple[dict, dict]:
    sys.path.insert(0, str(Path(__file__).parents[2] / "output"))
    from test_fhir_radiology_dr import _make_ctx

    ctx = _make_ctx([study], country=country)
    [dr] = [r for r in _bb_diagnostic_reports(ctx) if r["id"].startswith(RADIOLOGY_DR_ID_PREFIX)]
    [comp] = _bb_imaging_report_compositions(ctx)
    return dr, comp


def test_ct_diagnostic_report_is_issued_after_its_effective_time() -> None:
    [study] = _enrich(_ct_order())
    study = replace(study, encounter_id="enc1")
    dr, comp = _radiology_dr_and_composition(study)
    assert dr["effectiveDateTime"].startswith("2023-09-26T14:59:00")
    assert dr["issued"] > dr["effectiveDateTime"]
    assert dr["issued"].startswith(study.report.issued_datetime.isoformat())
    assert comp["date"] == dr["issued"]


def test_a_report_without_a_read_time_keeps_the_study_time() -> None:
    """CIF written before the read time existed: issued falls back to the study start."""
    [study] = _enrich(_ct_order())
    study = replace(study, report=replace(study.report, issued_datetime=None))
    dr, comp = _radiology_dr_and_composition(study)
    assert dr["issued"] == dr["effectiveDateTime"] == comp["date"]
