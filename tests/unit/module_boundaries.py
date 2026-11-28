"""Counter and baseline for the module-boundary ratchet (Issue #3978).

Used by ``tests/unit/test_module_boundaries.py``. Reads every Python file under
``clinosim/`` with the AST and counts, per rule:

* ``foundation_imports`` — an import in a foundation package (:data:`FOUNDATION`)
  of ``clinosim.modules`` (other than ``modules/_shared``), ``clinosim.simulator``,
  ``clinosim.eval`` or ``clinosim.audit``;
* ``module_to_simulator`` — an import of ``clinosim.simulator`` in
  ``clinosim/modules/<m>/`` for every ``m`` other than ``output``;
* ``private_cross_package`` — an import of a ``_``-prefixed module or name of
  another package (:func:`package_of`), except ``_<topic>_thresholds`` /
  ``_<topic>_defaults`` constant modules, ``_bb_*`` bundle builders imported by
  ``modules/output/fhir_r4/builder.py`` or an ``audit.py``, and ``modules/_shared``;
* ``output_to_simulator`` — an import of ``clinosim.simulator`` in
  ``clinosim/modules/output/``;
* ``qa_to_simulator`` — an import of ``clinosim.simulator`` in ``clinosim/eval/``
  or ``clinosim/audit/``;
* ``foreign_reference_data`` — a path built (with ``/``, ``joinpath`` or
  ``os.path.join``) into the ``reference_data`` directory of another package, or
  into one whose owner cannot be resolved from the file alone.

Every import statement counts, at any depth (function-local and
``TYPE_CHECKING`` imports included), one finding per imported name; relative
imports are resolved to absolute names. ``importlib`` calls are not imports.

The committed baseline is ``module_boundaries_baseline.json`` in the
rename-aware format of ``tests/unit/ratchet_baseline.py``: the total per rule
(the only thing compared) and content-keyed informational entries
(``<rule>::<qualified name>::<normalized text>``; the text of an import is
``from <absolute module> import <name>`` or ``import <module>``, aliases
dropped). The test fails only when a rule's total exceeds the stored total; a
decrease passes without editing the baseline, and a ``git mv`` is not a raise.
Print the current totals (with ``--clusters N``, also the ``N`` largest
``<importing package> -> <target>`` clusters per rule), or lower the stored
totals (never inside a feature change), with::

    python -m tests.unit.module_boundaries --clusters 10
    python -m tests.unit.module_boundaries --write
"""

from __future__ import annotations

import ast
import os
import re
from collections import Counter
from collections.abc import Iterator
from functools import cache
from pathlib import Path

import clinosim
from tests.unit.ratchet_baseline import Ratchet, Scan, content_key, walk_qualified

ROOT = Path(clinosim.__file__).parent
BASELINE = Path(__file__).with_name("module_boundaries_baseline.json")
REGENERATE = "python -m tests.unit.module_boundaries --write"

KINDS = (
    "foundation_imports",
    "module_to_simulator",
    "private_cross_package",
    "output_to_simulator",
    "qa_to_simulator",
    "foreign_reference_data",
)
RULES = {
    "foundation_imports": "Foundation packages do not import modules, simulator, output, eval or audit",
    "module_to_simulator": "A domain module (clinosim/modules/<m>, not output) does not import clinosim.simulator",
    "private_cross_package": "No package imports a _-prefixed module or name of another package",
    "output_to_simulator": "clinosim/modules/output does not import clinosim.simulator",
    "qa_to_simulator": "clinosim/eval and clinosim/audit do not import clinosim.simulator",
    "foreign_reference_data": "No package builds a path into another module's reference_data directory",
}

# Foundation (L0) files and packages, relative to ``clinosim/``; a trailing ``/`` is a package.
FOUNDATION = (
    "datafiles.py",
    "determinism.py",
    "seeding.py",
    "age_bands.py",
    "timeutil.py",
    "reference_data.py",
    "countries/__init__.py",
    "country_profile.py",
    "codes/",
    "locale/",
    "types/",
    "modules/_shared.py",
)
# Top-level packages a foundation file may not import (``modules`` minus ``modules/_shared``).
FOUNDATION_FORBIDDEN = ("modules", "simulator", "eval", "audit")
QA_PACKAGES = ("eval", "audit")

