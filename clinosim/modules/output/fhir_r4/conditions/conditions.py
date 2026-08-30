"""FHIR R4 Condition resource builder (FA-1 conditions).

Extracted verbatim from ``fhir_r4_adapter``. Self-contained: imports only
leaf data, shared helpers, and stdlib/first-party deps — never the adapter.
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri, system_key_for
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key, is_jp, resolve_lang
from clinosim.modules.output.fhir_r4.conditions.primary_ref import (
    CONDITION_KEY_SYSTEM,
    chronic_condition_id,
    chronic_condition_key,
    encounter_admission_condition_id,
    encounter_admission_condition_key,
    encounter_primary_condition_id,
    encounter_primary_condition_key,
    needs_admission_diagnosis_condition,
)
from clinosim.modules.output.fhir_r4.conditions.primary_ref import (
    is_chronic_primary as _encounter_primary_is_chronic,
)
from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
from clinosim.modules.output.fhir_r4.encounters.encounter import encounter_ref
from clinosim.modules.output.fhir_r4.lib.common import (
    _coding_with_display,
    build_diagnosis_codeable_concept,
    infer_severity,
    map_diagnosis_code,
    severity_coding,
    to_fhir_date,
    to_fhir_datetime,
)
from clinosim.modules.output.fhir_r4.lib.ids import wrap_as_identifier
from clinosim.modules.output.fhir_r4.lib.localization import (
    _CATEGORY_DISPLAY_JA,
    _localize_display,
)

# Condition.stage.summary SNOMED coding for staging systems with an unambiguous,
# authoritatively-verified (tx.fhir.org $lookup) SNOMED CT concept. Keys are the
# exact stage strings produced by patient.activator._generate_stage — the drift
# guard test_every_generated_stage_is_mapped fails loud if activator adds a value
# without a code here (whitelist-drift bug class).
#
# Post-CO-6 (Chain 4, 2026-07-11): every stage system used by _generate_stage now
# has a verified SNOMED coding. Previously-text-only entries (GOLD 4, asthma
# severity 4-tier, hypertension stage 1-2, CCS angina I-III) verified via
# tx.fhir.org $lookup this session.
_STAGE_SUMMARY_SNOMED: dict[str, str] = {
    "CKD G1": "431855005",
    "CKD G2": "431856006",
    "CKD G3a": "700378005",
    "CKD G3b": "700379002",
    "CKD G4": "431857002",
    "CKD G5": "433146000",
    "NYHA I": "420300004",
    "NYHA II": "421704003",
    "NYHA III": "420913000",
    "NYHA IV": "422293003",
    # COPD severity — GOLD 1/2/3 verified (RM-4); GOLD 4 mapped
    # to SNOMED 135836000 "End stage COPD" (clinical equivalence; no distinct
    # "Very severe COPD" concept exists in SNOMED CT International Edition).
    "GOLD 1": "313296004",
    "GOLD 2": "313297008",
    "GOLD 3": "313299006",
    "GOLD 4": "135836000",
    # Asthma severity 4-tier (J45)
    "Mild intermittent": "427679007",
    "Mild persistent": "426979002",
    "Moderate persistent": "427295004",
    "Severe persistent": "426656000",
    # Hypertension stage (I10) — Stage 1/2 per ACC/AHA 2017 boundaries
    "Stage 1": "827069000",
    "Stage 2": "827068008",
    # CCS angina class (I25) — Canadian Cardiovascular Society I-IV
    # (activator currently emits I/II/III only; IV registered forward-compat)
    "CCS I": "61490001",
    "CCS II": "41334000",
    "CCS III": "85284003",
    "CCS IV": "89323001",
}

# CY8-23 fix:Condition.bodySite mapping。
# 特定の解剖学的部位を持つ疾患について SNOMED body structure コードを付与。
# 非部位性(高血圧・糖尿病等)は bodySite emit しない = 100% 化はせず
# 臨床的に意味のある約 15 疾患に絞る。ICD prefix で match、no fabrication。
_CONDITION_BODY_SITE: dict[str, dict[str, str]] = {
    # 呼吸器
    "J18": {"code": "39607008", "display_en": "Lung structure", "display_ja": "肺"},
    "J13": {"code": "39607008", "display_en": "Lung structure", "display_ja": "肺"},
    "J14": {"code": "39607008", "display_en": "Lung structure", "display_ja": "肺"},
    "J15": {"code": "39607008", "display_en": "Lung structure", "display_ja": "肺"},
    "J44": {"code": "39607008", "display_en": "Lung structure", "display_ja": "肺"},
    "J45": {"code": "955009", "display_en": "Bronchial structure", "display_ja": "気管支"},
    # 心血管
    "I21": {"code": "80891009", "display_en": "Heart structure", "display_ja": "心臓"},
    "I25": {"code": "80891009", "display_en": "Heart structure", "display_ja": "心臓"},
    "I50": {"code": "80891009", "display_en": "Heart structure", "display_ja": "心臓"},
    # 脳血管
    "I63": {"code": "12738006", "display_en": "Brain structure", "display_ja": "脳"},
    "I61": {"code": "12738006", "display_en": "Brain structure", "display_ja": "脳"},
    "I60": {"code": "12738006", "display_en": "Brain structure", "display_ja": "脳"},
    # 泌尿器
    "N10": {"code": "64033007", "display_en": "Kidney structure", "display_ja": "腎臓"},
    "N17": {"code": "64033007", "display_en": "Kidney structure", "display_ja": "腎臓"},
    "N39": {"code": "89837001", "display_en": "Urinary bladder structure", "display_ja": "膀胱"},
    "N30": {"code": "89837001", "display_en": "Urinary bladder structure", "display_ja": "膀胱"},
    # 皮膚・軟部
    "L03": {"code": "39937001", "display_en": "Skin structure", "display_ja": "皮膚"},
}


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
_EX_DIAGNOSISTYPE_SYSTEM = "http://terminology.hl7.org/CodeSystem/ex-diagnosistype"

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
    entry = _CONDITION_BODY_SITE.get(key3)
    if not entry:
        return None
    disp = entry["display_ja"] if is_jp(country) else entry["display_en"]
    return {
        "coding": [
            {
                "system": get_system_uri("snomed-ct"),
                "code": entry["code"],
                "display": disp,
            }
        ],
        "text": disp,
    }


def _build_conditions(record: dict, patient_id: str, country: str) -> list[dict]:
    """Build FHIR Condition resources from diagnosis and chronic conditions.

    Generates:
    - Primary encounter diagnosis (from clinical_diagnosis) with severity
    - Chronic conditions (from patient.chronic_conditions) with onset dates
    Deduplicates by ICD base code.
    """
    conditions: list[dict] = []
    seen_codes: set[str] = set()

    dx = record.get("clinical_diagnosis", {})
    encounters = record.get("encounters", [])
    encounter_id = encounters[0].get("encounter_id", "") if encounters else ""
    encounter_type = encounters[0].get("encounter_type", "") if encounters else ""
    is_inpatient = encounter_type == "inpatient"
    admission_dt = encounters[0].get("admission_datetime", "") if encounters else ""
    discharge_dt = encounters[0].get("discharge_datetime", "") if encounters else ""
    deceased = record.get("deceased", False)

    country_code = "JP" if is_jp(country) else "US"
    lang = resolve_lang(country_code)
    icd_system_key = system_key_for("diagnosis", country_code)

    # Chronic conditions the patient carries — used both to recognise a chronic
    # primary diagnosis (active + chronic onset) and to emit problem-list items below.
    chronic_list = record.get("patient", {}).get("chronic_conditions", [])
    chronic_onset_by_base: dict[str, str] = {}
    # C4-05 / C4-07..09: also index severity + stage so a
    # chronic-primary encounter-diagnosis can inherit them when infer_severity
    # returns empty (routine outpatient follow-up with no physiological states).
    # Applies to essential HTN (I10) routine visits, DM/COPD/HF/CKD follow-ups —
    # 65.8% of I10 lacked severity because infer_severity fell back to "" for
    # outpatient encounters.
    chronic_severity_by_base: dict[str, str] = {}
    chronic_stage_by_base: dict[str, str] = {}
    for _chronic in chronic_list:
        if isinstance(_chronic, str):
            _cc = _chronic
            _onset = ""
            _sev = ""
            _stg = ""
        else:
            # dict (production JSON path) or a ChronicCondition dataclass
            # (in-memory path) — get_attr_or_key handles both uniformly.
            _cc = get_attr_or_key(_chronic, "code", "")
            _onset = get_attr_or_key(_chronic, "onset_date", "") or ""
            _sev = get_attr_or_key(_chronic, "severity", "") or ""
            _stg = get_attr_or_key(_chronic, "stage", "") or ""
        if _cc:
            base = _cc.split(".")[0]
            chronic_onset_by_base.setdefault(base, _onset)
            chronic_severity_by_base.setdefault(base, _sev)
            chronic_stage_by_base.setdefault(base, _stg)

    # --- Primary diagnosis (encounter diagnosis) ---
    dx_code = dx.get("discharge_diagnosis_code") or dx.get("admission_diagnosis_code", "")
    # Chronic-primary suppression: when this encounter's primary dx merges
    # into a chronic problem (HTN follow-up, HF exacerbation, DM control,
    # …), skip the encounter-primary Condition emission. The chronic
    # Condition below already carries the disease info, and
    # `Encounter.diagnosis[].use=DD` expresses the encounter-role — the
    # duplicate `cond-{enc}-primary` was drifting ICD granularity (I50 vs
    # I50.9) and inflating the Condition table by ~encounter_count for
    # polymorbid patients.
    if dx_code and not _encounter_primary_is_chronic(record):
        base_code = dx_code.split(".")[0]
        seen_codes.add(base_code)

        # Determine severity from physiological states
        severity = infer_severity(record)

        # A primary diagnosis that is one of the patient's chronic conditions
        # (e.g. an outpatient diabetes follow-up coding E11.9) is ongoing, not
        # resolved at the visit: mark it active with the chronic onset date.
        is_chronic_primary = base_code in chronic_onset_by_base
        chronic_onset = chronic_onset_by_base.get(base_code, "") if is_chronic_primary else ""
        # C4-05: chronic-primary severity fallback.
        # infer_severity returns "" when the encounter has no physiological
        # states (routine outpatient follow-up), leaving I10/E11/etc. Condition
        # without severity. Inherit from patient chronic_conditions severity
        # so problem-list severity is consistent with encounter-diagnosis.
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
            _enc_severity = (encounters[0].get("severity", "") if encounters else "") or ""
            if _enc_severity:
                severity = _enc_severity

        # clinicalStatus: resolved if discharged alive, active if deceased (didn't resolve)
        if is_chronic_primary:
            clinical_status = "active"
        elif is_inpatient:
            clinical_status = "active" if deceased or not discharge_dt else "resolved"
        else:
            clinical_status = "resolved"

        # Issue #854 Bucket B (PR-condition): opaque Condition.id.
        # Structural key = pre-#854 id body (without ``cond-`` prefix).
        _primary_structural_key = encounter_primary_condition_key(patient_id, encounter_id)
        cond: dict[str, Any] = {
            "resourceType": "Condition",
            "id": encounter_primary_condition_id(patient_id, encounter_id),
            "identifier": [wrap_as_identifier(_primary_structural_key, CONDITION_KEY_SYSTEM)],
            # C2-20: JP Core Condition profile.
            **(
                {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Condition"]}}
                if is_jp(country_code)
                else {}
            ),
            "clinicalStatus": {
                "coding": [_coding_with_display("hl7-condition-clinical", clinical_status, lang)],
            },
            "verificationStatus": {
                "coding": [_coding_with_display("hl7-condition-ver-status", "confirmed", lang)],
            },
            "category": [
                {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-condition-category"),
                            "code": "encounter-diagnosis",
                            "display": _localize_display("Encounter Diagnosis", country, _CATEGORY_DISPLAY_JA),
                        }
                    ],
                }
            ],
            "code": build_diagnosis_codeable_concept(map_diagnosis_code(dx_code, country), icd_system_key, country),
            "subject": patient_ref(patient_id),
        }
        # Issue #744: JP_Condition_eCS must-support `extension:eCS_DiagnosisType`
        # (spec binding: http://hl7.org/fhir/ValueSet/ex-diagnosistype|4.0.1).
        # Encounter-diagnosis Condition is the reason-for-visit → `principal`
        # (matches the FHIR-standard code and the JP display CS
        # `http://jpfhir.jp/core/terminology/CodeSystemJPDisplay/ex-diagnosistype`).
        if is_jp(country_code):
            cond.setdefault("extension", []).append(_ecs_diagnosis_type_extension("principal"))

        if severity:
            cond["severity"] = severity_coding(severity, country)

        # CY6-19 (Chain-6): Condition.evidence — record what supported the
        # diagnosis. Cross-referencing specific DiagnosticReport IDs requires
        # the same panel-grouping logic used by the DR builder; instead, emit
        # a text-only CodeableConcept via `evidence.code` describing the
        # supporting evidence category. FHIR R4 Condition.evidence is 0..*
        # with 0..1 code + 0..* detail — text-only code is spec-compliant
        # (no fabricated coding). For chronic-primary: prior established
        # diagnosis; for acute: clinical presentation + supporting labs.
        _ev_text_ja = "既往診断" if is_chronic_primary else "臨床所見および検査結果"
        _ev_text_en = (
            "Prior established diagnosis"
            if is_chronic_primary
            else "Clinical presentation and supporting laboratory results"
        )  # noqa: E501
        cond["evidence"] = [
            {
                "code": [{"text": _ev_text_ja if is_jp(country_code) else _ev_text_en}],
            }
        ]

        # C4-07..10: encounter-diagnosis stage inheritance.
        # When the primary dx is a staged chronic condition (DM/COPD/HF/CKD)
        # the encounter-diagnosis Condition should carry the same stage as the
        # patient's chronic entry. Otherwise E11/J44/I50 encounter-dx records
        # emit no stage while the sibling problem-list-item entry has stage
        # populated — inconsistent across the two Condition rows for the same
        # underlying disease.
        if is_chronic_primary:
            _stg = chronic_stage_by_base.get(base_code, "")
            if _stg:
                summary: dict[str, Any] = {"text": _stg}
                stage_snomed = _STAGE_SUMMARY_SNOMED.get(_stg)
                if stage_snomed:
                    summary["coding"] = [
                        {
                            "system": get_system_uri("snomed-ct"),
                            "code": stage_snomed,
                            "display": code_lookup("snomed-ct", stage_snomed, resolve_lang(country)),
                        }
                    ]
                cond["stage"] = [
                    {
                        "summary": summary,
                        "type": {"text": "Clinical stage"},
                    }
                ]

        if chronic_onset:
            # Chronic primary: onset is the disease onset date (typically month-year
            # granularity; keep as date-only). recordedDate is the visit — use full
            # datetime from admission so time-series UIs sort correctly.
            cond["onsetDateTime"] = to_fhir_date(chronic_onset)
            if admission_dt:
                cond["recordedDate"] = to_fhir_datetime(admission_dt)
        elif admission_dt:
            # Encounter-diagnosis onset = admission time (full datetime). Issue #821
            # (N-7): consumer time-series UIs sort by these fields and were
            # broken by date-only precision.
            cond["onsetDateTime"] = to_fhir_datetime(admission_dt)
            cond["recordedDate"] = cond["onsetDateTime"]

        if encounters:
            cond["encounter"] = encounter_ref(encounters[0].get("encounter_id", ""))
            # C2-31: Condition.recorder ← attending physician
            # of the encounter. FHIR R4 R0..1; JP Core Condition recommends
            # this reference for chart traceability. Attending is emitted as
            # Practitioner in the encounter builder so this ref resolves.
            _att = encounters[0].get("attending_physician_id", "")
            if _att:
                cond["recorder"] = {"reference": f"Practitioner/{_att}"}
                # CY8-22 fix:Condition.asserter — 疾患を
                # 診断・断定する医師。clinosim 運用では recorder と同一 attending。
                cond["asserter"] = {"reference": f"Practitioner/{_att}"}

        # CY8-24 fix:Condition.abatementDateTime — 疾患解消日。
        # 入院診断が退院時に active/resolved どちらであるかを CIF は保持しないが、
        # discharge_datetime が snapshot 前 = encounter finished/completed の場合
        # 「一時的な急性エピソード」型(cellulitis, pneumonia 等)は退院時に
        # resolved と想定し abatementDateTime を discharge に設定。
        # 慢性疾患(chronic primary)は resolved しない前提のため abatement 無し。
        # 判定:encounter status が完了かつ non-chronic → abatement 付与。
        #
        # Chain F (v2 feedback §【最優先 4】): the original guard
        # relied on the docstring alone and did not check `is_chronic_primary`
        # in the emit code, so chronic-primary encounters received both
        # `clinicalStatus="active"` (line 213) and `abatementDateTime` from
        # the block below, triggering FHIR R4 invariant `con-4` on 2,452
        # Condition resources. Restrict the abatement emission to
        # non-chronic-primary, living-patient encounters so the docstring's
        # intent is actually enforced. (Deceased patients: clinicalStatus=active
        # because the diagnosis didn't resolve, so abatement must not be set.)
        if encounters and not is_chronic_primary and not deceased:
            _enc0 = encounters[0]
            _dd = _enc0.get("discharge_datetime", "")
            _est = _enc0.get("status", "")
            if _dd and _est in ("completed", "finished"):
                # Issue #821 (N-7): abatement is the discharge time (full datetime).
                cond["abatementDateTime"] = to_fhir_datetime(_dd)

        # CY8-23 fix:Condition.bodySite — 解剖学的部位。
        # 15 疾患 prefix に対して SNOMED body structure を emit(非部位性は無し)。
        _bs = _bodysite_for(dx_code, country)
        if _bs:
            cond["bodySite"] = [_bs]

        conditions.append(cond)

    # --- Admission diagnosis (Issue #912) ---
    # When ``clinical_diagnosis.admission_diagnosis_code`` differs from the
    # discharge/primary dx AND from every chronic Condition, the admission dx
    # was previously only carried as a text-only ``Encounter.reasonCode`` with
    # NO matching ``Condition`` in the patient record — 45.4% of IMP encounters
    # at seed=500 p=1000 (pyelonephritis-admitted patients whose workup landed
    # on renal-stone as the discharge dx; COPD-exacerbation-admitted patients
    # whose diagnosis[] linked to chronic COPD Condition; pneumonia-admitted
    # patients whose diagnosis[] linked to a more specific pneumococcal
    # pneumonia Condition; etc.). Fix: emit an ``AD`` Condition so the
    # invariant ``reasonCode ⊆ diagnosis[].condition.code`` holds. The
    # encounter builder mirrors this decision (same helper) to add the
    # ``diagnosis[].use=AD`` entry that references this Condition.
    _admit_dx_code_raw = dx.get("admission_diagnosis_code", "") or ""
    _primary_dx_code_raw = dx.get("discharge_diagnosis_code") or _admit_dx_code_raw
    _chronic_codes_raw = [
        _cc if isinstance(_cc, str) else (get_attr_or_key(_cc, "code", "") or "") for _cc in chronic_list
    ]
    _chronic_codes_raw = [c for c in _chronic_codes_raw if c]
    _admit_mapped_check = map_diagnosis_code(_admit_dx_code_raw, country) if _admit_dx_code_raw else ""
    _primary_mapped_check = map_diagnosis_code(_primary_dx_code_raw, country) if _primary_dx_code_raw else ""
    _chronic_mapped_check = [map_diagnosis_code(_c, country) for _c in _chronic_codes_raw]
    if encounter_id and (
        needs_admission_diagnosis_condition(_admit_dx_code_raw, _primary_dx_code_raw, _chronic_codes_raw)
        or needs_admission_diagnosis_condition(_admit_mapped_check, _primary_mapped_check, _chronic_mapped_check)
    ):
        _admit_mapped = _admit_mapped_check
        # NOTE: intentionally do not add ``_admit_mapped``'s ICD base to
        # ``seen_codes`` — the admission Condition carries a distinct ICD code
        # (e.g. J44.1 COPD exacerbation vs J44 chronic COPD on the chronic
        # entry, or vs J44.0 on the encounter-primary entry). Leaving the base
        # out of ``seen_codes`` keeps both rows for the same-base cases (three
        # rows for COPD-exacerbation admissions with chronic COPD carriers:
        # primary J44.0 / admission J44.1 / chronic J44), which is the desired
        # audit trail.
        _admit_structural_key = encounter_admission_condition_key(patient_id, encounter_id)
        _admit_cond: dict[str, Any] = {
            "resourceType": "Condition",
            "id": encounter_admission_condition_id(patient_id, encounter_id),
            "identifier": [wrap_as_identifier(_admit_structural_key, CONDITION_KEY_SYSTEM)],
            **(
                {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Condition"]}}
                if is_jp(country_code)
                else {}
            ),
            **({"extension": [_ecs_diagnosis_type_extension("admitting")]} if is_jp(country_code) else {}),
            # Admission dx is the working diagnosis at admission — during the
            # stay it may be refined or resolved. Encode as ``active`` until
            # the encounter completes; ``resolved`` at discharge (same rule as
            # the encounter-primary path above for non-chronic, non-deceased).
            "clinicalStatus": {
                "coding": [
                    _coding_with_display(
                        "hl7-condition-clinical",
                        "resolved" if (is_inpatient and discharge_dt and not deceased) else "active",
                        lang,
                    )
                ],
            },
            "verificationStatus": {
                "coding": [_coding_with_display("hl7-condition-ver-status", "confirmed", lang)],
            },
            "category": [
                {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-condition-category"),
                            "code": "encounter-diagnosis",
                            "display": _localize_display("Encounter Diagnosis", country, _CATEGORY_DISPLAY_JA),
                        }
                    ],
                }
            ],
            "code": build_diagnosis_codeable_concept(_admit_mapped, icd_system_key, country),
            "subject": patient_ref(patient_id),
        }
        # Override ``code.text`` with the code's full-granularity display so
        # ``Condition.code.text`` == ``Encounter.reasonCode.text`` (Issue #912
        # audit's substring rule requires the two ``text`` slots to overlap —
        # short-name lookup in ``build_diagnosis_codeable_concept`` folds to
        # the ICD base and so returns e.g. "COPD" for J44.1, not the leaf
        # "COPD急性増悪" that reasonCode carries). Only replaces when a
        # distinct leaf display exists; otherwise leaves the short-name text
        # in place (backwards-compatible).
        _leaf_display = code_lookup(icd_system_key, _admit_mapped, lang) if _admit_mapped else ""
        if _leaf_display and _leaf_display != _admit_mapped:
            _admit_cond["code"]["text"] = _leaf_display
        if encounters:
            _admit_cond["encounter"] = encounter_ref(encounters[0].get("encounter_id", ""))
            _att = encounters[0].get("attending_physician_id", "") or encounters[0].get("admitting_physician_id", "")
            if _att:
                _admit_cond["recorder"] = {"reference": f"Practitioner/{_att}"}
                _admit_cond["asserter"] = {"reference": f"Practitioner/{_att}"}
        if admission_dt:
            _admit_cond["onsetDateTime"] = to_fhir_datetime(admission_dt)
            _admit_cond["recordedDate"] = _admit_cond["onsetDateTime"]
        if is_inpatient and discharge_dt and not deceased:
            _admit_cond["abatementDateTime"] = to_fhir_datetime(discharge_dt)
        _bs_admit = _bodysite_for(_admit_dx_code_raw, country)
        if _bs_admit:
            _admit_cond["bodySite"] = [_bs_admit]
        # Text-only evidence label consistent with the encounter-primary path.
        _admit_cond["evidence"] = [
            {
                "code": [
                    {
                        "text": "入院時所見および初期評価"
                        if is_jp(country_code)
                        else "Admission presentation and initial assessment"
                    }
                ],
            }
        ]
        conditions.append(_admit_cond)

    # --- Chronic conditions (from patient profile) ---
    for i, chronic in enumerate(chronic_list):
        if isinstance(chronic, str):
            c_code = chronic
            c_onset = ""
            c_severity = ""
            c_stage = ""
        else:
            # dict (production JSON path) or a ChronicCondition dataclass
            # (in-memory path) — get_attr_or_key handles both uniformly, so
            # a bare dataclass instance is no longer silently dropped.
            c_code = get_attr_or_key(chronic, "code", "")
            c_onset = get_attr_or_key(chronic, "onset_date", "")
            c_severity = get_attr_or_key(chronic, "severity", "")
            c_stage = get_attr_or_key(chronic, "stage", "")

        if not c_code:
            continue

        base = c_code.split(".")[0]
        if base in seen_codes:
            continue
        seen_codes.add(base)

        # Issue #854 Bucket B (PR-condition): opaque chronic Condition.id.
        _chronic_structural_key = chronic_condition_key(patient_id, i)
        cond = {
            "resourceType": "Condition",
            # C4-02: patient-scoped structural key so the adapter's
            # write() dedup collapses per-encounter re-emissions. Was
            # `cond-{encounter_id}-chronic-{i}` which produced N duplicates
            # per patient (N = number of the patient's encounters), driving
            # cycle-3 RM-7 problem-list-item excess to 10x realistic count.
            "id": chronic_condition_id(patient_id, i),
            "identifier": [wrap_as_identifier(_chronic_structural_key, CONDITION_KEY_SYSTEM)],
            # C2-20: JP Core Condition profile also on chronic-
            # condition path (encounter-dx path handled above).
            **(
                {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Condition"]}}
                if is_jp(country_code)
                else {}
            ),
            # Issue #744: chronic condition → `clinical` (general clinical
            # finding, not the encounter's reason). Same extension family as
            # the encounter-diagnosis path above.
            **({"extension": [_ecs_diagnosis_type_extension("clinical")]} if is_jp(country_code) else {}),
            # C2-02/03: use _coding_with_display so the
            # chronic-condition path also emits displays (was raw code).
            "clinicalStatus": {
                "coding": [_coding_with_display("hl7-condition-clinical", "active", lang)],
            },
            "verificationStatus": {
                "coding": [_coding_with_display("hl7-condition-ver-status", "confirmed", lang)],
            },
            "category": [
                {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-condition-category"),
                            "code": "problem-list-item",
                            "display": _localize_display("Problem List Item", country, _CATEGORY_DISPLAY_JA),
                        }
                    ],
                }
            ],
            "code": build_diagnosis_codeable_concept(map_diagnosis_code(c_code, country), icd_system_key, country),
            "subject": patient_ref(patient_id),
        }

        if c_severity:
            cond["severity"] = severity_coding(c_severity, country)

        # CY6-19 (Chain-6): Condition.evidence — problem-list-item entries are
        # established from prior encounters. Text-only evidence label per the
        # same rationale as the encounter-diagnosis path.
        cond["evidence"] = [
            {
                "code": [
                    {
                        "text": "問題リスト:過去診療で確立"
                        if is_jp(country_code)
                        else "Problem list — established in prior encounters"
                    }
                ],  # noqa: E501
            }
        ]

        # Stage (NYHA class, CKD G, GOLD, hypertension Stage, CCS, etc.) — c_stage set
        # in the branch above. The stage VALUE is carried by summary.text (always) plus
        # a summary.coding when the staging system has a verified SNOMED CT concept
        # (_STAGE_SUMMARY_SNOMED — CKD / NYHA). type.type is left as a plain-text label:
        # these are non-cancer clinical stages, so the former SNOMED 385356007 "Tumor
        # stage finding" coding was clinically wrong and is intentionally NOT emitted.
        if c_stage:
            summary = {"text": c_stage}
            stage_snomed = _STAGE_SUMMARY_SNOMED.get(c_stage)
            if stage_snomed:
                summary["coding"] = [
                    {
                        "system": get_system_uri("snomed-ct"),
                        "code": stage_snomed,
                        "display": code_lookup("snomed-ct", stage_snomed, resolve_lang(country)),
                    }
                ]
            cond["stage"] = [
                {
                    "summary": summary,
                    "type": {"text": "Clinical stage"},
                }
            ]

        if c_onset:
            cond["onsetDateTime"] = to_fhir_date(c_onset)

        # C2-31: Condition.recorder for chronic path as well.
        # CY8-21 fix:encounters が無い(problem-list chronic
        # で outpatient-only 患者)の場合も recorder / asserter を担当医らしき
        # ID(先頭 encounter が無ければ hospital-main の primary care physician)
        # にフォールバック。旧 88.7% → 100%。
        _att = ""
        if encounters:
            _att = encounters[0].get("attending_physician_id", "") or ""
        if _att:
            cond["recorder"] = {"reference": f"Practitioner/{_att}"}
            # CY8-22 fix:chronic path も asserter を並置。
            cond["asserter"] = {"reference": f"Practitioner/{_att}"}
        else:
            cond["recorder"] = {"reference": "Practitioner/DR-IM-001"}
            cond["asserter"] = {"reference": "Practitioner/DR-IM-001"}
        # recordedDate: use admission datetime (full time) so time-series UIs sort correctly (Issue #821 / N-7).
        if admission_dt:
            cond["recordedDate"] = to_fhir_datetime(admission_dt)

        # CY8-23 fix (chronic path): SNOMED bodySite for anatomically-localizable
        # chronic conditions(e.g. J44 COPD → 肺, I50 心不全 → 心臓)。
        _bs = _bodysite_for(c_code, country)
        if _bs:
            cond["bodySite"] = [_bs]

        conditions.append(cond)

    return conditions
