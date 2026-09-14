"""JP Core narrow-gate compliance axis.

Purpose
-------
Measure a **narrow** subset of JP Core Patient / Encounter /
MedicationRequest must-support element compliance on the generator
side. Runs per PR as a fast (~1 min) invariant check; the full HL7
FHIR Validator run (``jp-validate.yml``) remains the authoritative
on-demand compliance surface for the JP Core + JP-CLINS bundle, and
``jp_clins_lab_compliance`` continues to cover the eCS lab surface
under its own strict-100 % gate.

This axis is intentionally **narrow-list-first** (Issue #1418
guidance): only invariants that hold at 100 % on master today are
gated at ``threshold=1.0``. Kana-representation (SYL) coverage is
NOT gated here — the existing ``locale`` axis already emits a WARN
for missing SYL on JP Patient names, and forcing SYL into the JP
Core strict gate would false-fail every current PR.

Checks
------
1. **jp_core_patient_profile_declared** — every JP Patient carries
   a ``meta.profile`` entry starting with
   ``http://jpfhir.jp/fhir/core/StructureDefinition/JP_Patient``.
   The JP-CLINS eCS ``JP_Patient_eCS`` SD (``.../fhir/eCS/...``)
   lives under a different prefix and does NOT satisfy this check
   on its own — a JP-CLINS cohort must also declare the JP Core
   Patient profile, per Issue #1418 (JP output → JP Core AND
   JP-CLINS 準拠必須).
2. **jp_core_patient_identifier_present** — every JP Patient carries
   at least one identifier (must-support on JP Core Patient).
3. **jp_core_patient_name_family_given** — every JP Patient has at
   least one name with both ``family`` and ``given`` set.
4. **jp_core_patient_kanji_representation** — every JP Patient has
   at least one name carrying the ISO 21090
   ``EN-representation = IDE`` extension (kanji name variant, the
   JP Core primary display representation).
5. **jp_core_encounter_class_present** — every JP Encounter carries
   ``class`` with a ``code`` value.
6. **jp_core_encounter_period_present** — every JP Encounter carries
   ``period.start`` (must-support on JP Core Encounter for
   inpatient/outpatient linkage).
7. **jp_core_medicationrequest_medication_coding_present** — every
   JP MedicationRequest carries
   ``medicationCodeableConcept.coding[]`` (must-support — the drug
   identity anchor for JP Core MedicationRequest).

Applicability
-------------
Axis returns an empty list on non-JP cohorts — mirrored on the US
side by ``us_core_compliance``.

CI Invariant Thresholds
-----------------------
All checks: ``threshold = 1.0``, ``severity = MAJOR``. A single
below-1.0 metric flips the axis FAIL, which triggers ``clinosim
eval --strict`` exit code 1 (CI gate failure). Complements the
existing ``jp_clins_lab_compliance`` axis without overlap — this
axis is JP Core baseline, that axis is JP-CLINS eCS lab specifics.

Rationale for narrowness
------------------------
See Issue #1418 body. YJ/HOT drug-code system membership is already
covered in the ``locale`` axis
(``_jp_yj_code_on_medications``); duplicating it here would double-
count without adding coverage. Kana-name (SYL) coverage is
similarly deferred to the existing ``locale`` axis WARN so the JP
Core strict gate does not false-fail today's cohorts.
"""

from __future__ import annotations

from clinosim.audit.types import Cohort
from clinosim.eval.axes.locale import _detect_country_from_cohort, _read
from clinosim.eval.engine import EvalCheck, Outcome, Severity

# --------------------------------------------------------------------------- #
# JP Core canonical URLs

_JP_CORE_PATIENT_PROFILE_PREFIX = "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Patient"
_ISO_21090_EN_REPRESENTATION_SUFFIX = "iso21090-EN-representation"
_IDE_REPRESENTATION_CODE = "IDE"  # ideographic (kanji) — JP Core primary display


# --------------------------------------------------------------------------- #
# Axis entrypoint


def run(cohort: Cohort, country: str) -> list[EvalCheck]:
    """7-check JP Core narrow-gate compliance axis. No-op on non-JP cohorts."""
    if _detect_country_from_cohort(cohort, country) != "JP":
        return []
    patients = list(_read(cohort, country, "Patient"))
    encounters = list(_read(cohort, country, "Encounter"))
    med_requests = list(_read(cohort, country, "MedicationRequest"))
    return [
        _check_patient_profile_declared(patients),
        _check_patient_identifier(patients),
        _check_patient_name_family_given(patients),
        _check_patient_kanji_representation(patients),
        _check_encounter_class_present(encounters),
        _check_encounter_period_present(encounters),
        _check_medicationrequest_medication_coding(med_requests),
    ]


# --------------------------------------------------------------------------- #
# Patient checks


def _check_patient_profile_declared(patients: list[dict]) -> EvalCheck:
    """Every JP Patient must declare the JP Core ``JP_Patient`` profile
    URL (``.../fhir/core/StructureDefinition/JP_Patient``). The
    JP-CLINS eCS ``JP_Patient_eCS`` SD lives under a different prefix
    (``.../fhir/eCS/StructureDefinition/JP_Patient_eCS``) and is a
    JP-CLINS declaration, not a JP Core one — Issue #1418 requires
    both, and this axis gates the JP Core half. Production JP output
    emits both profiles side by side, so this check remains 100 % on
    master today."""
    name = "jp_core_patient_profile_declared"
    total = len(patients)
    if total == 0:
        return _na(name, "No JP Patients found.")
    ok = 0
    for p in patients:
        profiles = (p.get("meta") or {}).get("profile") or []
        if any(u.startswith(_JP_CORE_PATIENT_PROFILE_PREFIX) for u in profiles):
            ok += 1
    return _ratio(
        name=name,
        numerator=ok,
        denominator=total,
        message_template=("{hits}/{total} JP Patients declare a JP_Patient-family profile URL on meta.profile"),
    )


