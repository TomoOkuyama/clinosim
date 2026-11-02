"""The LLM-service template fallbacks read their text from the phrase
catalog (Issue #2399)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import clinosim
from clinosim.locale.i18n import _load_phrase_catalog
from clinosim.modules.llm_service import engine as llm_engine
from clinosim.modules.llm_service.engine import PatientSummary

pytestmark = pytest.mark.unit

_JP = re.compile(r"[぀-ヿ一-鿿]")
_PS = PatientSummary(age=72, sex="male", chief_complaint="fever", current_diagnosis="pneumonia", hospital_day=3)


def test_no_japanese_literal_in_the_llm_engine() -> None:
    tree = ast.parse((Path(clinosim.__file__).parent / "modules/llm_service/engine.py").read_text(encoding="utf-8"))
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


def test_every_template_entry_has_both_languages() -> None:
    for key, entry in _load_phrase_catalog()["llm_template"].items():
        assert entry.get("en") and entry.get("ja"), key


def test_japanese_output_has_no_english_empty_markers() -> None:
    texts = [
        llm_engine._death_summary_template(_PS, {}, "ja"),
        llm_engine._operative_note_template(_PS, {}, "ja"),
        llm_engine._procedure_note_template(_PS, {}, "ja"),
    ]
    for text in texts:
        for marker in ("(none)", "(none documented)", "(not available)", "合併症: None"):
            assert marker not in text, (marker, text)


def test_english_templates() -> None:
    assert llm_engine._chief_complaint({}, "en") == "3-day history of fever, cough, dyspnea."
    assert (
        llm_engine._chief_complaint({"symptoms": ["発熱"], "symptom_days": 2}, "ja") == "2日前からの発熱を主訴に来院。"
    )
    note = llm_engine._procedure_note_template(_PS, {"findings": "clear"}, "en")
    assert "Findings: clear\n" in note and note.endswith("Outcome: Successful")
