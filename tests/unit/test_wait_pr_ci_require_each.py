"""wait-pr-ci.sh requires every --require-pattern alternative to be present in the rollup."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "wait-pr-ci.sh"


def _run(tmp_path: Path, checks: list[str]) -> int:
    rollup = [{"name": n, "status": "COMPLETED", "conclusion": "SUCCESS"} for n in checks]
    fake = tmp_path / "gh"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        "  *headRefOid*) echo abc123 ;;\n"
        f"  *statusCheckRollup*) echo '{json.dumps(rollup)}' ;;\n"
        "esac\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    return subprocess.run(
        [
            "bash",
            str(_SCRIPT),
            "1",
            "--poll-seconds",
            "1",
            "--timeout-seconds",
            "2",
            "--require-pattern",
            "Unit tests|Signed-off-by",
        ],
        env=env,
        capture_output=True,
        text=True,
    ).returncode


def test_only_dco_check_does_not_satisfy_unit_tests_requirement(tmp_path: Path) -> None:
    assert _run(tmp_path, ["Signed-off-by check"]) == 124


def test_all_required_names_present_passes(tmp_path: Path) -> None:
    assert _run(tmp_path, ["Signed-off-by check", "Unit tests (Py 3.12 shard 1/3)"]) == 0
