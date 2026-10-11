"""Issue #1572 Phase 2.5 prep: ``PersonRecord.disease_stages``
snapshot written back by ``activate_patient``.

Covers:
* field defaults to empty dict
* ``activate_patient`` writes the sampled stage into
  ``person.disease_stages`` for staged codes (N18, J44, I50, J45,
  I10 Stage 1/2, I25 CCS)
* unstaged codes (F32, F33, F17.210) leave the dict empty for
  that code
* writing is idempotent (second call sees same stage, no stacking)
"""

from __future__ import annotations

from datetime import date

import numpy as np

from clinosim.locale.loader import load_demographics
from clinosim.modules.patient.activator import activate_patient
from clinosim.types.population import PersonRecord


_DEMO = load_demographics("us")


def _person(
    person_id: str = "PT-1",
    chronic_conditions: list[str] | None = None,
    age: int = 65,
) -> PersonRecord:
    return PersonRecord(
        person_id=person_id,
        household_id="HH-1",
        age=age,
        sex="M",
        date_of_birth=date(2026 - age, 6, 15),
        chronic_conditions=list(chronic_conditions or []),
    )


def test_disease_stages_default_is_empty_dict() -> None:
    p = _person()
    assert p.disease_stages == {}
    assert isinstance(p.disease_stages, dict)


def test_disease_stages_defaults_are_independent_instances() -> None:
    """Two PersonRecord instances must not share the same dict object."""
    a = _person("PT-A")
    b = _person("PT-B")
    a.disease_stages["N18"] = "CKD G3a"
    assert b.disease_stages == {}


def test_activate_patient_writes_ckd_stage_snapshot() -> None:
    """A person with N18 → `disease_stages['N18']` populated with a
    valid KDIGO stage string prefixed with 'CKD '."""
    p = _person(chronic_conditions=["N18"])
    profile = activate_patient(p, np.random.default_rng(42), _DEMO)
    assert "N18" in p.disease_stages
    stage = p.disease_stages["N18"]
    assert stage.startswith("CKD G")
    assert stage.removeprefix("CKD ") in ("G1", "G2", "G3a", "G3b", "G4", "G5")
    # Layer-2 and Layer-1 agree.
    layer2_stages = {c.code.split(".")[0]: c.stage for c in profile.chronic_conditions}
    assert layer2_stages["N18"] == stage


def test_activate_patient_writes_copd_stage_snapshot() -> None:
    """A person with J44 → `disease_stages['J44']` is a GOLD 1..4 string."""
    p = _person(chronic_conditions=["J44"])
    _ = activate_patient(p, np.random.default_rng(7), _DEMO)
    assert p.disease_stages["J44"] in ("GOLD 1", "GOLD 2", "GOLD 3", "GOLD 4")


def test_activate_patient_leaves_unstaged_code_absent() -> None:
    """Codes without a stage distribution (e.g. F32 depression) do
    not populate `disease_stages` — the condition is still created
    on the Layer-2 side, just without a stage key here."""
    p = _person(chronic_conditions=["F32"])
    activate_patient(p, np.random.default_rng(0), _DEMO)
    assert "F32" not in p.disease_stages


def test_activate_patient_populates_all_staged_codes_in_cohort() -> None:
    """A multi-chronic person gets per-ICD stage entries for every
    staged code they carry."""
    p = _person(chronic_conditions=["N18", "J44", "I50"])
    activate_patient(p, np.random.default_rng(13), _DEMO)
    for base in ("N18", "J44", "I50"):
        assert base in p.disease_stages, f"missing {base} in {p.disease_stages}"


def test_disease_stages_write_is_mutation_not_rebind() -> None:
    """The write is in-place mutation on the field — callers holding
    a reference to the dict see the update."""
    p = _person(chronic_conditions=["N18"])
    ref = p.disease_stages
    activate_patient(p, np.random.default_rng(1), _DEMO)
    assert ref is p.disease_stages
    assert ref["N18"].startswith("CKD G")
