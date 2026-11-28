"""Rename-aware, conflict-free baseline shared by the AST ratchets under ``tests/unit/``.

Used by ``tests/unit/code_data_separation.py`` and ``tests/unit/module_boundaries.py``.
A ratchet counts findings per rule; each finding has a content key
``<rule>::<qualified name>::<normalized text>``, where the qualified name is the
enclosing class / function chain without the module path (``<module>`` at
module level), so a ``git mv`` keeps every key. The committed baseline JSON
stores the total per rule (the only thing compared) and an informational list of
the content keys with their counts:

* a rule fails only when its total exceeds the stored total;
* a decrease passes without editing the baseline;
* content keys that are new (or counted more often) are reported, so a net-zero
  swap is visible to the reviewer;
* ``python -m tests.unit.<ratchet> --write`` lowers the stored totals and refuses
  to raise one.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

Scan = dict[str, Counter[str]]


def walk_qualified(tree: ast.AST, qual: tuple[str, ...] = ()) -> Iterator[tuple[ast.AST, str]]:
    """Every node of ``tree`` with the qualified name of its enclosing class / function chain."""
    for child in ast.iter_child_nodes(tree):
        yield child, ".".join(qual) or "<module>"
        inner = (
            (*qual, child.name) if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) else qual
        )
        yield from walk_qualified(child, inner)


def content_key(kind: str, qual: str, text: str) -> str:
    return f"{kind}::{qual}::{text}"


@dataclass
class Verdict:
    raised: dict[str, tuple[int, int]] = field(default_factory=dict)  # rule -> (found, stored)
    lowered: dict[str, tuple[int, int]] = field(default_factory=dict)
    new_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Ratchet:
    """The baseline of one ratchet: its rule ids, its JSON file and its lowering command."""

    kinds: tuple[str, ...]
    baseline: Path
    regenerate: str

    def totals(self, found: Scan) -> dict[str, int]:
        return {k: sum(found.get(k, Counter()).values()) for k in self.kinds}

    def baseline_from(self, found: Scan) -> dict:
        """The baseline document for ``found``: totals per rule plus the informational entries."""
        return {
            "totals": self.totals(found),
            "entries": {k: dict(sorted(found.get(k, Counter()).items())) for k in self.kinds},
        }

    def load_baseline(self) -> dict:
        data = json.loads(self.baseline.read_text(encoding="utf-8"))
        return {
            "totals": {k: int(data["totals"].get(k, 0)) for k in self.kinds},
            "entries": {k: dict(data.get("entries", {}).get(k, {})) for k in self.kinds},
        }

    def compare(self, baseline: dict, found: Scan) -> Verdict:
        """Totals above the stored total are ``raised`` (the failure); below, ``lowered``.
        ``new_keys`` are content keys absent from the stored entries or with a higher
        count, reported so a net-zero swap is visible."""
        verdict = Verdict()
        now = self.totals(found)
        for kind in self.kinds:
            stored = baseline["totals"][kind]
            if now[kind] > stored:
                verdict.raised[kind] = (now[kind], stored)
            elif now[kind] < stored:
                verdict.lowered[kind] = (now[kind], stored)
            known = baseline["entries"].get(kind, {})
            verdict.new_keys += sorted(k for k, n in found.get(kind, Counter()).items() if n > known.get(k, 0))
        return verdict

    def lowered_baseline(self, baseline: dict, found: Scan) -> dict:
        """The new baseline for ``found``, provided no rule's total rose. Raises
        ``ValueError`` naming the rules that would raise the baseline."""
        raised = self.compare(baseline, found).raised
        if raised:
            raise ValueError(f"refusing to raise the baseline (found, stored): {raised}")
        return self.baseline_from(found)

    def main(
        self,
        argv: list[str] | None,
        current_scan: Callable[[], Scan],
        description: str,
        report: Callable[[int], str] | None = None,
    ) -> int:
        """Print the current totals, or with ``--write`` lower the committed totals to them.
        With ``report``, ``--clusters N`` also prints ``report(N)`` after the totals."""
        parser = argparse.ArgumentParser(description=description)
        parser.add_argument("--write", action="store_true", help="lower the committed totals to the current counts")
        if report is not None:
            parser.add_argument("--clusters", type=int, metavar="N", help="also print the N largest clusters per rule")
        args = parser.parse_args(argv)
        found = current_scan()
        if not args.write:
            print(json.dumps(self.totals(found)))
            if report is not None and args.clusters:
                print(report(args.clusters))
            return 0
        try:
            new = self.lowered_baseline(self.load_baseline(), found)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        self.baseline.write_text(json.dumps(new, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {self.baseline}: " + json.dumps(new["totals"]))
        return 0
