"""Clinical axis — coherence checks (7 checks: 5 MVP + 2 P1-9 contradictions)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from clinosim.audit.types import Cohort
from clinosim.codes import get_system_uri
from clinosim.eval.engine import EvalCheck, Outcome, Severity

# JP medication CodeSystem URI set — mirrors locale.py `_JP_MEDICATION_SYSTEM_URIS`.
# canonical single source of truth = `codes/loader.py::_BUILTIN_URIS` + `codes/data/yj.yaml`.
# Used by ``_check_medication_lab_coherence_warfarin`` for warfarin-
# patient detection on the JP path when inspecting
# ``MedicationRequest.medicationCodeableConcept.coding[*].system``.
# The emit side
# (``clinosim/modules/output/fhir_r4/medications/medications.py:_resolve_jp_drug_system_uri``)
# dispatches to five URIs by drug-code format (yj / hot7 / hot9 /
# hot13 / medication-nocoded), and this set recognises all of them.
# Replaces a previously hard-coded
# ``urn:oid:1.2.392.100495.20.2.74`` prefix check: that OID is only
# the HOT9 alias in the JP Core NamingSystem, not the YJ canonical,
# so the previous check was silent-broken for YJ codes emitted at
# the ``capstandard`` URI.
_JP_MEDICATION_SYSTEM_KEYS = ("yj", "hot7", "hot9", "hot13", "medication-nocoded")
_JP_MEDICATION_SYSTEM_URIS: frozenset[str] = frozenset(get_system_uri(k) for k in _JP_MEDICATION_SYSTEM_KEYS)

# Physiological plausibility bounds — **unit-aware** (B3 2026-07-26 fix).
#
# The previous implementation used a single-unit
# ``{LOINC: (lo, hi, unit_hint)}`` bounds map. ``unit_hint`` was not
# consulted at check time (the comparison ignored units entirely), so
# any mismatch between the emitted unit and the bounds unit produced
# a systematic false FAIL — a silent bug. Empirical example (JP
# p=300 seed=300 cohort): WBC (LOINC 6690-2) is emitted in ``/uL``
# 584 times, but the bounds were defined for ``10^9/L`` with an upper
# limit of 500, so 584 records failed spuriously (WBC 4720–17522 /uL
# is clinically normal).
#
# **Requirement**: do NOT hide the 584 records by widening the
# bounds. The fix is to stop comparing values across incompatible
# units. Bounds are now unit-aware — only the bounds whose unit
# matches the emitted unit are consulted. Unknown units are
# fail-safe-skipped (no false FAIL), but their appearance is surfaced
# on ``EvalCheck.detail.unknown_units_by_loinc`` so a new-unit
# infiltration is not silenced.
#
# Sources:
#   - WBC: LOINC 6690-2. Canonical unit ``10*9/L`` (UCUM); clinical
#     convention US = ``10^9/L``, JP = ``/uL``. 1 × 10^9/L = 1000 /uL,
#     so the upper bound of 500 × 10^9/L equals 500,000 /uL.
#   - K: LOINC 2823-3. ``mmol/L`` = ``mEq/L`` (monovalent ion);
#     shared bounds ``[0, 10]``.
#   - Na: LOINC 2951-2. Same relation as K.
#   - Cre / Glucose / Hb / Bili: only one unit observed
#     (``mg/dL`` / ``g/dL``); no alias.
#   - PT-INR: unit-less (``{INR}`` in UCUM); value taken as-is.
_LAB_BOUNDS_BY_UNIT: dict[str, dict[str, tuple[float, float]]] = {
    # LOINC → {unit_string: (min, max)}
    # ``unit_string`` matches either ``valueQuantity.unit`` (human-readable)
    # or ``.code`` (UCUM); the check site tries both in the order ``unit``
    # then ``code``.
    "6690-2": {  # WBC
        "/uL": (0.0, 500_000.0),
        "/μL": (0.0, 500_000.0),
        "10^9/L": (0.0, 500.0),
        "10*9/L": (0.0, 500.0),  # UCUM canonical form.
    },
    "718-7": {"g/dL": (0.0, 25.0)},  # Hemoglobin
    "2160-0": {"mg/dL": (0.0, 30.0)},  # Serum creatinine
    "2345-7": {"mg/dL": (0.0, 1500.0)},  # Serum glucose
    "2823-3": {  # Serum potassium
        "mmol/L": (0.0, 10.0),
        "mEq/L": (0.0, 10.0),
    },
    "2951-2": {  # Serum sodium
        "mmol/L": (0.0, 200.0),
        "mEq/L": (0.0, 200.0),
    },
    "1975-2": {"mg/dL": (0.0, 50.0)},  # Total bilirubin
    "6301-6": {  # PT-INR
        "{INR}": (0.5, 20.0),
        "": (0.5, 20.0),  # unitless fallback (some emitters omit unit for INR)
    },
}


# --------------------------------------------------------------------------- #
# P1-9 — condition × lab clinical pairings.
#
# Each entry declares: "given a patient carrying a Condition whose ICD-10
# code matches one of `icd_prefixes`, we expect a related lab drawn within
# a ±window of the condition onset to be in the `expected_band`.
# Otherwise a clinical contradiction is present (e.g. sepsis without
# lactate lift, DKA with normal HCO3, MI with normal troponin)."
#
# See docs/eval-rules.md for the clinical rationale + literature source
# for each band.


@dataclass(frozen=True)
class _CondLabPairing:
    name: str
    icd_prefixes: tuple[str, ...]  # matches Condition.code.coding[].code.startswith(any of these)
    loinc: str  # target lab's LOINC code
    expected_band: tuple[float, float]  # inclusive [low, high]; violation = outside
    direction: str  # "high" (expect above low), "low" (expect below high), "band" (expect between)
    rationale: str


# Window (± days) around Condition.onsetDateTime in which the lab is
# considered "related". 7 days matches the acute clinical horizon;
# chronic pairings (CKD, T2DM) still apply because their Conditions are
# recorded on the day the lab drew.
_LAB_WINDOW_DAYS = 7


_CONDITION_LAB_PAIRINGS: tuple[_CondLabPairing, ...] = (
    _CondLabPairing(
        name="sepsis_lactate",
        icd_prefixes=("A41",),
        loinc="2524-7",  # Serum lactate (there are multiple LOINCs; this is the venous one clinosim emits)
        expected_band=(2.0, 100.0),
        direction="high",
        rationale="Surviving Sepsis 2021: lactate > 2 mmol/L is a defining feature of sepsis with tissue hypoperfusion.",  # noqa: E501
    ),
    _CondLabPairing(
        name="dka_hco3",
        icd_prefixes=("E10.10", "E10.11", "E11.10", "E11.11"),
        loinc="1963-8",  # HCO3 serum
        expected_band=(0.0, 18.0),
        direction="low",
        rationale="ADA severity criteria: HCO3 < 18 mEq/L on presentation defines mild-to-severe DKA.",
    ),
    _CondLabPairing(
        name="acute_mi_troponin",
        icd_prefixes=("I21", "I22"),
        loinc="10839-9",  # Troponin I
        expected_band=(0.04, 100.0),
        direction="high",
        rationale="Universal Definition of MI: Troponin I above 99th-percentile URL (0.04 ng/mL for most assays).",
    ),
    _CondLabPairing(
        name="ckd_stage_creatinine",
        icd_prefixes=("N18.3", "N18.4", "N18.5"),
        loinc="2160-0",  # Serum creatinine
        expected_band=(1.3, 20.0),
        direction="high",
        rationale="KDIGO 2012: CKD stage 3+ corresponds to eGFR ≤ 60 mL/min/1.73m², which typically implies Cr > 1.3 mg/dL in most adult body sizes.",  # noqa: E501
    ),
    _CondLabPairing(
        name="t2dm_hba1c",
        icd_prefixes=("E11.9",),
        loinc="4548-4",  # HbA1c
        expected_band=(6.5, 20.0),
        direction="high",
        rationale="ADA: HbA1c ≥ 6.5% is diagnostic threshold for type-2 diabetes.",
    ),
    _CondLabPairing(
        name="bacterial_pneumonia_wbc",
        icd_prefixes=("J13", "J14", "J15"),
        loinc="6690-2",  # WBC
        expected_band=(11.0, 500.0),
        direction="high",
        rationale="Infection response: WBC > 11 × 10^9/L is one of the SIRS criteria and typical of bacterial pneumonia.",  # noqa: E501
    ),
    _CondLabPairing(
        name="anemia_hgb",
        icd_prefixes=("D50", "D51", "D52", "D53", "D62", "D63", "D64"),
        loinc="718-7",  # Hb
        expected_band=(0.0, 12.0),
        direction="low",
        rationale="WHO anemia cutoffs: Hgb < 12 g/dL (non-pregnant adult female) / < 13 g/dL (male). Using the more permissive cutoff to avoid false positives on borderline male cases.",  # noqa: E501
    ),
    _CondLabPairing(
        name="chf_bnp",
        icd_prefixes=("I50",),
        loinc="30934-4",  # BNP serum
        expected_band=(100.0, 5000.0),
        direction="high",
        rationale="Framingham / ACC-AHA heart failure criteria: BNP > 100 pg/mL supports acute HF diagnosis.",
    ),
)


# Warfarin monitoring pairing (medication-driven). Warfarin's RxNorm code
# is 11289; JP YJ code family 3332001*. When an ACTIVE MedicationRequest
# for warfarin exists, related PT-INR draws within the window should sit
# in the therapeutic band 2.0-3.5 (broader than 2.0-3.0 to accommodate
# co-morbidity perturbation — see AD-57 warfarin coupling).
_WARFARIN_RXNORM = "11289"
_WARFARIN_YJ_PREFIX = "3332001"
_PT_INR_LOINC = "6301-6"
_WARFARIN_THERAPEUTIC_BAND = (2.0, 3.5)

# Issue #737: Warfarin induction period. INR climbs from baseline ~1.0 to
# therapeutic range over 3-5 days as vitamin-K-dependent clotting factors
# (II, VII, IX, X) are depleted. Real-world clinical practice measures INR
# daily during induction but does not expect the therapeutic band until
# loading is achieved. Skipping the induction window keeps this axis a
# signal for **maintenance-phase** deviations only, matching how
# clinicians reason about "warfarin monitoring coherence".
#
# 5 days is the conservative upper bound of typical loading — an
# uncomplicated patient reaches therapeutic INR in 3-5 days; a slow
# metaboliser can take 7-10 days but is still legitimately within
# induction. Widening the window trades off against maintenance-phase
# coverage — 5 days is a defensible middle ground.
_WARFARIN_INDUCTION_DAYS = 5


# Violation-rate thresholds for the aggregated coherence score.
# See P1-9 plan: PASS ≤ 5%, WARN 5-25%, FAIL > 25%. Rates below the PASS
# threshold reflect the natural biological variability + acquisition
# window mismatch; anything higher is a real defect worth flagging.
_COHERENCE_PASS_MAX = 0.05
_COHERENCE_WARN_MAX = 0.25


# Age bounds used by ``_check_age_condition_consistency``. Empirical
# tuning for the synthetic simulator, chosen to leave a WHO/CDC-adjacent
# "adolescent" grey zone (12–18) where neither adult-only nor peds-only
# ICD prefixes may fire — clinosim currently does not model diseases
# with pediatric ICD prefixes, but the zone keeps the check
# symmetrically safe if that changes.
_PEDIATRIC_AGE_CEILING: int = 12  # age < this ⇒ patient counted as pediatric
_ADULT_AGE_FLOOR: int = 18  # age > this ⇒ patient counted as adult

# ICD-10 (US) / ICD-10 (JP) prefixes for conditions that are strictly
# adult-onset — clinosim never generates these for pediatric patients.
# Prefix-matched against ``Condition.code.coding[].code`` in the age /
# condition consistency check. Extracted from inline literal so the
# vocabulary sits at module scope alongside the other clinical-axis
# thresholds.
_ADULT_ONLY_ICD_PREFIXES: frozenset[str] = frozenset({"I10", "I25", "I48", "I50", "E11", "N18", "N40", "F03"})

# Truncation limits for ``EvalCheck.detail.problems_sample`` — the
# report keeps a bounded slice so a large cohort does not blow up the
# JSON payload. 20 for the age-condition check (which also breaks the
# scan early once it has 20 problems); 10 elsewhere.
_AGE_CONDITION_PROBLEM_LIMIT: int = 20
_PROBLEM_SAMPLE_LIMIT: int = 10


def run(cohort: Cohort, country: str) -> list[EvalCheck]:
    return [
        _check_lab_values_physiological_range(cohort, country),
        _check_age_condition_consistency(cohort, country),
        _check_medication_date_sanity(cohort, country),
        _check_encounter_temporal_ordering(cohort, country),
        _check_condition_encounter_link(cohort, country),
        _check_condition_lab_coherence(cohort, country),  # P1-9
        _check_medication_lab_coherence_warfarin(cohort, country),  # P1-9
    ]


# --------------------------------------------------------------------------- #


def _check_lab_values_physiological_range(cohort: Cohort, country: str) -> EvalCheck:
    """Lab values must fall inside gross physiological bounds. Any WBC
    of 10^30 or negative creatinine is a defect.

    B3 2026-07-26: unit-aware bounds — emit `valueQuantity.unit` (fallback
    ``.code``) matches a key in ``_LAB_BOUNDS_BY_UNIT[loinc]`` the
    bounds are applied. Unknown units are fail-safe-skipped (no
    false FAIL) and surfaced on ``detail.unknown_units_by_loinc`` so
    silence is prevented
    (when a new unit is introduced on the emit side, the addition
    surfaces via ``EvalCheck.detail``).
    """
    out_of_range: dict[str, int] = {}
    unknown_units: dict[str, dict[str, int]] = {}
    total_checked = 0
    for row in _read(cohort, country, "Observation"):
        code_bag = (row.get("code") or {}).get("coding") or []
        loinc_code = _first_code_for_system(code_bag, "http://loinc.org")
        if not loinc_code or loinc_code not in _LAB_BOUNDS_BY_UNIT:
            continue
        vq = row.get("valueQuantity") or {}
        val = vq.get("value")
        if val is None:
            continue
        unit_str = vq.get("unit") or ""
        unit_code = vq.get("code") or ""
        bounds_by_unit = _LAB_BOUNDS_BY_UNIT[loinc_code]
        # Try ``unit`` before ``code`` (``unit`` is human-readable; ``code`` is UCUM canonical).
        bounds = bounds_by_unit.get(unit_str) or bounds_by_unit.get(unit_code)
        if bounds is None:
            # Unknown unit = cannot judge (fail-safe skip); surface it instead.
            key = unit_str or unit_code or "<empty>"
            unknown_units.setdefault(loinc_code, {}).setdefault(key, 0)
            unknown_units[loinc_code][key] += 1
            continue
        total_checked += 1
        lo, hi = bounds
        if not (lo <= val <= hi):
            out_of_range[loinc_code] = out_of_range.get(loinc_code, 0) + 1

    detail_extras: dict[Any, Any] = {}
    if unknown_units:
        detail_extras["unknown_units_by_loinc"] = unknown_units

    if total_checked == 0:
        if detail_extras:
            return EvalCheck(
                name="lab_values_physiological_range",
                outcome=Outcome.NA,
                severity=Severity.MAJOR,
                message="No LOINC-coded lab values in the checked set were found.",
                detail=detail_extras,
            )
        return EvalCheck(
            name="lab_values_physiological_range",
            outcome=Outcome.NA,
            severity=Severity.MAJOR,
            message="No LOINC-coded lab values in the checked set were found.",
        )
    if not out_of_range:
        return EvalCheck(
            name="lab_values_physiological_range",
            outcome=Outcome.PASS,
            severity=Severity.MAJOR,
            message=f"{total_checked} lab value(s) checked; all within physiological bounds.",
            detail={"checked": total_checked, "loinc_bounds": _bounds_summary(), **detail_extras},
        )
    return EvalCheck(
        name="lab_values_physiological_range",
        outcome=Outcome.FAIL,
        severity=Severity.MAJOR,
        message=f"{sum(out_of_range.values())} lab value(s) out of physiological bounds",
        detail={"by_loinc": out_of_range, "checked": total_checked, **detail_extras},
    )


def _check_age_condition_consistency(cohort: Cohort, country: str) -> EvalCheck:
    """Adult-only conditions must not appear on pediatric patients (< 12 y),
    pediatric-only conditions must not appear on adults (> 18 y)."""
    # Build Patient.id → age (years) map from birthDate + any death or
    # first-encounter reference.
    ages_by_patient = _patient_ages(cohort, country)

    peds_only_prefixes: set[str] = set()  # Reserved — clinosim does not model peds diseases yet.

    problems: list[str] = []
    for row in _read(cohort, country, "Condition"):
        pid = (row.get("subject") or {}).get("reference", "").split("/", 1)[-1]
        age = ages_by_patient.get(pid)
        if age is None:
            continue
        codes = (row.get("code") or {}).get("coding") or []
        for c in codes:
            code = c.get("code", "")
            for prefix in _ADULT_ONLY_ICD_PREFIXES:
                if code.startswith(prefix) and age < _PEDIATRIC_AGE_CEILING:
                    problems.append(f"pediatric patient (age {age}) with {code}")
                    break
            for prefix in peds_only_prefixes:
                if code.startswith(prefix) and age > _ADULT_AGE_FLOOR:
                    problems.append(f"adult patient (age {age}) with peds-only {code}")
                    break
        if len(problems) > _AGE_CONDITION_PROBLEM_LIMIT:
            break

    if not problems:
        return EvalCheck(
            name="age_condition_consistency",
            outcome=Outcome.PASS,
            severity=Severity.MAJOR,
            message="No adult-only conditions on pediatric patients.",
        )
    return EvalCheck(
        name="age_condition_consistency",
        outcome=Outcome.FAIL,
        severity=Severity.MAJOR,
        message=f"{len(problems)} age-condition mismatch(es)",
        detail={"problems_sample": problems[:_AGE_CONDITION_PROBLEM_LIMIT]},
    )


def _check_medication_date_sanity(cohort: Cohort, country: str) -> EvalCheck:
    """MedicationRequest.authoredOn must fall after the patient's birthDate."""
    births = {row.get("id"): row.get("birthDate") for row in _read(cohort, country, "Patient")}
    problems: list[str] = []
    for row in _read(cohort, country, "MedicationRequest"):
        pid = (row.get("subject") or {}).get("reference", "").split("/", 1)[-1]
        birth = births.get(pid)
        authored = (row.get("authoredOn") or "")[:10]
        if not birth or not authored:
            continue
        if authored < birth:
            problems.append(f"MedicationRequest/{row.get('id', '?')} authoredOn={authored} < birthDate={birth}")

    if not problems:
        return EvalCheck(
            name="medication_date_sanity",
            outcome=Outcome.PASS,
            severity=Severity.MAJOR,
            message="No MedicationRequests are dated before the patient's birth.",
        )
    return EvalCheck(
        name="medication_date_sanity",
        outcome=Outcome.FAIL,
        severity=Severity.MAJOR,
        message=f"{len(problems)} MedicationRequest date sanity violation(s)",
        detail={"problems_sample": problems[:_PROBLEM_SAMPLE_LIMIT]},
    )


