"""Every ``workup.labs`` entry of every encounter protocol is a lab the loader knows (#3916).

The ED and outpatient loops silently skip a lab entry that is not a lab analyte, so an
ECG filed under ``labs`` (as ``syncope.yaml`` once did) was dropped without a trace.
"""

import pytest

from clinosim.locale.loader import load_code_mapping
from clinosim.modules.encounter.protocol import load_all_encounter_conditions, load_encounter_condition
from clinosim.modules.observation.engine import canonical_lab_name, is_qualitative_test, lab_panel_components
from clinosim.modules.observation.microbiology import specimen_for_order
from clinosim.modules.observation.order_routing import _routing, lab_order_targets
from clinosim.types.encounter import OrderType

pytestmark = pytest.mark.unit


def _is_known_lab(test: str) -> bool:
    """A lab the loader knows: a coded analyte, a panel, a qualitative test or a culture.

    A vital sign or a history item is declared in ``order_routing.yaml`` as deliberately
    not an order (Issue #2583), so it is not a silent drop; an unknown name is.
    """
    routing = _routing()
    if test in routing["vital_signs"] or test in routing["history"]:
        return True
    targets = lab_order_targets(test)
    if not targets or any(t.order_type != OrderType.LAB for t in targets):
        return False
    coded = load_code_mapping("lab", "US")
    return all(
        canonical_lab_name(t.name) in coded
        or bool(lab_panel_components(t.name))
        or is_qualitative_test(canonical_lab_name(t.name))
        or bool(specimen_for_order(t.name))
        for t in targets
    )


def test_every_protocol_lab_entry_is_a_known_lab_analyte() -> None:
    unknown = sorted(
        f"{cid}: {spec.get('test')}"
        for cid, data in load_all_encounter_conditions().items()
        for spec in (data.get("workup") or {}).get("labs") or []
        if not _is_known_lab(str(spec.get("test", "")))
    )
    assert not unknown, f"workup.labs entries that are not lab analytes (move to imaging): {unknown}"


def test_syncope_ecg_is_an_imaging_entry() -> None:
    workup = load_encounter_condition("syncope")["workup"]
    assert "ECG" not in [s["test"] for s in workup["labs"]]
    ecg = [s for s in workup["imaging"] if s["test"] == "ECG"]
    assert ecg and ecg[0]["probability"] == 0.95