# Rule-3 exceptions: formula-constant modules (documentation policy §5.1) ...
CONSTANT_MODULE = re.compile(r"_[A-Za-z0-9_]+_(thresholds|defaults)")
# ... ``_bb_*`` bundle builders, in these importers only ...
BUNDLE_BUILDER_PREFIX = "_bb_"
BUNDLE_BUILDER_IMPORTERS = ("modules/output/fhir_r4/builder.py",)
BUNDLE_BUILDER_IMPORTER_NAME = "audit.py"
# ... and the shared module helpers.
SHARED = ("modules", "_shared")

REFERENCE_DATA = "reference_data"


def is_foundation(rel: str) -> bool:
    """Whether ``rel`` (a path relative to ``clinosim/``) is a foundation file."""
    return any(rel == f or (f.endswith("/") and rel.startswith(f)) for f in FOUNDATION)


def package_of(parts: tuple[str, ...]) -> str:
    """The package that owns ``parts`` (a module path below ``clinosim``, without ``.py``).

    ``modules/<m>`` and ``countries/<cc>`` are packages of their own; any other
    top-level directory or file of ``clinosim/`` is one package."""
    if not parts:
        return ""
    if parts[0] in ("modules", "countries") and len(parts) > 1:
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


def _is_private(part: str) -> bool:
    return part.startswith("_") and not (part.startswith("__") and part.endswith("__"))


def _module_parts(rel: str) -> tuple[str, ...]:
    """Dotted parts below ``clinosim`` of the module file ``rel`` (``__init__`` dropped)."""
    parts = tuple(rel[: -len(".py")].split("/"))
    return parts[:-1] if parts[-1] == "__init__" else parts


def _is_module(root: Path, parts: tuple[str, ...]) -> bool:
    base = root.joinpath(*parts)
    return base.with_suffix(".py").is_file() or base.is_dir()


