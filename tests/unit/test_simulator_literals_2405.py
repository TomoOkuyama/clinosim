"""Simulator order intents, hold reasons and notes come from catalogs, not
Japanese literals in Python (Issue #2405)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import clinosim
from clinosim.locale.i18n import t

pytestmark = pytest.mark.unit

_JP = re.compile(r"[぀-ヿ一-鿿]")


@pytest.mark.parametrize(
    "rel", ["simulator/medication_pipeline.py", "simulator/daily_loop.py", "simulator/discharge_rx.py"]
)
def test_no_japanese_literal(rel: str) -> None:
    tree = ast.parse((Path(clinosim.__file__).parent / rel).read_text(encoding="utf-8"))
    docs = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    hits = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and _JP.search(n.value)
    ]
    assert not hits, hits


def test_order_intent_both_languages() -> None:
    assert (
        t("order_intent.escalation", "en", day=2, drug="Heparin", indication="PE") == "Escalation day 2: Heparin (PE)"
    )
    assert (
        t("order_intent.escalation", "ja", day=2, drug="Heparin", indication="PE")
        == "治療エスカレーション第2病日: Heparin (PE)"
    )
