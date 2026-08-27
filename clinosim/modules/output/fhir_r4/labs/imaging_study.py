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
from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
from clinosim.modules.output.fhir_r4.encounters.encounter import encounter_ref
from clinosim.modules.output.fhir_r4.labs.service_request import _resolve_service_request_id
from clinosim.modules.output.fhir_r4.lib.common import BundleContext, to_fhir_datetime
from clinosim.modules.output.fhir_r4.lib.ids import (
    derive_opaque_id,
    structural_key_system,
    wrap_as_identifier,
)

# Writer-owned constant — DICOM/FHIR standard URI for DICOM Study UID.
DICOM_UID_SYSTEM = "urn:dicom:uid"


# === Issue #854 Bucket B (PR-imaging-study): opaque ImagingStudy.id ===
# Same pattern as PR #357 / #863 / #867 / #868 / #869 / #878 / #879 /
# #880 / #881 / #882 / #883 / #884. The CIF-side `study.study_id`
# retains the pre-#854 shape `imgst-{encounter_id}-{idx}` (referenced
# elsewhere via `f"ImagingStudy/{study_id}"`, and by the parallel
# `report.report_id = imgrpt-{encounter_id}-{idx}` for 1:1 pairing with
# radiology DR); the FHIR-side ImagingStudy.id becomes opaque per Issue
# #854. Structural key = pre-#854 body without the `imgst-` prefix,
# preserved on `identifier[]` for round-trip.
IMAGING_STUDY_KEY_SYSTEM = structural_key_system("imaging-study-key")


def _resolve_imaging_study_id(structural_key: str) -> str:
    """Return the opaque FHIR ImagingStudy.id from a structural key.

    Shape: ``imgst-{sha256(structural_key)[:12]}`` = 18 chars, fixed.

    Structural key = CIF-side ``study_id`` stripped of its ``imgst-``
    prefix (i.e. ``{encounter_id}-{idx}``). Every ImagingStudy
    reference site (``DR.imagingStudy[]``, ``DR.media[].link``) that
    used to inline ``f"ImagingStudy/{study_id}"`` now derives the id
    via this resolver so byte-consistency is preserved by construction.
    """
    return derive_opaque_id(IMAGING_STUDY_ID_PREFIX, structural_key)


def imaging_study_id_for_cif_study_id(cif_study_id: str) -> str:
    """Convenience wrapper: opaque ImagingStudy.id from CIF-side ``study_id``.

    Every consumer that has a CIF ``study_id`` (which is
    ``imgst-{enc}-{idx}``) can call this to obtain the FHIR
    ImagingStudy.id — the CIF prefix is stripped, then the body is
    hashed under the same ``imgst-`` prefix.
    """
    key = (
        cif_study_id.removeprefix(IMAGING_STUDY_ID_PREFIX)
        if cif_study_id.startswith(IMAGING_STUDY_ID_PREFIX)
        else cif_study_id
    )
    return _resolve_imaging_study_id(key)


# Re-export so readers can import from this module or the canonical owner.
__all__ = [
    "IMAGING_STUDY_ID_PREFIX",
    "IMAGING_STUDY_KEY_SYSTEM",
    "ENDPOINT_ID_PREFIX",
    "DICOM_UID_SYSTEM",
    "_bb_imaging_studies",
    "_resolve_imaging_study_id",
    "imaging_study_id_for_cif_study_id",
]


