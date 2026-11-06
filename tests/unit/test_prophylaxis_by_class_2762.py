"""Issue #2762: the therapeutic-anticoagulant skip is decided by drug class, not name substrings."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.prophylaxis.engine import should_skip_dvt_prophylaxis

pytestmark = pytest.mark.unit

_ENC = SimpleNamespace(encounter_id="E1", admission_datetime=datetime(2025, 3, 1, 9))


def _skip(*meds: object) -> tuple[bool, str]:
    patient = SimpleNamespace(patient_id="P1", age=70, current_medications=list(meds))
    return should_skip_dvt_prophylaxis(patient=patient, encounter=_ENC, admission_dx_code="J18.9")


@pytest.mark.parametrize("name", ["Eliquis", "Xarelto", "Warfarin", "アピキサバン"])
def test_an_oral_anticoagulant_by_any_name_skips(name: str) -> None:
    assert _skip(SimpleNamespace(drug_name=name, frequency="daily")) == (True, "therapeutic_anticoagulant_active")


def test_a_heparin_infusion_skips_but_prophylactic_heparin_does_not() -> None:
    assert _skip(SimpleNamespace(drug_name="Heparin", frequency="continuous"))[0]
    assert not _skip(SimpleNamespace(drug_name="Heparin", frequency="BID"))[0]


def test_an_antiplatelet_is_not_a_therapeutic_anticoagulant() -> None:
    # (Aspirin may still skip through the drug-safety pair check, not this rule.)
    assert _skip(SimpleNamespace(drug_name="Aspirin", frequency="daily"))[1] != "therapeutic_anticoagulant_active"
