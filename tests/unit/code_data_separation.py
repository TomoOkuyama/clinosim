"""Counter and baseline for the code-data separation ratchet (Issue #3137).

Used by ``tests/unit/test_code_data_separation_3137.py``. Counts, per Python
file under ``clinosim/``, with the AST (not a text search):

* ``country_branches`` — calls to :data:`COUNTRY_PREDICATES` and comparisons
  (``==`` / ``!=`` / ``in`` / ``not in``) with a :data:`COUNTRY_LANGUAGE_LITERALS`
  value;
* ``numeric_literals`` — numeric literals in comparisons, outside
  ``_<topic>_thresholds.py`` / ``_<topic>_defaults.py`` modules and other than
  :data:`TRIVIAL_NUMBERS`.

The committed baseline is ``code_data_separation_baseline.json``. Lower it
after removing branches or literals with::

    python -m tests.unit.code_data_separation --write

The command refuses to raise any count: a new branch or literal is moved to
data (YAML, a country profile, a thresholds module), not added to the baseline.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from functools import cache
from pathlib import Path

import clinosim

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
# (``clinosim/countries.py``) and country packages (``clinosim/countries/<cc>/``).
COUNTRY_PACKAGES = ("countries.py", "countries/")

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


def country_branches(source: str) -> list[int]:
    """Line numbers of country / language branches in ``source``."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            if name in COUNTRY_PREDICATES:
                lines.append(node.lineno)
        elif isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            for op, left, right in zip(node.ops, operands, operands[1:]):
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
                    lines.append(node.lineno)
                    break
    return sorted(lines)


def _number(node: ast.AST) -> float | None:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _number(node.operand)
        return -inner if inner is not None else None
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    return None


def numeric_literals(source: str) -> list[int]:
    """Line numbers of non-trivial numeric literals in comparisons, one per literal."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Compare):
            continue
        for operand in (node.left, *node.comparators):
            value = _number(operand)
            if value is not None and value not in TRIVIAL_NUMBERS:
                lines.append(node.lineno)
    return sorted(lines)


def counts_literals(rel_path: str) -> bool:
    """Whether the literal count applies to ``rel_path`` (relative to ``clinosim/``)."""
    name = rel_path.rsplit("/", 1)[-1]
    return not (name.startswith("_") and (name.endswith("_thresholds.py") or name.endswith("_defaults.py")))


def counts_branches(rel_path: str) -> bool:
    """Whether the branch count applies to ``rel_path`` (relative to ``clinosim/``)."""
    return not any(rel_path == p or (p.endswith("/") and rel_path.startswith(p)) for p in COUNTRY_PACKAGES)


@cache
def current_counts() -> dict[str, dict[str, int]]:
    """Per-file counts of each kind, files with a zero count omitted."""
    out: dict[str, dict[str, int]] = {k: {} for k in KINDS}
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        if counts_branches(rel) and (n := len(country_branches(source))):
            out["country_branches"][rel] = n
        if counts_literals(rel) and (n := len(numeric_literals(source))):
            out["numeric_literals"][rel] = n
    return out


def load_baseline() -> dict[str, dict[str, int]]:
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    return {k: dict(data.get(k, {})) for k in KINDS}


def merge_lowered(baseline: dict[str, dict[str, int]], found: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    """The new baseline: ``found``, provided no file's count grew. Raises
    ``ValueError`` naming the files that would raise the baseline."""
    raised = {
        f"{kind}:{f}": (n, baseline.get(kind, {}).get(f, 0))
        for kind in KINDS
        for f, n in found.get(kind, {}).items()
        if n > baseline.get(kind, {}).get(f, 0)
    }
    if raised:
        raise ValueError(f"refusing to raise the baseline (found, baseline): {raised}")
    return {k: dict(sorted(found.get(k, {}).items())) for k in KINDS}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="lower the committed baseline to the current counts")
    args = parser.parse_args(argv)
    found = current_counts()
    if not args.write:
        print(json.dumps({k: sum(v.values()) for k, v in found.items()}))
        return 0
    try:
        new = merge_lowered(load_baseline(), found)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    BASELINE.write_text(json.dumps(new, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {BASELINE}: " + json.dumps({k: sum(v.values()) for k, v in new.items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
