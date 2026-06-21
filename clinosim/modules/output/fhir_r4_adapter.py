"""FHIR R4 adapter — Stage 3: convert CIF structural data to FHIR R4 Bundles.

Generates one FHIR Bundle (JSON) per patient containing:
  Patient, Encounter, Observation (labs + vitals), MedicationRequest, Practitioner references.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.locale.loader import (
    load_code_mapping,
    load_identity_config,
)

# FA-1 (Phases 1-5) split this adapter's leaf data, shared fragment helpers, and
# per-theme resource builders into sibling _fhir_* modules. The blocks below are
# re-imported here so existing `from ...fhir_r4_adapter import X` call sites keep
# working (facade). They are marked # noqa: F401 because many symbols are now used
# only by the extracted modules (which import them directly) and are re-exported
# purely as a compatibility facade; the # noqa keeps the facade stable as further
# builders move out, without per-symbol import churn each phase.
from clinosim.modules.output._fhir_common import (  # noqa: F401
    _build_address,
    _build_diagnosis_codeable_concept,
    _build_dosage_instruction,
    _build_reference_range,
    _build_telecom,
    _entry,
    _infer_severity,
    _loinc_coding,
    _make_participant,
    _map_diagnosis_code,
    _map_encounter_status,
    _map_mar_status,
    _micro_coding,
    _parse_dose_for_mar,
    _severity_coding,
    _sha1_b64,
    _strip_protocol_prefix,
    _survey_category,
)
from clinosim.modules.output._fhir_conditions import _build_conditions  # noqa: F401
from clinosim.modules.output._fhir_documents import _build_document_reference  # noqa: F401
from clinosim.modules.output._fhir_encounter import _build_encounter  # noqa: F401
from clinosim.modules.output._fhir_facility import _build_facility_bundle  # noqa: F401
from clinosim.modules.output._fhir_localization import (  # noqa: F401
    _CATEGORY_DISPLAY_JA,
    _CLASS_DISPLAY_JA,
    _FREQ_JA,
    _INTERPRETATION_DISPLAY_JA,
    _LOCATION_NAME_JA,
    _LOCATION_TYPE_DISPLAY_JA,
    _OCCUPATION_DISPLAY_EN,
    _OCCUPATION_DISPLAY_JA,
    _ORG_TYPE_DISPLAY_JA,
    _RELATIONSHIP_DISPLAY_JA,
    _ROLE_PREFIX_MAP_JA,
    _ROUTE_JA,
    _SEVERITY_DISPLAY_JA,
    _dept_display,
    _load_department_display,
    _load_drug_names_ja,
    _load_med_terms_ja,
    _localize_display,
    _localize_dosage_terms,
    _localize_drug_name,
    _localize_interp,
    _procedure_display,
)
from clinosim.modules.output._fhir_medications import (  # noqa: F401
    _build_medication_admin,
    _build_medication_request,
)
from clinosim.modules.output._fhir_practitioner import (  # noqa: F401
    _build_practitioner,
    _build_practitioner_role,
)
from clinosim.modules.output._fhir_procedures import _build_procedure  # noqa: F401
from clinosim.modules.output._fhir_reference_data import (  # noqa: F401
    _ALLERGEN_RXNORM,
    _CONDITION_SHORT_NAME,
    _ENCOUNTER_TYPE_SNOMED,
    _ENCOUNTER_TYPE_SNOMED_JA,
    _PREFECTURE_CODE,
    _ROLE_PREFIX_MAP,
    _ROUTE_SNOMED,
    _SEVERITY_SNOMED,
    _SPECIALTY_SNOMED,
    _US_STATE_CODE,
)


def convert_cif_to_fhir(
    cif_dir: str,
    output_dir: str,
    country: str = "US",
    narrative_version: str | None = None,
) -> None:
    """Read CIF structural data and write FHIR R4 Bulk Data Export NDJSON files.

    Output follows the HL7 FHIR Bulk Data Access spec:
    one NDJSON file per resource type (Patient.ndjson, Encounter.ndjson, etc.).
    Each line is a single FHIR resource (no Bundle wrapping).

    Args:
        cif_dir: path to a cif/ directory containing structural/ and
            (optionally) narratives/<version>/documents/.
        output_dir: directory to write the FHIR NDJSON files.
        country: "US" or "JP" — selects display language and code systems.
        narrative_version: if set, reads narrative CIF documents from
            cif_dir/narratives/<narrative_version>/documents/ and emits them
            as DocumentReference resources. When None (or "current"),
            the pointer at cif_dir/narratives/current_version.txt is used.
            When the directory does not exist, no DocumentReferences are
            emitted (graceful degradation).
    """
    os.makedirs(output_dir, exist_ok=True)

    structural_dir = os.path.join(cif_dir, "structural", "patients")
    if not os.path.exists(structural_dir):
        raise FileNotFoundError(f"CIF structural directory not found: {structural_dir}")

    # Resolve narrative version (current_version.txt pointer)
    narrative_docs_dir: str | None = None
    if narrative_version:
        if narrative_version == "current":
            current_link = os.path.join(cif_dir, "narratives", "current_version.txt")
            if os.path.exists(current_link):
                with open(current_link) as _f:
                    narrative_version = _f.read().strip()
        candidate = os.path.join(
            cif_dir, "narratives", narrative_version, "documents"
        )
        if os.path.isdir(candidate):
            narrative_docs_dir = candidate

    # Load hospital data (Practitioner roster + Organization/Location config)
    roster_map: dict[str, dict] = {}
    hospital_config: dict = {}
    hospital_path = os.path.join(cif_dir, "hospital.json")
    if os.path.exists(hospital_path):
        with open(hospital_path) as f:
            hospital_data = json.load(f)
        for staff in hospital_data.get("staff", []):
            roster_map[staff.get("staff_id", "")] = staff
        hospital_config = hospital_data.get("config", {}) or {}

    # Open NDJSON file handles for each resource type
    # Use a writer cache to lazy-create files only for types we encounter
    writers: dict[str, Any] = {}
    written_ids: dict[str, set[str]] = {}  # de-dup Patient and Practitioner

    def write(resource: dict) -> None:
        rt = resource.get("resourceType", "")
        if not rt:
            return
        # Enforce global Resource.id uniqueness within each type (FHIR requirement).
        # Patient-level resources (Patient, AllergyIntolerance, Coverage, occupation
        # Observation, ...) recur across a patient's per-encounter bundles; keep the
        # first write only. Per-encounter resources have unique ids → never dropped.
        rid = resource.get("id", "")
        if rid:
            ids = written_ids.setdefault(rt, set())
            if rid in ids:
                return
            ids.add(rid)
        if rt not in writers:
            path = os.path.join(output_dir, f"{rt}.ndjson")
            writers[rt] = open(path, "w", encoding="utf-8")
        writers[rt].write(json.dumps(resource, ensure_ascii=False) + "\n")

    try:
        # Master resources (Organization + Location) — written once
        facility_bundle = _build_facility_bundle(hospital_config, country)
        for entry in facility_bundle.get("entry", []):
            write(entry["resource"])

        # Walk patient records, build per-record FHIR resources, write each line
        for filename in sorted(os.listdir(structural_dir)):
            if not filename.endswith(".json"):
                continue
            with open(os.path.join(structural_dir, filename)) as f:
                record = json.load(f)

            bundle = _build_bundle(record, country, roster_map, hospital_config)
            for entry in bundle.get("entry", []):
                write(entry["resource"])

            # === DocumentReference resources (narrative CIF) ===
            if narrative_docs_dir:
                enc_id = (
                    (record.get("encounters") or [{}])[0].get("encounter_id", "")
                )
                if enc_id:
                    enc_docs_dir = os.path.join(narrative_docs_dir, enc_id)
                    if os.path.isdir(enc_docs_dir):
                        patient_id = (
                            record.get("patient", {}).get("patient_id", "")
                        )
                        for doc_file in sorted(os.listdir(enc_docs_dir)):
                            if not doc_file.endswith(".json"):
                                continue
                            with open(
                                os.path.join(enc_docs_dir, doc_file),
                                encoding="utf-8",
                            ) as df:
                                doc_data = json.load(df)
                            docref = _build_document_reference(
                                doc_data, patient_id, country
                            )
                            if docref:
                                write(docref)

        # Manifest (FHIR Bulk Data spec)
        request_desc = f"clinosim generate (country={country})"
        if narrative_version:
            request_desc += f" narrative={narrative_version}"
        manifest = {
            "transactionTime": datetime.now().isoformat(),
            "request": request_desc,
            "requiresAccessToken": False,
            "output": [
                {"type": rt, "url": f"{rt}.ndjson"}
                for rt in sorted(writers.keys())
            ],
            "error": [],
        }
        with open(os.path.join(output_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
    finally:
        for w in writers.values():
            w.close()


@dataclass
class BundleContext:
    """Shared inputs for FHIR resource builders (AD-56)."""

    record: dict
    country: str
    roster_map: dict
    hospital_config: dict
    patient_data: dict
    patient_id: str
    is_readmission: bool
    prior_encounter_id: Any
    primary_dx_code: str
    admit_dx_code: str
    admit_dx_system: str
    primary_enc_id: str
    patient_sex: str


# --- Resource builders: (ctx) -> list[resource]. Order here == emission order. ---

def _bb_patient(ctx: BundleContext) -> list[dict]:
    return [_build_patient(ctx.patient_data, ctx.country)]


def _bb_coverage(ctx: BundleContext) -> list[dict]:
    return _build_coverage_resources(ctx.patient_data, ctx.country)


def _bb_encounters(ctx: BundleContext) -> list[dict]:
    return [
        _build_encounter(enc, ctx.patient_id, ctx.is_readmission, ctx.prior_encounter_id,
                         primary_dx_code=ctx.primary_dx_code, country=ctx.country,
                         admit_dx_code=ctx.admit_dx_code, admit_dx_system=ctx.admit_dx_system)
        for enc in ctx.record.get("encounters", [])
    ]


def _bb_conditions(ctx: BundleContext) -> list[dict]:
    return list(_build_conditions(ctx.record, ctx.patient_id, ctx.country))


def _bb_allergies(ctx: BundleContext) -> list[dict]:
    out: list[dict] = []
    for i, allergy in enumerate(ctx.patient_data.get("allergies", []) or []):
        if isinstance(allergy, dict):
            ai = _build_allergy_intolerance(allergy, ctx.patient_id, i, ctx.country)
            if ai:
                out.append(ai)
    return out


def _bb_occupation(ctx: BundleContext) -> list[dict]:
    # US Core Patient Occupation (LOINC 11341-5). Patient-level, not encounter-scoped.
    occupation = ctx.patient_data.get("occupation", "")
    if occupation:
        occ_obs = _build_occupation_observation(occupation, ctx.patient_id, ctx.country)
        if occ_obs:
            return [occ_obs]
    return []


def _bb_labs(ctx: BundleContext) -> list[dict]:
    out: list[dict] = []
    for i, order in enumerate(ctx.record.get("orders", [])):
        if order.get("order_type") == "lab" and order.get("result"):
            obs = _build_lab_observation(order, order["result"], ctx.patient_id, i,
                                          ctx.country, ctx.patient_sex, ctx.primary_enc_id)
            if obs:
                out.append(obs)
    return out


def _bb_vitals(ctx: BundleContext) -> list[dict]:
    # _build_vital_observations returns already-wrapped Bundle entries; unwrap to raw
    # resources so the registry's single _entry() wrap applies uniformly.
    out: list[dict] = []
    for i, vs in enumerate(ctx.record.get("vital_signs", [])):
        for entry in _build_vital_observations(vs, ctx.patient_id, i, ctx.country, ctx.primary_enc_id):
            out.append(entry["resource"])
    return out


def _bb_medication_requests(ctx: BundleContext) -> list[dict]:
    out: list[dict] = []
    for order in ctx.record.get("orders", []):
        if order.get("order_type") == "medication":
            if not (order.get("display_name") or "").strip():
                continue  # skip blank drug names (CIF data quality)
            out.append(_build_medication_request(
                order, ctx.patient_id, ctx.country, ctx.primary_enc_id, ctx.primary_dx_code))
    return out


def _bb_medication_admins(ctx: BundleContext) -> list[dict]:
    out: list[dict] = []
    for i, mar in enumerate(ctx.record.get("medication_administrations", [])):
        if not (mar.get("drug_name") or "").strip():
            continue
        out.append(_build_medication_admin(
            mar, ctx.patient_id, i, ctx.country,
            encounter_id=ctx.primary_enc_id, primary_dx_code=ctx.primary_dx_code))
    return out


def _bb_procedures(ctx: BundleContext) -> list[dict]:
    return [
        _build_procedure(proc, ctx.patient_id, i, ctx.country)
        for i, proc in enumerate(ctx.record.get("procedures", []))
    ]


def _bb_practitioners(ctx: BundleContext) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()

    def add(staff_id: str) -> None:
        if not staff_id or staff_id in seen:
            return
        seen.add(staff_id)
        out.append(_build_practitioner(staff_id, ctx.roster_map, country=ctx.country))
        role = _build_practitioner_role(staff_id, ctx.roster_map)
        if role:
            out.append(role)

    for enc in ctx.record.get("encounters", []):
        add(enc.get("attending_physician_id", ""))
        add(enc.get("admitting_physician_id", ""))
        add(enc.get("discharging_physician_id", ""))
    for o in ctx.record.get("orders", []):
        add(o.get("ordered_by", ""))
        if o.get("result"):
            add(o["result"].get("performed_by", ""))
    for vs in ctx.record.get("vital_signs", []):
        add(vs.get("measured_by", ""))
    for mar in ctx.record.get("medication_administrations", []):
        add(mar.get("administered_by", ""))
    for proc in ctx.record.get("procedures", []):
        add(proc.get("primary_surgeon_id", ""))
        add(proc.get("anesthesiologist_id", ""))
    return out


# FHIR-standard antibiotic susceptibility interpretation labels
# (v3-ObservationInterpretation; standard 3-value enum, localized for display only).
_SUSCEPTIBILITY_DISPLAY = {
    "S": {"en": "Susceptible", "ja": "感性"},
    "I": {"en": "Intermediate", "ja": "中間"},
    "R": {"en": "Resistant", "ja": "耐性"},
}


def _bb_microbiology(ctx: BundleContext) -> list[dict]:
    """Microbiology cultures → Specimen + Observation(s) + DiagnosticReport (AD-55)."""
    cultures = ctx.record.get("microbiology") or []
    if not cultures:
        return []
    lang = "ja" if ctx.country == "JP" else "en"
    subject = {"reference": f"Patient/{ctx.patient_id}"}
    enc_ref = {"reference": f"Encounter/{ctx.primary_enc_id}"} if ctx.primary_enc_id else None
    lab_category = [{"coding": [{
        "system": get_system_uri("hl7-observation-category"),
        "code": "laboratory", "display": "Laboratory",
    }]}]
    out: list[dict] = []

    for i, mb in enumerate(cultures):
        base = f"{ctx.primary_enc_id or ctx.patient_id}-{i}"
        spec_id = f"spec-{base}"
        specimen: dict[str, Any] = {"resourceType": "Specimen", "id": spec_id, "subject": subject}
        if mb.get("specimen_snomed"):
            specimen["type"] = {"coding": [_micro_coding("snomed-ct", mb["specimen_snomed"], lang)]}
        if mb.get("collected_datetime"):
            specimen["collection"] = {"collectedDateTime": mb["collected_datetime"]}
        out.append(specimen)

        culture_loinc = mb.get("test_loinc", "")
        culture_code = ({"coding": [_micro_coding("loinc", culture_loinc, lang)]}
                        if culture_loinc else {"text": "Culture"})
        result_refs: list[dict] = []

        org_id = f"mb-org-{base}"
        org_obs: dict[str, Any] = {
            "resourceType": "Observation", "id": org_id, "status": "final",
            "category": lab_category, "code": culture_code, "subject": subject,
            "specimen": {"reference": f"Specimen/{spec_id}"},
        }
        if enc_ref:
            org_obs["encounter"] = enc_ref
        if mb.get("reported_datetime"):
            org_obs["effectiveDateTime"] = mb["reported_datetime"]
        if mb.get("growth") and mb.get("organism_snomed"):
            org_obs["valueCodeableConcept"] = {
                "coding": [_micro_coding("snomed-ct", mb["organism_snomed"], lang)]
            }
            if mb.get("quantitation"):
                org_obs["note"] = [{"text": mb["quantitation"]}]
        else:
            org_obs["valueString"] = "発育なし" if lang == "ja" else "No growth"
        out.append(org_obs)
        result_refs.append({"reference": f"Observation/{org_id}"})

        for j, sus in enumerate(mb.get("susceptibilities") or []):
            interp = sus.get("interpretation", "")
            disp = _SUSCEPTIBILITY_DISPLAY.get(interp, {})
            sus_id = f"mb-sus-{base}-{j}"
            sus_obs: dict[str, Any] = {
                "resourceType": "Observation", "id": sus_id, "status": "final",
                "category": lab_category,
                "code": {"coding": [_micro_coding("loinc", sus.get("antibiotic_loinc", ""), lang)]},
                "subject": subject,
                "specimen": {"reference": f"Specimen/{spec_id}"},
                "valueCodeableConcept": {"coding": [{
                    "system": get_system_uri("hl7-observation-interpretation"),
                    "code": interp,
                    "display": disp.get(lang, disp.get("en", interp)),
                }]},
            }
            if enc_ref:
                sus_obs["encounter"] = enc_ref
            out.append(sus_obs)
            result_refs.append({"reference": f"Observation/{sus_id}"})

        report: dict[str, Any] = {
            "resourceType": "DiagnosticReport", "id": f"dr-mb-{base}", "status": "final",
            "category": [{"coding": [{
                "system": get_system_uri("hl7-diagnostic-service-section"),
                "code": "MB", "display": "Microbiology",
            }]}],
            "code": culture_code, "subject": subject,
            "specimen": [{"reference": f"Specimen/{spec_id}"}],
            "result": result_refs,
        }
        if enc_ref:
            report["encounter"] = enc_ref
        if mb.get("reported_datetime"):
            report["effectiveDateTime"] = mb["reported_datetime"]
        out.append(report)

    return out


# --- Nursing flowsheet Observations (NEWS2 / GCS / Braden / Morse / ADL / I&O) ---


def _build_nursing_observations(ctx: BundleContext) -> list[dict]:
    """Build FHIR Observation resources for nursing flowsheet data (category=survey).

    Emits observations for:
    - NEWS2 score (no authoritative LOINC — code.text only)
    - GCS total (LOINC 9269-2)
    - Braden scale total (LOINC 38227-5)
    - Morse fall risk total (LOINC 59460-6) with fall_risk_level in interpretation
    - Barthel index total (LOINC 96761-2)
    - Fluid intake total 24h (LOINC 9108-2)
    - Urine output 24h (LOINC 9192-6)
    - Fluid output total 24h (LOINC 9262-7)
    """
    enc = ctx.primary_enc_id
    lang = "ja" if ctx.country == "JP" else "en"
    subject: dict[str, Any] = {"reference": f"Patient/{ctx.patient_id}"}
    enc_ref: dict[str, Any] | None = (
        {"reference": f"Encounter/{enc}"} if enc else None
    )
    out: list[dict] = []

    def _obs_base(obs_id: str, effective: str | None) -> dict[str, Any]:
        """Return the shared skeleton of a survey Observation."""
        resource: dict[str, Any] = {
            "resourceType": "Observation",
            "id": obs_id,
            "status": "final",
            "category": _survey_category(),
            "subject": subject,
        }
        if enc_ref:
            resource["encounter"] = enc_ref
        if effective:
            resource["effectiveDateTime"] = effective
        return resource

    # --- Vital signs: NEWS2 and GCS ---
    for i, vs in enumerate(ctx.record.get("vital_signs") or []):
        ts: str | None = vs.get("timestamp")
        effective = ts if isinstance(ts, str) else (str(ts) if ts is not None else None)

        news2 = vs.get("news2_score")
        if news2 is not None:
            obs = _obs_base(f"news2-{enc or ctx.patient_id}-{i}", effective)
            # NEWS2 has no authoritative LOINC — emit code.text only (per AD brief)
            obs["code"] = {"text": "NEWS2"}
            obs["valueInteger"] = int(news2)
            out.append(obs)

        gcs = vs.get("gcs_score")
        if gcs is not None:
            obs = _obs_base(f"gcs-{enc or ctx.patient_id}-{i}", effective)
            obs["code"] = {
                "coding": [_loinc_coding("9269-2", lang)],
                "text": code_lookup("loinc", "9269-2", lang) or "Glasgow coma score total",
            }
            obs["valueInteger"] = int(gcs)
            out.append(obs)

    # --- Nursing risk assessments: Braden and Morse ---
    for i, nra in enumerate(ctx.record.get("nursing_risk_assessments") or []):
        nra_date: str | None = nra.get("date")
        effective = nra_date if isinstance(nra_date, str) else (
            str(nra_date) if nra_date is not None else None
        )

        braden = nra.get("braden_total")
        if braden is not None:
            obs = _obs_base(f"braden-{enc or ctx.patient_id}-{i}", effective)
            obs["code"] = {
                "coding": [_loinc_coding("38227-5", lang)],
                "text": code_lookup("loinc", "38227-5", lang) or "Braden scale total score",
            }
            obs["valueInteger"] = int(braden)
            out.append(obs)

        morse = nra.get("morse_total")
        if morse is not None:
            obs = _obs_base(f"morse-{enc or ctx.patient_id}-{i}", effective)
            morse_text = (
                code_lookup("loinc", "59460-6", lang) or "Fall risk total [Morse Fall Scale]"
            )
            obs["code"] = {
                "coding": [_loinc_coding("59460-6", lang)],
                "text": morse_text,
            }
            obs["valueInteger"] = int(morse)
            fall_level = nra.get("fall_risk_level")
            if fall_level:
                # Clinosim Morse risk bands ("low"/"moderate"/"high") → HL7 v3
                # ObservationInterpretation L / N / H.
                _fall_interp: dict[str, tuple[str, str, str]] = {
                    "low": ("L", "Low", "低リスク"),
                    "moderate": ("N", "Normal", "中リスク"),
                    "high": ("H", "High", "高リスク"),
                }
                code_val, display_en, display_ja = _fall_interp.get(
                    str(fall_level).lower(), ("N", "Normal", "通常")
                )
                interp_display = display_ja if ctx.country == "JP" else display_en
                interp_text = (
                    f"転倒リスク: {fall_level}"
                    if ctx.country == "JP"
                    else f"Fall risk: {fall_level}"
                )
                obs["interpretation"] = [{
                    "coding": [{
                        "system": get_system_uri("hl7-observation-interpretation"),
                        "code": code_val,
                        "display": interp_display,
                    }],
                    "text": interp_text,
                }]
            out.append(obs)

    # --- ADL assessments: Barthel index ---
    for i, adl in enumerate(ctx.record.get("adl_assessments") or []):
        adl_date = adl.get("date")
        effective = adl_date if isinstance(adl_date, str) else (
            str(adl_date) if adl_date is not None else None
        )

        barthel = adl.get("barthel_score")
        if barthel is not None:
            obs = _obs_base(f"barthel-{enc or ctx.patient_id}-{i}", effective)
            obs["code"] = {
                "coding": [_loinc_coding("96761-2", lang)],
                "text": code_lookup("loinc", "96761-2", lang) or "Total score Barthel Index",
            }
            obs["valueInteger"] = int(barthel)
            out.append(obs)

    # --- Intake and output records ---
    for i, io in enumerate(ctx.record.get("intake_output_records") or []):
        io_date = io.get("date")
        effective = io_date if isinstance(io_date, str) else (
            str(io_date) if io_date is not None else None
        )

        # Fluid intake total 24h = iv + oral + other (LOINC 9108-2)
        iv_ml = io.get("intake_iv_ml") or 0
        oral_ml = io.get("intake_oral_ml") or 0
        other_in_ml = io.get("intake_other_ml") or 0
        intake_total = iv_ml + oral_ml + other_in_ml
        if intake_total > 0:
            obs = _obs_base(f"intake-{enc or ctx.patient_id}-{i}", effective)
            obs["code"] = {
                "coding": [_loinc_coding("9108-2", lang)],
                "text": code_lookup("loinc", "9108-2", lang) or "Fluid intake total 24 hour",
            }
            obs["valueQuantity"] = {
                "value": int(intake_total),
                "unit": "mL",
                "system": get_system_uri("ucum"),
                "code": "mL",
            }
            out.append(obs)

        # Urine output 24h (component; LOINC 9192-6)
        urine_ml = io.get("output_urine_ml")
        if urine_ml is not None:
            obs = _obs_base(f"urine-{enc or ctx.patient_id}-{i}", effective)
            obs["code"] = {
                "coding": [_loinc_coding("9192-6", lang)],
                "text": code_lookup("loinc", "9192-6", lang) or "Urine output 24 hour",
            }
            obs["valueQuantity"] = {
                "value": int(urine_ml),
                "unit": "mL",
                "system": get_system_uri("ucum"),
                "code": "mL",
            }
            out.append(obs)

        # Fluid output total 24h = urine + drain + other (aggregate; LOINC 9262-7)
        drain_ml = io.get("output_drain_ml") or 0
        other_out_ml = io.get("output_other_ml") or 0
        output_total = (urine_ml or 0) + drain_ml + other_out_ml
        if output_total > 0:
            obs = _obs_base(f"output-{enc or ctx.patient_id}-{i}", effective)
            obs["code"] = {
                "coding": [_loinc_coding("9262-7", lang)],
                "text": code_lookup("loinc", "9262-7", lang) or "Fluid output total 24 hour",
            }
            obs["valueQuantity"] = {
                "value": int(output_total),
                "unit": "mL",
                "system": get_system_uri("ucum"),
                "code": "mL",
            }
            out.append(obs)

    return out


def _build_immunizations(ctx: BundleContext) -> list[dict]:
    """Build FHIR Immunization resources from CIF immunizations (CVX codes, AD-30/AD-56).

    Each ImmunizationRecord in ctx.record["immunizations"] maps to one FHIR Immunization.
    Display text is resolved via lookup("cvx", code, lang); never emitted as display == code.
    US output contains no Japanese characters; JP output uses Japanese display when available.
    """
    lang = "ja" if ctx.country == "JP" else "en"
    out: list[dict] = []

    for i, imm in enumerate(ctx.record.get("immunizations") or []):
        if isinstance(imm, dict):
            cvx = imm.get("vaccine_cvx", "")
            occurrence = imm.get("occurrence_date", "")
            status = imm.get("status", "completed")
            primary_source = imm.get("primary_source", True)
        else:
            # ImmunizationRecord dataclass (in-memory path)
            cvx = getattr(imm, "vaccine_cvx", "")
            occurrence = getattr(imm, "occurrence_date", "")
            status = getattr(imm, "status", "completed")
            primary_source = getattr(imm, "primary_source", True)

        if not cvx:
            continue

        display = code_lookup("cvx", cvx, lang)
        coding: dict[str, Any] = {"system": get_system_uri("cvx"), "code": cvx}
        if display and display != cvx:
            coding["display"] = display

        vaccine_code: dict[str, Any] = {"coding": [coding]}
        if display and display != cvx:
            vaccine_code["text"] = display

        # occurrence_date may be a date object or ISO string; normalise to YYYY-MM-DD
        occ_str = occurrence.isoformat() if hasattr(occurrence, "isoformat") else str(occurrence)

        resource: dict[str, Any] = {
            "resourceType": "Immunization",
            "id": f"imm-{ctx.patient_id}-{i}",
            "status": status,
            "vaccineCode": vaccine_code,
            "patient": {"reference": f"Patient/{ctx.patient_id}"},
            "occurrenceDateTime": occ_str,
            "primarySource": primary_source,
        }
        out.append(resource)

    return out


# Registry: emission order == list order. New Base/Module resources append a builder
# here (or via register_bundle_builder) instead of editing _build_bundle (AD-56).
_BUNDLE_BUILDERS: list[Callable[[BundleContext], list[dict]]] = [
    _bb_patient,
    _bb_coverage,
    _bb_encounters,
    _bb_conditions,
    _bb_allergies,
    _bb_occupation,
    _bb_labs,
    _bb_vitals,
    _bb_microbiology,
    _bb_medication_requests,
    _bb_medication_admins,
    _bb_procedures,
    _bb_practitioners,
    _build_nursing_observations,
    _build_immunizations,
]


def register_bundle_builder(builder: Callable[[BundleContext], list[dict]]) -> None:
    """Register a FHIR resource builder appended after the built-ins (AD-56).

    Deduplicated by function name (first registration wins), so a second builder with
    the same name — e.g. a re-import of the same module — is not double-registered.
    """
    if builder.__name__ not in {b.__name__ for b in _BUNDLE_BUILDERS}:
        _BUNDLE_BUILDERS.append(builder)


def available_builders() -> list[str]:
    """Names of the registered bundle builders, in execution order (introspection)."""
    return [b.__name__ for b in _BUNDLE_BUILDERS]


def _build_bundle(
    record: dict, country: str,
    roster_map: dict[str, dict] | None = None,
    hospital_config: dict | None = None,
) -> dict:
    """Build a FHIR R4 Bundle from a CIF patient record by running the builder registry."""
    if roster_map is None:
        roster_map = {}
    if hospital_config is None:
        hospital_config = {}
    patient_data = record.get("patient", {})
    dx = record.get("clinical_diagnosis", {})
    encounters = record.get("encounters") or []
    ctx = BundleContext(
        record=record,
        country=country,
        roster_map=roster_map,
        hospital_config=hospital_config,
        patient_data=patient_data,
        patient_id=patient_data.get("patient_id", "unknown"),
        is_readmission=record.get("is_readmission", False),
        prior_encounter_id=record.get("prior_encounter_id"),
        primary_dx_code=dx.get("discharge_diagnosis_code") or dx.get("admission_diagnosis_code", ""),
        admit_dx_code=dx.get("admission_diagnosis_code", ""),
        admit_dx_system=dx.get("admission_diagnosis_system", "icd-10-cm"),
        primary_enc_id=encounters[0].get("encounter_id", "") if encounters else "",
        patient_sex=patient_data.get("sex", ""),
    )

    entries: list[dict] = []
    for builder in _BUNDLE_BUILDERS:
        for resource in builder(ctx):
            entries.append(_entry(resource))

    return {
        "resourceType": "Bundle",
        "id": str(uuid.uuid4()),
        "type": "collection",
        "timestamp": datetime.now().isoformat(),
        "entry": entries,
    }


# ============================================================
# Resource builders
# ============================================================

_IDENTITY_CFG_CACHE: dict[str, dict] = {}

# FHIR R4 standard: payer organization type
_ORG_TYPE_SYSTEM = "http://terminology.hl7.org/CodeSystem/organization-type"
# FHIR R4 standard: beneficiary's relationship to the policy subscriber
_SUBSCRIBER_REL_SYSTEM = "http://terminology.hl7.org/CodeSystem/subscriber-relationship"


def _identity_cfg(country: str) -> dict:
    """Full resident-identity locale config (AD-54), cached."""
    if country not in _IDENTITY_CFG_CACHE:
        _IDENTITY_CFG_CACHE[country] = load_identity_config(country)
    return _IDENTITY_CFG_CACHE[country]


def _payer_name_map(country: str) -> dict[str, str]:
    """Map 保険者番号 → insurer name from locale (display resolved at output, AD-30)."""
    payers = _identity_cfg(country).get("payers", {})
    out: dict[str, str] = {}
    for entries in payers.values():
        for e in entries or []:
            if e.get("number"):
                out[str(e["number"])] = str(e.get("name", e["number"]))
    return out


def _build_coverage_resources(patient_data: dict, country: str) -> list[dict]:
    """Build JP Core Coverage + payor Organization from the patient's insurance enrollment.

    Reads CIF data only (no dependency on the identity module — module independence).
    `national_id` is never read here: the privacy chokepoint (AD-54) means individual
    numbers are never emitted to FHIR.
    """
    cfg = _identity_cfg(country).get("fhir_coverage", {})
    if not cfg:
        return []
    name_map = _payer_name_map(country)
    type_labels = _identity_cfg(country).get("coverage_type_labels", {})
    identity = patient_data.get("identity") or {}
    enrollments = identity.get("enrollments") or []
    pid = patient_data.get("patient_id", "")
    resources: list[dict] = []

    for idx, enr in enumerate(enrollments):
        insurer = enr.get("insurer_number") or ""
        number = enr.get("member_id") or ""
        symbol = enr.get("group_symbol")
        branch = enr.get("branch_number")
        category = enr.get("category") or ""
        if not insurer or not number:
            continue

        payer_org_id = f"payer-{insurer}"
        resources.append({
            "resourceType": "Organization",
            "id": payer_org_id,
            "identifier": [{
                "system": cfg.get("insurer_number_system", ""),
                "value": insurer,
            }],
            "type": [{"coding": [{
                "system": _ORG_TYPE_SYSTEM,
                "code": "pay",
                "display": "Payer",
            }]}],
            "name": name_map.get(insurer, insurer),
        })

        # JP Core extensions: 記号 / 番号 / 枝番
        extensions: list[dict] = []
        if symbol:
            extensions.append({"url": cfg.get("ext_symbol", ""), "valueString": symbol})
        extensions.append({"url": cfg.get("ext_number", ""), "valueString": number})
        if branch:
            extensions.append({"url": cfg.get("ext_subnumber", ""), "valueString": branch})

        # Composite member identifier: 保険者番号:記号:番号:枝番
        composite = ":".join([insurer, symbol or "", number, branch or ""])
        subscriber = f"{symbol}:{number}" if symbol else number

        coverage: dict[str, Any] = {
            "resourceType": "Coverage",
            "id": f"cov-{pid}-{idx}",
            "extension": extensions,
            "identifier": [{"system": cfg.get("member_id_system", ""), "value": composite}],
            "status": "active",
            "subscriberId": subscriber,
            "beneficiary": {"reference": f"Patient/{pid}"},
            "payor": [{"reference": f"Organization/{payer_org_id}"}],
        }
        if cfg.get("profile"):
            coverage["meta"] = {"profile": [cfg["profile"]]}
        if branch:
            coverage["dependent"] = branch
        # Beneficiary's relationship to the subscriber: 被扶養者 → not self.
        rel_code = "other" if category == "dependent" else "self"
        coverage["relationship"] = {
            "coding": [{"system": _SUBSCRIBER_REL_SYSTEM, "code": rel_code}]
        }
        # Coverage.type: human label (text-only CodeableConcept — no fabricated codes).
        label = type_labels.get(category)
        if label:
            coverage["type"] = {"text": label}
        period = {}
        if enr.get("valid_from"):
            period["start"] = enr["valid_from"]
        if enr.get("valid_to"):
            period["end"] = enr["valid_to"]
        if period:
            coverage["period"] = period
        resources.append(coverage)

    return resources


def _build_patient(p: dict, country: str) -> dict:
    """Build FHIR Patient resource with locale-aware name."""
    # Extract name from patient profile
    name_data = p.get("name", {})
    family = name_data.get("family_name", p.get("patient_id", ""))
    given = name_data.get("given_name", "")

    gender = "female" if p.get("sex") == "F" else "male"
    dob = p.get("date_of_birth")

    # Build FHIR HumanName
    fhir_name: dict[str, Any] = {"family": family, "given": [given]}
    phonetic = name_data.get("phonetic")
    if phonetic and country == "JP":
        # JP: add phonetic representation (katakana)
        fhir_name["extension"] = [{
            "url": "http://hl7.org/fhir/StructureDefinition/iso21090-EN-representation",
            "valueString": "SYL",
        }]

    pid = p.get("patient_id", str(uuid.uuid4()))
    # Hospital MRN identifier system (country-specific)
    mrn_system = (
        "urn:oid:1.2.392.100495.20.3.51.1"  # JP example MRN OID
        if country == "JP"
        else "http://hospital.example.org/identifiers/mrn"
    )
    resource: dict[str, Any] = {
        "resourceType": "Patient",
        "id": pid,
        "identifier": [{
            "use": "usual",
            "type": {
                "coding": [{
                    "system": get_system_uri("hl7-v2-0203"),
                    "code": "MR",
                    "display": "Medical Record Number",
                }],
                "text": "MRN" if country != "JP" else "診療録番号",
            },
            "system": mrn_system,
            "value": pid,
            "assigner": {"reference": "Organization/hospital-main"},
        }],
        "active": True,
        "name": [fhir_name],
        "gender": gender,
    }

    if dob:
        resource["birthDate"] = dob if isinstance(dob, str) else str(dob)

    # Extensions for blood type
    if p.get("blood_type"):
        resource["extension"] = [{
            "url": "http://hl7.org/fhir/StructureDefinition/patient-bloodType",
            "valueString": f"{p['blood_type']}{p.get('rh_factor', '+')}",
        }]

    # Address
    addr = p.get("address")
    if addr and isinstance(addr, dict):
        fhir_addr = _build_address(addr, country)
        if fhir_addr:
            resource["address"] = [fhir_addr]

    # Telecom (phone)
    contact = p.get("contact")
    if contact and isinstance(contact, dict):
        telecoms = _build_telecom(contact)
        if telecoms:
            resource["telecom"] = telecoms

    # Marital status
    marital = p.get("marital_status", "")
    if marital:
        resource["maritalStatus"] = {
            "coding": [{
                "system": get_system_uri("hl7-v3-maritalstatus"),
                "code": marital,
                "display": (_MARITAL_DISPLAY_JA if country == "JP" else _MARITAL_DISPLAY).get(marital, ""),
            }],
        }

    # Communication / preferred language
    lang = p.get("preferred_language", "")
    if lang:
        resource["communication"] = [{
            "language": {
                "coding": [{
                    "system": "urn:ietf:bcp:47",
                    "code": lang,
                    "display": _LANG_DISPLAY.get(lang, lang),
                }],
            },
            "preferred": True,
        }]

    # Emergency contact
    if contact and isinstance(contact, dict):
        emer_name = contact.get("emergency_contact_name", "")
        emer_phone = contact.get("emergency_contact_phone", "")
        emer_rel = contact.get("emergency_contact_relationship", "")
        if emer_name or emer_phone:
            ec: dict[str, Any] = {}
            if emer_rel:
                ec["relationship"] = [{
                    "coding": [{
                        "system": get_system_uri("hl7-v2-0131"),
                        "code": "C",
                        "display": "Emergency Contact",
                    }],
                    "text": _localize_display(emer_rel, country, _RELATIONSHIP_DISPLAY_JA),
                }]
            if emer_name:
                ec["name"] = {"text": emer_name}
            if emer_phone:
                ec["telecom"] = [{
                    "system": "phone", "value": emer_phone, "use": "mobile",
                }]
            resource["contact"] = [ec]

    return resource


_MARITAL_DISPLAY = {
    "S": "Never Married", "M": "Married", "D": "Divorced",
    "W": "Widowed", "U": "Unmarried", "T": "Domestic partner",
}
_MARITAL_DISPLAY_JA = {
    "S": "未婚", "M": "既婚", "D": "離婚",
    "W": "死別", "U": "未婚", "T": "事実婚",
}

_LANG_DISPLAY = {
    "en-US": "English (US)",
    "ja-JP": "Japanese (Japan)",
}


# ============================================================
# AllergyIntolerance
# ============================================================


# Occupation category localization for Observation.valueCodeableConcept
def _build_occupation_observation(
    occupation: str, patient_id: str, country: str,
) -> dict | None:
    """Build FHIR Observation for patient occupation (social history).

    Uses US Core Patient Occupation profile (LOINC 11341-5).
    Reference: http://hl7.org/fhir/us/core/StructureDefinition/us-core-occupation
    """
    if not occupation:
        return None
    display_map = _OCCUPATION_DISPLAY_JA if country == "JP" else _OCCUPATION_DISPLAY_EN
    display = display_map.get(occupation, occupation.title())
    category_text = "社会歴" if country == "JP" else "Social History"
    return {
        "resourceType": "Observation",
        "id": f"occupation-{patient_id}",
        "status": "final",
        "category": [{
            "coding": [{
                "system": get_system_uri("hl7-observation-category"),
                "code": "social-history",
                "display": _localize_display("Social History", country, _CATEGORY_DISPLAY_JA),
            }],
            "text": category_text,
        }],
        "code": {
            "coding": [{
                "system": get_system_uri("loinc"),
                "code": "11341-5",
                "display": "History of Occupation",
            }],
            "text": "職業" if country == "JP" else "Occupation",
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "valueCodeableConcept": {
            "coding": [{
                "system": get_system_uri("occupation-category"),
                "code": occupation,
                "display": display,
            }],
            "text": display,
        },
    }


def _build_allergy_intolerance(
    allergy: dict, patient_id: str, index: int, country: str,
) -> dict | None:
    """Build FHIR AllergyIntolerance from CIF allergy data."""
    substance = allergy.get("substance", "")
    if not substance:
        return None

    # Localize substance display for JP
    substance_display = _localize_drug_name(substance, country) if country == "JP" else substance

    rxnorm = _ALLERGEN_RXNORM.get(substance, "")
    code: dict[str, Any] = {"text": substance_display}
    if rxnorm:
        code["coding"] = [{
            "system": get_system_uri("rxnorm"),
            "code": rxnorm,
            "display": substance_display,
        }]

    severity = allergy.get("severity", "mild").lower()
    criticality = "high" if severity == "severe" else "low"

    reaction_type = allergy.get("reaction_type", "")
    reaction: dict[str, Any] = {"severity": severity}
    if reaction_type:
        reaction["manifestation"] = [{
            "text": reaction_type,
        }]

    return {
        "resourceType": "AllergyIntolerance",
        "id": f"allergy-{patient_id}-{index:02d}",  # patient-scoped is OK (allergies are patient-level)
        "clinicalStatus": {
            "coding": [{
                "system": get_system_uri("hl7-allergyintolerance-clinical"),
                "code": "active",
                "display": "Active",
            }],
        },
        "verificationStatus": {
            "coding": [{
                "system": get_system_uri("hl7-allergyintolerance-verification"),
                "code": "confirmed",
                "display": "Confirmed",
            }],
        },
        "type": "allergy",
        "category": ["medication"],
        "criticality": criticality,
        "code": code,
        "patient": {"reference": f"Patient/{patient_id}"},
        "reaction": [reaction],
    }


# Clinical abbreviations / short names for common conditions.
# Keyed by ICD base code (before "."), with per-language short forms.
# coding[].display keeps the official ICD name; code.text uses these.


# JIS X 0401 prefecture codes

# US state abbreviation to FIPS code (common ones)


def _build_lab_observation(
    order: dict, result: dict, patient_id: str, index: int,
    country: str, patient_sex: str = "", encounter_id: str = "",
) -> dict | None:
    """Build FHIR Observation resource for a lab result."""
    value = result.get("value")
    if value is None:
        return None

    # Prefer the result's canonical analyte name (stat/serial/alias resolved upstream)
    # over the raw order label, so the code mapping resolves (AD-55).
    lab_name = result.get("lab_name") or order.get("display_name", "Unknown")

    # test_name → code mapping still lives in locale (internal name → standard code)
    country_code = "JP" if country != "US" else "US"
    lang = "ja" if country_code == "JP" else "en"
    code_map = load_code_mapping("lab", country_code)
    code_value = code_map.get(lab_name, order.get("order_code", ""))

    # Display text comes from codes module (via standard code)
    code_system_key = "jlac10" if country_code == "JP" else "loinc"
    display_name = code_lookup(code_system_key, code_value, lang) if code_value else lab_name
    if display_name == code_value:  # no translation found
        display_name = lab_name
    code_system = get_system_uri(code_system_key)

    # Use encounter_id-scoped IDs to avoid collisions across patient's multiple encounters
    enc_scope = encounter_id or patient_id
    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "id": f"lab-{enc_scope}-{index:04d}",
        "status": "final",
        "category": [{
            "coding": [{
                "system": get_system_uri("hl7-observation-category"),
                "code": "laboratory",
                "display": _localize_display("Laboratory", country, _CATEGORY_DISPLAY_JA),
            }],
            "text": _localize_display("Laboratory", country, _CATEGORY_DISPLAY_JA),
        }],
        "code": {
            "coding": [{"system": code_system, "code": code_value, "display": display_name}],
            "text": display_name,
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": result.get("result_datetime", ""),
    }

    if isinstance(value, (int, float)):
        unit_str = result.get("unit", "")
        resource["valueQuantity"] = {
            "value": value,
            "unit": unit_str,
            "system": get_system_uri("ucum"),
            "code": unit_str,  # UCUM code identical to display unit
        }
    else:
        resource["valueString"] = str(value)

    # Reference range (JP: JCCLS共用基準範囲)
    ref_range = _build_reference_range(lab_name, patient_sex, country_code)
    if ref_range:
        resource["referenceRange"] = ref_range

    # Interpretation — recompute from value vs reference range when possible
    # (ensures consistency per FHIR spec: both must be consistent when provided).
    # Fall back to flag-based mapping for non-numeric or no-range cases.
    flag = result.get("flag")
    interp_map = {
        "H": {"code": "H", "display": "High"},
        "L": {"code": "L", "display": "Low"},
        "H*": {"code": "HH", "display": "Critical high"},
        "L*": {"code": "LL", "display": "Critical low"},
        "critical": {"code": "AA", "display": "Critical abnormal"},
    }
    coded: dict[str, str] | None = None
    if isinstance(value, (int, float)) and ref_range:
        # Find normal range (type=normal or unlabeled first entry)
        normal_rng = None
        for rng in ref_range:
            tc = (rng.get("type") or {}).get("coding", [{}])[0].get("code", "")
            if tc == "normal" or not tc:
                normal_rng = rng
                break
        if normal_rng:
            low_v = (normal_rng.get("low") or {}).get("value")
            high_v = (normal_rng.get("high") or {}).get("value")
            is_critical = flag in ("H*", "L*", "critical")
            out_low = low_v is not None and value < low_v
            out_high = high_v is not None and value > high_v
            if is_critical and out_low:
                coded = {"code": "LL", "display": "Critical low"}
            elif is_critical and out_high:
                coded = {"code": "HH", "display": "Critical high"}
            elif is_critical:
                coded = {"code": "AA", "display": "Critical abnormal"}
            elif out_low:
                coded = {"code": "L", "display": "Low"}
            elif out_high:
                coded = {"code": "H", "display": "High"}
            else:
                coded = {"code": "N", "display": "Normal"}
    if coded is None:
        coded = interp_map.get(flag) if flag else {"code": "N", "display": "Normal"}
    coded = _localize_interp(coded, country)
    resource["interpretation"] = [{
        "coding": [{
            "system": get_system_uri("hl7-observation-interpretation"),
            **coded,
        }],
    }]

    # Encounter reference (use order's encounter_id, fallback to primary)
    enc_ref = order.get("encounter_id", "") or encounter_id
    if enc_ref:
        resource["encounter"] = {"reference": f"Encounter/{enc_ref}"}

    # Performer (lab technician or ordering physician)
    performer_id = result.get("performed_by", "") or order.get("ordered_by", "")
    if performer_id:
        resource["performer"] = [{"reference": f"Practitioner/{performer_id}"}]

    return resource


def _build_vital_observations(
    vs: dict, patient_id: str, index: int, country: str = "US",
    encounter_id: str = "",
) -> list[dict]:
    """Build FHIR Observation resources for vital signs (one per parameter)."""
    entries = []

    # (field, loinc, display_en, display_ja, unit, low, high, critical_low, critical_high, time_offset_sec)
    # crit_high=None means no upper critical bound (e.g., SpO2 cannot be critically high)
    # time_offset: per-field realistic delay within a vital-sign set
    # BP/HR measured simultaneously (same device cycle), Temp added later, RR counted last
    _vital_map = [
        ("heart_rate", "8867-4", "Heart rate", "脈拍", "/min", 60, 100, 40, 130, 0),
        ("systolic_bp", "8480-6", "Systolic blood pressure", "収縮期血圧", "mm[Hg]", 90, 140, 80, 200, 0),
        ("diastolic_bp", "8462-4", "Diastolic blood pressure", "拡張期血圧", "mm[Hg]", 60, 90, 50, 120, 0),
        ("spo2", "2708-6", "Oxygen saturation", "酸素飽和度", "%", 95, 100, 88, None, 5),
        ("temperature_celsius", "8310-5", "Body temperature", "体温", "Cel", 36.0, 37.5, 35.0, 39.5, 30),
        ("respiratory_rate", "9279-1", "Respiratory rate", "呼吸数", "/min", 12, 20, 8, 30, 60),
    ]

    for field, loinc, display_en, display_ja, unit, low, high, crit_low, crit_high, offset_sec in _vital_map:
        display = display_ja if country == "JP" else display_en
        value = vs.get(field)
        if value is None:
            continue

        obs: dict[str, Any] = {
            "resourceType": "Observation",
            "id": f"vs-{encounter_id or patient_id}-{index:04d}-{field}",
            "status": "final",
            "category": [{
                "coding": [{
                    "system": get_system_uri("hl7-observation-category"),
                    "code": "vital-signs",
                    "display": _localize_display("Vital Signs", country, _CATEGORY_DISPLAY_JA),
                }],
                "text": _localize_display("Vital Signs", country, _CATEGORY_DISPLAY_JA),
            }],
            "code": {
                "coding": [{"system": get_system_uri("loinc"), "code": loinc, "display": display}],
                "text": display,
            },
            "subject": {"reference": f"Patient/{patient_id}"},
            "valueQuantity": {
                "value": value,
                "unit": unit,
                "system": get_system_uri("ucum"),
                "code": unit,
            },
        }
        # Add timestamp with per-field offset (BP/HR same, Temp +30s, RR +60s, SpO2 +5s)
        timestamp = vs.get("timestamp")
        if timestamp:
            try:
                from datetime import datetime as _dt
                from datetime import timedelta as _td
                base_dt = _dt.fromisoformat(str(timestamp).replace("Z","+00:00").split("+")[0])
                shifted = base_dt + _td(seconds=offset_sec)
                obs["effectiveDateTime"] = shifted.isoformat()
            except (ValueError, TypeError):
                obs["effectiveDateTime"] = timestamp if isinstance(timestamp, str) else str(timestamp)

        # Encounter reference
        if encounter_id:
            obs["encounter"] = {"reference": f"Encounter/{encounter_id}"}

        # Performer (nurse who measured)
        performer_id = vs.get("measured_by", "")
        if performer_id:
            obs["performer"] = [{"reference": f"Practitioner/{performer_id}"}]

        # Reference range — normal range (always) + critical range (when defined)
        range_text = "成人正常範囲" if country == "JP" else "Normal adult range"
        crit_text = "パニック値" if country == "JP" else "Critical range"
        ref_ranges = [{
            "low": {"value": low, "unit": unit, "system": get_system_uri("ucum"), "code": unit},
            "high": {"value": high, "unit": unit, "system": get_system_uri("ucum"), "code": unit},
            "type": {
                "coding": [{
                    "system": get_system_uri("hl7-referencerange-meaning"),
                    "code": "normal",
                    "display": "正常範囲" if country == "JP" else "Normal Range",
                }],
            },
            "text": range_text,
        }]
        # Add critical range as separate entry (panic values)
        if crit_low is not None or crit_high is not None:
            crit_range: dict[str, Any] = {
                "type": {
                    "coding": [{
                        "system": get_system_uri("hl7-referencerange-meaning"),
                        "code": "treatment",
                        "display": "パニック範囲" if country == "JP" else "Critical Range",
                    }],
                },
                "text": crit_text,
            }
            if crit_low is not None:
                crit_range["low"] = {"value": crit_low, "unit": unit, "system": get_system_uri("ucum"), "code": unit}
            if crit_high is not None:
                crit_range["high"] = {"value": crit_high, "unit": unit, "system": get_system_uri("ucum"), "code": unit}
            ref_ranges.append(crit_range)
        obs["referenceRange"] = ref_ranges

        # Interpretation (compute from value vs reference range — always consistent)
        interp_code = "N"
        interp_display = "Normal"
        if crit_low is not None and value <= crit_low:
            interp_code = "LL"; interp_display = "Critical low"
        elif crit_high is not None and value >= crit_high:
            interp_code = "HH"; interp_display = "Critical high"
        elif value < low:
            interp_code = "L"; interp_display = "Low"
        elif value > high:
            interp_code = "H"; interp_display = "High"
        obs["interpretation"] = [{
            "coding": [{
                "system": get_system_uri("hl7-observation-interpretation"),
                "code": interp_code,
                "display": _localize_display(interp_display, country, _INTERPRETATION_DISPLAY_JA),
            }],
        }]

        entries.append(_entry(obs))

    # Consciousness level (AVPU) — Glasgow Coma Scale-related
    loc = vs.get("consciousness_level", "")
    if loc:
        loc_display_map = {
            "A": ("Alert", "248234008"),
            "V": ("Responds to voice", "248236005"),
            "P": ("Responds to pain", "248237001"),
            "U": ("Unresponsive", "422768004"),
        }
        loc_display, loc_snomed = loc_display_map.get(loc, ("Alert", "248234008"))
        loc_label_ja = {"A": "意識清明", "V": "呼びかけに反応", "P": "痛み刺激に反応", "U": "無反応"}
        display = loc_label_ja.get(loc, loc_display) if country == "JP" else loc_display
        loc_obs: dict[str, Any] = {
            "resourceType": "Observation",
            "id": f"vs-{encounter_id or patient_id}-{index:04d}-loc",
            "status": "final",
            "category": [{
                "coding": [{
                    "system": get_system_uri("hl7-observation-category"),
                    "code": "vital-signs",
                    "display": _localize_display("Vital Signs", country, _CATEGORY_DISPLAY_JA),
                }],
                "text": _localize_display("Vital Signs", country, _CATEGORY_DISPLAY_JA),
            }],
            "code": {
                "coding": [{
                    "system": get_system_uri("loinc"),
                    "code": "80288-4",
                    "display": "Level of consciousness AVPU",
                }],
                "text": "意識レベル (AVPU)" if country == "JP" else "Level of consciousness (AVPU)",
            },
            "subject": {"reference": f"Patient/{patient_id}"},
            "valueCodeableConcept": {
                "coding": [{
                    "system": get_system_uri("snomed-ct"),
                    "code": loc_snomed,
                    "display": loc_display,
                }],
                "text": display,
            },
        }
        timestamp = vs.get("timestamp")
        if timestamp:
            loc_obs["effectiveDateTime"] = timestamp if isinstance(timestamp, str) else str(timestamp)
        if encounter_id:
            loc_obs["encounter"] = {"reference": f"Encounter/{encounter_id}"}
        entries.append(_entry(loc_obs))

    # Supplemental oxygen (LOINC 3151-8 = inhaled oxygen flow rate)
    if vs.get("on_supplemental_oxygen"):
        flow = vs.get("oxygen_flow_rate_lpm")
        device = vs.get("oxygen_delivery_device", "")
        o2_obs: dict[str, Any] = {
            "resourceType": "Observation",
            "id": f"vs-{encounter_id or patient_id}-{index:04d}-o2",
            "status": "final",
            "category": [{
                "coding": [{
                    "system": get_system_uri("hl7-observation-category"),
                    "code": "vital-signs",
                    "display": _localize_display("Vital Signs", country, _CATEGORY_DISPLAY_JA),
                }],
                "text": _localize_display("Vital Signs", country, _CATEGORY_DISPLAY_JA),
            }],
            "code": {
                "coding": [{
                    "system": get_system_uri("loinc"),
                    "code": "3151-8",
                    "display": "Inhaled oxygen flow rate",
                }],
                "text": "酸素投与量" if country == "JP" else "Supplemental oxygen flow rate",
            },
            "subject": {"reference": f"Patient/{patient_id}"},
        }
        if flow is not None:
            o2_obs["valueQuantity"] = {
                "value": flow,
                "unit": "L/min",
                "system": get_system_uri("ucum"),
                "code": "L/min",
            }
        if device:
            o2_obs["component"] = [{
                "code": {
                    "coding": [{
                        "system": get_system_uri("loinc"),
                        "code": "8478-0",
                        "display": "Inhaled oxygen delivery system",
                    }],
                },
                "valueString": device,
            }]
        timestamp = vs.get("timestamp")
        if timestamp:
            o2_obs["effectiveDateTime"] = timestamp if isinstance(timestamp, str) else str(timestamp)
        if encounter_id:
            o2_obs["encounter"] = {"reference": f"Encounter/{encounter_id}"}
        entries.append(_entry(o2_obs))

    return entries


# SNOMED specialty codes


