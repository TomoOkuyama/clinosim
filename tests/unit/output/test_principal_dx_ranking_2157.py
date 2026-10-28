"""Codes the ICD-10-CM guidelines forbid as principal rank after the principal code (Issue #2157).

Delivery stays carry Z37.0 (outcome of delivery) and septic-shock stays
R65.21 as the discharge diagnosis, with the principal O80 / A41.9 as the
admission diagnosis. Rank 1 is read as the principal diagnosis, so the
O / A41 code must come first.
"""

from __future__ import annotations

import pytest

from clinosim.modules.diagnosis.nonspecific_codes import is_never_principal_dx
from clinosim.modules.output.fhir_r4.conditions.primary_ref import encounter_admission_condition_id
from clinosim.modules.output.fhir_r4.encounters.encounter import _build_encounter

pytestmark = pytest.mark.unit

_ENC = {
    "encounter_id": "ENC-1",
    "encounter_type": "inpatient",
    "status": "finished",
    "admission_datetime": "2026-05-01T10:00:00",
    "discharge_datetime": "2026-05-03T10:00:00",
}


def _ranked(resource: dict) -> list[tuple[str, str]]:
    return [
        (d["use"]["coding"][0]["code"], d["condition"]["reference"])
        for d in sorted(resource["diagnosis"], key=lambda d: d["rank"])
    ]


@pytest.mark.parametrize(
    ("discharge", "admit"),
    [("Z37.0", "O80"), ("R65.21", "A41.9"), ("R65.20", "A41.9")],
)
def test_principal_code_ranks_first(discharge: str, admit: str) -> None:
    r = _build_encounter(
        _ENC,
        patient_id="POP-000001",
        primary_dx_code=discharge,
        admit_dx_code=admit,
        chronic_condition_codes=["E66.9"],
    )
    ranked = _ranked(r)
    assert ranked[0] == ("AD", f"Condition/{encounter_admission_condition_id('POP-000001', 'ENC-1')}")
    assert [u for u, _ in ranked[1:]] == ["DD", "CM"]
    assert sorted(d["rank"] for d in r["diagnosis"]) == [1, 2, 3]


def test_other_stays_keep_discharge_diagnosis_first() -> None:
    r = _build_encounter(_ENC, patient_id="POP-000001", primary_dx_code="J18.9", admit_dx_code="R50.9")
    assert [u for u, _ in _ranked(r)] == ["DD", "AD"]


def test_never_principal_codes() -> None:
    assert is_never_principal_dx("Z37.0") and is_never_principal_dx("R65.21") and is_never_principal_dx("R65.11")
    assert not any(is_never_principal_dx(c) for c in ("O80", "A41.9", "Z38.00", ""))