def _check_encounter_temporal_ordering(cohort: Cohort, country: str) -> EvalCheck:
    """Encounter.period.start ≤ Encounter.period.end. Both dates required
    for finished encounters; in-progress encounters may omit end."""
    problems: list[str] = []
    for row in _read(cohort, country, "Encounter"):
        period = row.get("period") or {}
        start = period.get("start")
        end = period.get("end")
        if start and end and end < start:
            problems.append(f"Encounter/{row.get('id', '?')} end {end} before start {start}")

    if not problems:
        return EvalCheck(
            name="encounter_temporal_ordering",
            outcome=Outcome.PASS,
            severity=Severity.MAJOR,
            message="All Encounter periods are non-decreasing.",
        )
    return EvalCheck(
        name="encounter_temporal_ordering",
        outcome=Outcome.FAIL,
        severity=Severity.MAJOR,
        message=f"{len(problems)} Encounter(s) with reversed period",
        detail={"problems_sample": problems[:_PROBLEM_SAMPLE_LIMIT]},
    )


def _check_condition_encounter_link(cohort: Cohort, country: str) -> EvalCheck:
    """When Condition.encounter is set, it must reference an emitted
    Encounter. (A missing encounter link is allowed — used for
    chronic problem-list items.)"""
    valid_encounters = {row.get("id") for row in _read(cohort, country, "Encounter")}
    problems: list[str] = []
    for row in _read(cohort, country, "Condition"):
        enc_ref = (row.get("encounter") or {}).get("reference", "")
        if enc_ref.startswith("Encounter/"):
            enc_id = enc_ref.split("/", 1)[1]
            if enc_id not in valid_encounters:
                problems.append(f"Condition/{row.get('id', '?')} → {enc_ref} (unresolved)")

    if not problems:
        return EvalCheck(
            name="condition_encounter_link",
            outcome=Outcome.PASS,
            severity=Severity.MINOR,
            message="All Condition.encounter references resolve to emitted Encounters.",
        )
    return EvalCheck(
        name="condition_encounter_link",
        outcome=Outcome.FAIL,
        severity=Severity.MINOR,
        message=f"{len(problems)} Condition.encounter reference(s) unresolved",
        detail={"problems_sample": problems[:_PROBLEM_SAMPLE_LIMIT]},
    )


