"""US Core narrow-gate compliance axis.

Purpose
-------
Measure a **narrow** subset of US Core AllPatients / Encounter /
Condition must-support element compliance on the generator side,
WITHOUT depending on the external HL7 FHIR Validator. Runs per PR
as a fast (~1 min) invariant check; the full validator run
(``us-validate.yml``, Phase 3) remains the authoritative on-demand
compliance surface.

This axis is intentionally **narrow-list-first** (Issue #1418
guidance): only invariants that hold at 100 % on master today are
gated at ``threshold=1.0``. Elements whose baseline emit is not yet
100 % (e.g. race / ethnicity extension coverage when
PatientProfile.race is an unknown slug per
[[feedback_empty_vs_wrong_assertion]]) are shape-checked with a
denominator = "has ext", so silent shape drift is caught even
though partial-coverage is by design.

Checks
------
1. **us_core_patient_identifier_present** — every US Patient carries
   at least one identifier (must-support on US Core AllPatients).
2. **us_core_patient_name_family_given** — every US Patient has at
   least one name with both ``family`` and ``given`` set.
3. **us_core_patient_birthsex_extension_valid** — every US Patient
   carries the ``us-core-birthsex`` extension with a valid valueCode
   (M / F / UNK / OTH / ASKU per HL7 v3 AdministrativeGender).
4. **us_core_patient_race_extension_shape** — of US Patients that
   emit ``us-core-race``, all have the correct nested-extension shape
   (``ombCategory.valueCoding.system = urn:oid:2.16.840.1.113883.6.238``
   + ``text.valueString`` present). ``NA`` when no Patient emits the
   extension (pre-migration state) so shape-check zero and coverage
   zero are distinguishable.
5. **us_core_patient_ethnicity_extension_shape** — same for
   ``us-core-ethnicity`` (same OMB CodeSystem OID).
6. **us_core_encounter_class_v3_actcode** — every US Encounter's
   ``class.system`` is the HL7 v3 ActCode CodeSystem
   (``http://terminology.hl7.org/CodeSystem/v3-ActCode``) — the
   binding US Core requires.
7. **us_core_condition_category_system** — every US Condition
   ``category.coding.system`` is the FHIR condition-category
   CodeSystem (``http://terminology.hl7.org/CodeSystem/condition-category``).

Applicability
-------------
Axis returns an empty list on non-US cohorts — mirrored on the JP
side by ``jp_core_compliance`` (Phase 1 companion axis).

CI Invariant Thresholds
-----------------------
All checks: ``threshold = 1.0``, ``severity = MAJOR``. A single
below-1.0 metric flips the axis FAIL, which triggers
``clinosim eval --strict`` exit code 1 (CI gate failure). One
narrow gate per locale (this + JP), each meant to catch the class
of silent-pass bugs the S114 verify pattern surfaced (#1412 /
#1416) inside 1 minute per PR without waiting for the full
validator run.

Rationale for narrowness
------------------------
See Issue #1418 body: must-support element curation is high-value
but high-risk (false-fail → PR stall = worse than no gate). The
seven checks above were chosen because a p=100 s=300 US cohort
proves them at 100 % on master today (2026-09-14), so this gate
starts green and any drop signals a real regression. Additional
must-support elements (US Core Observation vitals category,
Coverage.subscriber, MedicationRequest requester, US Core
Immunization series data) are next-session expansion candidates.
"""

from __future__ import annotations

from clinosim.audit.types import Cohort
from clinosim.eval.axes.locale import _detect_country_from_cohort, _read
from clinosim.eval.engine import EvalCheck, Outcome, Severity

# --------------------------------------------------------------------------- #
# US Core canonical URLs — sourced from emit-side constants (single source of
# truth). If the emit URL ever drifts, the axis catches it because the URL is
# what the axis matches against, not a re-derived copy.

_US_CORE_RACE_URL = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race"
_US_CORE_ETHNICITY_URL = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity"
_US_CORE_BIRTHSEX_URL = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-birthsex"

# HL7 v3 AdministrativeGender ValueSet — the US Core birthsex extension's
# valueCode binding.
_BIRTHSEX_VALID_CODES: frozenset[str] = frozenset({"M", "F", "UNK", "OTH", "ASKU"})

# CDC Race and Ethnicity OMB CodeSystem OID — required by US Core race +
# ethnicity extension ombCategory sub-extension.
_OMB_RACE_ETHNICITY_OID = "urn:oid:2.16.840.1.113883.6.238"

# HL7 v3 ActCode CodeSystem — the US Core Encounter.class binding.
_V3_ACTCODE_SYSTEM = "http://terminology.hl7.org/CodeSystem/v3-ActCode"

# FHIR condition-category CodeSystem — US Core Condition.category binding.
_CONDITION_CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-category"


# --------------------------------------------------------------------------- #
# Axis entrypoint


def run(cohort: Cohort, country: str) -> list[EvalCheck]:
    """7-check US Core narrow-gate compliance axis. No-op on non-US cohorts."""
    if _detect_country_from_cohort(cohort, country) != "US":
        return []
    patients = list(_read(cohort, country, "Patient"))
    encounters = list(_read(cohort, country, "Encounter"))
    conditions = list(_read(cohort, country, "Condition"))
    return [
        _check_patient_identifier(patients),
        _check_patient_name_family_given(patients),
        _check_patient_birthsex_extension(patients),
        _check_patient_race_extension_shape(patients),
        _check_patient_ethnicity_extension_shape(patients),
        _check_encounter_class_v3_actcode(encounters),
        _check_condition_category_system(conditions),
    ]


# --------------------------------------------------------------------------- #
# Patient checks