def _check_patient_identifier(patients: list[dict]) -> EvalCheck:
    name = "jp_core_patient_identifier_present"
    total = len(patients)
    if total == 0:
        return _na(name, "No JP Patients found.")
    ok = sum(1 for p in patients if p.get("identifier"))
    return _ratio(
        name=name,
        numerator=ok,
        denominator=total,
        message_template="{hits}/{total} JP Patients carry at least one identifier",
    )


def _check_patient_name_family_given(patients: list[dict]) -> EvalCheck:
    name = "jp_core_patient_name_family_given"
    total = len(patients)
    if total == 0:
        return _na(name, "No JP Patients found.")
    ok = 0
    for p in patients:
        names = p.get("name") or []
        has_family = any(n.get("family") for n in names)
        has_given = any(n.get("given") for n in names)
        if has_family and has_given:
            ok += 1
    return _ratio(
        name=name,
        numerator=ok,
        denominator=total,
        message_template="{hits}/{total} JP Patients have name.family + name.given",
    )


def _check_patient_kanji_representation(patients: list[dict]) -> EvalCheck:
    """Every JP Patient must have at least one name carrying the
    ISO 21090 ``EN-representation`` extension with ``valueCode = IDE``
    — the kanji-primary display variant JP Core expects. Kana (SYL) is
    handled as a WARN in the ``locale`` axis and is intentionally not
    gated here."""
    name = "jp_core_patient_kanji_representation"
    total = len(patients)
    if total == 0:
        return _na(name, "No JP Patients found.")
    ok = 0
    for p in patients:
        if _has_representation(p.get("name") or [], _IDE_REPRESENTATION_CODE):
            ok += 1
    return _ratio(
        name=name,
        numerator=ok,
        denominator=total,
        message_template=(
            "{hits}/{total} JP Patients have at least one name with iso21090-EN-representation = IDE (kanji)"
        ),
    )


def _has_representation(names: list[dict], target_code: str) -> bool:
    for n in names:
        for ext in n.get("extension") or []:
            url = ext.get("url", "")
            if url.endswith(_ISO_21090_EN_REPRESENTATION_SUFFIX) and ext.get("valueCode") == target_code:
                return True
    return False


# --------------------------------------------------------------------------- #
# Encounter checks


def _check_encounter_class_present(encounters: list[dict]) -> EvalCheck:
    name = "jp_core_encounter_class_present"
    total = len(encounters)
    if total == 0:
        return _na(name, "No JP Encounters found.")
    ok = sum(1 for e in encounters if (e.get("class") or {}).get("code"))
    return _ratio(
        name=name,
        numerator=ok,
        denominator=total,
        message_template="{hits}/{total} JP Encounters carry class with a code",
    )


def _check_encounter_period_present(encounters: list[dict]) -> EvalCheck:
    name = "jp_core_encounter_period_present"
    total = len(encounters)
    if total == 0:
        return _na(name, "No JP Encounters found.")
    ok = sum(1 for e in encounters if (e.get("period") or {}).get("start"))
    return _ratio(
        name=name,
        numerator=ok,
        denominator=total,
        message_template="{hits}/{total} JP Encounters carry period.start",
    )


# --------------------------------------------------------------------------- #
# MedicationRequest check


def _check_medicationrequest_medication_coding(mrs: list[dict]) -> EvalCheck:
    """Every JP MedicationRequest must carry
    ``medicationCodeableConcept.coding[]`` (the drug identity).
    ``medicationReference`` alternative is not currently used by
    clinosim, so this check is scoped to the CodeableConcept path.
    Denominator = MedicationRequests with a
    ``medicationCodeableConcept`` element; MRs that use the
    Reference variant would be counted separately if introduced."""
    name = "jp_core_medicationrequest_medication_coding_present"
    total_with_cc = 0
    ok = 0
    for mr in mrs:
        cc = mr.get("medicationCodeableConcept")
        if cc is None:
            continue
        total_with_cc += 1
        if cc.get("coding"):
            ok += 1
    if total_with_cc == 0:
        return _na(
            name,
            "No JP MedicationRequests carry a medicationCodeableConcept.",
        )
    return _ratio(
        name=name,
        numerator=ok,
        denominator=total_with_cc,
        message_template=("{hits}/{total} JP MedicationRequests carry medicationCodeableConcept.coding[]"),
    )


# --------------------------------------------------------------------------- #
# Helpers


def _na(name: str, message: str) -> EvalCheck:
    return EvalCheck(name=name, outcome=Outcome.NA, severity=Severity.MAJOR, message=message)


def _ratio(*, name: str, numerator: int, denominator: int, message_template: str) -> EvalCheck:
    ratio = numerator / denominator
    detail = {"numerator": numerator, "denominator": denominator, "ratio": ratio}
    outcome = Outcome.PASS if ratio >= 1.0 else Outcome.FAIL
    return EvalCheck(
        name=name,
        outcome=outcome,
        severity=Severity.MAJOR,
        message=(message_template + f" — {ratio:.1%}").format(hits=numerator, total=denominator),
        detail=detail,
    )
