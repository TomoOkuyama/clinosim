"""Elective admissions are scheduled stays: admit source outp, priority EL, no ED companion."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.codes.hl7_encounter import ActPriority, AdmitSource
from clinosim.simulator.inpatient import _admission_route_fields

pytestmark = pytest.mark.unit


def test_elective_route_is_outpatient_scheduled() -> None:
    proto = SimpleNamespace(admission_route="elective")
    assert _admission_route_fields(proto, "elective_knee_arthroplasty") == (AdmitSource.OUTP, ActPriority.EL)


def test_default_route_keeps_ed_admission() -> None:
    proto = SimpleNamespace(admission_route="emergency")
    source, priority = _admission_route_fields(proto, "bacterial_pneumonia")
    assert source == AdmitSource.EMD
    assert priority in (ActPriority.EM, ActPriority.UR)


def test_arthroplasty_protocol_loads_as_elective() -> None:
    from clinosim.modules.disease.protocol import load_disease_protocol

    proto = load_disease_protocol("elective_knee_arthroplasty")
    assert proto.admission_route == "elective"
    assert proto.requires_surgery is True
