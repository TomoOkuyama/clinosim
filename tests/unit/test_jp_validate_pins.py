"""P2-13 PR3 sub-PR-C 高度化(session 48):JP validator bridge pin file テスト.

Pin file の shape / bash script の syntax / workflow yml の shape を静的に検証。
実 validator は環境依存なため、CI ではこのユニット層のみが常時走る。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PIN_FILE = ROOT / ".github" / "jp-validator-pins.env"
VALIDATE_SH = ROOT / "scripts" / "validate_jp.sh"
PIN_SH = ROOT / "scripts" / "pin_jp_validator.sh"
WORKFLOW_YML = ROOT / ".github" / "workflows" / "jp-validate.yml"


def _load_env(path: Path) -> dict[str, str]:
    """`.env`(shell-source-able)の KEY=VALUE を dict にする。"""
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"([A-Z_][A-Z0-9_]*)=(.*)", line)
        if m:
            result[m.group(1)] = m.group(2).strip()
    return result


@pytest.mark.unit
def test_pin_file_exists_with_expected_keys():
    """`.github/jp-validator-pins.env` が期待 key を全て含む。"""
    assert PIN_FILE.exists(), f"pin file missing: {PIN_FILE}"
    env = _load_env(PIN_FILE)
    required_keys = {
        "VALIDATOR_VERSION",
        "VALIDATOR_SHA256",
        "JP_CORE_PACKAGE_ID",
        "JP_CORE_PACKAGE_VERSION",
        "JP_CORE_PACKAGE_URL",
        "JP_CORE_PACKAGE_SHA256",
        "JP_CLINS_PACKAGE_ID",
        "JP_CLINS_PACKAGE_VERSION",
        "JP_CLINS_PACKAGE_URL",
        "JP_CLINS_PACKAGE_SHA256",
        "JP_ECHECKUP_PACKAGE_ID",
        "JP_ECHECKUP_PACKAGE_VERSION",
        "JP_ECHECKUP_PACKAGE_URL",
        "JP_ECHECKUP_PACKAGE_SHA256",
    }
    missing = required_keys - env.keys()
    assert not missing, f"pin file missing keys: {missing}"


@pytest.mark.unit
def test_pin_file_validator_version_non_empty():
    """VALIDATOR_VERSION は空にしない(URL 決定に必要)。"""
    env = _load_env(PIN_FILE)
    assert env["VALIDATOR_VERSION"], "VALIDATOR_VERSION must be set"


@pytest.mark.unit
def test_pin_file_no_placeholders_in_id_version():
    """*_PACKAGE_ID / _VERSION に placeholder(`<xxx>`)残留なし。"""
    env = _load_env(PIN_FILE)
    for key in (
        "JP_CORE_PACKAGE_ID",
        "JP_CORE_PACKAGE_VERSION",
    ):
        val = env.get(key, "")
        assert "<" not in val, f"{key} has placeholder: {val!r}"


@pytest.mark.unit
def test_validate_sh_bash_syntax_ok():
    """validate_jp.sh は bash -n で構文エラーなし。"""
    if shutil.which("bash") is None:
        pytest.skip("bash not on PATH")
    result = subprocess.run(
        ["bash", "-n", str(VALIDATE_SH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"bash -n failed:\n{result.stdout}\n{result.stderr}"


@pytest.mark.unit
def test_pin_bootstrap_sh_bash_syntax_ok():
    """pin_jp_validator.sh は bash -n で構文エラーなし。"""
    if shutil.which("bash") is None:
        pytest.skip("bash not on PATH")
    result = subprocess.run(
        ["bash", "-n", str(PIN_SH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"bash -n failed:\n{result.stdout}\n{result.stderr}"


@pytest.mark.unit
def test_pin_bootstrap_sh_executable():
    """pin_jp_validator.sh は実行可能ビットが立っている。"""
    import os

    assert os.access(PIN_SH, os.X_OK), f"not executable: {PIN_SH}"


@pytest.mark.unit
def test_workflow_yml_loads_and_has_pin_steps():
    """workflow yml が yaml として load でき、pin verify ステップを含む。"""
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(WORKFLOW_YML.read_text())
    assert doc["name"] == "JP FHIR validate"
    steps = doc["jobs"]["jp-validate"]["steps"]
    step_names = [s.get("name", "") for s in steps]
    assert any("Load validator pins" in n for n in step_names), f"pin load step missing: {step_names}"
    assert any("Verify validator SHA256" in n for n in step_names), f"SHA256 verify step missing: {step_names}"


@pytest.mark.unit
def test_workflow_yml_default_run_validator_true():
    """workflow_dispatch の run_validator default が true(auto-fail gate)。"""
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(WORKFLOW_YML.read_text())
    # yaml が `on:` key を Python bool True に変換するケースを吸収
    on_key = "on" if "on" in doc else True
    trigger = doc[on_key]
    dispatch = trigger["workflow_dispatch"]
    inputs = dispatch["inputs"]
    assert inputs["run_validator"]["default"] is True
    assert inputs["strict_pins"]["default"] is True


@pytest.mark.unit
def test_validate_sh_references_pins_env_and_strict():
    """validate_jp.sh が pins env / STRICT モード / IG_ARGS を実装している。"""
    txt = VALIDATE_SH.read_text()
    assert "CLINOSIM_JP_VAL_PINS" in txt
    assert "CLINOSIM_JP_VAL_STRICT" in txt
    assert "IG_ARGS" in txt
    assert "_verify_sha256" in txt
    assert "_resolve_ig" in txt


@pytest.mark.unit
def test_pin_bootstrap_sh_calls_shasum():
    """pin_jp_validator.sh は sha256 計算を含む(shasum -a 256 呼び出し)。"""
    txt = PIN_SH.read_text()
    assert "shasum -a 256" in txt
    assert "sed -i" in txt  # in-place 書き換え
