"""Integration: clinosim audit framework discovers + accepts the antibiotic module.

PR-93 follow-up (adversarial review fix): also verifies that the
silent_no_op axis actually consumes the proof (the original PR-93
returned a plain dict that the axis silently skipped without raising
— PR-90 class bug in the audit harness itself).
"""
import pytest

from clinosim.audit.axes.silent_no_op import _check_proof
from clinosim.audit.registry import discover, get_registered
from clinosim.audit.types import AxisResult, Severity


@pytest.mark.integration
def test_antibiotic_module_registered():
    discover()
    assert "antibiotic" in get_registered()


@pytest.mark.integration
def test_antibiotic_proof_factory_returns_equality_checks():
    """The proof factory must return the equality_checks proof format."""
    discover()
    spec = get_registered()["antibiotic"]
    assert spec.lift_firing_proof is not None
    proof = spec.lift_firing_proof()
    assert "equality_checks" in proof, (
        "antibiotic proof must use the equality_checks format (PR-93 fix); "
        "the original dict-of-actuals-and-'expected'-dict format is silently "
        "skipped by the silent_no_op axis"
    )
    # Spot-check PR3b-1 canonical checks
    labels = {label for label, _, _ in proof["equality_checks"]}
    assert "ext_antibiotic_count" in labels
    assert "mar_count" in labels
    assert "mar_first_dt" in labels
    # PR3b-2 antibiogram checks — a broken proof returning [] would silently pass
    # without these assertions (PR-90 class silent no-op gate).
    assert "clabsi_saureus_susceptibility_count" in labels, (
        "PR3b-2 antibiogram count check missing — silent no-op"
    )
    assert "clabsi_saureus_vancomycin_is_S" in labels, (
        "PR3b-2 vancomycin-S check missing — silent no-op"
    )
    assert len(proof["equality_checks"]) == 17, (
        f"Expected 17 equality_checks (8 PR3b-1 + 3 PR3b-2 + 6 PR3b-3 "
        f"narrow chain), got {len(proof['equality_checks'])}"
    )


@pytest.mark.integration
def test_antibiotic_silent_no_op_axis_actually_runs_proof():
    """The silent_no_op axis must CONSUME the proof and report PASS findings.

    PR-93 adversarial review surfaced that the original antibiotic proof
    returned a plain dict the axis silently skipped (apply_fn was None,
    expected was not list-of-tuples). The axis fix recognises the new
    equality_checks format and runs each check.

    This test pins both halves: the axis recognises the format AND each
    equality check passes (closed-form Ceftriaxone q24h × 7d).
    """
    discover()
    spec = get_registered()["antibiotic"]
    result = AxisResult(axis="silent_no_op", module="antibiotic")
    _check_proof(spec, result)
    # No FAIL findings — every equality check must match
    fails = [f for f in result.findings if f.severity == Severity.FAIL]
    assert not fails, f"silent_no_op axis reported FAIL findings: {fails!r}"
    # Each equality_check produces an info entry — ensure non-empty
    eq_info_keys = [k for k in result.info if k.startswith("proof_eq_")]
    assert eq_info_keys, (
        "silent_no_op axis did not consume any equality_checks — "
        "the axis is silently no-op'ing the antibiotic proof"
    )
    # PR3b-2 specific info keys — a broken antibiogram proof returning []
    # would silently pass without these (PR-90 class silent no-op gate).
    assert "proof_eq_clabsi_saureus_susceptibility_count" in result.info, (
        "silent_no_op axis did not surface PR3b-2 count proof"
    )
    assert "proof_eq_clabsi_saureus_vancomycin_is_S" in result.info, (
        "silent_no_op axis did not surface PR3b-2 vancomycin proof"
    )


@pytest.mark.integration
def test_silent_no_op_axis_fails_on_stub_proof():
    """A proof returning neither format must FAIL (audit-harness self-check).

    Prevents PR-93 class regression: a future module that returns a plain
    dict (no apply_fn, no equality_checks) was silently skipped before this
    fix. Now the axis records a FAIL finding.
    """
    from clinosim.audit.registry import ModuleAuditSpec
    stub_spec = ModuleAuditSpec(
        name="stub",
        lift_firing_proof=lambda: {"some_actual": 1, "expected": {"some_actual": 1}},
    )
    result = AxisResult(axis="silent_no_op", module="stub")
    _check_proof(stub_spec, result)
    fails = [f for f in result.findings if f.severity == Severity.FAIL]
    assert any("no-op silent skip" in f.message for f in fails), (
        "axis must FAIL when proof has no recognised format"
    )


