"""FHIR R4 Procedure resource builder (FA-1 procedures).

Extracted verbatim from ``fhir_r4_adapter``. Self-contained: imports only
leaf data, shared helpers, and stdlib/first-party deps — never the adapter.
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import display as registry_display
from clinosim.codes import (
    get_system_uri,
    system_key_for,
)
from clinosim.codes.procedures import catalog_procedure_types, procedure_type_display
from clinosim.codes.snomed import snomed_for_phrase
from clinosim.countries import lang_for
from clinosim.locale.free_text import localize_procedure_name
from clinosim.locale.i18n import t
from clinosim.locale.loader import map_diagnosis_code
from clinosim.modules._shared import is_jp
from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
from clinosim.modules.output.fhir_r4.encounters.encounter import encounter_ref
from clinosim.modules.output.fhir_r4.lib.common import dual_slot_concept, system_coding
from clinosim.modules.output.fhir_r4.lib.fhir_time import to_fhir_datetime
from clinosim.modules.output.fhir_r4.lib.ids import (
    derive_opaque_id,
    structural_key_system,
    wrap_as_identifier,
)
from clinosim.modules.output.fhir_r4.lib.jp_profiles import JP_PROCEDURE_PROFILE
from clinosim.modules.output.fhir_r4.lib.localization import _procedure_display

# Issue #854 Bucket A: opaque id + identifier[] round-trip for Procedure
# (same pattern PR #357 established for antibiotic MedicationRequest, PR
# #863 widened to all MR + MA, and PR #867 applied to Device + DUS). Three
# emit sites all resolve through the shared helper so ``Procedure.id`` shape
# is consistent regardless of the source path (CIF procedure record via
# ``_build_procedure`` here, order-derived via
# ``inline_bb.py::_bb_procedures``, or O2-therapy via
# ``oxygen_therapy.py``). PUBLIC constant (no underscore prefix) so
# downstream readers can import it for identifier[]-based lookup without
# string-parsing the (now opaque) id.
PROCEDURE_KEY_SYSTEM = structural_key_system("procedure-key")

# Issue #1766: a few call sites set ``ProcedureRecord.procedure_type`` to a
# snake_case classifier key (``chemotherapy_administration``,
# ``hearing_screen_aabr``, ``metabolic_screen_tandem_ms``,
# ``radiation_therapy``, ``pregnancy_termination``). The classifier is
# consumed by narrative + screening logic (kept stable), but the FHIR
# builder uses the same string as the ``coding[].display`` fallback when
# per-country code lookup (CPT / K-code) misses. A snake_case display
# fails the HL7 validator's binding at ERROR severity, so the humanizer
# below converts the key to a human-readable Title Case label before it
# reaches ``coding[].display``. Specific acronyms (AABR, MS) retain
# upper-case; everything else is simple ``.replace("_", " ").capitalize()``.
_PROCEDURE_TYPE_ACRONYMS = ("aabr", "crp", "mri", "ms", "cpap", "ecg", "ekg", "us")


def _catalog_types() -> frozenset[str]:
    return catalog_procedure_types()


def _humanize_procedure_type(proc_type: str) -> str:
    """Convert a snake_case ``procedure_type`` classifier key to a
    human-readable display fallback. Issue #1766."""
    if not proc_type or "_" not in proc_type:
        return proc_type
    parts = proc_type.split("_")
    first = parts[0].capitalize()
    rest = [p.upper() if p.lower() in _PROCEDURE_TYPE_ACRONYMS else p for p in parts[1:]]
    return " ".join([first, *rest])


def _resolve_procedure_id(structural_key: str) -> str:
    """Return the FHIR Procedure.id for any Procedure emit source (Issue #854).

    Shape: ``proc-{sha256(structural_key)[:12]}`` = 17 chars, fixed. The
    5-char ``proc-`` prefix retains the pre-#854 human-recognisable identity
    (a URL like ``/Procedure/proc-<hex>`` reads as a Procedure at a glance)
    while dropping the compound-key body. The compound structural_key is
    preserved in ``Procedure.identifier[]`` via :func:`wrap_as_identifier`
    for round-trip. Callers own the structural_key composition — the three
    emit paths pass different keys (CIF procedure_id + encounter_id;
    order_id; O2 order_id / enc_id / patient_id-seq) — but any two calls
    with the same key produce byte-identical output.
    """
    return derive_opaque_id("proc-", structural_key)


