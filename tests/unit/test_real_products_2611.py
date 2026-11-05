"""Issue #2611: supportive medication orders name real products; a 30 mL/kg
bolus is one weight-based dose."""

from __future__ import annotations

import glob
from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

from clinosim.codes.drugs import drug_ref
from clinosim.modules.order.engine import place_admission_orders
from clinosim.modules.order.treatment_classifier import classify_inpatient_supportive
from clinosim.modules.output.fhir_r4.medications.medications import _resolve_medication_concept
from clinosim.simulator.medication_pipeline import _generate_mar
from clinosim.types.encounter import OrderType
from clinosim.types.staff import StaffRoster

pytestmark = pytest.mark.unit

_ADM = datetime(2025, 3, 1, 10, 0)


def _supportive_meds() -> list[tuple[str, str, str]]:
    out = []

    def walk(x: object, name: str) -> None:
        if isinstance(x, dict):
            if isinstance(x.get("detail"), str) and "type" in x:
                if classify_inpatient_supportive(x["detail"], x["type"]) == OrderType.MEDICATION:
                    out.append((name, str(x["type"]), x["detail"]))
            for v in x.values():
                walk(v, name)
        elif isinstance(x, list):
            for v in x:
                walk(v, name)

    for path in sorted(glob.glob("clinosim/modules/disease/reference_data/*.yaml")):
        walk(yaml.safe_load(open(path, encoding="utf-8")), path.rsplit("/", 1)[-1])
    return out


def test_every_supportive_medication_names_a_catalog_drug() -> None:
    unresolved = [
        (n, t, d)
        for n, t, d in _supportive_meds()
        if not (drug_ref(d.split(" or ")[0]) or drug_ref(t.replace("_", " ")))
    ]
    assert not unresolved, unresolved


def test_lactated_ringers_is_coded() -> None:
    concept, _ = _resolve_medication_concept(
        "IV_fluid: Lactated Ringer's 75-100 mL/h until oral intake", "", "US", route="IV"
    )
    assert concept["coding"][0]["code"] == "847630"


def _bolus_order():
    protocol = {
        "order_protocols": {
            "admission_orders": {
                "supportive": [{"type": "IV_fluid", "detail": "Lactated Ringer 30 mL/kg bolus within 3 hours"}]
            }
        }
    }
    orders = place_admission_orders(
        protocol, "P1", "ENC-1", _ADM, "us", np.random.default_rng(1), patient_weight_kg=70.0
    )
    return next(o for o in orders if o.order_type == OrderType.MEDICATION and "Ringer" in o.display_name)


def test_the_sepsis_bolus_is_one_weight_based_dose() -> None:
    order = _bolus_order()
    assert (order.dose_quantity, order.dose_unit, order.single_dose) == (2100.0, "mL", True)
    patient = SimpleNamespace(patient_id="P1", current_medications=[], age=60)
    day0 = _generate_mar(patient, [order], 0, _ADM, roster=StaffRoster(), rng=np.random.default_rng(2))
    day1 = _generate_mar(patient, [order], 1, _ADM, roster=StaffRoster(), rng=np.random.default_rng(3))
    assert len(day0) == 1 and day1 == []
    assert _ADM <= day0[0].actual_datetime <= _ADM.replace(hour=13)
