"""Unit tests for the pediatric encounter scaffold (Issue #760 foundation)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.pediatric.calendar import (
    generate_pediatric_events,
    load_pediatric_schedule,
)

pytestmark = pytest.mark.unit


class TestLoadPediatricSchedule:
    def test_shipped_schedule_has_well_child_entries(self):
        # #760 pass 2 — well-child ships as the first registered
        # encounter-type family. Pass 1 shipped an empty schedule; this
        # test replaces the pass-1 empty-assertion.
        schedule = load_pediatric_schedule()
        assert set(schedule) >= {"well_child_infant", "well_child_early", "well_child_school"}
        assert schedule["well_child_infant"]["age_min"] == 0
        assert schedule["well_child_infant"]["age_max"] == 1
        assert schedule["well_child_school"]["age_max"] == 18

    def test_valid_entry_round_trips(self, tmp_path):
        p = tmp_path / "schedule.yaml"
        p.write_text(
            """encounters:
  well_child_infant:
    age_min: 0
    age_max: 1
    visits_per_year: [6, 7, 8]
    encounter_type: outpatient
    disease_id: well_child_infant
    visit_reason: "Well-child visit — infant"
"""
        )
        schedule = load_pediatric_schedule(p)
        assert set(schedule) == {"well_child_infant"}
        assert schedule["well_child_infant"]["age_min"] == 0
        assert schedule["well_child_infant"]["visits_per_year"] == [6, 7, 8]

    def test_missing_required_field_raises(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text(
            """encounters:
  broken:
    age_min: 0
    age_max: 1
    visits_per_year: [1]
    encounter_type: outpatient
    # missing disease_id
"""
        )
        with pytest.raises(ValueError, match="missing required 'disease_id'"):
            load_pediatric_schedule(p)

    def test_empty_visits_per_year_raises(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text(
            """encounters:
  broken:
    age_min: 0
    age_max: 1
    visits_per_year: []
    encounter_type: outpatient
    disease_id: broken
"""
        )
        with pytest.raises(ValueError, match="visits_per_year"):
            load_pediatric_schedule(p)

    def test_inverted_age_band_raises(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text(
            """encounters:
  broken:
    age_min: 18
    age_max: 5
    visits_per_year: [1]
    encounter_type: outpatient
    disease_id: broken
"""
        )
        with pytest.raises(ValueError, match="age_min > age_max"):
            load_pediatric_schedule(p)

    def test_missing_top_level_encounters_returns_empty(self, tmp_path):
        p = tmp_path / "empty.yaml"
        p.write_text("# empty file\n")
        assert load_pediatric_schedule(p) == {}


class TestGeneratePediatricEvents:
    def _person(self, age: int, pid: str = "POP-CHILD-1") -> SimpleNamespace:
        return SimpleNamespace(person_id=pid, age=age, is_alive=True)

    def test_empty_schedule_returns_no_events_and_does_not_consume_rng(self):
        # #760 foundation invariant: an unregistered schedule must be
        # byte-diff neutral, so the rng passed in must NOT be advanced by
        # the call. Verify by taking a snapshot draw before + after.
        rng = np.random.default_rng(42)
        rng.random()  # burn one draw so we compare two subsequent draws with control
        events = generate_pediatric_events(self._person(3), 2025, rng, schedule={})
        after_1 = rng.random()

        rng_control = np.random.default_rng(42)
        _ = rng_control.random()
        after_2 = rng_control.random()

        assert events == []
        # If the function consumed from rng, `after_1` would differ from
        # `after_2` (the control-run's second draw with no interposing call).
        assert after_1 == after_2, "generate_pediatric_events consumed rng on empty schedule"

    def test_child_matches_age_band(self):
        schedule = {
            "well_child_infant": {
                "age_min": 0,
                "age_max": 1,
                "visits_per_year": [8],
                "encounter_type": "outpatient",
                "disease_id": "well_child_infant",
            }
        }
        events = generate_pediatric_events(self._person(0), 2025, np.random.default_rng(1), schedule)
        assert len(events) == 8
        assert all(e.event_type == "pediatric_visit" for e in events)
        assert all(e.disease_id == "well_child_infant" for e in events)
        # Events span the year (spread across months, not clustered on one day).
        months = {e.timestamp.month for e in events}
        assert len(months) >= 4

    def test_age_out_of_band_returns_empty(self):
        schedule = {
            "well_child_infant": {
                "age_min": 0,
                "age_max": 1,
                "visits_per_year": [8],
                "encounter_type": "outpatient",
                "disease_id": "well_child_infant",
            }
        }
        events = generate_pediatric_events(self._person(40), 2025, np.random.default_rng(1), schedule)
        assert events == []

    def test_multiple_entries_matching_same_age(self):
        schedule = {
            "well_child": {
                "age_min": 0,
                "age_max": 18,
                "visits_per_year": [1],
                "encounter_type": "outpatient",
                "disease_id": "well_child",
            },
            "immunization": {
                "age_min": 0,
                "age_max": 18,
                "visits_per_year": [2],
                "encounter_type": "outpatient",
                "disease_id": "immunization_visit",
            },
        }
        events = generate_pediatric_events(self._person(5), 2025, np.random.default_rng(1), schedule)
        disease_ids = [e.disease_id for e in events]
        assert disease_ids.count("well_child") == 1
        assert disease_ids.count("immunization_visit") == 2

    def test_determinism_same_seed_same_events(self):
        schedule = {
            "well_child_infant": {
                "age_min": 0,
                "age_max": 1,
                "visits_per_year": [6, 7, 8],
                "encounter_type": "outpatient",
                "disease_id": "well_child_infant",
            }
        }
        ev_a = generate_pediatric_events(self._person(0), 2025, np.random.default_rng(42), schedule)
        ev_b = generate_pediatric_events(self._person(0), 2025, np.random.default_rng(42), schedule)
        assert [e.timestamp for e in ev_a] == [e.timestamp for e in ev_b]
        assert [e.disease_id for e in ev_a] == [e.disease_id for e in ev_b]

    def test_yaml_shipped_file_produces_well_child_events_for_pediatric_ages(self):
        # #760 pass 2 — shipped YAML activates well-child visits.
        # Infants get 6-8 visits, ages 2-4 get 2-3, ages 5-18 get 1;
        # adults (age >= 19) get zero.
        rng = np.random.default_rng(0)
        # Infant: 6-8 well-child visits.
        infant_events = generate_pediatric_events(self._person(0), 2025, rng)
        assert 6 <= len(infant_events) <= 8
        assert all(e.disease_id == "well_child_infant" for e in infant_events)
        # Early childhood: 2-3 well-child visits.
        early_events = generate_pediatric_events(self._person(3), 2025, np.random.default_rng(0))
        assert 2 <= len(early_events) <= 3
        assert all(e.disease_id == "well_child_early" for e in early_events)
        # School-age: 1 visit.
        school_events = generate_pediatric_events(self._person(10), 2025, np.random.default_rng(0))
        assert len(school_events) == 1
        assert school_events[0].disease_id == "well_child_school"
        # Adult: zero events (out of every age band).
        assert generate_pediatric_events(self._person(40), 2025, np.random.default_rng(0)) == []
        assert generate_pediatric_events(self._person(90), 2025, np.random.default_rng(0)) == []
