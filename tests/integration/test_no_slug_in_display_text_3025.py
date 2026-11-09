"""Guard: generated FHIR text people read carries no internal slug (Issue #3025).

Generates a small US and JP cohort and scans every human-readable field
(display / text / div / title / description / conclusion / note text and the
decoded text attachments) for snake_case tokens such as ``toilet_use`` or
``CT_angiography``. Codes, ids, references and system URIs are not scanned.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

_SLUG = re.compile(r"(?<![\w/.:#@=-])[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+(?![\w/.-])")
# Echo view keys in ImagingStudy.series.description are named by the imaging
# view table of Issue #3030; drop this exemption once that change is in.
_EXEMPT = {"ImagingStudy:parasternal_long_axis", "ImagingStudy:apical_4_chamber"}
_TEXT_KEYS = {"display", "text", "div", "title", "description", "conclusion", "comment", "patientInstruction"}


def _slugs(node: object, out: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "attachment" and isinstance(value, dict) and str(value.get("contentType", "")).startswith("text"):
                text = base64.b64decode(value.get("data", "") or "").decode("utf-8", "replace")
                out.extend(_SLUG.findall(re.sub(r"<[^>]+>", " ", text)))
            elif isinstance(value, str):
                if key in _TEXT_KEYS:
                    out.extend(_SLUG.findall(re.sub(r"<[^>]+>", " ", value)))
            else:
                _slugs(value, out)
    elif isinstance(node, list):
        for item in node:
            _slugs(item, out)


@pytest.mark.integration
@pytest.mark.parametrize("country", ["US", "JP"])
def test_no_slug_in_generated_text(tmp_path: Path, country: str) -> None:
    out = tmp_path / country
    args = [sys.executable, "-m", "clinosim.simulator.cli", "simulate", "-p", "150", "-s", "42", "--country", country]
    args += ["--start", "2025-11-01", "--end", "2026-11-01", "-o", str(out), "--format", "fhir-r4"]
    if country == "JP":
        args.append("--allow-legacy")
    r = subprocess.run(args, capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stderr[-2000:]
    found: dict[str, int] = {}
    for path in sorted((out / "fhir_r4").glob("*.ndjson")):
        for line in path.read_text().splitlines():
            tokens: list[str] = []
            _slugs(json.loads(line), tokens)
            for tok in tokens:
                if f"{path.stem}:{tok}" in _EXEMPT:
                    continue
                found[f"{path.stem}:{tok}"] = found.get(f"{path.stem}:{tok}", 0) + 1
    assert not found, sorted(found.items(), key=lambda kv: -kv[1])[:30]