# --------------------------------------------------------------------------- #
# helpers


def _read(cohort: Cohort, country: str, resource_type: str):
    import json

    path = cohort.root / country / "fhir_r4" / f"{resource_type}.ndjson"
    if not path.exists():
        return iter(())

    def _gen():
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    return _gen()


def _first_code_for_system(coding: list, system: str) -> str | None:
    for c in coding:
        if c.get("system") == system:
            return c.get("code")
    return None


def _patient_ages(cohort: Cohort, country: str) -> dict[str, int]:
    today = date.today()
    ages: dict[str, int] = {}
    for row in _read(cohort, country, "Patient"):
        pid = row.get("id")
        birth = row.get("birthDate")
        if not (pid and birth):
            continue
        try:
            b = date.fromisoformat(birth[:10])
            ages[pid] = today.year - b.year - int((today.month, today.day) < (b.month, b.day))
        except ValueError:
            continue
    return ages


def _bounds_summary() -> dict[str, dict[str, str]]:
    """LOINC → unit → "[lo, hi]" (unit-aware, B3 2026-07-26)."""
    return {
        code: {unit: f"[{lo}, {hi}]" for unit, (lo, hi) in units.items()} for code, units in _LAB_BOUNDS_BY_UNIT.items()
    }


# --------------------------------------------------------------------------- #
# P1-9 — condition × lab coherence
#
# For each pairing in `_CONDITION_LAB_PAIRINGS`, find every Condition
# matching the icd_prefixes and check whether the same patient carries a
# related lab drawn within ±_LAB_WINDOW_DAYS whose value falls inside
# the `expected_band`. Aggregate across all pairings into one axis
# check, with per-pairing violation rates in `detail`.