@pytest.mark.integration
def test_silent_no_op_axis_fails_on_equality_mismatch():
    """A proof whose equality_checks reports actual != expected must FAIL."""
    from clinosim.audit.registry import ModuleAuditSpec
    bad_spec = ModuleAuditSpec(
        name="bad",
        lift_firing_proof=lambda: {
            "equality_checks": [("count", 0, 1)],   # actual=0, expected=1
        },
    )
    result = AxisResult(axis="silent_no_op", module="bad")
    _check_proof(bad_spec, result)
    fails = [f for f in result.findings if f.severity == Severity.FAIL]
    assert any("equality_check 'count'" in f.message for f in fails)


@pytest.mark.integration
def test_lift_firing_proof_pr3b3_narrow_chain_six_checks_pass() -> None:
    """The combined proof now includes 6 PR3b-3 equality_checks: narrow target,
    each empirical discontinuation_datetime, narrowed regimen count, drug,
    intent. All 6 must pass under synthetic CLABSI/MSSA case."""
    from clinosim.modules.antibiotic.audit import _build_combined_proof

    proof = _build_combined_proof()
    labels = [label for label, _, _ in proof["equality_checks"]]
    pr3b3_labels = [l for l in labels if l.startswith("pr3b3_")]
    assert len(pr3b3_labels) == 6, (
        f"expected 6 pr3b3_* checks, got {len(pr3b3_labels)}: {pr3b3_labels}"
    )
    # Verify each check passes (actual == expected)
    for label, actual, expected in proof["equality_checks"]:
        if label.startswith("pr3b3_"):
            assert actual == expected, (
                f"{label}: actual={actual!r} != expected={expected!r}"
            )


@pytest.mark.integration
def test_clinical_axis_wires_pr3b3_gates_on_empty_cohort() -> None:
    """PR3b-3: smoke-verify clinical axis runs without crashing even with an
    empty cohort. Real population-scale gate firing is covered by the DQR
    (Task 8). This test guarantees the 3 new enforcement blocks (NHSN R-rate,
    empty rate, narrow rate) don't NPE on empty data."""
    import tempfile
    from pathlib import Path

    from clinosim.audit.axes import clinical as clinical_axis
    from clinosim.audit.types import Cohort

    discover()
    spec = get_registered()["antibiotic"]
    with tempfile.TemporaryDirectory() as tmp:
        cohort = Cohort(root=Path(tmp))
        result = clinical_axis.run(spec, cohort)
        # Axis must complete without raising; result is well-formed
        assert isinstance(result.findings, list)
        assert isinstance(result.info, dict)


@pytest.mark.integration
def test_audit_clinical_acceptance_has_narrow_rate_bands() -> None:
    """PR3b-3: narrow_rate_bands key surfaced in clinical_acceptance for
    Task 6 active enforcement."""
    discover()
    spec = get_registered()["antibiotic"]
    bands = spec.clinical_acceptance.get("narrow_rate_bands")
    assert bands is not None
    assert isinstance(bands, list)
    assert len(bands) >= 3  # at least 3 cohort bands
    for band in bands:
        assert "cohort" in band
        assert "expected_narrow_rate_min" in band
        assert "expected_narrow_rate_max" in band
        assert "source" in band


