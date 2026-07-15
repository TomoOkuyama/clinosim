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

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules.output._fhir_allergy_intolerance import (  # noqa: F401
    _bb_allergy_intolerances,
)
from clinosim.modules.output._fhir_care_level import _build_care_level  # noqa: F401
from clinosim.modules.output._fhir_care_team import (  # noqa: F401
    _bb_care_teams,
)
from clinosim.modules.output._fhir_clinical_impression import (  # noqa: F401
    _bb_clinical_impressions,
)
from clinosim.modules.output._fhir_code_status import _build_code_status  # noqa: F401

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
from clinosim.modules.output._fhir_composition import (  # noqa: F401
    _bb_compositions,
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
from clinosim.modules.output._fhir_document_reference_checkup import (  # noqa: F401
    _bb_document_references_checkup,
)
from clinosim.modules.output._fhir_documents import (  # noqa: F401
    _bb_document_references,
)
from clinosim.modules.output._fhir_encounter import (  # noqa: F401
    _build_encounter,
    _compute_encounter_length,
)
from clinosim.modules.output._fhir_endpoint import (  # noqa: F401
    _bb_endpoints,
)
from clinosim.modules.output._fhir_facility import _build_facility_bundle  # noqa: F401
from clinosim.modules.output._fhir_family_history import _build_family_history  # noqa: F401
from clinosim.modules.output._fhir_hai import _build_hai_conditions  # noqa: F401
from clinosim.modules.output._fhir_imaging_study import (  # noqa: F401
    _bb_imaging_studies,
)
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
from clinosim.modules.output._fhir_smoking_alcohol import (  # noqa: F401
    _build_alcohol_use,
    _build_smoking_status,
)
from clinosim.modules.output.cif_reader import CIFReader


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
        # FHIR resources, write each line. Patient-scoped resources
        # (chronic problem-list-item Condition, Coverage, AllergyIntolerance,
        # FamilyMemberHistory, Immunization) use patient-scoped IDs so the
        # `write()` helper's `written_ids` dedup keeps them at one per patient
        # (root-cause fix for cycle 3 RM-7 problem-list-item excess = per-
        # encounter re-emission with encounter-scoped IDs, C4-02 session 43).
        for record in reader.iter_patients():
            bundle = _build_bundle(record, country, roster_map, hospital_config)
            for entry in bundle.get("entry", []):
                write(entry["resource"])

        # Manifest (FHIR Bulk Data spec)
        manifest = {
            "transactionTime": datetime.now().isoformat(),
            "request": f"clinosim generate (country={country})",
            "requiresAccessToken": False,
            "output": [{"type": rt, "url": f"{rt}.ndjson"} for rt in sorted(writers.keys())],
            "error": [],
        }
        with open(os.path.join(output_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
    finally:
        # F2 (session 49): close writers, then rewrite each NDJSON file with
        # its resources sorted by id ascending. Row order is otherwise
        # cursor-dependent (patient_records iteration order), so a line diff
        # between two snapshots (cursor A / cursor B) would surface spurious
        # "line moved" noise. Sorting by id makes the diff reflect only
        # genuine new / changed / removed resources.
        for w in writers.values():
            w.close()
        for rt in writers:
            path = os.path.join(output_dir, f"{rt}.ndjson")
            _sort_ndjson_by_id_inplace(path)


def _sort_ndjson_by_id_inplace(path: str) -> None:
    """Rewrite an NDJSON file in place with lines sorted by resource id ascending.

    F2 (session 49): sorting removes cursor-dependent (patient_records
    iteration order) row ordering so that a line diff between two snapshots
    surfaces only genuine new / changed / removed resources, not spurious
    "line moved" noise.

    Reads the whole file into memory, so RAM usage scales with file size —
    at p=10k total NDJSON output is ~4.7GB, with the largest single file
    (Observation.ndjson) in the multi-GB range. This is acceptable for
    Phase A; a future JP p=500k scale may need to replace this with an
    external merge sort, but in-memory sort is sufficient for now.
    """
    with open(path, encoding="utf-8") as f:
        lines = [line for line in f.read().splitlines() if line.strip()]
    lines.sort(key=lambda line: json.loads(line).get("id", ""))
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


# --- Resource builders: (ctx) -> list[resource]. Order here == emission order. ---


def _bb_patient(ctx: BundleContext) -> list[dict]:
    return [_build_patient(ctx.patient_data, ctx.country)]


def _bb_coverage(ctx: BundleContext) -> list[dict]:
    return _build_coverage_resources(ctx.patient_data, ctx.country)


def _bb_encounters(ctx: BundleContext) -> list[dict]:
    # C5-22 (session 43): record-level fields propagated to Encounter builder
    # so classHistory (ward→ICU transition) + statusHistory (planned→in-progress→finished)
    # can be emitted.
    _record = ctx.record
    _icu_day = (
        _record.get("icu_transferred_day", -1)
        if isinstance(_record, dict)
        else getattr(_record, "icu_transferred_day", -1)
    )
    _deceased = _record.get("deceased", False) if isinstance(_record, dict) else getattr(_record, "deceased", False)
    # C5-12 (session 43 history chain): extract chronic condition codes
    # from record.patient.chronic_conditions for secondary diagnosis emit.
    _chronic_codes: list[str] = []
    _patient_dict = ctx.patient_data or {}
    for _c in _patient_dict.get("chronic_conditions", []) or []:
        if isinstance(_c, str):
            _chronic_codes.append(_c)
        elif isinstance(_c, dict):
            _chronic_codes.append(_c.get("code", ""))
        else:
            _chronic_codes.append(getattr(_c, "code", ""))
    # CY7-05 (structural fix, 2026-07-11): ED→IMP partOf linkage. The
    # inpatient simulator sets `admit_source_encounter_id` on IMP encounters
    # admitted from ED (admit_source == "emd"). At emit time we ALSO
    # synthesize a lightweight ED Encounter FHIR resource for that ID so
    # the partOf reference resolves. The synthesis is FHIR-emit only —
    # the ED encounter does NOT appear in CIF nor generate additional
    # doc stubs / orders — avoiding downstream contract breakage.
    _resources = []
    for enc in ctx.record.get("encounters", []) or []:
        _partof_id = (
            enc.get("admit_source_encounter_id", "")
            if isinstance(enc, dict)
            else getattr(enc, "admit_source_encounter_id", "")
        )  # noqa: E501
        _resource = _build_encounter(
            enc,
            ctx.patient_id,
            ctx.is_readmission,
            ctx.prior_encounter_id,
            primary_dx_code=ctx.primary_dx_code,
            country=ctx.country,
            admit_dx_code=ctx.admit_dx_code,
            admit_dx_system=ctx.admit_dx_system,
            icu_transferred_day=_icu_day,
            deceased=_deceased,
            chronic_condition_codes=_chronic_codes,
            record_orders=ctx.record.get("orders", []),
        )
        # Only add ED→IMP partOf if _build_encounter didn't already set one
        # (readmission takes precedence — same field, different semantics).
        if _partof_id and "partOf" not in _resource:
            _resource["partOf"] = {"reference": f"Encounter/{_partof_id}"}
            # Synthesize the ED Encounter FHIR resource (minimal but valid).
            _adm_dt = (
                enc.get("admission_datetime", "") if isinstance(enc, dict) else getattr(enc, "admission_datetime", "")
            )  # noqa: E501
            _adm_str = str(_adm_dt) if _adm_dt else ""
            # ED stay ~3.5 hours before IMP admission — clinical-realistic.
            _ed_end_str = _adm_str
            _ed_start_str = ""
            try:
                from datetime import datetime as _dt
                from datetime import timedelta as _td

                if _adm_str:
                    _dt0 = _dt.fromisoformat(_adm_str.replace("Z", "+00:00")) if "T" in _adm_str else None
                    if _dt0:
                        _ed_start_str = (_dt0 - _td(hours=3, minutes=30)).isoformat()
            except (ValueError, TypeError):
                pass
            _att = (
                enc.get("attending_physician_id", "")
                if isinstance(enc, dict)
                else getattr(enc, "attending_physician_id", "")
            )  # noqa: E501
            _chief = enc.get("chief_complaint", "") if isinstance(enc, dict) else getattr(enc, "chief_complaint", "")
            _ed_resource: dict = {
                "resourceType": "Encounter",
                "id": _partof_id,
                "meta": _resource.get("meta", {}),
                "status": "finished",
                "class": {
                    "system": get_system_uri("hl7-v3-actcode"),
                    "code": "EMER",
                    "display": "救急外来" if str(ctx.country).upper() == "JP" else "Emergency",
                },
                "subject": {"reference": f"Patient/{ctx.patient_id}"},
            }
            _period: dict = {}
            if _ed_start_str:
                _period["start"] = _ed_start_str
            if _ed_end_str:
                _period["end"] = _ed_end_str
            if _period:
                _ed_resource["period"] = _period
            # Session 45: emit Encounter.length on the synthesized ED encounter
            # (CY7-05 synthesis previously skipped this — verification found
            # 1093/1144 length-missing Encounter were EMER-with-partOf).
            _ed_length = _compute_encounter_length(_ed_start_str, _ed_end_str)
            if _ed_length is not None:
                _ed_resource["length"] = _ed_length
            if _att:
                _ed_resource["participant"] = [
                    {
                        "individual": {"reference": f"Practitioner/{_att}"},
                    }
                ]
            if _chief:
                _ed_resource["reasonCode"] = [{"text": _chief}]
            # cycle 8 cross-seed verify fix (CY7-06 regression): ED synth
            # encounter に priority を emit(実運用では ED は emergency = "EM"、
            # ここでは実 IMP と同じ priority CodeableConcept 形状で "EM" 固定)。
            _ed_resource["priority"] = {
                "coding": [
                    {
                        "system": get_system_uri("hl7-v3-actpriority"),
                        "code": "EM",
                        "display": "緊急" if str(ctx.country).upper() == "JP" else "emergency",
                    }
                ],
            }
            _ed_resource["hospitalization"] = {
                "admitSource": {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-admit-source"),
                            "code": "outp",
                            "display": "外来より" if str(ctx.country).upper() == "JP" else "From outpatient",
                        }
                    ],
                },
                "dischargeDisposition": {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-discharge-disposition"),
                            "code": "hosp",
                            "display": "入院となる" if str(ctx.country).upper() == "JP" else "Admitted to hospital",
                        }
                    ],
                },
            }
            # CY8-04 (session 48 cycle 8): synthesized ED encounter にも
            # serviceProvider を hospital-main で emit。従来 1075 EMER 欠落。
            _ed_resource["serviceProvider"] = {
                "reference": "Organization/hospital-main",
            }
            _resources.append(_ed_resource)
        _resources.append(_resource)
    return _resources


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
            from clinosim.modules.output._fhir_smoking_alcohol import (
                _sdoh_effective_datetime,
                _sdoh_performer_ref,
            )

            eff = _sdoh_effective_datetime(ctx)
            if eff:
                occ_obs["effectiveDateTime"] = eff
            perf = _sdoh_performer_ref(ctx)
            if perf:
                occ_obs["performer"] = [{"reference": perf}]
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
    # C4-22 (session 43 cycle 4): MR.requester fallback to encounter attending
    # (was 3% missing requester). Same pattern as C4-17 for Procedure.performer.
    _attending_by_enc: dict[str, str] = {}
    for _enc in encounters:
        _eid = (_enc.get("encounter_id", "") if isinstance(_enc, dict) else getattr(_enc, "encounter_id", "")) or ""
        _att = (
            _enc.get("attending_physician_id", "")
            if isinstance(_enc, dict)
            else getattr(_enc, "attending_physician_id", "")
        ) or ""
        if _eid and _att:
            _attending_by_enc[_eid] = _att
    # session 49 clinosim_feedback P1-4: JP_MedicationRequest.identifier slice
    # rpNumber + orderInRp を assign。1 encounter = 1 Rp グループとして扱い、
    # encounter 内の medication order 出現順を orderInRp (1-based) にする。
    # 同一 order の MedicationRequest / MedicationAdministration は同じ
    # order_id → order_in_rp map を使うため両者の紐付けが取れる。
    _order_in_rp_by_oid = _build_order_in_rp_map(ctx.record.get("orders", []) or [])
    for order in ctx.record.get("orders", []):
        if order.get("order_type") == "medication":
            if not (order.get("display_name") or "").strip():
                continue  # skip blank drug names (CIF data quality)
            if not order.get("ordered_by"):
                _eid = order.get("encounter_id", "") or ctx.primary_enc_id
                _att = _attending_by_enc.get(_eid, "")
                if _att:
                    order = dict(order)
                    order["ordered_by"] = _att
            _oid = order.get("order_id", "") or ""
            out.append(
                _build_medication_request(
                    order,
                    ctx.patient_id,
                    ctx.country,
                    ctx.primary_enc_id,
                    ctx.primary_dx_code,
                    encounter_type=primary_enc_type,
                    rp_number="1",
                    order_in_rp=str(_order_in_rp_by_oid.get(_oid, 1)),
                )
            )
    return out


