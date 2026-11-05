"""Issue #2608: emit-time de-duplication never strands an administration."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.newborn.enricher import _add_orders_for_administrations
from clinosim.modules.output.fhir_r4.lib.inline_bb import _dedup_medication_requests
from clinosim.modules.output.fhir_r4.medications.medications import _dedup_same_class_orders
from clinosim.types.encounter import MedicationAdministration

pytestmark = pytest.mark.unit


def _mr(mid: str, text: str, dose: str = "1 tab") -> dict:
    return {
        "id": mid,
        "subject": {"reference": "Patient/P1"},
        "authoredOn": "2025-02-19T10:00:00Z",
        "medicationCodeableConcept": {"text": text},
        "dosageInstruction": [{"text": dose, "route": {"coding": [{"code": "26643006"}]}}],
    }


def test_an_exact_duplicate_hands_its_administrations_to_the_kept_request() -> None:
    aliases: dict[str, str] = {}
    kept = _dedup_medication_requests([_mr("mr-a", "Pip/Tazo"), _mr("mr-b", "Pip/Tazo")], aliases=aliases)
    assert [m["id"] for m in kept] == ["mr-a"] and aliases == {"mr-b": "mr-a"}


def test_an_administered_request_is_not_dropped_as_a_same_class_duplicate() -> None:
    mrs = [_mr("mr-arb", "Candesartan"), _mr("mr-ace", "Enalapril")]
    assert [m["id"] for m in _dedup_same_class_orders(mrs)] == ["mr-arb"]
    assert [m["id"] for m in _dedup_same_class_orders(mrs, protected={"mr-ace"})] == ["mr-arb", "mr-ace"]


def test_newborn_prophylaxis_has_its_order() -> None:
    enc = SimpleNamespace(
        encounter_id="ENC-B", admission_datetime=datetime(2025, 5, 1, 10), attending_physician_id="DR-OB-001"
    )
    rec = SimpleNamespace(patient=SimpleNamespace(patient_id="P1-BABY"), encounters=[enc], orders=[])
    mar = MedicationAdministration(
        order_id="ORD-ENC-B-VITK",
        drug_name="Vitamin K1 (phytonadione) 1 mg IM",
        scheduled_datetime=datetime(2025, 5, 1, 16),
        actual_datetime=datetime(2025, 5, 1, 16),
        route="IM",
    )
    _add_orders_for_administrations(rec, [mar, mar])
    assert [o.order_id for o in rec.orders] == ["ORD-ENC-B-VITK"]
    assert rec.orders[0].route == "IM" and rec.orders[0].ordered_datetime <= mar.actual_datetime


def test_the_request_kept_for_an_administered_duplicate_is_not_dropped_by_class() -> None:
    """HM Pantoprazole duplicates an earlier (stopped) Pantoprazole order and is
    administered; the kept Pantoprazole must survive the PPI class rule."""
    aliases: dict[str, str] = {}
    mrs = [_mr("mr-omep", "Omeprazole", "80mg"), _mr("mr-panto-1", "Pantoprazole"), _mr("mr-panto-hm", "Pantoprazole")]
    unique = _dedup_medication_requests(mrs, aliases=aliases)
    protected = {"mr-panto-hm"} | {aliases[i] for i in ["mr-panto-hm"] if i in aliases}
    assert "mr-panto-1" in {m["id"] for m in _dedup_same_class_orders(unique, protected=protected)}
