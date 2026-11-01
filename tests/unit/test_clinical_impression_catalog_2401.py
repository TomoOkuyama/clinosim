"""ClinicalImpression labels, phases and descriptions come from the phrase
catalog (Issue #2401)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import clinosim
from clinosim.locale.i18n import t

pytestmark = pytest.mark.unit

_JP = re.compile(r"[぀-ヿ一-鿿]")


def test_no_japanese_literal_in_the_document_engine() -> None:
    tree = ast.parse((Path(clinosim.__file__).parent / "modules/document/engine.py").read_text(encoding="utf-8"))
    docstrings = {
        id(n.body[0].value)
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Module))
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
    }
    hits = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings and _JP.search(n.value)
    ]
    assert not hits, hits


@pytest.mark.parametrize(
    ("lang", "expected"),
    [
        (
            "en",
            "Day 2 of 5 inpatient clinical assessment for pneumonia (moderate) — acute phase. Attending review of "
            "vitals, medication response, complication risk, and progress toward discharge criteria.",
        ),
        (
            "ja",
            "入院第2病日／全5病日 臨床評価（pneumonia）（moderate） — 急性期。"
            "バイタル・薬効反応・合併症リスク・退院基準への進捗を主治医が評価。",
        ),
    ],
)
def test_description(lang: str, expected: str) -> None:
    text = t(
        "clinical_impression.description",
        lang,
        enc=t("clinical_impression.enc_label.inpatient", lang),
        day=2,
        los=5,
        dx_part=t("clinical_impression.dx_part", lang, dx="pneumonia"),
        sev_part=t("clinical_impression.sev_part", lang, severity="moderate"),
        phase=t("clinical_impression.phase.acute_phase", lang),
    )
    assert text == expected