def _build_order_in_rp_map(orders: list) -> dict[str, int]:
    """Per-encounter medication order 出現順 → orderInRp 番号(1-based)map を返す。

    JP Core JP_MedicationRequest / JP_MedicationAdministration の
    identifier:orderInRp slice に使う。同一 order_id で MR / MA 双方が
    同じ番号を得るため、両 builder が同 map を再計算しても結果が一致する
    ことを前提にしている(deterministic な iteration 順)。
    """
    result: dict[str, int] = {}
    per_enc: dict[str, int] = {}
    for order in orders:
        if order.get("order_type") != "medication":
            continue
        if not (order.get("display_name") or "").strip():
            continue
        eid = order.get("encounter_id", "") or ""
        per_enc[eid] = per_enc.get(eid, 0) + 1
        oid = order.get("order_id", "") or ""
        if oid:
            result[oid] = per_enc[eid]
    return result


def _bb_medication_admins(ctx: BundleContext) -> list[dict]:
    out: list[dict] = []
    # C5-07 (session 43 history chain): build the set of MedicationRequest ids
    # that WILL be emitted so we can drop MAR.request references that would
    # otherwise dangle (was 4 orphan refs in baseline — CIF corner case where
    # a supportive Order is created but not persisted into record.orders while
    # the corresponding MAR is). Reference integrity > preserving a broken link.
    _mr_ids: set[str] = set()
    _primary_enc_id = ctx.primary_enc_id
    # CY6-04 / CY6-25 (Chain-6, 2026-07-11): build order_id → order_code map so
    # MAR builder can inherit the parent Order's authoritative YJ / RxNorm code
    # (previously the MAR builder re-derived code via English code_mapping,
    # missing JP-text drug names like "エルカトニン" / "乳酸リンゲル液" that
    # bypass the English keys). Session 44 CO-8 fixed the MR-side; MAR-side
    # requires this join because MAR records don't carry code_yj directly.
    _order_code_by_id: dict[str, str] = {}
    for order in ctx.record.get("orders", []) or []:
        if order.get("order_type") == "medication":
            if not (order.get("display_name") or "").strip():
                continue
            _base_oid = order.get("order_id", "") or ""
            _enc_ref_id = order.get("encounter_id", "") or _primary_enc_id
            _mr_id = f"{_enc_ref_id}-{_base_oid}" if _enc_ref_id else _base_oid
            _mr_ids.add(_mr_id)
            _oc = order.get("order_code", "") or ""
            if _base_oid and _oc:
                _order_code_by_id[_base_oid] = _oc
    # session 49 clinosim_feedback P1-4: JP_MedicationAdministration.identifier
    # slice orderInRp。同 order_id を参照する MedicationRequest と同じ
    # 番号にするため、`_build_order_in_rp_map` の同一ロジックで再構築。
    _order_in_rp_by_oid = _build_order_in_rp_map(ctx.record.get("orders", []) or [])
    for i, mar in enumerate(ctx.record.get("medication_administrations", [])):
        if not (mar.get("drug_name") or "").strip():
            continue
        # Inject the parent Order's code_yj so MAR emits authoritative coding.
        _oid = mar.get("order_id", "") or ""
        _parent_code = _order_code_by_id.get(_oid, "")
        if _parent_code and not mar.get("code_yj"):
            mar = dict(mar)
            mar["code_yj"] = _parent_code
        _resource = _build_medication_admin(
            mar,
            ctx.patient_id,
            i,
            ctx.country,
            encounter_id=ctx.primary_enc_id,
            primary_dx_code=ctx.primary_dx_code,
            rp_number="1",
            order_in_rp=str(_order_in_rp_by_oid.get(_oid, 1)),
        )
        _req = _resource.get("request") if isinstance(_resource, dict) else None
        if _req and isinstance(_req, dict):
            _ref = _req.get("reference", "")
            if _ref.startswith("MedicationRequest/"):
                _target = _ref[len("MedicationRequest/") :]
                if _target not in _mr_ids:
                    _resource.pop("request", None)  # drop the dangling ref
        out.append(_resource)
    return out


