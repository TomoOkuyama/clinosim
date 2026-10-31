"""Issue #2291: LifeEvent.disease_id / ground_truth_diseases values belong to
declared namespaces, and the disease-id → ICD relations live in disease YAMLs."""

from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.modules.disease.protocol import load_all_disease_protocols
from clinosim.simulator.event_refs import EVENT_LABELS, event_ref_kind

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2] / "clinosim"


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        ("acute_mi", "disease"),
        ("suicidal_ideation_depression", "encounter"),
        ("Z34", "icd"),
        ("Z39", "icd"),
        ("Z38.0", "icd"),
        ("C50", "icd"),
        ("E11.9", "icd"),
        ("annual_health_screening", "encounter"),  # also an encounter condition id
        ("newborn_birth", "label"),
        ("well_child_infant", "label"),
        ("unknown_fever", "label"),
    ],
)
def test_producer_values_have_a_declared_kind(value: str, kind: str) -> None:
    assert event_ref_kind(value) == kind


def test_unknown_values_have_no_kind() -> None:
    assert event_ref_kind("not_a_thing") is None
    assert event_ref_kind("X99.99") is None


def test_every_event_label_is_classified() -> None:
    assert all(event_ref_kind(label) in ("label", "encounter") for label in EVENT_LABELS)


def test_disease_to_icd_relations_live_in_the_disease_yamls() -> None:
    protocols = load_all_disease_protocols()
    assert protocols["acute_mi"].implied_chronic_codes == ["I25", "I10", "E78"]
    assert protocols["cerebral_infarction"].sequela_code == "I69.3"
    assert protocols["hemorrhagic_stroke"].sequela_code == "I69.1"
    for proto in protocols.values():
        for code in proto.implied_chronic_codes:
            assert event_ref_kind(code) == "icd", (proto.disease_id, code)


def test_no_python_copy_of_the_disease_to_icd_mapping() -> None:
    for name in ("_IMPLIED_CHRONIC_BY_DISEASE", "_STROKE_SEQUELA_MAP"):
        hits = [
            p
            for p in _ROOT.rglob("*.py")
            if f"{name} = " in p.read_text(encoding="utf-8") or f"{name}: " in p.read_text(encoding="utf-8")
        ]
        assert not hits, (name, hits)


def test_validator_flags_an_unclassified_ground_truth() -> None:
    from types import SimpleNamespace

    from clinosim.modules.validator.consistency import ConsistencyReport, _check_ground_truth_namespace

    report = ConsistencyReport()
    record = SimpleNamespace(condition_event=SimpleNamespace(ground_truth_diseases=["acute_mi", "not_a_thing"]))
    _check_ground_truth_namespace(record, "p1", report)  # type: ignore[arg-type]
    assert [i.message for i in report.issues] == ["ground truth 'not_a_thing' has no declared kind"]
