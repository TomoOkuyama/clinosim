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
        "slug_to_code",
        "code_system",
        "system_keys",
        "CodeSystem",
    ],
    "clinosim.codes.valuesets": ["concept_group", "has_condition", "patient_condition_names", "code_by_chronic_prefix"],
    "clinosim.codes.drugs": ["resolve_drug", "get_drug", "find_drug", "drug_key", "same_drug"],
    "clinosim.codes.procedures": ["procedure_code", "procedure_type_display", "procedure_code_display"],
    "clinosim.codes.ucum": ["ucum_code", "ucum_quantity"],
    "clinosim.codes.loinc": ["loinc_display", "loinc_coding"],
    "clinosim.codes.prefectures": ["prefecture_code"],
    "clinosim.codes.jlac10": ["jp_clins_lab_system", "jlac10_display"],
    "clinosim.codes.medis": ["medis_disease_keyno"],
    "clinosim.codes.yj": ["jp_drug_system_key", "is_verified_yj"],
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
    "clinosim.locale.localized": ["localized", "localized_field", "label"],
    "clinosim.locale.free_text": [
        "localize_drug_name",
        "localize_procedure_name",
        "localize_allergen_name",
        "localize_free_text",
    ],
    "clinosim.countries": ["lang_for", "is_jp", "is_us", "normalize_lang"],
    "clinosim.modules.output.fhir_r4.lib.common": ["dual_slot_concept", "system_coding"],
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
    section = re.split(r"\n## \d+\. Known deviations\n", _SPEC.read_text(encoding="utf-8"), maxsplit=1)[1]
    rows = [line for line in section.splitlines() if line.startswith("| ") and not line.startswith("| Deviation")]
    rows = [r for r in rows if not set(r) <= set("|- ")]
    # No open deviation is written as "None: …" instead of an empty table.
    assert rows or "\nNone:" in section.split("\n## ", 1)[0]
    assert len(rows) == len({r.rsplit("|", 2)[-2].strip() for r in rows}), "one row per issue"
    assert all(re.search(r"\| #\d+ \|$", r) for r in rows), rows


def test_every_enforcing_test_the_spec_names_exists() -> None:
    text = _SPEC.read_text(encoding="utf-8")
    paths = set(re.findall(r"`(tests/[\w/]+\.py)`", text))
    assert paths
    missing = sorted(p for p in paths if not (_ROOT / p).exists())
    assert not missing, missing


def test_japanese_counterpart_matches_sections_and_deviations() -> None:
    en = _SPEC.read_text(encoding="utf-8")
    ja = _SPEC.with_name(_SPEC.stem + ".ja.md").read_text(encoding="utf-8")

    def numbered(text: str) -> list[str]:
        return re.findall(r"^#{2,3} (\d+(?:\.\d+)?)\.? ", text, flags=re.M)

    assert numbered(en) == numbered(ja)
    assert re.findall(r"\| (#\d+) \|$", en, flags=re.M) == re.findall(r"\| (#\d+) \|$", ja, flags=re.M)