def _bb_procedures(ctx: BundleContext) -> list[dict]:
    # C4-17 (session 43 cycle 4): Procedure.performer fallback to encounter
    # attending physician when the CIF procedure record has no
    # primary_surgeon_id (was 59% missing performer in baseline). Look up by
    # encounter_id; falls through to _build_procedure's own no-performer path
    # if no attending is available.
    _attending_by_enc: dict[str, str] = {}
    for _enc in ctx.record.get("encounters", []) or []:
        _eid = (_enc.get("encounter_id", "") if isinstance(_enc, dict) else getattr(_enc, "encounter_id", "")) or ""
        _att = (
            _enc.get("attending_physician_id", "")
            if isinstance(_enc, dict)
            else getattr(_enc, "attending_physician_id", "")
        ) or ""
        if _eid and _att:
            _attending_by_enc[_eid] = _att
    _procs = ctx.record.get("procedures", []) or []
    _enriched = []
    for proc in _procs:
        if not proc.get("primary_surgeon_id"):
            _eid = proc.get("encounter_id", "")
            _att = _attending_by_enc.get(_eid, "")
            if _att:
                proc = dict(proc)
                proc["primary_surgeon_id"] = _att
        _enriched.append(proc)
    out = [_build_procedure(proc, ctx.patient_id, i, ctx.country) for i, proc in enumerate(_enriched)]
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
        ordered_dt = (
            order.get("ordered_datetime", "") if isinstance(order, dict) else getattr(order, "ordered_datetime", "")
        )  # noqa: E501
        _lang = "ja" if str(ctx.country).upper() == "JP" else "en"
        _profile = (
            {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Procedure"]}}
            if str(ctx.country).upper() == "JP"
            else {}
        )
        # C4-03/18 (session 43 cycle 4): PROCEDURE-Order path lacked
        # Procedure.category. Bind SNOMED 277132007 (Therapeutic procedure,
        # SNOMED CT) — these are treatment-side procedures (splint / bandage /
        # wound care / etc.) routed to PROCEDURE by emergency.py's _procedure_kw
        # filter. category is a Procedure.category coding, well-known SNOMED
        # concept from https://build.fhir.org/valueset-procedure-category.html.
        _cat_lang = "ja" if str(ctx.country).upper() == "JP" else "en"
        procedure_res: dict = {
            "resourceType": "Procedure",
            "id": f"proc-order-{order_id}" if order_id else f"proc-order-{ctx.patient_id}-{proc_seq:04d}",
            **_profile,
            "status": "completed",
            "category": {
                "coding": [
                    {
                        "system": get_system_uri("snomed-ct"),
                        "code": "277132007",
                        "display": code_lookup("snomed-ct", "277132007", _cat_lang),
                    }
                ],
            },
            "code": {"text": display} if display else {"text": "Procedure"},
            "subject": {"reference": f"Patient/{ctx.patient_id}"},
        }
        if enc_id:
            procedure_res["encounter"] = {"reference": f"Encounter/{enc_id}"}
            # CY7-17 (Chain-7): reasonReference to encounter primary Condition.
            procedure_res["reasonReference"] = [{"reference": f"Condition/cond-{enc_id}-primary"}]
        if ordered_dt:
            procedure_res["performedDateTime"] = str(ordered_dt)
        if ordered_by:
            procedure_res["performer"] = [{"actor": {"reference": f"Practitioner/{ordered_by}"}}]
        # CY7-17 (Chain-7): text-only reasonCode fallback for treatment-side
        # Procedures (splint/bandage/wound-care/etc.) — same rationale as
        # _fhir_procedures._build_procedure text-only fallback.
        procedure_res["reasonCode"] = [
            {
                "text": "入院時診断に基づく処置"
                if str(ctx.country).upper() == "JP"
                else "Procedure indicated by encounter diagnosis",  # noqa: E501
            }
        ]
        # CY7-18 (Chain-7): text-only bodySite fallback for order-derived
        # Procedures — the Order carries display_name but not a SNOMED site
        # code, so text is defensible.
        procedure_res["bodySite"] = [
            {
                "text": "処置部位不明" if str(ctx.country).upper() == "JP" else "Body site not specified",
            }
        ]
        # CY7-19 (Chain-7): outcome default = Successful for completed status.
        procedure_res["outcome"] = {
            "coding": [
                {
                    "system": get_system_uri("snomed-ct"),
                    "code": "385669000",
                    "display": code_lookup("snomed-ct", "385669000", _cat_lang) or "Successful",
                }
            ],
            "text": "成功" if str(ctx.country).upper() == "JP" else "Successful",
        }
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
        add(imm.get("administered_by", "") if isinstance(imm, dict) else getattr(imm, "administered_by", ""))
    # RM-1 (session 42): nursing survey Observations use primary_nurse_id;
    # ensure the nurse is emitted even when not the primary_nurse of encounter.
    for enc in ctx.record.get("encounters", []) or []:
        add(enc.get("primary_nurse_id", "") if isinstance(enc, dict) else getattr(enc, "primary_nurse_id", ""))
    # C2-09 (session 42 cycle 2): also emit every pharmacist in the roster so
    # CareTeam.participant refs to `Practitioner/PH-*` (C1-15 fix) resolve.
    # Pharmacists are assigned deterministically by encounter-id hash in
    # _fhir_care_team.py, so any pharmacist in the roster might be referenced.
    for sid, staff in (ctx.roster_map or {}).items():
        if (staff.get("role", "") or "") == "pharmacist":
            add(sid)
    # C5-25 (Chain 3): allied-health staff (PT/OT/ST/MSW/RD) are populated by
    # generate_roster but not yet referenced by CareTeam (2-name scope
    # invariant AD-64 until β-JP-1 multi-disciplinary expansion). Emit them
    # here so the hospital's Practitioner registry is complete — matches JP
    # EHR practice where staff master data lists all licensed clinicians
    # regardless of encounter participation.
    _allied_roles = {
        "physical_therapist",
        "occupational_therapist",
        "speech_therapist",
        "medical_social_worker",
        "dietitian",
    }
    for sid, staff in (ctx.roster_map or {}).items():
        if (staff.get("role", "") or "") in _allied_roles:
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
    _bb_care_teams,  # α-min-2 Task 11: 1 CareTeam per encounter (attending + nurse)
    _bb_conditions,
    _bb_allergy_intolerances,  # Task 9 / Task 15: 8-field SNOMED-coded schema (sole emit path)
    _bb_clinical_impressions,  # Task 9: ClinicalImpression (daily working diagnosis)
    _bb_occupation,
    _bb_service_requests,
    _bb_endpoints,  # Imaging: emit after SR, before ImagingStudy (reference resolve order)
    _bb_imaging_studies,  # Imaging: emit after Endpoint (endpoint[] ref resolve)
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
    _bb_document_references,  # Task 10: DocumentReference from record.documents (free_text, §2.2)
    _bb_compositions,  # Task 9: Composition (section-structured H&P / Discharge)
    _bb_document_references_checkup,  # P2-13 PR3 sub-PR-E (session 48): DocumentReference wrapper for HEALTH_CHECKUP_REPORT  # noqa: E501
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
    record: dict,
    country: str,
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
    # Session 45 seed=400 verification finding: record.deceased was set by
    # `_evaluate_mortality` in the inpatient simulator (74 expired IMP
    # encounters at seed=400 v2) but never propagated to `patient_data`, so
    # `_build_patient` always emitted `deceasedBoolean=False`. Copy the flag
    # + death timestamp into patient_data so the FHIR Patient carries a
    # `deceasedDateTime` matching the Encounter.dischargeDisposition="expired".
    _record_deceased = record.get("deceased", False) if isinstance(record, dict) else getattr(record, "deceased", False)
    if _record_deceased and not patient_data.get("date_of_death") and not patient_data.get("dod"):
        _dod = None
        for _enc in encounters:
            _dis = (
                _enc.get("discharge_datetime") if isinstance(_enc, dict) else getattr(_enc, "discharge_datetime", None)
            )
            if _dis:
                _dod = _dis
                break
        if _dod:
            patient_data = dict(patient_data)
            patient_data["date_of_death"] = str(_dod)
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
        # CY7-05 (structural fix): CIFPatientRecord contract — primary
        # (IMP) encounter is always at encounters[0]; synthesized ED
        # encounter (when present) is appended at [1].
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
                _apply_jp_clins_profile(resource)
                # session 49 clinosim_feedback P1-4: JP Core は
                # Observation.category:first slice を要求。既存 HL7 slice の
                # code を保持しつつ、JP CodeSystem URL の first slice を
                # prepend する。builders 個別修正回避のため single seam で対応。
                _inject_jp_observation_category_first(resource)
            # session 48 feedback FB-F1: 全 emit resource の dateTime / instant
            # field を single seam で TZ 付与に正規化(builders 個別修正回避)。
            _normalize_dt_fields(resource)
            entries.append(_entry(resource))

    return {
        "resourceType": "Bundle",
        "id": str(uuid.uuid4()),
        "type": "collection",
        "entry": entries,
    }


# session 48 deferred cleanup (g): shape unification.
# JP Core registry uses `dict[str, list[str]]` (was `dict[str, str]`) so its
# shape matches `_JP_CLINS_PROFILES` below. Future JP Core release with
# multiple sibling profiles per resource type (e.g. JP_Observation_Common
# + JP_Observation_Vital) can be listed here without an accessor change.
_JP_CORE_PROFILES: dict[str, list[str]] = {
    # Resources with a canonical JP Core profile URL (JPFHIR core 1.1+).
    # Verified via https://jpfhir.jp/fhir/core/
    "Patient": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Patient"],
    "Encounter": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Encounter"],
    "Condition": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Condition"],
    "Coverage": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Coverage"],
    "Observation": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common"],
    "MedicationRequest": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_MedicationRequest"],
    "MedicationAdministration": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_MedicationAdministration"],
    "AllergyIntolerance": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_AllergyIntolerance"],
    "Immunization": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Immunization"],
    "Practitioner": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Practitioner"],
    "PractitionerRole": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_PractitionerRole"],
    "Organization": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Organization"],
    "DiagnosticReport": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_DiagnosticReport_Common"],
    # RM-6c (session 42): Procedure profile so RECORD-based and ORDER-based
    # Procedure emissions both carry JP Core conformance.
    "Procedure": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Procedure"],
}


# session 48 feedback FB-F1: 全 emit resource で dateTime / instant field を
# TZ 付与に正規化する post-emit normalization pass。builders 個別修正の代替。
# 対象 field は FHIR R4 で dateTime / instant 型を持つ known-name 一覧。
_DATETIME_FIELDS = frozenset(
    (
        # top-level dateTime
        "authoredOn",
        "effectiveDateTime",
        "performedDateTime",
        "date",
        "started",
        "receivedTime",
        "recordedDate",
        "onsetDateTime",
        "occurrenceDateTime",
        "abatementDateTime",
        "assertedDate",
        "authored",
        "assertedDateTime",
        "collectedDateTime",  # Specimen.collection.collectedDateTime (nested)
        "time",  # attester.time / Provenance.recorded など
        # instant type
        "issued",
        "recorded",
        "createdOn",
        "sent",
        "lastUpdated",
    )
)
_PERIOD_FIELDS = frozenset(("start", "end"))
# instant 型 field(秒精度+TZ 必須)
_INSTANT_FIELDS = frozenset(("issued",))


def _normalize_dt(v, want_instant: bool = False):
    """string dateTime → +09:00 付与。TZ ある場合 passthrough。"""
    if not isinstance(v, str) or not v:
        return v
    # date-only YYYY-MM-DD は通す(FHIR date 型として valid)
    if len(v) == 10 and v[4] == "-" and v[7] == "-":
        if want_instant:
            # instant 要求 → 秒 + TZ 補完
            return f"{v}T00:00:00+09:00"
        return v
    if "T" not in v:
        return v  # 空 or 非 datetime 形式は不変
    # 既に TZ suffix ある?
    if v.endswith("Z") or (len(v) >= 6 and v[-6] in "+-" and v[-3] == ":"):
        return v
    # 秒欠落補完(instant 用)
    if want_instant and v.count(":") == 1:
        v = v + ":00"
    return v + "+09:00"


# session 49 clinosim_feedback P1-4: JP Core Observation.category:first slice。
# JP_Observation_Common (v1.2.0) StructureDefinition の
# `Observation.category:first.coding.system` が
# `http://jpfhir.jp/fhir/core/CodeSystem/JP_SimpleObservationCategory_CS` に
# 固定されている(iris4h-ai jp_core/package/StructureDefinition-jp-
# observation-common.json の fixedUri で確認)。実 example の Observation
# は同 CodeSystem の code(laboratory / vital-signs / imaging / procedure /
# social-history / exam / body-measurement)を使用しており、HL7 標準
# observation-category と code 語彙が概ね一致するため、既存 HL7 slice の
# code をそのまま再利用して URI だけを JP CodeSystem に切替える。既存
# HL7 slice は互換用に維持し、JP-first-slice を prepend する。
# ★ session 50 adv-1 code review 検出: 初版で
#   `http://jpfhir.jp/fhir/observation-category`(推測)を使ってしまい HAPI
#   validator が silent-no-op のまま 100% miss を継続。実 spec の fixedUri
#   に修正済み。
_JP_OBSERVATION_CATEGORY_SYSTEM = "http://jpfhir.jp/fhir/core/CodeSystem/JP_SimpleObservationCategory_CS"


def _inject_jp_observation_category_first(resource: dict) -> None:
    """Prepend JP Core observation-category first slice for JP output。

    JP only(caller が country=JP のみで呼ぶ前提)。既に JP-first-slice が
    ある resource は idempotent。code は既存 HL7 slice のものを再利用する
    (JP_SimpleObservationCategory_CS は HL7 observation-category と code
    語彙が概ね一致:laboratory / vital-signs / imaging / procedure /
    social-history / exam / body-measurement)。
    """
    if resource.get("resourceType") != "Observation":
        return
    cats = resource.get("category")
    if not isinstance(cats, list) or not cats:
        return
    # idempotent: 既に JP-first-slice がある場合 skip
    for cat in cats:
        for cod in cat.get("coding", []) if isinstance(cat.get("coding"), list) else []:
            if cod.get("system") == _JP_OBSERVATION_CATEGORY_SYSTEM:
                return
    # 現行 first slice の code を抽出(HL7 observation-category からのみ拾う)
    first_hl7 = cats[0]
    hl7_code = None
    for cod in first_hl7.get("coding", []) if isinstance(first_hl7.get("coding"), list) else []:
        sys_val = cod.get("system") or ""
        if "observation-category" in sys_val:
            hl7_code = cod.get("code")
            break
    if not hl7_code:
        return
    jp_first = {
        "coding": [
            {
                "system": _JP_OBSERVATION_CATEGORY_SYSTEM,
                "code": hl7_code,
            }
        ]
    }
    resource["category"] = [jp_first] + cats


def _normalize_dt_fields(resource) -> None:
    """resource dict を再帰 walk、_DATETIME_FIELDS / _INSTANT_FIELDS / Period を正規化。"""
    if isinstance(resource, dict):
        for k, v in list(resource.items()):
            if k in _INSTANT_FIELDS and isinstance(v, str):
                resource[k] = _normalize_dt(v, want_instant=True)
            elif k in _DATETIME_FIELDS and isinstance(v, str):
                resource[k] = _normalize_dt(v)
            elif k in ("period", "validityPeriod", "servicedPeriod") and isinstance(v, dict):
                for pk in _PERIOD_FIELDS:
                    if pk in v:
                        v[pk] = _normalize_dt(v[pk])
                _normalize_dt_fields(v)
            elif isinstance(v, (dict, list)):
                _normalize_dt_fields(v)
    elif isinstance(resource, list):
        for item in resource:
            _normalize_dt_fields(item)


def _apply_jp_core_profile(resource: dict) -> None:
    """Attach the JP Core profile URLs for the resource's type when absent.

    C3-11..18 (session 42 cycle 3): idempotent — leaves existing meta.profile
    untouched when a builder has already set one. Appends any JP Core
    StructureDefinition URL that is not yet in `meta.profile[]`.
    Session 48 cleanup: dict shape unified with `_JP_CLINS_PROFILES` (list-of-URLs).
    """
    rt = resource.get("resourceType", "")
    profiles = _JP_CORE_PROFILES.get(rt)
    if not profiles:
        return
    meta = resource.setdefault("meta", {})
    profs = meta.setdefault("profile", [])
    for profile in profiles:
        if profile not in profs:
            profs.append(profile)


# JP-CLINS eCS profiles (電子カルテ情報共有サービス).
# Applied additively on top of JP Core profiles for country=JP.
# URLs verified against jpfhir.jp/fhir/clins/igv1/artifacts.html (v1.12.0,
# 2026-02-16) on 2026-07-12. Canonical URLs use /fhir/eCS/ path.
#
# JP-CLINS v1.12.0 publishes 5 profiles covering the "6 information items"
# domain: 傷病名 + 感染症 share JP_Condition_eCS; DiagnosticReport is not in
# JP-CLINS scope (lab results emitted only as Observation.LabResult).
_JP_CLINS_PROFILES: dict[str, list[str]] = {
    "Condition": [
        "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Condition_eCS",
    ],
    "AllergyIntolerance": [
        "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_AllergyIntolerance_eCS",
    ],
    "Observation": [
        "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Observation_LabResult_eCS",
    ],
    "MedicationRequest": [
        "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_MedicationRequest_eCS",
    ],
    "Procedure": [
        "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Procedure_eCS",
    ],
}


def _apply_jp_clins_profile(resource: dict) -> None:
    """Attach JP-CLINS eCS profile URLs additively (idempotent).

    Called after `_apply_jp_core_profile`. Preserves existing meta.profile[]
    entries and skips URLs already present. Filter: for Observation, only
    laboratory category resources receive the JP-CLINS profile (vital signs
    stay on the JP Core profile only).
    """
    rt = resource.get("resourceType", "")
    profiles = _JP_CLINS_PROFILES.get(rt)
    if not profiles:
        return
    if rt == "Observation" and not _is_lab_observation(resource):
        return
    meta = resource.setdefault("meta", {})
    profs = meta.setdefault("profile", [])
    for url in profiles:
        if url not in profs:
            profs.append(url)


def _is_lab_observation(resource: dict) -> bool:
    for cat in resource.get("category", []) or []:
        for coding in cat.get("coding", []) or []:
            if coding.get("code") == "laboratory":
                return True
    return False


# ============================================================
# Resource builders
# ============================================================


# Clinical abbreviations / short names for common conditions.
# Keyed by ICD base code (before "."), with per-language short forms.
# coding[].display keeps the official ICD name; code.text uses these.


# JIS X 0401 prefecture codes

# US state abbreviation to FIPS code (common ones)


# SNOMED specialty codes
