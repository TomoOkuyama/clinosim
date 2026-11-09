"""FHIR R4 Condition resource builder (FA-1 conditions).

Extracted verbatim from ``fhir_r4_adapter``. Self-contained: imports only
leaf data, shared helpers, and stdlib/first-party deps — never the adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from typing import Any

from clinosim.codes import data_table, get_system_uri, system_key_for
from clinosim.codes import lookup as code_lookup
from clinosim.codes.icd10 import is_icd10_shaped
from clinosim.codes.snomed import snomed_for
from clinosim.countries import lang_for
from clinosim.locale.i18n import t
from clinosim.locale.loader import condition_stage_display, map_diagnosis_code
from clinosim.modules._shared import get_attr_or_key, is_jp
from clinosim.modules.diagnosis.nonspecific_codes import is_visit_reason_zcode
from clinosim.modules.disease.protocol import load_all_disease_protocols
from clinosim.modules.output.fhir_r4.conditions.primary_ref import (
    CONDITION_KEY_SYSTEM,
    chronic_condition_id,
    chronic_condition_key,
    encounter_admission_condition_id,
    encounter_admission_condition_key,
    encounter_primary_condition_id,
    encounter_primary_condition_key,
    encounter_secondary_condition_id,
    encounter_secondary_condition_key,
    needs_admission_diagnosis_condition,
)
from clinosim.modules.output.fhir_r4.conditions.primary_ref import (
    is_chronic_primary as _encounter_primary_is_chronic,
)
from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
from clinosim.modules.output.fhir_r4.encounters.encounter import encounter_ref
from clinosim.modules.output.fhir_r4.lib.common import (
    build_diagnosis_codeable_concept,
    display_entry,
    dual_slot_concept,
    infer_severity,
    severity_coding,
)
from clinosim.modules.output.fhir_r4.lib.fhir_time import to_fhir_date, to_fhir_datetime
from clinosim.modules.output.fhir_r4.lib.ids import wrap_as_identifier

# Condition.stage.summary SNOMED coding for staging systems with an unambiguous,
# authoritatively-verified (tx.fhir.org $lookup) SNOMED CT concept. Keys are the
# exact stage strings produced by patient.activator._generate_stage — the drift
# guard test_every_generated_stage_is_mapped fails loud if activator adds a value
# without a code here (whitelist-drift bug class).
#
# Post-CO-6 (Chain 4, 2026-07-11): every stage system used by _generate_stage now
# has a verified SNOMED coding. Previously-text-only entries (GOLD 4, asthma
# severity 4-tier, hypertension stage 1-2, CCS angina I-III). Phase 3.β.6
# (#1808 follow-up): the 24-entry stage → SNOMED mapping now lives in
# `clinosim/codes/data/snomed-maps.yaml` (`stage`) and resolves via
# `clinosim.codes.snomed.snomed_for("stage", label)`. The
# authority SNOMED display stays in snomed-ct.yaml and is still fetched
# via `code_lookup("snomed-ct", code, lang)` at emit time.

# CY8-23 fix:Condition.bodySite mapping。
# 特定の解剖学的部位を持つ疾患について SNOMED body structure コードを付与。
# 非部位性(高血圧・糖尿病等)は bodySite emit しない = 100% 化はせず
# 臨床的に意味のある約 17 疾患に絞る。ICD prefix で match、no fabrication。
# Crosswalk + display SoT moved under META #1849 post-review:
#   `clinosim/codes/data/icd10-condition-bodysite-crosswalk.yaml` holds
#   the 17 ICD-10 prefix → SNOMED body-site mapping; displays resolve
#   via `code_lookup("snomed-ct", code, lang)` against snomed-ct.yaml.
#   (hardcoded-audit Finding 9).


@cache
def _icd10_condition_bodysite_map() -> dict[str, str]:
    """Load the ICD-10 prefix → SNOMED body-site crosswalk."""

    raw = data_table("icd10-condition-bodysite-crosswalk")
    return {str(k).upper(): str(v) for k, v in (raw.get("crosswalk", {}) or {}).items()}


# Issue #744: JP-CLINS eCS DiagnosisType extension family.
#
# Spec: `StructureDefinition-jp-ecs-diagnosisType.json`
# - URL: http://jpfhir.jp/fhir/eCS/Extension/StructureDefinition/JP_eCS_DiagnosisType
# - Context: Condition only
# - value[x]: CodeableConcept, binding = http://hl7.org/fhir/ValueSet/ex-diagnosistype|4.0.1
#
# The value-set is the FHIR-standard ex-diagnosistype (Diagnosis Type) — code
# system `http://terminology.hl7.org/CodeSystem/ex-diagnosistype`. JP publishes a
# display overlay CS at
# `http://jpfhir.jp/core/terminology/CodeSystemJPDisplay/ex-diagnosistype`
# which reuses the FHIR codes verbatim, so only the FHIR system URI needs to
# be emitted for terminology conformance.
#
# clinosim maps its two Condition emit paths as follows:
# - encounter-diagnosis (per-encounter reason for visit) → `principal`
# - chronic (problem-list-item, patient-level)         → `clinical`
_JP_ECS_DIAGNOSIS_TYPE_EXT_URL = "http://jpfhir.jp/fhir/eCS/Extension/StructureDefinition/JP_eCS_DiagnosisType"
_EX_DIAGNOSISTYPE_SYSTEM = get_system_uri("hl7-ex-diagnosistype")

# Kept minimal: only the two codes clinosim currently emits. Adding more
# (differential / admitting / discharge / laboratory / radiology / …) is a
# targeted extension, not fabrication — every value in `ex-diagnosistype` is
# spec-defined.
_DIAGNOSIS_TYPE_DISPLAY_EN = {
    "principal": "Principal Diagnosis",
    "clinical": "Clinical Diagnosis",
    # Issue #912: admitting-diagnosis Condition emitted alongside the
    # principal (discharge) Condition when the admission dx differs from the
    # discharge dx and from every chronic Condition — carries the
    # ``Encounter.reasonCode`` code so the invariant
    # ``reasonCode ⊆ diagnosis[].condition.code`` holds.
    "admitting": "Admitting Diagnosis",
    # Issue #1307: working_diagnoses secondary Condition — pregnancy
    # complications carried onto the delivery encounter and in-hospital
    # complications recorded during an active admission.
    "differential": "Differential Diagnosis",
}


def _ecs_diagnosis_type_extension(code: str) -> dict:
    """Return the `JP_eCS_DiagnosisType` extension for a Condition (Issue #744).

    `code` is one of the FHIR standard `ex-diagnosistype` codes
    (see `_DIAGNOSIS_TYPE_DISPLAY_EN`). Caller gates on JP.
    """
    display = _DIAGNOSIS_TYPE_DISPLAY_EN.get(code, code)
    return {
        "url": _JP_ECS_DIAGNOSIS_TYPE_EXT_URL,
        "valueCodeableConcept": {
            "coding": [
                {
                    "system": _EX_DIAGNOSISTYPE_SYSTEM,
                    "code": code,
                    "display": display,
                }
            ]
        },
    }


def _bodysite_for(code: str, country: str) -> dict | None:
    """CY8-23 helper:ICD code prefix から SNOMED bodySite CodeableConcept を返す。"""
    if not code:
        return None
    key3 = code.split(".")[0].upper()
    snomed_code = _icd10_condition_bodysite_map().get(key3)
    if not snomed_code:
        return None
    lang = lang_for(country)
    disp = code_lookup("snomed-ct", snomed_code, lang)
    return {
        "coding": [
            {
                "system": get_system_uri("snomed-ct"),
                "code": snomed_code,
                # Issue #3026: English SNOMED display; the label is text.
                **display_entry(code_lookup("snomed-ct", snomed_code, "en")),
            }
        ],
        **({"text": disp} if disp else {}),
    }


_JP_CONDITION_PROFILE = "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Condition"
# Recorder / asserter for a problem-list Condition when the record has no encounter.
_FALLBACK_RECORDER_ID = "DR-IM-001"


@dataclass(frozen=True)
class _ConditionContext:
    """What every Condition of one CIF record shares."""

    patient_id: str
    country: str
    encounters: list[dict]
    deceased: bool
    patient_sex: str

    @property
    def country_code(self) -> str:
        return "JP" if is_jp(self.country) else "US"

    @property
    def lang(self) -> str:
        return lang_for(self.country_code)

    @property
    def encounter(self) -> dict:
        return self.encounters[0] if self.encounters else {}

    @property
    def encounter_id(self) -> str:
        return self.encounter.get("encounter_id", "")

    @property
    def is_inpatient(self) -> bool:
        return self.encounter.get("encounter_type", "") == "inpatient"

    @property
    def admission_dt(self) -> str:
        return self.encounter.get("admission_datetime", "")

    @property
    def discharge_dt(self) -> str:
        return self.encounter.get("discharge_datetime", "")

    @property
    def resolved_at_discharge(self) -> bool:
        """An inpatient stay that ended with the patient alive."""
        return bool(self.is_inpatient and self.discharge_dt and not self.deceased)

    def mapped(self, code: str) -> str:
        return map_diagnosis_code(code, self.country, sex=self.patient_sex)


def _condition_skeleton(
    ctx: _ConditionContext,
    *,
    condition_id: str,
    structural_key: str,
    diagnosis_type: str | None,
    clinical_status: str,
    category: str,
    mapped_code: str,
) -> dict[str, Any]:
    """The elements every Condition starts with, in emit order. ``diagnosis_type``
    adds the JP eCS DiagnosisType extension after ``meta`` (``None``: no extension)."""
    jp = is_jp(ctx.country_code)
    return {
        "resourceType": "Condition",
        "id": condition_id,
        "identifier": [wrap_as_identifier(structural_key, CONDITION_KEY_SYSTEM)],
        # C2-20: JP Core Condition profile.
        **({"meta": {"profile": [_JP_CONDITION_PROFILE]}} if jp else {}),
        **({"extension": [_ecs_diagnosis_type_extension(diagnosis_type)]} if jp and diagnosis_type else {}),
        "clinicalStatus": dual_slot_concept("hl7-condition-clinical", clinical_status, ctx.lang),
        "verificationStatus": dual_slot_concept("hl7-condition-ver-status", "confirmed", ctx.lang),
        "category": [dual_slot_concept("hl7-condition-category", category, lang_for(ctx.country))],
        "code": build_diagnosis_codeable_concept(
            mapped_code, system_key_for("diagnosis", ctx.country_code), ctx.country
        ),
        "subject": patient_ref(ctx.patient_id),
    }


def _evidence(ctx: _ConditionContext, label_key: str) -> list[dict]:
    """CY6-19: text-only ``Condition.evidence`` naming what supported the
    diagnosis (R4 allows a text-only code; no fabricated coding)."""
    return [{"code": [{"text": t(label_key, ctx.lang)}]}]


def _set_recorder(cond: dict, practitioner_id: str) -> None:
    """C2-31 / CY8-22: the diagnosing physician both records and asserts."""
    cond["recorder"] = {"reference": f"Practitioner/{practitioner_id}"}
    cond["asserter"] = {"reference": f"Practitioner/{practitioner_id}"}


def _stage(stage: str, country: str) -> list[dict]:
    """``Condition.stage`` for a non-cancer clinical stage (NYHA class, CKD G,
    GOLD, hypertension stage, CCS, …): the value in ``summary.text``, plus a
    SNOMED coding when the staging system has a verified concept. ``type`` is a
    plain-text label — the former SNOMED 385356007 "Tumor stage finding" coding
    was clinically wrong for these stages and is intentionally not emitted."""
    # Issue #3032: the label and the stage type in the output language; the
    # SNOMED coding keeps its English display (code-mapping spec 5.3).
    summary: dict[str, Any] = {"text": condition_stage_display(stage, lang_for(country))}
    stage_snomed = snomed_for("stage", stage)
    if stage_snomed:
        summary["coding"] = [
            {
                "system": get_system_uri("snomed-ct"),
                "code": stage_snomed,
                **display_entry(code_lookup("snomed-ct", stage_snomed, "en")),
            }
        ]
    return [{"summary": summary, "type": {"text": t("condition_fhir.stage_type", lang_for(country))}}]


def _set_bodysite(cond: dict, code: str, country: str) -> None:
    """CY8-23: SNOMED ``bodySite`` for anatomically localisable diagnoses."""
    bodysite = _bodysite_for(code, country)
    if bodysite:
        cond["bodySite"] = [bodysite]


def _chronic_fields(chronic: Any) -> tuple[str, str, str, str]:
    """``(code, onset_date, severity, stage)`` of a chronic condition given as
    a bare code, a dict (production JSON path) or a ``ChronicCondition``
    dataclass (in-memory path)."""
    if isinstance(chronic, str):
        return chronic, "", "", ""
    return (
        get_attr_or_key(chronic, "code", ""),
        get_attr_or_key(chronic, "onset_date", ""),
        get_attr_or_key(chronic, "severity", ""),
        get_attr_or_key(chronic, "stage", ""),
    )


def _build_conditions(record: dict, patient_id: str, country: str) -> list[dict]:
    """Build FHIR Condition resources from diagnosis and chronic conditions.

    Generates, in order: the primary encounter diagnosis, the admission
    diagnosis, secondary (working) diagnoses, the patient's chronic
    conditions and past births. Deduplicates by ICD base code.
    """
    ctx = _ConditionContext(
        patient_id=patient_id,
        country=country,
        encounters=record.get("encounters", []),
        deceased=record.get("deceased", False),
        # Issue #957: US ICD-10-CM C50 splits into female (C50.919) / male
        # (C50.929) billable leaves, so every ``map_diagnosis_code`` call is
        # per-person. JP C50 is identity-mapped, so the sex is a no-op there.
        patient_sex=str(record.get("patient", {}).get("sex", "") or ""),
    )
    dx = record.get("clinical_diagnosis", {})
    chronic_list = record.get("patient", {}).get("chronic_conditions", [])
    seen_codes: set[str] = set()

    conditions: list[dict] = []
    primary = _primary_condition(ctx, record, dx, chronic_list, seen_codes)
    if primary is not None:
        conditions.append(primary)
    admission = _admission_condition(ctx, dx, chronic_list)
    if admission is not None:
        conditions.append(admission)
    conditions.extend(_secondary_conditions(ctx, dx, seen_codes))
    conditions.extend(_chronic_conditions(ctx, chronic_list, seen_codes))
    conditions.extend(_past_birth_conditions(ctx, record, seen_codes))
    return conditions


def _primary_condition(
    ctx: _ConditionContext, record: dict, dx: dict, chronic_list: list, seen_codes: set[str]
) -> dict | None:
    """The encounter's primary (discharge, else admission) diagnosis."""
    dx_code = dx.get("discharge_diagnosis_code") or dx.get("admission_diagnosis_code", "")
    # Issue #916: Z-chapter visit-reason codes (Z00.0 general medical,
    # Z09 follow-up, Z23 immunization, Z12/Z13 screening, …) are not
    # clinical Conditions — they describe *reasons for encountering the
    # health system*. They already appear on ``Encounter.reasonCode``
    # (encounter.py) and ``Immunization`` (self-describing resource);
    # emitting a duplicate resolved same-day ``Condition`` for them
    # pollutes the problem list. 43.3 % of Conditions at v0.5.0 were
    # Z-code pseudo-diagnoses; the fix here is to skip the Condition
    # emission (encounter.py mirror in the ``diagnosis[]`` /
    # ``reasonReference`` slots so no dangling refs remain).
    if not dx_code or is_visit_reason_zcode(dx_code) or _encounter_primary_is_chronic(record):
        return None
    base_code = dx_code.split(".")[0]
    seen_codes.add(base_code)

    # The patient's chronic conditions by ICD base. C4-05 / C4-07..09: a
    # chronic primary also inherits their severity and stage when
    # infer_severity returns empty (routine outpatient follow-up with no
    # physiological states — 65.8% of I10 lacked severity before).
    chronic_onset_by_base: dict[str, str] = {}
    chronic_severity_by_base: dict[str, str] = {}
    chronic_stage_by_base: dict[str, str] = {}
    for chronic in chronic_list:
        code, onset, severity_, stage = _chronic_fields(chronic)
        if code:
            base = code.split(".")[0]
            chronic_onset_by_base.setdefault(base, onset or "")
            chronic_severity_by_base.setdefault(base, severity_ or "")
            chronic_stage_by_base.setdefault(base, stage or "")

    # Determine severity from physiological states
    severity = infer_severity(record)

    # A primary diagnosis that is one of the patient's chronic conditions
    # (e.g. an outpatient diabetes follow-up coding E11.9) is ongoing, not
    # resolved at the visit: mark it active with the chronic onset date.
    is_chronic_primary = base_code in chronic_onset_by_base
    chronic_onset = chronic_onset_by_base.get(base_code, "") if is_chronic_primary else ""
    # C4-05: chronic-primary severity fallback, so problem-list severity is
    # consistent with the encounter diagnosis.
    if not severity and is_chronic_primary:
        severity = chronic_severity_by_base.get(base_code, "")
    # CY6-21 (Chain-6): acute encounter-diagnosis severity fallback.
    # ED visits sampled from encounter YAMLs carry a severity category
    # ("mild"/"moderate"/"severe") on Encounter (AD-65 Bug C
    # fix stored it as Encounter.severity). Use it when neither the
    # physiological-state inference nor chronic inheritance produced a
    # severity, so acute non-chronic Z00 / R07 / T14 / etc. no longer
    # emit without severity. Only fires for non-Z encounter dx (Z-codes
    # denote health-check / preventive care where severity is absent
    # by design).
    if not severity and not base_code.startswith("Z"):
        enc_severity = ctx.encounter.get("severity", "") or ""
        if enc_severity:
            severity = enc_severity

    # clinicalStatus: resolved if discharged alive, active if deceased (didn't resolve)
    if is_chronic_primary:
        clinical_status = "active"
    elif ctx.is_inpatient:
        clinical_status = "active" if ctx.deceased or not ctx.discharge_dt else "resolved"
    else:
        clinical_status = "resolved"

    # Issue #854 Bucket B (PR-condition): opaque Condition.id.
    # Structural key = pre-#854 id body (without ``cond-`` prefix).
    cond = _condition_skeleton(
        ctx,
        condition_id=encounter_primary_condition_id(ctx.patient_id, ctx.encounter_id),
        structural_key=encounter_primary_condition_key(ctx.patient_id, ctx.encounter_id),
        diagnosis_type=None,
        clinical_status=clinical_status,
        category="encounter-diagnosis",
        mapped_code=ctx.mapped(dx_code),
    )
    # Issue #744: JP_Condition_eCS must-support `extension:eCS_DiagnosisType`
    # (spec binding: http://hl7.org/fhir/ValueSet/ex-diagnosistype|4.0.1).
    # Encounter-diagnosis Condition is the reason-for-visit → `principal`
    # (matches the FHIR-standard code and the JP display CS
    # `http://jpfhir.jp/core/terminology/CodeSystemJPDisplay/ex-diagnosistype`).
    # Placed after `subject`, unlike the other kinds.
    if is_jp(ctx.country_code):
        cond.setdefault("extension", []).append(_ecs_diagnosis_type_extension("principal"))

    if severity:
        cond["severity"] = severity_coding(severity, ctx.country)

    # For chronic-primary: prior established diagnosis; for acute: clinical
    # presentation + supporting labs.
    cond["evidence"] = _evidence(
        ctx, "condition_evidence.prior_diagnosis" if is_chronic_primary else "condition_evidence.clinical_and_labs"
    )

    # C4-07..10: a staged chronic primary (DM/COPD/HF/CKD) carries the same
    # stage as the patient's problem-list entry for the same disease.
    if is_chronic_primary:
        stage = chronic_stage_by_base.get(base_code, "")
        if stage:
            cond["stage"] = _stage(stage, ctx.country)

    if chronic_onset:
        # Chronic primary: onset is the disease onset date (typically month-year
        # granularity; keep as date-only). recordedDate is the visit — use full
        # datetime from admission so time-series UIs sort correctly.
        cond["onsetDateTime"] = to_fhir_date(chronic_onset)
        if ctx.admission_dt:
            cond["recordedDate"] = to_fhir_datetime(ctx.admission_dt)
    elif ctx.admission_dt:
        # Encounter-diagnosis onset = admission time (full datetime). Issue #821
        # (N-7): consumer time-series UIs sort by these fields and were
        # broken by date-only precision.
        cond["onsetDateTime"] = to_fhir_datetime(ctx.admission_dt)
        cond["recordedDate"] = cond["onsetDateTime"]

    if ctx.encounters:
        cond["encounter"] = encounter_ref(ctx.encounter_id)
        attending = ctx.encounter.get("attending_physician_id", "")
        if attending:
            _set_recorder(cond, attending)

    # CY8-24: abatementDateTime = discharge for an acute episode (cellulitis,
    # pneumonia, …) whose encounter has completed. Chain F: never for a
    # chronic primary (clinicalStatus=active + abatement violates R4 `con-4`)
    # nor for a deceased patient (the diagnosis did not resolve).
    if ctx.encounters and not is_chronic_primary and not ctx.deceased:
        discharge = ctx.encounter.get("discharge_datetime", "")
        if discharge and ctx.encounter.get("status", "") in ("completed", "finished"):
            # Issue #821 (N-7): abatement is the discharge time (full datetime).
            cond["abatementDateTime"] = to_fhir_datetime(discharge)

    _set_bodysite(cond, dx_code, ctx.country)
    return cond


def _admission_condition(ctx: _ConditionContext, dx: dict, chronic_list: list) -> dict | None:
    """Issue #912: an admitting-diagnosis Condition when the admission dx differs
    from the primary dx and from every chronic Condition, so the invariant
    ``Encounter.reasonCode ⊆ diagnosis[].condition.code`` holds (45.4% of IMP
    encounters had an orphaned admission dx before). The encounter builder
    mirrors this decision (same helper) for its ``diagnosis[].use=AD`` entry.

    Its ICD base is deliberately not added to ``seen_codes``: e.g. a COPD
    exacerbation admission keeps three rows (primary J44.0 / admission J44.1 /
    chronic J44) as the audit trail."""
    admit_raw = dx.get("admission_diagnosis_code", "") or ""
    primary_raw = dx.get("discharge_diagnosis_code") or admit_raw
    # Issue #916: skip Z-chapter visit-reason codes (mirrors the primary path).
    if admit_raw and is_visit_reason_zcode(admit_raw):
        admit_raw = ""
    chronic_raw = [code for code in (_chronic_fields(c)[0] or "" for c in chronic_list) if code]
    admit_mapped = ctx.mapped(admit_raw) if admit_raw else ""
    primary_mapped = ctx.mapped(primary_raw) if primary_raw else ""
    chronic_mapped = [ctx.mapped(c) for c in chronic_raw]
    # Issue #1341: the raw AND the mapped codes must both say "admission dx is
    # orphaned". With OR, a JP hip fracture (admit S72.0, discharge S72.00 →
    # both S72.0 after mapping) emitted two S72.0 Conditions on one encounter.
    if not (
        ctx.encounter_id
        and needs_admission_diagnosis_condition(admit_raw, primary_raw, chronic_raw)
        and needs_admission_diagnosis_condition(admit_mapped, primary_mapped, chronic_mapped)
    ):
        return None
    cond = _condition_skeleton(
        ctx,
        condition_id=encounter_admission_condition_id(ctx.patient_id, ctx.encounter_id),
        structural_key=encounter_admission_condition_key(ctx.patient_id, ctx.encounter_id),
        diagnosis_type="admitting",
        # The working diagnosis at admission: resolved at a live discharge
        # (same rule as the primary path), active otherwise.
        clinical_status="resolved" if ctx.resolved_at_discharge else "active",
        category="encounter-diagnosis",
        mapped_code=admit_mapped,
    )
    # ``code.text`` takes the leaf display so it equals ``Encounter.reasonCode.text``
    # (the short name folds J44.1 to "COPD", not "COPD急性増悪"). Only when a
    # distinct leaf display exists.
    icd_system_key = system_key_for("diagnosis", ctx.country_code)
    leaf_display = code_lookup(icd_system_key, admit_mapped, ctx.lang) if admit_mapped else ""
    if leaf_display and leaf_display != admit_mapped:
        cond["code"]["text"] = leaf_display
    if ctx.encounters:
        cond["encounter"] = encounter_ref(ctx.encounter_id)
        attending = ctx.encounter.get("attending_physician_id", "") or ctx.encounter.get("admitting_physician_id", "")
        if attending:
            _set_recorder(cond, attending)
    if ctx.admission_dt:
        cond["onsetDateTime"] = to_fhir_datetime(ctx.admission_dt)
        cond["recordedDate"] = cond["onsetDateTime"]
    if ctx.resolved_at_discharge:
        cond["abatementDateTime"] = to_fhir_datetime(ctx.discharge_dt)
    _set_bodysite(cond, admit_raw, ctx.country)
    cond["evidence"] = _evidence(ctx, "condition_evidence.admission_assessment")
    return cond


def _working_diagnosis_code(value: str) -> str:
    """ICD-10 code of a ``working_diagnoses[].disease_id`` (Issue #3028).

    Pregnancy complications and lab-derived diagnoses store an ICD code there;
    an in-hospital new disease (``simulator/_dispatch.py``) stores its disease
    id, which resolves to that protocol's primary ICD code. Anything else is
    ``""`` — a disease key is never emitted as an ICD code."""
    if is_icd10_shaped(value):
        return value
    protocol = load_all_disease_protocols().get(value)
    primary = str((protocol.icd_codes or {}).get("primary") or "") if protocol is not None else ""
    return primary if is_icd10_shaped(primary) else ""


def _secondary_conditions(ctx: _ConditionContext, dx: dict, seen_codes: set[str]) -> list[dict]:
    """Issue #1307: one encounter-diagnosis Condition per
    ``clinical_diagnosis.working_diagnoses`` entry — pregnancy complications
    carried onto the delivery encounter (``simulator/perinatal.py``) and
    in-hospital complications (``simulator/engine.py::
    _record_complication_on_active_encounter``)."""
    conditions: list[dict] = []
    for idx, wd in enumerate(dx.get("working_diagnoses") or []):
        code_raw = _working_diagnosis_code(str((wd.get("disease_id") or "") if isinstance(wd, dict) else ""))
        if not code_raw:
            continue
        base = code_raw.split(".")[0]
        # The primary / a chronic Condition already owns this ICD base.
        if base in seen_codes:
            continue
        seen_codes.add(base)
        mapped = ctx.mapped(code_raw)
        if not mapped:
            continue
        onset_dt = str(wd.get("onset_datetime") or "") if isinstance(wd, dict) else ""
        source = str(wd.get("source") or "") if isinstance(wd, dict) else ""
        cond = _condition_skeleton(
            ctx,
            condition_id=encounter_secondary_condition_id(ctx.patient_id, ctx.encounter_id, idx),
            structural_key=encounter_secondary_condition_key(ctx.patient_id, ctx.encounter_id, idx),
            # "differential" is the closest ``ex-diagnosistype`` code for an
            # entry under active consideration; "secondary" is not in that value set.
            diagnosis_type="differential",
            clinical_status="resolved" if ctx.resolved_at_discharge else "active",
            category="encounter-diagnosis",
            mapped_code=mapped,
        )
        if ctx.encounters:
            cond["encounter"] = encounter_ref(ctx.encounter_id)
            attending = ctx.encounter.get("attending_physician_id", "")
            if attending:
                _set_recorder(cond, attending)
        if onset_dt:
            cond["onsetDateTime"] = to_fhir_datetime(onset_dt)
            cond["recordedDate"] = cond["onsetDateTime"]
        elif ctx.admission_dt:
            cond["onsetDateTime"] = to_fhir_datetime(ctx.admission_dt)
            cond["recordedDate"] = cond["onsetDateTime"]
        if ctx.resolved_at_discharge:
            cond["abatementDateTime"] = to_fhir_datetime(ctx.discharge_dt)
        # Tell an in-hospital complication from a carried-over pregnancy
        # complication without parsing ICD chapters.
        cond["evidence"] = _evidence(
            ctx,
            "condition_evidence.in_hospital_complication"
            if source == "in_hospital_complication"
            else "condition_evidence.secondary_diagnosis",
        )
        _set_bodysite(cond, code_raw, ctx.country)
        conditions.append(cond)
    return conditions


def _chronic_conditions(ctx: _ConditionContext, chronic_list: list, seen_codes: set[str]) -> list[dict]:
    """One problem-list-item Condition per chronic condition the patient carries."""
    conditions: list[dict] = []
    for i, chronic in enumerate(chronic_list):
        code, onset, severity, stage = _chronic_fields(chronic)
        if not code:
            continue
        base = code.split(".")[0]
        if base in seen_codes:
            continue
        seen_codes.add(base)
        cond = _condition_skeleton(
            ctx,
            # C4-02: patient-scoped id so the per-encounter re-emissions collapse
            # in the adapter's dedup (was 10x the realistic problem-list count).
            condition_id=chronic_condition_id(ctx.patient_id, i),
            structural_key=chronic_condition_key(ctx.patient_id, i),
            # Issue #744: a general clinical finding, not the encounter's reason.
            diagnosis_type="clinical",
            clinical_status="active",
            category="problem-list-item",
            mapped_code=ctx.mapped(code),
        )
        if severity:
            cond["severity"] = severity_coding(severity, ctx.country)
        cond["evidence"] = _evidence(ctx, "condition_evidence.problem_list_prior")
        if stage:
            cond["stage"] = _stage(stage, ctx.country)
        if onset:
            cond["onsetDateTime"] = to_fhir_date(onset)
        # CY8-21: a patient with no encounter in the record falls back to the
        # hospital's primary-care physician as recorder / asserter.
        _set_recorder(cond, ctx.encounter.get("attending_physician_id", "") or _FALLBACK_RECORDER_ID)
        # recordedDate: use admission datetime (full time) so time-series UIs sort correctly (Issue #821 / N-7).
        if ctx.admission_dt:
            cond["recordedDate"] = to_fhir_datetime(ctx.admission_dt)
        _set_bodysite(cond, code, ctx.country)
        conditions.append(cond)
    return conditions


# SNOMED CT 271903000 "History of pregnancy" (tx.fhir.org $lookup, 2026-11-06).
_HISTORY_OF_PREGNANCY_SNOMED = "271903000"


def _history_of_pregnancy_code(lang: str) -> dict[str, Any]:
    """Issue #2788: the code of a past birth with no recorded complication."""
    display = code_lookup("snomed-ct", _HISTORY_OF_PREGNANCY_SNOMED, lang)
    return {
        "coding": [
            {
                "system": get_system_uri("snomed-ct"),
                "code": _HISTORY_OF_PREGNANCY_SNOMED,
                **display_entry(code_lookup("snomed-ct", _HISTORY_OF_PREGNANCY_SNOMED, "en")),
            }
        ],
        **({"text": display} if display else {}),
    }


def _past_birth_conditions(ctx: _ConditionContext, record: dict, seen_codes: set[str]) -> list[dict]:
    """META #957 / #1092: one problem-list-item per delivered pregnancy,
    anchored at the delivery date: Z87.59 (personal history of complications
    of pregnancy, childbirth and the puerperium) when the pregnancy recorded a
    complication, otherwise SNOMED CT 271903000 History of pregnancy (Issue #2788). Z37.x belongs only on the
    delivery encounter's own Condition."""
    conditions: list[dict] = []
    # A dict on the FHIR emit path; a live TemporalStatePeriod in tests.
    for period in record.get("patient", {}).get("state_periods", []) or []:
        if get_attr_or_key(period, "state_type", "") != "pregnancy":
            continue
        if get_attr_or_key(period, "outcome", "") != "delivered":
            continue
        end_date = get_attr_or_key(period, "end_date", "") or ""
        if not end_date:
            continue
        # Defensive: Z87 is not a chronic code, so this is not an expected path.
        if "Z87" in seen_codes:
            break
        seq = len(conditions)
        cond = _condition_skeleton(
            ctx,
            condition_id=f"cond-past-birth-{ctx.patient_id}-{seq}",
            structural_key=f"pregnancy-past-birth|{ctx.patient_id}|{seq}",
            diagnosis_type="clinical",
            clinical_status="active",
            category="problem-list-item",
            mapped_code=ctx.mapped("Z87.59"),
        )
        # Issue #2788: Z87.59 asserts a complication; a birth without a
        # recorded pregnancy complication is a history of pregnancy.
        metadata = get_attr_or_key(period, "metadata", {}) or {}
        if not (metadata.get("complications") or []):
            cond["code"] = _history_of_pregnancy_code(ctx.lang)
        cond["onsetDateTime"] = to_fhir_date(end_date)
        cond["evidence"] = _evidence(ctx, "condition_evidence.problem_list_prior")
        _set_recorder(cond, ctx.encounter.get("attending_physician_id", "") or _FALLBACK_RECORDER_ID)
        if ctx.admission_dt:
            cond["recordedDate"] = to_fhir_datetime(ctx.admission_dt)
        conditions.append(cond)
    return conditions