def _imports(tree: ast.AST, rel: str, root: Path) -> Iterator[tuple[str, tuple[str, ...], str | None, str]]:
    """``(qualified name, target parts below clinosim, imported name or None, text)`` per imported name.

    ``target`` is the module the name lives in, or the submodule when the name is
    one; only imports of ``clinosim`` are yielded."""
    own = _module_parts(rel)
    package = own if rel.endswith("__init__.py") else own[:-1]
    for node, qual in walk_qualified(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                dotted = alias.name.split(".")
                if dotted[0] == "clinosim":
                    yield qual, tuple(dotted[1:]), None, f"import {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.level - 1 > len(package):
                    continue
                base = package[: len(package) - (node.level - 1)]
                parts = (*base, *(node.module.split(".") if node.module else ()))
            else:
                dotted = (node.module or "").split(".")
                if dotted[0] != "clinosim":
                    continue
                parts = tuple(dotted[1:])
            module = ".".join(("clinosim", *parts))
            for alias in node.names:
                sub = (*parts, alias.name)
                target = sub if alias.name != "*" and _is_module(root, sub) else parts
                name = None if target == sub else alias.name
                yield qual, target, name, f"from {module} import {alias.name}"


def _imports_simulator(target: tuple[str, ...]) -> bool:
    return target[:1] == ("simulator",)


def _private_elements(target: tuple[str, ...], name: str | None) -> list[str]:
    """The ``_``-prefixed parts of an import below ``clinosim.<top>``, minus the written exceptions
    that do not depend on the importer (constant modules, ``modules/_shared``)."""
    parts = [*target[1:], *([name] if name is not None else [])]
    if target[:2] == SHARED:
        parts = parts[1:]
    return [p for p in parts if _is_private(p) and not CONSTANT_MODULE.fullmatch(p)]


def _counts_private(rel: str, target: tuple[str, ...], name: str | None) -> bool:
    if package_of(target) == package_of(_module_parts(rel)):
        return False
    builder_ok = rel in BUNDLE_BUILDER_IMPORTERS or rel.rsplit("/", 1)[-1] == BUNDLE_BUILDER_IMPORTER_NAME
    return any(not (builder_ok and p.startswith(BUNDLE_BUILDER_PREFIX)) for p in _private_elements(target, name))


Finding = tuple[str, str, str, str]  # (rule, qualified name, normalized text, target)


def _import_findings(tree: ast.AST, rel: str, root: Path) -> Iterator[Finding]:
    foundation = is_foundation(rel)
    top = rel.split("/", 1)[0] if "/" in rel else ""
    in_module = rel.startswith("modules/") and rel.count("/") >= 2
    in_output = rel.startswith("modules/output/")
    for qual, target, name, text in _imports(tree, rel, root):
        dotted = ".".join(("clinosim", *target))
        if foundation and target[:1] and target[0] in FOUNDATION_FORBIDDEN and target[:2] != SHARED:
            yield "foundation_imports", qual, text, dotted
        if _imports_simulator(target):
            if in_output:
                yield "output_to_simulator", qual, text, dotted
            elif in_module:
                yield "module_to_simulator", qual, text, dotted
            if top in QA_PACKAGES:
                yield "qa_to_simulator", qual, text, dotted
        if _counts_private(rel, target, name):
            yield "private_cross_package", qual, text, dotted


# --- rule 6: paths into reference_data -------------------------------------------------------


def _assignments(tree: ast.AST) -> dict[str, ast.expr | None]:
    """Simple ``name = expr`` bindings of the file; a name bound to different expressions maps to None."""
    out: dict[str, ast.expr | None] = {}
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        for t in targets:
            if not isinstance(t, ast.Name):
                continue
            if t.id not in out:
                out[t.id] = value
            elif (prev := out[t.id]) is None or ast.dump(prev) != ast.dump(value):
                out[t.id] = None
    return out


def _is_os_path(func: ast.expr, names: tuple[str, ...]) -> bool:
    """Whether ``func`` is ``os.path.<one of names>``."""
    return (
        isinstance(func, ast.Attribute)
        and func.attr in names
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "path"
    )


def _resolve(expr: ast.AST, file: Path, env: dict[str, ast.expr | None], depth: int = 0) -> Path | None:
    """The filesystem path ``expr`` evaluates to, when it is built from ``__file__`` alone."""
    if depth > 20:
        return None
    if isinstance(expr, ast.Name):
        if expr.id == "__file__":
            return file
        bound = env.get(expr.id)
        return _resolve(bound, file, env, depth + 1) if bound is not None else None
    if isinstance(expr, ast.Call):
        f = expr.func
        if isinstance(f, (ast.Name, ast.Attribute)) and (f.id if isinstance(f, ast.Name) else f.attr) in (
            "Path",
            "PurePath",
        ):
            return _resolve(expr.args[0], file, env, depth + 1) if len(expr.args) == 1 else None
        if isinstance(f, ast.Attribute) and f.attr in ("resolve", "absolute") and not expr.args:
            return _resolve(f.value, file, env, depth + 1)
        if _is_os_path(f, ("abspath", "realpath", "normpath")) and len(expr.args) == 1:
            return _resolve(expr.args[0], file, env, depth + 1)
        if _is_os_path(f, ("dirname",)) and len(expr.args) == 1:
            base = _resolve(expr.args[0], file, env, depth + 1)
            return base.parent if base is not None else None
        return None
    if isinstance(expr, ast.Attribute) and expr.attr == "parent":
        base = _resolve(expr.value, file, env, depth + 1)
        return base.parent if base is not None else None
    if (
        isinstance(expr, ast.Subscript)
        and isinstance(expr.value, ast.Attribute)
        and expr.value.attr == "parents"
        and isinstance(expr.slice, ast.Constant)
        and isinstance(expr.slice.value, int)
    ):
        base = _resolve(expr.value.value, file, env, depth + 1)
        if base is None or expr.slice.value >= len(base.parents):
            return None
        return base.parents[expr.slice.value]
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Div):
        base = _resolve(expr.left, file, env, depth + 1)
        right = expr.right
        if base is None or not (isinstance(right, ast.Constant) and isinstance(right.value, str)):
            return None
        return base / right.value
    return None


