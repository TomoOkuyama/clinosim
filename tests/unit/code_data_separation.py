"""Counter and baseline for the code-data separation ratchet (Issue #3137).

Used by ``tests/unit/test_code_data_separation_3137.py``. Counts, per Python
file under ``clinosim/``, with the AST (not a text search):

* ``country_branches`` — calls to :data:`COUNTRY_PREDICATES` and comparisons
  (``==`` / ``!=`` / ``in`` / ``not in``) with a :data:`COUNTRY_LANGUAGE_LITERALS`
  value;
* ``numeric_literals`` — numeric literals in comparisons, outside
  ``_<topic>_thresholds.py`` / ``_<topic>_defaults.py`` modules and other than
  :data:`TRIVIAL_NUMBERS`.

The committed baseline is ``code_data_separation_baseline.json``: the total per
rule (the only thing the test compares) and an informational list of
content-keyed entries. A key is ``<rule>::<qualified name>::<normalized node
text>`` where the qualified name is the enclosing class / function chain
without the module path (``<module>`` at module level), so a ``git mv`` keeps
every key and a move is not a raise. The test fails only when a rule's total
exceeds the stored total; a decrease passes without editing the baseline. Lower
the stored totals (never inside a feature change) with::

    python -m tests.unit.code_data_separation --write

The command refuses to raise any total: a new branch or literal is moved to
data (YAML, a country profile, a thresholds module), not added to the baseline.
The baseline machinery is shared with the module-boundary ratchet
(``tests/unit/ratchet_baseline.py``).
"""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Iterator
from functools import cache
from pathlib import Path

import clinosim
from tests.unit.ratchet_baseline import Ratchet, Scan, content_key
from tests.unit.ratchet_baseline import walk_qualified as _walk

ROOT = Path(clinosim.__file__).parent
BASELINE = Path(__file__).with_name("code_data_separation_baseline.json")
REGENERATE = "python -m tests.unit.code_data_separation --write"

KINDS = ("country_branches", "numeric_literals")
RULES = {
    "country_branches": "Values that differ by country are data, not code branches",
    "numeric_literals": "Clinical and statistical values are named constants or data, not literals in code",
}

# Country / language predicates whose call is a branch on the country.
COUNTRY_PREDICATES = frozenset({"is_jp", "is_us", "uses_jp_clins_profile"})
# Literals whose comparison is a branch on the country or the output language.
COUNTRY_LANGUAGE_LITERALS = frozenset({"JP", "US", "ja", "en"})
# A comparison whose other side names one of these is not about the country:
# "US" is also the DICOM modality code for ultrasound (imaging).
NOT_A_COUNTRY = ("modality",)

# Files where branching on the country is the point: the country registry
# (``clinosim/countries/__init__.py``) and country packages (``clinosim/countries/<cc>/``).
COUNTRY_PACKAGES = ("countries/",)

# Numbers that are mechanical rather than clinical or statistical: emptiness /
# sign / index sentinels (0, 1, -1, 2 — "at least two", pairs) and time / metric
# unit factors (24 h, 60 min / s, 365 d, 1000, 3600 s). Anything else in a
# comparison is a threshold that belongs in a thresholds module or YAML.
TRIVIAL_NUMBERS = frozenset({0, 1, -1, 2, 24, 60, 365, 1000, 3600})


def _segment_names(node: ast.AST) -> str:
    return " ".join(
        n.id if isinstance(n, ast.Name) else n.attr for n in ast.walk(node) if isinstance(n, (ast.Name, ast.Attribute))
    )


def _language_literals(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str) and node.value in COUNTRY_LANGUAGE_LITERALS
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return any(_language_literals(e) for e in node.elts)
    return False


def _branch_nodes(source: str) -> Iterator[tuple[ast.AST, str]]:
    for node, qual in _walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            if name in COUNTRY_PREDICATES:
                yield node, qual
        elif isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            for op, left, right in zip(node.ops, operands, operands[1:]):
                pair: tuple[tuple[ast.AST, ast.AST], ...]
                if isinstance(op, (ast.Eq, ast.NotEq)):
                    pair = ((left, right), (right, left))
                elif isinstance(op, (ast.In, ast.NotIn)) and isinstance(right, (ast.Tuple, ast.List, ast.Set)):
                    pair = ((right, left),)  # "en" in entry is key presence, not a branch
                else:
                    continue
                if any(
                    _language_literals(lit) and not any(w in _segment_names(other) for w in NOT_A_COUNTRY)
                    for lit, other in pair
                ):
                    yield node, qual
                    break


def country_branches(source: str) -> list[int]:
    """Line numbers of country / language branches in ``source``."""
    return sorted(node.lineno for node, _ in _branch_nodes(source))  # type: ignore[attr-defined]


def _number(node: ast.AST) -> float | None:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _number(node.operand)
        return -inner if inner is not None else None
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    return None


def _literal_nodes(source: str) -> Iterator[tuple[ast.AST, str]]:
    """One ``(comparison, qualified name)`` per non-trivial literal operand."""
    for node, qual in _walk(ast.parse(source)):
        if not isinstance(node, ast.Compare):
            continue
        for operand in (node.left, *node.comparators):
            value = _number(operand)
            if value is not None and value not in TRIVIAL_NUMBERS:
                yield node, qual


def numeric_literals(source: str) -> list[int]:
    """Line numbers of non-trivial numeric literals in comparisons, one per literal."""
    return sorted(node.lineno for node, _ in _literal_nodes(source))  # type: ignore[attr-defined]


def counts_literals(rel_path: str) -> bool:
    """Whether the literal count applies to ``rel_path`` (relative to ``clinosim/``)."""
    name = rel_path.rsplit("/", 1)[-1]
    return not (name.startswith("_") and (name.endswith("_thresholds.py") or name.endswith("_defaults.py")))


def counts_branches(rel_path: str) -> bool:
    """Whether the branch count applies to ``rel_path`` (relative to ``clinosim/``)."""
    return not any(rel_path == p or (p.endswith("/") and rel_path.startswith(p)) for p in COUNTRY_PACKAGES)


def _key(kind: str, qual: str, node: ast.AST) -> str:
    return content_key(kind, qual, ast.unparse(node))


def scan(root: Path) -> Scan:
    """Per rule, the count of each content key under ``root`` (same counting rules as always)."""
    out: Scan = {k: Counter() for k in KINDS}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        source = path.read_text(encoding="utf-8")
        if counts_branches(rel):
            out["country_branches"].update(_key("country_branches", q, n) for n, q in _branch_nodes(source))
        if counts_literals(rel):
            out["numeric_literals"].update(_key("numeric_literals", q, n) for n, q in _literal_nodes(source))
    return out


@cache
def current_scan() -> Scan:
    return scan(ROOT)


RATCHET = Ratchet(kinds=KINDS, baseline=BASELINE, regenerate=REGENERATE)
totals = RATCHET.totals
baseline_from = RATCHET.baseline_from
load_baseline = RATCHET.load_baseline
compare = RATCHET.compare
lowered_baseline = RATCHET.lowered_baseline


def main(argv: list[str] | None = None) -> int:
    return RATCHET.main(argv, current_scan, __doc__.splitlines()[0])


if __name__ == "__main__":
    raise SystemExit(main())
