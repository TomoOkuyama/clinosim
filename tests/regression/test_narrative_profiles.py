"""AD-66 α-min-2c: byte-diff narrative regression suite.

For each canonical patient profile:
1. Subprocess-invoke `clinosim test-disease --patient-profile <id> --format cif -o <tmpdir>`
2. Walk cif/narratives/template/documents/**/*.json → build canonical dict
3. Load `<profile>.golden.json`
4. Assert dict equality; emit unified diff on mismatch

Marker `regression` = opt-in. Default `pytest` run does not execute this
suite (subprocess latency + β-JP-1 LLM cost budget considerations).
"""
from __future__ import annotations

import difflib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.regression.conftest import FIXTURE_DIR, profile_ids


@pytest.mark.regression
@pytest.mark.parametrize("profile_id", profile_ids())
def test_profile_narrative_byte_diff(profile_id: str, tmp_path: Path) -> None:
    """<profile>.yaml → generate → byte-diff vs <profile>.golden.json."""
    profile_path = FIXTURE_DIR / f"{profile_id}.yaml"
    assert profile_path.is_file(), f"missing profile YAML: {profile_path}"

    golden_path = FIXTURE_DIR / f"{profile_id}.golden.json"
    assert golden_path.is_file(), (
        f"missing golden JSON: {golden_path}. Run "
        f"`clinosim regenerate-goldens --profile {profile_id}` to bootstrap."
    )

    # 1. Subprocess-invoke test-disease pipeline
    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "test-disease",
         "--patient-profile", str(profile_path),
         "--format", "cif", "-o", str(tmp_path)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, (
        f"test-disease failed for {profile_id}:\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )

    # 2. Walk narrative output → canonical dict
    narr_dir = tmp_path / "cif" / "narratives" / "template" / "documents"
    if not narr_dir.is_dir():
        pytest.fail(f"no narratives written for {profile_id} (expected {narr_dir})")

    actual: dict[str, dict] = {}
    for enc_dir in sorted(narr_dir.iterdir()):
        if not enc_dir.is_dir():
            continue
        for doc_file in sorted(enc_dir.iterdir()):
            if doc_file.suffix != ".json":
                continue
            actual[doc_file.stem] = json.loads(doc_file.read_text())

    # 3. Load golden
    expected = json.loads(golden_path.read_text())

    # 4. Byte-diff
    if actual == expected:
        return

    # Actionable unified diff
    actual_str = json.dumps(actual, indent=2, ensure_ascii=False, sort_keys=True)
    expected_str = json.dumps(expected, indent=2, ensure_ascii=False, sort_keys=True)
    diff = "\n".join(difflib.unified_diff(
        expected_str.splitlines(),
        actual_str.splitlines(),
        fromfile=f"{profile_id}.golden.json",
        tofile=f"{profile_id}.actual",
        lineterm="",
        n=3,
    ))
    pytest.fail(
        f"Narrative regression for {profile_id}:\n"
        f"If intentional, run `clinosim regenerate-goldens --profile "
        f"{profile_id}` + commit.\n\n{diff}"
    )
