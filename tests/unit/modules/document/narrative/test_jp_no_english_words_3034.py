"""JP documents read as Japanese EHR text (Issue #3034).

Japanese records write abbreviations, scale names, eponyms and units in
Latin script (CRP, HbA1c, SpO2, mMRC, NYHA, Barthel, mg/dL, ...), but not
ordinary English words ("score", "wheeze", "moderate"). This guard scans
every Japanese string of the narrative phrase sources and rejects an English
word that is not on the allowlist.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

import clinosim
from clinosim.locale.loader import condition_stage_display
from clinosim.modules.document.narrative._localization import _localize_stage

pytestmark = pytest.mark.unit

_ROOT = Path(clinosim.__file__).parent
_SOURCES = (
    "locale/shared/narrative_phrases.yaml",
    "locale/shared/narrative_labels.yaml",
    "locale/shared/narrative_stage_tokens.yaml",
    "locale/shared/condition_stage_labels.yaml",
    "modules/document/reference_data/chronic_soap_templates.yaml",
    "modules/document/reference_data/cc-pe-consistency-keywords.yaml",
)
# A word with lower-case letters (not an abbreviation, code or unit).
_WORD = re.compile(r"(?<![A-Za-z0-9])[A-Za-z][a-z]+(?:-[a-z]+)*(?![A-Za-z0-9])")
# Written in Latin script in Japanese records: eponyms and scale / unit
# words that Japanese charts keep as written.
_ALLOWED = {
    "Barthel",
    "Braden",
    "Morse",
    "Apgar",
    "Glasgow",
    "Hoehn",
    "Yahr",
    "Child",
    "Pugh",
    "Killip",
    "Forrester",
    "Alzheimer",
    "Parkinson",
    "Kussmaul",
    "Wells",
    "Geneva",
    "Ranson",
    "Blatchford",
    "Rockall",
    "Wexner",
    "Hb",
    "Ht",
    "Hct",
    "Rh",
    "Rankin",
    "Plt",
    "Cr",
    "Na",
    "Ca",
    "Mg",
    "Alb",
    "Fe",
    "Glu",
    "Lac",
    "Ar",
    "Hg",
    "pH",
    "mg",
    "mL",
    "dL",
    "kg",
    "mmHg",
    "bpm",
    "cm",
    "mm",
    "mEq",
    "mmol",
    "min",
    "sec",
    "hr",
    "mcg",
    "kcal",
    "proBNP",
    "dimer",
    "mRS",
    "mMRC",
    "eGFR",
    "qSOFA",
    "aPTT",
    "tPA",
    "rt",
}


def _ja_strings(node: Any, key: str = "") -> list[str]:
    """Every string under a ``ja`` key, plus the bare strings of the
    Japanese-only pools of the consistency-keyword file."""
    out: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            out += _ja_strings(v, str(k))
    elif isinstance(node, list):
        for v in node:
            out += _ja_strings(v, key)
    elif isinstance(node, str) and (key == "ja" or re.search(r"[぀-ヿ㐀-鿿]", node)):
        if not re.fullmatch(r"[a-z0-9-]+", node):  # a code-system key, not text
            out.append(node)
    return out


def _english_words(text: str) -> list[str]:
    text = re.sub(r"\{[^}]*\}", "", text)  # placeholders
    return [w for w in _WORD.findall(text) if w not in _ALLOWED]


@pytest.mark.parametrize("source", _SOURCES)
def test_japanese_phrases_have_no_english_words(source: str) -> None:
    data = yaml.safe_load((_ROOT / source).read_text(encoding="utf-8"))
    offenders = sorted({(w, s.strip()[:60]) for s in _ja_strings(data) for w in _english_words(s)})
    assert not offenders, offenders


def test_a_jp_lung_exam_with_crackles_reads_japanese() -> None:
    data = yaml.safe_load((_ROOT / _SOURCES[-1]).read_text(encoding="utf-8"))
    pool = data["pe_replacement_pool"]["severe_dyspnea"]
    assert any("断続性ラ音" in line for line in pool)
    assert not any(re.search(r"crackles|wheeze|rhonchi", line) for line in pool)


@pytest.mark.parametrize(
    ("stage", "ja"),
    [("PHQ-9 moderate", "PHQ-9 中等度"), ("Stage 1", "ステージ1"), ("Long-standing persistent", "長期持続性")],
)
def test_narrative_stage_labels_follow_the_condition_stage_table(stage: str, ja: str) -> None:
    assert _localize_stage(stage, "ja") == condition_stage_display(stage, "ja") == ja
    assert _localize_stage(stage, "en") == stage
