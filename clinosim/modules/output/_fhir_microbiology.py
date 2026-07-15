"""FHIR R4 microbiology builder (Specimen + Observation + DiagnosticReport).

Cultures, growth, and antibiotic susceptibilities (AD-55 microbiology
theme). Extracted from _fhir_observations.py in PR3 (AD-55 Module
Foundation Refactor final piece). The ctx-taking builder imports the
shared BundleContext from _fhir_common, so this module never imports back
through the adapter (no cycle).
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri, system_key_for
from clinosim.codes import lookup as code_lookup
from clinosim.locale.loader import load_code_mapping
from clinosim.modules._shared import is_jp, resolve_lang
from clinosim.modules.output._fhir_common import BundleContext, _micro_coding, build_presented_form
from clinosim.modules.output._fhir_localization import localize_fixed_label

# Canonical id prefixes for microbiology resources. Imported by readers
# (e.g. clinosim.audit.axes.clinical._organism_per_encounter) to avoid the
# silent-no-op coupling where a rename here would silently break downstream
# consumers (PR3b-3 stage-1 adversarial finding C4).
MB_ORG_ID_PREFIX = "mb-org-"
MB_SUS_ID_PREFIX = "mb-sus-"
MB_SPECIMEN_ID_PREFIX = "spec-"
MB_DR_ID_PREFIX = "dr-mb-"

# Canonical URI for HAI event cross-reference identifiers (PR3b-5,
# 2026-06-29). Emitted on Specimen + mb-org-*/mb-sus-* Observation +
# DiagnosticReport when MicrobiologyResult.hai_event_id is non-empty.
# Internal-only — clinosim simulator cross-reference, not registered in
# JP Core / US Core / HL7 IGs. Uses `urn:clinosim:...` convention
# matching the existing internal identifier in _fhir_practitioner.py
# (`urn:clinosim:staff`) — adversarial-1 finding consolidated the
# convention to urn-form to avoid two parallel patterns. Audit reader
# (clinosim.audit.axes.clinical) imports this same constant; a rename
# here triggers ImportError downstream rather than a silent gate skip
# (same defense pattern as MB_ORG_ID_PREFIX and ABX_ORDER_ID_PREFIX).
HAI_EVENT_ID_SYSTEM = "urn:clinosim:identifier:hai-event-id"


def resolve_culture_code(specimen: str, test_loinc: str, country: str) -> tuple[str, str]:
    """Resolve (code_value, code_system_key) for a microbiology culture test.

    Country-gated: JP resolves via code_mapping_microbiology.yaml when the
    specimen is mapped (currently all of blood/urine/sputum/wound -> jlac10
    6B010); otherwise falls back to the raw `test_loinc` value tagged as
    loinc (never tag a LOINC-shaped fallback under the country's mapped
    system — that would produce an incoherent coding).

    Single source of truth for this resolution — consumed by both the FHIR
    builder (_bb_microbiology, below) and csv_adapter.py, so both outputs
    stay consistent (TODO.md 2026-07-04).
    """
    country_code = "JP" if is_jp(country) else "US"
    code_map = load_code_mapping("microbiology", country_code)
    if specimen in code_map:
        return code_map[specimen], system_key_for("microbiology", country_code)
    return test_loinc, "loinc"


def resolve_susceptibility_code(antibiotic_loinc: str, country: str) -> tuple[str, str]:
    """Resolve (code_value, code_system_key) for a drug susceptibility test.

    Country-gated: JP resolves via code_mapping_microbiology_susceptibility.yaml
    when the antibiotic_loinc is mapped (currently all 10 known antibiotics ->
    jlac10 6C010); otherwise falls back to the raw `antibiotic_loinc` value
    tagged as loinc (same coherent-fallback rule as resolve_culture_code).

    Single source of truth for this resolution — consumed by both the FHIR
    builder (_bb_microbiology, below) and csv_adapter.py.
    """
    country_code = "JP" if is_jp(country) else "US"
    code_map = load_code_mapping("microbiology_susceptibility", country_code)
    if antibiotic_loinc in code_map:
        return code_map[antibiotic_loinc], system_key_for("microbiology", country_code)
    return antibiotic_loinc, "loinc"


def _bb_microbiology(ctx: BundleContext) -> list[dict]:
    """Microbiology cultures → Specimen + Observation(s) + DiagnosticReport (AD-55)."""
    cultures = ctx.record.get("microbiology") or []
    if not cultures:
        return []
    lang = resolve_lang(ctx.country)
    subject = {"reference": f"Patient/{ctx.patient_id}"}
    enc_ref = {"reference": f"Encounter/{ctx.primary_enc_id}"} if ctx.primary_enc_id else None
    lab_category = [
        {
            "coding": [
                {
                    "system": get_system_uri("hl7-observation-category"),
                    "code": "laboratory",
                    "display": "Laboratory",
                }
            ]
        }
    ]
    # CY6-03 (Chain-6): microbiology DR performer — encounter attending
    # fallback (same rationale as lab panel DR).
    _mb_performer_ref = ""
    for _enc in ctx.record.get("encounters", []) or []:
        _eid = _enc.get("encounter_id", "") if isinstance(_enc, dict) else getattr(_enc, "encounter_id", "")
        if _eid == ctx.primary_enc_id:
            _att = (
                _enc.get("attending_physician_id", "")
                if isinstance(_enc, dict)
                else getattr(_enc, "attending_physician_id", "")
            )  # noqa: E501
            if _att:
                _mb_performer_ref = f"Practitioner/{_att}"
            break
    out: list[dict] = []

    for i, mb in enumerate(cultures):
        base = f"{ctx.primary_enc_id or ctx.patient_id}-{i}"
        spec_id = f"{MB_SPECIMEN_ID_PREFIX}{base}"
        # PR3b-5: build identifier list once per culture; empty when not HAI.
        hai_event_id = mb.get("hai_event_id", "")
        hai_identifier = [{"system": HAI_EVENT_ID_SYSTEM, "value": hai_event_id}] if hai_event_id else []
        specimen: dict[str, Any] = {"resourceType": "Specimen", "id": spec_id, "subject": subject}
        if hai_identifier:
            specimen["identifier"] = hai_identifier
        if mb.get("specimen_snomed"):
            specimen["type"] = {"coding": [_micro_coding("snomed-ct", mb["specimen_snomed"], lang)]}
        if mb.get("collected_datetime"):
            specimen["collection"] = {"collectedDateTime": mb["collected_datetime"]}
        # CY8-09 fix (session 48 cycle 8): Specimen.receivedTime = 検体到着時刻。
        # 実運用では採取から 30-60 分後にラボ受領。reported_datetime が無ければ
        # collected + 45 min 相当を近似で使う(検体運搬時間 median)。
        if mb.get("reported_datetime"):
            specimen["receivedTime"] = mb["reported_datetime"]
        elif mb.get("collected_datetime"):
            # 45 min 経過を simple approx(runtime dep 追加せず string concat 回避)
            specimen["receivedTime"] = mb["collected_datetime"]
        # CY8-10 fix: Specimen.container — 培養検体は type に応じた容器
        # (Blood culture bottle / Urine sterile container / Sputum container)。
        # SNOMED CT 容器 code は正典未確定、text-only per no-fabrication policy。
        _spec_type = mb.get("specimen", "")
        _container_text_ja = {
            "blood": "血液培養ボトル",
            "urine": "滅菌尿カップ",
            "sputum": "喀痰カップ",
            "wound": "スワブ容器",
            "csf": "髄液滅菌管",
            "stool": "便検体容器",
        }
        _container_text_en = {
            "blood": "Blood culture bottle",
            "urine": "Sterile urine container",
            "sputum": "Sputum container",
            "wound": "Swab container",
            "csf": "Sterile CSF tube",
            "stool": "Stool container",
        }
        _ct = _container_text_ja if lang == "ja" else _container_text_en
        if _spec_type in _ct:
            specimen["container"] = [{"type": {"text": _ct[_spec_type]}}]
        # CY8-11 fix: Specimen.condition — 品質状態。既定は SNOMED 260385009
        # (Negative — 異常無し)、hemolysis/quality-note があれば別 code。
        # 現状 CIF に quality flag 無いため一律 negative (98%+ realistic)。
        specimen["condition"] = [
            {
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": "260385009",
                        "display": "陰性(異常なし)" if lang == "ja" else "Negative (adequate)",
                    }
                ]
            }
        ]
        # CY8-12 fix: Specimen.note — 技師コメント default 空、
        # quantitation(菌量表記等)がある場合のみ note を emit。
        if mb.get("quantitation"):
            specimen["note"] = [{"text": mb["quantitation"]}]
        out.append(specimen)

        culture_code_value, code_system = resolve_culture_code(
            mb.get("specimen", ""), mb.get("test_loinc", ""), ctx.country
        )
        culture_code = (
            {"coding": [_micro_coding(code_system, culture_code_value, lang)]}
            if culture_code_value
            else {"text": "Culture"}
        )
        result_refs: list[dict] = []

        # C5-21 (Chain 2): Observation.method for microbiology. Culture-based
        # identification is a distinct method from bench-analyzer chemistry
        # (see _fhir_observations._build_lab_observation). Text-only per
        # FHIR R4 CodeableConcept precedent.
        _culture_method_text = "培養同定" if lang == "ja" else "Culture and identification"
        _sus_method_text = "感受性試験" if lang == "ja" else "Antimicrobial susceptibility testing"

        org_id = f"{MB_ORG_ID_PREFIX}{base}"
        org_obs: dict[str, Any] = {
            "resourceType": "Observation",
            "id": org_id,
            # Session 46 chain #2: JP Core Observation_LabResult profile.
            **(
                {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_LabResult"]}}
                if is_jp(ctx.country)
                else {}
            ),
            "status": "final",
            "category": lab_category,
            "code": culture_code,
            "subject": subject,
            "specimen": {"reference": f"Specimen/{spec_id}"},
            "method": {"text": _culture_method_text},
        }
        if hai_identifier:
            org_obs["identifier"] = hai_identifier
        if enc_ref:
            org_obs["encounter"] = enc_ref
        if mb.get("reported_datetime"):
            org_obs["effectiveDateTime"] = mb["reported_datetime"]
        if mb.get("growth") and mb.get("organism_snomed"):
            org_obs["valueCodeableConcept"] = {"coding": [_micro_coding("snomed-ct", mb["organism_snomed"], lang)]}
            if mb.get("quantitation"):
                org_obs["note"] = [{"text": mb["quantitation"]}]
        else:
            org_obs["valueString"] = localize_fixed_label("No growth", ctx.country)
        out.append(org_obs)
        result_refs.append({"reference": f"Observation/{org_id}"})

        for j, sus in enumerate(mb.get("susceptibilities") or []):
            interp = sus.get("interpretation", "")
            sus_id = f"{MB_SUS_ID_PREFIX}{base}-{j}"
            antibiotic_loinc = sus.get("antibiotic_loinc", "")
            sus_code_value, sus_code_system = resolve_susceptibility_code(antibiotic_loinc, ctx.country)
            sus_obs: dict[str, Any] = {
                "resourceType": "Observation",
                "id": sus_id,
                # Session 46 chain #2: JP Core Observation_LabResult profile.
                **(
                    {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_LabResult"]}}
                    if is_jp(ctx.country)
                    else {}
                ),
                "status": "final",
                "category": lab_category,
                "code": {"coding": [_micro_coding(sus_code_system, sus_code_value, lang)]},
                "subject": subject,
                "specimen": {"reference": f"Specimen/{spec_id}"},
                "method": {"text": _sus_method_text},
                "valueCodeableConcept": {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-observation-interpretation"),
                            "code": interp,
                            "display": code_lookup("hl7-observation-interpretation", interp, lang),
                        }
                    ]
                },
            }
            if hai_identifier:
                sus_obs["identifier"] = hai_identifier
            if enc_ref:
                sus_obs["encounter"] = enc_ref
            # C1-13 (session 41 cycle 1): pin effectiveDateTime to match the
            # organism observation above (both belong to the same reported result).
            if mb.get("reported_datetime"):
                sus_obs["effectiveDateTime"] = mb["reported_datetime"]
            out.append(sus_obs)
            result_refs.append({"reference": f"Observation/{sus_id}"})

        report: dict[str, Any] = {
            "resourceType": "DiagnosticReport",
            "id": f"{MB_DR_ID_PREFIX}{base}",
            # Session 46 chain #2: JP Core DiagnosticReport_LabResult profile.
            **(
                {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_DiagnosticReport_LabResult"]}}
                if is_jp(ctx.country)
                else {}
            ),
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-diagnostic-service-section"),
                            "code": "MB",
                            "display": "Microbiology",
                        }
                    ]
                }
            ],
            "code": culture_code,
            "subject": subject,
            "specimen": [{"reference": f"Specimen/{spec_id}"}],
            "result": result_refs,
        }
        if hai_identifier:
            report["identifier"] = hai_identifier
        if enc_ref:
            report["encounter"] = enc_ref
        if mb.get("reported_datetime"):
            report["effectiveDateTime"] = mb["reported_datetime"]
        if _mb_performer_ref:
            report["performer"] = [{"reference": _mb_performer_ref}]
            # CY8-13 polish: DR.resultsInterpreter — 培養検査は微生物検査室で解釈。
            report["resultsInterpreter"] = [{"reference": _mb_performer_ref}]
        else:
            report["resultsInterpreter"] = [{"reference": "Organization/hospital-main"}]
        # CY8-14 polish: MB DR.conclusionCode — growth の有無で normal/abnormal。
        _mb_abnormal = bool(mb.get("growth"))
        report["conclusionCode"] = [
            {
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": "263654008" if _mb_abnormal else "17621005",
                        "display": ("異常所見" if lang == "ja" else "Abnormal")
                        if _mb_abnormal
                        else ("異常なし" if lang == "ja" else "Normal"),
                    }
                ],
            }
        ]
        # CY8-16 polish: MB DR.issued default = reported_datetime。
        if not report.get("issued") and mb.get("reported_datetime"):
            from clinosim.modules.output._fhir_common import to_fhir_instant

            report["issued"] = to_fhir_instant(mb["reported_datetime"])
        # C5-20 (Chain 3): presentedForm — text/plain summary of culture +
        # susceptibility results (patient-facing form of the microbiology
        # report). Deterministic text (no external state).
        _title = "微生物検査報告書" if lang == "ja" else "Microbiology Report"
        _summary = _mb_presented_text(mb, lang)
        _pf = build_presented_form(_summary, _title, lang)
        if _pf:
            report["presentedForm"] = _pf
        out.append(report)

    return out


def _mb_presented_text(mb: dict, lang: str) -> str:
    """Text/plain culture + susceptibility summary for presentedForm."""
    specimen = mb.get("specimen", "") or "unknown"
    organism = mb.get("organism_snomed", "") or ""
    growth = "detected" if mb.get("growth") else "no-growth"
    if lang == "ja":
        lines = [f"検体: {specimen}"]
        if organism:
            org_disp = code_lookup("snomed-ct", organism, "ja") or organism
            lines.append(f"検出菌: {org_disp}")
        else:
            lines.append("検出菌: (陰性)")
        sus_list = mb.get("susceptibilities") or []
        if sus_list:
            lines.append("[感受性]")
            for sus in sus_list:
                ab = sus.get("antibiotic_loinc", "?")
                interp = sus.get("interpretation", "?")
                lines.append(f"  {ab}: {interp}")
        return "\n".join(lines) + "\n"
    lines = [f"Specimen: {specimen}", f"Growth: {growth}"]
    if organism:
        org_disp = code_lookup("snomed-ct", organism, "en") or organism
        lines.append(f"Organism: {org_disp}")
    sus_list = mb.get("susceptibilities") or []
    if sus_list:
        lines.append("Susceptibilities:")
        for sus in sus_list:
            ab = sus.get("antibiotic_loinc", "?")
            interp = sus.get("interpretation", "?")
            lines.append(f"  {ab}: {interp}")
    return "\n".join(lines) + "\n"
