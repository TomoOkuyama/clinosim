"""Issue #3410: a joined exam or objective never doubles a sentence
terminator, and the ankle sprain exam states the neurovascular status once."""

from __future__ import annotations

import glob
import re
from pathlib import Path

import pytest
import yaml

from clinosim.modules.document.narrative.renderers._shared_helpers import format_physical_exam

pytestmark = pytest.mark.unit

_DOUBLED = re.compile(r"。。|[A-Za-z0-9)]\.\. ")
_EXAM_DIR = Path(__file__).resolve().parents[5] / "clinosim" / "modules" / "encounter" / "reference_data"


def test_format_physical_exam_does_not_double_terminator_en() -> None:
    out = format_physical_exam(
        {"musculoskeletal": "Limited ROM. Neurovascularly intact.", "neurological": "Alert"}, "moderate", "en"
    )
    assert ".." not in out
    assert out.endswith("Alert")


def test_format_physical_exam_does_not_double_terminator_ja() -> None:
    out = format_physical_exam({"musculoskeletal": "ROM制限あり。", "neurological": "意識清明"}, "moderate", "ja")
    assert "。。" not in out
    assert out.endswith("意識清明")
    assert "。。" not in out


def _exam_texts(node: object):
    if isinstance(node, dict):
        if "physical_exam" in node and isinstance(node["physical_exam"], dict):
            for lang_block in node["physical_exam"].values():
                if isinstance(lang_block, dict):
                    yield lang_block
        for v in node.values():
            yield from _exam_texts(v)
    elif isinstance(node, list):
        for v in node:
            yield from _exam_texts(v)


def test_every_encounter_yaml_exam_renders_without_doubled_terminator() -> None:
    files = sorted(glob.glob(str(_EXAM_DIR / "*.yaml")))
    assert files
    checked = 0
    for f in files:
        data = yaml.safe_load(Path(f).read_text(encoding="utf-8"))
        for block in _exam_texts(data):
            for lang in ("en", "ja"):
                out = format_physical_exam(block, "moderate", lang)
                assert not _DOUBLED.search(out), (f, out)
                checked += 1
    assert checked


def test_ankle_sprain_states_neurovascular_status_once() -> None:
    text = (_EXAM_DIR / "ankle_sprain.yaml").read_text(encoding="utf-8")
    assert len(re.findall(r"[Nn]eurovascular", text)) == 1
    assert text.count("神経血管正常") == 0
