"""Cycle 3 C3-NEW-1 — activator must union base-regimen home meds with
any pre-existing current_medications (not skip derivation when non-empty).

Previously the activator short-circuited `_derive_home_medications` behind
`if not current_meds:` — but the longitudinal engine's Phase 4a / 4b.1
escalation events (htn_escalate_third_agent_i10, dm_escalate_insulin_e11,
lipid_escalate_*) can fire during `advance_population` BEFORE the first
`activate_patient` call for a patient, pre-populating
`person.current_medications` with just the escalation drug (e.g. HCTZ).
The gate then skipped the chronic-base derivation and the base regimen
(Amlodipine for I10, Metformin for E11.9, Atorvastatin for E78) was
never sampled. Audit: 48 % of multi-chronic adults carried ≤1 med at
p=2000 US seed=42 5y (Issue #1745).

Fix: always derive the chronic regimen and union with Layer-1 meds
(dedup by drug_name). RNG-shape neutral — the per-patient
chronic_medication_seed sub-RNG is independent of year_rng.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from clinosim.locale.loader import load_demographics
from clinosim.modules.patient.activator import activate_patient
from clinosim.types.patient import HomeMedication
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit

_DEMO = load_demographics("US")


def _hypertensive() -> PersonRecord:
    return PersonRecord(
        person_id="P-C3-NEW1",
        household_id="H",
        sex="M",
        age=55,
        date_of_birth=date(1969, 1, 1),
        chronic_conditions=["I10"],
    )


def test_activator_adds_base_regimen_when_escalation_drug_already_present() -> None:
    """An I10 patient who already carries HCTZ (as if a Phase 4b.1
    htn_escalate_third_agent event fired during advance_population before
    activation) MUST still receive Amlodipine (the implicit-prob-1.0
    base regimen for I10 in chronic_medications.yaml)."""
    person = _hypertensive()
    person.current_medications = [
        HomeMedication(drug_name="Hydrochlorothiazide", dose="25mg", route="PO", frequency="daily"),
    ]
    profile = activate_patient(person, np.random.default_rng(0), _DEMO, as_of_year=2024)
    drug_names = {m.drug_name for m in profile.current_medications}
    assert "Hydrochlorothiazide" in drug_names, "pre-existing escalation drug must be preserved"
    assert "Amlodipine" in drug_names, (
        "base I10 regimen (Amlodipine, implicit prob=1.0) must be derived "
        f"even when pre-existing meds present; got {sorted(drug_names)}"
    )


def test_activator_does_not_duplicate_meds_on_union() -> None:
    """When the pre-existing current_medications already contains a drug
    that the base derivation would also pick (e.g. Amlodipine via I10),
    the union must dedup by drug_name — exactly one entry per drug."""
    person = _hypertensive()
    person.current_medications = [
        HomeMedication(drug_name="Amlodipine", dose="5mg", route="PO", frequency="daily"),
    ]
    profile = activate_patient(person, np.random.default_rng(0), _DEMO, as_of_year=2024)
    amlo = [m for m in profile.current_medications if m.drug_name == "Amlodipine"]
    assert len(amlo) == 1, f"expected exactly 1 Amlodipine entry after union-dedup, got {len(amlo)}: {amlo}"
