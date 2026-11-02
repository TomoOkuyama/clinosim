"""A code never takes the display of a more specific child code
(code-mapping spec §4.4, Issue #2454)."""

from __future__ import annotations

import pytest

from clinosim.codes import CodeSystem, code_exists, display

pytestmark = pytest.mark.unit


def test_a_code_with_only_a_registered_child_has_no_display() -> None:
    cs = CodeSystem(key="t", name="t", uri="urn:t", version="", codes={"A01.1": {"en": "Child"}})
    assert cs.display("A01", "en") is None
    assert not cs.code_exists("A01")


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("E11", "Type 2 diabetes mellitus"),
        ("C16", "Malignant neoplasm of stomach"),
        ("Z00", "Encounter for general examination without complaint, suspected or reported diagnosis"),
    ],
)
def test_categories_have_their_own_display(code: str, expected: str) -> None:
    assert code_exists("icd-10-cm", code, exact=True)
    assert display("icd-10-cm", code, "en") == expected


def test_jp_categories_take_the_mhlw_name() -> None:
    assert display("icd-10-mhlw", "C16", "ja") == "胃の悪性新生物＜腫瘍＞"
    assert display("icd-10-mhlw", "C71", "ja") == "脳の悪性新生物＜腫瘍＞"


def test_a_subcode_still_takes_its_category() -> None:
    assert display("icd-10-cm", "E11.99", "en") == "Type 2 diabetes mellitus"