@pytest.mark.integration
def test_clinical_axis_r_rate_gate_filters_per_organism(tmp_path) -> None:
    """D1: R-rate gate cohort must include ONLY encounters whose organism
    matches the band's cohort key.

    Synthetic CLABSI cohort with 35 encounters:
      - 30 with S.aureus (3092008): 15 cefazolin R, 15 cefazolin S → 50% R
      - 5 with S.epidermidis (11638008): all cefazolin R → 100% R (would
        skew the mixed cohort outside the MRSA band).
    The band "clabsi/3092008" (cefazolin 40-55% R) must measure 50%, NOT
    the mixed 57%.
    """
    import json

    from clinosim.audit.axes import clinical as clinical_axis
    from clinosim.audit.types import Cohort
    from clinosim.modules.antibiotic import ANTIBIOTIC_LOINC_LOOKUP

    discover()
    spec = get_registered()["antibiotic"]

    def _w(country: str, file: str, rows: list[dict]) -> None:
        p = tmp_path / country / "fhir_r4" / file
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    cefaz_loinc = ANTIBIOTIC_LOINC_LOOKUP["cefazolin"]

    encounters = [{"resourceType": "Encounter", "id": f"E{i}", "class": {"code": "IMP"}}
                  for i in range(35)]
    conditions = [
        {"resourceType": "Condition", "id": f"c{i}",
         "code": {"coding": [{"code": "T80.211A"}]},  # CLABSI ICD
         "encounter": {"reference": f"Encounter/E{i}"}}
        for i in range(35)
    ]
    organism_obs = []
    susc_obs = []
    for i in range(30):  # S.aureus
        organism_obs.append({
            "resourceType": "Observation", "id": f"mb-org-E{i}-0",
            "encounter": {"reference": f"Encounter/E{i}"},
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{"system": "http://snomed.info/sct", "code": "3092008"}]},
        })
        susc_obs.append({
            "resourceType": "Observation", "id": f"mb-sus-E{i}-0",
            "encounter": {"reference": f"Encounter/E{i}"},
            "code": {"coding": [{"code": cefaz_loinc}]},
            "valueCodeableConcept": {"coding": [{"code": "R" if i < 15 else "S"}]},
        })
    for i in range(30, 35):  # S.epidermidis, all R
        organism_obs.append({
            "resourceType": "Observation", "id": f"mb-org-E{i}-0",
            "encounter": {"reference": f"Encounter/E{i}"},
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{"system": "http://snomed.info/sct", "code": "11638008"}]},
        })
        susc_obs.append({
            "resourceType": "Observation", "id": f"mb-sus-E{i}-0",
            "encounter": {"reference": f"Encounter/E{i}"},
            "code": {"coding": [{"code": cefaz_loinc}]},
            "valueCodeableConcept": {"coding": [{"code": "R"}]},
        })

    _w("us", "Encounter.ndjson", encounters)
    _w("us", "Condition.ndjson", conditions)
    _w("us", "Observation.ndjson", organism_obs + susc_obs)

    result = clinical_axis.run(spec, Cohort.open(tmp_path))
    n = result.info.get("us_clabsi/3092008_cefazolin_n")
    r_rate = result.info.get("us_clabsi/3092008_cefazolin_R_rate")
    assert n == 30, f"S.aureus cohort must be 30, got {n} (per-organism filter not applied)"
    assert r_rate == 0.5, f"S.aureus cohort R-rate must be 0.5, got {r_rate}"
    fails = [f for f in result.findings if f.severity.name == "FAIL"
             and "clabsi/3092008/cefazolin" in f.message]
    assert not fails, f"50% should be inside [0.40, 0.55] band; got FAIL: {fails!r}"


@pytest.mark.integration
def test_clinical_axis_r_rate_gate_zero_for_absent_organism(tmp_path) -> None:
    """D1: a band whose organism appears in NO cohort encounter yields n=0
    (not a spurious FAIL). Cohort = only E.coli CAUTI; verify CLABSI/S.aureus
    band yields n=0 cleanly."""
    import json

    from clinosim.audit.axes import clinical as clinical_axis
    from clinosim.audit.types import Cohort

    discover()
    spec = get_registered()["antibiotic"]

    def _w(country: str, file: str, rows: list[dict]) -> None:
        p = tmp_path / country / "fhir_r4" / file
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    encounters = [{"resourceType": "Encounter", "id": f"E{i}", "class": {"code": "IMP"}}
                  for i in range(10)]
    conditions = [
        {"resourceType": "Condition", "id": f"c{i}",
         "code": {"coding": [{"code": "T83.511A"}]},  # CAUTI ICD only
         "encounter": {"reference": f"Encounter/E{i}"}}
        for i in range(10)
    ]
    # Only E.coli organisms — no S.aureus / S.epidermidis
    organism_obs = [{
        "resourceType": "Observation", "id": f"mb-org-E{i}-0",
        "encounter": {"reference": f"Encounter/E{i}"},
        "code": {"coding": [{"code": "600-7"}]},
        "valueCodeableConcept": {
            "coding": [{"system": "http://snomed.info/sct", "code": "112283007"}]},
    } for i in range(10)]
    _w("us", "Encounter.ndjson", encounters)
    _w("us", "Condition.ndjson", conditions)
    _w("us", "Observation.ndjson", organism_obs)

    result = clinical_axis.run(spec, Cohort.open(tmp_path))
    # CLABSI/S.aureus band should report n=0, no FAIL
    n = result.info.get("us_clabsi/3092008_cefazolin_n")
    assert n == 0
    fails = [f for f in result.findings if f.severity.name == "FAIL"
             and "clabsi/3092008/cefazolin" in f.message]
    assert not fails, f"Absent-organism cohort must not FAIL; got {fails!r}"


