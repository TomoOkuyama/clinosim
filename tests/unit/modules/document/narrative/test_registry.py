"""DocumentTypeSpec registry tests."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from clinosim.modules.document.narrative.registry import (
    SUPPORTED_DOCUMENT_TYPES,
    DocumentTypeSpec,
    load_document_type_specs,
    specs_for_country,
    specs_for_encounter_type,
)
from clinosim.types.document import DocumentType, FormatType


def test_registry_covers_α_min_1_doc_types() -> None:
    specs = load_document_type_specs()
    assert DocumentType.ADMISSION_HP in specs
    assert DocumentType.PROGRESS_NOTE in specs
    assert DocumentType.DISCHARGE_SUMMARY in specs


def test_admission_hp_spec_metadata() -> None:
    specs = load_document_type_specs()
    hp = specs[DocumentType.ADMISSION_HP]
    assert hp.loinc_code == "34117-2"
    assert hp.format_type == FormatType.COMPOSITION
    assert "us" in hp.countries_supported
    assert "jp" in hp.countries_supported


def test_progress_note_is_free_text() -> None:
    specs = load_document_type_specs()
    pn = specs[DocumentType.PROGRESS_NOTE]
    assert pn.format_type == FormatType.FREE_TEXT


def test_country_gating_for_us() -> None:
    us_specs = specs_for_country("us")
    types = [s.type_key for s in us_specs]
    assert "admission_hp" in types
    assert "progress_note" in types
    assert "discharge_summary" in types
    # JP-only docs(後続 phase で追加)はこの時点では未登録、フィルタ対象なし


def test_country_gating_unknown_returns_empty() -> None:
    result = specs_for_country("xx")
    assert result == []


def test_discharge_summary_spec_metadata() -> None:
    specs = load_document_type_specs()
    ds = specs[DocumentType.DISCHARGE_SUMMARY]
    assert ds.loinc_code == "18842-5"
    assert ds.format_type == FormatType.COMPOSITION
    assert "hospital_course" in ds.composition_sections


def test_load_raises_on_missing_required_field() -> None:
    """6-layer validator fires on missing required field."""
    import clinosim.modules.document.narrative.registry as reg_module

    bad_data = {
        "specs": {
            "admission_hp": {
                "loinc_code": "34117-2",
                "format_type": "composition",
                # countries_supported intentionally missing
                "generation_frequency": "admission_once",
            },
            "progress_note": {
                "loinc_code": "11506-3",
                "format_type": "free_text",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "daily",
            },
            "discharge_summary": {
                "loinc_code": "18842-5",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "discharge_once",
            },
            "admission_nursing_assessment": {
                "loinc_code": "78390-2",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "admission_once",
            },
            "nursing_shift_note": {
                "loinc_code": "34746-8",
                "format_type": "free_text",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "daily",
            },
            "nursing_discharge_summary": {
                "loinc_code": "34745-0",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "discharge_once",
            },
            "outpatient_soap": {
                "loinc_code": "34131-3",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "encounter_once",
            },
            "ed_note": {
                "loinc_code": "34878-9",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "encounter_once",
            },
            "ed_triage_note": {
                "loinc_code": "54094-8",
                "format_type": "free_text",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "encounter_once",
            },
            "admission_care_plan": {
                "loinc_code": "18776-5",
                "format_type": "composition",
                "countries_supported": ["jp"],
                "generation_frequency": "admission_once",
            },
            "nutrition_care_plan": {
                "loinc_code": "80791-7",
                "format_type": "composition",
                "countries_supported": ["jp"],
                "generation_frequency": "admission_once_los_gt_7",
            },
            "rehabilitation_plan": {
                "loinc_code": "34823-5",
                "format_type": "composition",
                "countries_supported": ["jp"],
                "generation_frequency": "admission_once_if_rehab_sessions",
            },
            "referral_note": {
                "loinc_code": "57133-1",
                "format_type": "composition",
                "countries_supported": ["jp"],
                "generation_frequency": "discharge_fraction_20pct",
            },
        }
    }
    with pytest.raises(ValueError, match="missing countries_supported"):
        reg_module._validate_document_type_specs(bad_data)


def test_load_raises_on_null_entry() -> None:
    """6-layer validator Layer 3: per-bucket null entry raises ValueError."""
    import clinosim.modules.document.narrative.registry as reg_module

    bad_data = {
        "specs": {
            "admission_hp": None,  # null entry
            "progress_note": {
                "loinc_code": "11506-3",
                "format_type": "free_text",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "daily",
            },
            "discharge_summary": {
                "loinc_code": "18842-5",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "discharge_once",
            },
            "admission_nursing_assessment": {
                "loinc_code": "78390-2",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "admission_once",
            },
            "nursing_shift_note": {
                "loinc_code": "34746-8",
                "format_type": "free_text",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "daily",
            },
            "nursing_discharge_summary": {
                "loinc_code": "34745-0",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "discharge_once",
            },
            "outpatient_soap": {
                "loinc_code": "34131-3",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "encounter_once",
            },
            "ed_note": {
                "loinc_code": "34878-9",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "encounter_once",
            },
            "ed_triage_note": {
                "loinc_code": "54094-8",
                "format_type": "free_text",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "encounter_once",
            },
            "admission_care_plan": {
                "loinc_code": "18776-5",
                "format_type": "composition",
                "countries_supported": ["jp"],
                "generation_frequency": "admission_once",
            },
            "nutrition_care_plan": {
                "loinc_code": "80791-7",
                "format_type": "composition",
                "countries_supported": ["jp"],
                "generation_frequency": "admission_once_los_gt_7",
            },
            "rehabilitation_plan": {
                "loinc_code": "34823-5",
                "format_type": "composition",
                "countries_supported": ["jp"],
                "generation_frequency": "admission_once_if_rehab_sessions",
            },
            "referral_note": {
                "loinc_code": "57133-1",
                "format_type": "composition",
                "countries_supported": ["jp"],
                "generation_frequency": "discharge_fraction_20pct",
            },
        }
    }
    with pytest.raises(ValueError, match="admission_hp.*empty entry"):
        reg_module._validate_document_type_specs(bad_data)


def test_load_raises_on_empty_countries_supported() -> None:
    """6-layer validator fires on empty countries_supported list."""
    import clinosim.modules.document.narrative.registry as reg_module

    bad_data = {
        "specs": {
            "admission_hp": {
                "loinc_code": "34117-2",
                "format_type": "composition",
                "countries_supported": [],  # empty
                "generation_frequency": "admission_once",
            },
            "progress_note": {
                "loinc_code": "11506-3",
                "format_type": "free_text",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "daily",
            },
            "discharge_summary": {
                "loinc_code": "18842-5",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "discharge_once",
            },
            "admission_nursing_assessment": {
                "loinc_code": "78390-2",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "admission_once",
            },
            "nursing_shift_note": {
                "loinc_code": "34746-8",
                "format_type": "free_text",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "daily",
            },
            "nursing_discharge_summary": {
                "loinc_code": "34745-0",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "discharge_once",
            },
            "outpatient_soap": {
                "loinc_code": "34131-3",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "encounter_once",
            },
            "ed_note": {
                "loinc_code": "34878-9",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "encounter_once",
            },
            "ed_triage_note": {
                "loinc_code": "54094-8",
                "format_type": "free_text",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "encounter_once",
            },
            "admission_care_plan": {
                "loinc_code": "18776-5",
                "format_type": "composition",
                "countries_supported": ["jp"],
                "generation_frequency": "admission_once",
            },
            "nutrition_care_plan": {
                "loinc_code": "80791-7",
                "format_type": "composition",
                "countries_supported": ["jp"],
                "generation_frequency": "admission_once_los_gt_7",
            },
            "rehabilitation_plan": {
                "loinc_code": "34823-5",
                "format_type": "composition",
                "countries_supported": ["jp"],
                "generation_frequency": "admission_once_if_rehab_sessions",
            },
            "referral_note": {
                "loinc_code": "57133-1",
                "format_type": "composition",
                "countries_supported": ["jp"],
                "generation_frequency": "discharge_fraction_20pct",
            },
        }
    }
    with pytest.raises(ValueError, match="countries_supported empty"):
        reg_module._validate_document_type_specs(bad_data)


# === α-min-2 tests ===

def test_load_specs_returns_13_total() -> None:
    """13 (3 α-min-1 + 6 α-min-2 + 3 chain-2 + 1 P2-13 PR2b referral_note) specs."""
    load_document_type_specs.cache_clear()
    specs = load_document_type_specs()
    assert len(specs) == 13, (
        f"Expected 13 specs (3 α-min-1 + 6 α-min-2 + 3 chain-2 + 1 referral_note), "
        f"got {len(specs)}"
    )


def test_supported_document_types_covers_13_entries() -> None:
    """SUPPORTED_DOCUMENT_TYPES frozenset has 13 members after P2-13 PR2b."""
    assert len(SUPPORTED_DOCUMENT_TYPES) == 13


def test_specs_for_encounter_type_outpatient_returns_only_outpatient_soap() -> None:
    """Among encounter-type-restricted specs, only OUTPATIENT_SOAP matches outpatient."""
    load_document_type_specs.cache_clear()
    outpatient_specs = specs_for_encounter_type("outpatient")
    # α-min-1 specs have empty encounter_types_supported (no restriction = also in results).
    # Among those WITH an explicit restriction, only outpatient_soap should match.
    restricted = [s for s in outpatient_specs if s.encounter_types_supported]
    keys = [s.type_key for s in restricted]
    assert keys == ["outpatient_soap"], f"Expected only outpatient_soap in restricted set, got {keys}"


def test_specs_for_encounter_type_inpatient_returns_10_specs() -> None:
    """3 α-min-1 (no restriction, matches all) + 3 nursing specs + admission_care_plan +
    nutrition_care_plan + rehabilitation_plan (chain 2) + referral_note (P2-13 PR2b)
    = 10 total for inpatient."""
    load_document_type_specs.cache_clear()
    inpatient_specs = specs_for_encounter_type("inpatient")
    assert len(inpatient_specs) == 10, f"Expected 10 inpatient specs, got {len(inpatient_specs)}"


def test_specs_for_encounter_type_emergency_returns_2_ed_specs() -> None:
    """ED_NOTE and ED_TRIAGE_NOTE are the only encounter-restricted specs for emergency."""
    load_document_type_specs.cache_clear()
    emergency_specs = specs_for_encounter_type("emergency")
    restricted = [s for s in emergency_specs if s.encounter_types_supported]
    keys = {s.type_key for s in restricted}
    assert keys == {"ed_note", "ed_triage_note"}, f"Expected ED specs only, got {keys}"


def test_encounter_once_generation_frequency_recognized() -> None:
    """encounter_once generation_frequency value loads without error and is stored correctly."""
    load_document_type_specs.cache_clear()
    specs = load_document_type_specs()
    assert specs[DocumentType.OUTPATIENT_SOAP].generation_frequency == "encounter_once"
    assert specs[DocumentType.ED_NOTE].generation_frequency == "encounter_once"
    assert specs[DocumentType.ED_TRIAGE_NOTE].generation_frequency == "encounter_once"


def test_daily_3shift_generation_frequency_recognized() -> None:
    """α-min-3: nursing_shift_note carries daily_3shift and loads without error."""
    load_document_type_specs.cache_clear()
    specs = load_document_type_specs()
    assert specs[DocumentType.NURSING_SHIFT_NOTE].generation_frequency == "daily_3shift"


def test_generation_frequencies_allowlist_contains_all_yaml_values() -> None:
    """Every YAML frequency value must be in the canonical allowlist (Layer 7 sanity)."""
    from clinosim.modules.document.narrative.registry import GENERATION_FREQUENCIES

    load_document_type_specs.cache_clear()
    for spec in load_document_type_specs().values():
        assert spec.generation_frequency in GENERATION_FREQUENCIES


def test_load_raises_on_unknown_generation_frequency() -> None:
    """α-min-3 Layer 7: an unknown generation_frequency raises fail-loud ValueError.

    Without this layer a typo like "daily3shift" would fall through the engine
    if/elif dispatch and silently emit zero documents (PR-90 class silent no-op).
    """
    import clinosim.modules.document.narrative.registry as reg_module

    ref_dir = Path(reg_module.__file__).resolve().parent.parent / "reference_data"
    with (ref_dir / "document_type_specs.yaml").open() as f:
        data = yaml.safe_load(f)
    data["specs"]["nursing_shift_note"]["generation_frequency"] = "daily3shift"
    with pytest.raises(ValueError, match="unknown generation_frequency"):
        reg_module._validate_document_type_specs(data)


# === N-chain adv-1 I-1: Layers 8 + 9 (stage2_strategy validation) ===


def _load_production_yaml() -> dict:
    import clinosim.modules.document.narrative.registry as reg_module

    ref_dir = Path(reg_module.__file__).resolve().parent.parent / "reference_data"
    with (ref_dir / "document_type_specs.yaml").open() as f:
        return yaml.safe_load(f)


def test_load_raises_on_unknown_stage2_strategy() -> None:
    """Layer 8: a typo like "template-seed" must raise at YAML load.

    Without this layer, replacement_strategy's unknown-strategy branch
    silently returns template output — the whole LLM path becomes a
    silent no-op (PR-90 class).
    """
    import clinosim.modules.document.narrative.registry as reg_module

    data = _load_production_yaml()
    data["specs"]["admission_hp"]["stage2_strategy"] = "template-seed"  # typo
    with pytest.raises(ValueError, match="unknown stage2_strategy"):
        reg_module._validate_document_type_specs(data)


def test_load_raises_on_template_seed_with_empty_llm_enabled_sections() -> None:
    """Layer 9: template_seed with no llm_enabled_sections = dead LLM wiring."""
    import clinosim.modules.document.narrative.registry as reg_module

    data = _load_production_yaml()
    data["specs"]["admission_hp"]["llm_enabled_sections"] = []
    with pytest.raises(ValueError, match="llm_enabled_sections"):
        reg_module._validate_document_type_specs(data)


def test_load_raises_on_llm_enabled_section_not_in_composition_sections() -> None:
    """Layer 9: llm_enabled_sections ⊄ composition_sections would fabricate a
    section that no template renders (empty-seed hallucination risk).
    """
    import clinosim.modules.document.narrative.registry as reg_module

    data = _load_production_yaml()
    data["specs"]["admission_hp"]["llm_enabled_sections"] = ["hpi", "nonexistent_section"]
    with pytest.raises(ValueError, match="nonexistent_section"):
        reg_module._validate_document_type_specs(data)


def test_load_raises_on_template_seed_with_free_text_format() -> None:
    """Layer 9: free_text renderers emit NO sections (raw_text only) — the
    per-section seed replacement has nothing to seed from, so template_seed
    on a non-composition spec is forbidden at load time.
    """
    import clinosim.modules.document.narrative.registry as reg_module

    data = _load_production_yaml()
    data["specs"]["progress_note"]["stage2_strategy"] = "template_seed"
    data["specs"]["progress_note"]["llm_enabled_sections"] = ["subjective"]
    with pytest.raises(ValueError, match="composition"):
        reg_module._validate_document_type_specs(data)


# === chain 2: admission_care_plan (LOINC 18776-5) ===


def test_admission_care_plan_loinc_code_resolves() -> None:
    """LOINC 18776-5 ('Plan of care note') must resolve in both languages —
    verified against loinc.org / findacode.com during design (spec §2)."""
    from clinosim.codes import lookup as code_lookup

    assert code_lookup("loinc", "18776-5", "en") == "Plan of care note"
    assert code_lookup("loinc", "18776-5", "ja") == "入院診療計画書"


def test_document_type_has_admission_care_plan() -> None:
    assert DocumentType.ADMISSION_CARE_PLAN.value == "admission_care_plan"


def test_registry_covers_admission_care_plan() -> None:
    specs = load_document_type_specs()
    assert DocumentType.ADMISSION_CARE_PLAN in specs


def test_admission_care_plan_spec_metadata() -> None:
    specs = load_document_type_specs()
    acp = specs[DocumentType.ADMISSION_CARE_PLAN]
    assert acp.loinc_code == "18776-5"
    assert acp.format_type == FormatType.COMPOSITION
    assert acp.countries_supported == ("jp",)
    assert acp.generation_frequency == "admission_once"
    assert acp.stage2_strategy == "template_only"
    assert set(acp.composition_sections) == {
        "ward_and_room", "other_staff", "diagnosis", "symptoms",
        "treatment_plan", "test_schedule", "surgery_schedule",
        "estimated_los", "special_nutrition_management", "other_plans",
    }


def test_admission_care_plan_is_jp_only() -> None:
    us_specs = specs_for_country("us")
    jp_specs = specs_for_country("jp")
    assert "admission_care_plan" not in [s.type_key for s in us_specs]
    assert "admission_care_plan" in [s.type_key for s in jp_specs]


def test_production_yaml_passes_stage2_validation() -> None:
    """Positive: the shipped document_type_specs.yaml passes Layers 8 + 9."""
    import clinosim.modules.document.narrative.registry as reg_module

    reg_module._validate_document_type_specs(_load_production_yaml())


# === chain 2: nutrition_care_plan (LOINC 80791-7) ===


def test_nutrition_care_plan_loinc_code_resolves() -> None:
    """LOINC 80791-7 ('Nutrition and dietetics Plan of care note') must
    resolve in both languages — verified against loinc.org during design
    (spec §2)."""
    from clinosim.codes import lookup as code_lookup

    assert code_lookup("loinc", "80791-7", "en") == "Nutrition and dietetics Plan of care note"
    assert code_lookup("loinc", "80791-7", "ja") == "栄養管理計画書"


def test_document_type_has_nutrition_care_plan() -> None:
    assert DocumentType.NUTRITION_CARE_PLAN.value == "nutrition_care_plan"


def test_registry_covers_nutrition_care_plan() -> None:
    specs = load_document_type_specs()
    assert DocumentType.NUTRITION_CARE_PLAN in specs


def test_nutrition_care_plan_spec_metadata() -> None:
    specs = load_document_type_specs()
    ncp = specs[DocumentType.NUTRITION_CARE_PLAN]
    assert ncp.loinc_code == "80791-7"
    assert ncp.format_type == FormatType.COMPOSITION
    assert ncp.countries_supported == ("jp",)
    assert ncp.generation_frequency == "admission_once_los_gt_7"
    assert ncp.stage2_strategy == "template_only"
    assert set(ncp.composition_sections) == {
        "ward_and_physician", "dietitian", "nutrition_risk",
        "nutrition_assessment", "nutrition_goals", "nutrition_supply",
        "dysphagia_diet", "dietary_content", "nutrition_counseling",
        "other_issues", "reassessment_timing", "discharge_evaluation",
    }


def test_nutrition_care_plan_is_jp_only() -> None:
    us_specs = specs_for_country("us")
    jp_specs = specs_for_country("jp")
    assert "nutrition_care_plan" not in [s.type_key for s in us_specs]
    assert "nutrition_care_plan" in [s.type_key for s in jp_specs]


def test_admission_once_los_gt_7_in_generation_frequencies_allowlist() -> None:
    from clinosim.modules.document.narrative.registry import GENERATION_FREQUENCIES

    assert "admission_once_los_gt_7" in GENERATION_FREQUENCIES


# === chain 2: rehabilitation_plan (LOINC 34823-5) ===


def test_document_type_has_rehabilitation_plan() -> None:
    assert DocumentType.REHABILITATION_PLAN.value == "rehabilitation_plan"


def test_generation_frequencies_includes_admission_once_if_rehab_sessions() -> None:
    from clinosim.modules.document.narrative.registry import GENERATION_FREQUENCIES

    assert "admission_once_if_rehab_sessions" in GENERATION_FREQUENCIES
