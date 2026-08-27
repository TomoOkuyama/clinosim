"""Intentional regression test for the JP-CLINS lab compliance CI gate.

This test is the safety net for the gate itself. It simulates the failure
mode the gate exists to catch — a lab analyte reaching the FHIR emit path
without a LocalCode co-slice — and asserts the gate goes red.

Design rationale (Session 69 supervisor review, Issue #410):

The gate catches "a new lab analyte was added but its JP-CLINS wiring
was forgotten." The most common shape of that failure is a missing
LocalCode coding on the Observation: the eCS applicability rule
(``jp_clins_lab_rule_satisfaction``) requires **LocalCode AND at least
one typed coding** (CoreLabo / InfectionLabo / Uncoded /
jlac10LaboCode) on every ``JP_Observation_LabResult_eCS`` row.
Dropping the LocalCode on a single analyte is the most direct way to
prove the gate fires; simulating "code_mapping mis-wired to a fake
JLAC10 code" would be silently absorbed by the Uncoded strategy
fallback (Uncoded is itself a JP-CLINS-defined system), so the gate
would stay green on that variant. See the session-69 supervisor
message for the full failure-mode taxonomy.

Coverage note (gate limits, explicitly recorded):

The ``jp_clins_lab_cs_usage`` metric alone cannot catch the LocalCode
regression because a CoreLabo-only Observation still satisfies
"references a JP-CLINS-defined CodeSystem" (CoreLabo IS one of the
defined systems). The rule_satisfaction metric is what carries the
detection. If a future story requires a stricter cs_usage that
requires LocalCode presence, the fix belongs in the axis definition —
not in a workaround here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# URIs used by the axis under test — read them from the axis module so
# the fixture stays in lockstep with the eval's constants.
from clinosim.eval.axes.jp_clins_lab_compliance import (
    _ECS_LABRESULT_PROFILE,
    _LOCALCODE_SYSTEM,
)
from clinosim.eval.engine import EvalEngine, Outcome
from clinosim.modules.output.fhir_r4.demographics.patient import resolve_patient_id

# CoreLabo JLAC10 slice URI (one of the "typed" codings) — pinned as a
# literal here (not imported) because we deliberately want the axis to
# see this coding when we hand-craft the fixture; if the axis renames
# its constant, the test *should* fail loud to force a review of the
# fixture rather than silently follow the rename.
_JLAC10_CORELABO_SYSTEM = "http://jpfhir.jp/fhir/clins/CodeSystem/JLAC10/JP_CLINS_ObsLabResult_CoreLabo_CS"


def _lab_observation(
    *,
    obs_id: str,
    analyte_local_code: str,
    analyte_local_display: str,
    corelabo_code: str,
    corelabo_display: str,
    include_localcode: bool,
) -> dict:
    """Build one JP-CLINS-shaped lab Observation.

    When ``include_localcode`` is False, the LocalCode slice is omitted
    — this is the exact failure mode the CI gate must catch.
    """
    codings: list[dict] = []
    if include_localcode:
        codings.append(
            {
                "system": _LOCALCODE_SYSTEM,
                "code": analyte_local_code,
                "display": analyte_local_display,
            }
        )
    codings.append(
        {
            "system": _JLAC10_CORELABO_SYSTEM,
            "code": corelabo_code,
            "display": corelabo_display,
        }
    )
    return {
        "resourceType": "Observation",
        "id": obs_id,
        "meta": {"profile": [_ECS_LABRESULT_PROFILE]},
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "laboratory",
                    }
                ]
            }
        ],
        "code": {"coding": codings, "text": analyte_local_display},
        "subject": {"reference": f"Patient/{resolve_patient_id('p1')}"},
    }


def _write_cohort(root: Path, observations: list[dict]) -> None:
    """Write a minimal JP flat-layout cohort.

    A Patient with ``address.country == "JP"`` is required — the axis
    peeks at it to switch on the JP-CLINS checks (see
    ``clinosim.eval.axes.locale._detect_country_from_cohort``).
    """
    fhir_dir = root / "fhir_r4"
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
    with (fhir_dir / "Observation.ndjson").open("w") as f:
        for obs in observations:
            f.write(json.dumps(obs) + "\n")


@pytest.mark.unit
def test_gate_fires_on_localcode_omission(tmp_path: Path) -> None:
    """LocalCode co-slice omission on 1 analyte MUST turn rule_satisfaction red.

    Four Observations carry both LocalCode + CoreLabo (satisfied). One
    Observation carries only CoreLabo (unsatisfied). The rule requires
    LocalCode AND at least one typed coding, so the ratio drops to 4/5
    and the axis fails the threshold=1.0 gate.
    """
    obs = [
        _lab_observation(
            obs_id=f"lab-{i}",
            analyte_local_code=f"WBC-{i}",
            analyte_local_display="白血球数",
            corelabo_code="2A0100000019101",
            corelabo_display="末梢血液一般 白血球数 血液 計数値 (/μL)",
            include_localcode=True,
        )
        for i in range(4)
    ]
    obs.append(
        _lab_observation(
            obs_id="lab-broken",
            analyte_local_code="RBC-broken",
            analyte_local_display="赤血球数",
            corelabo_code="2A0200000019101",
            corelabo_display="末梢血液一般 赤血球数 血液 計数値 (10^6/μL)",
            include_localcode=False,  # <- the intentional regression
        )
    )
    _write_cohort(tmp_path, obs)

    engine = EvalEngine(cohort_dir=tmp_path, only_axes=["jp_clins_lab_compliance"])
    report = engine.run()

    # Extract the rule_satisfaction check from the single-axis report.
    axes = [a for a in report.axes if a.axis == "jp_clins_lab_compliance"]
    assert len(axes) == 1, f"expected single axis, got {[a.axis for a in report.axes]}"
    checks = {c.name: c for c in axes[0].checks}
    rule = checks["jp_clins_lab_rule_satisfaction"]

    # Primary assertion: the gate goes red on the exact failure mode.
    assert rule.outcome is Outcome.FAIL, (
        f"gate did not fire on LocalCode omission: outcome={rule.outcome!r}, message={rule.message!r}"
    )
    # Ratio must reflect 4/5 satisfaction (the regression is one row).
    assert "4/5" in rule.message, f"expected 4/5 numerator in message, got: {rule.message!r}"
    # Overall report status must also be FAIL — this is what --strict
    # reads to decide the exit code, and what the CI gate ultimately
    # keys off.
    assert report.overall_status == "FAIL"


@pytest.mark.unit
def test_baseline_rule_satisfaction_is_green_when_analytes_wired(
    tmp_path: Path,
) -> None:
    """Baseline for the regression: LocalCode + CoreLabo → rule PASS.

    Pins the fixture's own correctness so a fixture bug can't masquerade
    as a "gate regression" — if this baseline fails, the test data
    itself has drifted from what the axis expects, not the emit path.

    Scope note: only ``rule_satisfaction`` and ``cs_usage`` are
    asserted here. ``fixed_display`` compares the coding's display to
    the eCS SD's Fixed-value table (loaded from the runtime JP-CLINS
    pkg); reproducing an SD-Fixed-value-matching display in unit-scope
    hand-crafted data would require duplicating the pkg's display
    table into the test, which drifts. The end-to-end pkg-fetch step
    of the CI workflow exercises ``fixed_display`` on real emitted
    output — that is the intended coverage for that metric.
    """
    obs = [
        _lab_observation(
            obs_id=f"lab-{i}",
            analyte_local_code=f"WBC-{i}",
            analyte_local_display="白血球数",
            corelabo_code="2A0100000019101",
            corelabo_display="末梢血液一般 白血球数 血液 計数値 (/μL)",
            include_localcode=True,
        )
        for i in range(5)
    ]
    _write_cohort(tmp_path, obs)

    engine = EvalEngine(cohort_dir=tmp_path, only_axes=["jp_clins_lab_compliance"])
    report = engine.run()

    checks = {c.name: c for c in next(a for a in report.axes if a.axis == "jp_clins_lab_compliance").checks}
    for metric_name in (
        "jp_clins_lab_cs_usage",
        "jp_clins_lab_rule_satisfaction",
    ):
        assert checks[metric_name].outcome is Outcome.PASS, (
            f"{metric_name} unexpectedly {checks[metric_name].outcome!r}: {checks[metric_name].message!r}"
        )


@pytest.mark.unit
def test_localcode_omission_does_not_break_cs_usage(tmp_path: Path) -> None:
    """Explicit record of a gate limit: cs_usage does NOT detect this failure.

    ``jp_clins_lab_cs_usage`` counts Observations that reference *any*
    JP-CLINS-defined CodeSystem. CoreLabo alone satisfies that; the
    LocalCode-omission case still has a CoreLabo coding, so cs_usage
    stays 100%. This is why the gate must include rule_satisfaction —
    cs_usage alone would let the regression through silently. Recording
    the limit here prevents future maintainers from "simplifying" the
    gate to cs_usage only.
    """
    obs = [
        _lab_observation(
            obs_id="lab-broken",
            analyte_local_code="X-1",
            analyte_local_display="X",
            corelabo_code="2A0100000019101",
            corelabo_display="末梢血液一般 白血球数 血液 計数値 (/μL)",
            include_localcode=False,
        )
    ]
    _write_cohort(tmp_path, obs)

    engine = EvalEngine(cohort_dir=tmp_path, only_axes=["jp_clins_lab_compliance"])
    report = engine.run()

    checks = {c.name: c for c in next(a for a in report.axes if a.axis == "jp_clins_lab_compliance").checks}
    # cs_usage misses this failure mode — record it.
    assert checks["jp_clins_lab_cs_usage"].outcome is Outcome.PASS
    # rule_satisfaction catches it — this is what carries the gate.
    assert checks["jp_clins_lab_rule_satisfaction"].outcome is Outcome.FAIL
