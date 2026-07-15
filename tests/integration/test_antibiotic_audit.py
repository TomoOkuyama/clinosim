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
    assert "clabsi_saureus_susceptibility_count" in labels, "PR3b-2 antibiogram count check missing — silent no-op"
    assert "clabsi_saureus_vancomycin_is_S" in labels, "PR3b-2 vancomycin-S check missing — silent no-op"
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
        "silent_no_op axis did not consume any equality_checks — the axis is silently no-op'ing the antibiotic proof"
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
    assert any("no-op silent skip" in f.message for f in fails), "axis must FAIL when proof has no recognised format"


@pytest.mark.integration
def test_silent_no_op_axis_fails_on_equality_mismatch():
    """A proof whose equality_checks reports actual != expected must FAIL."""
    from clinosim.audit.registry import ModuleAuditSpec

    bad_spec = ModuleAuditSpec(
        name="bad",
        lift_firing_proof=lambda: {
            "equality_checks": [("count", 0, 1)],  # actual=0, expected=1
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
    assert len(pr3b3_labels) == 6, f"expected 6 pr3b3_* checks, got {len(pr3b3_labels)}: {pr3b3_labels}"
    # Verify each check passes (actual == expected)
    for label, actual, expected in proof["equality_checks"]:
        if label.startswith("pr3b3_"):
            assert actual == expected, f"{label}: actual={actual!r} != expected={expected!r}"


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


def _write_obs_with_specimen(
    enc: str,
    spec_suffix: str,
    organism_snomed: str,
    abx_loinc: str,
    interpretation: str,
    hai_event_id: str = "",
) -> list[dict]:
    """Build a triple (Specimen, mb-org-*, mb-sus-*) wired with the same
    specimen reference, optionally with HAI identifier."""
    from clinosim.modules.output._fhir_microbiology import HAI_EVENT_ID_SYSTEM

    spec_id = f"spec-{enc}-{spec_suffix}"
    rows: list[dict] = []
    spec: dict = {"resourceType": "Specimen", "id": spec_id}
    org_obs: dict = {
        "resourceType": "Observation",
        "id": f"mb-org-{enc}-{spec_suffix}",
        "encounter": {"reference": f"Encounter/{enc}"},
        "specimen": {"reference": f"Specimen/{spec_id}"},
        "code": {"coding": [{"code": "600-7"}]},
        "valueCodeableConcept": {
            "coding": [{"system": "http://snomed.info/sct", "code": organism_snomed}],
        },
    }
    sus_obs: dict = {
        "resourceType": "Observation",
        "id": f"mb-sus-{enc}-{spec_suffix}-0",
        "encounter": {"reference": f"Encounter/{enc}"},
        "specimen": {"reference": f"Specimen/{spec_id}"},
        "code": {"coding": [{"code": abx_loinc}]},
        "valueCodeableConcept": {"coding": [{"code": interpretation}]},
    }
    if hai_event_id:
        ident = [{"system": HAI_EVENT_ID_SYSTEM, "value": hai_event_id}]
        spec["identifier"] = ident
        org_obs["identifier"] = ident
        sus_obs["identifier"] = ident
    rows.append(spec)
    rows.append(org_obs)
    rows.append(sus_obs)
    return rows


@pytest.mark.integration
def test_clinical_axis_r_rate_gate_no_double_count_multi_organism_encounter(
    tmp_path,
) -> None:
    """C1 resolution: CLABSI encounter with 2 specimens (S.aureus +
    S.epidermidis HAI), each with its own cefazolin susc. The S.aureus
    band counts ONLY the S.aureus-specimen susc (not the S.epidermidis-
    specimen susc). PR3b-3 encounter-level join double-counted;
    PR3b-5 specimen-based join attributes correctly."""
    import json

    from clinosim.audit.axes import clinical as clinical_axis
    from clinosim.audit.types import Cohort
    from clinosim.modules.antibiotic import ANTIBIOTIC_LOINC_LOOKUP

    discover()
    spec = get_registered()["antibiotic"]

    def _w(file: str, rows: list[dict]) -> None:
        p = tmp_path / "us" / "fhir_r4" / file
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    cefaz = ANTIBIOTIC_LOINC_LOOKUP["cefazolin"]
    enc_rows: list[dict] = []
    cond_rows: list[dict] = []
    obs_rows: list[dict] = []
    for i in range(30):
        eid = f"E{i}"
        enc_rows.append({"resourceType": "Encounter", "id": eid, "class": {"code": "IMP"}})
        cond_rows.append(
            {
                "resourceType": "Condition",
                "id": f"c{i}",
                "code": {"coding": [{"code": "T80.211A"}]},
                "encounter": {"reference": f"Encounter/{eid}"},
            }
        )
        # S.aureus specimen — cefazolin R (HAI)
        obs_rows.extend(
            _write_obs_with_specimen(
                eid,
                "0",
                organism_snomed="3092008",
                abx_loinc=cefaz,
                interpretation="R",
                hai_event_id=f"hai-{eid}-sa",
            )
        )
        # S.epidermidis specimen — cefazolin S (HAI, but would inflate
        # S.aureus band under encounter-level join)
        obs_rows.extend(
            _write_obs_with_specimen(
                eid,
                "1",
                organism_snomed="60875001",
                abx_loinc=cefaz,
                interpretation="S",
                hai_event_id=f"hai-{eid}-se",
            )
        )
    _w("Encounter.ndjson", enc_rows)
    _w("Condition.ndjson", cond_rows)
    _w("Observation.ndjson", obs_rows)

    result = clinical_axis.run(spec, Cohort.open(tmp_path))
    n = result.info.get("us_clabsi/3092008_cefazolin_n")
    r_rate = result.info.get("us_clabsi/3092008_cefazolin_R_rate")
    # PR3b-5: 30 S.aureus-specimen susc, all R → rate = 1.0, n = 30.
    # (S.epidermidis-specimen susc NOT counted under S.aureus band.)
    assert n == 30, (
        f"S.aureus band cohort must be 30 (S.aureus specimens only); "
        f"got {n}. Pre-PR3b-5 encounter-level join would yield 60."
    )
    assert r_rate == 1.0, (
        f"S.aureus band R-rate must be 1.0 (true per-specimen rate); "
        f"got {r_rate}. Pre-PR3b-5 would yield 0.5 (false, mixed)."
    )


@pytest.mark.integration
def test_clinical_axis_d1_warn_when_hai_specimens_empty(tmp_path) -> None:
    """pr117-adv-1 Agent 2 MAJOR-1: D1 symmetric WARN guard. When HAI
    cohort encounters exist (Condition rows with HAI ICD) but the
    HAI specimen set is empty (writer-side identifier emit regression /
    HAI_EVENT_ID_SYSTEM drift), the gate must WARN. Mirrors D2 I1 from
    PR #114."""
    import json

    from clinosim.audit.axes import clinical as clinical_axis
    from clinosim.audit.types import Cohort

    discover()
    spec = get_registered()["antibiotic"]

    def _w(file: str, rows: list[dict]) -> None:
        p = tmp_path / "us" / "fhir_r4" / file
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    # HAI cohort encounters present (Condition rows) but NO mb-org-*
    # with HAI identifier → hai_specimens empty
    _w("Encounter.ndjson", [{"resourceType": "Encounter", "id": f"E{i}", "class": {"code": "IMP"}} for i in range(5)])
    _w(
        "Condition.ndjson",
        [
            {
                "resourceType": "Condition",
                "id": f"c{i}",
                "code": {"coding": [{"code": "T80.211A"}]},
                "encounter": {"reference": f"Encounter/E{i}"},
            }
            for i in range(5)
        ],
    )
    # mb-org-* present but NO HAI identifier (regression scenario)
    _w(
        "Observation.ndjson",
        [
            {
                "resourceType": "Observation",
                "id": f"mb-org-E{i}-0",
                "encounter": {"reference": f"Encounter/E{i}"},
                "specimen": {"reference": f"Specimen/spec-E{i}-0"},
                "code": {"coding": [{"code": "600-7"}]},
                "valueCodeableConcept": {"coding": [{"system": "http://snomed.info/sct", "code": "3092008"}]},
            }
            for i in range(5)
        ],
    )

    result = clinical_axis.run(spec, Cohort.open(tmp_path))
    warns = [f for f in result.findings if f.severity.name == "WARN" and "HAI specimen set empty" in f.message]
    assert warns, (
        f"D1 must WARN when HAI Conditions exist but HAI_EVENT_ID_SYSTEM "
        f"identifier emit is missing; got {result.findings!r}"
    )


@pytest.mark.integration
def test_clinical_axis_r_rate_gate_compound_multi_organism_plus_community(
    tmp_path,
) -> None:
    """pr117-adv-1 Agent 3 LOW: compound C1+C2 case. CLABSI encounter
    with 3 specimens (HAI S.aureus + HAI S.epidermidis + community
    S.aureus). Only the HAI S.aureus specimen counts under the S.aureus
    band: HAI S.epidermidis correctly attributed to its own (unbanded)
    organism via specimen→organism map; community S.aureus excluded by
    HAI-only filter."""
    import json

    from clinosim.audit.axes import clinical as clinical_axis
    from clinosim.audit.types import Cohort
    from clinosim.modules.antibiotic import ANTIBIOTIC_LOINC_LOOKUP

    discover()
    spec = get_registered()["antibiotic"]

    def _w(file: str, rows: list[dict]) -> None:
        p = tmp_path / "us" / "fhir_r4" / file
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    cefaz = ANTIBIOTIC_LOINC_LOOKUP["cefazolin"]
    enc_rows: list[dict] = []
    cond_rows: list[dict] = []
    obs_rows: list[dict] = []
    for i in range(30):
        eid = f"E{i}"
        enc_rows.append({"resourceType": "Encounter", "id": eid, "class": {"code": "IMP"}})
        cond_rows.append(
            {
                "resourceType": "Condition",
                "id": f"c{i}",
                "code": {"coding": [{"code": "T80.211A"}]},
                "encounter": {"reference": f"Encounter/{eid}"},
            }
        )
        # HAI S.aureus — cefazolin R (true HAI MRSA)
        obs_rows.extend(
            _write_obs_with_specimen(
                eid,
                "0",
                organism_snomed="3092008",
                abx_loinc=cefaz,
                interpretation="R",
                hai_event_id=f"hai-{eid}-sa",
            )
        )
        # HAI S.epidermidis — cefazolin S (other HAI organism, not banded)
        obs_rows.extend(
            _write_obs_with_specimen(
                eid,
                "1",
                organism_snomed="60875001",
                abx_loinc=cefaz,
                interpretation="S",
                hai_event_id=f"hai-{eid}-se",
            )
        )
        # Community S.aureus — cefazolin S (would inflate S.aureus band
        # pre-PR3b-5; HAI-only filter excludes)
        obs_rows.extend(
            _write_obs_with_specimen(
                eid,
                "2",
                organism_snomed="3092008",
                abx_loinc=cefaz,
                interpretation="S",
                hai_event_id="",
            )
        )
    _w("Encounter.ndjson", enc_rows)
    _w("Condition.ndjson", cond_rows)
    _w("Observation.ndjson", obs_rows)

    result = clinical_axis.run(spec, Cohort.open(tmp_path))
    n = result.info.get("us_clabsi/3092008_cefazolin_n")
    r_rate = result.info.get("us_clabsi/3092008_cefazolin_R_rate")
    # PR3b-5: ONLY the 30 HAI S.aureus specimens count. n=30, R-rate=1.0
    # (S.epidermidis HAI rejected by organism match; community S.aureus
    # rejected by HAI-only filter.)
    assert n == 30, (
        f"compound scenario must yield n=30 (HAI S.aureus only); got {n}. "
        f"Pre-PR3b-5 encounter-level join would yield 90 (mixed)."
    )
    assert r_rate == 1.0, (
        f"compound scenario R-rate must be 1.0; got {r_rate}. Pre-PR3b-5 would yield ~0.33 (1 R + 2 S of 3)."
    )


@pytest.mark.integration
def test_clinical_axis_r_rate_gate_excludes_community_culture(tmp_path) -> None:
    """C2 resolution: CLABSI encounter with HAI S.aureus specimen + community
    S.aureus specimen (no HAI identifier). The S.aureus band must NOT count
    the community S.aureus susc — same organism but different specimen
    + different provenance (community). PR3b-5 HAI-only filter excludes
    community specimens entirely."""
    import json

    from clinosim.audit.axes import clinical as clinical_axis
    from clinosim.audit.types import Cohort
    from clinosim.modules.antibiotic import ANTIBIOTIC_LOINC_LOOKUP

    discover()
    spec = get_registered()["antibiotic"]

    def _w(file: str, rows: list[dict]) -> None:
        p = tmp_path / "us" / "fhir_r4" / file
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    cefaz = ANTIBIOTIC_LOINC_LOOKUP["cefazolin"]
    enc_rows: list[dict] = []
    cond_rows: list[dict] = []
    obs_rows: list[dict] = []
    for i in range(30):
        eid = f"E{i}"
        enc_rows.append({"resourceType": "Encounter", "id": eid, "class": {"code": "IMP"}})
        cond_rows.append(
            {
                "resourceType": "Condition",
                "id": f"c{i}",
                "code": {"coding": [{"code": "T80.211A"}]},
                "encounter": {"reference": f"Encounter/{eid}"},
            }
        )
        # HAI S.aureus specimen — cefazolin R (true HAI MRSA)
        obs_rows.extend(
            _write_obs_with_specimen(
                eid,
                "0",
                organism_snomed="3092008",
                abx_loinc=cefaz,
                interpretation="R",
                hai_event_id=f"hai-{eid}-sa",
            )
        )
        # Community S.aureus specimen — cefazolin S (would inflate via
        # encounter-level join in pre-PR3b-5; same organism but no HAI marker)
        obs_rows.extend(
            _write_obs_with_specimen(
                eid,
                "1",
                organism_snomed="3092008",
                abx_loinc=cefaz,
                interpretation="S",
                hai_event_id="",  # community
            )
        )
    _w("Encounter.ndjson", enc_rows)
    _w("Condition.ndjson", cond_rows)
    _w("Observation.ndjson", obs_rows)

    result = clinical_axis.run(spec, Cohort.open(tmp_path))
    n = result.info.get("us_clabsi/3092008_cefazolin_n")
    r_rate = result.info.get("us_clabsi/3092008_cefazolin_R_rate")
    # PR3b-5: only HAI-derived S.aureus specimens count. 30 HAI S.aureus
    # specimens, all R → rate = 1.0, n = 30. (Community S.aureus excluded.)
    assert n == 30, (
        f"HAI-only filter must exclude community specimens; got n={n}. "
        f"Pre-PR3b-5 would yield 60 (HAI + community mixed)."
    )
    assert r_rate == 1.0, (
        f"HAI-only R-rate must be 1.0 (pure HAI); got {r_rate}. Pre-PR3b-5 would yield 0.5 (HAI + community mixed)."
    )


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

    encounters = [{"resourceType": "Encounter", "id": f"E{i}", "class": {"code": "IMP"}} for i in range(35)]
    conditions = [
        {
            "resourceType": "Condition",
            "id": f"c{i}",
            "code": {"coding": [{"code": "T80.211A"}]},  # CLABSI ICD
            "encounter": {"reference": f"Encounter/E{i}"},
        }
        for i in range(35)
    ]
    # PR3b-5: include specimen.reference + HAI identifier on both
    # mb-org-* and mb-sus-* so the specimen-based join + HAI-only filter
    # finds these. (Pre-PR3b-5 the gate joined via encounter ref alone.)
    from clinosim.modules.output._fhir_microbiology import HAI_EVENT_ID_SYSTEM

    organism_obs = []
    susc_obs = []
    for i in range(30):  # S.aureus HAI
        spec_id = f"spec-E{i}-0"
        ident = [{"system": HAI_EVENT_ID_SYSTEM, "value": f"hai-{i}-sa"}]
        organism_obs.append(
            {
                "resourceType": "Observation",
                "id": f"mb-org-E{i}-0",
                "encounter": {"reference": f"Encounter/E{i}"},
                "specimen": {"reference": f"Specimen/{spec_id}"},
                "code": {"coding": [{"code": "600-7"}]},
                "valueCodeableConcept": {"coding": [{"system": "http://snomed.info/sct", "code": "3092008"}]},
                "identifier": ident,
            }
        )
        susc_obs.append(
            {
                "resourceType": "Observation",
                "id": f"mb-sus-E{i}-0",
                "encounter": {"reference": f"Encounter/E{i}"},
                "specimen": {"reference": f"Specimen/{spec_id}"},
                "code": {"coding": [{"code": cefaz_loinc}]},
                "valueCodeableConcept": {"coding": [{"code": "R" if i < 15 else "S"}]},
                "identifier": ident,
            }
        )
    for i in range(30, 35):  # S.epidermidis HAI, all R
        spec_id = f"spec-E{i}-0"
        ident = [{"system": HAI_EVENT_ID_SYSTEM, "value": f"hai-{i}-se"}]
        organism_obs.append(
            {
                "resourceType": "Observation",
                "id": f"mb-org-E{i}-0",
                "encounter": {"reference": f"Encounter/E{i}"},
                "specimen": {"reference": f"Specimen/{spec_id}"},
                "code": {"coding": [{"code": "600-7"}]},
                "valueCodeableConcept": {"coding": [{"system": "http://snomed.info/sct", "code": "11638008"}]},
                "identifier": ident,
            }
        )
        susc_obs.append(
            {
                "resourceType": "Observation",
                "id": f"mb-sus-E{i}-0",
                "encounter": {"reference": f"Encounter/E{i}"},
                "specimen": {"reference": f"Specimen/{spec_id}"},
                "code": {"coding": [{"code": cefaz_loinc}]},
                "valueCodeableConcept": {"coding": [{"code": "R"}]},
                "identifier": ident,
            }
        )

    _w("us", "Encounter.ndjson", encounters)
    _w("us", "Condition.ndjson", conditions)
    _w("us", "Observation.ndjson", organism_obs + susc_obs)

    result = clinical_axis.run(spec, Cohort.open(tmp_path))
    n = result.info.get("us_clabsi/3092008_cefazolin_n")
    r_rate = result.info.get("us_clabsi/3092008_cefazolin_R_rate")
    assert n == 30, f"S.aureus cohort must be 30, got {n} (per-organism filter not applied)"
    assert r_rate == 0.5, f"S.aureus cohort R-rate must be 0.5, got {r_rate}"
    fails = [f for f in result.findings if f.severity.name == "FAIL" and "clabsi/3092008/cefazolin" in f.message]
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

    encounters = [{"resourceType": "Encounter", "id": f"E{i}", "class": {"code": "IMP"}} for i in range(10)]
    conditions = [
        {
            "resourceType": "Condition",
            "id": f"c{i}",
            "code": {"coding": [{"code": "T83.511A"}]},  # CAUTI ICD only
            "encounter": {"reference": f"Encounter/E{i}"},
        }
        for i in range(10)
    ]
    # Only E.coli organisms — no S.aureus / S.epidermidis
    organism_obs = [
        {
            "resourceType": "Observation",
            "id": f"mb-org-E{i}-0",
            "encounter": {"reference": f"Encounter/E{i}"},
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {"coding": [{"system": "http://snomed.info/sct", "code": "112283007"}]},
        }
        for i in range(10)
    ]
    _w("us", "Encounter.ndjson", encounters)
    _w("us", "Condition.ndjson", conditions)
    _w("us", "Observation.ndjson", organism_obs)

    result = clinical_axis.run(spec, Cohort.open(tmp_path))
    # CLABSI/S.aureus band should report n=0, no FAIL
    n = result.info.get("us_clabsi/3092008_cefazolin_n")
    assert n == 0
    fails = [f for f in result.findings if f.severity.name == "FAIL" and "clabsi/3092008/cefazolin" in f.message]
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

    encounters = [{"resourceType": "Encounter", "id": f"E{i}", "class": {"code": "IMP"}} for i in range(40)]
    conditions = [
        {
            "resourceType": "Condition",
            "id": f"c{i}",
            "code": {"coding": [{"code": "T80.211A"}]},  # CLABSI
            "encounter": {"reference": f"Encounter/E{i}"},
        }
        for i in range(40)
    ]
    org_obs = []
    susc_obs = []
    # 30 panel-eligible (S.aureus) + susceptibilities → not empty
    for i in range(30):
        org_obs.append(
            {
                "resourceType": "Observation",
                "id": f"mb-org-E{i}-0",
                "encounter": {"reference": f"Encounter/E{i}"},
                "code": {"coding": [{"code": "600-7"}]},
                "valueCodeableConcept": {"coding": [{"system": "http://snomed.info/sct", "code": "3092008"}]},
            }
        )
        susc_obs.append(
            {
                "resourceType": "Observation",
                "id": f"mb-sus-E{i}-0",
                "encounter": {"reference": f"Encounter/E{i}"},
                "code": {"coding": [{"code": vanc_loinc}]},
                "valueCodeableConcept": {"coding": [{"code": "S"}]},
            }
        )
    # 10 no-panel (E.faecalis) → no susc → would be empty pre-D2
    for i in range(30, 40):
        org_obs.append(
            {
                "resourceType": "Observation",
                "id": f"mb-org-E{i}-0",
                "encounter": {"reference": f"Encounter/E{i}"},
                "code": {"coding": [{"code": "600-7"}]},
                "valueCodeableConcept": {"coding": [{"system": "http://snomed.info/sct", "code": "78065002"}]},
            }
        )
    _w("us", "Encounter.ndjson", encounters)
    _w("us", "Condition.ndjson", conditions)
    _w("us", "Observation.ndjson", org_obs + susc_obs)

    result = clinical_axis.run(spec, Cohort.open(tmp_path))
    total = result.info.get("us_hai_empty_susc_n")
    rate = result.info.get("us_hai_empty_susc_rate")
    assert total == 30, f"panel-eligible denominator must exclude E.faecalis cohort; expected 30, got {total}"
    assert rate == 0.0, f"all 30 panel-eligible encounters have S susceptibility, empty rate must be 0.0; got {rate}"
    fails = [f for f in result.findings if f.severity.name == "FAIL" and "empty-susceptibility" in f.message]
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
def test_load_hai_antibiogram_rejects_empty_per_hai_type_bucket(monkeypatch) -> None:
    """pr112-adv-2 Agent 2 HIGH: per-hai_type bucket empty is same silent-no-op
    class as I2 top-level empty. `{hai_antibiogram: {clabsi: {}}}` would
    silently disable _panel_eligible_organisms for clabsi."""
    import yaml

    import clinosim.modules.hai as hai_mod

    monkeypatch.setattr(yaml, "safe_load", lambda f: {"hai_antibiogram": {"clabsi": {}}})
    hai_mod.load_hai_antibiogram.cache_clear()
    try:
        with pytest.raises(ValueError, match="'clabsi' bucket empty"):
            hai_mod.load_hai_antibiogram()
    finally:
        hai_mod.load_hai_antibiogram.cache_clear()


@pytest.mark.integration
def test_validators_run_before_register_audit_module() -> None:
    """pr112-adv-2 Agent 1 CRITICAL: all canonical-constants / reverse-coverage
    validators must run BEFORE register_audit_module so a band-shape failure
    prevents stale spec from registering. Re-import the module and confirm
    the spec is fully registered (validators succeeded) AND the module-level
    invocation order is correct."""
    import inspect

    import clinosim.modules.antibiotic.audit as A
    from clinosim.audit.registry import get_registered

    src = inspect.getsource(A)
    register_idx = src.index("register_audit_module(")
    val1_idx = src.rindex("_validate_narrow_rate_bands()")
    val2_idx = src.rindex("_validate_nhsn_resistance_bands()")
    val3_idx = src.rindex("_validate_narrow_ladder_at_import()")
    assert val1_idx < register_idx, "_validate_narrow_rate_bands() must run before register"
    assert val2_idx < register_idx, "_validate_nhsn_resistance_bands() must run before register"
    assert val3_idx < register_idx, "_validate_narrow_ladder_at_import() must run before register"

    # Spec is registered (validators passed)
    assert "antibiotic" in get_registered()


@pytest.mark.integration
def test_nhsn_reverse_coverage_exempt_no_stale_entries() -> None:
    """pr112-adv-2 Agent 2 MED: every entry in _NHSN_REVERSE_COVERAGE_EXEMPT
    must correspond to a present (hai_type, organism) pair in
    hai_antibiogram.yaml — staleness defense. _validate_nhsn_resistance_bands
    raises on stale entries; this test asserts the invariant explicitly."""
    from clinosim.modules.antibiotic.audit import _NHSN_REVERSE_COVERAGE_EXEMPT
    from clinosim.modules.hai import load_hai_antibiogram

    abg = load_hai_antibiogram()
    antibiogram_pairs = {(ht, o) for ht, om in abg.items() for o in om.keys()}
    for pair in _NHSN_REVERSE_COVERAGE_EXEMPT:
        assert pair in antibiogram_pairs, (
            f"stale _NHSN_REVERSE_COVERAGE_EXEMPT entry {pair!r} — not in "
            f"hai_antibiogram.yaml. Validator should already raise; this "
            f"test pins the invariant explicitly."
        )


@pytest.mark.integration
def test_fhir_microbiology_emits_hai_event_id_identifier() -> None:
    """PR3b-5 Task 1: MicrobiologyResult.hai_event_id non-empty → FHIR
    Specimen / mb-org-* Observation / mb-sus-* Observation /
    DiagnosticReport all carry identifier[].system == HAI_EVENT_ID_SYSTEM
    with value == hai_event_id. Empty hai_event_id → no identifier field
    (byte-identical to pre-PR3b-5 community-culture output)."""
    from clinosim.modules.output._fhir_common import BundleContext
    from clinosim.modules.output._fhir_microbiology import (
        HAI_EVENT_ID_SYSTEM,
        _bb_microbiology,
    )

    # HAI culture: hai_event_id set
    hai_mb = {
        "specimen": "blood",
        "specimen_snomed": "119297000",
        "test_loinc": "600-7",
        "collected_datetime": "2026-01-10T08:00:00",
        "reported_datetime": "2026-01-12T08:00:00",
        "growth": True,
        "organism_snomed": "3092008",
        "susceptibilities": [
            {"antibiotic_loinc": "10-9", "interpretation": "S"},
        ],
        "hai_event_id": "hai-clabsi-E1-1",
    }
    # Community culture: hai_event_id empty
    comm_mb = {
        "specimen": "urine",
        "specimen_snomed": "122575003",
        "test_loinc": "630-4",
        "collected_datetime": "2026-01-10T08:00:00",
        "reported_datetime": "2026-01-12T08:00:00",
        "growth": True,
        "organism_snomed": "112283007",
        "susceptibilities": [],
        "hai_event_id": "",
    }
    ctx = BundleContext(
        record={"microbiology": [hai_mb, comm_mb]},
        country="US",
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="p1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        primary_enc_id="E1",
        patient_sex="",
    )
    resources = _bb_microbiology(ctx)

    spec_hai = next(r for r in resources if r["resourceType"] == "Specimen" and r["id"] == "spec-E1-0")
    spec_comm = next(r for r in resources if r["resourceType"] == "Specimen" and r["id"] == "spec-E1-1")
    org_hai = next(r for r in resources if r["id"] == "mb-org-E1-0")
    org_comm = next(r for r in resources if r["id"] == "mb-org-E1-1")
    sus_hai = next(r for r in resources if r["id"] == "mb-sus-E1-0-0")
    dr_hai = next(r for r in resources if r["id"] == "dr-mb-E1-0")
    dr_comm = next(r for r in resources if r["id"] == "dr-mb-E1-1")

    # HAI side: identifier present, system + value correct
    for res in (spec_hai, org_hai, sus_hai, dr_hai):
        ident = res.get("identifier") or []
        assert len(ident) == 1, f"{res['id']}: expected 1 identifier, got {ident}"
        assert ident[0]["system"] == HAI_EVENT_ID_SYSTEM, f"{res['id']}: identifier.system mismatch"
        assert ident[0]["value"] == "hai-clabsi-E1-1", f"{res['id']}: identifier.value mismatch"

    # Community side: no identifier field at all (byte-identical pre-PR3b-5)
    for res in (spec_comm, org_comm, dr_comm):
        assert "identifier" not in res, (
            f"{res['id']}: community culture must NOT emit identifier "
            f"(byte-identical invariant), got {res.get('identifier')!r}"
        )


@pytest.mark.integration
def test_narrow_rate_bands_forward_coverage_complete() -> None:
    """pr112-adv-3 Agent 2 MEDIUM: _NARROW_RATE_BANDS must cover every
    HAI_TYPES entry — sibling pattern to _NHSN_RESISTANCE_BANDS reverse-
    coverage from adv-1 I3. Adding a new HAI_TYPE without a corresponding
    _NARROW_RATE_BANDS entry would silently no-op the narrow rate gate for
    that hai_type (silent-no-op defense layer 4 forward-coverage)."""
    from clinosim.modules.antibiotic.audit import _NARROW_RATE_BANDS
    from clinosim.modules.hai import HAI_TYPES

    banded_hai_types = {b["cohort"] for b in _NARROW_RATE_BANDS}
    missing = set(HAI_TYPES) - banded_hai_types
    assert not missing, (
        f"_NARROW_RATE_BANDS forward-coverage gap: HAI_TYPES {sorted(missing)!r} "
        f"have no narrow rate band. Validator should already raise; this test "
        f"asserts the invariant explicitly for future contributors."
    )


@pytest.mark.integration
def test_abx_order_id_canonical_constant() -> None:
    """pr112-adv-2 F3 fix: ABX_ORDER_ID_PREFIX shared between writer (enricher)
    and reader (audit clinical.py). A rename in engine.py triggers ImportError
    downstream instead of a silent gate skip — same defense pattern as C4."""
    from clinosim.audit.axes import clinical as clinical_axis
    from clinosim.modules.antibiotic.engine import (
        ABX_NARROW_SUFFIX,
        ABX_ORDER_ID_PREFIX,
        ABX_ORDER_REQ_PREFIX,
        ABX_REGIMEN_ID_PREFIX,
    )

    assert ABX_REGIMEN_ID_PREFIX == "abx-"
    assert ABX_ORDER_REQ_PREFIX == "req-"
    assert ABX_ORDER_ID_PREFIX == "req-abx-"
    assert ABX_NARROW_SUFFIX == "-narrowed"
    # The audit gate imports the same constants — proving the coupling
    assert clinical_axis.ABX_ORDER_ID_PREFIX is ABX_ORDER_ID_PREFIX
    assert clinical_axis.ABX_NARROW_SUFFIX is ABX_NARROW_SUFFIX


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

    encounters = [{"resourceType": "Encounter", "id": f"E{i}", "class": {"code": "IMP"}} for i in range(5)]
    conditions = [
        {
            "resourceType": "Condition",
            "id": f"c{i}",
            "code": {"coding": [{"code": "T80.211A"}]},
            "encounter": {"reference": f"Encounter/E{i}"},
        }
        for i in range(5)
    ]
    # All C.albicans (no panel)
    organism_obs = [
        {
            "resourceType": "Observation",
            "id": f"mb-org-E{i}-0",
            "encounter": {"reference": f"Encounter/E{i}"},
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {"coding": [{"system": "http://snomed.info/sct", "code": "53326005"}]},
        }
        for i in range(5)
    ]
    _w("us", "Encounter.ndjson", encounters)
    _w("us", "Condition.ndjson", conditions)
    _w("us", "Observation.ndjson", organism_obs)

    result = clinical_axis.run(spec, Cohort.open(tmp_path))
    total = result.info.get("us_hai_empty_susc_n", -1)
    assert total == 0, f"all-no-panel cohort denominator must be 0, got {total}"
    fails = [f for f in result.findings if f.severity.name == "FAIL" and "empty-susceptibility" in f.message]
    assert not fails, f"empty panel-eligible cohort must not FAIL; got {fails!r}"
    # PR3b-3 stage-1 fix I1: total=0 with cohort_enc populated must WARN
    # (signal of antibiogram corruption / mb-org drift / SNOMED URI drift)
    warns = [f for f in result.findings if f.severity.name == "WARN" and "panel-eligible cohort empty" in f.message]
    assert warns, (
        "all-no-panel cohort with HAI condition rows must WARN about "
        f"panel-eligible coverage gap; got findings: {result.findings!r}"
    )
