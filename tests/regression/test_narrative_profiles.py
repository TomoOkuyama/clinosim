"""AD-66 α-min-2c: byte-diff narrative regression suite.

For each canonical patient profile:
1. Subprocess-invoke `clinosim test-disease --patient-profile <id> --format cif -o <tmpdir>`
2. Walk cif/narratives/template/documents/**/*.json → build canonical dict
3. Load `<profile>.golden.json`
4. Assert dict equality; emit unified diff on mismatch

β-JP-1 chain 1b T1 adds an llm-mock leg: for each profile with an
`<profile>.llm-mock.golden.json`, additionally run
`clinosim narrate --provider mock` over the structural CIF and byte-diff
against the llm-mock golden (MockProvider is deterministic + per-run reset,
walk order is deterministic → byte-stable).

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
import yaml

from tests.regression.conftest import FIXTURE_DIR, llm_mock_profile_ids, profile_ids

#: Narrative version directory written by `regenerate-goldens --provider mock`
#: (and mirrored here). Keep in sync with `_run_regenerate_goldens`.
LLM_MOCK_VERSION_ID = "llm-mock"


def _run_test_disease(profile_id: str, tmp_path: Path) -> None:
    """Subprocess-invoke the test-disease profile pipeline into tmp_path."""
    profile_path = FIXTURE_DIR / f"{profile_id}.yaml"
    assert profile_path.is_file(), f"missing profile YAML: {profile_path}"
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


def _collect_narratives(narr_dir: Path) -> dict[str, dict]:
    """Walk narratives/<version>/documents/**/*.json → {doc_file_stem: payload}."""
    actual: dict[str, dict] = {}
    for enc_dir in sorted(narr_dir.iterdir()):
        if not enc_dir.is_dir():
            continue
        for doc_file in sorted(enc_dir.iterdir()):
            if doc_file.suffix != ".json":
                continue
            actual[doc_file.stem] = json.loads(doc_file.read_text())
    return actual


def _assert_matches_golden(
    profile_id: str, actual: dict, golden_path: Path, regen_hint: str
) -> None:
    """Assert actual == golden; on mismatch fail with an actionable unified diff."""
    expected = json.loads(golden_path.read_text())
    if actual == expected:
        return
    actual_str = json.dumps(actual, indent=2, ensure_ascii=False, sort_keys=True)
    expected_str = json.dumps(expected, indent=2, ensure_ascii=False, sort_keys=True)
    diff = "\n".join(difflib.unified_diff(
        expected_str.splitlines(),
        actual_str.splitlines(),
        fromfile=golden_path.name,
        tofile=f"{profile_id}.actual",
        lineterm="",
        n=3,
    ))
    pytest.fail(
        f"Narrative regression for {profile_id}:\n"
        f"If intentional, run `{regen_hint}` + commit.\n\n{diff}"
    )


@pytest.mark.regression
@pytest.mark.parametrize("profile_id", profile_ids())
def test_profile_narrative_byte_diff(profile_id: str, tmp_path: Path) -> None:
    """<profile>.yaml → generate → byte-diff vs <profile>.golden.json."""
    golden_path = FIXTURE_DIR / f"{profile_id}.golden.json"
    assert golden_path.is_file(), (
        f"missing golden JSON: {golden_path}. Run "
        f"`clinosim regenerate-goldens --profile {profile_id}` to bootstrap."
    )

    _run_test_disease(profile_id, tmp_path)

    narr_dir = tmp_path / "cif" / "narratives" / "template" / "documents"
    if not narr_dir.is_dir():
        pytest.fail(f"no narratives written for {profile_id} (expected {narr_dir})")

    actual = _collect_narratives(narr_dir)
    _assert_matches_golden(
        profile_id, actual, golden_path,
        regen_hint=f"clinosim regenerate-goldens --profile {profile_id}",
    )


@pytest.mark.regression
@pytest.mark.parametrize("profile_id", llm_mock_profile_ids())
def test_profile_narrative_llm_mock_byte_diff(profile_id: str, tmp_path: Path) -> None:
    """<profile>.yaml → generate → narrate --provider mock → byte-diff vs llm-mock golden."""
    golden_path = FIXTURE_DIR / f"{profile_id}.llm-mock.golden.json"
    assert golden_path.is_file(), f"missing llm-mock golden: {golden_path}"

    _run_test_disease(profile_id, tmp_path)

    # Mirror `regenerate-goldens --provider mock`: narrate the structural CIF
    # with the deterministic MockProvider under the llm-mock version id.
    profile = yaml.safe_load((FIXTURE_DIR / f"{profile_id}.yaml").read_text())
    cif_dir = tmp_path / "cif"
    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "narrate",
         "--cif-dir", str(cif_dir), "--provider", "mock",
         "--country", str(profile.get("country", "US")),
         "--seed", str(profile.get("random_seed", 42)),
         "--version-id", LLM_MOCK_VERSION_ID, "--no-set-current"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, (
        f"narrate --provider mock failed for {profile_id}:\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )

    narr_dir = cif_dir / "narratives" / LLM_MOCK_VERSION_ID / "documents"
    if not narr_dir.is_dir():
        pytest.fail(f"no llm-mock narratives written for {profile_id} (expected {narr_dir})")

    actual = _collect_narratives(narr_dir)
    _assert_matches_golden(
        profile_id, actual, golden_path,
        regen_hint=f"clinosim regenerate-goldens --profile {profile_id} --provider mock",
    )
