"""Qualitative lab results are printed in the note language (Issue #3561).

The JP ED note printed the stored English wording of a urinalysis / urine drug
screen ("尿検査 2+ leukocytes, trace blood"); the FHIR output already shows it
through ``lab_result_display``. Every qualitative option the simulator can store
must have a Japanese wording.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from clinosim.locale.loader import lab_result_display
from clinosim.modules.document.narrative._localization import lab_value_text
from clinosim.modules.document.narrative.renderers.section_builders.ed_note import build_ed_workup
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.observation import _variability_defaults as variability
from tests.unit.modules.document.narrative.test_ed_note_content_3244 import _WHEN, _ctx

pytestmark = pytest.mark.unit

_GEN = TemplateNarrativeGenerator()
_ROOT = Path(__file__).resolve().parents[5] / "clinosim"
_LATIN_WORD = re.compile(r"[A-Za-z]{3,}")


def _order(name: str, value: str) -> dict:
    return {
        "order_id": "L1",
        "encounter_id": "ENC-1",
        "order_type": "lab",
        "display_name": name,
        "ordered_datetime": _WHEN.isoformat(),
        "result": {
            "lab_name": name,
            "value": value,
            "unit": "{qualitative}",
            "result_datetime": _WHEN.isoformat(),
        },
    }


def test_the_jp_ed_note_localizes_a_qualitative_result_and_the_us_note_keeps_it() -> None:
    order = _order("Urinalysis", "2+ leukocytes, trace blood")
    ja, _ = build_ed_workup(_GEN, _ctx("renal_colic", "ja", orders=[order]))
    en, _ = build_ed_workup(_GEN, _ctx("renal_colic", "en", orders=[order]))
    assert "白血球(2+)、尿潜血(±)" in ja and "leukocytes" not in ja, ja
    assert "2+ leukocytes, trace blood" in en, en


def test_a_numeric_result_is_unchanged() -> None:
    assert lab_value_text("WBC", 8.2, "10*3/uL", "ja") == "8.2"


def _stored_qualitative_options() -> set[str]:
    options: set[str] = set()
    for name in dir(variability):
        if name.endswith("_RESULT_DIST"):
            options.update(getattr(variability, name).options)

    def walk(node: object) -> None:
        if isinstance(node, dict):
            dist = node.get("result_distribution")
            if isinstance(dist, dict):
                options.update(o for o in dist.get("options", []) if isinstance(o, str))
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    for path in (_ROOT / "modules").rglob("*.yaml"):
        walk(yaml.safe_load(path.read_text(encoding="utf-8")))
    return options


def test_every_stored_qualitative_result_has_a_japanese_wording() -> None:
    options = _stored_qualitative_options()
    assert len(options) > 20
    untranslated = {o: lab_result_display(o, "ja") for o in options if _LATIN_WORD.search(lab_result_display(o, "ja"))}
    assert not untranslated, untranslated
