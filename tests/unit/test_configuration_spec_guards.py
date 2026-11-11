"""Guards of docs/design-guides/configuration-and-reference-data-spec.md (Issue #2732)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_PKG = Path(__file__).resolve().parents[2] / "clinosim"


_YAML_NAME = re.compile(r"(?:^|/)([\w.-]+\.ya?ml)$")

# Module reference YAMLs that no Pydantic model validates yet. The list only
# shrinks: an entry that gains a model must be removed (see the stale check).
# Empty since Issue #2896 (every module reference YAML has a model), and it
# stays empty (test_not_yet_modeled_stays_empty).
_NOT_YET_MODELED: dict[str, str] = {}

# Modules whose loader discovers its reference YAML by pattern (``*.yaml``
# glob or ``f"{id}.yaml"``) and validates each file; every YAML in those
# directories is covered. Pinned so a new pattern loader is reviewed.
# healthcare_system: loads clinosim/config/<stem>.yaml, the stem named by the
# country profile (Issue #3192), validated by HealthcareSystemConfig.
_PATTERN_LOADED_MODULES = {"disease", "encounter", "healthcare_system"}


# Simulator reference YAMLs (``simulator/reference_data``) are held to the
# same rule as module ones, keyed ``simulator/reference_data/<file>``
# (Issue #2956).
_SIMULATOR = "simulator"


def _reference_yamls() -> dict[str, Path]:
    modules = {
        str(p.relative_to(_PKG / "modules")): p for p in sorted((_PKG / "modules").glob("*/reference_data/*.yaml"))
    }
    simulator = {str(p.relative_to(_PKG)): p for p in sorted((_PKG / _SIMULATOR / "reference_data").glob("*.yaml"))}
    return {**modules, **simulator}


def _pydantic_model_names(trees: dict[Path, ast.Module]) -> set[str]:
    """Names of the classes in clinosim that derive (transitively) from BaseModel."""
    bases: dict[str, set[str]] = {}
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases.setdefault(node.name, set()).update(
                    b.id if isinstance(b, ast.Name) else b.attr if isinstance(b, ast.Attribute) else ""
                    for b in (x.value if isinstance(x, ast.Subscript) else x for x in node.bases)
                )
    models = {"BaseModel", "RootModel"}
    while True:
        more = {name for name, bs in bases.items() if name not in models and bs & models}
        if not more:
            return models
        models |= more


_Ref = tuple[str | None, str]  # (owning module named next to the file, or None; file name)


def _yaml_refs(node: ast.AST, names: dict[str, set[_Ref]], module_names: set[str]) -> tuple[set[_Ref], bool]:
    """YAML files ``node`` refers to, by string literal or through a
    module-level constant holding one, and whether it names files by pattern.

    A file is owned by a module named in the same expression (a cross-module
    path such as ``.../"observation"/"reference_data"/"lab_panels.yaml"``);
    otherwise its owner is left to the caller (the file's own module)."""
    files: set[str] = set()
    refs: set[_Ref] = set()
    owners: set[str] = set()
    pattern = False
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            if sub.value == "*.yaml":
                pattern = True
            elif sub.value in module_names:
                owners.add(sub.value)
            elif m := _YAML_NAME.search(sub.value):
                files.add(m.group(1))
        elif isinstance(sub, ast.JoinedStr) and sub.values:
            last = sub.values[-1]
            if isinstance(last, ast.Constant) and str(last.value) == ".yaml":
                pattern = True
        elif isinstance(sub, ast.Name) and sub.id in names:
            refs |= names[sub.id]
    refs |= {(o, f) for o in (owners or {None}) for f in files}
    return refs, pattern


def _validates(node: ast.AST, models: set[str]) -> bool:
    """``node`` calls ``load_validated_yaml``, ``<Model>.model_validate`` or ``<Model>(**data)``."""
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if isinstance(func, ast.Name) and func.id == "load_validated_yaml":
            return True
        if isinstance(func, ast.Attribute) and func.attr in ("model_validate", "load_validated_yaml"):
            return True
        if isinstance(func, ast.Name) and func.id in models and any(k.arg is None for k in sub.keywords):
            return True
    return False


def _validated_reference_yamls() -> tuple[set[tuple[str, str]], set[str]]:
    """``(module, file name)`` pairs some code unit both names and validates,
    and the modules whose reference YAML is validated by pattern.

    A code unit is one function (with what it nests) or the module-level
    statements of a file. A file belongs to the module named next to it (see
    ``_yaml_refs``), else to the module the unit lives in.
    """
    trees = {p: ast.parse(p.read_text(encoding="utf-8")) for p in sorted(_PKG.rglob("*.py"))}
    models = _pydantic_model_names(trees)
    module_names = {p.name for p in (_PKG / "modules").iterdir() if p.is_dir()} | {_SIMULATOR}
    covered: set[tuple[str, str]] = set()
    pattern_modules: set[str] = set()
    for path, tree in trees.items():
        rel = path.relative_to(_PKG).parts
        home = rel[1] if rel[0] == "modules" and len(rel) > 2 else _SIMULATOR if rel[0] == _SIMULATOR else None
        # Module-level constants naming a YAML file, resolved in order.
        names: dict[str, set[_Ref]] = {}
        for stmt in tree.body:
            targets = (
                stmt.targets
                if isinstance(stmt, ast.Assign)
                else [stmt.target]
                if isinstance(stmt, ast.AnnAssign)
                else []
            )
            value = getattr(stmt, "value", None)
            if value is None:
                continue
            refs, _ = _yaml_refs(value, names, module_names)
            for t in targets:
                if isinstance(t, ast.Name) and refs:
                    names[t.id] = refs
        top = ast.Module(
            body=[s for s in tree.body if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))],
            type_ignores=[],
        )
        units = [top] + [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for unit in units:
            if not _validates(unit, models):
                continue
            refs, pattern = _yaml_refs(unit, names, module_names)
            covered |= {(owner or home, f) for owner, f in refs if owner or home}
            if pattern and home:
                pattern_modules.add(home)
    return covered, pattern_modules


def test_module_reference_yaml_has_a_model() -> None:
    """Spec §2: every module reference YAML FILE is validated by a Pydantic
    model at load (``load_validated_yaml``, ``Model.model_validate`` or
    ``Model(**data)`` in the code unit that names the file)."""
    covered, pattern_modules = _validated_reference_yamls()
    assert pattern_modules == _PATTERN_LOADED_MODULES, (
        f"pattern-loaded modules changed: {sorted(pattern_modules)}; review and update _PATTERN_LOADED_MODULES"
    )
    unvalidated = sorted(
        rel
        for rel, path in _reference_yamls().items()
        if path.parent.parent.name not in pattern_modules and (path.parent.parent.name, path.name) not in covered
    )
    missing = sorted(set(unvalidated) - set(_NOT_YET_MODELED))
    assert not missing, f"module reference YAML loaded without a Pydantic model: {missing}"
    stale = sorted(set(_NOT_YET_MODELED) - set(unvalidated))
    assert not stale, f"now validated (or removed); drop from _NOT_YET_MODELED: {stale}"


def test_not_yet_modeled_stays_empty() -> None:
    """Shrink-only ratchet at zero: a new reference YAML gets a model, not an
    allow-list entry (Issue #2896)."""
    assert not _NOT_YET_MODELED


@pytest.mark.parametrize(
    "rel",
    [
        "order/reference_data/medication_supersede.yaml",
        "observation/reference_data/lab_aliases.yaml",
        "observation/reference_data/lab_constants.yaml",
        "observation/reference_data/nursing_scores.yaml",
    ],
)
def test_guard_sees_the_issue_2844_files(rel: str) -> None:
    """The four files modeled in issue #2844 are recognised as validated."""
    covered, _ = _validated_reference_yamls()
    module, _, name = rel.split("/")
    assert (module, name) in covered


# Module models that may still accept unknown keys (spec §2). Shrink-only:
# a fixed entry must be removed, and no entry may be added (Issue #2845).
_EXTRA_FORBID_RATCHET: dict[str, str] = {}


def _config_sets(cls: ast.ClassDef, key: str, value: object) -> bool:
    """``cls`` declares ``model_config = ConfigDict(..., key=value, ...)``."""
    for stmt in cls.body:
        if not (isinstance(stmt, ast.Assign) and any(getattr(t, "id", "") == "model_config" for t in stmt.targets)):
            continue
        call = stmt.value
        return isinstance(call, ast.Call) and any(
            kw.arg == key and isinstance(kw.value, ast.Constant) and kw.value.value == value for kw in call.keywords
        )
    return False


def _forbids_extra(cls: ast.ClassDef) -> bool:
    return _config_sets(cls, "extra", "forbid")


def _base_models(root: Path) -> list[tuple[str, ast.ClassDef]]:
    """``(path::Class, node)`` of the direct ``BaseModel`` subclasses under ``root``."""
    return [
        (f"{path.relative_to(root).as_posix()}::{node.name}", node)
        for path in sorted(root.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ClassDef) and any(getattr(b, "id", "") == "BaseModel" for b in node.bases)
    ]


def _module_models_accepting_unknown_keys() -> set[str]:
    return {name for name, node in _base_models(_PKG / "modules") if not _forbids_extra(node)}


def test_module_models_forbid_unknown_keys() -> None:
    """Spec §2: a module model rejects unknown keys (``ConfigDict(extra="forbid")``),
    so a misspelled YAML key fails at load instead of being silently ignored."""
    found = _module_models_accepting_unknown_keys()
    new = sorted(found - set(_EXTRA_FORBID_RATCHET))
    fixed = sorted(set(_EXTRA_FORBID_RATCHET) - found)
    assert not new, f"module models accepting unknown keys (declare the fields, then forbid): {new}"
    assert not fixed, f"now forbid unknown keys — remove from _EXTRA_FORBID_RATCHET: {fixed}"


def test_simulator_models_forbid_unknown_keys_and_are_frozen() -> None:
    """The simulator reference-YAML models reject unknown keys and are
    read-only, nested models included (Issue #2956)."""
    models = _base_models(_PKG / _SIMULATOR)
    assert models, "no simulator models found"
    offenders = [name for name, node in models if not (_forbids_extra(node) and _config_sets(node, "frozen", True))]
    assert not offenders, f'simulator models without ConfigDict(extra="forbid", frozen=True): {offenders}'


@pytest.mark.parametrize(
    "name",
    [
        "chronic_propagation.yaml",
        "diagnosis_rules.yaml",
        "icd10_sex_restrictions.yaml",
        "renal_medication_rules.yaml",
        "statin_monitoring.yaml",
    ],
)
def test_guard_sees_the_simulator_reference_yamls(name: str) -> None:
    """Every simulator reference YAML is discovered and validated (Issue #2956)."""
    assert f"{_SIMULATOR}/reference_data/{name}" in _reference_yamls()
    covered, _ = _validated_reference_yamls()
    assert (_SIMULATOR, name) in covered


def test_no_extra_allow_models() -> None:
    """No Pydantic model in the package opts into ``extra="allow"``; an open map
    is a typed ``dict[str, X]`` field instead (Issue #2845)."""
    pattern = re.compile(r"""extra\s*=\s*["']allow["']""")
    offenders = [
        f"{p.relative_to(_PKG)}:{i}"
        for p in sorted(_PKG.rglob("*.py"))
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert not offenders, offenders


def test_no_ad_hoc_age_band_parsing() -> None:
    """Age-band keys are parsed only by clinosim/age_bands.py."""
    pattern = re.compile(r'key\.partition\("-"\)|band\w*\.endswith\("\+"\)|band\w*\.split\("-"\)')
    offenders = [
        f"{p.relative_to(_PKG)}:{i}"
        for p in sorted(_PKG.rglob("*.py"))
        if p.name != "age_bands.py"
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert not offenders, offenders
