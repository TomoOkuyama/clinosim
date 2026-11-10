"""Guard: every emitted ICD-10-CM, LOINC, SNOMED CT and YJ coding carries a
display of its code system (Issue #3127).

Generates a small US and JP cohort and compares each coding's display with the
authoritative extracts in ``clinosim/codes/authoritative/``. Codes registered
in ``tests/unit/codes/authoritative_override_allowlist.yaml`` (tracked wrong
codes) and codes absent from an extract are not judged here.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_AUTH = _ROOT / "clinosim" / "codes" / "authoritative"
_EXTRACTS = {
    "http://loinc.org": ("loinc", "loinc_2_83_tx.json"),
    "http://hl7.org/fhir/sid/icd-10-cm": ("icd-10-cm", "icd10cm_2027_cms.json"),
    "http://snomed.info/sct": ("snomed-ct", "snomed_ct_tx.json"),
    "http://capstandard.jp/iyaku.info/CodeSystem/YJ-code": ("yj", "yj_medis_hot_20261031.json"),
}


def _allowed() -> dict[str, dict[str, set[str]]]:
    out: dict[str, dict[str, set[str]]] = {}
    for system, (_key, name) in _EXTRACTS.items():
        names: dict[str, set[str]] = {}
        for concept in json.loads((_AUTH / name).read_text(encoding="utf-8"))["concept"]:
            names[concept["code"]] = {concept["display"], concept.get("short_display") or ""} | {
                d["value"] for d in concept.get("designation") or []
            }
        out[system] = names
    return out


def _tracked_wrong_codes() -> dict[str, set[str]]:
    allow = yaml.safe_load((_ROOT / "tests/unit/codes/authoritative_override_allowlist.yaml").read_text()) or {}
    return {system: {str(c) for c in (allow.get(key) or {})} for system, (key, _name) in _EXTRACTS.items()}


def _codings(node: object, out: list[dict]) -> None:
    if isinstance(node, dict):
        if node.get("system") in _EXTRACTS and isinstance(node.get("code"), str) and "display" in node:
            out.append(node)
        for key, value in node.items():
            if key != "extension":
                _codings(value, out)
    elif isinstance(node, list):
        for item in node:
            _codings(item, out)


@pytest.mark.integration
@pytest.mark.parametrize("country", ["US", "JP"])
def test_emitted_displays_are_code_system_displays(tmp_path: Path, country: str) -> None:
    out = tmp_path / country
    args = [sys.executable, "-m", "clinosim.simulator.cli", "simulate", "-p", "150", "-s", "42", "--country", country]
    args += ["--allow-legacy"] if country == "JP" else []
    args += ["--start", "2025-11-01", "--end", "2026-11-01", "-o", str(out), "--format", "fhir-r4"]
    r = subprocess.run(args, capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stderr[-2000:]
    allowed, wrong = _allowed(), _tracked_wrong_codes()
    bad: dict[str, int] = {}
    checked = 0
    for path in sorted((out / "fhir_r4").glob("*.ndjson")):
        for line in path.read_text().splitlines():
            found: list[dict] = []
            _codings(json.loads(line), found)
            for coding in found:
                system, code = coding["system"], coding["code"]
                if code in wrong[system] or code not in allowed[system]:
                    continue
                checked += 1
                if coding["display"] not in allowed[system][code]:
                    key = f"{system} {code} {coding['display']!r}"
                    bad[key] = bad.get(key, 0) + 1
    assert checked, "no coding checked"
    assert not bad, sorted(bad.items(), key=lambda kv: -kv[1])[:40]
