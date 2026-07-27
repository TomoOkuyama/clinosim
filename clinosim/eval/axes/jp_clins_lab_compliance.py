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

Slice fixed values are extracted **at runtime** from an installed JP-CLINS
package (via the shared ``lab_coding_package.load_lab_coding_package``
loader, which walks ``_find_pkg_files``). The extract is intentionally NOT
committed to the repo — the installed pkg is the single source of truth,
and a committed extract would drift from pkg updates (Fixed value table
additions/changes), causing the axis to measure "clinosim's snapshot"
instead of "the actual spec". When the pkg is not installed, the
display-check metric returns ``Outcome.NA`` with an actionable message
pointing to the pkg install step. (The pkg license itself is CC0-1.0
per its ``package.json.license`` field, verified 2026-07-27;
runtime-extract is driven by the drift concern, not by license.)

Applicability
-------------
Axis returns an empty list when the cohort is not JP — this is a JP-only
compliance surface. When called on a JP cohort with zero lab
Observations, each check returns ``Outcome.NA``.

CI Invariant Thresholds (Session 68 PR 5)
-----------------------------------------
The axis is integrated into clinosim CI via ``clinosim eval --strict``:

1. **Metric 1 (CS usage)** threshold = 100% (strict) — every lab Observation
   MUST carry a JP-CLINS-defined CodeSystem. Baseline for regression detection:
   1898/2509 CoreLabo + Uncoded analytes (session 67 migration completion).
   If new analytes added without proper JP-CLINS coding wiring, this metric
   will drop and signal regression.

2. **Metric 2 (Fixed display)** threshold = 100% (strict) — every slice-typed
   coding (CoreLabo / InfectionLabo / Uncoded) MUST carry the eCS SD Fixed
   display. No regression tolerance.

3. **Metric 3 (Rule satisfaction)** threshold = 100% (strict) — every lab
   Observation MUST carry localLaboCode + one typed coding. No regression
   tolerance.

All three checks are MAJOR severity, so one FAIL causes the entire axis to FAIL,
which triggers ``clinosim eval --strict`` exit code 1 (CI gate failure).

Positive/negative fixture tests in
``tests/unit/test_axis_jp_clins_lab_compliance.py`` are load-bearing:
the axis's whole purpose is to distinguish "measured zero" from "silently
returning zero because the code was broken", so the negative fixtures
must drive the ratios below 100% or the axis itself has silently
failed. Baseline (pre-migration, v29 dataset) must produce ``0/0/0``.
"""

from __future__ import annotations

from clinosim.audit.types import Cohort
from clinosim.eval.axes.locale import _detect_country_from_cohort
from clinosim.eval.engine import EvalCheck, Outcome, Severity
from clinosim.modules.output.lab_coding_package import (
    jp_clins_defined_system_uris,
    jp_clins_fixed_display_system_uris,
    jp_clins_localcode_system_uri,
    load_lab_coding_package,
)

# JP-CLINS pkg license is CC0-1.0 (per ``package.json.license``, verified
# 2026-07-27). The axis consumes the shared pkg loader
# (``clinosim.modules.output.lab_coding_package``) — see that module's
# docstring for pkg discovery + drift-avoidance rationale. When the
# pkg is absent, the display-check metric returns ``Outcome.NA``.

# --------------------------------------------------------------------------- #
# JP-CLINS-defined CodeSystem URIs — canonical registry lives in
# ``lab_coding_package``. The three module-level names below are
# module-load-time binds of the accessors (frozen set + str, both cheap
# lru_cached returns) so the hot-path predicates in this file continue
# to compare against a local constant with no per-call function overhead.
# When adding / removing a JP-CLINS-defined lab CS URI, edit
# ``lab_coding_package`` — the change flows here automatically.
#
# The defined set includes MEDIS's generic 17-digit JLAC10 CodeSystem
# (``http://medis.or.jp/CodeSystem/master-JLAC10-17digits``) — JP-CLINS
# recognizes it as an acceptable ``coding.system`` for the jlac10LaboCode
# slice even though it is not JP-CLINS-authored.

_JP_CLINS_DEFINED_SYSTEMS = jp_clins_defined_system_uris()
_FIXED_DISPLAY_SYSTEMS = jp_clins_fixed_display_system_uris()
_LOCALCODE_SYSTEM = jp_clins_localcode_system_uri()


def _load_fixed_display_by_system() -> dict[str, frozenset[str]] | None:
    """{system_uri: {valid_display, ...}} pivot for Metric 2 lookup.

    Consumes the shared package loader
    (``clinosim.modules.output.lab_coding_package``). Returns None when
    the pkg is not available; the display-check metric surfaces
    ``Outcome.NA`` in that case."""
    pkg = load_lab_coding_package()
    if not pkg.is_available():
        return None
    by_sys: dict[str, set[str]] = {}
    for (sys_uri, display), _slice in pkg.all_slices_by_system_display().items():
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
    if valid_by_sys is None:
        return EvalCheck(
            name=name,
            outcome=Outcome.NA,
            severity=Severity.MAJOR,
            message=(
                "JP-CLINS eCS StructureDefinition not available — install pkg "
                "'clinical-information-sharing#1.12.0' via the fhir CLI or set "
                "$CLINOSIM_JP_CLINS_PKG_DIR to the pkg's package/ directory. Display check "
                "requires the SD's Fixed value table from the installed pkg — a bundled "
                "extract would drift from pkg updates and undermine the check's meaning."
            ),
            detail={"pkg_missing": True},
        )
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
