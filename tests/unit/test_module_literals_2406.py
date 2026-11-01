"""Simulator and module text comes from catalogs, not Japanese literals in
Python (Issue #2406). Input matchers (keywords, regexes) stay in code."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

import clinosim
from clinosim.locale.i18n import t

pytestmark = pytest.mark.unit

_ROOT = Path(clinosim.__file__).parent
_JP = re.compile(r"[぀-ヿ一-鿿]")

# Text matchers that parse disease-YAML or order text; they are not output.
_MATCHERS = {
    "modules/order/treatment_classifier.py",
    "modules/order/engine.py",  # " または " splits "A or B" drug alternatives
    "modules/imaging/inference.py",
    "audit/axes/jp_language.py",
    "simulator/cli.py",  # --help text naming the Japanese insurance fields
    "simulator/cli_narrate.py",
}
# Covered by #2405's own guard.
_OTHER_ISSUE = {"simulator/medication_pipeline.py", "simulator/daily_loop.py", "simulator/discharge_rx.py"}
_EXCLUDED_TREES = ("modules/output/", "modules/document/", "modules/llm_service/")


def _japanese_literals(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    return [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and _JP.search(n.value)
    ]


def test_no_japanese_literal_in_simulator_and_modules() -> None:
    hits = {}
    for path in sorted(_ROOT.rglob("*.py")):
        rel = path.relative_to(_ROOT).as_posix()
        if rel.startswith(_EXCLUDED_TREES) or rel in _MATCHERS or rel in _OTHER_ISSUE:
            continue
        if lines := _japanese_literals(path):
            hits[rel] = lines
    assert not hits, hits


@pytest.mark.parametrize(
    "section",
    [
        "encounter_intent",
        "safety_text",
        "perinatal_intent",
        "health_checkup",
        "imaging_report",
        "module_text",
        "newborn_screen",
    ],
)
def test_moved_entries_have_both_languages(section: str) -> None:
    data = yaml.safe_load((_ROOT / "locale/shared/narrative_phrases.yaml").read_text(encoding="utf-8"))
    for key, entry in data[section].items():
        assert entry.get("en") and entry.get("ja"), f"{section}.{key}"


def test_phrases_render() -> None:
    assert t("encounter_intent.day_monitoring", "ja", day=3, test="CBC") == "第3病日モニタリング: CBC"
    assert t("module_text.test_given", "en", n=2) == "Patient2"
