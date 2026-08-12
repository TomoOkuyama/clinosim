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

    def test_shipped_schedule_has_immunization_entries(self):
        # #760 pass 3 — immunization visits at 3 age bands (infant
        # catch-up, kindergarten entry, adolescent bundle).
        schedule = load_pediatric_schedule()
        assert set(schedule) >= {
            "immunization_infant",
            "immunization_kindergarten",
            "immunization_adolescent",
        }
        assert schedule["immunization_kindergarten"]["age_min"] == 4
        assert schedule["immunization_kindergarten"]["age_max"] == 6
        assert schedule["immunization_adolescent"]["age_min"] == 11
        assert schedule["immunization_adolescent"]["age_max"] == 13

    def test_shipped_schedule_has_pediatric_acute_entries(self):
        # #760 pass 4 — bronchiolitis + otitis + URI across 3 age bands.
        schedule = load_pediatric_schedule()
        assert set(schedule) >= {
            "pediatric_bronchiolitis",
            "pediatric_otitis_media_early",
            "pediatric_uri_young",
            "pediatric_uri_school",
            "pediatric_uri_adolescent",
        }
        # Bronchiolitis only fires for infants + toddlers (age 0-2).
        assert schedule["pediatric_bronchiolitis"]["age_max"] == 2
        # URI covers the full 0-18 range across 3 non-overlapping bands.
        assert schedule["pediatric_uri_young"]["age_max"] == 5
        assert schedule["pediatric_uri_school"]["age_min"] == 6
        assert schedule["pediatric_uri_school"]["age_max"] == 12
        assert schedule["pediatric_uri_adolescent"]["age_min"] == 13

    def test_shipped_schedule_has_injury_and_behavioural_entries(self):
        # #760 pass 5 (final) — injury (5-18) + adolescent behavioural (12-18).
        schedule = load_pediatric_schedule()
        assert set(schedule) >= {
            "pediatric_injury_school",
            "pediatric_injury_adolescent",
            "pediatric_behavioural_adolescent",
        }
        # Injury covers 5-18 across two bands (5-12 school, 13-18 adolescent).
        assert schedule["pediatric_injury_school"]["age_min"] == 5
        assert schedule["pediatric_injury_school"]["age_max"] == 12
        assert schedule["pediatric_injury_adolescent"]["age_min"] == 13
        # Behavioural fires 12-18 only.
        assert schedule["pediatric_behavioural_adolescent"]["age_min"] == 12
        assert schedule["pediatric_behavioural_adolescent"]["age_max"] == 18

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

    def test_yaml_shipped_file_produces_pediatric_events_across_bands(self):
        # #760 passes 2 + 3 + 4 — shipped YAML activates well-child +
        # immunization + acute entries. Assertions use `>=` set semantics
        # (rather than exact equality) because acute entries use
        # probability-approximating `visits_per_year: [0, ..., N]` and
        # may or may not appear on any given draw. Well-child + immunization
        # entries always fire on their bands.
        rng = np.random.default_rng(0)
        # Infant 0-1yo — well_child_infant + immunization_infant guaranteed.
        infant_events = generate_pediatric_events(self._person(0), 2025, rng)
        infant_ids = {e.disease_id for e in infant_events}
        assert "well_child_infant" in infant_ids
        assert "immunization_infant" in infant_ids
        # Early childhood 3yo — well_child_early guaranteed; URI + otitis
        # probabilistic. All present-set must be a subset of the age-band-
        # allowed ids for that age.
        early_events = generate_pediatric_events(self._person(3), 2025, np.random.default_rng(0))
        early_ids = {e.disease_id for e in early_events}
        assert "well_child_early" in early_ids
        assert early_ids.issubset({"well_child_early", "pediatric_otitis_media", "pediatric_uri"})
        # Kindergarten 5 — well_child_school + immunization_kindergarten guaranteed.
        kg_events = generate_pediatric_events(self._person(5), 2025, np.random.default_rng(0))
        kg_ids = {e.disease_id for e in kg_events}
        assert "well_child_school" in kg_ids
        assert "immunization_kindergarten" in kg_ids
        # School-age 8 — well_child_school guaranteed; URI + injury possible.
        school_events = generate_pediatric_events(self._person(8), 2025, np.random.default_rng(0))
        school_ids = {e.disease_id for e in school_events}
        assert "well_child_school" in school_ids
        assert school_ids.issubset({"well_child_school", "pediatric_uri", "pediatric_injury"})
        # Adolescent 12 — well_child_school + immunization_adolescent guaranteed;
        # URI + injury + behavioural possible (pass 5).
        adol_events = generate_pediatric_events(self._person(12), 2025, np.random.default_rng(0))
        adol_ids = {e.disease_id for e in adol_events}
        assert "well_child_school" in adol_ids
        assert "immunization_adolescent" in adol_ids
        assert adol_ids.issubset(
            {
                "well_child_school",
                "immunization_adolescent",
                "pediatric_uri",
                "pediatric_injury",
                "pediatric_behavioural",
            }
        )
        # Late adolescent 17 — well_child_school guaranteed; URI + injury + behavioural possible.
        late_events = generate_pediatric_events(self._person(17), 2025, np.random.default_rng(0))
        late_ids = {e.disease_id for e in late_events}
        assert "well_child_school" in late_ids
        assert late_ids.issubset({"well_child_school", "pediatric_uri", "pediatric_injury", "pediatric_behavioural"})
        # Adult: zero events (out of every age band).
        assert generate_pediatric_events(self._person(40), 2025, np.random.default_rng(0)) == []
        assert generate_pediatric_events(self._person(90), 2025, np.random.default_rng(0)) == []
