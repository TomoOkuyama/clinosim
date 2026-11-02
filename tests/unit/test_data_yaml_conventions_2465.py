"""Data YAML conventions (code-mapping spec §3.1, §3.2; Issue #2465).

Every data YAML under ``clinosim/codes/data``, ``clinosim/locale/shared`` and
``clinosim/locale/<cc>/code_mapping_*.yaml`` starts with a ``metadata`` block
whose ``kind`` is one of the specification's kinds, and the kind belongs where
the file lives. Data YAML is parsed by ``clinosim.datafiles``; the remaining
direct parses are a ratchet pinned to #2494.
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
    [*_ROOT.glob("codes/data/*.yaml"), *_ROOT.glob("locale/shared/*.yaml"), *_ROOT.glob("locale/*/code_mapping_*.yaml")]
)
_CODES_KINDS = {"code-system", "map", "crosswalk", "catalog", "value-set"}
# `reference` in locale/shared: country and clinical defaults the locale layer
# serves through its loaders (spec §3.2, Issue #2495).
_LOCALE_KINDS = {"display-table", "translation-table", "phrase-catalog", "reference"}


# file → direct yaml.safe_load / yaml.load calls not yet moved to
# clinosim.datafiles (Issue #2494). `locale/i18n.py` keeps its strict
# duplicate-key parser and strips the header itself.
_DIRECT_PARSES = {
    "audit/axes/silent_no_op.py": 1,
    "countries.py": 1,
    "dataset/__init__.py": 1,
    "determinism.py": 1,
    "locale/_io.py": 1,
    "modules/allergy/engine.py": 2,
    "modules/antibiotic/engine.py": 2,
    "modules/care_level/engine.py": 2,
    "modules/clinical_course/engine.py": 1,
    "modules/code_status/engine.py": 2,
    "modules/device/engine.py": 1,
    "modules/diagnosis/engine.py": 1,
    "modules/disease/protocol.py": 1,
    "modules/document/audit.py": 1,
    "modules/document/narrative/_chronic_soap.py": 1,
    "modules/document/narrative/_extra_context_builder.py": 1,
    "modules/document/narrative/_hedging.py": 1,
    "modules/document/narrative/registry.py": 2,
    "modules/document/narrative/semantic_check.py": 1,
    "modules/document/reference_data_loaders.py": 4,
    "modules/drug_safety/demographic.py": 1,
    "modules/drug_safety/engine.py": 3,
    "modules/encounter/protocol.py": 2,
    "modules/facility/hospital_state.py": 1,
    "modules/family_history/engine.py": 2,
    "modules/hai/__init__.py": 1,
    "modules/hai/engine.py": 1,
    "modules/hai/lab_lift.py": 1,
    "modules/healthcare_system/loader.py": 1,
    "modules/imaging/engine.py": 3,
    "modules/immunization/engine.py": 1,
    "modules/llm_service/engine.py": 3,
    "modules/llm_service/factory.py": 1,
    "modules/llm_service/prompt_registry.py": 1,
    "modules/longitudinal/loader.py": 1,
    "modules/monitoring/engine.py": 1,
    "modules/monitoring/mapping.py": 1,
    "modules/newborn/engine.py": 1,
    "modules/nursing/engine.py": 1,
    "modules/observation/engine.py": 3,
    "modules/observation/microbiology.py": 1,
    "modules/observation/nursing.py": 1,
    "modules/order/panel_grouping.py": 1,
    "modules/output/fhir_r4/labs/anthropometrics.py": 1,
    "modules/output/fhir_r4/lib/common.py": 1,
    "modules/pediatric/calendar.py": 1,
    "modules/physiology/engine.py": 2,
    "modules/population/_pediatric_anthropometry.py": 1,
    "modules/prophylaxis/engine.py": 1,
    "modules/sdoh/engine.py": 1,
    "modules/triage/engine.py": 1,
    "simulator/_setup.py": 1,
    "simulator/enumerate.py": 1,
    "simulator/event_refs.py": 1,
    "simulator/medication_pipeline.py": 1,
    "simulator/sex_gating.py": 1,
    "types/config.py": 1,
}


def _rel(path: Path) -> str:
    return path.relative_to(_ROOT).as_posix()


@pytest.mark.parametrize("path", _FILES, ids=_rel)
def test_every_data_yaml_has_a_kind(path: Path) -> None:
    assert data_metadata(path).get("kind") in DATA_KINDS


@pytest.mark.parametrize("path", _FILES, ids=_rel)
def test_the_kind_belongs_where_the_file_lives(path: Path) -> None:
    rel, kind = _rel(path), data_metadata(path)["kind"]
    if rel.startswith("codes/data/"):
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
