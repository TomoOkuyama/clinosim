"""C11g-4 FHIR alignment tests (Issue #1114).

Verifies that a person with a natural ``date_of_death`` (populated by
the ``natural_death`` POST_POPULATION enricher) surfaces as a FHIR
``Patient.deceasedDateTime`` + ``active=False`` on the emit path.
Covers both the direct ``_build_patient`` call site and the
activator-plumbed PatientProfile flow.

C11g-3b sibling filter-site tests live in ``test_natural_death.py``
(scope: sampling + is_alive_at predicate). This file's scope: the
downstream FHIR surface.
"""

from __future__ import annotations

from datetime import date

import pytest

from clinosim.modules.output.fhir_r4.demographics.patient import _build_patient


@pytest.mark.unit
class TestFHIRDeceasedDateTime:
    def test_natural_death_emits_deceased_date_time(self, patient_dict_factory) -> None:
        p = patient_dict_factory(date_of_death="2025-06-15")
        resource = _build_patient(p, "US")
        assert resource.get("deceasedDateTime") == "2025-06-15"
        # Issue #926: deceased patients also flip active=False.
        assert resource.get("active") is False
        # Not both — deceasedBoolean must not co-exist with deceasedDateTime.
        assert "deceasedBoolean" not in resource

    def test_natural_death_uses_dod_alias_when_only_dod_set(self, patient_dict_factory) -> None:
        """The FHIR builder accepts either ``date_of_death`` or ``dod`` —
        both keys should yield the same emit. Session-103 C11g-4 keeps
        this alias so legacy CIF paths (in-hospital ``record.deceased``
        derivation, see fhir_r4/__init__.py:521) stay compatible."""
        p = patient_dict_factory(dod="2024-12-01")
        resource = _build_patient(p, "US")
        assert resource.get("deceasedDateTime") == "2024-12-01"
        assert resource.get("active") is False

    def test_living_patient_emits_deceased_boolean_false(self, patient_dict_factory) -> None:
        p = patient_dict_factory()  # no date_of_death
        resource = _build_patient(p, "US")
        assert resource.get("deceasedBoolean") is False
        assert "deceasedDateTime" not in resource
        # active stays True (the default) — no aging-into-deceased flip.
        assert resource.get("active") is True

    def test_jp_natural_death_same_behavior(self, patient_dict_factory) -> None:
        """JP path uses the same ``_build_patient`` builder — verify
        cross-locale parity of the deceased handling."""
        p = patient_dict_factory(date_of_death="2025-06-15", sex="M")
        resource = _build_patient(p, "JP")
        assert resource.get("deceasedDateTime") == "2025-06-15"
        assert resource.get("active") is False


@pytest.mark.unit
class TestActivatorForwardsDateOfDeath:
    """PatientProfile inherits ``date_of_death`` from PersonRecord via
    the activator (C11g-4 plumbing). Downstream CIF write + FHIR emit
    then sees it as ``patient_data.date_of_death`` and produces the
    deceasedDateTime slot."""

    def test_person_with_natural_death_flows_to_patient_profile(self) -> None:
        import numpy as np

        from clinosim.locale.loader import load_demographics
        from clinosim.modules.patient.activator import activate_patient
        from clinosim.types.population import PersonRecord

        demo = load_demographics("US")
        rng = np.random.default_rng(42)
        person = PersonRecord(
            person_id="P-C11g-4",
            household_id="H-1",
            age=72,
            sex="M",
            date_of_birth=date(1953, 6, 15),
            date_of_death=date(2025, 3, 10),
        )
        # Activator requires demographics + rng; use real US demo config.
        patient_profile = activate_patient(person, rng, demo)
        assert patient_profile.date_of_death == date(2025, 3, 10)