def _build_procedure(
    proc: dict,
    patient_id: str,
    index: int,
    country: str,
    record: dict | None = None,
) -> dict:
    """Build FHIR Procedure resource."""
    code_system_key = system_key_for("procedure", country)
    code_system = get_system_uri(code_system_key)
    lang = lang_for(country)

    # Use performedDateTime for point-in-time procedures, performedPeriod for longer ones
    start = proc.get("start_datetime", "")
    end = proc.get("end_datetime", "")

    # Issue #854 Bucket A: compound structural key drives an opaque id.
    # Structural key = pre-#854 id shape (``{enc_id}-{base_pid}`` or ``base_pid``)
    # so consumers can recover it verbatim from identifier[] via
    # PROCEDURE_KEY_SYSTEM. This preserves the encounter-scoping property
    # (same base_pid across encounters hashes to different opaque ids because
    # enc_id is part of the key when populated).
    enc_id = proc.get("encounter_id", "")
    base_pid = proc.get("procedure_id") or f"proc-{patient_id}-{index:03d}"
    structural_key = f"{enc_id}-{base_pid}" if enc_id else base_pid
    resource_id = _resolve_procedure_id(structural_key)

    # Per AD-30, CIF stores only codes. Displays resolved via code_lookup.
    proc_code_jp = proc.get("procedure_code_jp", "")
    proc_code_us = proc.get("procedure_code_us", "")
    primary_code = proc.get("procedure_code", "")
    proc_type = proc.get("procedure_type", "")
    # Issue #1766: when the display lookup misses, the fallback must not
    # leak the raw snake_case classifier key to ``coding[].display``.
    # Issue #2263: catalog name first (the same name the narrative shows).
    catalog_name = procedure_type_display(proc_type, "en") if proc_type in _catalog_types() else ""
    fallback = catalog_name or _humanize_procedure_type(proc_type) or "(procedure)"

    # Resolve displays via code dictionaries (k-codes.yaml / cpt.yaml)
    primary_lang = lang_for(country)
    if primary_code:
        # Issue #3081: a code with no K-code / CPT display (the SNOMED CT
        # newborn screens) is named from the catalog in the output language.
        named = procedure_type_display(proc_type, primary_lang) if proc_type in _catalog_types() else ""
        primary_display = _procedure_display(primary_code, primary_lang, named or fallback)
    else:
        # Uncoded by design in this country (Issue #2340: e.g. JP 正常分娩 is
        # uninsured, US oxygen administration has no CPT code): name it from
        # the catalog, else from the other country's registered code.
        other_code = proc_code_us if is_jp(country) else proc_code_jp
        primary_display = (
            procedure_type_display(proc_type, primary_lang) if proc_type in _catalog_types() else ""
        ) or _procedure_display(other_code, primary_lang, fallback)
    # Issue #360 G6 / Issue #474: supportive-care Procedure records commonly
    # lack a K-code, so `primary_display` falls back to the English composite
    # ``{type}: {detail}`` text from ``modules/order/engine.py`` (e.g.
    # "O2: Nasal cannula SpO2 >= 94%") OR to a procedure name from encounter
    # YAML (e.g. "Ice pack application", "Wound irrigation with normal saline").
    #
    # The JP fallback goes through the procedure-name resolver (Issue #2408):
    # an exact procedure-phrase / imaging entry ("Ice pack application" →
    # 「氷嚢貼付」), else the free-text translator for composite order text,
    # which also translates dosage abbreviations (O2 → 酸素投与, PO → 経口).
    # A K-code display is already Japanese, so this is a no-op there.
    if is_jp(country) and primary_display:
        primary_display = localize_procedure_name(primary_display, "ja")

    # Issue #1701 Phase 4d.2: when running JP output on a Procedure whose
    # CIF record carries only a CPT code (``procedure_code_us``) and no
    # K-code (``procedure_code_jp``), emit the primary ``coding[]`` entry
    # under the CPT system URI, not the K-codes URI. The K-codes URI is
    # authoritative for K-codes only; stamping a CPT code (e.g. 94660 CPAP,
    # 95810 polysomnography) under the K-codes URI is a semantic error that
    # a strict JP-Core consumer would reject. Phase 4d (OSA follow-up)
    # routed its CPT codes through this emit path for JP output; horizontal
    # extensions reusing the Phase 4d / 4e ``procedures:`` yaml schema will
    # too, so the fix lives at the common choke point.
    #
    # Cycle-2 M2 (mirror case): when the CIF record pins
    # ``procedure_system_key`` (e.g. "snomed-ct" for the newborn hearing
    # screen 413083006 and newborn metabolic screen 428447008), honour it
    # as the authoritative system URI — SNOMED concept ids stamped under
    # the country default CPT / K-codes URI are rejected by a strict
    # US-Core / JP-Core consumer. The pinned key wins over the Phase 4d.2
    # inference below; it is strictly additive (empty key preserves the
    # pre-#1701 country-default + Phase 4d.2 behaviour).
    _primary_system_key_override = str(proc.get("procedure_system_key", "") or "")
    _primary_system = code_system
    if _primary_system_key_override:
        _primary_system = get_system_uri(_primary_system_key_override)
    elif is_jp(country) and not proc_code_jp and proc_code_us and primary_code == proc_code_us:
        _primary_system = get_system_uri("cpt")
    # Issue #3009: JP output uses JP code systems only. CPT is a US code
    # system (AMA) and is never emitted on JP: a procedure with no K-code
    # keeps its Japanese ``code.text`` (and a SNOMED coding below when one
    # is verified) and no CPT coding (code-mapping spec: no other country's
    # system as a fallback).
    _drop_primary = is_jp(country) and _primary_system == get_system_uri("cpt")

    # No primary coding without a code (an empty ``code`` is invalid FHIR);
    # the text and the SNOMED coding still describe it.
    coding_entries: list[dict[str, Any]] = (
        [{"system": _primary_system, "code": primary_code, "display": primary_display}]
        if primary_code and not _drop_primary
        else []
    )
    if coding_entries and _primary_system_key_override:
        # Issue #3081: a code pinned to its own system (the SNOMED CT newborn
        # screens) carries that system's display, English for an
        # English-only system (spec §5.3); ``code.text`` keeps the name in
        # the output language.
        coding_entries = [
            system_coding(_primary_system_key_override, primary_code, lang, fallback_display=catalog_name or fallback)
        ]

    # Issue #1701 Phase 4d.1: when ``procedure_type`` matches a verified
    # keyword in ``codes/data/procedure-phrase-to-snomed.yaml``, attach the SNOMED coding
    # as a secondary entry. Mirrors the inline_bb.py Order-derived path
    # (PR #1282). Benefits CIF ``ProcedureRecord`` emits whose
    # ``procedure_type`` carries a clinical phrase (e.g. "CPAP therapy",
    # "Polysomnography") regardless of the per-country primary coding
    # system.
    if proc_type:
        _sct_code = snomed_for_phrase(proc_type)
        if _sct_code is not None:
            # English SNOMED preferred term from the registry (dual slot,
            # Issue #2363); the localized name is code.text.
            coding_entries.append(system_coding("snomed-ct", _sct_code, lang_for(country)))

    resource: dict[str, Any] = {
        "resourceType": "Procedure",
        "id": resource_id,
        "identifier": [wrap_as_identifier(structural_key, PROCEDURE_KEY_SYSTEM)],
        # Chain #2: JP Core Procedure profile.
        **({"meta": {"profile": [JP_PROCEDURE_PROFILE]}} if is_jp(country) else {}),
        "status": "completed",
        "code": {
            **({"coding": coding_entries} if coding_entries else {}),
            "text": primary_display,
        },
        "subject": patient_ref(patient_id),
    }

    # category (SNOMED)
    category_code = proc.get("category_code", "")
    if category_code:
        resource["category"] = dual_slot_concept("snomed-ct", category_code, lang)

    # Route through to_fhir_datetime so performedPeriod /
    # performedDateTime carry the FHIR R4-required TZ suffix (JST +09:00
    # for JP, per FB-F1 helper). Previously raw strings bypassed the
    # helper — this was the last site left after a broader sweep, and
    # was the source of the iris4h-ai HAPI validator "日付/TZ 不備 262件
    # Procedure" finding.
    _start_fhir = to_fhir_datetime(start)
    _end_fhir = to_fhir_datetime(end)
    if _start_fhir and _end_fhir and _start_fhir != _end_fhir:
        resource["performedPeriod"] = {"start": _start_fhir, "end": _end_fhir}
    elif _start_fhir:
        resource["performedDateTime"] = _start_fhir

    if proc.get("encounter_id"):
        resource["encounter"] = encounter_ref(proc["encounter_id"])

    # performer[] with function (surgeon, anesthesiologist)
    performers: list[dict[str, Any]] = []
    surgeon_id = proc.get("primary_surgeon_id", "")
    anes_id = proc.get("anesthesiologist_id", "")
    if surgeon_id:
        performers.append(
            {
                "function": dual_slot_concept("snomed-ct", "304292004", lang),
                "actor": {"reference": f"Practitioner/{surgeon_id}"},
            }
        )
    if anes_id and anes_id != surgeon_id:
        performers.append(
            {
                "function": dual_slot_concept("snomed-ct", "88189002", lang),
                "actor": {"reference": f"Practitioner/{anes_id}"},
            }
        )
    if performers:
        resource["performer"] = performers
        # recorder (default to surgeon when available)
        resource["recorder"] = {"reference": f"Practitioner/{surgeon_id or anes_id}"}

    # reasonReference — link to encounter's primary Condition. Chronic-
    # primary encounters resolve to the patient-scoped chronic Condition;
    # acute-primary encounters keep the encounter-scoped id.
    # Issue #1222: skip reasonReference when the encounter's primary dx is a
    # Z-chapter visit-reason code — ``conditions.py`` does not emit a
    # Condition for these (Issue #916 gate), so a reasonReference would
    # dangle. Encounter.reasonCode already carries the Z-code semantic;
    # Procedure.reasonCode below mirrors it as text/coding, no reference
    # needed. P=10k audit finding #F: 45 Procedure→Condition dangling refs.
    # Post-#1223 residual (S105 v2 audit): 41 refs remained because the
    # gate looked at record-level dx only. VAX companion encounters
    # (#1215) carry encounter-scoped ``admission_diagnosis_code=Z23``
    # while the record-level dx is the primary IMP admission (non-Z-code),
    # so the gate did not fire. ``encounter_primary_dx_code`` prefers the
    # per-encounter dx and falls back to record-level.
    from clinosim.modules.diagnosis.nonspecific_codes import encounter_primary_dx_code, is_visit_reason_zcode

    _primary_dx_code = encounter_primary_dx_code(record, enc_id)
    if enc_id and not (_primary_dx_code and is_visit_reason_zcode(_primary_dx_code)):
        # Issue #854 Bucket B (PR-condition): route through the shared
        # resolver so `.reasonReference[]` stays byte-consistent with the
        # opaque Condition.id emit — no string reconstruction anywhere.
        from clinosim.modules.output.fhir_r4.conditions.primary_ref import (
            encounter_primary_condition_id,
            primary_condition_ref,
        )

        if record is not None:
            _primary_ref = primary_condition_ref(record, patient_id, enc_id)
        else:
            _primary_ref = encounter_primary_condition_id(patient_id, enc_id)
        resource["reasonReference"] = [{"reference": f"Condition/{_primary_ref}"}]
    # session-88j P2-5a: Procedure.reasonCode with real ICD-10 coding from
    # the encounter's clinical_diagnosis (was text-only generic template
    # "入院時診断に基づく処置" for all procedures — v14 review flagged as
    # uninformative). Preserves the existing text as fallback + as .text
    # alongside the coding for consumers that fall back to text.
    # CY7-17 (Chain-7): base fallback wording kept identical for
    # backwards compatibility of CY7-17 assertions.
    if not resource.get("reasonCode"):
        resource["reasonCode"] = procedure_reason_codes(record, country, encounter_id=enc_id)

    # bodySite (SNOMED)
    body_site_code = proc.get("body_site_code", "")
    if body_site_code:
        resource["bodySite"] = [dual_slot_concept("snomed-ct", body_site_code, lang)]
    # CY7-18 (Chain-7): bodySite text-only fallback when the CIF record
    # doesn't carry a SNOMED site code (bedside procedures often don't).
    if not resource.get("bodySite"):
        resource["bodySite"] = [{"text": t("fhir_text.body_site_unspecified", lang_for(country))}]

    # location (OR etc.)
    location_id = proc.get("location_id", "")
    if location_id:
        resource["location"] = {"reference": f"Location/{location_id}"}

    # outcome (SNOMED)
    outcome_code = proc.get("outcome_code", "")
    if outcome_code:
        resource["outcome"] = dual_slot_concept("snomed-ct", outcome_code, lang)
    # CY7-19 (Chain-7): outcome default = SNOMED 385669000 "Successful" when
    # Procedure.status == "completed" and no explicit outcome_code. Reflects
    # the majority clinical reality (few procedures fail without explicit
    # complication).
    if not resource.get("outcome") and resource.get("status") == "completed":
        _succ_code = "385669000"
        resource["outcome"] = dual_slot_concept("snomed-ct", _succ_code, lang, fallback_display="Successful")

    # complication (SNOMED)
    comp_codes = proc.get("complication_codes", []) or []
    if comp_codes:
        resource["complication"] = [dual_slot_concept("snomed-ct", c, lang) for c in comp_codes]

    return resource


