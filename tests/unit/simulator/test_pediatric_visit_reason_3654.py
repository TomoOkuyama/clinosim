"""Issue #3654: a paediatric visit carries the reason of the schedule entry that generated it."""

from __future__ import annotations

import re

import pytest

from clinosim.modules.pediatric.calendar import load_pediatric_schedule
from clinosim.simulator._setup import _pediatric_visit_reason


def _en(reason: str | dict[str, str]) -> str:
    return reason["en"] if isinstance(reason, dict) else reason


@pytest.mark.parametrize(
    "entry_key",
    ["pediatric_uri_young", "pediatric_uri_school", "pediatric_uri_adolescent"],
)
def test_uri_entry_key_returns_its_own_reason(entry_key: str) -> None:
    schedule = load_pediatric_schedule()
    assert _pediatric_visit_reason("pediatric_uri", entry_key) == schedule[entry_key]["visit_reason"]


def test_school_and_adolescent_reasons_differ_from_young() -> None:
    young = _pediatric_visit_reason("pediatric_uri", "pediatric_uri_young")
    school = _pediatric_visit_reason("pediatric_uri", "pediatric_uri_school")
    adolescent = _pediatric_visit_reason("pediatric_uri", "pediatric_uri_adolescent")
    assert len({_en(young), _en(school), _en(adolescent)}) == 3


@pytest.mark.parametrize("entry_key", ["pediatric_injury_school", "pediatric_injury_adolescent"])
def test_injury_bands_keep_their_own_reason(entry_key: str) -> None:
    schedule = load_pediatric_schedule()
    assert _pediatric_visit_reason("pediatric_injury", entry_key) == schedule[entry_key]["visit_reason"]


def test_fixed_age_entries_still_keep_their_reason() -> None:
    schedule = load_pediatric_schedule()
    for key in ("well_child_one_month", "well_child_infant"):
        if key in schedule:
            assert _pediatric_visit_reason(schedule[key]["disease_id"], key) == schedule[key]["visit_reason"]


def test_entry_key_for_other_disease_is_ignored() -> None:
    schedule = load_pediatric_schedule()
    assert (
        _pediatric_visit_reason("pediatric_uri", "pediatric_injury_school")
        == schedule["pediatric_uri_young"]["visit_reason"]
    )


def test_uri_reasons_do_not_claim_a_fever() -> None:
    schedule = load_pediatric_schedule()
    for key, entry in schedule.items():
        if entry.get("disease_id") != "pediatric_uri":
            continue
        reason = entry["visit_reason"]
        assert not re.search(r"fever", reason["en"], re.IGNORECASE), key
        assert "発熱" not in reason["ja"], key
