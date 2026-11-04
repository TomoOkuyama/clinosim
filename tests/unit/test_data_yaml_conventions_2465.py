"""Data YAML conventions (code-mapping spec §3.1, §3.2; Issue #2465).

Every data YAML under ``clinosim/codes/data``, ``clinosim/locale/shared`` and
``clinosim/locale/<cc>/code_mapping_*.yaml`` starts with a ``metadata`` block
whose ``kind`` is one of the specification's kinds, and the kind belongs where
the file lives. Data YAML is parsed by ``clinosim.datafiles``; only configuration and
input files are parsed directly.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import clinosim
from clinosim.datafiles import DATA_KINDS, data_metadata, load_data_yaml

pytestmark = pytest.mark.unit

_ROOT = Path(clinosim.__file__).parent
_FILES = sorted(
    [
        *_ROOT.glob("codes/data/*.yaml"),
        *_ROOT.glob("locale/shared/*.yaml"),
        *_ROOT.glob("locale/*/code_mapping_*.yaml"),
        *_ROOT.glob("**/reference_data/*.yaml"),
    ]
)
_CODES_KINDS = {"code-system", "map", "crosswalk", "catalog", "value-set"}
# `reference` in locale/shared: country and clinical defaults the locale layer
# serves through its loaders (spec §3.2, Issue #2495).
_LOCALE_KINDS = {"display-table", "translation-table", "phrase-catalog", "reference"}


# Files that parse YAML that is not data YAML — user configuration, dataset
# presets, LLM prompt templates and paths passed in by the caller — with the
# number of parses (Issue #2494). Data YAML goes through clinosim.datafiles;
# `locale/i18n.py` keeps its duplicate-key-strict parser and strips the header
# itself.
_DIRECT_PARSES = {
    "dataset/__init__.py": 1,  # dataset preset spec
    "determinism.py": 1,  # determinism configuration
    "modules/document/narrative/semantic_check.py": 1,  # a narrative file passed in by the caller
    "modules/facility/hospital_state.py": 1,  # hospital operations configuration
    "modules/healthcare_system/loader.py": 1,  # healthcare-system configuration
    "modules/llm_service/factory.py": 1,  # LLM service configuration
    "modules/llm_service/prompt_registry.py": 1,  # LLM prompt templates
    "simulator/_setup.py": 1,  # hospital configuration passed on the command line
    "types/config.py": 1,  # simulation configuration
}


def _rel(path: Path) -> str:
    return path.relative_to(_ROOT).as_posix()


@pytest.mark.parametrize("path", _FILES, ids=_rel)
def test_every_data_yaml_has_a_kind(path: Path) -> None:
    assert data_metadata(path).get("kind") in DATA_KINDS


@pytest.mark.parametrize("path", _FILES, ids=_rel)
def test_the_kind_belongs_where_the_file_lives(path: Path) -> None:
    rel, kind = _rel(path), data_metadata(path)["kind"]
    if "/reference_data/" in rel:
        # Disease and encounter protocols, and module reference data (Issue #2500).
        protocol = rel.startswith(("modules/disease/", "modules/encounter/"))
        assert kind == ("protocol" if protocol else "reference"), (rel, kind)
    elif rel.startswith("codes/data/"):
        assert kind in _CODES_KINDS, (rel, kind)
    elif "/code_mapping_" in rel:
        assert kind == "country-mapping", (rel, kind)
    else:
        assert kind in _LOCALE_KINDS, (rel, kind)


def test_metadata_is_not_a_section() -> None:
    assert all("metadata" not in load_data_yaml(p) for p in _FILES)


def _direct_parses() -> dict[str, int]:
    found: dict[str, int] = {}
    for path in sorted(_ROOT.rglob("*.py")):
        rel = _rel(path)
        if rel in ("datafiles.py", "locale/i18n.py"):
            continue
        n = sum(
            1
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("safe_load", "load")
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "yaml"
        )
        if n:
            found[rel] = n
    return found


def test_no_new_direct_yaml_parse() -> None:
    found = _direct_parses()
    grown = {f: (n, _DIRECT_PARSES.get(f, 0)) for f, n in found.items() if n > _DIRECT_PARSES.get(f, 0)}
    assert not grown, f"parse data YAML with clinosim.datafiles (found, pinned): {grown}"


def test_direct_parse_ratchet_shrinks() -> None:
    found = _direct_parses()
    stale = {f: (found.get(f, 0), n) for f, n in _DIRECT_PARSES.items() if found.get(f, 0) < n}
    assert not stale, f"fewer direct parses than pinned — lower the entry (found, pinned): {stale}"


def _language_suffixed_keys(node: object, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and key.endswith(("_en", "_ja")):
                found.append(f"{path}.{key}")
            found += _language_suffixed_keys(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            found += _language_suffixed_keys(value, f"{path}[{i}]")
    return found


def test_no_language_suffixed_key_in_any_data_yaml() -> None:
    """Translatable text is a language map, never a `<field>_<lang>` key
    (spec §3.1 rule 4; META #2475)."""
    offenders = {
        _rel(p): keys for p in sorted(_ROOT.rglob("*.yaml")) if (keys := _language_suffixed_keys(load_data_yaml(p)))
    }
    assert not offenders, offenders
