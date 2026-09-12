"""LOINC registration for PHQ-9 / GAD-7 mental-health assessment scores.

Advance work for META #1137 (mental_health cluster). The Observation
emit for these scores is a follow-up (needs an enricher that fires
at F32 / F33 / F41.1 chronic follow-up encounters); this PR registers
the LOINC codes so consumers / tests / future emit paths that
reference PHQ-9 (44249-1) / GAD-7 (70274-6) / PHQ-2 (55757-9) /
PHQ-9-modified-teen (89204-2) by LOINC resolve the display
correctly.

All codes verified 2026-09-12 via `tx.fhir.org` `$lookup` against
`http://loinc.org`.
"""

from __future__ import annotations

import pytest

from clinosim.codes import lookup

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "code, en_expected",
    [
        ("44249-1", "PHQ-9 quick depression assessment panel"),
        ("70274-6", "Generalized anxiety disorder 7 item (GAD-7) total score"),
        (
            "89204-2",
            "Patient Health Questionnaire-9: Modified for Teens total score",
        ),
        ("55757-9", "Patient Health Questionnaire 2 item (PHQ-2)"),
    ],
)
def test_mental_health_loinc_display_en(code, en_expected):
    assert lookup("loinc", code, "en") == en_expected


@pytest.mark.parametrize(
    "code, ja_substr",
    [
        ("44249-1", "PHQ-9"),
        ("70274-6", "GAD-7"),
        ("89204-2", "PHQ-9"),
        ("55757-9", "PHQ-2"),
    ],
)
def test_mental_health_loinc_display_ja(code, ja_substr):
    """JP display carries the international acronym so the JP FHIR
    emit path renders both scripts."""
    ja = lookup("loinc", code, "ja")
    assert ja_substr in ja, f"JP display for {code} missing acronym {ja_substr}: {ja!r}"


def test_ssri_cohort_loinc_display_matches_registered_pattern():
    """`tx.fhir.org` uses `[Reported.PHQ]` scale-of-measurement suffix
    in the authoritative display. clinosim's registration deliberately
    drops the suffix in favour of a shorter clinical name — regression
    guard: registered display must NOT start with `Patient Health` for
    the adult PHQ-9 (that would be the PHQ-2 line). Guards against a
    yaml swap between the two codes."""
    en = lookup("loinc", "44249-1", "en")
    assert "PHQ-9" in en
    assert "PHQ-2" not in en, "44249-1 must resolve to PHQ-9, not PHQ-2 — yaml swap?"
    en2 = lookup("loinc", "55757-9", "en")
    assert "PHQ-2" in en2
