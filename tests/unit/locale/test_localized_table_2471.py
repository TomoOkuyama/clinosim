"""LocalizedTable owns selection and fallback for every display and
translation table (code-mapping spec §2.3, Issue #2471)."""

from __future__ import annotations

import pytest

from clinosim.locale.loader import imaging_exam_display, narrative_label, prompt_label, vocab_display
from clinosim.locale.table import ImagingExamTable, LocalizedTable, localized_tables

pytestmark = pytest.mark.unit

# display table → entries still without `en`, removed by #2460 (a ratchet:
# a new entry without English fails, a fixed one must lower the count).
_MISSING_EN = {
    "narrative_imaging.imaging": 36,
    "narrative_lab_flags.lab_flags": 6,
    "narrative_stage_tokens.stage_tokens": 9,
    "llm_prompt_labels.encounter_type": 10,
    "llm_prompt_labels.disposition": 16,
    "llm_prompt_labels.severity": 6,
    "llm_prompt_labels.risk_level": 10,
    "llm_prompt_labels.barthel_band": 10,
}


def _all_subclasses(cls: type) -> set[type]:
    found = set()
    for sub in cls.__subclasses__():
        found |= {sub} | _all_subclasses(sub)
    return found


def test_subclasses_do_not_override_the_shared_operations() -> None:
    for sub in _all_subclasses(LocalizedTable):
        assert not [op for op in LocalizedTable.FINAL_OPERATIONS if op in vars(sub)], sub.__name__


def test_get_order_and_fallback() -> None:
    table = LocalizedTable("t.t", lambda: {"chest": {"en": "Chest", "ja": "胸部"}, "ja_only": {"ja": "日本語"}})
    assert table.get("chest", "ja") == "胸部"
    assert table.get("chest", "fr") == "Chest"
    assert table.get("CHEST", "en") == "Chest"
    assert table.get("ja_only", "en", fallback="x") == "x"  # never another language
    assert table.get("missing", "en", fallback="x") == "x"
    assert LocalizedTable("t.t", dict, humanize_unknown=True).get("new_slug", "en") == "new slug"


def test_imaging_candidates_try_spaced_and_underscore_forms() -> None:
    table = ImagingExamTable("t.t", lambda: {"chest_xray": {"en": "chest X-ray"}})
    assert table.get("Chest  Xray", "en") == "chest X-ray"


def test_entry_points_delegate_to_tables() -> None:
    tables = localized_tables()
    assert imaging_exam_display("chest_xray", "ja") == tables["narrative_imaging.imaging"].get("chest_xray", "ja")
    assert vocab_display("smoking", "never", "ja") == tables["vocabulary.smoking"].get("never", "ja")
    assert prompt_label("severity", "MILD", "ja") == tables["llm_prompt_labels.severity"].get("mild", "ja")
    assert narrative_label("smoking", "never", "en") == tables["narrative_labels.smoking"].get(
        "never", "en", fallback="never"
    )


def test_every_display_table_entry_has_english() -> None:
    found = {}
    for name, table in localized_tables().items():
        if table.kind != "display-table":
            continue
        missing = [
            k
            for k, e in table.entries().items()
            if isinstance(e, dict) and "en" not in e and any(isinstance(v, str) for v in e.values())
        ]
        if missing:
            found[name] = len(missing)
    assert found == _MISSING_EN, f"entries without `en` (found vs pinned): {found}"
