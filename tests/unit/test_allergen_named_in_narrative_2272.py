"""Nursing notes and care plans name the patient's allergen (Issue #2272)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.renderers.section_builders.care_plans import build_ncp_other_issues
from clinosim.modules.document.narrative.renderers.section_builders.nursing import build_nursing_history
from clinosim.types.allergy import Allergy

pytestmark = pytest.mark.unit

_PENICILLIN = "764146007"  # Penicillin (substance)


def _ctx(lang: str) -> SimpleNamespace:
    return SimpleNamespace(
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
        allergies=[Allergy(allergen_code=_PENICILLIN, category="medication")],
        encounter=SimpleNamespace(primary_nurse_id="", chief_complaint="Fever"),
        patient=SimpleNamespace(chronic_conditions=[]),
        roster_map={},
        chronic_conditions=[],
    )


@pytest.mark.parametrize("lang,name", [("en", "Penicillin"), ("ja", "ペニシリン")])
def test_nursing_history_names_the_allergen(lang: str, name: str) -> None:
    text, _ = build_nursing_history(None, _ctx(lang))  # type: ignore[arg-type]
    assert name in text


@pytest.mark.parametrize("lang,name", [("en", "Penicillin"), ("ja", "ペニシリン")])
def test_care_plan_names_the_allergen(lang: str, name: str) -> None:
    text, _ = build_ncp_other_issues(None, _ctx(lang))  # type: ignore[arg-type]
    assert name in text
