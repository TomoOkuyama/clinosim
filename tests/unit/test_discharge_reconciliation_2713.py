"""Issue #2713: a discharge prescription does not add a drug of a class it already holds."""

from __future__ import annotations

import pytest

from clinosim.modules import drug_safety

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("candidate", "on_rx", "rule"),
    [
        ("Clopidogrel", "Ticagrelor", "p2y12-plus-p2y12"),
        ("Warfarin", "Apixaban", "doac-plus-vka"),
        ("Candesartan", "Lisinopril", "acei-plus-arb"),
        ("Atorvastatin", "Rosuvastatin", "statin-plus-statin"),
        ("Carvedilol", "Bisoprolol", "beta-blocker-plus-beta-blocker"),  # Issue #3274
    ],
)
def test_the_class_duplicate_is_a_reconciled_conflict(candidate: str, on_rx: str, rule: str) -> None:
    verdicts = drug_safety.check_candidate_against_active(candidate, [on_rx])
    assert rule in {v.rule_id for v in verdicts}
    assert rule in drug_safety.discharge_reconciliation_rules()


def test_an_indication_dependent_combination_is_not_reconciled() -> None:
    verdicts = drug_safety.check_candidate_against_active("Warfarin", ["Aspirin"])
    assert not {v.rule_id for v in verdicts} & drug_safety.discharge_reconciliation_rules()


def _discharge_items(patient, disease_id: str, country_key: str) -> list[str]:
    from datetime import datetime

    import numpy as np

    from clinosim.modules.disease.protocol import load_disease_protocol
    from clinosim.simulator.discharge_rx import build_discharge_rx

    rx = build_discharge_rx(
        patient,
        disease_id,
        load_disease_protocol(disease_id),
        "PR-1",
        datetime(2026, 1, 1),
        np.random.default_rng(3),
        country_key=country_key,
    )
    return [it["drug_name"] for it in rx.items]


def _beta_blockers(names: list[str]) -> list[str]:
    return [n for n in names if "beta_blocker" in drug_safety.resolve_classes(n)]


def test_two_home_beta_blockers_leave_with_one(patient_factory) -> None:
    """Issue #3274: the discharge reconciliation applies the admission gate's
    no-second-beta-blocker rule (a JP prescription continued bisoprolol and
    carvedilol together)."""
    patient = patient_factory(current_meds=["Bisoprolol", "Carvedilol"])
    assert _beta_blockers(_discharge_items(patient, "bacterial_pneumonia", "japan")) == ["Bisoprolol"]


def test_an_af_discharge_beta_blocker_is_not_added_to_a_home_one(patient_factory) -> None:
    patient = patient_factory(current_meds=["Carvedilol"])
    assert len(_beta_blockers(_discharge_items(patient, "atrial_fibrillation_rvr", "us"))) == 1
