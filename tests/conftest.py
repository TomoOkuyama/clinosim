"""Shared pytest fixtures (Issue #567).

Currently exports:

- ``patient_factory`` — canonical ``PatientProfile`` builder used by unit
  and integration tests. Replaces the 5 near-duplicate local ``_patient()``
  helpers that had drifted across test files. See `tests/README.md § Fixture
  policy` for the convention.

Not covered here (deliberately):

- ``dict``-shaped patient fixtures (used by tests that go through the CIF
  reader path — ``test_fhir_patient_codes_yaml.py``, ``test_narrative_
  context_wiring.py``). Those bypass ``PatientProfile`` entirely and belong
  to a separate ``patient_dict_factory`` follow-up.
- ``SimpleNamespace``-shaped stand-ins (``test_archetype_modifiers.py``,
  ``test_hai_lab_lift.py``). Those exist to test code paths that only need
  attribute access, not a full ``PatientProfile``.
"""

from __future__ import annotations

from datetime import date

import pytest

from clinosim.types.patient import ChronicCondition, HomeMedication, PatientProfile


@pytest.fixture
def patient_factory():
    """Return a callable that builds a ``PatientProfile`` from a kwargs subset.

    Consolidates the ``_patient()`` helpers previously duplicated across ≥5
    test files with divergent signatures.

    Args accepted by the returned callable:

    - ``patient_id`` (default ``"POP-000001"``)
    - ``age`` (default ``65``)
    - ``sex`` (default ``"M"``)
    - ``household_id`` (default ``None`` — dataclass default applies)
    - ``date_of_birth`` (default: derived from ``age`` as ``date(2026 - age,
      1, 1)`` — matches ``test_immunization.py``'s legacy behaviour)
    - ``current_meds`` (list[str], drug names — promoted to
      ``HomeMedication`` because attribute-assign on ``PatientProfile``
      bypasses ``__post_init__`` normalisation; see Issue #452 PR 3)
    - ``chronic_icds`` (list[str], ICD codes — promoted to
      ``ChronicCondition``)
    - ``chronic_conditions`` (list[ChronicCondition], escape hatch for tests
      that need severity_score or other non-default fields)
    - ``baseline_chronic_medications`` (list[HomeMedication], for tests that
      simulate an activator populate)

    Returns the built ``PatientProfile`` — never a factory of factories.
    """

    def _make(
        patient_id: str = "POP-000001",
        age: int = 65,
        sex: str = "M",
        household_id: str | None = None,
        date_of_birth: date | None = None,
        current_meds: list[str] | None = None,
        chronic_icds: list[str] | None = None,
        chronic_conditions: list[ChronicCondition] | None = None,
        baseline_chronic_medications: list[HomeMedication] | None = None,
    ) -> PatientProfile:
        dob = date_of_birth if date_of_birth is not None else date(2026 - age, 1, 1)
        kwargs: dict = {"patient_id": patient_id, "age": age, "sex": sex, "date_of_birth": dob}
        if household_id is not None:
            kwargs["household_id"] = household_id
        if chronic_conditions is not None:
            kwargs["chronic_conditions"] = chronic_conditions
        elif chronic_icds is not None:
            kwargs["chronic_conditions"] = [ChronicCondition(code=c) for c in chronic_icds]
        p = PatientProfile(**kwargs)
        # attribute-assign bypasses PatientProfile.__post_init__, so drug-name
        # strings must be promoted to HomeMedication explicitly (Issue #452 PR 3).
        if current_meds is not None:
            p.current_medications = [HomeMedication(drug_name=m) for m in current_meds]
        if baseline_chronic_medications is not None:
            p.baseline_chronic_medications = list(baseline_chronic_medications)
        return p

    return _make
