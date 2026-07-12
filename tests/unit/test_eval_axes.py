"""P1-8 (session 46) — clinosim eval unit tests.

Exercises the three axes against synthetic mini-cohorts written straight
to a temp dir: no `clinosim generate` is invoked (that's what the
end-to-end integration test does). Each mini-cohort is a handful of
NDJSON rows crafted to isolate a single check outcome.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.eval.engine import (
    EvalAxisResult,
    EvalCheck,
    EvalEngine,
    EvalReport,
    Outcome,
    Severity,
)


def _write_ndjson(dir_: Path, resource_type: str, rows: list[dict]) -> None:
    (dir_ / "fhir_r4").mkdir(parents=True, exist_ok=True)
    with (dir_ / "fhir_r4" / f"{resource_type}.ndjson").open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


# --------------------------------------------------------------------------- #
# Score arithmetic

@pytest.mark.unit
def test_axis_score_all_pass_is_100() -> None:
    axis = EvalAxisResult(axis="x", country="US", checks=[
        EvalCheck(name="a", outcome=Outcome.PASS, severity=Severity.CRITICAL, message=""),
        EvalCheck(name="b", outcome=Outcome.PASS, severity=Severity.MAJOR, message=""),
        EvalCheck(name="c", outcome=Outcome.PASS, severity=Severity.MINOR, message=""),
    ])
    assert axis.score == 100.0
    assert axis.status == "PASS"


@pytest.mark.unit
def test_axis_score_all_fail_is_0() -> None:
    axis = EvalAxisResult(axis="x", country="US", checks=[
        EvalCheck(name="a", outcome=Outcome.FAIL, severity=Severity.CRITICAL, message=""),
        EvalCheck(name="b", outcome=Outcome.FAIL, severity=Severity.MAJOR, message=""),
    ])
    assert axis.score == 0.0
    assert axis.status == "FAIL"


@pytest.mark.unit
def test_warn_counts_as_half_pass() -> None:
    axis = EvalAxisResult(axis="x", country="US", checks=[
        EvalCheck(name="a", outcome=Outcome.WARN, severity=Severity.MAJOR, message=""),
    ])
    assert axis.score == 50.0
    assert axis.status == "WARN"


@pytest.mark.unit
def test_severity_weighting_favours_critical_passes() -> None:
    # critical=3, major=2, minor=1 — one FAIL on the critical dominates.
    axis = EvalAxisResult(axis="x", country="US", checks=[
        EvalCheck(name="crit", outcome=Outcome.FAIL, severity=Severity.CRITICAL, message=""),
        EvalCheck(name="min",  outcome=Outcome.PASS, severity=Severity.MINOR,   message=""),
    ])
    # weight: critical fail = 0/3, minor pass = 1/1. total = 4. pass_weight = 1.
    assert axis.score == pytest.approx(25.0, abs=0.1)


# --------------------------------------------------------------------------- #
# Structural axis

@pytest.mark.unit
def test_structural_detects_duplicate_ids(tmp_path: Path) -> None:
    _write_ndjson(tmp_path, "Patient", [
        {"resourceType": "Patient", "id": "p1", "identifier": [{"value": "x"}]},
        {"resourceType": "Patient", "id": "p1", "identifier": [{"value": "y"}]},
    ])
    from clinosim.audit.types import Cohort
    from clinosim.eval.axes import structural
    checks = structural.run(Cohort.open(tmp_path), "")
    dup = next(c for c in checks if c.name == "resource_id_uniqueness")
    assert dup.outcome is Outcome.FAIL


@pytest.mark.unit
def test_structural_dangling_reference(tmp_path: Path) -> None:
    _write_ndjson(tmp_path, "Patient", [
        {"resourceType": "Patient", "id": "p1", "identifier": [{"value": "x"}]},
    ])
    _write_ndjson(tmp_path, "Condition", [
        {"resourceType": "Condition", "id": "c1",
         "subject": {"reference": "Patient/p9-does-not-exist"}},
    ])
    from clinosim.audit.types import Cohort
    from clinosim.eval.axes import structural
    checks = structural.run(Cohort.open(tmp_path), "")
    ref = next(c for c in checks if c.name == "reference_integrity")
    assert ref.outcome is Outcome.FAIL


@pytest.mark.unit
def test_structural_resource_type_consistency_detects_mismatch(tmp_path: Path) -> None:
    _write_ndjson(tmp_path, "Patient", [
        {"resourceType": "Observation", "id": "wrong-type"},  # deliberate
    ])
    from clinosim.audit.types import Cohort
    from clinosim.eval.axes import structural
    checks = structural.run(Cohort.open(tmp_path), "")
    rt = next(c for c in checks if c.name == "resource_type_consistency")
    assert rt.outcome is Outcome.FAIL


# --------------------------------------------------------------------------- #
# Clinical axis

@pytest.mark.unit
def test_clinical_flags_impossible_lab_value(tmp_path: Path) -> None:
    _write_ndjson(tmp_path, "Observation", [
        {"resourceType": "Observation", "id": "obs1",
         "category": [{"coding": [{"code": "laboratory"}]}],
         "code": {"coding": [{"system": "http://loinc.org", "code": "6690-2"}]},
         "valueQuantity": {"value": 10000, "unit": "10^9/L"}},  # WBC 10k = impossible
    ])
    from clinosim.audit.types import Cohort
    from clinosim.eval.axes import clinical
    checks = clinical.run(Cohort.open(tmp_path), "")
    lab = next(c for c in checks if c.name == "lab_values_physiological_range")
    assert lab.outcome is Outcome.FAIL


@pytest.mark.unit
def test_clinical_medication_before_birth_is_flagged(tmp_path: Path) -> None:
    _write_ndjson(tmp_path, "Patient", [
        {"resourceType": "Patient", "id": "p1", "identifier": [{"value": "x"}],
         "birthDate": "2026-05-01"},
    ])
    _write_ndjson(tmp_path, "MedicationRequest", [
        {"resourceType": "MedicationRequest", "id": "m1",
         "subject": {"reference": "Patient/p1"},
         "authoredOn": "2026-01-15"},  # BEFORE birth
    ])
    from clinosim.audit.types import Cohort
    from clinosim.eval.axes import clinical
    checks = clinical.run(Cohort.open(tmp_path), "")
    med = next(c for c in checks if c.name == "medication_date_sanity")
    assert med.outcome is Outcome.FAIL


@pytest.mark.unit
def test_clinical_reversed_encounter_period_is_flagged(tmp_path: Path) -> None:
    _write_ndjson(tmp_path, "Encounter", [
        {"resourceType": "Encounter", "id": "e1", "status": "finished",
         "period": {"start": "2026-05-01", "end": "2026-04-15"}},  # reversed
    ])
    from clinosim.audit.types import Cohort
    from clinosim.eval.axes import clinical
    checks = clinical.run(Cohort.open(tmp_path), "")
    period = next(c for c in checks if c.name == "encounter_temporal_ordering")
    assert period.outcome is Outcome.FAIL


# --------------------------------------------------------------------------- #
# Locale axis

@pytest.mark.unit
def test_locale_flags_english_leak_on_jp_condition_display(tmp_path: Path) -> None:
    _write_ndjson(tmp_path, "Patient", [
        {"resourceType": "Patient", "id": "p1", "identifier": [{"value": "x"}],
         "address": [{"country": "JP"}]},
    ])
    _write_ndjson(tmp_path, "Condition", [
        {"resourceType": "Condition", "id": "c1",
         "subject": {"reference": "Patient/p1"},
         "code": {"text": "Type 2 diabetes",  # English on a JP cohort
                  "coding": [{"code": "E11", "display": "Type 2 diabetes"}]}},
    ])
    from clinosim.audit.types import Cohort
    from clinosim.eval.axes import locale
    checks = locale.run(Cohort.open(tmp_path), "")
    disp = next(c for c in checks if c.name == "japanese_displays_on_condition")
    assert disp.outcome is Outcome.FAIL


@pytest.mark.unit
def test_locale_us_no_japanese_leakage(tmp_path: Path) -> None:
    _write_ndjson(tmp_path, "Patient", [
        {"resourceType": "Patient", "id": "p1", "identifier": [{"value": "x"}],
         "address": [{"country": "US"}]},
    ])
    _write_ndjson(tmp_path, "Condition", [
        {"resourceType": "Condition", "id": "c1",
         "subject": {"reference": "Patient/p1"},
         "code": {"coding": [{"code": "E11", "display": "2型糖尿病"}]}},  # JP leaks into US
    ])
    from clinosim.audit.types import Cohort
    from clinosim.eval.axes import locale
    checks = locale.run(Cohort.open(tmp_path), "")
    leak = next(c for c in checks if c.name == "no_japanese_leakage")
    assert leak.outcome is Outcome.FAIL


@pytest.mark.unit
def test_locale_detects_jp_from_flat_cohort_via_address(tmp_path: Path) -> None:
    """The country auto-detection must pick JP when the flat cohort's first
    Patient address.country is JP."""
    _write_ndjson(tmp_path, "Patient", [
        {"resourceType": "Patient", "id": "p1", "identifier": [{"value": "x"}],
         "address": [{"country": "JP"}]},
    ])
    from clinosim.audit.types import Cohort
    from clinosim.eval.axes.locale import _detect_country_from_cohort
    assert _detect_country_from_cohort(Cohort.open(tmp_path), "") == "JP"


# --------------------------------------------------------------------------- #
# Report shape

@pytest.mark.unit
def test_report_serialises_json_round_trip(tmp_path: Path) -> None:
    _write_ndjson(tmp_path, "Patient", [
        {"resourceType": "Patient", "id": "p1", "identifier": [{"value": "x"}]},
    ])
    engine = EvalEngine(tmp_path)
    report = engine.run()

    from clinosim.eval.report import render_json
    d = json.loads(render_json(report))
    assert d["eval_version"]
    assert d["overall_score"] >= 0
    assert isinstance(d["axes"], list)
    assert all("score" in a for a in d["axes"])


@pytest.mark.unit
def test_report_markdown_contains_headers(tmp_path: Path) -> None:
    _write_ndjson(tmp_path, "Patient", [
        {"resourceType": "Patient", "id": "p1", "identifier": [{"value": "x"}]},
    ])
    from clinosim.eval.report import render_markdown
    engine = EvalEngine(tmp_path)
    md = render_markdown(engine.run())
    assert md.startswith("# clinosim eval report")
    assert "Overall score" in md
    assert "Axis: structural" in md
    assert "Axis: clinical" in md
    assert "Axis: locale" in md


@pytest.mark.unit
def test_engine_raises_on_empty_cohort(tmp_path: Path) -> None:
    engine = EvalEngine(tmp_path / "nonexistent")
    with pytest.raises(FileNotFoundError):
        engine.run()
