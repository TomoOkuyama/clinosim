"""Issue #2342: the code-mapping specification names only functions and
files that exist, and every listed deviation points at an issue."""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = _ROOT / "docs" / "design-guides" / "code-mapping-and-localization-spec.md"

# Every resolver the spec's section 4 promises, as module → names.
_RESOLVERS = {
    "clinosim.codes": [
        "display",
        "code_exists",
        "get_system_uri",
        "system_key_for_uri",
        "system_key_for",
        "is_english_only_system",
        "jp_clins_lab_system",
        "jlac10_display",
        "lookup",
    ],
    "clinosim.codes.valuesets": ["concept_group", "has_condition", "patient_condition_names", "code_by_chronic_prefix"],
    "clinosim.codes.drugs": ["resolve_drug", "get_drug", "find_drug", "names_drug", "drug_name_needles"],
    "clinosim.codes.procedures": ["procedure_code", "procedure_type_display", "procedure_code_display"],
    "clinosim.codes.ucum": ["ucum_code", "ucum_quantity"],
    "clinosim.codes.loinc": ["loinc_display", "loinc_coding"],
    "clinosim.codes.prefectures": ["prefecture_code"],
    "clinosim.locale.loader": [
        "load_code_mapping",
        "lab_code",
        "lab_codes",
        "vocab_display",
        "narrative_label",
        "imaging_exam_display",
        "department_display",
        "department_specialty_snomed",
        "role_display",
        "chronic_followup_vitals",
        "chronic_followup_interval_months",
    ],
    "clinosim.locale.i18n": ["t"],
    "clinosim.countries": ["lang_for", "is_jp", "is_us"],
    "clinosim.modules.output.fhir_r4.lib.common": ["dual_slot_concept"],
    "clinosim.modules._shared": ["practitioner_name", "pick_localized_field"],
    "clinosim.simulator.event_refs": ["event_ref_kind"],
}


@pytest.mark.parametrize("module", sorted(_RESOLVERS))
def test_every_spec_resolver_exists(module: str) -> None:
    mod = importlib.import_module(module)
    missing = [name for name in _RESOLVERS[module] if not hasattr(mod, name)]
    assert not missing, (module, missing)
    text = _SPEC.read_text(encoding="utf-8")
    assert all(re.search(rf"\b{name}\b", text) for name in _RESOLVERS[module])


def test_every_file_the_spec_names_exists() -> None:
    text = _SPEC.read_text(encoding="utf-8")
    paths = set(re.findall(r"`((?:clinosim/)?(?:codes|locale)/[\w./-]+\.(?:yaml|py))`", text))
    for rel in paths:
        candidates = [_ROOT / rel, _ROOT / "clinosim" / rel]
        assert any(p.exists() for p in candidates), rel


def test_every_deviation_points_at_an_issue() -> None:
    section = _SPEC.read_text(encoding="utf-8").split("## 9. Known deviations", 1)[1]
    rows = [line for line in section.splitlines() if line.startswith("| ") and not line.startswith("| Deviation")]
    rows = [r for r in rows if not set(r) <= set("|- ")]
    assert rows
    assert all(re.search(r"\| #\d+ \|$", r) for r in rows), rows
