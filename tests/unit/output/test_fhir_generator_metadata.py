"""Unit tests for `_fhir_generator_metadata`.

Issue #206: emit a sidecar `_generator_metadata.json` next to the FHIR
NDJSON export so validators can correlate observed results with the
clinosim revision that produced the data.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from clinosim.modules.output._fhir_generator_metadata import (
    _PR_NUMBER_RE,
    _RECENT_MERGES_LIMIT,
    _SIDECAR_FILENAME,
    _collect_recent_merges,
    write_generator_metadata,
)

pytestmark = pytest.mark.unit


def test_pr_number_regex_extracts_trailing_hash() -> None:
    """The trailing `(#N)` on GitHub squash-merge subjects is the PR number."""
    assert _PR_NUMBER_RE.search("fix(fhir): populate identifier (#187)").group(1) == "187"
    # Chained `(#N) (#M)` — right-most is the master merge PR
    assert _PR_NUMBER_RE.search("fix(fhir): x (#186) (#187)").group(1) == "187"
    # No trailing hash → no match (feature/plain commits are skipped)
    assert _PR_NUMBER_RE.search("chore: rename foo") is None
    # A `#N` inside the subject that is NOT the trailing token → no match
    assert _PR_NUMBER_RE.search("closes #42 but no trailer") is None


def test_sidecar_filename_starts_with_underscore() -> None:
    """The sidecar name must not collide with a FHIR resource-type NDJSON."""
    assert _SIDECAR_FILENAME.startswith("_")
    assert _SIDECAR_FILENAME.endswith(".json")


def test_write_generator_metadata_produces_sidecar_with_expected_shape(tmp_path: Path) -> None:
    """End-to-end: write the sidecar into a temp dir and check its shape."""
    cif_dir = tmp_path / "cif"
    cif_dir.mkdir()
    # Provide a plausible cif/metadata.json so the forwarding path is exercised
    cif_meta: dict[str, Any] = {
        "clinosim_version": "0.2.0",
        "random_seed": 42,
        "country": "JP",
        "snapshot_date": "2026-06-30",
        "total_patients_generated": 736,
        "hospital_scale": "medium",
        "llm_mode": "none",
    }
    (cif_dir / "metadata.json").write_text(json.dumps(cif_meta), encoding="utf-8")
    out_dir = tmp_path / "fhir_r4"
    out_dir.mkdir()

    path = write_generator_metadata(str(out_dir), str(cif_dir), country="JP")
    assert path is not None
    assert os.path.basename(path) == _SIDECAR_FILENAME
    assert os.path.exists(path)

    with open(path, encoding="utf-8") as f:
        payload = json.load(f)

    # Required top-level keys
    for k in ("clinosim_version", "generated_at", "country", "cif_metadata", "git", "recent_merges"):
        assert k in payload, f"missing key: {k}"

    assert payload["country"] == "JP"
    assert payload["clinosim_version"]
    # cif_metadata forwarded verbatim
    assert payload["cif_metadata"] == cif_meta
    # generated_at is an ISO-8601 datetime — smoke-check via prefix + TZ offset
    ts = payload["generated_at"]
    assert isinstance(ts, str) and len(ts) >= 19  # "YYYY-MM-DDTHH:MM:SS" minimum


def test_write_generator_metadata_handles_missing_cif_metadata(tmp_path: Path) -> None:
    """No `cif/metadata.json` → `cif_metadata` is an empty dict, sidecar still written."""
    cif_dir = tmp_path / "cif"
    cif_dir.mkdir()
    out_dir = tmp_path / "fhir_r4"
    out_dir.mkdir()

    path = write_generator_metadata(str(out_dir), str(cif_dir), country="US")
    assert path is not None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert payload["cif_metadata"] == {}
    assert payload["country"] == "US"


def test_write_generator_metadata_records_git_info_when_available(tmp_path: Path) -> None:
    """Running inside the clinosim git repo, the `git` block should be populated
    (SHA + commit_datetime + subject). This test acts as a smoke check that
    the git subprocess plumbing works; it does not pin exact values."""
    cif_dir = tmp_path / "cif"
    cif_dir.mkdir()
    out_dir = tmp_path / "fhir_r4"
    out_dir.mkdir()

    path = write_generator_metadata(str(out_dir), str(cif_dir), country="JP")
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    git_info = payload["git"]
    if git_info is None:
        # Test is running outside a git checkout (rare but possible in
        # CI on tag builds) — verify we handled it gracefully.
        assert payload["recent_merges"] == []
        return
    assert isinstance(git_info["commit"], str)
    assert len(git_info["commit"]) == 40  # full SHA
    assert len(git_info["commit_short"]) == 8
    assert isinstance(git_info["dirty"], bool)


def test_collect_recent_merges_extracts_pr_numbers_from_subjects() -> None:
    """`_collect_recent_merges` parses `(#N)` trailers off of `git log --oneline`
    output. Mocked git result so the test does not depend on repo state."""
    fake_log = "\n".join(
        [
            "abc123 fix(fhir): populate identifier (#187)",
            "def456 chore: whatever",  # no trailer → skipped
            "789abc fix(fhir): specimen emit (#194) (#195)",  # chained trailers → right-most
            "111222 feat: X (#200)",
            "3334 also skipped",
        ]
    )
    with patch(
        "clinosim.modules.output._fhir_generator_metadata._run_git",
        return_value=fake_log,
    ):
        merges = _collect_recent_merges(Path("/nonexistent"), limit=10)
    assert merges == [
        {"pr": 187, "subject": "fix(fhir): populate identifier (#187)"},
        {"pr": 195, "subject": "fix(fhir): specimen emit (#194) (#195)"},
        {"pr": 200, "subject": "feat: X (#200)"},
    ]


def test_collect_recent_merges_returns_empty_when_git_unavailable() -> None:
    """`git log` failure (not a repo / no git on PATH) → empty list, not raise."""
    with patch(
        "clinosim.modules.output._fhir_generator_metadata._run_git",
        return_value=None,
    ):
        assert _collect_recent_merges(Path("/nonexistent")) == []


def test_collect_recent_merges_respects_limit() -> None:
    """When the log has many PR-merge lines, the walker returns at most `limit`."""
    lines = [f"aaa{n:03d} fix: item {n} (#{n})" for n in range(50)]
    fake_log = "\n".join(lines)
    with patch(
        "clinosim.modules.output._fhir_generator_metadata._run_git",
        return_value=fake_log,
    ):
        merges = _collect_recent_merges(Path("/nonexistent"), limit=5)
    assert len(merges) == 5
    assert [m["pr"] for m in merges] == [0, 1, 2, 3, 4]


def test_recent_merges_limit_constant_is_reasonable() -> None:
    """Guard: the module-level cap balances sidecar size vs history coverage.
    30 covers ~1-2 weeks of feedback-response chains; larger caps waste bytes."""
    assert 10 <= _RECENT_MERGES_LIMIT <= 100
