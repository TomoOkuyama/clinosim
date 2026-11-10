"""FHIR R4 microbiology builder (Specimen + Observation + DiagnosticReport).

Cultures, growth, and antibiotic susceptibilities (AD-55 microbiology
theme). Extracted from _fhir_observations.py in PR3 (AD-55 Module
Foundation Refactor final piece). The ctx-taking builder imports the
shared BundleContext from _fhir_common, so this module never imports back
through the adapter (no cycle).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from clinosim.codes import display as registry_display
from clinosim.codes import get_system_uri, system_key_for
from clinosim.codes import lookup as code_lookup
from clinosim.codes.loinc import loinc_for
from clinosim.codes.snomed_concepts import FINDING_ABNORMAL, FINDING_NORMAL, NO_GROWTH
from clinosim.countries import country_code as _country_code
from clinosim.countries import lang_for
from clinosim.locale.i18n import t
from clinosim.locale.loader import load_code_mapping, load_narrative_labels, resolve_localized_display
from clinosim.modules._shared import get_attr_or_key, is_jp
from clinosim.modules.observation.engine import canonical_lab_name
from clinosim.modules.observation.microbiology import (
    culture_order_match_window_hours,
    culture_order_names,
    specimen_transport_minutes,
)
from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
from clinosim.modules.output.fhir_r4.encounters.encounter import encounter_ref
from clinosim.modules.output.fhir_r4.labs.diagnostic_report import (
    MB_DR_KEY_SYSTEM,
    _resolve_mb_dr_id,
)
from clinosim.modules.output.fhir_r4.labs.service_request import build_panel_counter, order_to_sr_id
from clinosim.modules.output.fhir_r4.lib.common import build_presented_form, dual_slot_concept, system_coding
from clinosim.modules.output.fhir_r4.lib.context import BundleContext
from clinosim.modules.output.fhir_r4.lib.ids import (
    derive_opaque_id,
    structural_key_system,
    wrap_as_identifier,
)
from clinosim.modules.output.fhir_r4.lib.jp_profiles import JP_OBSERVATION_LAB_RESULT_PROFILE
from clinosim.modules.output.fhir_r4.lib.localization import localize_fixed_label
from clinosim.modules.output.fhir_r4.post_process.specimen import (
    SPECIMEN_KEY_SYSTEM,
    _resolve_specimen_id,
)
from clinosim.timeutil import parse_iso_datetime
from clinosim.types.encounter import OrderType

# Canonical id prefixes for microbiology resources. Imported by readers
# (e.g. clinosim.audit.axes.clinical._organism_per_encounter) to avoid the
# silent-no-op coupling where a rename here would silently break downstream
# consumers (PR3b-3 stage-1 adversarial finding C4).
MB_ORG_ID_PREFIX = "mb-org-"
MB_SUS_ID_PREFIX = "mb-sus-"
# `MB_DR_ID_PREFIX` retired in PR-diagnostic-report (#884): the mb DR
# emit now funnels through `_resolve_mb_dr_id` in
# `labs/diagnostic_report.py` (canonical owner). Downstream consumers
# that need the mb DR prefix can import `MB_DR_ID_PREFIX_FHIR` from
# `labs/diagnostic_report.py`.
# `MB_SPECIMEN_ID_PREFIX` retired in PR-specimen (#882): the Specimen.id
# emit now funnels through `SPECIMEN_ID_PREFIX` from
# `post_process/specimen.py`. Downstream consumers that need to identify a
# Specimen by id prefix use that constant (or the shared resolver +
# `SPECIMEN_KEY_SYSTEM` identifier lookup).

# === Issue #854 Bucket A row 4 (PR-obs-microbiology): opaque mb-org / mb-sus ids ===
# Same pattern as PR #357 / #863 / #867 / #868 / #869 / #878 / #879 / #880.
#
# mb-org (organism isolate) and mb-sus (per-antibiotic susceptibility)
# Observations both carry a compound id embedding the encounter + culture
# index. mb-sus additionally embeds the per-antibiotic index. Post-#854:
#     mb-org-<12hex> (19 chars, fixed)
#     mb-sus-<12hex> (19 chars, fixed)
#
# Cross-reference: DR.result[] references both by opaque id — funneled
# through the same resolver so the reference edge stays byte-consistent
# with the writer by construction (PR-90 silent-no-op defense).
#
# Structural keys = pre-#854 id bodies (without prefix):
#     mb-org: ``{enc or patient_id}-{i}``
#     mb-sus: ``{enc or patient_id}-{i}-{j}``  where j is the 0-based
#             index into the per-culture ``susceptibilities`` list.
#
# PUBLIC constants so downstream readers (identifier[] round-trip, future
# audit tooling) can import them.
MB_ORG_KEY_SYSTEM = structural_key_system("mb-organism-observation-key")
MB_SUS_KEY_SYSTEM = structural_key_system("mb-susceptibility-observation-key")


def _resolve_mb_org_id(structural_key: str) -> str:
    return derive_opaque_id(MB_ORG_ID_PREFIX, structural_key)


def _resolve_mb_sus_id(structural_key: str) -> str:
    return derive_opaque_id(MB_SUS_ID_PREFIX, structural_key)


# JP Core DiagnosticReport_Microbiology profile constants (spec-pinned from
# fhir-jp-validator/jp_core/package/
# StructureDefinition-jp-diagnosticreport-microbiology.json).# chain #2 originally routed microbiology DRs through
# `JP_DiagnosticReport_LabResult` because Microbiology profile constraints
# had not been surveyed; verifies Microbiology's actual profile
# requirements are compatible with clinosim's existing MB emission shape and
# switches meta.profile accordingly. The Microbiology profile requires:
#   * `category:first.coding.code` fixedCode = `LP7819-8` on LOINC
#   * `code.coding` patternCodeableConcept containing
#     `{system: JP_DocumentCodes_CS, code: 18725-2}` ("微生物学的検査報告書")
JP_MB_DR_PROFILE_URI = "http://jpfhir.jp/fhir/core/StructureDefinition/JP_DiagnosticReport_Microbiology"
JP_MB_DR_CATEGORY_LOINC = "LP7819-8"
JP_MB_DR_CODE_CS = get_system_uri("jp-document-codes")
JP_MB_DR_CODE_VALUE = loinc_for("report", "microbiology")
JP_MB_DR_CODE_DISPLAY = registry_display("jp-document-codes", JP_MB_DR_CODE_VALUE, "ja") or ""

# Canonical URI for HAI event cross-reference identifiers (PR3b-5,
# 2026-06-29). Emitted on Specimen + mb-org-*/mb-sus-* Observation +
# DiagnosticReport when MicrobiologyResult.hai_event_id is non-empty.
# Internal-only — clinosim simulator cross-reference, not registered in
# JP Core / US Core / HL7 IGs. Uses `urn:clinosim:...` convention
# matching the existing internal identifier in fhir_r4/demographics/practitioner.py
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
    country_code = _country_code(country)
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
    country_code = _country_code(country)
    code_map = load_code_mapping("microbiology_susceptibility", country_code)
    if antibiotic_loinc in code_map:
        return code_map[antibiotic_loinc], system_key_for("microbiology", country_code)
    return antibiotic_loinc, "loinc"


def culture_orders_for(culture: Any, orders: list[Any]) -> list[Any]:
    """The lab orders a culture result reports (Issue #2585).

    The orders that request a culture of the result's specimen, in its
    encounter, drawn nearest its collection time (within the configured
    window). Every order of that draw is returned (two blood-culture sets are
    one draw). ``[]`` when no such order was placed.
    """
    names = culture_order_names(get_attr_or_key(culture, "specimen", "") or "")
    collected = parse_iso_datetime(get_attr_or_key(culture, "collected_datetime"))
    if not names or collected is None:
        return []
    enc_id = get_attr_or_key(culture, "encounter_id", "") or ""
    window = timedelta(hours=culture_order_match_window_hours())
    candidates: list[tuple[timedelta, datetime, Any]] = []
    for order in orders:
        if get_attr_or_key(order, "order_type") not in (OrderType.LAB, "lab"):
            continue
        if enc_id and get_attr_or_key(order, "encounter_id", "") != enc_id:
            continue
        if canonical_lab_name(get_attr_or_key(order, "display_name", "") or "") not in names:
            continue
        ordered = parse_iso_datetime(get_attr_or_key(order, "ordered_datetime"))
        if ordered is None or abs(ordered - collected) > window:
            continue
        candidates.append((abs(ordered - collected), ordered, order))
    if not candidates:
        return []
    nearest = min(candidates, key=lambda c: c[0])[1]
    return [order for _gap, ordered, order in candidates if ordered == nearest]


def culture_reported_order_ids(record: Any) -> set[str]:
    """Order ids of the culture orders some culture result reports."""
    orders = get_attr_or_key(record, "orders", []) or []
    return {
        get_attr_or_key(o, "order_id", "")
        for culture in get_attr_or_key(record, "microbiology", []) or []
        for o in culture_orders_for(culture, orders)
    }


def _bb_microbiology(ctx: BundleContext) -> list[dict]:
    """Microbiology cultures → Specimen + Observation(s) + DiagnosticReport (AD-55)."""
    cultures = ctx.record.get("microbiology") or []
    if not cultures:
        return []
    lang = lang_for(ctx.country)
    subject = patient_ref(ctx.patient_id)
    enc_ref = encounter_ref(ctx.primary_enc_id) if ctx.primary_enc_id else None
    # p=500 review finding (session 89): populate `.text` so the JP
    # post-process normalizer (`_normalize_jp_observation_category`)
    # carries a JP-language label forward on mb-org Observations. The
    # normalizer swaps coding.system to JP_SimpleObservationCategory_CS
    # (which by design omits `.display`) and copies any `.text` hint from
    # the original category — without a text hint here, mb-org
    # Observations end up with a bare `{system, code}` category and no
    # human-readable label at all.
    lab_category = [dual_slot_concept("hl7-observation-category", "laboratory", lang_for(ctx.country))]
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
    orders = ctx.record.get("orders", []) or []
    panel_counter = build_panel_counter(
        [o for o in orders if get_attr_or_key(o, "order_type") in (OrderType.LAB, "lab")]
    )

    for i, mb in enumerate(cultures):
        base = f"{ctx.primary_enc_id or ctx.patient_id}-{i}"
        # Issue #2585: the culture order(s) this result reports.
        based_on = [
            {"reference": f"ServiceRequest/{sid}"}
            for sid in sorted({order_to_sr_id(o, panel_counter) for o in culture_orders_for(mb, orders)})
        ]
        # Issue #854 Bucket B (PR-specimen): opaque Specimen.id.
        # Structural key = pre-#854 id body (without ``spec-`` prefix) =
        # ``{enc or patient_id}-{i}``; identifier round-trip carries it
        # under :data:`SPECIMEN_KEY_SYSTEM`.
        _spec_structural_key = base
        spec_id = _resolve_specimen_id(_spec_structural_key)
        _spec_identifier = wrap_as_identifier(_spec_structural_key, SPECIMEN_KEY_SYSTEM)
        # PR3b-5: build identifier list once per culture; empty when not HAI.
        hai_event_id = mb.get("hai_event_id", "")
        hai_identifier = [{"system": HAI_EVENT_ID_SYSTEM, "value": hai_event_id}] if hai_event_id else []
        specimen: dict[str, Any] = {
            "resourceType": "Specimen",
            "id": spec_id,
            # Structural-key identifier always present; HAI identifier
            # prepended when present so PR3b-5 audit reader still finds
            # it via HAI_EVENT_ID_SYSTEM.
            "identifier": [*hai_identifier, _spec_identifier],
            "subject": subject,
        }
        if mb.get("specimen_snomed"):
            specimen["type"] = dual_slot_concept("snomed-ct", mb["specimen_snomed"], lang)
        if mb.get("collected_datetime"):
            specimen["collection"] = {"collectedDateTime": mb["collected_datetime"]}
        # Issue #3039: Specimen.receivedTime is the laboratory's receipt of
        # the specimen, a transport time after collection (not the report).
        _collected_dt = parse_iso_datetime(mb.get("collected_datetime"))
        if _collected_dt is not None:
            specimen["receivedTime"] = (_collected_dt + timedelta(minutes=specimen_transport_minutes())).isoformat()
        # CY8-10 fix: Specimen.container — 培養検体は type に応じた容器
        # (Blood culture bottle / Urine sterile container / Sputum container)。
        # SNOMED CT 容器 code は正典未確定、text-only per no-fabrication policy。
        _spec_type = mb.get("specimen", "")
        _ct_entry = load_narrative_labels().get("mb_container_text", {}).get(_spec_type)
        if _ct_entry:
            specimen["container"] = [{"type": {"text": resolve_localized_display(_ct_entry, lang, fallback="")}}]
        # CY8-11 fix: Specimen.condition — 品質状態。既定は SNOMED 260385009
        # (Negative — 異常無し)、hemolysis/quality-note があれば別 code。
        # 現状 CIF に quality flag 無いため一律 negative (98%+ realistic)。
        specimen["condition"] = [dual_slot_concept("snomed-ct", "260385009", lang)]
        # CY8-12 fix: Specimen.note — 技師コメント default 空、
        # quantitation(菌量表記等)がある場合のみ note を emit。
        if mb.get("quantitation"):
            specimen["note"] = [{"text": mb["quantitation"]}]
        out.append(specimen)

        culture_code_value, code_system = resolve_culture_code(
            mb.get("specimen", ""), mb.get("test_loinc", ""), ctx.country
        )
        # #321 JP_Observation_LabResult は code.text min=1 を要求。
        # coding が存在する場合も text を必ず併記(coding display を text に
        # コピー、無ければ "Culture" fallback)。
        if culture_code_value:
            _c = system_coding(code_system, culture_code_value, lang)
            culture_code = {
                "coding": [_c],
                "text": _c.get("display") or t("microbiology_fhir.culture", lang),
            }
        else:
            culture_code = {"text": t("microbiology_fhir.culture", lang)}
        result_refs: list[dict] = []

        # C5-21 (Chain 2): Observation.method for microbiology. Culture-based
        # identification is a distinct method from bench-analyzer chemistry
        # (see _fhir_observations._build_lab_observation). Text-only per
        # FHIR R4 CodeableConcept precedent.
        _culture_method_text = t("microbiology_fhir.culture_and_identification", lang)
        _sus_method_text = t("microbiology_fhir.antimicrobial_susceptibility_testing", lang)

        # Issue #854 Bucket A row 4 (PR-obs-microbiology): opaque mb-org id.
        _mb_org_structural_key = base
        org_id = _resolve_mb_org_id(_mb_org_structural_key)
        _mb_org_identifier = wrap_as_identifier(_mb_org_structural_key, MB_ORG_KEY_SYSTEM)
        org_obs: dict[str, Any] = {
            "resourceType": "Observation",
            "id": org_id,
            # chain #2: JP Core Observation_LabResult profile.
            **({"meta": {"profile": [JP_OBSERVATION_LAB_RESULT_PROFILE]}} if is_jp(ctx.country) else {}),
            "status": "final",
            "category": lab_category,
            "code": culture_code,
            "subject": subject,
            "specimen": {"reference": f"Specimen/{spec_id}"},
            "method": {"text": _culture_method_text},
        }
        # Structural-key identifier always present (Issue #854); HAI event
        # identifier prepended when the culture belongs to a HAI event so
        # PR3b-5's audit reader can still find it via HAI_EVENT_ID_SYSTEM.
        org_obs["identifier"] = [*hai_identifier, _mb_org_identifier]
        if based_on:
            org_obs["basedOn"] = based_on
        if enc_ref:
            org_obs["encounter"] = enc_ref
        # Issue #3039: a culture result is effective at the specimen
        # collection (the physiologically relevant time); the report time is
        # `issued`.
        _effective, _issued = _culture_times(mb)
        if _effective:
            org_obs["effectiveDateTime"] = _effective
        if _issued:
            org_obs["issued"] = _issued
        if mb.get("growth") and mb.get("organism_snomed"):
            # #321 JP_Observation_LabResult_eCS profile は
            # valueCodeableConcept.coding.display min=1 を要求(v6.1 で
            # 162 件 error)。SNOMED CT は English-only CS(tx-server の
            # JA display 未収録)のため JP output でも "en" で lookup する
            # (JA lookup → walker `_strip_japanese_display_on_english
            # _only_systems` により削除、validator が "display=0" を検出)。
            # lookup 失敗時は SNOMED code 自体を display fallback として
            # 使う(FHIR spec:code は不明でも display 必要)。
            _org_c = system_coding("snomed-ct", mb["organism_snomed"], "en")
            if not _org_c.get("display"):
                _org_c["display"] = mb["organism_snomed"]
            org_obs["valueCodeableConcept"] = {"coding": [_org_c]}
            if mb.get("quantitation"):
                org_obs["note"] = [{"text": mb["quantitation"]}]
        else:
            # Issue #2660: SNOMED CT 264868006 No growth (tx.fhir.org $lookup).
            org_obs["valueCodeableConcept"] = dual_slot_concept(
                "snomed-ct", NO_GROWTH, lang, text=localize_fixed_label("No growth", ctx.country)
            )
        out.append(org_obs)
        result_refs.append({"reference": f"Observation/{org_id}"})
        member_refs: list[dict] = []

        for j, sus in enumerate(mb.get("susceptibilities") or []):
            interp = sus.get("interpretation", "")
            # Issue #854 Bucket A row 4 (PR-obs-microbiology): opaque mb-sus id.
            _mb_sus_structural_key = f"{base}-{j}"
            sus_id = _resolve_mb_sus_id(_mb_sus_structural_key)
            _mb_sus_identifier = wrap_as_identifier(_mb_sus_structural_key, MB_SUS_KEY_SYSTEM)
            antibiotic_loinc = sus.get("antibiotic_loinc", "")
            sus_code_value, sus_code_system = resolve_susceptibility_code(antibiotic_loinc, ctx.country)
            # #321 JP_Observation_LabResult code.text min=1 満たす。
            _sus_c = system_coding(sus_code_system, sus_code_value, lang)
            _sus_code_text = _sus_c.get("display") or t("microbiology_fhir.antimicrobial_susceptibility", lang)
            # 同 profile の valueCodeableConcept.coding.display min=1 満たす
            # (v6.1 で 162 件 error)。v3-ObservationInterpretation は
            # English-only CS のため、JP output でも "en" で lookup
            # (Japanese display は walker `_strip_japanese_display_on_english
            # _only_systems` により削除されてしまい validator が
            # "display=0" を検出する)。lookup 失敗時は interp code 自体を
            # fallback として使う。
            _sus_interp_display = registry_display("hl7-observation-interpretation", interp, "en") or interp
            sus_obs: dict[str, Any] = {
                "resourceType": "Observation",
                "id": sus_id,
                # chain #2: JP Core Observation_LabResult profile.
                **({"meta": {"profile": [JP_OBSERVATION_LAB_RESULT_PROFILE]}} if is_jp(ctx.country) else {}),
                "status": "final",
                "category": lab_category,
                "code": {"coding": [_sus_c], "text": _sus_code_text},
                "subject": subject,
                "specimen": {"reference": f"Specimen/{spec_id}"},
                "method": {"text": _sus_method_text},
                "valueCodeableConcept": dual_slot_concept(
                    "hl7-observation-interpretation",
                    interp,
                    lang_for(ctx.country),
                    fallback_display=_sus_interp_display,
                ),
            }
            sus_obs["identifier"] = [*hai_identifier, _mb_sus_identifier]
            if based_on:
                sus_obs["basedOn"] = based_on
            # Issue #2585: the susceptibility is of this isolate.
            sus_obs["derivedFrom"] = [{"reference": f"Observation/{org_id}"}]
            if enc_ref:
                sus_obs["encounter"] = enc_ref
            # C1-13: the same times as the organism observation above (both
            # belong to the same reported result).
            if _effective:
                sus_obs["effectiveDateTime"] = _effective
            if _issued:
                sus_obs["issued"] = _issued
            out.append(sus_obs)
            result_refs.append({"reference": f"Observation/{sus_id}"})
            member_refs.append({"reference": f"Observation/{sus_id}"})
        if member_refs:
            org_obs["hasMember"] = member_refs

        # chain B: for JP output, the microbiology DR routes through
        # JP_DiagnosticReport_Microbiology (chain #2 originally used
        # LabResult without verifying Microbiology-specific constraints; spec
        # `StructureDefinition-jp-diagnosticreport-microbiology.json` requires
        # `code.coding` to contain a patternCodeableConcept for
        # `JP_DocumentCodes_CS 18725-2`, which LabResult does not accept).
        report_code: dict[str, Any] = culture_code
        if is_jp(ctx.country):
            _jp_doc_coding = {
                "system": JP_MB_DR_CODE_CS,
                "code": JP_MB_DR_CODE_VALUE,
                "display": JP_MB_DR_CODE_DISPLAY,
            }
            report_code = {
                **culture_code,
                "coding": [_jp_doc_coding, *culture_code.get("coding", [])],
            }
        # Issue #854 Bucket B (PR-diagnostic-report): opaque mb DR.id.
        _mb_dr_structural_key = base
        _mb_dr_identifier = wrap_as_identifier(_mb_dr_structural_key, MB_DR_KEY_SYSTEM)
        report: dict[str, Any] = {
            "resourceType": "DiagnosticReport",
            "id": _resolve_mb_dr_id(_mb_dr_structural_key),
            **({"meta": {"profile": [JP_MB_DR_PROFILE_URI]}} if is_jp(ctx.country) else {}),
            "status": "final",
            "category": (
                # Issue #3026: English LOINC display, the label in text.
                [dual_slot_concept("loinc", JP_MB_DR_CATEGORY_LOINC, lang)] if is_jp(ctx.country) else []
            )
            + [
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
            "code": report_code,
            "subject": subject,
            "specimen": [{"reference": f"Specimen/{spec_id}"}],
            "result": result_refs,
        }
        # Structural-key identifier always present; HAI identifier prepended
        # when the culture belongs to a HAI event (byte-preserves PR3b-5).
        report["identifier"] = [*hai_identifier, _mb_dr_identifier]
        if based_on:
            report["basedOn"] = based_on
        if enc_ref:
            report["encounter"] = enc_ref
        if _effective:
            report["effectiveDateTime"] = _effective
        if _mb_performer_ref:
            report["performer"] = [{"reference": _mb_performer_ref}]
            # CY8-13 polish: DR.resultsInterpreter — 培養検査は微生物検査室で解釈。
            report["resultsInterpreter"] = [{"reference": _mb_performer_ref}]
        else:
            report["resultsInterpreter"] = [{"reference": "Organization/hospital-main"}]
        # CY8-14 polish: MB DR.conclusionCode — growth の有無で normal/abnormal。
        _mb_abnormal = bool(mb.get("growth"))
        report["conclusionCode"] = [
            dual_slot_concept("snomed-ct", FINDING_ABNORMAL if _mb_abnormal else FINDING_NORMAL, lang)
        ]
        # Issue #1343: MB DR.conclusion — a one-line human-readable summary
        # of the culture outcome. Previously blank (0 %); a reader with the
        # ``conclusionCode`` alone cannot see WHICH organism grew or WHICH
        # antibiotic sensitivities were tested. Populate from the same mb
        # payload that drives ``presentedForm`` — organism display + a
        # compact susceptibility summary for positive cultures, or the
        # "no growth after 5-day incubation" wording for negatives.
        _mb_conclusion = _mb_conclusion_text(mb, lang)
        if _mb_conclusion:
            report["conclusion"] = _mb_conclusion
        # CY8-16 polish: MB DR.issued = the report time.
        if not report.get("issued") and _issued:
            report["issued"] = _issued
        # C5-20 (Chain 3): presentedForm — text/plain summary of culture +
        # susceptibility results (patient-facing form of the microbiology
        # report). Deterministic text (no external state).
        _title = t("microbiology_fhir.report_title", lang)
        _summary = _mb_presented_text(mb, lang)
        _pf = build_presented_form(_summary, _title, lang)
        if _pf:
            report["presentedForm"] = _pf
        out.append(report)

    return out


def _culture_times(mb: dict) -> tuple[str, str]:
    """``(effective, issued)`` of a culture result (Issue #3039): effective at
    the specimen collection (the report time when the collection is
    unknown), issued at the report as a FHIR instant (empty when unknown)."""
    from clinosim.modules.output.fhir_r4.lib.fhir_time import to_fhir_instant

    collected = mb.get("collected_datetime") or ""
    reported = mb.get("reported_datetime") or ""
    when = collected or reported
    effective = when.isoformat() if isinstance(when, datetime) else str(when)
    return effective, to_fhir_instant(reported) if reported else ""


def _antibiotic_name(sus: dict, lang: str) -> str:
    """The tested antibiotic's name in ``lang`` (LOINC display without the
    "[Susceptibility]" / 感受性 tail); shared by the conclusion and the text form."""
    if sus.get("antibiotic_display"):
        return str(sus["antibiotic_display"])
    loinc = str(sus.get("antibiotic_loinc") or "")
    if not loinc:
        return "?"
    disp = registry_display("loinc", loinc, lang) or ""
    if not disp:
        return loinc
    # Trim the "[Susceptibility]" / "感受性" tail — the header
    # of the summary already establishes we are listing sensitivities.
    for tail_marker in (" [Susceptibility]", t("mb_text.susceptibility_tail", "ja")):
        if disp.endswith(tail_marker):
            disp = disp[: -len(tail_marker)]
            break
    return disp.strip() or loinc


def _mb_conclusion_text(mb: dict, lang: str) -> str:
    """One-line ``DiagnosticReport.conclusion`` text (Issue #1343).

    For positive cultures (``mb["growth"]``): "<Organism> isolated" plus a
    compact susceptibility summary (``PEN=S, CTX=S, VAN=R``). For
    negatives: "No growth after 5-day incubation" / "5 日間培養で発育
    なし。". Empty string only when the payload lacks both a growth flag
    and an organism (a defensive guard — realistic microbiology events
    always carry one).
    """
    growth = bool(mb.get("growth"))
    organism = mb.get("organism_snomed", "") or ""
    if not growth:
        if not organism:
            return t("microbiology_fhir.no_growth_after_5day", lang)
        # Rare: growth flag off but organism recorded → treat as "not
        # clinically significant, likely contaminant" for narrative honesty.
        org_disp = registry_display("snomed-ct", organism, lang) or organism
        return t("microbiology_fhir.detected_not_significant", lang, org=org_disp)
    org_disp = code_lookup("snomed-ct", organism, lang) if organism else ""
    if not org_disp:
        return t("microbiology_fhir.culture_positive_pending_id", lang)
    sus_list = mb.get("susceptibilities") or []
    if not sus_list:
        return t("microbiology_fhir.isolated_pending_sus", lang, org=org_disp)

    # Sensitivity summary. Prefer the payload's ``antibiotic_display`` when
    # provided; otherwise resolve the LOINC display and strip the trailing
    # ``[Susceptibility]`` suffix / JA ``感受性`` suffix so the reader
    # sees the drug name ("Ceftriaxone=S") rather than a bare LOINC code.

    # Issue #2659: every tested antibiotic (a panel is at most a handful);
    # the conclusion is never cut off with an ellipsis.
    parts: list[str] = []
    for sus in sus_list:
        ab = _antibiotic_name(sus, lang)
        interp = str(sus.get("interpretation") or "?")
        parts.append(f"{ab}={interp}")
    tail = ", ".join(parts)
    return t("microbiology_fhir.isolated_with_sus", lang, org=org_disp, tail=tail)


def _mb_presented_text(mb: dict, lang: str) -> str:
    """Text/plain culture + susceptibility summary for presentedForm, in
    ``lang``: the same lines in every language, worded by the phrase
    catalog (``mb_text``; Issue #2457)."""
    # Issue #2664: the specimen's name, not the CIF key.
    specimen_code = mb.get("specimen_snomed", "") or ""
    specimen = (registry_display("snomed-ct", specimen_code, lang) if specimen_code else "") or (
        mb.get("specimen", "") or "unknown"
    )
    organism = mb.get("organism_snomed", "") or ""
    growth = t("mb_text.growth_detected" if mb.get("growth") else "mb_text.growth_none", lang)
    lines = [t("mb_text.specimen", lang, value=specimen), t("mb_text.growth", lang, value=growth)]
    if organism:
        org_disp = registry_display("snomed-ct", organism, lang) or organism
        lines.append(t("mb_text.organism", lang, value=org_disp))
    else:
        lines.append(t("mb_text.organism_negative", lang))
    sus_list = mb.get("susceptibilities") or []
    if sus_list:
        lines.append(t("mb_text.susceptibility_header", lang))
        for sus in sus_list:
            ab = _antibiotic_name(sus, lang)
            code = str(sus.get("interpretation") or "?")
            interp = registry_display("hl7-observation-interpretation", code, lang) or code
            lines.append(f"  {ab}: {interp}")
    return "\n".join(lines) + "\n"
