"""Code never compares a language with a literal such as ``"ja"`` to pick
text (code-mapping spec §1.6, §9; Issue #2455). Text is selected through
``clinosim.locale.localized`` so that a new language is a data change.

The check is on the AST: ``x == "ja"`` / ``x != "en"`` and
``x in ("ja", ...)``. Key-presence checks (``"en" in entry``) are not
selections and are not counted. Sites that remain are a ratchet: each file's
count is pinned to the issue that removes it, so a new comparison fails and
a removed one must shrink the table.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import clinosim

pytestmark = pytest.mark.unit

_ROOT = Path(clinosim.__file__).parent
_LANGS = frozenset({"ja", "en"})

# Comparisons that are not a display selection, with the reason.
_ALLOWED = {
    "locale/localized.py": (1, "the selection API itself"),
    "modules/output/fhir_r4/labs/coding_package.py": (1, "reads the language of a designation in the JP-CLINS package"),
}

# file → (comparisons, issue that removes them). Empty: every display
# selection goes through data (Issue #2483).
_RATCHET: dict[str, tuple[int, int]] = {}


def _is_lang(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value in _LANGS


def language_comparisons(source: str) -> list[int]:
    """Line numbers of comparisons of a value with a language literal."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Compare) and len(node.ops) == 1):
            continue
        op, left, right = node.ops[0], node.left, node.comparators[0]
        if isinstance(op, (ast.Eq, ast.NotEq)) and (_is_lang(left) or _is_lang(right)):
            lines.append(node.lineno)
        elif isinstance(op, (ast.In, ast.NotIn)) and isinstance(right, (ast.Tuple, ast.List, ast.Set)):
            if any(_is_lang(e) for e in right.elts):
                lines.append(node.lineno)
    return lines


def _counts() -> dict[str, int]:
    found = {}
    for path in sorted(_ROOT.rglob("*.py")):
        n = len(language_comparisons(path.read_text(encoding="utf-8")))
        if n:
            found[path.relative_to(_ROOT).as_posix()] = n
    return found


def test_detects_the_comparison_forms() -> None:
    src = 'a = lang == "ja"\nb = "en" != x\nc = lang in ("ja", "zh")\nd = "en" in entry\n'
    assert language_comparisons(src) == [1, 2, 3]


def test_no_new_language_literal_comparison() -> None:
    expected = {f: n for f, (n, _) in {**_ALLOWED, **_RATCHET}.items()}
    found = _counts()
    grown = {f: (n, expected.get(f, 0)) for f, n in found.items() if n > expected.get(f, 0)}
    assert not grown, f"new language-literal comparisons (found, allowed): {grown}"


def test_ratchet_shrinks_with_the_fixes() -> None:
    found = _counts()
    stale = {f: (found.get(f, 0), n) for f, (n, _) in {**_ALLOWED, **_RATCHET}.items() if found.get(f, 0) < n}
    assert not stale, f"fewer comparisons than pinned — lower the entry (found, pinned): {stale}"


def test_authored_narrative_languages_come_from_data() -> None:
    """Japanese-only narrative pipelines are gated on the language list in
    ``country_language.yaml``, not on a literal (Issue #2483)."""
    from clinosim.countries import has_authored_narrative

    assert has_authored_narrative("ja") and has_authored_narrative("JP") and has_authored_narrative("ja-JP")
    assert not has_authored_narrative("en") and not has_authored_narrative("fr")
