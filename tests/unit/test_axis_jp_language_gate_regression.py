"""Intentional-regression tests for the jp_language axis (Issue #473).

Design (from Issue #473 §5 — same shape as the ``jp_clins_lab_compliance``
gate regression test in ``test_axis_jp_clins_lab_compliance_gate_regression.py``):

The axis's job is DETECTION — proving it fires when a JP-side field
regresses to English. The three tests below pin the axis's contract
at the fixture level (small, hand-crafted cohort with a specific
residue) so that a future "refactor" cannot silently regress the
detection.

- Test 1 (main): N-1 rows in Japanese, 1 row Latin-only → the axis
  MUST detect ≥1 violation on the leaked slot. Directly proves the
  scan works when a real regression happens.
- Test 2 (baseline): all N rows in Japanese → the axis MUST report
  zero violations. Pins the FIXTURE's own correctness so that a
  fixture-authoring bug cannot masquerade as a "gate regression".
- Test 3 (dual-slot boundary): coding[].display uses SNOMED "Oral"
  while code.text is Japanese → the axis MUST NOT flag the display.
  Pins the dual-slot rule (session 67: display=EN canonical, text=JP)
  so a future change that starts scanning canonical CS displays would
  fail loud.

Tests 1 and 3 are BOTH required. Together they fix the dual-slot rule
in code: test 1 pins "text must be JP", test 3 pins "display stays
EN". Test 1 alone would allow "let's also demand display be JP"; test
3 alone would allow "let's not scan text either".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.audit.axes.jp_language import (
    count_jp_violations,
    count_us_leakage,
    run,
)
from clinosim.audit.types import Cohort, Severity

# SNOMED CT — an English canonical CS whose display is EN by design.
_SNOMED_URI = "http://snomed.info/sct"


def _medication_administration(*, ma_id: str, dosage_text: str) -> dict:
    """Build one MedicationAdministration with a single dosage.text.

    ``dosage.text`` is the highest-volume violation slot documented in
    Issue #473 (13,372 / 13,372 pre-fix). Using it here mirrors the
    real leakage shape.
    """
    return {
        "resourceType": "MedicationAdministration",
        "id": ma_id,
        "status": "completed",
        "medicationCodeableConcept": {
            "coding": [
                {
                    "system": _SNOMED_URI,
                    "code": "421925002",
                    "display": "Oral",  # EN canonical — must NOT trip axis
                }
            ],
            "text": "セファゾリン",  # JP
        },
        "subject": {"reference": "Patient/p1"},
        "dosage": {
            "text": dosage_text,
            "route": {
                "coding": [
                    {
                        "system": _SNOMED_URI,
                        "code": "26643006",
                        "display": "Oral",  # EN canonical
                    }
                ],
                "text": "経口",  # JP
            },
        },
    }


def _write_jp_cohort(root: Path, records: list[dict]) -> None:
    fhir_dir = root / "jp" / "fhir_r4"
    fhir_dir.mkdir(parents=True, exist_ok=True)
    with (fhir_dir / "Patient.ndjson").open("w") as f:
        f.write(
            json.dumps(
                {
                    "resourceType": "Patient",
                    "id": "p1",
                    "address": [{"country": "JP"}],
                }
            )
            + "\n"
        )
    with (fhir_dir / "MedicationAdministration.ndjson").open("w") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ────────────────────────────────────────────────────────────────────
# Test 1 (main): axis detects when one row regresses to English


@pytest.mark.unit
def test_axis_fires_on_single_dosage_text_regression(tmp_path: Path) -> None:
    """N-1 rows in Japanese + 1 row Latin-only → axis detects the residue.

    If this test fails, the axis has lost the detection contract that
    Issue #473 established — every JP-side ``.text`` field must be
    scanned for Latin-only regressions.
    """
    records = [_medication_administration(ma_id=f"ma-{i}", dosage_text="5.0mg 1日1回") for i in range(4)]
    records.append(_medication_administration(ma_id="ma-broken", dosage_text="5.0mg DAILY"))
    _write_jp_cohort(tmp_path, records)

    # Direct scan — proves detection independent of WARN/FAIL gating.
    violations = count_jp_violations(Cohort.open(tmp_path))
    assert violations == {"MedicationAdministration": {"dosage.text": 1}}, (
        f"expected 1 violation on dosage.text, got {violations!r}"
    )

    # And the axis surfaces it as WARN (visibility) — pinning the
    # rollout gating so it can be promoted to FAIL later via
    # LOCKED_SLOTS without breaking this test.
    result = run(None, Cohort.open(tmp_path))
    assert result.status in {"WARN", "FAIL"}, f"axis must report a finding on this fixture, got {result.status!r}"
    assert any(f.severity in {Severity.WARN, Severity.FAIL} for f in result.findings), (
        f"expected WARN/FAIL finding, got: {[(f.severity, f.message) for f in result.findings]}"
    )


# ────────────────────────────────────────────────────────────────────
# Test 2 (baseline): axis PASSes when all rows are properly localized


@pytest.mark.unit
def test_axis_passes_on_fully_localized_baseline(tmp_path: Path) -> None:
    """All N rows in Japanese → axis reports zero violations, status PASS.

    This pins the FIXTURE's own correctness. If this baseline fails
    while test 1 also fails, the fixture itself has drifted and any
    inference about the axis's behavior from test 1 alone is unsound.
    """
    records = [_medication_administration(ma_id=f"ma-{i}", dosage_text="5.0mg 1日1回") for i in range(5)]
    _write_jp_cohort(tmp_path, records)

    violations = count_jp_violations(Cohort.open(tmp_path))
    assert violations == {}, f"baseline must have zero JP violations, got {violations!r}"

    result = run(None, Cohort.open(tmp_path))
    assert result.status == "PASS", (
        f"baseline must be PASS, got {result.status!r}; findings={[(f.severity, f.message) for f in result.findings]}"
    )


# ────────────────────────────────────────────────────────────────────
# Test 3 (dual-slot boundary): SNOMED display stays EN, axis ignores it


@pytest.mark.unit
def test_axis_does_not_flag_snomed_display(tmp_path: Path) -> None:
    """SNOMED ``coding[].display = 'Oral'`` MUST NOT trigger the axis.

    Session 67 dual-slot rule: ``coding.display`` is the English
    canonical value (from the terminology's own text), while
    ``code.text`` carries the JP-facing text. If this test fails, a
    future change has broken the boundary — likely by scanning ALL
    ``.display`` fields regardless of the coding's system. That would
    force every LOINC / SNOMED / RxNorm display to be re-translated,
    which is out of scope for this axis and would corrupt US output
    (where those displays are also EN).

    The fixture is deliberately shaped like test 1 — same JP text on
    every field EXCEPT the SNOMED display, which stays English. The
    only difference from test 2 is that test 3 exercises the display
    boundary explicitly (test 2 has it too but proves nothing about
    it).
    """
    records = [_medication_administration(ma_id=f"ma-{i}", dosage_text="5.0mg 1日1回") for i in range(3)]
    _write_jp_cohort(tmp_path, records)

    # Sanity: every record has SNOMED 'Oral' displays. Confirm the
    # cohort actually has them (guards against a fixture typo).
    with (tmp_path / "jp" / "fhir_r4" / "MedicationAdministration.ndjson").open() as f:
        loaded = [json.loads(line) for line in f if line.strip()]
    assert all(c.get("display") == "Oral" for rec in loaded for c in rec["medicationCodeableConcept"]["coding"]), (
        "fixture must carry SNOMED 'Oral' displays for the boundary test"
    )

    violations = count_jp_violations(Cohort.open(tmp_path))
    assert violations == {}, (
        f"SNOMED display 'Oral' MUST NOT trigger the axis (dual-slot boundary broken), got {violations!r}"
    )


# ────────────────────────────────────────────────────────────────────
# Test 4 (US side): axis FAILs on JP leakage in US output


@pytest.mark.unit
def test_axis_fails_on_us_side_jp_leakage(tmp_path: Path) -> None:
    """A single JP character in US ``.text`` MUST FAIL the axis.

    Complements the JP-side rollout: US leakage is a real defect (JP
    text should never appear in a US export), so the axis gates it as
    FAIL immediately without a segmented rollout.
    """
    us_dir = tmp_path / "us" / "fhir_r4"
    us_dir.mkdir(parents=True, exist_ok=True)
    with (us_dir / "Patient.ndjson").open("w") as f:
        f.write(json.dumps({"resourceType": "Patient", "id": "p1", "address": [{"country": "US"}]}) + "\n")
    with (us_dir / "Observation.ndjson").open("w") as f:
        f.write(
            json.dumps(
                {
                    "resourceType": "Observation",
                    "id": "o1",
                    "code": {"text": "White blood cells"},
                }
            )
            + "\n"
        )
        f.write(
            json.dumps(
                {
                    "resourceType": "Observation",
                    "id": "o2",
                    "code": {"text": "白血球数"},  # leakage
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    leaks = count_us_leakage(Cohort.open(tmp_path))
    assert leaks == {"Observation": {"code.text": 1}}, f"expected 1 US leakage on Observation.code.text, got {leaks!r}"

    result = run(None, Cohort.open(tmp_path))
    assert result.status == "FAIL", f"US leakage must FAIL (not WARN), got {result.status!r}"
    assert any(f.severity == Severity.FAIL for f in result.findings), (
        f"expected FAIL finding, got: {[(f.severity, f.message) for f in result.findings]}"
    )
