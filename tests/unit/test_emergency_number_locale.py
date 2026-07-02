"""β-JP-1 chain 1a adv-1 I-3: emergency phone numbers must match the language.

"119" is Japan's emergency number; English narrative text must say "911"
(the en variant reaches US narratives via the chain-1a disease_protocol
wiring). Data-driven guard: every ``en`` string value in disease + encounter
reference-data YAMLs is scanned for a standalone "119" token (code fields
like ``code_rxnorm: "1191"`` are not ``en`` keys and digit-adjacent matches
are excluded, so LOINC/RxNorm/YJ values cannot false-positive).

The ja variants intentionally keep 119.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

_MODULES = Path(__file__).resolve().parents[2] / "clinosim" / "modules"
_YAML_DIRS = (
    _MODULES / "disease" / "reference_data",
    _MODULES / "encounter" / "reference_data",
)

# Standalone 119 (not part of a longer digit run like "1191" / "2119406")
_JP_EMERGENCY_NUMBER = re.compile(r"(?<!\d)119(?!\d)")


def _collect_en_values(node: Any, path: str, hits: list[tuple[str, str]]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "en" and isinstance(value, str):
                if _JP_EMERGENCY_NUMBER.search(value):
                    hits.append((f"{path}.en", value))
            else:
                _collect_en_values(value, f"{path}.{key}", hits)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _collect_en_values(item, f"{path}[{i}]", hits)


def test_no_jp_emergency_number_in_en_yaml_text() -> None:
    hits: list[tuple[str, str]] = []
    scanned = 0
    for yaml_dir in _YAML_DIRS:
        assert yaml_dir.is_dir(), f"missing reference_data dir: {yaml_dir}"
        for yaml_path in sorted(yaml_dir.glob("*.yaml")):
            scanned += 1
            data = yaml.safe_load(yaml_path.read_text())
            _collect_en_values(data, yaml_path.name, hits)
    assert scanned > 0
    assert not hits, (
        "English text must say 'Call 911', not Japan's 119: "
        + "; ".join(f"{path} = {text!r}" for path, text in hits)
    )
