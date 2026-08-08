"""Inline bundle builders for `fhir_r4_adapter.py`.

Split from `clinosim/modules/output/fhir_r4_adapter.py` (session 82) — see PR L.

Each `_bb_*` function takes a `BundleContext` and returns a list of FHIR
resource dicts. They complement the per-theme `_fhir_*.py` builders (which
are imported into `fhir_r4_adapter.py` alongside these).

Contains:
  - _bb_patient
  - _bb_coverage
  - _bb_encounters
  - _bb_conditions
  - _bb_occupation
  - _bb_vitals
  - _bb_medication_requests
  - _bb_discharge_medication_requests
  - _bb_medication_admins (+ helper build_order_in_rp_map)
  - _bb_procedures
  - _bb_practitioners

The full adapter header (imports + module constants) is inlined below so
every symbol these builders reference is visible without a circular import
back into `fhir_r4_adapter.py`.
"""

from __future__ import annotations

import re

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key, is_jp
from clinosim.modules.output.fhir_r4.conditions.allergy_intolerance import (  # noqa: F401
    _bb_allergy_intolerances,
)
from clinosim.modules.output.fhir_r4.conditions.clinical_impression import (  # noqa: F401
    _bb_clinical_impressions,
)
from clinosim.modules.output.fhir_r4.conditions.code_status import _bb_code_status  # noqa: F401
from clinosim.modules.output.fhir_r4.conditions.conditions import _build_conditions  # noqa: F401
from clinosim.modules.output.fhir_r4.conditions.hai import _bb_hai_conditions  # noqa: F401
from clinosim.modules.output.fhir_r4.demographics.family_history import _bb_family_history  # noqa: F401
from clinosim.modules.output.fhir_r4.demographics.patient import (  # noqa: F401
    _ORG_TYPE_SYSTEM,
    _SUBSCRIBER_REL_SYSTEM,
    _build_coverage_resources,
    _build_occupation_observation,
    _build_patient,
    _identity_cfg,
    _payer_name_map,
)
from clinosim.modules.output.fhir_r4.demographics.practitioner import (  # noqa: F401
    _build_practitioner,
    _build_practitioner_role,
)
from clinosim.modules.output.fhir_r4.demographics.smoking_alcohol import (  # noqa: F401
    _bb_alcohol_use,
    _bb_smoking_status,
)
from clinosim.modules.output.fhir_r4.documents.composition import (  # noqa: F401
    _bb_compositions,
)
from clinosim.modules.output.fhir_r4.documents.document_reference_checkup import (  # noqa: F401
    _bb_document_references_checkup,
)
from clinosim.modules.output.fhir_r4.documents.documents import (  # noqa: F401
    _bb_document_references,
)
from clinosim.modules.output.fhir_r4.encounters.care_level import _bb_care_level  # noqa: F401
from clinosim.modules.output.fhir_r4.encounters.care_team import (  # noqa: F401
    _bb_care_teams,
)
from clinosim.modules.output.fhir_r4.encounters.encounter import (  # noqa: F401
    _build_encounter,
    _compute_encounter_length,
)
from clinosim.modules.output.fhir_r4.encounters.endpoint import (  # noqa: F401
    _bb_endpoints,
)
from clinosim.modules.output.fhir_r4.encounters.facility import _build_facility_bundle  # noqa: F401
from clinosim.modules.output.fhir_r4.labs.diagnostic_report import (  # noqa: F401
    _bb_diagnostic_reports,
    build_lab_panel_reports,  # kept for backward compat (tests + external callers)
)
from clinosim.modules.output.fhir_r4.labs.imaging_study import (  # noqa: F401
    _bb_imaging_studies,
)
from clinosim.modules.output.fhir_r4.labs.microbiology import _bb_microbiology  # noqa: F401
from clinosim.modules.output.fhir_r4.labs.observations import (  # noqa: F401
    _bb_labs,
    _build_lab_observation,
    _build_vital_observations,
)
from clinosim.modules.output.fhir_r4.labs.service_request import (  # noqa: F401
    _bb_service_requests,
)

