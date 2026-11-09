"""Guard: every JP coding of an English-only code system carries an English
display (code-mapping spec 5.3 dual slot; Issue #3026).

Generates a small JP cohort and checks every Coding whose system is LOINC,
SNOMED CT, HL7 terminology / FHIR, DICOM or CVX: it has a ``display`` and the
display has no Japanese. The Japanese label belongs in ``CodeableConcept.text``.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from clinosim.codes import ENGLISH_ONLY_SYSTEM_PREFIXES, get_system_uri

_JA = re.compile(r"[぀-ヿ一-鿿]")
_SYSTEMS = (*ENGLISH_ONLY_SYSTEM_PREFIXES, get_system_uri("cvx"))


def _codings(node: object, path: str, out: list[tuple[str, dict]]) -> None:
    if isinstance(node, dict):
        if isinstance(node.get("system"), str) and isinstance(node.get("code"), str):
            out.append((path, node))
        for key, value in node.items():
            if key not in ("identifier", "meta", "extension"):
                _codings(value, f"{path}.{key}", out)
    elif isinstance(node, list):
        for item in node:
            _codings(item, path, out)


@pytest.mark.integration
def test_jp_english_only_codings_carry_an_english_display(tmp_path: Path) -> None:
    out = tmp_path / "jp"
    args = [sys.executable, "-m", "clinosim.simulator.cli", "simulate", "-p", "150", "-s", "42", "--country", "JP"]
    args += ["--allow-legacy", "--start", "2025-11-01", "--end", "2026-11-01", "-o", str(out), "--format", "fhir-r4"]
    r = subprocess.run(args, capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stderr[-2000:]
    bad: dict[str, int] = {}
    for path in sorted((out / "fhir_r4").glob("*.ndjson")):
        for line in path.read_text().splitlines():
            found: list[tuple[str, dict]] = []
            resource = json.loads(line)
            _codings(resource, resource["resourceType"], found)
            for where, coding in found:
                if not coding["system"].startswith(_SYSTEMS) or "unitsofmeasure" in coding["system"]:
                    continue
                display = coding.get("display") or ""
                if not display or _JA.search(display):
                    key = f"{where} {coding['system']}"
                    bad[key] = bad.get(key, 0) + 1
    assert not bad, sorted(bad.items(), key=lambda kv: -kv[1])[:40]
