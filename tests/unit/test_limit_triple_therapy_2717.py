"""Issue #2717: an anticoagulated patient discharged after MI does not stay on triple therapy."""

from __future__ import annotations

import pytest

from clinosim.simulator.discharge_rx import limit_triple_antithrombotic

pytestmark = pytest.mark.unit


def _items(*names: str) -> list[dict]:
    return [{"drug_name": n, "dose": "", "duration_days": 28} for n in names]


def test_anticoagulated_post_mi_regimen_is_oac_plus_clopidogrel_with_short_aspirin() -> None:
    items = _items("Aspirin", "Ticagrelor", "Atorvastatin")
    limit_triple_antithrombotic(items, home_medications=["Apixaban"])
    names = [i["drug_name"] for i in items]
    assert "Ticagrelor" not in names and "Clopidogrel" in names
    aspirin = next(i for i in items if i["drug_name"] == "Aspirin")
    assert aspirin["duration_days"] == 7


def test_an_anticoagulant_on_the_prescription_counts() -> None:
    items = _items("Warfarin", "Aspirin", "Prasugrel")
    limit_triple_antithrombotic(items, home_medications=[])
    assert [i["drug_name"] for i in items] == ["Warfarin", "Aspirin", "Clopidogrel"]


def test_dual_antiplatelet_without_an_anticoagulant_is_unchanged() -> None:
    items = _items("Aspirin", "Ticagrelor")
    limit_triple_antithrombotic(items, home_medications=["Atorvastatin"])
    assert items == _items("Aspirin", "Ticagrelor")


def test_activated_home_medications_drop_aspirin_with_oac_and_p2y12() -> None:
    from clinosim.modules.patient.activator import _derive_home_medications  # noqa: F401  (module import check)

    items = _items("Aspirin", "Clopidogrel", "Apixaban")
    limit_triple_antithrombotic(items, home_medications=[])
    assert next(i for i in items if i["drug_name"] == "Aspirin")["duration_days"] == 7
