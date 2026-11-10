"""Health-checkup questionnaire answers as JP-eCheckup Observations (Issue #3163).

The questionnaire section of a health-checkup report references one
``JP_Observation_eCheckupGeneral`` per questionnaire item the record can
answer: medication for blood pressure / glucose / lipids (current
medications), history of cerebrovascular / heart / kidney disease (chronic
conditions) and smoking (smoking status). Items, answer codes and derivation
rules live in ``locale/<cc>/checkup_questionnaire.yaml``; a country without
the file (US) emits none. No random draws: every answer is read from the
record, and an item whose source the record lacks is omitted.
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import display as registry_display
from clinosim.codes import get_system_uri
from clinosim.codes.drugs import medication_matches
from clinosim.codes.valuesets import concept_group
from clinosim.countries import country_code, lang_for
from clinosim.locale.loader import load_checkup_questionnaire, load_checkup_report_items
from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
from clinosim.modules.output.fhir_r4.encounters.encounter import encounter_ref
from clinosim.modules.output.fhir_r4.lib.common import dual_slot_concept
from clinosim.modules.output.fhir_r4.lib.context import BundleContext
from clinosim.modules.output.fhir_r4.lib.ids import derive_opaque_id

CHECKUP_QUESTIONNAIRE_ID_PREFIX = "chkq-"
_KEY_KIND = "checkup-questionnaire-observation-key"


def _medication_answer(rule: dict[str, Any], patient: dict[str, Any]) -> str | None:
    meds = patient.get("current_medications")
    if meds is None:
        return None
    conditions = [str(c.get("code") or "") for c in patient.get("chronic_conditions") or [] if isinstance(c, dict)]
    gated: dict[str, str] = rule.get("classes_requiring_condition") or {}
    classes = [
        cls
        for cls in rule.get("drug_classes") or []
        if cls not in gated or any(concept_group(gated[cls]).contains(code) for code in conditions)
    ]
    return "yes" if any(medication_matches(m, classes=classes) for m in meds) else "no"


def _condition_answer(rule: dict[str, Any], patient: dict[str, Any], checkup_date: str) -> str | None:
    conditions = patient.get("chronic_conditions")
    if conditions is None:
        return None
    prefixes = tuple(str(p) for p in rule.get("icd10_prefixes") or [])
    for c in conditions:
        if not isinstance(c, dict):
            continue
        code = str(c.get("code") or "")
        onset = str(c.get("onset_date") or "")[:10]
        if code.startswith(prefixes) and (not onset or not checkup_date or onset <= checkup_date):
            return "yes"
    return "no"


def _answer_key(rule: dict[str, Any], patient: dict[str, Any], checkup_date: str) -> str | None:
    source = rule.get("source")
    if source == "medication":
        return _medication_answer(rule, patient)
    if source == "condition":
        return _condition_answer(rule, patient, checkup_date)
    if source == "smoking":
        return str(patient.get("smoking_status") or "") or None
    raise ValueError(f"checkup_questionnaire.yaml: unknown source {source!r}")


def _checkup_type(record: dict[str, Any], encounter_id: str) -> str:
    for doc in record.get("documents") or []:
        if isinstance(doc, dict) and doc.get("encounter_id") == encounter_id and doc.get("checkup_type"):
            return str(doc["checkup_type"])
    return ""


def checkup_questionnaire_observations(record: dict[str, Any], country: str) -> list[dict[str, Any]]:
    """The questionnaire Observations of every checkup encounter in ``record``."""
    table = load_checkup_questionnaire(country_code(country))
    if not table:
        return []
    profile = load_checkup_report_items(country_code(country))["observation_profile"]
    patient = record.get("patient") or {}
    patient_id = str(patient.get("patient_id") or "")
    lang = lang_for(country)
    out: list[dict[str, Any]] = []
    for enc in record.get("encounters") or []:
        if not isinstance(enc, dict) or enc.get("encounter_type") != "checkup":
            continue
        encounter_id = str(enc.get("encounter_id") or "")
        started = str(enc.get("admission_datetime") or "")
        for key in table["questionnaires"].get(_checkup_type(record, encounter_id), []):
            rule = table["items"][key]
            answer = _answer_key(rule, patient, started[:10])
            answer_code = (rule.get("answers") or {}).get(answer) if answer else None
            if not answer_code:
                continue  # the record cannot answer this item
            item_code = str(rule["code"])
            item_system = table["item_code_system"]
            answer_system = str(rule["answer_system"])
            obs: dict[str, Any] = {
                "resourceType": "Observation",
                "id": derive_opaque_id(CHECKUP_QUESTIONNAIRE_ID_PREFIX, f"{_KEY_KIND}:{encounter_id}:{item_code}"),
                "meta": {"profile": [profile]},
                "status": "final",
                "category": [dual_slot_concept("hl7-observation-category", table["category"], lang)],
                "code": {
                    "coding": [
                        {
                            "system": get_system_uri(item_system),
                            "code": item_code,
                            "display": registry_display(item_system, item_code, lang) or item_code,
                        }
                    ]
                },
                "subject": patient_ref(patient_id),
                "encounter": encounter_ref(encounter_id),
                "valueCodeableConcept": dual_slot_concept(answer_system, str(answer_code), lang),
            }
            if started:
                obs["effectiveDateTime"] = started
            if enc.get("attending_physician_id"):
                obs["performer"] = [{"reference": f"Practitioner/{enc['attending_physician_id']}"}]
            out.append(obs)
    return out


def _bb_checkup_questionnaire(ctx: BundleContext) -> list[dict]:
    """Bundle builder: the health-checkup questionnaire Observations."""
    return checkup_questionnaire_observations(ctx.record, ctx.country)
