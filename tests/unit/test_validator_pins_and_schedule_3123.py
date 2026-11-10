"""The HL7 validator workflows are pinned and run nightly (Issue #3123)."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _env(name: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (ROOT / ".github" / name).read_text().splitlines():
        m = re.match(r"([A-Z_][A-Z0-9_]*)=(.*)", line.strip())
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


@pytest.mark.parametrize("pins", ["us-validator-pins.env", "jp-validator-pins.env"])
def test_the_validator_and_every_downloaded_package_are_pinned(pins: str) -> None:
    env = _env(pins)
    assert env["VALIDATOR_VERSION"]
    assert _SHA256.match(env["VALIDATOR_SHA256"]), pins
    for key, url in env.items():
        if key.endswith("_PACKAGE_URL") and url:
            assert _SHA256.match(env[key.replace("_URL", "_SHA256")]), key


def test_jp_pins_cover_the_dependencies_no_registry_publishes() -> None:
    env = _env("jp-validator-pins.env")
    assert (env["JP_CORE_PACKAGE_ID"], env["JP_CORE_PACKAGE_VERSION"]) == ("jp-core.r4", "1.1.2-clins")
    assert (env["JP_TERMINOLOGY_PACKAGE_ID"], env["JP_TERMINOLOGY_PACKAGE_VERSION"]) == (
        "jpfhir-terminology.r4",
        "2.0.0",
    )
    assert env["JP_CLINS_PACKAGE_URL"] and env["JP_ECHECKUP_PACKAGE_URL"]


@pytest.mark.parametrize(("workflow", "job"), [("us-validate.yml", "us-validate"), ("jp-validate.yml", "jp-validate")])
def test_the_workflow_runs_nightly_with_the_validator(workflow: str, job: str) -> None:
    doc = yaml.safe_load((ROOT / ".github" / "workflows" / workflow).read_text())
    on = doc["on"] if "on" in doc else doc[True]
    assert on["schedule"][0]["cron"]
    assert "workflow_dispatch" in on and "pull_request" in on
    spec = doc["jobs"][job]
    assert "schedule" in spec["if"]
    for step in spec["steps"]:
        cond = str(step.get("if", ""))
        if "run_validator" in cond:
            assert "github.event_name == 'schedule'" in cond, step.get("name")


@pytest.mark.parametrize("script", ["validate_us.sh", "validate_jp.sh"])
def test_the_bridge_runs_under_bash_3(script: str) -> None:
    text = (ROOT / "scripts" / script).read_text()
    assert "declare -A" not in text
    bash = shutil.which("bash")
    if bash:
        assert subprocess.run([bash, "-n", str(ROOT / "scripts" / script)]).returncode == 0
