"""Unit tests for clinosim.audit.axes.jp_language.

Issue #473 rewrote this axis from an ``Observation``-only, per-Module
check into a cohort-level walker with dual predicates (JP-side "no JP
where JP expected" and US-side "no JP in EN output"). These tests pin:

- The predicate itself (``_is_jp_violation`` / ``_is_us_leakage``).
- The slot scope (``.text`` always, ``.coding[].display`` only when
  the system is not an English canonical CS).
- The excluded blocks (``meta`` / ``identifier`` / ``extension`` /
  ``modifierExtension`` / ``contained``; URL-shaped strings).
- The cohort-level entrypoint (``run`` with ``spec=None``).
- The segmented rollout (WARN on JP violations, FAIL on US leakage).

Intentional-regression tests (fixture with 1 residue → detection) are
in ``test_axis_jp_language_gate_regression.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.audit.axes import jp_language
from clinosim.audit.axes.jp_language import (
    _is_jp_violation,
    _is_us_leakage,
    _iter_slots,
    count_jp_violations,
    count_us_leakage,
)
from clinosim.audit.types import Cohort

# ────────────────────────────────────────────────────────────────────
# Predicate — pins the "Latin word AND no JP char" rule


@pytest.mark.unit
class TestJpViolationPredicate:
    def test_pure_english_word_is_violation(self):
        assert _is_jp_violation("Survey") is True
        assert _is_jp_violation("Blood glucose monitoring") is True

    def test_pure_japanese_is_ok(self):
        assert _is_jp_violation("白血球数") is False
        assert _is_jp_violation("外来経過記録") is False

    def test_mixed_jp_and_latin_is_ok(self):
        # This is the key case the allow-list approach failed on —
        # "AVPU" is a Latin word, but the string as a whole has JP.
        assert _is_jp_violation("意識レベル (AVPU)") is False
        assert _is_jp_violation("血清クレアチニン(Cre)") is False
        assert _is_jp_violation("外来経過記録（SOAP）") is False
        assert _is_jp_violation("JCCLS共用基準範囲2022") is False

    def test_empty_and_numeric_are_not_violations(self):
        assert _is_jp_violation("") is False
        assert _is_jp_violation("123") is False
        assert _is_jp_violation(">100,000") is False

    def test_single_letter_is_not_a_word(self):
        # ``[A-Za-z]{2,}`` — single letters (unit suffixes like ``A``,
        # ``S``) are not "Latin words" in this axis.
        assert _is_jp_violation("A") is False


@pytest.mark.unit
class TestUsLeakagePredicate:
    def test_pure_english_is_ok(self):
        assert _is_us_leakage("Leukocytes") is False

    def test_any_japanese_char_is_leakage(self):
        assert _is_us_leakage("白血球数") is True
        assert _is_us_leakage("Leukocytes 白") is True  # mixed still counts


# ────────────────────────────────────────────────────────────────────
# Slot scope — pins .text always, .coding[].display filtered by system


@pytest.mark.unit
class TestSlotIter:
    def test_yields_text_at_top_level(self):
        obj = {"text": "hello"}
        slots = list(_iter_slots(obj))
        assert slots == [("text", "hello")]

    def test_yields_text_nested(self):
        obj = {"code": {"text": "hello"}}
        slots = list(_iter_slots(obj))
        assert ("code.text", "hello") in slots

    def test_skips_display_when_system_is_english_canonical(self):
        obj = {
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "6690-2",
                        "display": "Leukocytes",
                    }
                ]
            }
        }
        slots = list(_iter_slots(obj))
        # LOINC display MUST NOT be surfaced — it is EN canonical by design.
        assert not any(s.endswith(".display") for s, _ in slots)

    def test_yields_display_when_system_is_unknown(self):
        obj = {
            "code": {
                "coding": [
                    {
                        "system": "http://example.jp/custom-cs",
                        "code": "X-1",
                        "display": "AST",
                    }
                ]
            }
        }
        slots = list(_iter_slots(obj))
        assert ("code.coding[].display", "AST") in slots

    def test_skips_display_when_corelabo_cs(self):
        # CoreLabo CS displays are English SD Fixed values — by design.
        obj = {
            "code": {
                "coding": [
                    {
                        "system": ("http://jpfhir.jp/fhir/clins/CodeSystem/JLAC10/JP_CLINS_ObsLabResult_CoreLabo_CS"),
                        "code": "2A0100000019101",
                        "display": "Cre",
                    }
                ]
            }
        }
        slots = list(_iter_slots(obj))
        assert not any(s.endswith(".display") for s, _ in slots)

    def test_excludes_meta_identifier_extension(self):
        obj = {
            "meta": {"profile": ["http://example/Profile", "text-with-Latin"]},
            "identifier": [{"value": "ID123"}],
            "extension": [{"url": "urn:x", "valueString": "English text"}],
            "text": "kept",
        }
        slots = list(_iter_slots(obj))
        # Only the top-level .text is retained.
        assert slots == [("text", "kept")]

    def test_skips_url_shaped_strings(self):
        obj = {"text": "https://example.com/thing"}
        slots = list(_iter_slots(obj))
        assert slots == []


# ────────────────────────────────────────────────────────────────────
# Cohort walker — end-to-end via count_jp_violations / count_us_leakage


def _write(root: Path, country: str, resource: str, records: list[dict]) -> None:
    p = root / country / "fhir_r4" / f"{resource}.ndjson"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


@pytest.mark.unit
def test_count_jp_violations_detects_dosage_text_leak(tmp_path: Path):
    _write(
        tmp_path,
        "jp",
        "MedicationAdministration",
        [
            {
                "resourceType": "MedicationAdministration",
                "id": "ma-1",
                "dosage": {"text": "5.0mg DAILY"},
            },
            {
                "resourceType": "MedicationAdministration",
                "id": "ma-2",
                "dosage": {"text": "5.0mg 1日1回"},
            },
        ],
    )
    counts = count_jp_violations(Cohort.open(tmp_path))
    assert counts == {"MedicationAdministration": {"dosage.text": 1}}


@pytest.mark.unit
def test_count_jp_violations_empty_when_no_jp_country(tmp_path: Path):
    _write(tmp_path, "us", "Observation", [{"resourceType": "Observation", "id": "x"}])
    assert count_jp_violations(Cohort.open(tmp_path)) == {}


@pytest.mark.unit
def test_count_us_leakage_detects_jp_char(tmp_path: Path):
    _write(
        tmp_path,
        "us",
        "Observation",
        [
            {
                "resourceType": "Observation",
                "id": "o1",
                "code": {"text": "White blood cells"},
            },
            {
                "resourceType": "Observation",
                "id": "o2",
                "code": {"text": "白血球数"},
            },
        ],
    )
    counts = count_us_leakage(Cohort.open(tmp_path))
    assert counts == {"Observation": {"code.text": 1}}


# ────────────────────────────────────────────────────────────────────
# Axis entrypoint — cohort-level dispatch (spec=None)


@pytest.mark.unit
def test_run_returns_pass_on_clean_jp_cohort(tmp_path: Path):
    _write(
        tmp_path,
        "jp",
        "Observation",
        [
            {
                "resourceType": "Observation",
                "id": "o1",
                "code": {"text": "白血球数"},
            }
        ],
    )
    result = jp_language.run(None, Cohort.open(tmp_path))
    assert result.status == "PASS"
    assert result.info["jp_violation_total"] == 0


@pytest.mark.unit
def test_run_warns_on_jp_violations(tmp_path: Path):
    _write(
        tmp_path,
        "jp",
        "MedicationAdministration",
        [
            {
                "resourceType": "MedicationAdministration",
                "id": "ma-1",
                "dosage": {"text": "5.0mg DAILY"},
            }
        ],
    )
    result = jp_language.run(None, Cohort.open(tmp_path))
    assert result.status == "WARN"
    assert result.info["jp_violation_total"] == 1
    # WARN message references the total and slot count.
    assert any("1 Latin-only" in f.message for f in result.findings)


@pytest.mark.unit
def test_run_fails_on_us_leakage(tmp_path: Path):
    _write(
        tmp_path,
        "us",
        "Observation",
        [
            {
                "resourceType": "Observation",
                "id": "o1",
                "code": {"text": "白血球数"},
            }
        ],
    )
    result = jp_language.run(None, Cohort.open(tmp_path))
    assert result.status == "FAIL"
    assert result.info["us_leakage_total"] == 1


@pytest.mark.unit
def test_run_ignores_spec(tmp_path: Path):
    # Cohort-level axis ignores ModuleAuditSpec; passing None must work.
    _write(tmp_path, "jp", "Observation", [])
    result = jp_language.run(None, Cohort.open(tmp_path))
    assert result.module == "_cohort_"


@pytest.mark.unit
def test_flat_layout_jp_country_detected_from_patient(tmp_path: Path):
    """Single-country ``clinosim simulate --country JP`` produces a flat
    layout (``<root>/fhir_r4/...``, no ``jp/`` prefix). The axis must
    infer country from Patient.address[0].country."""
    fhir_dir = tmp_path / "fhir_r4"
    fhir_dir.mkdir(parents=True)
    (fhir_dir / "Patient.ndjson").write_text(
        json.dumps({"resourceType": "Patient", "id": "p1", "address": [{"country": "JP"}]}) + "\n"
    )
    (fhir_dir / "MedicationAdministration.ndjson").write_text(
        json.dumps(
            {
                "resourceType": "MedicationAdministration",
                "id": "ma-1",
                "dosage": {"text": "5.0mg DAILY"},
            }
        )
        + "\n"
    )
    violations = count_jp_violations(Cohort.open(tmp_path))
    assert violations == {"MedicationAdministration": {"dosage.text": 1}}, (
        f"flat-layout JP cohort was not walked; got {violations!r}"
    )


@pytest.mark.unit
def test_flat_layout_us_country_detected_from_patient(tmp_path: Path):
    fhir_dir = tmp_path / "fhir_r4"
    fhir_dir.mkdir(parents=True)
    (fhir_dir / "Patient.ndjson").write_text(
        json.dumps({"resourceType": "Patient", "id": "p1", "address": [{"country": "US"}]}) + "\n"
    )
    (fhir_dir / "Observation.ndjson").write_text(
        json.dumps(
            {"resourceType": "Observation", "id": "o1", "code": {"text": "白血球数"}},
            ensure_ascii=False,
        )
        + "\n"
    )
    leaks = count_us_leakage(Cohort.open(tmp_path))
    assert leaks == {"Observation": {"code.text": 1}}, f"flat-layout US cohort was not walked; got {leaks!r}"