def _check_condition_lab_coherence(cohort: Cohort, country: str) -> EvalCheck:
    # Pre-index Observations by (patient_id, loinc_code) for the LOINCs
    # any pairing cares about — one pass, then O(1) lookups downstream.
    interesting_loincs = {p.loinc for p in _CONDITION_LAB_PAIRINGS}
    obs_by_patient_loinc: dict[tuple[str, str], list[tuple[date | None, float]]] = {}
    for row in _read(cohort, country, "Observation"):
        loinc = _first_loinc(row)
        if loinc not in interesting_loincs:
            continue
        pid = (row.get("subject") or {}).get("reference", "").split("/", 1)[-1]
        if not pid:
            continue
        vq = row.get("valueQuantity") or {}
        val = vq.get("value")
        if val is None:
            continue
        effective = _parse_date(row.get("effectiveDateTime", ""))
        obs_by_patient_loinc.setdefault((pid, loinc), []).append((effective, float(val)))

    per_pairing: dict[str, dict[str, int | float]] = {}
    total_eligible = 0
    total_violations = 0
    for pairing in _CONDITION_LAB_PAIRINGS:
        eligible = 0
        violations = 0
        for cond in _read(cohort, country, "Condition"):
            codes = _condition_codes(cond)
            if not any(any(c.startswith(p) for p in pairing.icd_prefixes) for c in codes):
                continue
            pid = (cond.get("subject") or {}).get("reference", "").split("/", 1)[-1]
            if not pid:
                continue
            onset = _parse_date(cond.get("onsetDateTime", ""))
            obs_list = obs_by_patient_loinc.get((pid, pairing.loinc), [])
            related = _within_window(obs_list, onset, _LAB_WINDOW_DAYS)
            if not related:
                continue  # no eligible lab — skip (not a violation)
            eligible += 1
            if not any(_value_in_band(v, pairing.expected_band, pairing.direction) for _, v in related):
                violations += 1
        rate = violations / eligible if eligible else 0.0
        per_pairing[pairing.name] = {
            "eligible": eligible,
            "violations": violations,
            "violation_rate": round(rate, 4),
        }
        total_eligible += eligible
        total_violations += violations

    if total_eligible == 0:
        return EvalCheck(
            name="condition_lab_coherence",
            outcome=Outcome.NA,
            severity=Severity.MAJOR,
            message="No eligible Condition + lab pairs found (small cohort or no matching diagnoses).",
            detail={"per_pairing": per_pairing},
        )
    overall_rate = total_violations / total_eligible
    outcome = _outcome_from_rate(overall_rate)
    return EvalCheck(
        name="condition_lab_coherence",
        outcome=outcome,
        severity=Severity.MAJOR,
        message=(
            f"{total_violations}/{total_eligible} condition-lab pairs violate the expected clinical band "
            f"({overall_rate:.1%} overall; PASS ≤ {_COHERENCE_PASS_MAX:.0%}, WARN ≤ {_COHERENCE_WARN_MAX:.0%})"
        ),
        detail={
            "overall_violation_rate": round(overall_rate, 4),
            "per_pairing": per_pairing,
            "window_days": _LAB_WINDOW_DAYS,
        },
    )