@pytest.mark.integration
def test_clinical_axis_empty_rate_gate_excludes_no_panel_organisms(tmp_path) -> None:
    """D2: empty-rate denominator must EXCLUDE encounters whose only culture
    is a no-panel organism (E.faecalis 78065002 / C.albicans 53326005).

    Cohort: 30 panel-eligible CLABSI encounters (S.aureus, all with susc) +
    10 no-panel CLABSI encounters (E.faecalis, never get a S/I/R panel).
    Pre-D2: denominator = 40, empty count = 10, rate = 25% > 5% → FAIL.
    Post-D2: denominator = 30 (panel-eligible only), empty count = 0,
    rate = 0% < 5% → PASS.
    """
    import json

    from clinosim.audit.axes import clinical as clinical_axis
    from clinosim.audit.types import Cohort
    from clinosim.modules.antibiotic import ANTIBIOTIC_LOINC_LOOKUP

    discover()
    spec = get_registered()["antibiotic"]

    def _w(country: str, file: str, rows: list[dict]) -> None:
        p = tmp_path / country / "fhir_r4" / file
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    vanc_loinc = ANTIBIOTIC_LOINC_LOOKUP["vancomycin"]

    encounters = [{"resourceType": "Encounter", "id": f"E{i}", "class": {"code": "IMP"}}
                  for i in range(40)]
    conditions = [
        {"resourceType": "Condition", "id": f"c{i}",
         "code": {"coding": [{"code": "T80.211A"}]},  # CLABSI
         "encounter": {"reference": f"Encounter/E{i}"}}
        for i in range(40)
    ]
    org_obs = []
    susc_obs = []
    # 30 panel-eligible (S.aureus) + susceptibilities → not empty
    for i in range(30):
        org_obs.append({
            "resourceType": "Observation", "id": f"mb-org-E{i}-0",
            "encounter": {"reference": f"Encounter/E{i}"},
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{"system": "http://snomed.info/sct", "code": "3092008"}]},
        })
        susc_obs.append({
            "resourceType": "Observation", "id": f"mb-sus-E{i}-0",
            "encounter": {"reference": f"Encounter/E{i}"},
            "code": {"coding": [{"code": vanc_loinc}]},
            "valueCodeableConcept": {"coding": [{"code": "S"}]},
        })
    # 10 no-panel (E.faecalis) → no susc → would be empty pre-D2
    for i in range(30, 40):
        org_obs.append({
            "resourceType": "Observation", "id": f"mb-org-E{i}-0",
            "encounter": {"reference": f"Encounter/E{i}"},
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{"system": "http://snomed.info/sct", "code": "78065002"}]},
        })
    _w("us", "Encounter.ndjson", encounters)
    _w("us", "Condition.ndjson", conditions)
    _w("us", "Observation.ndjson", org_obs + susc_obs)

    result = clinical_axis.run(spec, Cohort.open(tmp_path))
    total = result.info.get("us_hai_empty_susc_n")
    rate = result.info.get("us_hai_empty_susc_rate")
    assert total == 30, (
        f"panel-eligible denominator must exclude E.faecalis cohort; "
        f"expected 30, got {total}"
    )
    assert rate == 0.0, (
        f"all 30 panel-eligible encounters have S susceptibility, "
        f"empty rate must be 0.0; got {rate}"
    )
    fails = [f for f in result.findings if f.severity.name == "FAIL"
             and "empty-susceptibility" in f.message]
    assert not fails, f"0% empty rate must PASS; got {fails!r}"


