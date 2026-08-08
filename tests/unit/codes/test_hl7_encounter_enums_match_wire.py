"""HL7 encounter StrEnum wire-value pin (Issue #562).

Each enum member's ``.value`` must equal its HL7-authoritative code string.
A silent renaming of a member's value would break FHIR output because
downstream consumers key on the exact code (e.g. a HAPI validator's
membership check against ``hl7-admit-source`` value-set).

The list below is the canonical wire vocabulary clinosim emits; adding a
member requires (a) citing the spec entry in its docstring in
``clinosim/codes/hl7_encounter.py`` and (b) extending the corresponding
expected map here.
"""

from __future__ import annotations

import pytest

from clinosim.codes.hl7_encounter import ActPriority, AdmitSource, DischargeDisposition

pytestmark = pytest.mark.unit


def test_admit_source_wire_values() -> None:
    expected = {
        AdmitSource.EMD: "emd",
        AdmitSource.OUTP: "outp",
        AdmitSource.HOSP: "hosp",
    }
    for member, code in expected.items():
        assert member.value == code, f"{member.name}.value must be {code!r}"
    assert set(AdmitSource) == set(expected), "AdmitSource members drift — update this test"


def test_discharge_disposition_wire_values() -> None:
    expected = {
        DischargeDisposition.HOME: "home",
        DischargeDisposition.EXP: "exp",
    }
    for member, code in expected.items():
        assert member.value == code, f"{member.name}.value must be {code!r}"
    assert set(DischargeDisposition) == set(expected), "DischargeDisposition members drift — update this test"


def test_act_priority_wire_values() -> None:
    expected = {
        ActPriority.EM: "EM",
        ActPriority.UR: "UR",
        ActPriority.R: "R",
    }
    for member, code in expected.items():
        assert member.value == code, f"{member.name}.value must be {code!r}"
    assert set(ActPriority) == set(expected), "ActPriority members drift — update this test"


def test_str_comparison_still_works() -> None:
    """StrEnum inheritance keeps ``==`` with str intact — legacy comparisons like
    ``encounter.admit_source == "emd"`` continue to work post-migration.
    """
    assert AdmitSource.EMD == "emd"
    assert "emd" == AdmitSource.EMD
    assert DischargeDisposition.HOME == "home"
    assert ActPriority.EM == "EM"
