"""silent_no_op axis: the gate that catches PR-90's class of bug.

Three checks, each independently severable so a Module can opt in to
any subset:

1. **Canonical constants cross-check** — for every (yaml_file,
   key_path) in spec.yaml_keys_to_validate, load the YAML and verify
   every key under key_path is in the matching set in
   spec.canonical_constants. ANY drift → FAIL.

2. **Lift-firing proof** — if spec.lift_firing_proof is set, call it
   (zero-arg factory) to build a dict with these keys:
     - record / encounter / state_history / admission_time: positional
       args for apply_fn
     - apply_fn(record, encounter, state_history, admission_time): the
       production code path under test
     - expected: list[tuple[obs, pre_value, expected_delta]] — one
       entry per observation to verify (list-of-tuples instead of a
       dict because OrderResult / SimpleNamespace can be unhashable).
   The engine snapshots pre_value from the tuple, runs apply_fn, then
   asserts (obs.value - pre_value) matches expected_delta within
   per-analyte tolerance (WBC ±2.0, CRP ±0.5). ANY mismatch → FAIL.
   This is the load-bearing verification that would have caught PR-90's
   UPPERCASE/lowercase silent no-op.

3. **Fired counter** — Phase 1 surface: counts Condition emissions
   carrying the codes in spec.canonical_constants["icd_codes"] if set.
   Phase 1 ships HAI without a fired_counter (Module-specific code
   discovery is Phase 2 backlog) — the axis runs the constants +
   proof checks only.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from clinosim.audit.registry import ModuleAuditSpec
from clinosim.audit.types import AuditFinding, AxisResult, Cohort, Severity

# Per-analyte tolerance band for lift-firing proof comparison.
_PROOF_TOLERANCE = {"WBC": 2.0, "CRP": 0.5}
_PROOF_DEFAULT_TOLERANCE = 1.0


def _yaml_keys_at_path(data, path: tuple[str, ...]):
    cur = data
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur if isinstance(cur, dict) else None


def _check_constants(spec: ModuleAuditSpec, result: AxisResult) -> None:
    if not spec.yaml_keys_to_validate:
        return
    canonical_union: set[str] = set()
    for values in spec.canonical_constants.values():
        canonical_union.update(values)
    if not canonical_union:
        return
    for yaml_path, key_path in spec.yaml_keys_to_validate.items():
        p = Path(yaml_path)
        if not p.exists():
            result.findings.append(
                AuditFinding(
                    Severity.FAIL,
                    f"canonical-constants source {yaml_path!r} not found",
                )
            )
            continue
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
        except Exception as e:
            result.findings.append(
                AuditFinding(
                    Severity.FAIL,
                    f"canonical-constants source {yaml_path!r} unparseable: {e}",
                )
            )
            continue
        node = _yaml_keys_at_path(data, key_path)
        if node is None:
            result.findings.append(
                AuditFinding(
                    Severity.FAIL,
                    f"key path {key_path} not found in {yaml_path}",
                )
            )
            continue
        unknown = set(node) - canonical_union
        if unknown:
            result.findings.append(
                AuditFinding(
                    Severity.FAIL,
                    f"canonical-constants drift in {yaml_path}: keys {sorted(unknown)} "
                    f"not in canonical set {sorted(canonical_union)}",
                )
            )
        else:
            result.info[f"constants_pass_{p.name}"] = "ok"


def _check_proof(spec: ModuleAuditSpec, result: AxisResult) -> None:
    if spec.lift_firing_proof is None:
        return
    try:
        proof = spec.lift_firing_proof()
    except Exception as e:
        result.findings.append(
            AuditFinding(
                Severity.FAIL,
                f"lift_firing_proof factory raised: {type(e).__name__}: {e}",
            )
        )
        return

    # Two supported proof formats:
    #
    # 1. **Observation-delta** (Phase 3a HAI lift pattern):
    #    {apply_fn, record, encounter, state_history, admission_time,
    #     expected: list[tuple[obs, pre_value, expected_delta]]}
    #
    # 2. **Equality-check** (PR3b-1 antibiotic pattern, post-fix):
    #    {equality_checks: list[tuple[label, actual, expected]]}
    #    For modules whose verification is structural (Order count, MAR count,
    #    regimen properties) rather than Observation-value delta. The factory
    #    runs the production code path itself, captures actuals, and returns
    #    a label/actual/expected tuple per assertion. Hard equality only —
    #    no tolerance (it's the load-bearing PR-90 gate; mismatches must FAIL).
    #
    # A proof returning NEITHER format silently skips (preserves previous
    # behavior for stubs); the spec.lift_firing_proof being defined but
    # producing no checks is itself an audit failure though, recorded
    # below for visibility.
    apply_fn = proof.get("apply_fn")
    obs_expected = proof.get("expected") or []
    equality_checks = proof.get("equality_checks") or []

    has_obs_format = apply_fn is not None and obs_expected
    has_eq_format = bool(equality_checks)

    if not has_obs_format and not has_eq_format:
        result.findings.append(
            AuditFinding(
                Severity.FAIL,
                "lift_firing_proof returned neither Observation-delta "
                "(apply_fn + expected) nor equality_checks format — proof is a "
                "no-op silent skip (PR-90 class of bug in the audit framework "
                "itself). Producing module: " + spec.name,
            )
        )
        return

    if has_obs_format:
        try:
            apply_fn(
                proof.get("record"),
                proof.get("encounter"),
                proof.get("state_history") or [],
                proof.get("admission_time"),
            )
        except Exception as e:
            result.findings.append(
                AuditFinding(
                    Severity.FAIL,
                    f"lift_firing_proof apply_fn raised: {type(e).__name__}: {e}",
                )
            )
            return
        for obs, pre_value, expected_delta in obs_expected:
            new_value = obs.value
            observed_delta = new_value - pre_value
            analyte = getattr(obs, "lab_name", None)
            tol = _PROOF_TOLERANCE.get(analyte, _PROOF_DEFAULT_TOLERANCE)
            if abs(observed_delta - expected_delta) > tol:
                result.findings.append(
                    AuditFinding(
                        Severity.FAIL,
                        f"lift-firing proof delta mismatch for {analyte}: "
                        f"observed {observed_delta:.2f}, expected {expected_delta:.2f} "
                        f"(tolerance ±{tol})",
                    )
                )
            else:
                result.info[f"proof_{analyte}_delta"] = round(observed_delta, 2)

    if has_eq_format:
        for label, actual, expected in equality_checks:
            if actual != expected:
                result.findings.append(
                    AuditFinding(
                        Severity.FAIL,
                        f"lift-firing equality_check {label!r}: "
                        f"actual={actual!r} != expected={expected!r}",
                    )
                )
            else:
                result.info[f"proof_eq_{label}"] = repr(actual)


def run(spec: ModuleAuditSpec, cohort: Cohort) -> AxisResult:
    result = AxisResult(axis="silent_no_op", module=spec.name)
    _check_constants(spec, result)
    _check_proof(spec, result)
    return result
