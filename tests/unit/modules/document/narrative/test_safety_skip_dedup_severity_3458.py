"""Issue #3458: a progress note states a drug-safety avoidance once per drug
(two raw names of one drug are one line) and words the reason by the rule's
severity (a contraindication is not worded like an interaction risk)."""

from __future__ import annotations

import pytest

from clinosim.modules.document.narrative._safety_skips import progress_note_safety_skips, safety_skip_line
from clinosim.modules.document.narrative._template_helpers import _render_safety_skips_line

pytestmark = pytest.mark.unit


def _avoid(considered: str, conflict: str, severity: str | None) -> dict:
    return {
        "considered": considered,
        "avoided_due_to": conflict,
        "substituted_with": None,
        "event_type": "avoid",
        "rule_id": "acei-arb-plus-potassium",
        "conflict_kind": "interaction",
        "severity": severity,
    }


def test_two_raw_names_of_one_drug_render_one_line() -> None:
    skips = [
        _avoid("Potassium chloride", "Losartan", "major"),
        _avoid("KCl", "Losartan", "major"),
    ]
    assert len(progress_note_safety_skips(skips)) == 1
    for lang in ("ja", "en"):
        assert len(_render_safety_skips_line(progress_note_safety_skips(skips), lang).splitlines()) == 1
    # Even unfiltered, the two names localize to one Japanese line.
    assert len(_render_safety_skips_line(skips, "ja").splitlines()) == 1


@pytest.mark.parametrize("severity", ["major", "moderate", "minor"])
def test_interaction_risk_is_not_worded_as_contraindication(severity: str | None) -> None:
    skip = _avoid("Potassium chloride", "Losartan", severity)
    ja = safety_skip_line(skip, "ja", prefix="safety_skips")
    en = safety_skip_line(skip, "en", prefix="safety_skips")
    assert "禁忌" not in ja and "相互作用" in ja
    assert "contraindicat" not in en.lower() and "interaction" in en
    assert "Losartan" in en and "Losartan" in ja


def test_contraindicated_keeps_contraindication_wording() -> None:
    skip = _avoid("Potassium chloride", "Losartan", "contraindicated")
    assert "併用禁忌" in safety_skip_line(skip, "ja", prefix="safety_skips")
    assert "interaction risk" not in safety_skip_line(skip, "en", prefix="safety_skips")


def test_prompt_path_follows_severity() -> None:
    skip = _avoid("Potassium chloride", "Losartan", "major")
    assert "interaction" in safety_skip_line(skip, "en", prefix="safety_skips_prompt")
    assert "禁忌" not in safety_skip_line(skip, "ja", prefix="safety_skips_prompt")
