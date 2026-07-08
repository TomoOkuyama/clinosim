"""FHIR R4 adapter — Stage 3: convert CIF structural data to FHIR R4 Bundles.

Generates one FHIR Bundle (JSON) per patient containing:
  Patient, Encounter, Observation (labs + vitals), MedicationRequest, Practitioner references.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from clinosim.modules.output._fhir_care_level import _build_care_level  # noqa: F401
from clinosim.modules.output._fhir_code_status import _build_code_status  # noqa: F401
from clinosim.modules.output.cif_reader import CIFReader

# FA-1 (Phases 1-13) split this adapter's leaf data, shared fragment helpers, and
# per-theme resource builders into sibling _fhir_* modules. The blocks below are
# re-imported here so existing `from ...fhir_r4_adapter import X` call sites keep
# working (facade). They are marked # noqa: F401 because many symbols are now used
# only by the extracted modules (which import them directly) and are re-exported
# purely as a compatibility facade; the # noqa keeps the facade stable as further
# builders move out, without per-symbol import churn each phase.
from clinosim.modules.output._fhir_common import (  # noqa: F401
    BundleContext,
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
from clinosim.modules.output._fhir_device import (  # noqa: F401
    _build_device,
    _build_device_use,
)
from clinosim.modules.output._fhir_diagnostic_report import (  # noqa: F401
    _bb_diagnostic_reports,
    build_lab_panel_reports,  # kept for backward compat (tests + external callers)
)
from clinosim.modules.output._fhir_documents import (  # noqa: F401
    _bb_document_references,
)
from clinosim.modules.output._fhir_encounter import _build_encounter  # noqa: F401
from clinosim.modules.output._fhir_facility import _build_facility_bundle  # noqa: F401
from clinosim.modules.output._fhir_family_history import _build_family_history  # noqa: F401
from clinosim.modules.output._fhir_hai import _build_hai_conditions  # noqa: F401
from clinosim.modules.output._fhir_immunization import _build_immunizations  # noqa: F401
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
from clinosim.modules.output._fhir_microbiology import _bb_microbiology  # noqa: F401
from clinosim.modules.output._fhir_nursing import _build_nursing_observations  # noqa: F401
from clinosim.modules.output._fhir_observations import (  # noqa: F401
    _bb_labs,
    _build_lab_observation,
    _build_vital_observations,
)
from clinosim.modules.output._fhir_patient import (  # noqa: F401
    _IDENTITY_CFG_CACHE,
    _ORG_TYPE_SYSTEM,
    _SUBSCRIBER_REL_SYSTEM,
    _build_coverage_resources,
    _build_occupation_observation,
    _build_patient,
    _identity_cfg,
    _payer_name_map,
)
from clinosim.modules.output._fhir_practitioner import (  # noqa: F401
    _build_practitioner,
    _build_practitioner_role,
)
from clinosim.modules.output._fhir_procedures import _build_procedure  # noqa: F401
from clinosim.modules.output._fhir_reference_data import (  # noqa: F401
    _ALLERGEN_RXNORM,
    _ENCOUNTER_TYPE_SNOMED_CODE,
    _PREFECTURE_CODE,
    _ROLE_PREFIX_MAP,
    _ROUTE_SNOMED,
    _SEVERITY_SNOMED,
    _SPECIALTY_SNOMED,
)
from clinosim.modules.output._fhir_service_request import (  # noqa: F401
    _bb_service_requests,
)
from clinosim.modules.output._fhir_endpoint import (  # noqa: F401
    _bb_endpoints,
)
from clinosim.modules.output._fhir_imaging_study import (  # noqa: F401
    _bb_imaging_studies,
)
from clinosim.modules.output._fhir_allergy_intolerance import (  # noqa: F401
    _bb_allergy_intolerances,
)
from clinosim.modules.output._fhir_care_team import (  # noqa: F401
    _bb_care_teams,
)
from clinosim.modules.output._fhir_clinical_impression import (  # noqa: F401
    _bb_clinical_impressions,
)
from clinosim.modules.output._fhir_composition import (  # noqa: F401
    _bb_compositions,
)
from clinosim.modules.output._fhir_smoking_alcohol import (  # noqa: F401
    _build_alcohol_use,
    _build_smoking_status,
)


def convert_cif_to_fhir(
    cif_dir: str,
    output_dir: str,
    country: str = "US",
    narrative_version: str = "current",
) -> None:
    """Read CIF structural data and write FHIR R4 Bulk Data Export NDJSON files.

    Output follows the HL7 FHIR Bulk Data Access spec:
    one NDJSON file per resource type (Patient.ndjson, Encounter.ndjson, etc.).
    Each line is a single FHIR resource (no Bundle wrapping).

    DocumentReference / Composition resources are emitted from
    record.documents, merged with narrative content by CIFReader (AD-65 Task
    4): structural stubs are created by document_enricher at POST_ENCOUNTER
    (Task 8); narrative text/sections are populated by a separate Stage 2
    NarrativePass (Task 3) and merged in at read time here.

    Args:
        cif_dir: path to a cif/ directory containing structural/.
        output_dir: directory to write the FHIR NDJSON files.
        country: "US" or "JP" — selects display language and code systems.
        narrative_version: narrative layer to merge in — "current" (default,
            resolved via cif/narratives/current_version.txt, falling back to
            "template") or an explicit version_id.
    """
    os.makedirs(output_dir, exist_ok=True)

    reader = CIFReader(cif_dir, narrative_version=narrative_version)

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

        # Walk patient records (structural + merged narrative), build per-record
        # FHIR resources, write each line
        for record in reader.iter_patients():
            bundle = _build_bundle(record, country, roster_map, hospital_config)
            for entry in bundle.get("entry", []):
                write(entry["resource"])

        # Manifest (FHIR Bulk Data spec)
        manifest = {
            "transactionTime": datetime.now().isoformat(),
            "request": f"clinosim generate (country={country})",
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


def _bb_occupation(ctx: BundleContext) -> list[dict]:
    # US Core Patient Occupation (LOINC 11341-5). Patient-level, not encounter-scoped.
    occupation = ctx.patient_data.get("occupation", "")
    if occupation:
        occ_obs = _build_occupation_observation(occupation, ctx.patient_id, ctx.country)
        if occ_obs:
            # C1-12 (session 41 cycle 1): US Core / JP Core social-history
            # profile lists effective[x] as MUST-SUPPORT. Use earliest encounter
            # admission as the SDOH-as-of proxy (same helper as smoking / alcohol).
            from clinosim.modules.output._fhir_smoking_alcohol import _sdoh_effective_datetime
            eff = _sdoh_effective_datetime(ctx)
            if eff:
                occ_obs["effectiveDateTime"] = eff
            return [occ_obs]
    return []



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
    # CO-7 (session 42 cycle 3): propagate encounter_type for MR.intent
    # inference. The primary encounter type is a reliable proxy when
    # CIF Order.clinical_intent is not populated.
    encounters = ctx.record.get("encounters", []) or []
    primary_enc_type = encounters[0].get("encounter_type", "") if encounters else ""
    for order in ctx.record.get("orders", []):
        if order.get("order_type") == "medication":
            if not (order.get("display_name") or "").strip():
                continue  # skip blank drug names (CIF data quality)
            out.append(_build_medication_request(
                order, ctx.patient_id, ctx.country, ctx.primary_enc_id, ctx.primary_dx_code,
                encounter_type=primary_enc_type,
            ))
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
    out = [
        _build_procedure(proc, ctx.patient_id, i, ctx.country)
        for i, proc in enumerate(ctx.record.get("procedures", []))
    ]
    # RM-6c (session 42): emit Procedure resources from PROCEDURE-type Orders
    # too. These are procedure/device items (compression device, splint, etc.)
    # that used to leak through the MedicationRequest path — RM-6a/b routed
    # them here at CIF creation. Emit a light-weight Procedure per Order.
    proc_seq = len(out) + 1
    for order in ctx.record.get("orders", []) or []:
        ot = order.get("order_type", "") if isinstance(order, dict) else getattr(order, "order_type", "")
        # OrderType enum stringifies to its value
        if str(ot) not in ("procedure", "OrderType.PROCEDURE"):
            continue
        display = order.get("display_name", "") if isinstance(order, dict) else getattr(order, "display_name", "")
        enc_id = order.get("encounter_id", "") if isinstance(order, dict) else getattr(order, "encounter_id", "")
        order_id = order.get("order_id", "") if isinstance(order, dict) else getattr(order, "order_id", "")
        ordered_by = order.get("ordered_by", "") if isinstance(order, dict) else getattr(order, "ordered_by", "")
        ordered_dt = order.get("ordered_datetime", "") if isinstance(order, dict) else getattr(order, "ordered_datetime", "")
        _lang = "ja" if str(ctx.country).upper() == "JP" else "en"
        _profile = {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Procedure"]}} \
            if str(ctx.country).upper() == "JP" else {}
        procedure_res: dict = {
            "resourceType": "Procedure",
            "id": f"proc-order-{order_id}" if order_id else f"proc-order-{ctx.patient_id}-{proc_seq:04d}",
            **_profile,
            "status": "completed",
            "code": {"text": display} if display else {"text": "Procedure"},
            "subject": {"reference": f"Patient/{ctx.patient_id}"},
        }
        if enc_id:
            procedure_res["encounter"] = {"reference": f"Encounter/{enc_id}"}
        if ordered_dt:
            procedure_res["performedDateTime"] = str(ordered_dt)
        if ordered_by:
            procedure_res["performer"] = [{"actor": {"reference": f"Practitioner/{ordered_by}"}}]
        out.append(procedure_res)
        proc_seq += 1
    return out


def _bb_practitioners(ctx: BundleContext) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()

    def add(staff_id: str) -> None:
        if not staff_id or staff_id in seen:
            return
        seen.add(staff_id)
        out.append(_build_practitioner(staff_id, ctx.roster_map, country=ctx.country))
        role = _build_practitioner_role(staff_id, ctx.roster_map, country=ctx.country)
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
    # RM-3 (session 42): Immunization.performer.actor references (nurse admin).
    for imm in ctx.record.get("immunizations", []) or []:
        add(imm.get("administered_by", "") if isinstance(imm, dict)
            else getattr(imm, "administered_by", ""))
    # RM-1 (session 42): nursing survey Observations use primary_nurse_id;
    # ensure the nurse is emitted even when not the primary_nurse of encounter.
    for enc in ctx.record.get("encounters", []) or []:
        add(enc.get("primary_nurse_id", "") if isinstance(enc, dict)
            else getattr(enc, "primary_nurse_id", ""))
    # C2-09 (session 42 cycle 2): also emit every pharmacist in the roster so
    # CareTeam.participant refs to `Practitioner/PH-*` (C1-15 fix) resolve.
    # Pharmacists are assigned deterministically by encounter-id hash in
    # _fhir_care_team.py, so any pharmacist in the roster might be referenced.
    for sid, staff in (ctx.roster_map or {}).items():
        if (staff.get("role", "") or "") == "pharmacist":
            add(sid)
    return out


# FHIR-standard antibiotic susceptibility interpretation labels
# (v3-ObservationInterpretation; standard 3-value enum, localized for display only).


# --- Nursing flowsheet Observations (NEWS2 / GCS / Braden / Morse / ADL / I&O) ---


# Registry: emission order == list order. New Base/Module resources append a builder
# here (or via register_bundle_builder) instead of editing _build_bundle (AD-56).
_BUNDLE_BUILDERS: list[Callable[[BundleContext], list[dict]]] = [
    _bb_patient,
    _bb_coverage,
    _bb_encounters,
    _bb_care_teams,            # α-min-2 Task 11: 1 CareTeam per encounter (attending + nurse)
    _bb_conditions,
    _bb_allergy_intolerances,  # Task 9 / Task 15: 8-field SNOMED-coded schema (sole emit path)
    _bb_clinical_impressions,  # Task 9: ClinicalImpression (daily working diagnosis)
    _bb_occupation,
    _bb_service_requests,
    _bb_endpoints,           # Imaging: emit after SR, before ImagingStudy (reference resolve order)
    _bb_imaging_studies,     # Imaging: emit after Endpoint (endpoint[] ref resolve)
    _bb_labs,
    _bb_vitals,
    _bb_microbiology,
    _bb_diagnostic_reports,
    _bb_medication_requests,
    _bb_medication_admins,
    _bb_procedures,
    _bb_practitioners,
    _build_nursing_observations,
    _build_immunizations,
    _build_family_history,
    _build_code_status,
    _build_smoking_status,
    _build_alcohol_use,
    _build_care_level,
    _build_device,
    _build_device_use,
    _build_hai_conditions,
    _bb_document_references,   # Task 10: DocumentReference from record.documents (free_text, §2.2)
    _bb_compositions,          # Task 9: Composition (section-structured H&P / Discharge)
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
            # C3-11..18 (session 42 cycle 3): apply JP Core profile URLs at
            # the adapter level so every resource type gains conformance
            # declarations without touching each builder. Coverage / Patient /
            # Encounter / Condition already carry inline profile; the helper is
            # idempotent (skips when meta.profile is already populated).
            if ctx.country == "JP":
                _apply_jp_core_profile(resource)
            entries.append(_entry(resource))

    return {
        "resourceType": "Bundle",
        "id": str(uuid.uuid4()),
        "type": "collection",
        "entry": entries,
    }


_JP_CORE_PROFILES: dict[str, str] = {
    # Resources with a canonical JP Core profile URL (JPFHIR core 1.1+).
    # Verified via https://jpfhir.jp/fhir/core/
    "Patient": "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Patient",
    "Encounter": "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Encounter",
    "Condition": "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Condition",
    "Coverage": "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Coverage",
    "Observation": "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common",
    "MedicationRequest": "http://jpfhir.jp/fhir/core/StructureDefinition/JP_MedicationRequest",
    "MedicationAdministration": "http://jpfhir.jp/fhir/core/StructureDefinition/JP_MedicationAdministration",
    "AllergyIntolerance": "http://jpfhir.jp/fhir/core/StructureDefinition/JP_AllergyIntolerance",
    "Immunization": "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Immunization",
    "Practitioner": "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Practitioner",
    "PractitionerRole": "http://jpfhir.jp/fhir/core/StructureDefinition/JP_PractitionerRole",
    "Organization": "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Organization",
    "DiagnosticReport": "http://jpfhir.jp/fhir/core/StructureDefinition/JP_DiagnosticReport_Common",
    # RM-6c (session 42): Procedure profile so RECORD-based and ORDER-based
    # Procedure emissions both carry JP Core conformance.
    "Procedure": "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Procedure",
}


def _apply_jp_core_profile(resource: dict) -> None:
    """Attach the JP Core profile URL for the resource's type when absent.

    C3-11..18 (session 42 cycle 3): idempotent — leaves existing meta.profile
    untouched when a builder has already set one. Adds `meta.profile[]` with
    the JP Core StructureDefinition URL when the resourceType is registered.
    """
    rt = resource.get("resourceType", "")
    profile = _JP_CORE_PROFILES.get(rt)
    if not profile:
        return
    meta = resource.setdefault("meta", {})
    profs = meta.setdefault("profile", [])
    if profile not in profs:
        profs.append(profile)


# ============================================================
# Resource builders
# ============================================================


# Clinical abbreviations / short names for common conditions.
# Keyed by ICD base code (before "."), with per-language short forms.
# coding[].display keeps the official ICD name; code.text uses these.


# JIS X 0401 prefecture codes

# US state abbreviation to FIPS code (common ones)


# SNOMED specialty codes


