"""JP-CLINS lab-Observation self-measurement axis.

Purpose
-------
Measure JP-CLINS ``JP_Observation_LabResult_eCS`` compliance on the
generator side, WITHOUT depending on any external FHIR validator (no
fhirserver, no HAPI). validator error counts alone cannot serve as a
quality metric — the eCS profile uses **Open slicing** on
``Observation.code.coding`` with ``discriminator = system + display``,
so a coding whose ``display`` does not match a slice's ``Fixed value``
is silently accepted as "an unknown extra coding" (only surfaces as an
``information`` OperationOutcome issue, never as error/warning). Whole
classes of coding drift are therefore invisible to pass/fail gating.

This axis reads generated NDJSON directly and derives three
**per-resource** ratios (denominator = Observations, never codings —
per-coding counting biases against resources that carry many codings).

1. **CS 使用率** — fraction of JP lab Observations that reference at
   least one JP-CLINS-defined CodeSystem URI on ``code.coding[*].system``.
2. **Fixed display 一致率** — fraction of Observations whose every
   slice-typed coding (CoreLabo / InfectionLabo / Uncoded) carries the
   eCS SD's Fixed display string. Denominator = Observations that
   emit at least one slice-typed coding; a ``denominator=0``
   (pre-migration baseline) returns ``Outcome.NA`` — NOT FAIL — so
   "no candidates to check" and "candidates exist but all wrong" are
   distinguishable during PR 2..4 diagnostics.
3. **適用規則満足率** — per-Observation rule: MUST carry a
   ``localLaboCode`` slice AND at least one of
   {CoreLabo / InfectionLabo / Uncoded / jlac10LaboCode} slice.

Slice fixed values are extracted from the eCS StructureDefinition and
persisted at ``clinosim/eval/axes/data/jp_clins_lab_slices.json``
(regenerate when the source SD updates).

Applicability
-------------
Axis returns an empty list when the cohort is not JP — this is a JP-only
compliance surface. When called on a JP cohort with zero lab
Observations, each check returns ``Outcome.NA``.

Positive/negative fixture tests in
``tests/unit/test_axis_jp_clins_lab_compliance.py`` are load-bearing:
the axis's whole purpose is to distinguish "measured zero" from "silently
returning zero because the code was broken", so the negative fixtures
must drive the ratios below 100% or the axis itself has silently
failed. Baseline (pre-migration, v29 dataset) must produce ``0/0/0``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from clinosim.audit.types import Cohort
from clinosim.eval.axes.locale import _detect_country_from_cohort
from clinosim.eval.engine import EvalCheck, Outcome, Severity

_DATA_PATH = Path(__file__).resolve().parent / "data" / "jp_clins_lab_slices.json"

# --------------------------------------------------------------------------- #
# JP-CLINS-defined CodeSystem URIs (spec eCS v1.12.0).
# These are the ONLY systems the axis recognizes as "JP-CLINS defined".
# Any other system (e.g. urn:oid:1.2.392.200119.4.1005 JSLM generic OID,
# http://loinc.org, http://medis.or.jp/CodeSystem/master-JLAC10-17digits)
# does NOT count toward the CS 使用率 numerator for JP-CLINS eCS compliance.

_CORELABO_JLAC10_SYSTEM = "http://jpfhir.jp/fhir/clins/CodeSystem/JLAC10/JP_CLINS_ObsLabResult_CoreLabo_CS"
_CORELABO_JLAC11_SYSTEM = "http://jpfhir.jp/fhir/clins/CodeSystem/JLAC11/JP_CLINS_ObsLabResult_CoreLabo_CS"
_INFECTIONLABO_JLAC10_SYSTEM = "http://jpfhir.jp/fhir/clins/CodeSystem/JLAC10/JP_CLINS_ObsLabResult_InfectionLabo_CS"
_INFECTIONLABO_JLAC11_SYSTEM = "http://jpfhir.jp/fhir/clins/CodeSystem/JLAC11/JP_CLINS_ObsLabResult_InfectionLabo_CS"
_LOCALCODE_SYSTEM = "http://jpfhir.jp/fhir/clins/CodeSystem/JP_CLINS_ObsLabResult_LocalCode_CS"
_UNCODED_SYSTEM = "http://jpfhir.jp/fhir/clins/CodeSystem/JP_CLINS_ObsLabResult_Uncoded_CS"
_JLAC10_GENERIC_SYSTEM = "http://medis.or.jp/CodeSystem/master-JLAC10-17digits"

_JP_CLINS_DEFINED_SYSTEMS = frozenset(
    {
        _CORELABO_JLAC10_SYSTEM,
        _CORELABO_JLAC11_SYSTEM,
        _INFECTIONLABO_JLAC10_SYSTEM,
        _INFECTIONLABO_JLAC11_SYSTEM,
        _LOCALCODE_SYSTEM,
        _UNCODED_SYSTEM,
        _JLAC10_GENERIC_SYSTEM,
    }
)

# Systems that carry a per-slice Fixed display constraint (open slicing
# discriminator = system + display). LocalCode and jlac10LaboCode do NOT
# have Fixed displays — they are permitted to carry site-local / analyte
# display text and are therefore excluded from the Fixed display metric.
_FIXED_DISPLAY_SYSTEMS = frozenset(
    {
        _CORELABO_JLAC10_SYSTEM,
        _CORELABO_JLAC11_SYSTEM,
        _INFECTIONLABO_JLAC10_SYSTEM,
        _INFECTIONLABO_JLAC11_SYSTEM,
        _UNCODED_SYSTEM,
    }
)


@lru_cache(maxsize=1)
def _load_slice_map() -> dict[tuple[str, str], str]:
    """Return {(system, display): slice_name} for every slice with a Fixed
    display in the eCS SD. Used to verify Metric 2."""
    raw = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    out: dict[tuple[str, str], str] = {}
    for slice_name, entry in raw["slices"].items():
        sys_uri = entry.get("system")
        display = entry.get("display")
        if sys_uri and display:
            out[(sys_uri, display)] = slice_name
    return out


@lru_cache(maxsize=1)
def _load_fixed_display_by_system() -> dict[str, frozenset[str]]:
    """{system_uri: {valid_display, ...}} — same source as _load_slice_map
    but pivoted for Fixed-display lookup."""
    by_sys: dict[str, set[str]] = {}
    for (sys_uri, display), _ in _load_slice_map().items():
        by_sys.setdefault(sys_uri, set()).add(display)
    return {k: frozenset(v) for k, v in by_sys.items()}


# --------------------------------------------------------------------------- #
# Axis entrypoint


def run(cohort: Cohort, country: str) -> list[EvalCheck]:
    """3-check JP-CLINS lab compliance axis. No-op on non-JP cohorts."""
    if _detect_country_from_cohort(cohort, country) != "JP":
        return []
    lab_obs = list(_iter_lab_observations(cohort, country))
    return [
        _check_cs_usage(lab_obs),
        _check_fixed_display(lab_obs),
        _check_rule_satisfaction(lab_obs),
    ]


# --------------------------------------------------------------------------- #
# Checks


def _check_cs_usage(lab_obs: list[dict]) -> EvalCheck:
    """Metric 1: fraction of lab Observations with any coding.system in
    the JP-CLINS-defined CS set."""
    name = "jp_clins_lab_cs_usage"
    total = len(lab_obs)
    if total == 0:
        return EvalCheck(
            name=name, outcome=Outcome.NA, severity=Severity.MAJOR, message="No JP lab Observations found."
        )
    hits = sum(1 for obs in lab_obs if _any_defined_system(obs))
    ratio = hits / total
    return _ratio_to_check(
        name=name,
        ratio=ratio,
        numerator=hits,
        denominator=total,
        threshold=1.0,
        message_template=(
            "{hits}/{total} lab Observations reference a JP-CLINS-defined CodeSystem "
            "(CoreLabo / InfectionLabo / LocalCode / Uncoded / jlac10 17-digit)"
        ),
    )


def _check_fixed_display(lab_obs: list[dict]) -> EvalCheck:
    """Metric 2: per-resource — fraction of Observations where **every**
    slice-typed coding (CoreLabo / InfectionLabo / Uncoded) carries the
    eCS SD's Fixed display.

    Denominator = Observations that emit at least one slice-typed
    coding. Numerator = subset where all such codings pass display
    check. Per-resource so the three metrics share the same
    per-Observation denominator convention (validator side reported that
    per-issue counting biases against Observations that carry many
    codings — one drift-affected element inflates the issue count by
    the number of codings on that resource).

    ``denominator=0`` returns ``Outcome.NA`` (NOT FAIL, NOT PASS). This
    is load-bearing — during migration two physically distinct states
    must be distinguishable by this axis:

    (a) no Observation emits any slice-typed coding (pre-migration
        baseline)
    (b) some Observations emit slice-typed codings but the display
        mismatches

    Both would collapse to FAIL if 0/0 were treated as ratio=0.0,
    hiding root cause during PR 2..4 diagnostic reads. N/A signals "no
    candidates to check" and forces the reader to verify Metric 1 (CS
    usage) for whether the pipeline is even emitting the slice-typed
    systems.
    """
    name = "jp_clins_lab_fixed_display"
    valid_by_sys = _load_fixed_display_by_system()
    obs_with_slice_typed = 0
    obs_all_correct = 0
    for obs in lab_obs:
        codings = (obs.get("code") or {}).get("coding") or []
        slice_typed = [c for c in codings if (c.get("system") or "") in _FIXED_DISPLAY_SYSTEMS]
        if not slice_typed:
            continue
        obs_with_slice_typed += 1
        all_correct = all(
            (c.get("display") or "") in valid_by_sys.get(c.get("system") or "", frozenset()) for c in slice_typed
        )
        if all_correct:
            obs_all_correct += 1
    if obs_with_slice_typed == 0:
        return EvalCheck(
            name=name,
            outcome=Outcome.NA,
            severity=Severity.MAJOR,
            message=(
                "No Observation emits a Fixed-display slice-typed coding (CoreLabo / InfectionLabo / Uncoded) — "
                "check Metric 1 (CS usage) to see whether the pipeline emits the slice-typed systems at all."
            ),
            detail={"numerator": 0, "denominator": 0},
        )
    ratio = obs_all_correct / obs_with_slice_typed
    return _ratio_to_check(
        name=name,
        ratio=ratio,
        numerator=obs_all_correct,
        denominator=obs_with_slice_typed,
        threshold=1.0,
        message_template=(
            "{hits}/{total} lab Observations have all slice-typed codings carrying the eCS SD Fixed display"
        ),
    )


def _check_rule_satisfaction(lab_obs: list[dict]) -> EvalCheck:
    """Metric 3: per-Observation rule — MUST have a LocalCode slice AND at
    least one of {CoreLabo/InfectionLabo/Uncoded/jlac10LaboCode}."""
    name = "jp_clins_lab_rule_satisfaction"
    total = len(lab_obs)
    if total == 0:
        return EvalCheck(
            name=name, outcome=Outcome.NA, severity=Severity.MAJOR, message="No JP lab Observations found."
        )
    satisfied = sum(1 for obs in lab_obs if _rule_satisfied(obs))
    ratio = satisfied / total
    return _ratio_to_check(
        name=name,
        ratio=ratio,
        numerator=satisfied,
        denominator=total,
        threshold=1.0,
        message_template=(
            "{hits}/{total} lab Observations satisfy the eCS applicability rule "
            "(LocalCode + one of CoreLabo/InfectionLabo/Uncoded/jlac10LaboCode)"
        ),
    )


# --------------------------------------------------------------------------- #
# Predicates


def _any_defined_system(obs: dict) -> bool:
    for coding in (obs.get("code") or {}).get("coding") or []:
        if (coding.get("system") or "") in _JP_CLINS_DEFINED_SYSTEMS:
            return True
    return False


def _rule_satisfied(obs: dict) -> bool:
    has_local = False
    has_typed = False
    for coding in (obs.get("code") or {}).get("coding") or []:
        sys_uri = coding.get("system") or ""
        if sys_uri == _LOCALCODE_SYSTEM:
            has_local = True
        elif sys_uri in _JP_CLINS_DEFINED_SYSTEMS and sys_uri != _LOCALCODE_SYSTEM:
            has_typed = True
    return has_local and has_typed


_ECS_LABRESULT_PROFILE = "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Observation_LabResult_eCS"


def _declares_ecs_labresult(row: dict) -> bool:
    """The axis's population is Observations that declare the JP-CLINS
    eCS profile — the same denominator the fhirserver validator uses
    when checking eCS conformance. Microbiology (mb-org-* / mb-sus-*)
    is excluded upstream by ``fhir_r4_adapter._is_lab_observation``
    because JP-CLINS scope prose puts culture / susceptibility outside
    the profile. Selecting by ``meta.profile`` — not by
    ``category=laboratory`` — keeps the axis's denominator identical
    to the validator's, so migration-time drift is comparable directly."""
    for prof in (row.get("meta") or {}).get("profile") or []:
        if prof == _ECS_LABRESULT_PROFILE:
            return True
    return False