def _check_medication_lab_coherence_warfarin(cohort: Cohort, country: str) -> EvalCheck:
    """Warfarin patients should sit in the 2.0-3.5 PT-INR therapeutic band.

    PT-INR draws made after warfarin loading (`_WARFARIN_INDUCTION_DAYS`
    days past the earliest active warfarin MedicationRequest) are
    considered eligible. Draws inside the induction window are excluded:
    a subtherapeutic value on day 1-5 of warfarin is clinically correct
    (INR climbs from baseline ~1.0 over 3-5 days as vitamin-K-dependent
    clotting factors deplete) and would only inflate the false-positive
    rate. Issue #737 (Baseline Analysis session 88g) documented this
    over-strict axis behaviour on the JP baseline where 6/38 flagged
    readings were all in the 1.2-1.6 range within 3 days of warfarin
    start.
    """
    # Find patients on warfarin. Match by RxNorm (US) or YJ prefix (JP).
    warfarin_start_by_patient: dict[str, date | None] = {}
    for row in _read(cohort, country, "MedicationRequest"):
        codings = ((row.get("medicationCodeableConcept") or {}).get("coding")) or []
        is_warfarin = any(
            (c.get("system") == "http://www.nlm.nih.gov/research/umls/rxnorm" and c.get("code") == _WARFARIN_RXNORM)
            or (
                (c.get("system") or "") in _JP_MEDICATION_SYSTEM_URIS
                and (c.get("code") or "").startswith(_WARFARIN_YJ_PREFIX)
            )
            for c in codings
        )
        if not is_warfarin:
            continue
        pid = (row.get("subject") or {}).get("reference", "").split("/", 1)[-1]
        if not pid:
            continue
        authored = _parse_date(row.get("authoredOn", ""))
        # Keep the earliest authoredOn per patient.
        prior = warfarin_start_by_patient.get(pid)
        if authored and (prior is None or authored < prior):
            warfarin_start_by_patient[pid] = authored
        warfarin_start_by_patient.setdefault(pid, None)

    if not warfarin_start_by_patient:
        return EvalCheck(
            name="medication_lab_coherence_warfarin",
            outcome=Outcome.NA,
            severity=Severity.MAJOR,
            message="No warfarin MedicationRequests found in the cohort.",
        )

    # Walk PT-INR observations; violation if a warfarin patient's INR at or
    # after the earliest warfarin start is outside 2.0-3.5.
    eligible = 0
    violations = 0
    for row in _read(cohort, country, "Observation"):
        if _first_loinc(row) != _PT_INR_LOINC:
            continue
        pid = (row.get("subject") or {}).get("reference", "").split("/", 1)[-1]
        if pid not in warfarin_start_by_patient:
            continue
        start = warfarin_start_by_patient[pid]
        eff = _parse_date(row.get("effectiveDateTime", ""))
        if start and eff and eff < start:
            continue
        # Issue #737: exclude readings inside the induction window. This
        # window is short enough (5 days) that a maintenance patient with
        # a persistent adherence problem still contributes to the
        # violation count via readings on day 6+.
        if start and eff and (eff - start) < timedelta(days=_WARFARIN_INDUCTION_DAYS):
            continue
        vq = row.get("valueQuantity") or {}
        val = vq.get("value")
        if val is None:
            continue
        eligible += 1
        lo, hi = _WARFARIN_THERAPEUTIC_BAND
        if not (lo <= float(val) <= hi):
            violations += 1

    if eligible == 0:
        return EvalCheck(
            name="medication_lab_coherence_warfarin",
            outcome=Outcome.NA,
            severity=Severity.MAJOR,
            message=(
                f"{len(warfarin_start_by_patient)} warfarin patient(s) found but no eligible PT-INR observations."
            ),
        )
    rate = violations / eligible
    outcome = _outcome_from_rate(rate)
    return EvalCheck(
        name="medication_lab_coherence_warfarin",
        outcome=outcome,
        severity=Severity.MAJOR,
        message=(
            f"{violations}/{eligible} PT-INR readings on warfarin patients "
            f"outside the therapeutic band {_WARFARIN_THERAPEUTIC_BAND[0]}-{_WARFARIN_THERAPEUTIC_BAND[1]} "
            f"({rate:.1%})"
        ),
        detail={
            "patients_on_warfarin": len(warfarin_start_by_patient),
            "eligible_inr_readings": eligible,
            "violations": violations,
            "violation_rate": round(rate, 4),
            "therapeutic_band": list(_WARFARIN_THERAPEUTIC_BAND),
        },
    )


