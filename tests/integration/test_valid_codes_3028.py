"""Guard: every ICD coding carries a registered ICD-shaped code and no coding
has an empty code (Issue #3028).

Generates a small US and JP cohort. A disease key under an ICD system, an
ICD code missing from the code table, or ``{"system": ..., "code": ""}``
fails the guard: a concept without a code is sent as text only.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from clinosim.codes import code_exists, get_system_uri
from clinosim.codes.icd10 import is_icd10_shaped

_ICD_SYSTEMS = {get_system_uri(key): key for key in ("icd-10-cm", "icd-10-mhlw", "icd-10")}


def _codings(node: object, path: str, out: list[tuple[str, dict]]) -> None:
    if isinstance(node, dict):
        if isinstance(node.get("system"), str) and "code" in node:
            out.append((path, node))
        for key, value in node.items():
            if key not in ("identifier", "meta", "extension"):
                _codings(value, f"{path}.{key}", out)
    elif isinstance(node, list):
        for item in node:
            _codings(item, path, out)


@pytest.mark.integration
@pytest.mark.parametrize("country", ["US", "JP"])
def test_codings_carry_valid_codes(tmp_path: Path, country: str) -> None:
    out = tmp_path / country
    args = [sys.executable, "-m", "clinosim.simulator.cli", "simulate", "-p", "150", "-s", "42", "--country", country]
    args += ["--allow-legacy"] if country == "JP" else []
    args += ["--start", "2025-11-01", "--end", "2026-11-01", "-o", str(out), "--format", "fhir-r4"]
    r = subprocess.run(args, capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stderr[-2000:]
    bad: dict[str, int] = {}
    icd_seen = 0
    for path in sorted((out / "fhir_r4").glob("*.ndjson")):
        for line in path.read_text().splitlines():
            found: list[tuple[str, dict]] = []
            resource = json.loads(line)
            _codings(resource, resource["resourceType"], found)
            for where, coding in found:
                code = coding.get("code")
                if not isinstance(code, str) or not code.strip():
                    problem = f"empty code: {where} {coding['system']}"
                elif coding["system"] in _ICD_SYSTEMS:
                    icd_seen += 1
                    key = _ICD_SYSTEMS[coding["system"]]
                    if is_icd10_shaped(code) and code_exists(key, code):
                        continue
                    problem = f"invalid ICD: {where} {key} {code}"
                else:
                    continue
                bad[problem] = bad.get(problem, 0) + 1
    assert icd_seen, "no ICD coding found — the guard checked nothing"
    assert not bad, sorted(bad.items(), key=lambda kv: -kv[1])[:40]
