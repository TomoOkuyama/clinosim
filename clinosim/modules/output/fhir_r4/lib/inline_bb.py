"""Inline bundle builders for `fhir_r4_adapter.py`.

Split from `clinosim/modules/output/fhir_r4_adapter.py` — see PR L.

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

from clinosim.codes import get_system_uri, system_key_for
from clinosim.codes import lookup as code_lookup
from clinosim.codes.hl7_encounter import ActPriority, AdmitSource
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
    _resolve_antibiotic_mr_id,
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


# Issue #546: synth-ED bridge Encounter now delegates to canonical
# `_build_encounter`. `_make_synth_ed_enc_dict` builds a minimal CIF-shape
# enc dict; the caller pops the canonical `dischargeDisposition` fallback
# because the ED→IMP transition is expressed via `partOf` on the primary
# IMP encounter (spec DD2 / DD4).
def _make_synth_ed_enc_dict(
    ctx: BundleContext,
    imp_enc: dict,
    partof_id: str,
) -> dict:
    """Build a minimal CIF-shape enc dict for the synth-ED bridge Encounter.

    Fed to `_build_encounter` so the synth-ED path emits through the
    single canonical builder (Issue #546, spec DD1). Preserves the
    ValueError/TypeError-tolerant admission_datetime derivation of the
    pre-refactor inline block: if the IMP encounter's admission_datetime
    is missing or non-ISO, admission_datetime is left empty and the
    canonical builder skips the period block (encounter.py:179).
    """
    _imp_adm = (
        imp_enc.get("admission_datetime", "")
        if isinstance(imp_enc, dict)
        else getattr(imp_enc, "admission_datetime", "")
    )
    _imp_adm_str = str(_imp_adm) if _imp_adm else ""
    # ED stay ~3.5 hours before IMP admission — clinical-realistic bridge.
    _ed_end_str = _imp_adm_str
    _ed_start_str = ""
    try:
        from datetime import datetime as _dt
        from datetime import timedelta as _td

        if _imp_adm_str and "T" in _imp_adm_str:
            _dt0 = _dt.fromisoformat(_imp_adm_str.replace("Z", "+00:00"))
            _ed_start_str = (_dt0 - _td(hours=3, minutes=30)).isoformat()
    except (ValueError, TypeError):
        pass
    _att = (
        imp_enc.get("attending_physician_id", "")
        if isinstance(imp_enc, dict)
        else getattr(imp_enc, "attending_physician_id", "")
    )
    _chief = (
        imp_enc.get("chief_complaint", "") if isinstance(imp_enc, dict) else getattr(imp_enc, "chief_complaint", "")
    )
    # Issue #776: also propagate `chief_complaint_ja` so the JP `reasonCode.text`
    # fallback (encounter.py:307) renders in Japanese. `inpatient.py:246`
    # populates the JA field on IMP encounters from the disease protocol,
    # but the synth-ED bridge previously dropped it and every EMER
    # reasonCode.text fell back to English on JP output (14/54 in
    # JP p=500 seed 42 baseline).
    _chief_ja = (
        imp_enc.get("chief_complaint_ja", "")
        if isinstance(imp_enc, dict)
        else getattr(imp_enc, "chief_complaint_ja", "")
    )
    return {
        "encounter_id": partof_id,
        "encounter_type": "emergency",
        "status": "completed",
        "priority": ActPriority.EM.value,
        "admit_source": AdmitSource.OUTP.value,
        "admission_datetime": _ed_start_str,
        "discharge_datetime": _ed_end_str,
        "attending_physician_id": _att,
        "chief_complaint": _chief,
        "chief_complaint_ja": _chief_ja,
        "department_id": "",
    }


def _bb_patient(ctx: BundleContext) -> list[dict]:
    return [_build_patient(ctx.patient_data, ctx.country)]


def _bb_coverage(ctx: BundleContext) -> list[dict]:
    return _build_coverage_resources(ctx.patient_data, ctx.country)


def _bb_encounters(ctx: BundleContext) -> list[dict]:
    # C5-22: record-level fields propagated to Encounter builder
    # so classHistory (ward→ICU transition) + statusHistory (planned→in-progress→finished)
    # can be emitted.
    _record = ctx.record
    _icu_day = (
        _record.get("icu_transferred_day", -1)
        if isinstance(_record, dict)
        else getattr(_record, "icu_transferred_day", -1)
    )
    _deceased = _record.get("deceased", False) if isinstance(_record, dict) else getattr(_record, "deceased", False)
    # C5-12 (history chain): extract chronic condition codes
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
        # ED bridge Encounter emit (CY7-05 + N-3 refinement):
        # - Always emit the synth `-ED` companion Encounter when the IMP
        #   carries an `admit_source_encounter_id`, so Phase B document
        #   stubs (ED_NOTE / ED_TRIAGE_NOTE with encounter_id=`{IMP}-ED`)
        #   never reference a nonexistent Encounter.
        # - Only set the ED→IMP partOf on the IMP resource itself if
        #   `_build_encounter` did NOT already set one for readmission
        #   linkage (readmission takes precedence — same field, different
        #   semantics). This preserves the readmission chain while still
        #   materializing the bridge Encounter (fixes the readmission×EMD
        #   dangling-reference case, ~13% of via-ED IMPs in p=10000).
        if _partof_id:
            if "partOf" not in _resource:
                _resource["partOf"] = {"reference": f"Encounter/{_partof_id}"}
            # CY7-05 synth-ED bridge Encounter: delegate to canonical
            # `_build_encounter` so localization / CS-registry lookups
            # are single-source-of-truth (Issue #546, spec DD1).
            synth_enc = _make_synth_ed_enc_dict(ctx, enc, _partof_id)
            _ed_resource = _build_encounter(
                synth_enc,
                ctx.patient_id,
                country=ctx.country,
            )
            # synth-ED conveys the discharge-to-IMP transition via partOf,
            # not dischargeDisposition; the canonical "home" fallback
            # (encounter.py:487) does not fit the bridge-encounter
            # context (spec DD2 / DD4).
            _ed_resource.get("hospitalization", {}).pop("dischargeDisposition", None)
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
            # C1-12: US Core / JP Core social-history
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
    # CO-7: propagate encounter_type for MR.intent
    # inference. The primary encounter type is a reliable proxy when
    # CIF Order.clinical_intent is not populated.
    encounters = ctx.record.get("encounters", []) or []
    primary_enc_type = encounters[0].get("encounter_type", "") if encounters else ""
    # C4-22: MR.requester fallback to encounter attending
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
    # clinosim_feedback P1-4: JP_MedicationRequest.identifier slice
    # rpNumber + orderInRp を assign。1 encounter = 1 Rp グループとして扱い、
    # encounter 内の medication order 出現順を orderInRp (1-based) にする。
    # 同一 order の MedicationRequest / MedicationAdministration は同じ
    # order_id → order_in_rp map を使うため両者の紐付けが取れる。
    _order_in_rp_by_oid = build_order_in_rp_map(ctx.record.get("orders", []) or [])
    # Chronic codes for primary-condition-ref resolution (chronic-primary
    # encounters resolve reasonReference to the patient-scoped chronic).
    _chronic_codes = _extract_chronic_codes(ctx.patient_data or {})
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
                    chronic_condition_codes=_chronic_codes,
                )
            )
    return out


def _extract_chronic_codes(patient_data: dict) -> list[str]:
    """Return the ordered list of chronic-condition ICD codes for a patient.

    Order matters — `primary_condition_ref_from_codes` uses the list index
    as the chronic Condition's suffix (`cond-chronic-{pat}-{i:02d}`), which
    must line up with `_build_conditions`' own iteration.
    """
    out: list[str] = []
    for _c in (patient_data or {}).get("chronic_conditions", []) or []:
        if isinstance(_c, str):
            out.append(_c)
        elif isinstance(_c, dict):
            out.append(_c.get("code", ""))
        else:
            out.append(getattr(_c, "code", ""))
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
    # C5-07 (history chain): build the set of MedicationRequest ids
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
    # bypass the English keys). CO-8 fixed the MR-side; MAR-side
    # requires this join because MAR records don't carry code_yj directly.
    _order_code_by_id: dict[str, str] = {}
    for order in ctx.record.get("orders", []) or []:
        if order.get("order_type") == "medication":
            if not (order.get("display_name") or "").strip():
                continue
            _base_oid = order.get("order_id", "") or ""
            # Issue #738: mirror the MR builder's exact id construction
            # (`resource_id = _resolve_antibiotic_mr_id(order.get("order_id"))`
            # at medications.py:636). The pre-#738 code prepended
            # `{encounter_id}-` to build `_mr_id`, matching a stale double-prefix
            # format the MR builder had already dropped (see medications.py
            # 622-625 comment). The mismatch made 100% of MAR.request.reference
            # look "dangling" to the strip check below, so the walker popped
            # every reference and the shipped MAR-MR audit-trail link went from
            # deterministic-but-scoped to completely missing.
            _mr_id = _resolve_antibiotic_mr_id(_base_oid) if _base_oid else ""
            if _mr_id:
                _mr_ids.add(_mr_id)
            _oc = order.get("order_code", "") or ""
            if _base_oid and _oc:
                _order_code_by_id[_base_oid] = _oc
    # clinosim_feedback P1-4: JP_MedicationAdministration.identifier
    # slice orderInRp。同 order_id を参照する MedicationRequest と同じ
    # 番号にするため、`build_order_in_rp_map` の同一ロジックで再構築。
    _order_in_rp_by_oid = build_order_in_rp_map(ctx.record.get("orders", []) or [])
    _chronic_codes = _extract_chronic_codes(ctx.patient_data or {})
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
            chronic_condition_codes=_chronic_codes,
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
    # C4-17: Procedure.performer fallback to encounter
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
    out = [
        _build_procedure(proc, ctx.patient_id, i, ctx.country, record=ctx.record) for i, proc in enumerate(_enriched)
    ]
    # RM-6c: emit Procedure resources from PROCEDURE-type Orders
    # too. These are procedure/device items (compression device, splint, etc.)
    # that used to leak through the MedicationRequest path — RM-6a/b routed
    # them here at CIF creation. Emit a light-weight Procedure per Order.
    from clinosim.modules.output.fhir_r4.procedures.oxygen_therapy import is_oxygen_order

    proc_seq = len(out) + 1
    for order in ctx.record.get("orders", []) or []:
        ot = order.get("order_type", "") if isinstance(order, dict) else getattr(order, "order_type", "")
        # OrderType enum stringifies to its value
        if str(ot) not in ("procedure", "OrderType.PROCEDURE"):
            continue
        # Oxygen-therapy orders are emitted by `_bb_oxygen_therapy` with a
        # session-derived performedPeriod, SNOMED coding, and no misleading
        # bodySite placeholder — skip them here so we do not emit a duplicate
        # point-in-time Procedure with the generic order-derived shape.
        if is_oxygen_order(order):
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
        # C4-03/18: PROCEDURE-Order path lacked
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
            # Chronic-primary encounters resolve to the patient-scoped chronic
            # Condition; acute-primary encounters keep the encounter-scoped id.
            from clinosim.modules.output.fhir_r4.conditions.primary_ref import primary_condition_ref

            _primary_ref = primary_condition_ref(ctx.record, ctx.patient_id, enc_id)
            procedure_res["reasonReference"] = [{"reference": f"Condition/{_primary_ref}"}]
        if ordered_dt:
            procedure_res["performedDateTime"] = str(ordered_dt)
        if ordered_by:
            procedure_res["performer"] = [{"actor": {"reference": f"Practitioner/{ordered_by}"}}]
        # Issue #816 (P2-5): populate reasonCode with real ICD-10 coding
        # from encounter's clinical_diagnosis (same treatment session-88j P2-5a
        # gave to the CIF-procedures path in procedures.py). Order-derived
        # Procedures (splint/bandage/wound-care/O2/etc.) previously
        # emitted a hardcoded generic text — 48% of all Procedures fell
        # here and consumer views could not distinguish the indication.
        _dx = (ctx.record or {}).get("clinical_diagnosis", {}) or {}
        _dx_code = _dx.get("discharge_diagnosis_code") or _dx.get("admission_diagnosis_code", "") or ""
        _dx_display = _dx.get("discharge_diagnosis_display") or _dx.get("admission_diagnosis_display", "") or ""
        _generic_reason_text = (
            "入院時診断に基づく処置" if is_jp(ctx.country) else "Procedure indicated by encounter diagnosis"
        )
        if _dx_code:
            _icd_key = system_key_for("diagnosis", ctx.country)
            _reason_display = _dx_display or (code_lookup(_icd_key, _dx_code, _lang) or _dx_code)
            procedure_res["reasonCode"] = [
                {
                    "coding": [
                        {
                            "system": get_system_uri(_icd_key),
                            "code": _dx_code,
                            "display": _reason_display,
                        }
                    ],
                    "text": _reason_display or _generic_reason_text,
                }
            ]
        else:
            procedure_res["reasonCode"] = [{"text": _generic_reason_text}]
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
    # RM-3: Immunization.performer.actor references (nurse admin).
    for imm in ctx.record.get("immunizations", []) or []:
        add(imm.get("administered_by", "") if isinstance(imm, dict) else getattr(imm, "administered_by", ""))
    # RM-1: nursing survey Observations use primary_nurse_id;
    # ensure the nurse is emitted even when not the primary_nurse of encounter.
    for enc in ctx.record.get("encounters", []) or []:
        add(enc.get("primary_nurse_id", "") if isinstance(enc, dict) else getattr(enc, "primary_nurse_id", ""))
    # C2-09: also emit every pharmacist in the roster so
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
