"""Unit tests for the hedging phrase helper (2026-08-17 density work).

Locks in the design contract: confirmed=True → assertive phrasing,
confirmed=False → softened phrasing that admits the scenario is not
CIF-verified. Prevents future regressions where scenario data leaks
into narratives as fact.
"""

from __future__ import annotations

import random

from clinosim.modules.document.narrative._hedging import has_topic, hedged_phrase


def test_confirmed_symptom_is_assertive_ja():
    text = hedged_phrase("symptom", "胸痛", confirmed=True, lang="ja")
    assert text
    assert "胸痛" in text
    # Assertive phrasing must not carry the possibility markers used in
    # the unconfirmed branch.
    assert "可能性" not in text
    assert "訴えなし" not in text


def test_unconfirmed_symptom_is_hedged_ja():
    text = hedged_phrase("symptom", "胸痛", confirmed=False, lang="ja")
    assert text
    assert "胸痛" in text
    # Unconfirmed must NOT read as a fact — one of the hedge markers
    # must appear (未確定 phrasing registry).
    assert any(marker in text for marker in ("可能性", "訴えなし", "確認予定"))


def test_confirmed_symptom_is_assertive_en():
    text = hedged_phrase("symptom", "chest pain", confirmed=True, lang="en")
    assert text
    assert "chest pain" in text
    assert "not endorsed" not in text


def test_unconfirmed_symptom_is_hedged_en():
    text = hedged_phrase("symptom", "chest pain", confirmed=False, lang="en")
    assert text
    assert "chest pain" in text
    assert any(marker in text for marker in ("not endorsed", "consideration", "reassess"))


def test_deterministic_by_default_returns_first_entry():
    """No RNG passed → same phrase across calls (template renders are
    deterministic across the same input)."""
    a = hedged_phrase("symptom", "咳嗽", confirmed=True, lang="ja")
    b = hedged_phrase("symptom", "咳嗽", confirmed=True, lang="ja")
    assert a == b


def test_rng_choice_varies_phrase():
    """When a seeded RNG is passed, the choice is deterministic per seed
    but can differ across seeds — enabling per-patient variation while
    staying reproducible."""
    r1 = random.Random(1)
    r2 = random.Random(42)
    a = hedged_phrase("symptom", "咳嗽", confirmed=True, lang="ja", rng=r1)
    b = hedged_phrase("symptom", "咳嗽", confirmed=True, lang="ja", rng=r2)
    assert a
    assert b


def test_chronic_status_supports_control_placeholder():
    text = hedged_phrase("chronic_status", "本態性高血圧", confirmed=True, lang="ja", control="不十分")
    assert "本態性高血圧" in text
    assert "不十分" in text


def test_missing_placeholder_does_not_crash():
    """chronic_status uses {control}; when caller forgets to pass it, the
    helper must NOT crash — it returns the raw phrase with {value}
    substituted so callers can still emit something."""
    text = hedged_phrase("chronic_status", "本態性高血圧", confirmed=True, lang="ja")
    assert "本態性高血圧" in text


def test_unknown_topic_returns_empty_string():
    text = hedged_phrase("not_a_topic", "X", confirmed=True, lang="ja")
    assert text == ""


def test_unknown_lang_falls_back_to_ja():
    text = hedged_phrase("symptom", "胸痛", confirmed=True, lang="xx")
    assert text
    assert "胸痛" in text


def test_has_topic_matches_registry_keys():
    assert has_topic("symptom")
    assert has_topic("trajectory")
    assert has_topic("lab_finding")
    assert has_topic("treatment")
    assert has_topic("complication")
    assert has_topic("chronic_status")
    assert not has_topic("not_a_topic")
