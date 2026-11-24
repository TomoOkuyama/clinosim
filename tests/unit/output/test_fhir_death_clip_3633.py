"""The FHIR post-mortem clip keeps a dateTime and clips the whole Encounter (Issue #3633)."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.builder import _drop_entries_after_death

pytestmark = pytest.mark.unit

_DEATH = "2026-05-27T23:59:59Z"


def _encounter() -> dict:
    return {
        "resource": {
            "resourceType": "Encounter",
            "id": "enc-1",
            "class": {"code": "IMP"},
            "period": {"start": "2026-05-24T08:44:00Z", "end": "2026-06-11T10:44:00Z"},
            "hospitalization": {"dischargeDisposition": {"coding": [{"code": "home"}]}},
            "classHistory": [
                {
                    "class": {"code": "ACUTE"},
                    "period": {"start": "2026-05-24T08:44:00Z", "end": "2026-06-09T10:44:00Z"},
                },
                {"class": {"code": "IMP"}, "period": {"start": "2026-06-09T10:44:00Z", "end": "2026-06-11T10:44:00Z"}},
                {
                    "class": {"code": "ACUTE"},
                    "period": {"start": "2026-05-24T08:44:00Z", "end": "2026-05-25T08:44:00Z"},
                },
            ],
            "location": [
                {
                    "location": {"reference": "Location/a"},
                    "period": {"start": "2026-05-24T08:44:00Z", "end": "2026-06-09T10:44:00Z"},
                },
                {
                    "location": {"reference": "Location/b"},
                    "period": {"start": "2026-06-09T10:44:00Z", "end": "2026-06-11T10:44:00Z"},
                },
            ],
        }
    }


def test_the_clipped_period_end_is_the_full_death_datetime() -> None:
    (kept,) = _drop_entries_after_death([_encounter()], "2026-05-27", "en", "US", death_iso=_DEATH)
    assert kept["resource"]["period"]["end"] == _DEATH


def test_a_clip_without_a_death_time_ends_at_the_end_of_the_death_day() -> None:
    (kept,) = _drop_entries_after_death([_encounter()], "2026-05-27", "en", "US")
    end = kept["resource"]["period"]["end"]
    assert len(end) > len("2026-05-27") and end.startswith("2026-05-27T")


def test_class_history_and_locations_are_clipped_to_the_death() -> None:
    (kept,) = _drop_entries_after_death([_encounter()], "2026-05-27", "en", "US", death_iso=_DEATH)
    res = kept["resource"]
    history = res["classHistory"]
    assert [h["class"]["code"] for h in history] == ["ACUTE", "ACUTE"]
    assert history[0]["period"]["end"] == _DEATH
    assert history[1]["period"]["end"] == "2026-05-25T08:44:00Z"
    assert [loc["location"]["reference"] for loc in res["location"]] == ["Location/a"]
    assert res["location"][0]["period"]["end"] == _DEATH
