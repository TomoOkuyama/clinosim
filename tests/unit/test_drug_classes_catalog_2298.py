"""Drug safety reads drug classes and aliases from the drug catalog (Issue #2298)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.codes.drugs import all_drug_ids, drug_classes, identify_drug
from clinosim.modules.drug_safety import check_pair
from clinosim.modules.drug_safety.classifier import canonical_name, resolve_classes

pytestmark = pytest.mark.unit

_REF = Path(__file__).resolve().parents[2] / "clinosim" / "modules" / "drug_safety" / "reference_data"


def _rule_classes() -> set[str]:
    rules = yaml.safe_load((_REF / "contraindications.yaml").read_text(encoding="utf-8"))["rules"]
    disease = yaml.safe_load((_REF / "disease_contraindications.yaml").read_text(encoding="utf-8"))
    disease_rules = disease.get("rules") if isinstance(disease, dict) else disease
    out = {r["lhs"] for r in rules} | {r["rhs"] for r in rules}
    return out | {r["drug_class"] for r in disease_rules or [] if r.get("drug_class")}


def test_the_parallel_class_table_is_gone() -> None:
    assert not (_REF / "drug_classes.yaml").exists()


def test_every_rule_class_has_a_catalog_drug() -> None:
    members = {c for d in all_drug_ids() for c in drug_classes(d)}
    assert not sorted(_rule_classes() - members)


def test_classes_include_dotted_ancestors() -> None:
    assert drug_classes("warfarin") == ("anticoagulant.vka", "anticoagulant")
    assert "beta_blocker" in drug_classes("Metoprolol succinate")
    assert resolve_classes("Unobtainium-500") == []


@pytest.mark.parametrize(
    ("text", "drug_id"),
    [
        ("Warfarin 3mg PO daily", "warfarin"),
        ("ワルファリン錠1mg", "warfarin"),
        ("IV ketorolac 15 mg", "ketorolac"),
        ("Acetaminophen / Codeine", "acetaminophen_codeine"),
        ("ロキソニン", "loxoprofen"),
    ],
)
def test_identify_drug_reads_free_text(text: str, drug_id: str) -> None:
    rec = identify_drug(text)
    assert rec is not None and rec.drug_id == drug_id


def test_short_ascii_names_match_whole_words_only() -> None:
    # The normal-saline id "ns" must not match inside another word.
    rec = identify_drug("transdermal patch")
    assert rec is None or rec.drug_id != "normal_saline"


def test_combination_product_keeps_both_ingredients_classes() -> None:
    classes = set(resolve_classes("Acetaminophen / Codeine"))
    assert {"analgesic.non_opioid", "analgesic.opioid"} <= classes
    assert canonical_name("Acetaminophen / Codeine") != canonical_name("Acetaminophen")


def test_statin_interaction_needs_a_cyp3a4_substrate() -> None:
    assert check_pair("Simvastatin", "Clarithromycin").severity == "major"
    assert check_pair("Rosuvastatin", "Clarithromycin").is_allowed


def test_catalog_only_drugs_now_reach_the_rules() -> None:
    # Landiolol (catalog beta blocker) with a non-DHP CCB; was unknown to drug safety.
    assert not check_pair("Landiolol", "Diltiazem").is_allowed


class _NoDuplicateKeys(yaml.SafeLoader):
    pass


def _construct_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode) -> dict:
    keys = [loader.construct_object(k) for k, _ in node.value]
    dupes = {k for k in keys if keys.count(k) > 1}
    assert not dupes, f"duplicate keys {sorted(dupes)} at line {node.start_mark.line + 1}"
    return loader.construct_mapping(node)


_NoDuplicateKeys.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def test_catalog_has_no_duplicate_keys() -> None:
    # A repeated `aliases:` silently drops the first list.
    path = _REF.parents[2] / "codes" / "data" / "drugs.yaml"
    yaml.load(path.read_text(encoding="utf-8"), Loader=_NoDuplicateKeys)  # noqa: S506


def test_english_names_start_with_a_capital() -> None:
    # names.en is the display source; drug safety reports it as the active drug.
    from clinosim.codes.drugs import resolve_drug

    assert not [d for d in all_drug_ids() if resolve_drug(d).names["en"][:1].islower()]