def _check_patient_identifier(patients: list[dict]) -> EvalCheck:
    name = "us_core_patient_identifier_present"
    total = len(patients)
    if total == 0:
        return _na(name, "No US Patients found.")
    missing = sum(1 for p in patients if not p.get("identifier"))
    return _ratio(
        name=name,
        numerator=total - missing,
        denominator=total,
        message_template="{hits}/{total} US Patients carry at least one identifier",
    )


def _check_patient_name_family_given(patients: list[dict]) -> EvalCheck:
    name = "us_core_patient_name_family_given"
    total = len(patients)
    if total == 0:
        return _na(name, "No US Patients found.")
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
        message_template="{hits}/{total} US Patients have name.family + name.given",
    )


def _check_patient_birthsex_extension(patients: list[dict]) -> EvalCheck:
    name = "us_core_patient_birthsex_extension_valid"
    total = len(patients)
    if total == 0:
        return _na(name, "No US Patients found.")
    ok = 0
    for p in patients:
        for ext in p.get("extension") or []:
            if ext.get("url") == _US_CORE_BIRTHSEX_URL:
                if ext.get("valueCode") in _BIRTHSEX_VALID_CODES:
                    ok += 1
                break
    return _ratio(
        name=name,
        numerator=ok,
        denominator=total,
        message_template="{hits}/{total} US Patients have us-core-birthsex ext with valid valueCode",
    )


def _check_patient_race_extension_shape(patients: list[dict]) -> EvalCheck:
    """Denominator = US Patients that emit ``us-core-race``. Numerator =
    subset whose ``ombCategory`` sub-extension carries the OMB
    CodeSystem OID and a ``text`` sub-extension is present. NA when no
    Patient emits the extension (pre-migration state)."""
    name = "us_core_patient_race_extension_shape"
    return _shape_check_omb(
        patients=patients,
        ext_url=_US_CORE_RACE_URL,
        name=name,
        label="race",
    )


def _check_patient_ethnicity_extension_shape(patients: list[dict]) -> EvalCheck:
    name = "us_core_patient_ethnicity_extension_shape"
    return _shape_check_omb(
        patients=patients,
        ext_url=_US_CORE_ETHNICITY_URL,
        name=name,
        label="ethnicity",
    )


def _shape_check_omb(*, patients: list[dict], ext_url: str, name: str, label: str) -> EvalCheck:
    with_ext = 0
    valid_shape = 0
    for p in patients:
        for ext in p.get("extension") or []:
            if ext.get("url") != ext_url:
                continue
            with_ext += 1
            sub_exts = ext.get("extension") or []
            has_omb = any(
                s.get("url") == "ombCategory" and (s.get("valueCoding") or {}).get("system") == _OMB_RACE_ETHNICITY_OID
                for s in sub_exts
            )
            has_text = any(s.get("url") == "text" and s.get("valueString") for s in sub_exts)
            if has_omb and has_text:
                valid_shape += 1
            break
    if with_ext == 0:
        return EvalCheck(
            name=name,
            outcome=Outcome.NA,
            severity=Severity.MAJOR,
            message=(
                f"No US Patient emits us-core-{label} — pre-migration baseline. "
                f"When emit lands, this check re-activates without code change."
            ),
            detail={"numerator": 0, "denominator": 0},
        )
    return _ratio(
        name=name,
        numerator=valid_shape,
        denominator=with_ext,
        message_template=(
            "{hits}/{total} US Patients with us-core-" + label + " have valid OMB shape "
            "(ombCategory.valueCoding.system + text.valueString)"
        ),
    )


# --------------------------------------------------------------------------- #
# Encounter check


def _check_encounter_class_v3_actcode(encounters: list[dict]) -> EvalCheck:
    """US Core requires Encounter.class binding to the HL7 v3 ActCode
    CodeSystem. Absent-system Encounter.class is also a fail (US Core
    treats class as a Coding with an actual code)."""
    name = "us_core_encounter_class_v3_actcode"
    total = len(encounters)
    if total == 0:
        return _na(name, "No US Encounters found.")
    ok = 0
    for enc in encounters:
        cls = enc.get("class") or {}
        if cls.get("system") == _V3_ACTCODE_SYSTEM and cls.get("code"):
            ok += 1
    return _ratio(
        name=name,
        numerator=ok,
        denominator=total,
        message_template=(
            "{hits}/{total} US Encounters carry class with v3-ActCode system "
            "(http://terminology.hl7.org/CodeSystem/v3-ActCode)"
        ),
    )


# --------------------------------------------------------------------------- #
# Condition check


def _check_condition_category_system(conditions: list[dict]) -> EvalCheck:
    """US Core Condition requires category with the FHIR condition-category
    CodeSystem. Denominator = US Conditions with any category coding."""
    name = "us_core_condition_category_system"
    total_with_cat = 0
    ok = 0
    for cond in conditions:
        cats = cond.get("category") or []
        codings = [c for cat in cats for c in (cat.get("coding") or [])]
        if not codings:
            continue
        total_with_cat += 1
        if all(c.get("system") == _CONDITION_CATEGORY_SYSTEM for c in codings):
            ok += 1
    if total_with_cat == 0:
        return _na(
            "us_core_condition_category_system",
            "No US Condition rows carry a category coding.",
        )
    return _ratio(
        name=name,
        numerator=ok,
        denominator=total_with_cat,
        message_template=("{hits}/{total} US Conditions with a category use only the condition-category CS"),
    )


# --------------------------------------------------------------------------- #
# Helpers


def _na(name: str, message: str) -> EvalCheck:
    return EvalCheck(name=name, outcome=Outcome.NA, severity=Severity.MAJOR, message=message)


def _ratio(*, name: str, numerator: int, denominator: int, message_template: str) -> EvalCheck:
    """threshold=1.0 strict. denominator > 0 required (callers screen NA
    themselves)."""
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