def _path_operands(node: ast.AST) -> list[ast.expr] | None:
    """The operands of a path join (``a / b / c``, ``a.joinpath(b, c)``, ``os.path.join(a, b)``)."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _path_operands(node.left) or [node.left]
        return [*left, node.right]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        f = node.func
        if f.attr == "joinpath":
            return [f.value, *node.args]
        if _is_os_path(f, ("join",)):
            return list(node.args)
    return None


def _owner_of_reference_data(operands: list[ast.expr], file: Path, root: Path, tree: ast.AST) -> str | None:
    """The package whose ``reference_data`` the join points into; ``""`` when it cannot be resolved,
    ``None`` when the join does not name ``reference_data``."""
    for i, op in enumerate(operands):
        if not (isinstance(op, ast.Constant) and isinstance(op.value, str)):
            continue
        segments = op.value.split("/")
        if REFERENCE_DATA not in segments:
            continue
        head = segments[: segments.index(REFERENCE_DATA)]
        base = _resolve(operands[0], file, _assignments(tree)) if i > 0 else None
        for mid in operands[1:i]:
            if base is None or not (isinstance(mid, ast.Constant) and isinstance(mid.value, str)):
                base = None
                break
            base = base / mid.value
        if base is None:
            return ""
        directory = Path(os.path.normpath(Path(*(base.parts + tuple(head)))))
        try:
            rel = directory.relative_to(root)
        except ValueError:
            return ""
        return package_of(rel.parts) if rel.parts else ""
    return None


def _reference_data_findings(tree: ast.AST, rel: str, root: Path) -> Iterator[Finding]:
    file = root / rel
    own = package_of(_module_parts(rel))
    inner: set[int] = set()
    for node, qual in walk_qualified(tree):
        if id(node) in inner:
            continue
        operands = _path_operands(node)
        if operands is None:
            continue
        for sub in ast.walk(node):
            if sub is not node and isinstance(sub, ast.BinOp):
                inner.add(id(sub))
        owner = _owner_of_reference_data(operands, file, root, tree)
        if owner is not None and owner != own:
            yield "foreign_reference_data", qual, ast.unparse(node), f"{owner or '<unresolved>'}/{REFERENCE_DATA}"


def findings(source: str, rel: str, root: Path) -> Iterator[Finding]:
    """``(rule, qualified name, normalized text, target)`` of every finding in ``source`` at ``rel``;
    the target is the imported module, or the package whose ``reference_data`` is read."""
    tree = ast.parse(source)
    yield from _import_findings(tree, rel, root)
    yield from _reference_data_findings(tree, rel, root)


def scan(root: Path) -> Scan:
    """Per rule, the count of each content key under ``root`` (a ``clinosim`` package directory)."""
    out: Scan = {k: Counter() for k in KINDS}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        for kind, qual, text, _ in findings(path.read_text(encoding="utf-8"), rel, root):
            out[kind][content_key(kind, qual, text)] += 1
    return out


def clusters(root: Path) -> Scan:
    """Per rule, the count of findings per ``<importing package> -> <target>`` edge (a report, not baselined)."""
    out: Scan = {k: Counter() for k in KINDS}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        for kind, _, _, target in findings(path.read_text(encoding="utf-8"), rel, root):
            out[kind][f"{package_of(_module_parts(rel))} -> {target}"] += 1
    return out


def cluster_report(top: int) -> str:
    """The ``top`` largest clusters per rule of the current tree, as text."""
    lines = []
    for kind, counter in clusters(ROOT).items():
        lines.append(f"{kind}: {sum(counter.values())} in {len(counter)} clusters")
        lines += [f"  {n:4d}  {edge}" for edge, n in sorted(counter.items(), key=lambda e: (-e[1], e[0]))[:top]]
    return "\n".join(lines)


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
    return RATCHET.main(argv, current_scan, __doc__.splitlines()[0], report=cluster_report)


if __name__ == "__main__":
    raise SystemExit(main())
