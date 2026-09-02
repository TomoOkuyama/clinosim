"""Issue #926 follow-up (session 98 F2): death filter must catch Condition /
AllergyIntolerance / Immunization emitted after death.

`_dt_fields` originally listed `recorded` but not `recordedDate`, and lacked
`onsetDateTime` / `abatementDateTime` entirely — the fields Condition and
AllergyIntolerance actually use as their event timestamps. Result on the
JP p=10000 seed=98 verify: a post-mortem CIF record (readmission fired
after the patient's death at 2023-05-31, three times) had its Encounter
dropped by the death gate but the sibling Condition and AllergyIntolerance
survived, dangling their `.encounter` reference.

This locks in symmetric field coverage so the dangling class does not
regress.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4 import _drop_entries_after_death

pytestmark = pytest.mark.unit


def _entry(resource: dict) -> dict:
    return {"fullUrl": f"urn:uuid:{resource.get('id', 'x')}", "resource": resource}


def test_drops_condition_recorded_after_death() -> None:
    """Condition emitted for a post-mortem admission must be dropped
    (otherwise its `.encounter` reference dangles when the Encounter is
    dropped by its own period-after-death check)."""
    entries = [
        _entry(
            {
                "resourceType": "Condition",
                "id": "cond-after",
                "subject": {"reference": "Patient/pt-dead"},
                "encounter": {"reference": "Encounter/enc-dropped"},
                "onsetDateTime": "2023-08-25T12:37:00+09:00",
                "recordedDate": "2023-08-25T12:37:00+09:00",
                "abatementDateTime": "2023-09-07T13:37:00+09:00",
            }
        )
    ]
    kept = _drop_entries_after_death(entries, "2023-05-31")
    assert kept == [], "post-death Condition must be dropped"


def test_keeps_chronic_condition_with_pre_death_onset() -> None:
    """Chronic Condition with onset before death must survive — the
    filter only drops events dated AFTER death, not established chronic
    problems whose onset is decades in the past."""
    entries = [
        _entry(
            {
                "resourceType": "Condition",
                "id": "cond-chronic",
                "subject": {"reference": "Patient/pt-dead"},
                "onsetDateTime": "2015-04-05T00:00:00+09:00",
                "recordedDate": "2023-04-18T01:35:00+09:00",
                "clinicalStatus": {"coding": [{"code": "active"}]},
            }
        )
    ]
    kept = _drop_entries_after_death(entries, "2023-05-31")
    assert len(kept) == 1


def test_drops_allergy_recorded_after_death() -> None:
    """AllergyIntolerance uses `recordedDate` — was previously invisible
    to the filter because only `recorded` (Provenance) was listed."""
    entries = [
        _entry(
            {
                "resourceType": "AllergyIntolerance",
                "id": "allergy-after",
                "patient": {"reference": "Patient/pt-dead"},
                "encounter": {"reference": "Encounter/enc-dropped"},
                "recordedDate": "2023-08-25",
            }
        )
    ]
    kept = _drop_entries_after_death(entries, "2023-05-31")
    assert kept == [], "post-death AllergyIntolerance must be dropped"


def test_drops_condition_abatement_after_death() -> None:
    """Only `abatementDateTime` after death — no onset, no recordedDate.
    Represents a defensive edge case: a Condition whose only future
    timestamp is the abatement should still be caught."""
    entries = [
        _entry(
            {
                "resourceType": "Condition",
                "id": "cond-abate",
                "subject": {"reference": "Patient/pt-dead"},
                "abatementDateTime": "2024-01-01T00:00:00+09:00",
            }
        )
    ]
    kept = _drop_entries_after_death(entries, "2023-05-31")
    assert kept == [], "post-death abatementDateTime must trigger drop"
