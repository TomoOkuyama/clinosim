"""Unit tests: lab_obs_id / parse_lab_obs_id writer↔reader roundtrip.

Verifies that the canonical OBS_ID_FORMAT constant and its two helpers
(lab_obs_id / parse_lab_obs_id) are self-consistent, so a future format
change on one side is caught at import-time rather than as a silent basedOn
mis-link (PR-90 silent-no-op class, PR1 Important finding).
"""

import re

from clinosim.modules.output._fhir_diagnostic_report import (
    OBS_ID_FORMAT,
    lab_obs_id,
    parse_lab_obs_id,
)


def test_writer_reader_format_roundtrip() -> None:
    """Writer and reader use the same format — roundtrip succeeds."""
    obs_id = lab_obs_id("enc-pt1-001", 42)
    idx = parse_lab_obs_id(obs_id, "enc-pt1-001")
    assert idx == 42


def test_roundtrip_zero_index() -> None:
    """Index 0 round-trips correctly (zero-padding edge case)."""
    obs_id = lab_obs_id("enc-abc", 0)
    assert obs_id == "lab-enc-abc-0000"
    assert parse_lab_obs_id(obs_id, "enc-abc") == 0


def test_roundtrip_large_index() -> None:
    """Index >= 1000 round-trips correctly (4-digit padding overflows gracefully)."""
    obs_id = lab_obs_id("enc-x", 1234)
    assert obs_id == "lab-enc-x-1234"
    assert parse_lab_obs_id(obs_id, "enc-x") == 1234


def test_parse_returns_none_on_wrong_encounter() -> None:
    """parse_lab_obs_id returns None when encounter_id doesn't match."""
    obs_id = lab_obs_id("enc-A", 5)
    assert parse_lab_obs_id(obs_id, "enc-B") is None


def test_parse_returns_none_on_format_mismatch() -> None:
    """A format-drifted obs_id returns None (not crash)."""
    assert parse_lab_obs_id("vital-enc1-0001", "enc1") is None
    assert parse_lab_obs_id("lab-enc1-XXXX", "enc1") is None
    assert parse_lab_obs_id("", "enc1") is None


def test_obs_id_format_string_well_formed() -> None:
    """OBS_ID_FORMAT constant has expected shape with enc and idx placeholders."""
    assert "{enc}" in OBS_ID_FORMAT
    assert "{idx:04d}" in OBS_ID_FORMAT
    # Must start with "lab-"
    assert OBS_ID_FORMAT.startswith("lab-")


def test_obs_id_matches_expected_pattern() -> None:
    """lab_obs_id output matches the regex pattern expected by the basedOn reader."""
    obs_id = lab_obs_id("enc-pt-001", 7)
    # Pattern: "lab-" + encounter_id + "-" + 4-digit zero-padded int
    assert re.fullmatch(r"lab-enc-pt-001-\d{4}", obs_id), f"unexpected format: {obs_id!r}"
