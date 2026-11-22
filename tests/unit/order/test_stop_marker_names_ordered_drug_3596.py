"""A stop marker names a drug the stay ordered (Issue #3596).

``treatment_modifications.<day>.stop`` is not keyed by country, so a stop of a
drug the country's first-line regimen never gave (cefmetazole in a US stay)
wrote a ``DISCONTINUE:`` marker for a drug that was never ordered.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import clinosim
from clinosim.codes.drugs import same_drug
from clinosim.datafiles import load_data_yaml
from clinosim.simulator.engine import run_forced
from clinosim.types.config import ForcedScenario, SimulatorConfig
from clinosim.types.encounter import OrderType

pytestmark = pytest.mark.unit

_REF = Path(clinosim.__file__).parent / "modules/disease/reference_data"


def _stop_archetypes() -> list[tuple[str, str]]:
    out = []
    for path in sorted(_REF.glob("*.yaml")):
        data = load_data_yaml(path)
        for name, arch in (data.get("course_archetypes") or {}).items():
            mods = (arch or {}).get("treatment_modifications") or {}
            if any(isinstance(m, dict) and m.get("stop") for m in mods.values()):
                out.append((path.stem, name))
    return out


def test_inventory_is_not_empty() -> None:
    assert ("acute_cholecystitis", "treatment_resistant") in _stop_archetypes()


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize(("disease", "archetype"), _stop_archetypes())
def test_no_stop_marker_for_a_drug_never_ordered(disease: str, archetype: str, country: str) -> None:
    dataset = run_forced(
        ForcedScenario(disease_id=disease, count=6, archetype=archetype),
        SimulatorConfig(random_seed=500, country=country),
    )
    bad: list[str] = []
    for record in dataset.patients:
        orders = list(record.orders)
        for o in orders:
            name = o.display_name or ""
            if o.order_type != OrderType.MEDICATION or not name.startswith("DISCONTINUE:"):
                continue
            drug = name.removeprefix("DISCONTINUE:").strip()
            if not any(
                not (p.display_name or "").startswith("DISCONTINUE:")
                and p.order_type == OrderType.MEDICATION
                and p.encounter_id == o.encounter_id
                and same_drug(p.drug_id or p.display_name, drug)
                for p in orders
            ):
                bad.append(f"{disease}/{archetype} {country}: {name}")
    assert not bad, sorted(set(bad))
