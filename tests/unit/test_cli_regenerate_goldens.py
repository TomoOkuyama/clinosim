"""AD-66 α-min-2c T3: regenerate-goldens CLI unit tests."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


def _write_profile(fixture_dir: Path, name: str, data: dict) -> Path:
    yaml_path = fixture_dir / f"{name}.yaml"
    yaml_path.write_text(yaml.safe_dump(data))
    return yaml_path


def _env_with(fixture_dir: Path) -> dict[str, str]:
    return {**os.environ, "CLINOSIM_PATIENT_PROFILE_DIR": str(fixture_dir)}


def test_regenerate_goldens_help():
    """`clinosim regenerate-goldens --help` mentions --profile and --all."""
    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "regenerate-goldens", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert "--profile" in result.stdout
    assert "--all" in result.stdout
    # β-JP-1 chain 1b T1: LLM golden support
    assert "--provider" in result.stdout
    assert "--llm-config" in result.stdout
    assert "--model-tag" in result.stdout


def test_regenerate_single_profile(tmp_path: Path):
    """--profile <name> writes <name>.golden.json in the fixture dir."""
    fixture_dir = tmp_path / "patient_profiles"
    fixture_dir.mkdir()
    _write_profile(fixture_dir, "single_test", {
        "profile_id": "single_test",
        "disease_id": "bacterial_pneumonia",
        "country": "US",
        "severity": "moderate",
        "count": 1,
        "random_seed": 42,
    })

    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "regenerate-goldens",
         "--profile", "single_test"],
        capture_output=True, text=True, check=False,
        env=_env_with(fixture_dir),
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    golden_path = fixture_dir / "single_test.golden.json"
    assert golden_path.is_file(), "golden JSON not written"
    golden = json.loads(golden_path.read_text())
    assert isinstance(golden, dict), "golden should be document_id → narrative_dict"


def test_regenerate_all_profiles(tmp_path: Path):
    """--all iterates every YAML in the fixture dir."""
    fixture_dir = tmp_path / "patient_profiles"
    fixture_dir.mkdir()
    for name in ("all_test_a", "all_test_b"):
        _write_profile(fixture_dir, name, {
            "profile_id": name,
            "disease_id": "bacterial_pneumonia",
            "country": "US",
            "severity": "moderate",
            "count": 1,
            "random_seed": 42,
        })

    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "regenerate-goldens", "--all"],
        capture_output=True, text=True, check=False,
        env=_env_with(fixture_dir),
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert (fixture_dir / "all_test_a.golden.json").is_file()
    assert (fixture_dir / "all_test_b.golden.json").is_file()


def test_profile_and_all_mutually_exclusive(tmp_path: Path):
    """--profile and --all are mutually exclusive."""
    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "regenerate-goldens",
         "--profile", "x", "--all"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "not allowed" in result.stderr.lower() or "argument" in result.stderr.lower()


def test_regenerate_is_idempotent(tmp_path: Path):
    """Running --profile twice yields byte-identical golden."""
    fixture_dir = tmp_path / "patient_profiles"
    fixture_dir.mkdir()
    _write_profile(fixture_dir, "idem_test", {
        "profile_id": "idem_test",
        "disease_id": "bacterial_pneumonia",
        "country": "US",
        "severity": "moderate",
        "count": 1,
        "random_seed": 42,
    })
    env = _env_with(fixture_dir)

    subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "regenerate-goldens",
         "--profile", "idem_test"],
        env=env, capture_output=True, text=True, check=True,
    )
    first = (fixture_dir / "idem_test.golden.json").read_text()

    subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "regenerate-goldens",
         "--profile", "idem_test"],
        env=env, capture_output=True, text=True, check=True,
    )
    second = (fixture_dir / "idem_test.golden.json").read_text()

    assert first == second, "regenerate-goldens is not idempotent (byte-diff between two runs)"


# --- β-JP-1 chain 1b T1: --provider {template,mock,bedrock,ollama} ---


def test_regenerate_mock_provider_writes_llm_mock_golden(tmp_path: Path):
    """--provider mock writes <name>.llm-mock.golden.json (template golden untouched)."""
    fixture_dir = tmp_path / "patient_profiles"
    fixture_dir.mkdir()
    _write_profile(fixture_dir, "mock_test", {
        "profile_id": "mock_test",
        "disease_id": "bacterial_pneumonia",
        "country": "US",
        "severity": "moderate",
        "count": 1,
        "random_seed": 42,
    })

    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "regenerate-goldens",
         "--profile", "mock_test", "--provider", "mock"],
        capture_output=True, text=True, check=False,
        env=_env_with(fixture_dir),
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    golden_path = fixture_dir / "mock_test.llm-mock.golden.json"
    assert golden_path.is_file(), "llm-mock golden JSON not written"
    assert not (fixture_dir / "mock_test.golden.json").is_file(), (
        "--provider mock must NOT touch the template golden"
    )
    golden = json.loads(golden_path.read_text())
    assert isinstance(golden, dict) and golden, "golden should be document_id → narrative dict"
    # At least one template_seed doc must carry actual mock-LLM section text —
    # otherwise the narrate step silently ran template-only (PR-90 class).
    all_text = json.dumps(golden, ensure_ascii=False)
    assert "[Mock LLM response" in all_text, "mock provider output missing from golden"


def test_regenerate_mock_provider_model_tag_override(tmp_path: Path):
    """--model-tag TAG overrides the filename tag derived from the provider."""
    fixture_dir = tmp_path / "patient_profiles"
    fixture_dir.mkdir()
    _write_profile(fixture_dir, "tag_test", {
        "profile_id": "tag_test",
        "disease_id": "bacterial_pneumonia",
        "country": "US",
        "severity": "moderate",
        "count": 1,
        "random_seed": 42,
    })

    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "regenerate-goldens",
         "--profile", "tag_test", "--provider", "mock", "--model-tag", "mymodel"],
        capture_output=True, text=True, check=False,
        env=_env_with(fixture_dir),
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert (fixture_dir / "tag_test.llm-mymodel.golden.json").is_file()


def test_regenerate_template_rejects_llm_only_flags(tmp_path: Path):
    """--model-tag / --llm-config with --provider template = fail-loud (exit != 0)."""
    fixture_dir = tmp_path / "patient_profiles"
    fixture_dir.mkdir()
    for extra in (["--model-tag", "x"], ["--llm-config", "/tmp/nonexistent.yaml"]):
        result = subprocess.run(
            [sys.executable, "-m", "clinosim.simulator.cli", "regenerate-goldens",
             "--profile", "whatever", *extra],
            capture_output=True, text=True, check=False,
            env=_env_with(fixture_dir),
        )
        assert result.returncode != 0, f"expected rejection for {extra}"
        assert "provider" in result.stderr.lower()


def test_regenerate_mock_provider_is_idempotent(tmp_path: Path):
    """Two --provider mock runs yield byte-identical llm-mock goldens (AD-16)."""
    fixture_dir = tmp_path / "patient_profiles"
    fixture_dir.mkdir()
    _write_profile(fixture_dir, "mock_idem", {
        "profile_id": "mock_idem",
        "disease_id": "bacterial_pneumonia",
        "country": "US",
        "severity": "moderate",
        "count": 1,
        "random_seed": 42,
    })
    env = _env_with(fixture_dir)
    cmd = [sys.executable, "-m", "clinosim.simulator.cli", "regenerate-goldens",
           "--profile", "mock_idem", "--provider", "mock"]

    subprocess.run(cmd, env=env, capture_output=True, text=True, check=True)
    first = (fixture_dir / "mock_idem.llm-mock.golden.json").read_text()
    subprocess.run(cmd, env=env, capture_output=True, text=True, check=True)
    second = (fixture_dir / "mock_idem.llm-mock.golden.json").read_text()

    assert first == second, "mock llm golden is not byte-stable across two subprocess runs"