def _isoformat_or_str(dt: Any) -> str:
    """Convert datetime to ISO-8601 string; passthrough for str; empty for None.

    (FP-UNIFY-2 completion): delegates to the shared
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
                # Issue #872: localize the CIF-canonical EN chief-complaint to
                # JA on JP output. No-op on US output. Unknown-in-dict values
                # pass through unchanged (preserves the 1,127 already-JA
                # records from the 2026-08-26 deploy verify).
                _enc_reason_by_id[_eid] = [{"text": _localize_chief_complaint(_cc, lang)}]
    return [_build_imaging_study(s, lang, _enc_reason_by_id) for s in studies]


def _build_imaging_study(
    study: Any, lang: str, enc_reason_by_id: dict[str, list[dict]] | None = None
) -> dict[str, Any]:  # noqa: E501
    """Build one FHIR R4 ImagingStudy resource from an ImagingStudyRecord.

    cycle 8 拡張(案 D):stub-only ImagingStudy(modality/body_site
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

    # Issue #854 Bucket B (PR-imaging-study): opaque ImagingStudy.id.
    # Strip the CIF `imgst-` prefix from `study.study_id` to obtain the
    # structural key, then hash. The pre-existing DICOM_UID_SYSTEM
    # identifier stays first; the structural-key round-trip identifier
    # is appended so consumers can recover the CIF study_id verbatim.
    _cif_study_id = _o(study, "study_id", "") or ""
    _study_structural_key = (
        _cif_study_id.removeprefix(IMAGING_STUDY_ID_PREFIX)
        if _cif_study_id.startswith(IMAGING_STUDY_ID_PREFIX)
        else _cif_study_id
    )
    res: dict[str, Any] = {
        "resourceType": "ImagingStudy",
        "id": _resolve_imaging_study_id(_study_structural_key),
        "identifier": [
            {
                "system": DICOM_UID_SYSTEM,
                "value": f"urn:oid:{_o(study, 'study_instance_uid', '')}",
            },
            wrap_as_identifier(_study_structural_key, IMAGING_STUDY_KEY_SYSTEM),
        ],
        "status": _o(study, "status", "available"),
        "subject": patient_ref(_o(study, "patient_id", "")),
        "encounter": encounter_ref(_o(study, "encounter_id", "")),
        # Issue #854 Bucket A: SR.id is now opaque, so basedOn goes through
        # the SAME resolver the SR builder uses (structural key = order_id
        # for imaging orders — 1 Order = 1 SR).
        "basedOn": [{"reference": f"ServiceRequest/{_resolve_service_request_id(_o(study, 'order_id', ''))}"}],
        "numberOfSeries": len(series_resources),
        "numberOfInstances": total_instances,
    }
    # #299:FHIR R4 "配列は空にできません" 制約 — modality / series
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
            # Issue #779: ImagingStudy.description = clinical procedure name.
            # Pre-fix behaviour: 0/90 studies (JP p=500) had a populated
            # description; consumer viewers could only fall back to DICOM
            # modality codes to label the study. `_proc_display` here is the
            # authored language-scoped procedure name from body_sites.yaml
            # (`display_ja` / `display_en`) — the same string that
            # DiagnosticReport.code.text carries — so populating it makes the
            # two resources internally consistent.
            if _proc_display:
                res["description"] = _proc_display
            if _proc_loinc:
                # #319 JP output は procedureCode 要素を完全省略。
                # JP_ImagingStudy_Radiology profile は procedureCode binding
                # strength "required" + valueSet =
                # http://playbook.radlex.org/playbook/SearchRadlexAction
                # (RadLexPlaybook)。#315 で text-only emit を
                # 試みたが v6.1 で regression(571→589)、"コードが提供
                # されていません" error 発火。
                #
                # 【新規教訓】FHIR R4 required binding は text-only
                # 回避不可 — text は補助表示のためのフィールドで、required
                # binding の充足条件に含まれない。VS が空でよい唯一の方法は
                # 要素自体を省略すること。
                #
                # 検査内容は関連 resource で追跡可能:
                # - series[].description(view label)
                # - DiagnosticReport.code(18748-4、#302 済)
                # - ServiceRequest.code(SR builder の LOINC 検査コード)
                #
                # US path は LOINC coding + text 両方 emit(US profile は
                # 該当 binding なし、情報保持)。
                if lang != "ja":
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

    # Issue #822 (N-9) fallback: stub-only studies (metadata inference
    # failed → no body_sites lookup possible) still need an informative
    # description so consumer UIs don't default it to the generic
    # "画像検査" placeholder that reads as duplication. The enricher
    # populates `study.description` from `order.display_name` in the
    # stub-only branch specifically for this purpose. Only applies when
    # the primary body_sites lookup did not already set description.
    if "description" not in res:
        _stub_desc = _o(study, "description", "") or ""
        if _stub_desc:
            # Issue #862: the CIF stub description is an English exam name
            # (`FAST_Ultrasound`, `ECG_12lead`, `Carotid_ultrasound`, ...)
            # sourced from disease-YAML `- {test: "..."}` items. On JP output,
            # 22.4% of ImagingStudy resources (1,060 / 4,735) leaked the raw
            # English form because `body_sites` lookup was a miss and no
            # localization applied. Look up the JA form in `drug_names_ja.yaml`
            # (the shared localization dict — see the "Imaging exam names"
            # section); normalize `_` → ` ` first to match the space-keyed
            # yaml entries. Passthrough on US (`lang != "ja"`) and on any
            # unknown key preserves the original English form.
            if lang == "ja":
                _stub_desc = _localize_imaging_exam_name(_stub_desc)
            res["description"] = _stub_desc
    return res


def _localize_imaging_exam_name(exam_name: str) -> str:
    """Return the JA form of an English CIF imaging exam name (Issue #862).

    Normalizes underscores to spaces (matching how the CIF disease-YAML
    ``- {test: "FAST_Ultrasound"}`` shape maps to the space-keyed
    ``drug_names_ja.yaml`` entries), then does a case-insensitive exact-match
    lookup. Unknown keys pass through as-is so the JA-locale surface
    degrades gracefully to the CIF English name instead of a placeholder.
    """
    from clinosim.locale.loader import load_drug_names_ja

    ja_dict = load_drug_names_ja()
    normalized = exam_name.replace("_", " ")
    return ja_dict.get(normalized.lower(), exam_name)


# Issue #872 — chief-complaint text (Encounter.chief_complaint) leaks in English
# on ImagingStudy.reasonCode.text when the disease-YAML authors chief_complaint
# as a plain-EN string (no per-language dict). 3,608 / 4,735 ImagingStudy
# reasonCode.text (76.2 %) shipped as English on JP p=10000 s500 deploy
# (2026-08-26). This dict covers the 30 distinct EN vignette phrases observed
# in that deploy. Unknown values pass through unchanged so this is safe against
# future disease additions.
#
# Long-term the disease YAMLs should author `chief_complaint: {en, ja}` (dict
# form) so `_disease_chief_complaint_ja` populates `Encounter.chief_complaint_ja`
# and the emit path can prefer it. That is out of scope for this PR — this dict
# is the pragmatic emit-time bridge until the CIF-side authoring is completed.
_CHIEF_COMPLAINT_JA: dict[str, str] = {
    "Sudden onset weakness, speech difficulty, facial droop": "突然発症の脱力・構音障害・顔面麻痺",
    "Dyspnea on exertion, orthopnea, lower extremity edema": "労作時呼吸困難・起坐呼吸・下腿浮腫",
    "Worsening dyspnea, increased sputum production, wheezing": "呼吸困難増悪・喀痰増加・喘鳴",
    "Fever, dysuria, flank pain": "発熱・排尿痛・側腹部痛",
    "Fever, cough, dyspnea": "発熱・咳嗽・呼吸困難",
    "Chest pain, diaphoresis, dyspnea": "胸痛・発汗・呼吸困難",
    "Severe wheezing, dyspnea, use of accessory muscles": "高度喘鳴・呼吸困難・呼吸補助筋使用",
    "Nausea, vomiting, abdominal pain, polyuria, altered consciousness": "悪心・嘔吐・腹痛・多尿・意識障害",
    "Hip pain after fall, unable to walk": "転倒後の股関節痛・歩行不能",
    "High fever, myalgia, cough, fatigue": "高熱・筋肉痛・咳嗽・倦怠感",
    "Fever, altered mental status, hypotension": "発熱・意識障害・低血圧",
    "Palpitations, dyspnea, dizziness, chest discomfort": "動悸・呼吸困難・めまい・胸部不快感",
    "Acute dyspnea, pleuritic chest pain, tachycardia": "急性呼吸困難・胸膜痛・頻脈",
    "Fall from height at work site, multiple trauma": "作業現場での転落・多発外傷",
    "Acute back pain after minimal trauma, worse with movement": "軽微外傷後の急性腰背部痛・体動時増悪",
    "Severe epigastric pain radiating to back, nausea, vomiting": "背部放散性の強い心窩部痛・悪心・嘔吐",
    "Decreased urine output, edema, nausea, confusion": "尿量減少・浮腫・悪心・意識混濁",
    "Hematemesis, melena, dizziness, syncope": "吐血・下血・めまい・失神",
    "Unilateral leg swelling, pain, warmth": "片側下肢腫脹・疼痛・熱感",
    "Sudden severe headache, vomiting, altered consciousness": "突然の激しい頭痛・嘔吐・意識障害",
    "Cough, fever, dyspnea after witnessed aspiration event": "誤嚥後の咳嗽・発熱・呼吸困難",
    "Displaced distal radius fracture requiring ORIF": "ORIFを要する転位型橈骨遠位端骨折",
    "Right upper quadrant pain, fever, Murphy's sign positive": "右上腹部痛・発熱・Murphy徴候陽性",
    "Abdominal pain, vomiting, constipation, abdominal distension": "腹痛・嘔吐・便秘・腹部膨満",
    "Erythema, warmth, swelling of affected limb, fever": "患肢の発赤・熱感・腫脹・発熱",
    "Major trauma, motor vehicle accident, multiple injuries": "交通事故による重症外傷・多発損傷",
    "Right lower quadrant pain, nausea, fever": "右下腹部痛・悪心・発熱",
    "Industrial hand crush injury with possible amputation": "労災による手部挫滅損傷・切断疑い",
    "Abdominal distension, jaundice, confusion, hematemesis": "腹部膨満・黄疸・意識混濁・吐血",
    "Altered consciousness after head trauma, progressive deterioration": "頭部外傷後の意識障害・進行性増悪",
}


def _localize_chief_complaint(text: str, lang: str) -> str:
    """Return the JA form of an English CIF chief-complaint (Issue #872).

    Only invoked on JP output. Case-sensitive exact-match against
    ``_CHIEF_COMPLAINT_JA``; unknown values pass through unchanged so
    JA-authored chief complaints (the 1,127 / 4,735 records already in JA
    per the 2026-08-26 deploy) are preserved as-is, and new EN phrases that
    the dict does not yet cover degrade gracefully to the CIF text rather
    than a placeholder. US output is a no-op.
    """
    if lang != "ja" or not text:
        return text
    return _CHIEF_COMPLAINT_JA.get(text, text)


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
