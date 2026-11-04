"""Safety-skip phrasing shared by the template and LLM paths (Issue #2519)."""

from __future__ import annotations

import pytest

from clinosim.locale.i18n import t
from clinosim.modules.document.narrative._safety_skips import safety_skip_line

_SKIP = {"considered": "warfarin", "avoided_due_to": "aspirin", "substituted_with": "apixaban", "stopped_on_day": 3}


@pytest.mark.parametrize("prefix", ["safety_skips", "safety_skips_prompt"])
@pytest.mark.parametrize(
    ("event", "key"),
    [
        ("hold", "hold"),
        ("substitute", "substitute_with_sub"),
        ("switch", "switch_with_sub"),
        ("deescalate", "deescalate_with_sub"),
        ("avoid", "avoid_with_sub"),
        (None, "avoid_with_sub"),
        ("unknown", "avoid_with_sub"),
    ],
)
def test_event_type_selects_the_phrase(prefix: str, event: str | None, key: str) -> None:
    skip = dict(_SKIP, event_type=event)
    day_phrase = t("safety_skips.day_phrase_specific", "en", day=3)
    expected = t(
        f"{prefix}.{key}",
        "en",
        considered="warfarin",
        conflict="aspirin",
        substituted="apixaban",
        day_phrase=day_phrase,
    )
    assert safety_skip_line(skip, "en", prefix=prefix) == expected


def test_no_substitute_uses_the_no_sub_phrase() -> None:
    skip = {"considered": "warfarin", "avoided_due_to": "aspirin", "event_type": "switch"}
    line = safety_skip_line(skip, "en", prefix="safety_skips")
    assert line == t(
        "safety_skips.switch_no_sub",
        "en",
        considered="warfarin",
        conflict="aspirin",
        substituted="",
        day_phrase=t("safety_skips.day_phrase_default", "en"),
    )


def test_drug_name_mapping_applies_to_drugs_only() -> None:
    line = safety_skip_line(dict(_SKIP, event_type="avoid"), "en", prefix="safety_skips", drug_name=str.upper)
    assert "WARFARIN" in line and "APIXABAN" in line and "aspirin" in line
