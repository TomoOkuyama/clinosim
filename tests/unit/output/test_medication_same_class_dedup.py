"""Same-day same-class MedicationRequest dedup (Issues #1176 / #1179).

- #1176: ACE-I + ARB co-prescription (dual RAAS blockade) — 70 orders
  across 19 patients (Class III: Harm per current guidelines).
- #1179: same-day PPI + PPI (26 buckets), NSAID + NSAID (11), and
  Anticoagulant + Anticoagulant (29).

The emit-time guard drops later orders that duplicate the therapeutic
class of an earlier order authored on the same day for the same patient.
Drugs not on the class list are always kept.
"""

from __future__ import annotations

from clinosim.modules.output.fhir_r4.medications.medications import (
    _classify_medication,
    _dedup_same_class_orders,
)


def _mk(drug: str, day: str = "2026-05-01", patient: str = "pt-x", mr_id: str = "") -> dict:
    return {
        "resourceType": "MedicationRequest",
        "id": mr_id or f"mr-{drug}",
        "subject": {"reference": f"Patient/{patient}"},
        "medicationCodeableConcept": {"text": drug},
        "authoredOn": day,
    }


def test_classify_ppi() -> None:
    assert _classify_medication("オメプラゾール") == "ppi"
    assert _classify_medication("Omeprazole 20mg") == "ppi"


def test_classify_nsaid() -> None:
    assert _classify_medication("イブプロフェン") == "nsaid"
    assert _classify_medication("Diclofenac sodium 50mg") == "nsaid"


def test_classify_anticoagulant() -> None:
    assert _classify_medication("エドキサバン") == "anticoagulant"
    assert _classify_medication("Warfarin 3mg") == "anticoagulant"


def test_classify_raas_collapses_ace_and_arb_to_supergroup() -> None:
    assert _classify_medication("エナラプリル") == "raas"
    assert _classify_medication("カンデサルタン") == "raas"
    assert _classify_medication("Enalapril 5mg") == "raas"


def test_classify_uncovered_returns_empty() -> None:
    # A statin / DPP-4 / beta blocker is not on the collision list, so
    # they stay unclassified and never get dropped.
    assert _classify_medication("アトルバスタチン") == ""
    assert _classify_medication("メトホルミン") == ""


def test_dedup_drops_second_ppi_same_day() -> None:
    mrs = [
        _mk("オメプラゾール", mr_id="mr-a"),
        _mk("ランソプラゾール", mr_id="mr-b"),
    ]
    out = _dedup_same_class_orders(mrs)
    assert len(out) == 1
    assert out[0]["id"] == "mr-a"


def test_dedup_drops_ace_when_arb_precedes() -> None:
    mrs = [
        _mk("カンデサルタン", mr_id="mr-arb"),
        _mk("エナラプリル", mr_id="mr-acei"),
    ]
    out = _dedup_same_class_orders(mrs)
    assert len(out) == 1
    assert out[0]["id"] == "mr-arb"


def test_dedup_drops_second_anticoagulant() -> None:
    mrs = [
        _mk("エドキサバン", mr_id="mr-edx"),
        _mk("アピキサバン", mr_id="mr-api"),
    ]
    out = _dedup_same_class_orders(mrs)
    assert len(out) == 1
    assert out[0]["id"] == "mr-edx"


def test_dedup_preserves_across_different_days() -> None:
    mrs = [
        _mk("オメプラゾール", day="2026-05-01", mr_id="mr-a"),
        _mk("ランソプラゾール", day="2026-05-02", mr_id="mr-b"),
    ]
    assert len(_dedup_same_class_orders(mrs)) == 2


def test_dedup_preserves_across_different_patients() -> None:
    mrs = [
        _mk("オメプラゾール", patient="pt-1", mr_id="mr-a"),
        _mk("ランソプラゾール", patient="pt-2", mr_id="mr-b"),
    ]
    assert len(_dedup_same_class_orders(mrs)) == 2


def test_dedup_preserves_uncovered_drugs() -> None:
    # Two different statins on the same day for the same patient: not on
    # the collision list, so both survive.
    mrs = [
        _mk("アトルバスタチン", mr_id="mr-a"),
        _mk("ロスバスタチン", mr_id="mr-b"),
    ]
    assert len(_dedup_same_class_orders(mrs)) == 2


def test_dedup_preserves_different_classes_same_day() -> None:
    # A PPI + an NSAID + an Anticoagulant on the same day: all three
    # different classes, all kept.
    mrs = [
        _mk("オメプラゾール", mr_id="mr-ppi"),
        _mk("イブプロフェン", mr_id="mr-nsaid"),
        _mk("エドキサバン", mr_id="mr-doac"),
    ]
    assert len(_dedup_same_class_orders(mrs)) == 3


def test_dedup_empty_authored_on_passes_through() -> None:
    mrs = [
        {
            "resourceType": "MedicationRequest",
            "subject": {"reference": "Patient/pt-x"},
            "medicationCodeableConcept": {"text": "オメプラゾール"},
            "authoredOn": "",
        },
        _mk("ランソプラゾール", mr_id="mr-b"),
    ]
    out = _dedup_same_class_orders(mrs)
    # Empty authoredOn = cannot key = passes through unchanged
    assert len(out) == 2