@pytest.mark.integration
def test_load_hai_antibiogram_rejects_empty_top_level(monkeypatch) -> None:
    """I2 fix: empty antibiogram top-level must raise ValueError, not
    silently return {} (which would disable D2 panel-eligible filter)."""
    import yaml

    import clinosim.modules.hai as hai_mod

    monkeypatch.setattr(yaml, "safe_load", lambda f: {"hai_antibiogram": {}})
    hai_mod.load_hai_antibiogram.cache_clear()
    try:
        with pytest.raises(ValueError, match="hai_antibiogram.yaml top-level is empty"):
            hai_mod.load_hai_antibiogram()
    finally:
        hai_mod.load_hai_antibiogram.cache_clear()


@pytest.mark.integration
def test_nhsn_resistance_bands_reverse_coverage_complete() -> None:
    """I3 fix: every (hai_type, organism) pair in hai_antibiogram.yaml must
    either be banded by _NHSN_RESISTANCE_BANDS OR explicitly listed in
    _NHSN_REVERSE_COVERAGE_EXEMPT. If a new organism is added to the
    antibiogram without either, _validate_nhsn_resistance_bands must raise."""
    from clinosim.modules.antibiotic.audit import (
        _NHSN_RESISTANCE_BANDS,
        _NHSN_REVERSE_COVERAGE_EXEMPT,
    )
    from clinosim.modules.hai import load_hai_antibiogram

    abg = load_hai_antibiogram()
    banded = {tuple(b["cohort"].split("/", maxsplit=1)) for b in _NHSN_RESISTANCE_BANDS}
    for hai_type, organism_map in abg.items():
        for organism_snomed in organism_map.keys():
            pair = (hai_type, organism_snomed)
            assert pair in banded or pair in _NHSN_REVERSE_COVERAGE_EXEMPT, (
                f"reverse-coverage gap: {pair} has panel but no band and "
                f"no exempt entry. Validator should already raise; this "
                f"test asserts the invariant explicitly for future contributors."
            )


@pytest.mark.integration
def test_clinical_axis_empty_rate_gate_skips_when_all_no_panel(tmp_path) -> None:
    """D2: cohort containing only no-panel organisms → panel_eligible_encs
    is empty → gate skipped cleanly (total=0, no info entry change)."""
    import json

    from clinosim.audit.axes import clinical as clinical_axis
    from clinosim.audit.types import Cohort

    discover()
    spec = get_registered()["antibiotic"]

    def _w(country: str, file: str, rows: list[dict]) -> None:
        p = tmp_path / country / "fhir_r4" / file
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    encounters = [{"resourceType": "Encounter", "id": f"E{i}", "class": {"code": "IMP"}}
                  for i in range(5)]
    conditions = [
        {"resourceType": "Condition", "id": f"c{i}",
         "code": {"coding": [{"code": "T80.211A"}]},
         "encounter": {"reference": f"Encounter/E{i}"}}
        for i in range(5)
    ]
    # All C.albicans (no panel)
    organism_obs = [{
        "resourceType": "Observation", "id": f"mb-org-E{i}-0",
        "encounter": {"reference": f"Encounter/E{i}"},
        "code": {"coding": [{"code": "600-7"}]},
        "valueCodeableConcept": {
            "coding": [{"system": "http://snomed.info/sct", "code": "53326005"}]},
    } for i in range(5)]
    _w("us", "Encounter.ndjson", encounters)
    _w("us", "Condition.ndjson", conditions)
    _w("us", "Observation.ndjson", organism_obs)

    result = clinical_axis.run(spec, Cohort.open(tmp_path))
    total = result.info.get("us_hai_empty_susc_n", -1)
    assert total == 0, f"all-no-panel cohort denominator must be 0, got {total}"
    fails = [f for f in result.findings if f.severity.name == "FAIL"
             and "empty-susceptibility" in f.message]
    assert not fails, f"empty panel-eligible cohort must not FAIL; got {fails!r}"
    # PR3b-3 stage-1 fix I1: total=0 with cohort_enc populated must WARN
    # (signal of antibiogram corruption / mb-org drift / SNOMED URI drift)
    warns = [f for f in result.findings if f.severity.name == "WARN"
             and "panel-eligible cohort empty" in f.message]
    assert warns, (
        "all-no-panel cohort with HAI condition rows must WARN about "
        f"panel-eligible coverage gap; got findings: {result.findings!r}"
    )