# --------------------------------------------------------------------------- #
# helpers used by the P1-9 checks


def _first_loinc(row: dict) -> str | None:
    for c in (row.get("code") or {}).get("coding") or []:
        if c.get("system") == "http://loinc.org":
            return c.get("code")
    return None


def _condition_codes(cond: dict) -> list[str]:
    return [c.get("code", "") for c in (cond.get("code") or {}).get("coding") or []]


def _parse_date(s: str) -> date | None:
    if not s or len(s) < 10:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _within_window(
    obs_list: list[tuple[date | None, float]],
    anchor: date | None,
    window_days: int,
) -> list[tuple[date | None, float]]:
    """Filter observations to those inside ±window_days of `anchor`. If
    either the anchor or the observation date is missing, keep the
    observation (permissive default — clinosim always emits both, so
    missing dates are the exception, not the rule)."""
    if anchor is None:
        return obs_list
    lo = anchor - timedelta(days=window_days)
    hi = anchor + timedelta(days=window_days)
    return [(d, v) for d, v in obs_list if d is None or lo <= d <= hi]


def _value_in_band(value: float, band: tuple[float, float], direction: str) -> bool:
    lo, hi = band
    if direction == "high":
        return value >= lo
    if direction == "low":
        return value <= hi
    return lo <= value <= hi


def _outcome_from_rate(rate: float) -> Outcome:
    if rate <= _COHERENCE_PASS_MAX:
        return Outcome.PASS
    if rate <= _COHERENCE_WARN_MAX:
        return Outcome.WARN
    return Outcome.FAIL
