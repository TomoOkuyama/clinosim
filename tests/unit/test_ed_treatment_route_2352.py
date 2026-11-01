"""ED treatment orders carry the route their encounter protocol declares (Issue #2352).

Before, the ED order builder ignored ``treatment[].route`` and the medication
enricher guessed a route from the drug name, which defaults to PO: lidocaine
infiltration, eye drops, nasal drops, tetanus toxoid and IV methylprednisolone
were all ordered by mouth.
"""

from __future__ import annotations

import copy
import glob
from datetime import datetime

import pytest
import yaml

from clinosim import determinism
from clinosim.codes.drugs import route_class
from clinosim.locale.loader import load_demographics
from clinosim.modules.encounter.protocol import load_encounter_condition
from clinosim.modules.order.treatment_classifier import classify_encounter_treatment
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population.engine import PersonRecord
from clinosim.modules.staff.engine import generate_roster
from clinosim.simulator.emergency import _simulate_ed_visit
from clinosim.types.encounter import OrderType

pytestmark = pytest.mark.unit


def _medication_entries() -> list[tuple[str, dict]]:
    out = []
    for path in sorted(glob.glob("clinosim/modules/encounter/reference_data/*.yaml")):
        for tx in (yaml.safe_load(open(path, encoding="utf-8")) or {}).get("treatment") or []:
            for name in sorted({tx.get("name", ""), *(tx.get("locale_name") or {}).values()}):
                if classify_encounter_treatment(name) == OrderType.MEDICATION:
                    out.append((f"{path.rsplit('/', 1)[-1]}:{name}", tx))
    return out


@pytest.mark.parametrize(("where", "tx"), _medication_entries(), ids=lambda v: v if isinstance(v, str) else "")
def test_every_medication_treatment_declares_an_administration_route(where: str, tx: dict) -> None:
    assert route_class(str(tx.get("route") or "")), f"{where}: route {tx.get('route')!r}"


@pytest.mark.parametrize(
    ("condition", "drug", "route"),
    [
        ("minor_laceration", "Lidocaine 1% local infiltration", "infiltration"),
        ("minor_laceration", "Tetanus toxoid booster", "IM"),
        ("eye_foreign_body", "Ofloxacin ophthalmic drops", "OPH"),
    ],
)
def test_ed_order_keeps_the_protocol_route(condition: str, drug: str, route: str) -> None:
    cond = copy.deepcopy(load_encounter_condition(condition))
    for tx in cond["treatment"]:
        tx["probability"] = 1.0
    rng = determinism.default_rng(5)
    roster = generate_roster("medium", "US", rng)
    person = PersonRecord(
        person_id="T-1", household_id="H-1", age=40, sex="M", date_of_birth=datetime(1984, 1, 1).date()
    )
    patient = activate_patient(person, rng, load_demographics("US"))
    record = _simulate_ed_visit(patient, cond, datetime(2024, 6, 1, 14, 0), roster, rng, country="US")
    orders = {o.display_name: o for o in record.orders}
    assert orders[drug].route == route
