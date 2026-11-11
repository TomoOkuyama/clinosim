"""No outpatient acute-illness visit in the first 28 days of life (Issue #2978).

A febrile infant <= 28 days old is admitted for a serious-bacterial-infection
workup (AAP febrile infant guideline, Pantell et al., Pediatrics 2021), not
seen as an outpatient cold. The acute presentations of the pediatric
calendar (URI, otitis media, bronchiolitis) therefore start at day 29.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.pediatric.calendar import generate_pediatric_events, load_pediatric_schedule

pytestmark = pytest.mark.unit

_ACUTE = {"pediatric_uri", "pediatric_otitis_media", "pediatric_bronchiolitis"}


def _baby(dob: date) -> SimpleNamespace:
    return SimpleNamespace(person_id=f"pt-{dob.isoformat()}", age=0, date_of_birth=dob, care_seeking_threshold=0.0)


def _events(dob: date, schedule: dict | None = None) -> list:
    return generate_pediatric_events(_baby(dob), dob.year, np.random.default_rng(7), schedule, country="US")


def _dobs() -> list[date]:
    return [date(2025, 1, 1) + timedelta(days=d) for d in range(0, 365, 3)]


def test_no_acute_visit_for_an_infant_aged_28_days_or_less() -> None:
    for dob in _dobs():
        for e in _events(dob):
            if e.disease_id in _ACUTE:
                assert (e.timestamp - dob).days >= 29, (dob, e.disease_id, e.timestamp)


def test_the_outpatient_uri_presentation_is_not_selected_for_a_17_day_old() -> None:
    seen = [(e.timestamp - dob).days for dob in _dobs() for e in _events(dob) if e.disease_id == "pediatric_uri"]
    assert seen, "the schedule still holds URI visits in the first year"
    assert 17 not in seen and min(seen) >= 29


def test_every_acute_entry_open_to_infants_carries_the_gate() -> None:
    for key, entry in load_pediatric_schedule().items():
        if entry["disease_id"] in _ACUTE and int(entry["age_min"]) == 0:
            assert int(entry.get("min_age_days", 0)) == 29, key


def test_the_gate_only_drops_visits_and_draws_the_same() -> None:
    gated = load_pediatric_schedule()
    ungated = {k: {kk: vv for kk, vv in v.items() if kk != "min_age_days"} for k, v in gated.items()}
    for dob in _dobs():
        kept = [(e.disease_id, e.timestamp) for e in _events(dob, gated)]
        all_ = [(e.disease_id, e.timestamp) for e in _events(dob, ungated)]
        dropped = [x for x in all_ if x not in kept]
        assert [x for x in all_ if x in kept] == kept
        assert all(d in _ACUTE and (t - dob).days < 29 for d, t in dropped)
