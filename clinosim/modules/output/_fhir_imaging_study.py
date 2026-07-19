"""ImagingStudy FHIR R4 builder (Tier 1 #2 PR1).

Reads CIF extensions['imaging']: list[ImagingStudyRecord]. Emits one
ImagingStudy resource per Record. References ServiceRequest (via basedOn),
Endpoint (via endpoint[]), Encounter, Patient.

No-drop invariant: every populated CIF field maps to a FHIR target
(spec Section 3.4 matrix):
  study_id             -> ImagingStudy.id (imgst- prefix)
  study_instance_uid   -> ImagingStudy.identifier[0] (urn:dicom:uid)
  encounter_id         -> ImagingStudy.encounter
  patient_id           -> ImagingStudy.subject
  order_id             -> ImagingStudy.basedOn[ServiceRequest]
  status               -> ImagingStudy.status
  started_datetime     -> ImagingStudy.started
  modality_code        -> ImagingStudy.modality[0] (DCM system)
  series[*]            -> ImagingStudy.series[*]
  endpoint_id          -> ImagingStudy.endpoint[Endpoint]
  report               -> DiagnosticReport (Task 6 builder)

Canonical constant ownership:
- IMAGING_STUDY_ID_PREFIX, ENDPOINT_ID_PREFIX: engine.py (writer-owner),
  imported here for use + re-export (silent-no-op defense Layer 2).
- SR_ID_PREFIX: _fhir_service_request.py (writer-owner), imported for
  basedOn reference construction.
- DICOM_UID_SYSTEM: defined here (FHIR/DICOM standard constant).
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import resolve_lang
from clinosim.modules.imaging.engine import (  # canonical owners; re-exported below
    ENDPOINT_ID_PREFIX,
    IMAGING_STUDY_ID_PREFIX,
    load_modalities,
)
from clinosim.modules.output._fhir_common import BundleContext, to_fhir_datetime
from clinosim.modules.output._fhir_service_request import SR_ID_PREFIX  # canonical owner

# Writer-owned constant — DICOM/FHIR standard URI for DICOM Study UID.
DICOM_UID_SYSTEM = "urn:dicom:uid"

# Re-export so readers can import from this module or the canonical owner.
__all__ = [
    "IMAGING_STUDY_ID_PREFIX",
    "ENDPOINT_ID_PREFIX",
    "DICOM_UID_SYSTEM",
    "_bb_imaging_studies",
]


def _isoformat_or_str(dt: Any) -> str:
    """Convert datetime to ISO-8601 string; passthrough for str; empty for None.

    Session 40 (FP-UNIFY-2 completion): delegates to the shared
    ``to_fhir_datetime`` helper in ``_fhir_common``. Kept as a thin alias so
    external callers importing this symbol continue to work; new code should
    import ``to_fhir_datetime`` directly.
    """
    return to_fhir_datetime(dt)


def _bb_imaging_studies(ctx: BundleContext) -> list[dict[str, Any]]:
    """Emit one ImagingStudy per ImagingStudyRecord in extensions['imaging']."""
    studies = (_o(ctx.record, "extensions", {}) or {}).get("imaging") or []
    if not studies:
        return []
    lang = resolve_lang(ctx.country)
    # CY7-03 (Chain-7): reasonCode inherits the encounter's primary reasonCode
    # (imaging is done to investigate the current diagnosis). Encounter → dx.
    _enc_reason_by_id: dict[str, list[dict]] = {}
    for _enc in ctx.record.get("encounters", []) or []:
        _eid = _o(_enc, "encounter_id", "")
        if _eid:
            _rc = _enc.get("reason_code", "") if isinstance(_enc, dict) else getattr(_enc, "reason_code", "")
            # Encounter carries reason via chief_complaint or disease_event_id;
            # simpler path: use the study's own order-encounter link and
            # look up the encounter's primary Condition.code at ImagingStudy
            # emit is out of scope here. Instead attach a chief-complaint text
            # from the Encounter which is already carried on Encounter model.
            _cc = _enc.get("chief_complaint", "") if isinstance(_enc, dict) else getattr(_enc, "chief_complaint", "")
            if _cc:
                _enc_reason_by_id[_eid] = [{"text": _cc}]
    return [_build_imaging_study(s, lang, _enc_reason_by_id) for s in studies]


def _build_imaging_study(
    study: Any, lang: str, enc_reason_by_id: dict[str, list[dict]] | None = None
) -> dict[str, Any]:  # noqa: E501
    """Build one FHIR R4 ImagingStudy resource from an ImagingStudyRecord.

    session 48 cycle 8 拡張(案 D):stub-only ImagingStudy(modality/body_site
    が空)にも対応。stub は modality / series 0..* を空で emit、identifier +
    status + subject + basedOn 最小構成で spec-valid。SR がある限り「オーダー
    はあった」ことを FHIR consumer に伝達可能。
    """
    modalities = load_modalities()
    modality_code = _o(study, "modality_code", "")
    mod_def = modalities.get(modality_code, {}) if modality_code else {}
    modality_display = mod_def.get(f"display_{lang}") or mod_def.get("display_en", modality_code)

    series_list = _o(study, "series", []) or []
    series_resources = [_build_series(s, lang) for s in series_list]
    total_instances = sum(_o(s, "instance_count", 0) for s in series_list)

    # 案 D stub 対応: modality_code 空なら modality array 空 emit
    modality_field: list[dict] = []
    if modality_code:
        modality_field = [
            {
                "system": get_system_uri("dicom-modality"),
                "code": modality_code,
                "display": modality_display,
            }
        ]

    res: dict[str, Any] = {
        "resourceType": "ImagingStudy",
        # session 51: study_id (engine.py) は既に IMAGING_STUDY_ID_PREFIX 付。builder 再 prepend の double-prefix bug 修正。  # noqa: E501
        "id": _o(study, "study_id", ""),
        "identifier": [
            {
                "system": DICOM_UID_SYSTEM,
                "value": f"urn:oid:{_o(study, 'study_instance_uid', '')}",
            }
        ],
        "status": _o(study, "status", "available"),
        "subject": {"reference": f"Patient/{_o(study, 'patient_id', '')}"},
        "encounter": {"reference": f"Encounter/{_o(study, 'encounter_id', '')}"},
        "basedOn": [{"reference": f"ServiceRequest/{SR_ID_PREFIX}{_o(study, 'order_id', '')}"}],
        "numberOfSeries": len(series_resources),
        "numberOfInstances": total_instances,
    }
    # session 59 #299:FHIR R4 "配列は空にできません" 制約 — modality / series
    # は 0..* だが FHIR 一般則で空 array の emit は禁止(v5 で 48 件 error)。
    # stub-only ImagingStudy(modality_code 空)では両 field を drop。
    if modality_field:
        res["modality"] = modality_field
    if series_resources:
        res["series"] = series_resources
    # endpoint は stub でない時のみ emit(PACS 参照)
    endpoint_id = _o(study, "endpoint_id", "")
    if endpoint_id:
        res["endpoint"] = [{"reference": f"Endpoint/{endpoint_id}"}]
    started = _isoformat_or_str(_o(study, "started_datetime", None))
    if started:
        res["started"] = started
    # CY7-03 (Chain-7): reasonCode from encounter chief complaint (text-only
    # CodeableConcept per no-fabrication policy — the actual ICD/SNOMED
    # code lives on the Condition; ImagingStudy references it via encounter).
    if enc_reason_by_id:
        _rc = enc_reason_by_id.get(_o(study, "encounter_id", ""))
        if _rc:
            res["reasonCode"] = _rc
    # CY7-04 (Chain-7): procedureCode — resolve LOINC from body_sites.yaml
    # procedure_codes for the (modality, body_site, contrast) triplet. Uses
    # the same resolver as the SR / radiology-DR emit paths so the codes
    # match across resources.
    body_site_snomed = _o(study, "body_site_snomed", "")
    from clinosim.modules.imaging.engine import (
        _resolve_imaging_procedure_code_key,
        load_body_sites,
    )

    body_sites = load_body_sites()
    _bs_key = None
    for bsk, bsv in body_sites.items():
        if bsv["snomed"] == body_site_snomed:
            _bs_key = bsk
            break
    if _bs_key is not None:
        try:
            _contrast = bool(_o(study, "contrast", False))
            _ck = _resolve_imaging_procedure_code_key(modality_code, _bs_key, [], _contrast)
            _proc = (body_sites[_bs_key].get("procedure_codes") or {}).get(_ck, {})
            _proc_loinc = _proc.get("loinc", "")
            _proc_display = _proc.get(f"display_{lang}") or _proc.get("display_en", "")
            if _proc_loinc:
                res["procedureCode"] = [
                    {
                        "coding": [
                            {
                                "system": get_system_uri("loinc"),
                                "code": _proc_loinc,
                                "display": _proc_display,
                            }
                        ],
                        "text": _proc_display,
                    }
                ]
        except ValueError:
            pass  # unknown combination, procedureCode omitted (forward-compat)
    return res


def _build_series(series: Any, lang: str) -> dict[str, Any]:
    """Build one FHIR R4 ImagingStudy.series element from an ImagingSeries."""
    snomed_system = get_system_uri("snomed-ct")
    body_site_snomed = _o(series, "body_site_snomed", "")
    # Resolve body site display via code registry (AD-30 — CIF stores the code
    # only; import-time validation guarantees every body_sites.yaml SNOMED
    # code resolves).
    body_site_display = code_lookup("snomed-ct", body_site_snomed, lang)
    modalities = load_modalities()
    modality_code = _o(series, "modality_code", "")
    mod_def = modalities.get(modality_code, {})
    modality_display = mod_def.get(f"display_{lang}") or mod_def.get("display_en", modality_code)
    return {
        "uid": _o(series, "series_uid", ""),
        "number": _o(series, "series_number", 1),
        "modality": {
            "system": get_system_uri("dicom-modality"),
            "code": modality_code,
            "display": modality_display,
        },
        "numberOfInstances": _o(series, "instance_count", 0),
        "description": _o(series, "description", ""),
        "bodySite": {
            "system": snomed_system,
            "code": body_site_snomed,
            "display": body_site_display,
        },
    }
