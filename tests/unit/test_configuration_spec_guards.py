"""Guards of docs/design-guides/configuration-and-reference-data-spec.md (Issue #2732)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_PKG = Path(__file__).resolve().parents[2] / "clinosim"


_YAML_NAME = re.compile(r"(?:^|/)([\w.-]+\.ya?ml)$")

# Module reference YAMLs that no Pydantic model validates yet. Each is still
# read as a plain dict (some with a hand-written check); the list only
# shrinks: an entry that gains a model must be removed (see the stale check).
_NOT_YET_MODELED: dict[str, str] = {
    "document/reference_data/document_type_specs.yaml": "hand-written check (registry._validate_document_type_specs)",
    "document/reference_data/hpi_pertinent_negatives.yaml": "plain dict (reference_data_loaders.py)",
    "hai/reference_data/hai_antibiogram.yaml": "hand-written check (hai.load_hai_antibiogram)",
    "document/reference_data/cc-pe-consistency-keywords.yaml": "plain dict (narrative/_narrative_utils.py)",
    "document/reference_data/chronic-med-class-hints.yaml": "plain dict (narrative section builder outpatient_soap.py)",
    "document/reference_data/chronic_soap_templates.yaml": "plain dict (narrative/_chronic_soap.py)",
    "document/reference_data/hedging_phrases.yaml": "plain dict (narrative/_hedging.py)",
    "document/reference_data/ja_only_fallback_sections.yaml": "plain dict (document/audit.py)",
    "document/reference_data/narrative_extras_whitelists.yaml": "plain dict (narrative/_extra_context_builder.py)",
    "document/reference_data/section_catalog.yaml": "hand-written check (registry._validate_section_catalog)",
    "hai/reference_data/hai_lab_lift.yaml": "hand-written check (lab_lift._validate_hai_lab_lift_config)",
    "imaging/reference_data/imaging-impression-keywords.yaml": "plain dict (output/fhir_r4/labs/diagnostic_report.py)",
}

# Modules whose loader discovers its reference YAML by pattern (``*.yaml``
# glob or ``f"{id}.yaml"``) and validates each file; every YAML in those
# directories is covered. Pinned so a new pattern loader is reviewed.
_PATTERN_LOADED_MODULES = {"disease", "encounter"}


def _reference_yamls() -> dict[str, Path]:
    return {str(p.relative_to(_PKG / "modules")): p for p in sorted((_PKG / "modules").glob("*/reference_data/*.yaml"))}


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
    module_names = {p.name for p in (_PKG / "modules").iterdir() if p.is_dir()}
    covered: set[tuple[str, str]] = set()
    pattern_modules: set[str] = set()
    for path, tree in trees.items():
        rel = path.relative_to(_PKG).parts
        home = rel[1] if rel[0] == "modules" and len(rel) > 2 else None
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