# FA-1 (Phases 1-13) split this adapter's leaf data, shared fragment helpers, and
# per-theme resource builders into sibling _fhir_* modules. The blocks below are
# re-imported here so existing `from ...fhir_r4_adapter import X` call sites keep
# working (facade). They are marked # noqa: F401 because many symbols are now used
# only by the extracted modules (which import them directly) and are re-exported
# purely as a compatibility facade; the # noqa keeps the facade stable as further
# builders move out, without per-symbol import churn each phase.
from clinosim.modules.output.fhir_r4.lib.common import (  # noqa: F401
    BundleContext,
    _parse_dose_for_mar,
    _sha1_b64,
    build_address,
    build_diagnosis_codeable_concept,
    build_dosage_instruction,
    build_reference_range,
    build_telecom,
    entry,
    infer_severity,
    loinc_coding,
    make_participant,
    map_diagnosis_code,
    map_encounter_status,
    map_mar_status,
    micro_coding,
    severity_coding,
    strip_protocol_prefix,
    survey_category,
)
from clinosim.modules.output.fhir_r4.lib.localization import (  # noqa: F401
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
from clinosim.modules.output.fhir_r4.lib.reference_data import (  # noqa: F401
    _ALLERGEN_RXNORM,
    _ENCOUNTER_TYPE_SNOMED_CODE,
    _PREFECTURE_CODE,
    _ROLE_PREFIX_MAP,
    _ROUTE_SNOMED,
    _SEVERITY_SNOMED,
    _SPECIALTY_SNOMED,
)
from clinosim.modules.output.fhir_r4.medications.medications import (  # noqa: F401
    _build_discharge_medication_request,
    _build_medication_admin,
    _build_medication_request,
)
from clinosim.modules.output.fhir_r4.procedures.device import (  # noqa: F401
    _bb_device,
    _bb_device_use,
)
from clinosim.modules.output.fhir_r4.procedures.immunization import _bb_immunizations  # noqa: F401
from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations  # noqa: F401
from clinosim.modules.output.fhir_r4.procedures.procedures import _build_procedure  # noqa: F401

# FHIR R4 `Resource.id` type: `[A-Za-z0-9\-\.]{1,64}`. iris4h-ai P0 finding
# (2026-07-17): 812,606 ids across the export violated this spec — `_` in id
# and >64 char ids were rejected by IRIS FHIR endpoint with HTTP 400. HAPI
# validator is more lenient but the FHIR spec is strict. The regex here is the
# single source of truth for the pattern — every writer path routes ids
# through it, and any non-conforming id logs a warning (fail-soft: the write
# still succeeds so a bug in a single builder does not break the whole export,
# but the log lets the audit CI catch regressions).
_FHIR_ID_PATTERN = re.compile(r"^[A-Za-z0-9\-\.]{1,64}$")


# Synthesised ED encounter (CY7-05) display strings — Issue #546 partial.
# `_fhir_inline_bb.py::_bb_encounters` builds an ED partOf encounter that
# bypasses `_build_encounter_resource` (the canonical builder). The 4
# hardcoded display strings below were inlined as `"救急外来" if is_jp(country)
# else "Emergency"` at 4 sites. Extracted here as a single named table so:
#
#   * A JP-CLINS revision that touches synth-ED display copy is a one-file edit.
#   * `grep _SYNTH_ED_DISPLAYS` surfaces every consumer.
#   * A future full-canonical migration (delegating synth ED to
#     `_build_encounter_resource`) knows exactly which slots differ from
#     the canonical `_CLASS_DISPLAY_JA` / `_ACT_PRIORITY_DISPLAY_JA` /
#     `code_lookup("hl7-admit-source"/"hl7-discharge-disposition", …)`
#     tables and needs a targeted override.
#
# NOTE: These four values INTENTIONALLY diverge from the canonical tables
# — the canonical helpers currently render:
#   * `_CLASS_DISPLAY_JA["EMER"]           = "救急"`      (vs synth ED "救急外来")
#   * `_ACT_PRIORITY_DISPLAY_JA["EM"]      = "救急"`      (vs synth ED "緊急")
#   * `code_lookup("hl7-admit-source",         "outp", "ja")`
#     and `code_lookup("hl7-discharge-disposition", "hosp", "ja")` return
#     the CS-registered displays; synth-ED's copy diverges deliberately for
#     the ED department context. A future PR that unifies them must update
#     both tables together (byte-diff shift documented in that PR).
_SYNTH_ED_DISPLAYS: dict[str, tuple[str, str]] = {
    # (JP display, US display) keyed by the JP-facing semantic slot name.
    "class_emer": ("救急外来", "Emergency"),
    "priority_em": ("緊急", "emergency"),
    "admit_source_outp": ("外来より", "From outpatient"),
    "discharge_disposition_hosp": ("入院となる", "Admitted to hospital"),
}


def _synth_ed_display(slot: str, country: str) -> str:
    """Return the JP or US display for a synth-ED slot from `_SYNTH_ED_DISPLAYS`."""
    jp, en = _SYNTH_ED_DISPLAYS[slot]
    return jp if is_jp(country) else en


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
                    "display": _synth_ed_display("class_emer", ctx.country),
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
                        "display": _synth_ed_display("priority_em", ctx.country),
                    }
                ],
            }
            _ed_resource["hospitalization"] = {
                "admitSource": {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-admit-source"),
                            "code": "outp",
                            "display": _synth_ed_display("admit_source_outp", ctx.country),
                        }
                    ],
                },
                "dischargeDisposition": {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-discharge-disposition"),
                            "code": "hosp",
                            "display": _synth_ed_display("discharge_disposition_hosp", ctx.country),
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
            from clinosim.modules.output.fhir_r4.demographics.smoking_alcohol import (
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
    # resources so the registry's single entry() wrap applies uniformly.
    out: list[dict] = []
    for i, vs in enumerate(ctx.record.get("vital_signs", [])):
        for bundle_entry in _build_vital_observations(vs, ctx.patient_id, i, ctx.country, ctx.primary_enc_id):
            out.append(bundle_entry["resource"])
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
    _order_in_rp_by_oid = build_order_in_rp_map(ctx.record.get("orders", []) or [])
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


def _bb_discharge_medication_requests(ctx: BundleContext) -> list[dict]:
    """Emit `discharge_prescription.items[]` as MedicationRequest (Issue #445).

    `CIFPatientRecord.discharge_prescription` reached the CSV adapter and the discharge
    summary narrative but no FHIR builder, so take-home and outpatient-renewal
    prescriptions were dropped from the FHIR export — a CIF→FHIR no-drop violation.
    This builder closes that path; it reads only existing CIF and draws no randomness, so
    every other resource type stays byte-identical.

    One prescription belongs to one encounter (CIF records carry exactly one), so the
    sequence numbers restart per record and feed both the id suffix and `orderInRp`.
    """
    out: list[dict] = []
    rx = ctx.record.get("discharge_prescription")
    if not rx:
        return out
    items = get_attr_or_key(rx, "items", None) or []
    if not items:
        return out

    encounters = ctx.record.get("encounters") or []
    if not encounters:
        return out
    enc = encounters[0]
    enc_id = get_attr_or_key(enc, "encounter_id", "") or ctx.primary_enc_id
    enc_type = str(get_attr_or_key(enc, "encounter_type", "") or "")

    issue_date = str(get_attr_or_key(rx, "issue_date", "") or "")
    discharge_dt = str(get_attr_or_key(enc, "discharge_datetime", "") or "")
    # `authoredOn` is min=1 in JP_MedicationRequest (JP Core 1.2.0). Before the
    # Issue #466 fix in `_simulate_patient`, the inpatient CIF `issue_date`
    # held the admission timestamp (7-15 days early) and needed to be replaced
    # here with `discharge_datetime`. That defect is fixed at the source, so
    # `issue_date` is now correct for both inpatient (= planned_discharge) and
    # outpatient (= visit start). `discharge_dt` remains as a fallback so a
    # future snapshot-truncation change cannot produce an empty cardinality.
    authored_on = issue_date or discharge_dt

    prescriber_id = str(get_attr_or_key(rx, "prescriber_id", "") or "")

    seq = 0
    for item in items:
        if not str(get_attr_or_key(item, "drug_name", "") or "").strip():
            continue  # blank drug name (CIF data quality) — same skip as _bb_medication_requests
        seq += 1
        out.append(
            _build_discharge_medication_request(
                item,
                ctx.patient_id,
                ctx.country,
                enc_id,
                enc_type,
                seq,
                authored_on,
                prescriber_id=prescriber_id,
            )
        )
    return out


def build_order_in_rp_map(orders: list) -> dict[str, int]:
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
    # 番号にするため、`build_order_in_rp_map` の同一ロジックで再構築。
    _order_in_rp_by_oid = build_order_in_rp_map(ctx.record.get("orders", []) or [])
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
        _lang = "ja" if is_jp(ctx.country) else "en"
        _profile = (
            {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Procedure"]}}
            if is_jp(ctx.country)
            else {}
        )
        # C4-03/18 (session 43 cycle 4): PROCEDURE-Order path lacked
        # Procedure.category. Bind SNOMED 277132007 (Therapeutic procedure,
        # SNOMED CT) — these are treatment-side procedures (splint / bandage /
        # wound care / etc.) routed to PROCEDURE by emergency.py's _procedure_kw
        # filter. category is a Procedure.category coding, well-known SNOMED
        # concept from https://build.fhir.org/valueset-procedure-category.html.
        _cat_lang = "ja" if is_jp(ctx.country) else "en"
        # Issue #474: localize the Order display for JP so treatment-side
        # procedures (splint/bandage/wound-care/O2 etc.) don't leak English
        # into JP `Procedure.code.text`. `_localize_drug_name` is the
        # phrase-level translator that consults `drug_names_ja.yaml` (which
        # already carries entries like "Ice pack application" → "氷嚢貼付",
        # "Wound irrigation with normal saline" → "生理食塩液による創部洗浄")
        # and internally chains dosage-abbrev translation (O2 → 酸素投与 etc.).
        # US path unchanged (helper is a no-op for is_us(country)).
        _code_text = _localize_drug_name(display, ctx.country) if display else "Procedure"
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
            "code": {"text": _code_text},
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
                if is_jp(ctx.country)
                else "Procedure indicated by encounter diagnosis",  # noqa: E501
            }
        ]
        # CY7-18 (Chain-7): text-only bodySite fallback for order-derived
        # Procedures — the Order carries display_name but not a SNOMED site
        # code, so text is defensible.
        procedure_res["bodySite"] = [
            {
                "text": "処置部位不明" if is_jp(ctx.country) else "Body site not specified",
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
            "text": "成功" if is_jp(ctx.country) else "Successful",
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
