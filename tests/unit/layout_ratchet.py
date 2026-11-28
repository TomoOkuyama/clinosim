"""Counter and baseline for the test-layout ratchet (Issue #3990).

Used by ``tests/unit/docs/test_test_layout_guard.py``. ``tests/README.md`` says
the path under ``tests/`` mirrors the path under ``clinosim/``, that no new file
goes to the top level of ``tests/unit/``, and that tests use the
``patient_factory`` fixture instead of a local ``_patient()`` builder. Counted,
with the AST for the builders (not a text search):

* ``flat_test_files`` - ``tests/unit/test_*.py`` files (key: the file name);
* ``local_patient_builders`` / ``local_stay_builders`` / ``local_record_builders``
  - functions named ``_patient`` / ``_stay`` / ``_record`` defined at module
  level or in a class anywhere under ``tests/`` (key: the qualified class chain
  and the normalized signature; a closure inside a test function is not counted).

The committed baseline is ``layout_ratchet_baseline.json`` in the shared format
of ``tests/unit/ratchet_baseline.py``: the total per rule (the only thing the
test compares) and the informational content keys. A key holds no directory, so
moving a file to its mirrored directory keeps it (the flat-file total drops, the
builder keys stay). A total may not rise; a decrease passes without editing the
baseline. Lower the stored totals (never inside a feature change) with::

    python -m tests.unit.layout_ratchet --write
"""

from __future__ import annotations

import ast
from collections import Counter
from functools import cache
from pathlib import Path

from tests.unit.ratchet_baseline import Ratchet, Scan, Verdict, content_key

TESTS = Path(__file__).resolve().parents[1]
BASELINE = Path(__file__).with_name("layout_ratchet_baseline.json")
REGENERATE = "python -m tests.unit.layout_ratchet --write"

KINDS = ("flat_test_files", "local_patient_builders", "local_stay_builders", "local_record_builders")
BUILDER_KINDS = {
    "_patient": "local_patient_builders",
    "_stay": "local_stay_builders",
    "_record": "local_record_builders",
}
RULES = {
    "flat_test_files": "New tests go under the directory that mirrors the module under clinosim/",
    "local_patient_builders": "Patients are built with the shared patient_factory fixture, not a local _patient()",
    "local_stay_builders": "Stays are built with a shared fixture or helper, not a new local _stay()",
    "local_record_builders": "Records are built with a shared fixture or helper, not a new local _record()",
}
ADVICE = {
    "flat_test_files": (
        "Put the file in the directory that mirrors the module it covers: tests/unit/<path under clinosim/>/ "
        "(for example tests/unit/modules/<module>/ for clinosim/modules/<module>/), or tests/integration/ for a "
        "multi-module chain. Run the tests of one module with the recipe in tests/README.md."
    ),
    "local_patient_builders": (
        "Use the patient_factory fixture (tests/conftest.py) instead of defining _patient() again."
    ),
    "local_stay_builders": (
        "Reuse an existing builder or add one shared fixture to tests/conftest.py instead of another local _stay()."
    ),
    "local_record_builders": (
        "Reuse an existing builder or add one shared fixture to tests/conftest.py instead of another local _record()."
    ),
}


def _builders(tree: ast.AST, qual: tuple[str, ...] = ()) -> list[tuple[str, ast.FunctionDef]]:
    """Builders defined at module level or inside classes (not inside a function body)."""
    found: list[tuple[str, ast.FunctionDef]] = []
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.ClassDef):
            found += _builders(node, (*qual, node.name))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in BUILDER_KINDS:
            found.append((".".join(qual) or "<module>", node))  # type: ignore[arg-type]
    return found


def scan(root: Path) -> Scan:
    """Per rule, the count of each content key under ``root`` (the ``tests/`` directory)."""
    out: Scan = {k: Counter() for k in KINDS}
    for path in sorted((root / "unit").glob("test_*.py")):
        out["flat_test_files"][content_key("flat_test_files", "<module>", path.name)] += 1
    for path in sorted(root.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if not any(f"def {name}(" in source for name in BUILDER_KINDS):
            continue  # cheap pre-filter: parse only the files that can hold a builder
        for qual, node in _builders(ast.parse(source)):
            kind = BUILDER_KINDS[node.name]
            signature = f"def {node.name}({ast.unparse(node.args)})"
            out[kind][content_key(kind, qual, signature)] += 1
    return out


@cache
def current_scan() -> Scan:
    return scan(TESTS)


RATCHET = Ratchet(kinds=KINDS, baseline=BASELINE, regenerate=REGENERATE)
totals = RATCHET.totals
baseline_from = RATCHET.baseline_from
load_baseline = RATCHET.load_baseline
compare = RATCHET.compare
lowered_baseline = RATCHET.lowered_baseline


def failure_message(kind: str, verdict: Verdict) -> str:
    found, stored = verdict.raised.get(kind, (0, 0))
    new = [k for k in verdict.new_keys if k.startswith(kind + "::")]
    return (
        f"{RULES[kind]} - total {kind.replace('_', ' ')} rose (found {found}, stored {stored}). "
        f"New: {new}. {ADVICE[kind]} A move is not a raise; removing a file or builder needs no baseline edit "
        f"(lower the stored totals with: {REGENERATE})."
    )


def main(argv: list[str] | None = None) -> int:
    return RATCHET.main(argv, current_scan, __doc__.splitlines()[0])


if __name__ == "__main__":
    raise SystemExit(main())