def _iter_lab_observations(cohort: Cohort, country: str):
    from clinosim.eval.axes.locale import _read

    for row in _read(cohort, country, "Observation"):
        if _declares_ecs_labresult(row):
            yield row


# --------------------------------------------------------------------------- #
# Helpers


def _ratio_to_check(
    *,
    name: str,
    ratio: float,
    numerator: int,
    denominator: int,
    threshold: float,
    message_template: str,
) -> EvalCheck:
    """Build an EvalCheck. threshold=1.0 (strict) is the JP-CLINS target
    per the user's directive (no middle threshold: middle thresholds
    freeze drift as normal). Below-threshold → FAIL, at-threshold → PASS.

    Zero-denominator handling belongs to the caller — different metrics
    have different semantics (Metric 1/3: 0 lab Observations → NA;
    Metric 2: 0 slice-typed codings → NA, see ``_check_fixed_display``).
    This helper assumes denominator > 0.
    """
    detail = {"numerator": numerator, "denominator": denominator, "ratio": ratio}
    outcome = Outcome.PASS if ratio >= threshold else Outcome.FAIL
    return EvalCheck(
        name=name,
        outcome=outcome,
        severity=Severity.MAJOR,
        message=(message_template + f" — {ratio:.1%}").format(hits=numerator, total=denominator),
        detail=detail,
    )
