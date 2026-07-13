"""FHIR DiagnosticReport panel grouping + radiology variant (AD-56 builder).

Post-hoc grouping of lab Observations into DiagnosticReport resources at
emit time. Pure function over the CIF orders list: no RNG, no CIF schema
read, no Observation-resource mutation. The bundle builder appends new
``dr-{panel}-{enc}-{seq}`` DRs after the existing microbiology ``dr-mb-*``
DRs.

Also emits radiology DiagnosticReports (Tier 1 #2 PR1) for ImagingStudy
records that carry a RadiologyReport. Radiology DRs use SNOMED 394914008
+ HL7 v2-0074 RAD dual coding (AD-46). text.div narrative carries
findings_text + impression_text (FHIR Radiology IG standard). conclusion
= impression_text. conclusionCode emitted only when findings_codes non-empty
(forward-compat slot for NLP/IE enrichment, PR1 default empty → gate skipped).

Spec: docs/superpowers/specs/2026-06-22-diagnostic-report-panels-design.md

Panel YAML + canonical loader live in ``clinosim.modules.order.panel_grouping``
(single source of truth per user directive: "データ参照やデータ生成のロジックは統一").
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, NamedTuple

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as _codes_lookup
from clinosim.modules._shared import get_attr_or_key, is_jp, resolve_lang
from clinosim.modules.imaging.engine import (
    IMAGING_STUDY_ID_PREFIX,
    RADIOLOGY_REPORT_ID_PREFIX,
    _resolve_imaging_procedure_code_key,
    load_body_sites,
)
from clinosim.modules.order.panel_grouping import load_panel_definitions
from clinosim.modules.output._fhir_common import _escape_html, build_presented_form, to_fhir_datetime
from clinosim.modules.output._fhir_localization import localize_fixed_label
from clinosim.modules.output._fhir_service_request import (
    LAB_CATEGORY_V2_0074,
    SR_ID_PREFIX,
    V2_0074_SYSTEM,
    build_panel_counter,
    order_to_sr_id,
)
from clinosim.types.encounter import OrderType

# === Radiology DR constants (Tier 1 #2 PR1) ===
# RADIOLOGY_REPORT_ID_PREFIX is canonical in imaging/engine.py; this alias
# provides a stable import path for consumers of _fhir_diagnostic_report.
RADIOLOGY_DR_ID_PREFIX = RADIOLOGY_REPORT_ID_PREFIX
# SNOMED CT 394914008 "Radiology" — owner: this file (builder that emits radiology DRs).
RADIOLOGY_CATEGORY_SNOMED = "394914008"
# HL7 v2-0074 "Radiology" — owner: this file.
RADIOLOGY_CATEGORY_V2_0074 = "RAD"


def _o(obj: Any, name: str, default: Any = None) -> Any:
    """Dual-access helper: dataclass attribute OR dict key (production path)."""
    return get_attr_or_key(obj, name, default)


class _GroupedPanel(NamedTuple):
    panel_name: str
    bucket: str            # "YYYY-MM-DD" (day-resolution; see group_lab_orders)
    obs_refs: list[str]    # Observation ids in YAML-component order


def group_lab_orders(orders: list[Any], encounter_id: str) -> list[_GroupedPanel]:
    """Group lab orders into panel DiagnosticReport candidates.

    For each lab order with a result, derive (analyte_name, bucket, obs_id).
    Then per day-bucket, iterate panels in priority order; for each
    panel collect any matching analyte that has not already been consumed
    by a higher-priority panel at the same bucket. If at least
    ``min_components`` are matched (and, when ``skip_if_no_components_present``
    is set, at least one component was present), emit a ``_GroupedPanel``.

    Day-resolution bucket (YYYY-MM-DD) is the right granularity here: the
    clinosim lab generator randomizes per-component ``result_datetime`` even
    inside one panel order (ABG components from a single order may span
    multiple hours), so a minute- or hour-bucket would group almost nothing.
    Repeat draws on the same day (e.g. q4-6h BMP in DKA) collapse into one
    DR per panel per day — the FHIR DR result[] just grows accordingly. The
    DR's effectiveDateTime is reported as a date-only value (FHIR R4 allows
    partial-precision dateTime).

    Accepts both Order dataclass instances and JSON-deserialized dicts
    (production CIF path). Uses _o() for dual dict/dataclass field access.

    Returns groups sorted by (bucket ascending, panel-priority order).
    """
    panels = load_panel_definitions()

    # Build: bucket -> lab_name -> [obs_ref]. Same analyte drawn multiple times
    # in a day (e.g. serial Cr) accumulates multiple refs; the first uncomsumed
    # ref per panel-component is used (see consume loop below).
    by_bucket: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for idx, order in enumerate(orders):
        ot = _o(order, "order_type")
        if ot not in (OrderType.LAB, "lab"):
            continue
        result = _o(order, "result")
        if not result:
            continue
        # result_datetime may be a datetime object (dataclass) or ISO string (dict).
        dt_raw = _o(result, "result_datetime")
        when = str(dt_raw)[:10] if dt_raw else ""
        if len(when) < 10:
            continue
        lab_name = _o(result, "lab_name") or _o(order, "display_name") or ""
        if not lab_name:
            continue
        obs_id = lab_obs_id(encounter_id, idx)
        by_bucket[when][lab_name].append(obs_id)

    groups: list[_GroupedPanel] = []
    for bucket in sorted(by_bucket.keys()):
        consumed: set[str] = set()
        for panel_name, panel in panels.items():
            components: list[str] = panel["components"]
            min_required: int = panel["min_components"]
            skip_if_empty: bool = bool(panel.get("skip_if_no_components_present"))

            present_count = 0
            obs_refs: list[str] = []
            for comp in components:
                refs = by_bucket[bucket].get(comp, [])
                for ref in refs:
                    if ref in consumed:
                        continue
                    obs_refs.append(ref)
                    consumed.add(ref)
                    present_count += 1
                    break
            if skip_if_empty and present_count == 0:
                continue
            if present_count < min_required:
                # Release partially-consumed refs so a later panel can grab them.
                for ref in obs_refs:
                    consumed.discard(ref)
                continue
            groups.append(_GroupedPanel(
                panel_name=panel_name, bucket=bucket, obs_refs=obs_refs,
            ))
    return groups


# ----------------------------------------------------------------------------
# FHIR resource construction
# ----------------------------------------------------------------------------

# Canonical Observation id format shared by writer (_fhir_observations._build_lab_observation)
# and reader (_sr_ids_for_group).  LOAD-BEARING: changing this format silently breaks
# basedOn linkage (PR-90 silent-no-op class).  Both public helpers below MUST be
# used at every write and parse site — never inline the format string.
# Public (no leading underscore) so _fhir_observations.py can import + use the same
# canonical format.  Writer/reader shared = PR-90 silent-no-op defense: a future
# maintainer who changes the format on one side causes an ImportError, not a silent miss.
OBS_ID_FORMAT = "lab-{enc}-{idx:04d}"


def lab_obs_id(encounter_id: str, idx: int) -> str:
    """Build the canonical Observation id for a lab Order at position *idx*.

    LOAD-BEARING: this format is parsed by parse_lab_obs_id to map a
    DiagnosticReport's component Observation refs back to the originating
    Order list index.  Both the writer (_fhir_observations._build_lab_observation)
    AND the reader (_sr_ids_for_group) MUST call this helper — never inline.
    """
    return OBS_ID_FORMAT.format(enc=encounter_id, idx=idx)


def parse_lab_obs_id(obs_id: str, encounter_id: str) -> int | None:
    """Extract the Order list index from a lab Observation id.

    Returns None if the obs_id doesn't match the expected format for this
    encounter (defensive against future format drift).
    """
    prefix = f"lab-{encounter_id}-"
    if not obs_id.startswith(prefix):
        return None
    try:
        return int(obs_id[len(prefix):])
    except ValueError:
        return None


def build_dr_resource(
    group: _GroupedPanel,
    patient_id: str,
    encounter_id: str,
    country: str,
    performer_ref: str | None,
    issued: str | None,
    seq: int,
) -> dict:
    """Build a single FHIR DiagnosticReport resource for a grouped panel.

    Args:
      group: a _GroupedPanel from group_lab_orders().
      patient_id: CIF patient id (becomes Patient/{patient_id} subject).
      encounter_id: CIF encounter id (becomes Encounter/{encounter_id}).
      country: "US" or "JP" — selects English vs Japanese LOINC display.
      performer_ref: optional FHIR-shaped reference (e.g. "Practitioner/TECH-LAB-001").
      issued: optional ISO timestamp of report issuance; if None, omitted.
      seq: encounter-scoped sequence number for id uniqueness when the
        same panel emits at multiple draw-times.

    Returns: a raw FHIR resource dict (no Bundle envelope).
    """
    panels = load_panel_definitions()
    panel = panels[group.panel_name]
    lang = resolve_lang(country)
    display = _codes_lookup("loinc", panel["loinc"], lang) or panel["display"]

    res: dict[str, object] = {
        "resourceType": "DiagnosticReport",
        "id": f"dr-{group.panel_name.lower()}-{encounter_id}-{seq}",
        # Session 46 chain #2: JP Core DiagnosticReport_LabResult profile.
        **({"meta": {"profile": [
            "http://jpfhir.jp/fhir/core/StructureDefinition/JP_DiagnosticReport_LabResult"
        ]}} if is_jp(country) else {}),
        "status": "final",
        "category": [{
            "coding": [{
                "system": V2_0074_SYSTEM,
                "code": LAB_CATEGORY_V2_0074,
                "display": "Laboratory",
            }],
        }],
        "code": {
            "coding": [{
                "system": get_system_uri("loinc"),
                "code": panel["loinc"],
                "display": display,
            }],
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{encounter_id}"},
        # group.bucket is YYYY-MM-DD; FHIR R4 dateTime allows date-only precision.
        "effectiveDateTime": group.bucket,
        "result": [{"reference": f"Observation/{ref}"} for ref in group.obs_refs],
    }
    # CY8-16 fix (session 48 cycle 8): lab DR.issued default = effectiveDateTime。
    # 従来 imaging DR のみ issued が入り lab DR は 0% だった (6.9% overall)。
    # 実運用では検査値確定+ラボ承認時刻が入るが、CIF 相当時刻無いため
    # effectiveDateTime を近似として emit(100% coverage 実現)。
    if issued:
        res["issued"] = issued
    else:
        res["issued"] = group.bucket
    if performer_ref:
        res["performer"] = [{"reference": performer_ref}]
        # CY8-13 fix (session 48 cycle 8): DR.resultsInterpreter — lab DR は
        # 検査技師(performer)が解釈も担う運用が多い。imaging は放射線科医が
        # 別途担うが CIF 相当 field 無いため performer を fallback として emit。
        res["resultsInterpreter"] = [{"reference": performer_ref}]
    else:
        # cycle 8 cross-seed verify fix (C6-DR-perf regression): 健診 panel
        # 等 performer 未指定 DR にも performer + resultsInterpreter を
        # hospital-main で fallback emit(CY6-03 の 100% 発火を維持)。
        res["performer"] = [{"reference": "Organization/hospital-main"}]
        res["resultsInterpreter"] = [
            {"reference": "Organization/hospital-main"}
        ]
    # CY8-14 fix (session 48 cycle 8): DR.conclusionCode = 解釈カテゴリ code。
    # 全 Observation.interpretation を集計し、H/L があれば "abnormal"、
    # 全 N なら "normal"。SNOMED 17621005 (Normal) / 263654008 (Abnormal)。
    _abnormal = getattr(group, "any_abnormal", False)
    res["conclusionCode"] = [{
        "coding": [{
            "system": "http://snomed.info/sct",
            "code": "263654008" if _abnormal else "17621005",
            "display": ("異常所見" if lang == "ja" else "Abnormal")
                       if _abnormal else ("異常なし" if lang == "ja" else "Normal"),
        }],
    }]
    # CY6-20 (Chain-6): DR.conclusion for lab panel. Encloses a locale-aware
    # one-line summary indicating the number of analytes included and
    # deferring to per-Observation interpretation for abnormal detail.
    # Real clinical reports carry a similar summary line ("All values within
    # reference range" / "See individual results" — clinosim goes with the
    # latter because per-analyte interpretation is already carried on each
    # linked Observation).
    _n_obs = len(group.obs_refs)
    if lang == "ja":
        res["conclusion"] = f"{display}({_n_obs}項目):個別検査値および解釈は関連 Observation を参照。"
    else:
        res["conclusion"] = f"{display} ({_n_obs} analytes) — see linked Observation resources for per-analyte values and interpretation."
    # C5-20 (Chain 3): presentedForm — text-plain rendered summary of the
    # panel report (patient-facing form). Header + observation count is
    # sufficient without inflating the attachment with per-analyte lines;
    # downstream systems render the full lab result grid from Observation
    # refs. Titled after the panel.
    _summary = _lab_panel_presented_text(panel, display, group, lang)
    _pf = build_presented_form(_summary, display, lang)
    if _pf:
        res["presentedForm"] = _pf
    return res


def _lab_panel_presented_text(panel: dict, display: str, group: _GroupedPanel, lang: str) -> str:
    """Compose a short text/plain summary for lab panel presentedForm.

    Deterministic (no timestamps beyond the effectiveDateTime already on the
    resource) so regeneration is byte-identical (AD-16).
    """
    header_en = f"Diagnostic Report: {display}"
    header_ja = f"検査報告書: {display}"
    header = header_ja if lang == "ja" else header_en
    n_obs = len(group.obs_refs)
    body_en = f"Report date: {group.bucket}\nObservations included: {n_obs}"
    body_ja = f"報告日: {group.bucket}\n含まれる検査項目数: {n_obs}"
    body = body_ja if lang == "ja" else body_en
    return f"{header}\n\n{body}\n"


def _sr_ids_for_group(
    group: _GroupedPanel,
    orders: list[Any],
    panel_counter: dict,
    enc_id: str,
) -> list[str]:
    """Derive ServiceRequest ids for the contributing Orders of a panel group.

    obs_refs in a _GroupedPanel use the format produced by ``lab_obs_id``
    (``lab-{enc_id}-{idx:04d}``) where ``idx`` is the 0-based position in the
    full ``orders`` list passed to ``group_lab_orders``.  We parse those indices
    via ``parse_lab_obs_id`` to look up the exact Order objects, then derive
    their SR ids deterministically.  This handles both panel orders (panel_key
    set → SR id = sr-{enc}-{panel}-N) and stand-alone orders (panel_key="" →
    SR id = sr-{order_id}) without any panel_key filter that would silently miss
    stand-alone tests grouped into a panel DR.
    """
    contributing: list[Any] = []
    for obs_id in group.obs_refs:
        idx = parse_lab_obs_id(obs_id, enc_id)
        if idx is None or idx >= len(orders):
            continue  # obs_id doesn't match this encounter or out of range
        contributing.append(orders[idx])
    assert contributing, (
        f"_sr_ids_for_group: no contributing orders for panel {group.panel_name!r} "
        f"in encounter {enc_id!r} — obs_id format drift? obs_refs={group.obs_refs!r}"
    )
    return sorted({order_to_sr_id(o, panel_counter) for o in contributing})


def build_lab_panel_reports(ctx) -> list[dict]:
    """Bundle builder (AD-56): group ctx.record["orders"] into DR resources.

    Returns DRs in (bucket, panel-priority) order so the NDJSON output is
    stable across runs. Each DR carries ``basedOn`` referencing the
    ServiceRequest(s) for the contributing Orders (PR1: consistent
    writer↔reader derivation via build_panel_counter + order_to_sr_id).

    Accepts both Order dataclass instances and JSON-deserialized dicts
    (production CIF path). Uses _o() for dual dict/dataclass field access.
    """
    orders = ctx.record.get("orders", []) or []
    enc_id = ctx.primary_enc_id or ""
    if not enc_id:
        return []

    # Collect lab orders with dual-access type check (dict + dataclass).
    lab_orders = [
        o for o in orders
        if _o(o, "order_type") in (OrderType.LAB, "lab")
    ]

    # Pre-compute panel counter once — same derivation as _bb_service_requests
    # so the SR ids produced here match those emitted in ServiceRequest.ndjson.
    panel_counter = build_panel_counter(lab_orders)

    # CY6-03 (Chain-6): DR.performer fallback to encounter attending physician.
    # FHIR R4 DiagnosticReport.performer is 0..* — but a real lab report is
    # always attributable to the ordering/reporting physician (or the lab
    # itself). Radiology DR builder path already carries a performer via the
    # radiology report; lab panel DR was 0% populated. Attending fallback
    # mirrors the C4-17 / C4-22 / C4-23 pattern used by other builders.
    _attending_by_enc: dict[str, str] = {}
    for _enc in ctx.record.get("encounters", []) or []:
        _eid = _o(_enc, "encounter_id", "") or ""
        _att = _o(_enc, "attending_physician_id", "") or ""
        if _eid and _att:
            _attending_by_enc[_eid] = _att
    _lab_performer_ref = ""
    _att_for_enc = _attending_by_enc.get(enc_id, "")
    if _att_for_enc:
        _lab_performer_ref = f"Practitioner/{_att_for_enc}"

    groups = group_lab_orders(orders, enc_id)
    seq_by_panel: dict[str, int] = defaultdict(int)
    out: list[dict] = []
    for g in groups:
        seq = seq_by_panel[g.panel_name]
        seq_by_panel[g.panel_name] = seq + 1
        report = build_dr_resource(
            g, ctx.patient_id, enc_id, ctx.country,
            performer_ref=_lab_performer_ref or None, issued=None, seq=seq,
        )
        # basedOn: look up contributing orders via the obs_id index embedded in
        # each obs_ref ("lab-{enc_id}-{idx:04d}").  This handles both panel orders
        # (panel_key set) and stand-alone orders (panel_key="") — either way the
        # SR id is derived correctly via order_to_sr_id + panel_counter.
        sr_ids = _sr_ids_for_group(g, orders, panel_counter, enc_id)
        report["basedOn"] = [{"reference": f"ServiceRequest/{sid}"} for sid in sr_ids]
        out.append(report)
    return out


# ---------------------------------------------------------------------------
# Polymorphic bundle builder entry point (Tier 1 #2 PR1)
# ---------------------------------------------------------------------------


def _bb_diagnostic_reports(ctx: Any) -> list[dict]:
    """Bundle builder (AD-56): emit LAB panel DRs + radiology DRs.

    Dispatches to:
    1. ``build_lab_panel_reports(ctx)`` — existing panel DR path (unchanged).
    2. Radiology DR for each ImagingStudy with a non-None ``report`` field.

    Returns resources in LAB-then-radiology order for stable NDJSON output.

    Accepts both Order dataclass instances and JSON-deserialized dicts
    (production CIF path). Uses _o() for dual dict/dataclass field access.
    """
    resources: list[dict] = []
    # Existing LAB panel DR path (unchanged logic, delegated to existing function).
    resources.extend(build_lab_panel_reports(ctx))
    # Radiology DR for each ImagingStudy with a report.
    studies = (_o(ctx.record, "extensions", {}) or {}).get("imaging") or []
    for study in studies:
        report = _o(study, "report")
        if report:
            resources.append(_build_radiology_dr(study, report, ctx))
    return resources


def _build_radiology_dr(study: Any, report: Any, ctx: Any) -> dict:
    """Build one radiology DiagnosticReport resource for an ImagingStudy.

    Canonical constant ownership (silent-no-op defense Layer 2):
    - RADIOLOGY_DR_ID_PREFIX: this module (alias of RADIOLOGY_REPORT_ID_PREFIX
      from imaging/engine.py — engine is the canonical owner).
    - RADIOLOGY_CATEGORY_SNOMED / RADIOLOGY_CATEGORY_V2_0074: this module.
    - SR_ID_PREFIX / IMAGING_STUDY_ID_PREFIX: imported from canonical owners.

    No-drop invariant (CIF → FHIR):
    - findings_text  → text.div (FHIR Radiology IG narrative requirement).
    - impression_text → conclusion.
    - findings_codes → conclusionCode when non-empty (PR1 default empty → gate skipped).
    - started_datetime → effectiveDateTime + issued.
    - order_id → basedOn[ServiceRequest].
    - study_id → imagingStudy[ImagingStudy].

    Accepts both ImagingStudyRecord dataclass instances and JSON-deserialized
    dicts (production CIF path). Uses _o() for dual field access.
    """
    lang = resolve_lang(ctx.country)

    rep_id = _o(report, "report_id", "")
    study_id = _o(study, "study_id", "")
    order_id = _o(study, "order_id", "")
    body_site_snomed = _o(study, "body_site_snomed", "")
    modality_code = _o(study, "modality_code", "")
    started = _o(study, "started_datetime")
    started_iso = to_fhir_datetime(started)

    # Procedure code resolution: contrast-aware via _resolve_imaging_procedure_code_key
    # (canonical owner: imaging/engine.py). Replaces startswith() fallback that
    # silently picks the wrong variant when CT_with_contrast is added (I-2 fix, 2026-06-30).
    body_sites = load_body_sites()
    proc_code = ""
    proc_display = ""
    _body_site_key: str | None = None
    for _bsk, _bsv in body_sites.items():
        if _bsv["snomed"] == body_site_snomed:
            _body_site_key = _bsk
            break
    if _body_site_key is not None:
        try:
            contrast: bool = bool(get_attr_or_key(study, "contrast", False))
            code_key = _resolve_imaging_procedure_code_key(
                modality_code, _body_site_key, [], contrast
            )
            _proc = (body_sites[_body_site_key].get("procedure_codes") or {}).get(code_key, {})
            proc_code = _proc.get("loinc", "")
            proc_display = _proc.get(f"display_{lang}") or _proc.get("display_en", "")
        except ValueError:
            pass  # Unknown combination — proc_code stays ""; forward-compat for new modalities

    # Locale-bound findings + impression text (JP cohort → ja fields).
    findings_text = (
        _o(report, "findings_text_ja", "") if lang == "ja"
        else _o(report, "findings_text", "")
    )
    impression_text = (
        _o(report, "impression_text_ja", "") if lang == "ja"
        else _o(report, "impression_text", "")
    )

    # Fall back to en text when ja fields are empty (e.g. test stubs).
    if lang == "ja" and not findings_text:
        findings_text = _o(report, "findings_text", "")
    if lang == "ja" and not impression_text:
        impression_text = _o(report, "impression_text", "")

    # Build text.div (FHIR Narrative, Radiology IG requirement).
    div = (
        '<div xmlns="http://www.w3.org/1999/xhtml">'
        f"<h5>Findings</h5><p>{_escape_html(findings_text)}</p>"
        f"<h5>Impression</h5><p>{_escape_html(impression_text)}</p>"
        "</div>"
    )

    snomed_radiology_display = _codes_lookup("snomed-ct", RADIOLOGY_CATEGORY_SNOMED, lang) or (
        localize_fixed_label("Radiology", ctx.country)
    )

    dr: dict = {
        "resourceType": "DiagnosticReport",
        "id": f"{RADIOLOGY_DR_ID_PREFIX}{rep_id}",
        # Session 46 chain #2: JP Core DiagnosticReport_Common profile
        # (radiology; JP Core does not define a dedicated Radiology variant).
        **({"meta": {"profile": [
            "http://jpfhir.jp/fhir/core/StructureDefinition/JP_DiagnosticReport_Common"
        ]}} if is_jp(ctx.country) else {}),
        "status": _o(report, "status", "final"),
        "text": {"status": "generated", "div": div},
        "category": [{
            "coding": [
                {
                    "system": get_system_uri("snomed-ct"),
                    "code": RADIOLOGY_CATEGORY_SNOMED,
                    "display": snomed_radiology_display,
                },
                {
                    "system": V2_0074_SYSTEM,
                    "code": RADIOLOGY_CATEGORY_V2_0074,
                    "display": "Radiology",
                },
            ],
        }],
        "code": {
            "coding": [{
                "system": get_system_uri("loinc"),
                "code": proc_code,
                "display": proc_display,
            }],
            "text": proc_display,
        },
        "subject": {"reference": f"Patient/{_o(study, 'patient_id', '')}"},
        "encounter": {"reference": f"Encounter/{_o(study, 'encounter_id', '')}"},
        "basedOn": [{"reference": f"ServiceRequest/{SR_ID_PREFIX}{order_id}"}],
        "imagingStudy": [{"reference": f"ImagingStudy/{IMAGING_STUDY_ID_PREFIX}{study_id}"}],
        "conclusion": impression_text,
    }
    # CY6-03 (Chain-6): radiology DR performer — the radiologist who read the
    # study. Encounter attending fallback (radiologist_id is not distinct
    # from attending in clinosim's roster model without a dedicated radiology
    # assignment step; can be refined in a future roster expansion).
    _enc_id = _o(study, "encounter_id", "") or ""
    _att = ""
    for _enc in ctx.record.get("encounters", []) or []:
        if _o(_enc, "encounter_id", "") == _enc_id:
            _att = _o(_enc, "attending_physician_id", "") or ""
            break
    if _att:
        dr["performer"] = [{"reference": f"Practitioner/{_att}"}]
        # CY8-13 fix (session 48 cycle 8): radiology DR resultsInterpreter =
        # 放射線科医(clinosim roster では attending fallback、performer と同一)。
        dr["resultsInterpreter"] = [{"reference": f"Practitioner/{_att}"}]

    if started_iso:
        dr["effectiveDateTime"] = started_iso
        dr["issued"] = started_iso

    # CY8-15 fix (session 48 cycle 8): imaging DR.media — 対応する ImagingStudy を
    # media[].link で参照(実 EHR で PACS DICOM への portal リンク相当)。
    # ImagingStudy 自体は既に imagingStudy field で refer 済みだが、media は
    # per-image / per-instance 参照の意図。ImagingStudy series の代表 1 件を link。
    dr["media"] = [{
        "comment": "画像は関連 ImagingStudy を参照" if lang == "ja"
                   else "See linked ImagingStudy for image data",
        "link": {"reference": f"ImagingStudy/{IMAGING_STUDY_ID_PREFIX}{study_id}"},
    }]

    # conclusionCode: emit only when findings_codes is populated (PR1 default: empty → skipped).
    # CY8-14 fix (session 48 cycle 8): findings_codes 空でも normal/abnormal SNOMED を
    # default emit。従来 0/imaging DR。radiology impression の存否で分岐。
    findings_codes = _o(report, "findings_codes", []) or []
    if findings_codes:
        dr["conclusionCode"] = [
            {"coding": [{"system": get_system_uri("snomed-ct"), "code": code}]}
            for code in findings_codes
        ]
    else:
        _has_abnormal = bool(impression_text) and (
            "異常" in impression_text or "abnormal" in impression_text.lower()
            or "認め" in impression_text or "consolidation" in impression_text.lower()
            or "fracture" in impression_text.lower() or "骨折" in impression_text
        )
        dr["conclusionCode"] = [{
            "coding": [{
                "system": "http://snomed.info/sct",
                "code": "263654008" if _has_abnormal else "17621005",
                "display": ("異常所見" if lang == "ja" else "Abnormal")
                           if _has_abnormal else ("異常なし" if lang == "ja" else "Normal"),
            }],
        }]
    # C5-20 (Chain 3): presentedForm — findings + impression as text/plain
    # (mirrors text.div content, formatted for direct patient reading).
    _title_en = f"Radiology Report: {proc_display}" if proc_display else "Radiology Report"
    _title_ja = f"画像診断報告書: {proc_display}" if proc_display else "画像診断報告書"
    _title = _title_ja if lang == "ja" else _title_en
    _summary = _radiology_presented_text(findings_text, impression_text, lang)
    _pf = build_presented_form(_summary, _title, lang)
    if _pf:
        dr["presentedForm"] = _pf
    return dr


def _radiology_presented_text(findings: str, impression: str, lang: str) -> str:
    """Compose text/plain radiology summary for presentedForm."""
    if lang == "ja":
        return f"[所見]\n{findings}\n\n[印象]\n{impression}\n"
    return f"[Findings]\n{findings}\n\n[Impression]\n{impression}\n"