def procedure_reason_codes(record: dict | None, country: str, encounter_id: str | None = None) -> list[dict]:
    """``Procedure.reasonCode`` from the encounter's clinical diagnosis
    (session-88j P2-5a / Issue #816), shared by the CIF-procedure and the
    order-derived Procedure paths.

    The coding carries the code the country emits for the diagnosis
    (``map_diagnosis_code``; Issue #3010: JP folds an ICD-10-CM code to WHO
    ICD-10, e.g. Z12.11 → Z12.1), in the country's ICD-10 system, as
    ``Condition`` and ``Encounter`` do; a folded code takes its own display.
    A vaccination visit of the CIF-procedure path (``encounter_id`` given)
    carries the reason of each vaccine given at the encounter (Issue #3008).
    Without a diagnosis, the generic reason text."""
    from clinosim.modules.immunization.visits import IMMUNIZATION_VISIT_DX, vaccination_visit_reason_codes

    lang = lang_for(country)
    dx = (record or {}).get("clinical_diagnosis", {}) or {}
    dx_code = dx.get("discharge_diagnosis_code") or dx.get("admission_diagnosis_code", "") or ""
    dx_display = dx.get("discharge_diagnosis_display") or dx.get("admission_diagnosis_display", "") or ""
    generic_text = t("fhir_text.procedure_reason_generic", lang)
    if not dx_code:
        return [{"text": generic_text}]
    icd_key = system_key_for("diagnosis", country)
    if encounter_id is not None and dx_code == IMMUNIZATION_VISIT_DX:
        # Issue #3008: a vaccination visit's reason in the country's system
        # (JP: the WHO need-for-immunization code of each vaccine given).
        vax = [
            str(imm.get("vaccine_cvx", "") if isinstance(imm, dict) else getattr(imm, "vaccine_cvx", ""))
            for imm in (record or {}).get("immunizations", []) or []
            if encounter_id
            and (imm.get("encounter_id") if isinstance(imm, dict) else getattr(imm, "encounter_id", "")) == encounter_id
        ]
        return [
            {
                "coding": [
                    {
                        "system": get_system_uri(icd_key),
                        "code": code,
                        "display": registry_display(icd_key, code, lang) or code,
                    }
                ],
                "text": registry_display(icd_key, code, lang) or generic_text,
            }
            for code in vaccination_visit_reason_codes(country, vax)
        ]
    patient = (record or {}).get("patient") or {}
    sex = str(patient.get("sex", "") or "") if isinstance(patient, dict) else ""
    emit_code = map_diagnosis_code(dx_code, country, sex=sex)
    if emit_code != dx_code:
        dx_code, dx_display = emit_code, ""
    display = dx_display or (registry_display(icd_key, dx_code, lang) or dx_code)
    return [
        {
            "coding": [{"system": get_system_uri(icd_key), "code": dx_code, "display": display}],
            "text": display or generic_text,
        }
    ]
