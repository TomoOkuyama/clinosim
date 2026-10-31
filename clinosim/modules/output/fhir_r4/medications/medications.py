"""FHIR R4 MedicationRequest / MedicationAdministration builders (FA-1 medications).

Extracted verbatim from ``fhir_r4_adapter``. Self-contained: imports only
leaf data, shared helpers, and stdlib/first-party deps — never the adapter.
"""

from __future__ import annotations

import re
import uuid
from functools import cache
from pathlib import Path
from typing import Any

from clinosim.codes import (
    get_system_uri,
    system_key_for,
)
from clinosim.codes import lookup as code_lookup
from clinosim.codes.drugs import drug_system_uri, is_verified_yj, jp_drug_code_table
from clinosim.codes.ucum import ucum_quantity
from clinosim.locale.loader import load_code_mapping
from clinosim.modules._shared import (
    MED_STOP_ORDER_ID_MARKER,
    get_attr_or_key,
    is_jp,
    resolve_lang,
)
from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
from clinosim.modules.output.fhir_r4.encounters.encounter import encounter_ref
from clinosim.modules.output.fhir_r4.lib.common import (
    _parse_dose_for_mar,
    build_dosage_instruction,
    build_route_concept,
    canonicalize_route,
    map_diagnosis_code,
    map_mar_status,
    strip_protocol_prefix,
)
from clinosim.modules.output.fhir_r4.lib.ids import (
    derive_opaque_id,
    structural_key_system,
    wrap_as_identifier,
)
from clinosim.modules.output.fhir_r4.lib.localization import (
    _localize_dosage_terms,
    _localize_drug_name,
    _localize_rate_adjustment,
    _split_rate_adjustment_suffix,
)

# HL7 CodeSystem URIs for MedicationRequest classification (both callers
# emitted them inline before Issue #548 partial extraction).
_MR_CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/medicationrequest-category"
_MR_COURSE_OF_THERAPY_SYSTEM = "http://terminology.hl7.org/CodeSystem/medicationrequest-course-of-therapy"

# Issue #1766: strip trailing `` (TradeName)`` from US RxNorm displays
# before emitting ``MedicationRequest.medicationCodeableConcept.coding[].display``.
# The source yaml tables (``rxnorm.yaml``, ``hot7.yaml``) decorate the
# generic name with the US trade name for clinician search ergonomics,
# but the RxNorm binding expects the canonical generic form alone.
_TRADE_NAME_SUFFIX_RE = re.compile(r"\s*\([^)]+\)\s*$")


def _build_category_block(code: str, display: str) -> list[dict]:
    """Return the standard ``MedicationRequest.category`` block for a
    ``medicationrequest-category`` code (Issue #548 partial extraction).

    Both public builders emit this exact shape; the code + display pair is the
    only per-caller variance. Kept in ``_fhir_medications`` to avoid a
    cross-module dependency for such a leaf helper.
    """
    return [
        {
            "coding": [
                {
                    "system": _MR_CATEGORY_SYSTEM,
                    "code": code,
                    "display": display,
                }
            ],
        }
    ]


def _build_course_of_therapy_block(code: str, display: str) -> dict:
    """Return the standard ``MedicationRequest.courseOfTherapyType`` block for a
    ``medicationrequest-course-of-therapy`` code (Issue #548 partial extraction).
    """
    return {
        "coding": [
            {
                "system": _MR_COURSE_OF_THERAPY_SYSTEM,
                "code": code,
                "display": display,
            }
        ],
    }


# Course-of-therapy selection rules (Issue #548 partial extraction) — two
# different callers use two DIFFERENT rules; named helpers make the
# divergence explicit at every call site. See Issue #548 for the full
# unification proposal (decision table shared by both paths).
#
# HL7 CodeSystem: `medicationrequest-course-of-therapy`
#   * `continuous` — "Continuous long term therapy" (chronic / maintenance)
#   * `acute`      — "Short course (acute) therapy"

_COURSE_CONTINUOUS = ("continuous", "Continuous long term therapy")
_COURSE_ACUTE = ("acute", "Short course (acute) therapy")


def _course_for_order(is_home_med: bool, category_code: str) -> tuple[str, str]:
    """Rule used by ``_build_medication_request`` (encounter-time orders).

    A chronic home med, or an order tagged with the ``community`` category,
    is continuous therapy; everything else is treated as acute (default).
    Preserves the CY8-18 heuristic verbatim.
    """
    return _COURSE_CONTINUOUS if (is_home_med or category_code == "community") else _COURSE_ACUTE


def _course_for_discharge(is_discharge: bool, duration_days: int | None) -> tuple[str, str]:
    """Rule used by ``_build_discharge_medication_request``.

    A non-discharge script (i.e. an outpatient renewal) is continuous by
    definition. A discharge script with an open-ended supply (no
    ``duration_days``) is a maintenance therapy handed over at discharge
    — continuous. A discharge script with an explicit duration is a short
    course — acute.
    """
    return _COURSE_CONTINUOUS if ((not is_discharge) or duration_days is None) else _COURSE_ACUTE


def _derive_mr_category(
    encounter_type: str,
    is_home_med: bool,
    is_episodic: bool,
    is_discharge_intent: bool,
) -> tuple[str, str]:
    """Derive the ``medicationrequest-category`` (code, display) tuple for
    a FHIR MedicationRequest emission (Issue #548 unification).

    Single source of truth for the 5-way decision tree previously
    duplicated across the order path (5-branch) and the discharge path
    (2-branch, which silently omitted episodic / discharge-intent
    awareness).

    HL7 CodeSystem: ``medicationrequest-category``
      * ``community``  — chronic home-medication or outpatient renewal
      * ``outpatient`` — episodic outpatient / emergency-department order
      * ``inpatient``  — inpatient order that is NOT a take-home
      * ``discharge``  — inpatient take-home script (Rx at discharge)

    Decision rule (evaluated in order):

    1. ``is_home_med`` OR (``encounter_type=="outpatient"`` AND NOT ``is_episodic``)
       → ``community`` — chronic maintenance / outpatient renewal
    2. ``encounter_type`` in ("outpatient", "emergency")
       → ``outpatient`` — episodic OP / ED order
    3. ``encounter_type == "inpatient"`` AND ``is_discharge_intent``
       → ``discharge`` — inpatient take-home
    4. ``encounter_type == "inpatient"``
       → ``inpatient`` — in-house prescription
    5. otherwise (encounter_type empty / unknown)
       → ``inpatient`` — safe fallback (intent already indicates an order was authored)
    """
    if is_home_med or (encounter_type == "outpatient" and not is_episodic):
        return "community", "Community"
    if encounter_type in ("outpatient", "emergency"):
        return "outpatient", "Outpatient"
    if encounter_type == "inpatient" and is_discharge_intent:
        return "discharge", "Discharge"
    if encounter_type == "inpatient":
        return "inpatient", "Inpatient"
    return "inpatient", "Inpatient"


# Issue #349 Phase 1b: canonical Identifier.system URI for antibiotic
# MedicationRequest structural-key round-trip. `.id` becomes an opaque
# `mr-{sha256(key)[:12]}` short id; the original compound key
# (`req-abx-hai-...-{drug}-{intent}`) is preserved as an Identifier so
# downstream consumers can recover parent HAI id + drug slug + intent
# without string-parsing the (now opaque) Resource.id.
# Constant is PUBLIC (no underscore prefix): imported by
# `clinosim/audit/axes/clinical.py` for the narrow-rate gate that filters
# antibiotic MRs by their structural-key identifier — same
# writer/reader shared-constant pattern as ``MB_ORG_ID_PREFIX``
# (`_fhir_microbiology.py`). Rename here triggers an ImportError
# downstream rather than a silent gate skip.
MEDICATION_REQUEST_KEY_SYSTEM = structural_key_system("medication-request-key")

# === Issue #854 remainder (PR-medication-administration): opaque MA.id ===
# Discovered post-#854-close via p=500 review: MedicationAdministration
# was overlooked in the original sweep. Structural key = pre-#854 id body
# `{encounter_id or patient_id}-{index:05d}` (`mar-` prefix stripped);
# post-#854 every `.id` is `mar-<12hex>` (16 chars, fixed). Cross-refs
# (`.subject`, `.context`, `.request`) already route through the shared
# resolvers (Patient / Encounter / MR migrated earlier), so this is a
# stand-alone-tail migration — no downstream cascade needed.
MEDICATION_ADMINISTRATION_ID_PREFIX = "mar-"
MEDICATION_ADMINISTRATION_KEY_SYSTEM = structural_key_system("medication-administration-key")


def _resolve_ma_id(structural_key: str) -> str:
    """Return the opaque FHIR MedicationAdministration.id from a structural key.

    Shape: ``mar-{sha256(structural_key)[:12]}`` = 16 chars, fixed.
    """
    return derive_opaque_id(MEDICATION_ADMINISTRATION_ID_PREFIX, structural_key)


# Issue #445: Resource.id prefixes for prescriptions that come from
# `CIFPatientRecord.discharge_prescription` rather than from an inpatient Order.
# Two prefixes, not one, so a consumer can tell a take-home script written at
# inpatient discharge from an outpatient chronic-medication renewal without
# re-reading the encounter. PUBLIC (no underscore): the bundle builder in
# `fhir_r4_adapter` and the tests both import these, so a rename raises
# ImportError instead of silently splitting writer and reader.
DISCHARGE_RX_ID_PREFIX = "rxdc-"
OUTPATIENT_RX_ID_PREFIX = "rxopd-"

# `dispenseRequest.expectedSupplyDuration` carries FIXED VALUES in BOTH profiles that
# clinosim's JP MedicationRequests claim. Quoted from the spec StructureDefinitions,
# never inferred (CLAUDE.md: spec fixedUri / fixed value must be copied from the spec):
#
#   JP_MedicationRequest (JP Core 1.2.0) — StructureDefinition-jp-medicationrequest.json
#     dispenseRequest.expectedSupplyDuration.unit    min=0  fixedString '日'
#   JP_MedicationRequest_eCS (JP-CLINS 1.13.0) — StructureDefinition-JP-MedicationRequest-eCS.json
#     dispenseRequest.expectedSupplyDuration.value   min=1  MS=True
#     dispenseRequest.expectedSupplyDuration.unit    min=1  MS=True  fixedString '日'
#     dispenseRequest.expectedSupplyDuration.system  min=1  MS=True  fixedUri  'http://unitsofmeasure.org'
#     dispenseRequest.expectedSupplyDuration.code    min=1  MS=True  fixedCode 'd'
#
# `unit` is the Japanese character, `code` is the UCUM token. Putting "d" in `unit`
# is a fixed-value violation that survives dropping the eCS profile, because JP Core
# pins the same string.
#
# US locale has NO fixed-value constraint (JP profiles never bind US resources), so
# `unit` gets the UCUM Latin token `d` to match `code` — the JP character in a US
# resource leaks Japanese-language text into English output (Issue #730).
_SUPPLY_DURATION_UNIT_JP = "日"
_SUPPLY_DURATION_UNIT_US = "d"
_SUPPLY_DURATION_CODE = "d"


def _resolve_mr_id(order_id: str) -> str:
    """Return the FHIR MedicationRequest.id for a CIF Order (Issue #853).

    Widened from Phase-1b's ``_resolve_antibiotic_mr_id`` (PR #357) — every
    non-empty ``Order.order_id`` now maps to the same
    ``mr-{sha256(order_id)[:12]}`` opaque shape. The compound structural key
    is preserved in ``MedicationRequest.identifier[]`` via
    :func:`_build_medication_request_identifiers` for round-trip. Cross-reference
    sites (``MedicationAdministration.request.reference``, discharge-Rx / outpatient-Rx
    builders) all go through this single helper so ``.id`` derivations stay
    byte-consistent across resources that reference the same order.

    Empty ``order_id`` raises ``ValueError`` via
    :func:`clinosim.modules.output.fhir_r4.lib.ids.derive_opaque_id`.
    """
    return derive_opaque_id("mr-", order_id)


def _resolve_dc_rx_id(structural_key: str) -> str:
    """Return the FHIR MedicationRequest.id for a discharge-Rx entry (Issue #853).

    Shape: ``rxdc-{sha256(structural_key)[:12]}``. The 5-char prefix keeps a
    take-home script written at inpatient discharge distinguishable from an
    outpatient chronic renewal (Issue #445 intent) even after both ids become
    opaque under Issue #853. The compound structural key
    (``{encounter_id}-{seq:02d}``) is preserved in
    ``MedicationRequest.identifier[]`` via
    :func:`_build_medication_request_identifiers` for round-trip.
    """
    return derive_opaque_id(DISCHARGE_RX_ID_PREFIX, structural_key)


def _resolve_opd_rx_id(structural_key: str) -> str:
    """Return the FHIR MedicationRequest.id for an outpatient-Rx entry (Issue #853).

    Shape: ``rxopd-{sha256(structural_key)[:12]}``. Companion to
    :func:`_resolve_dc_rx_id` — see Issue #445 for why the two prefixes stay
    distinguishable.
    """
    return derive_opaque_id(OUTPATIENT_RX_ID_PREFIX, structural_key)


def _build_medication_request_meta(
    country_code: str,
    medication_intent: str,
) -> dict[str, Any]:
    """Build MedicationRequest.meta with profile (JP only) and tag[] (medication_intent).

    Issue #349 Phase 2: medication_intent ("empirical" or "narrowed") is emitted
    in meta.tag[] with system urn:clinosim:regimen-intent. For non-antibiotic
    orders, medication_intent is empty and no tag is emitted.
    """
    meta: dict[str, Any] = {}

    # JP Core profile
    if is_jp(country_code):
        meta["profile"] = ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_MedicationRequest"]

    # Medication intent tag (antibiotic regimens only)
    if medication_intent:
        meta["tag"] = [
            {
                "system": "urn:clinosim:regimen-intent",
                "code": medication_intent,
            }
        ]

    return {"meta": meta} if meta else {}


def _build_medication_request_identifiers(
    structural_key: str,
    country_code: str,
    rp_number: str,
    order_in_rp: str,
) -> dict[str, list[dict[str, str]]]:
    """Assemble the MedicationRequest.identifier[] slice list.

    Two concerns coexist:

    * Structural-key round-trip (Issue #349 Phase 1b + Issue #853):
      preserved via :func:`wrap_as_identifier` under
      :data:`MEDICATION_REQUEST_KEY_SYSTEM` so consumers can recover the
      compound Order.order_id from the (now opaque) Resource.id. Post-#853
      this fires unconditionally — Phase-1b (PR #357) gated it on
      antibiotic-only; Issue #853 widened it to every MR path.
    * JP Core MR (P1-4): mhlw ``rpNumber`` + ``orderInRp``
      slices required by JP_MedicationRequest profile.

    Returns ``{"identifier": [...]}``; the structural-key entry always
    contributes at least one entry so this helper never returns ``{}``.
    """
    entries: list[dict[str, str]] = [
        wrap_as_identifier(structural_key, MEDICATION_REQUEST_KEY_SYSTEM),
    ]
    if is_jp(country_code):
        entries.extend(
            [
                {
                    "system": "http://jpfhir.jp/fhir/core/mhlw/IdSystem/Medication-RPGroupNumber",
                    "value": rp_number,
                },
                {
                    "system": "http://jpfhir.jp/fhir/core/mhlw/IdSystem/MedicationAdministrationIndex",
                    "value": order_in_rp,
                },
            ]
        )
    return {"identifier": entries}


# iris4h-ai feedback F-1: MedicationRequest / MedicationAdministration
# の system URI を code 形式ごとに JP Core NamingSystem 準拠 URI に振り分け。
#
# 従来 `get_system_uri("yj")` は `urn:oid:1.2.392.100495.20.2.74` を常に返す
# が、この OID は JP Core NamingSystem 上 HOT9 に紐付いており、clinosim の
# yj.yaml に格納されている実 code(HOT7 106 件 + YJ12 59 件、HOT9 は 0 件)
# のいずれも HOT9 pattern と一致しない = jpfhir-terminology 2.2606.0 で
# ~53k info。format ごとに spec-fixed URI へ dispatch する。
#
# URI 出典(iris4h-ai/jp_core/package/NamingSystem-*.json fixedUri 直接引用):
#   - HOT7  : http://medis.or.jp/CodeSystem/master-HOT7
#   - HOT9  : http://medis.or.jp/CodeSystem/master-HOT9
#   - HOT13 : http://medis.or.jp/CodeSystem/master-HOT13
#   - YJ    : http://capstandard.jp/iyaku.info/CodeSystem/YJ-code
# Issue #2262: the per-format dispatch lives in clinosim.codes.drugs.
_JP_YJ_CODE_URI = get_system_uri("yj")

# #291 JP-CLINS eCS "nocoded" slice — code_mapping にヒットしない
# 薬(ED 特異薬 等)の `medication[x].coding` min=1 を満たすための fallback。
# spec: clinical-information-sharing#1.13.0/package/
# CodeSystem-jp-eCS-medicationcode-nocoded-cs.json 権威 display "標準コードなし"。
_JP_MEDICATION_CODE_NOCODED_CS = get_system_uri("medication-nocoded")
_JP_MEDICATION_CODE_NOCODED_CODE = "NOCODED"
_JP_MEDICATION_CODE_NOCODED_DISPLAY = "標準コードなし"

# Issue #1220 (2026-09-10): JP national YJ CodeSystem shipped as clinosim
# artifact (``codes/authoritative/JP_MedicationCodeYJ_CS_full.json``,
# ``content=complete``, 23,923 concepts sourced from MEDIS 医薬品HOTコード
# マスター). Replaces the tx-server-fragment-based gate (Issue #283) which
# downgraded 41.8 % of MedicationRequest / 25.1 % of MedicationAdministration
# to the JP-CLINS eCS ``nocoded`` slice because the tx-server-shipped
# ``jpfhir-terminology 2.2606.0`` CodeSystem is content=fragment (2000/25542,
# psychiatric/neurological only) and cannot verify cardiovascular /
# respiratory / oncology YJ codes clinosim emits.
#
# The clinosim-shipped CS is honest — same canonical URL as tx-server's
# (``http://capstandard.jp/iyaku.info/CodeSystem/YJ-code``), full concept
# set, MEDIS attribution in copyright. Downstream FHIR validators should
# load clinosim's CS ahead of the tx-server fragment (IG package
# precedence) so the ``required`` binding on
# ``codingYJ.code -> JP_MedicationCodeYJ_VS|1.1.0a`` resolves against the
# complete concept set — spec-clean rather than defensive-downgrade.
#
# Refresh from upstream MEDIS master:
#     python scripts/refresh_authoritative_yj_full.py \\
#         --source h<YYYYMMDD>/MEDIS<YYYYMMDD>.TXT


def _is_yj_code_valid(code: str) -> bool:
    """Return True when ``code`` is in the JP national YJ CodeSystem
    (``clinosim.codes.drugs.is_verified_yj``, Issues #1220 / #2262)."""
    return is_verified_yj(code)


def _resolve_jp_drug_system_uri(code: str) -> str:
    """JP Core NamingSystem URI for a JP drug code by format
    (``clinosim.codes.drugs.drug_system_uri``, Issue #2262)."""
    return drug_system_uri(code, "JP")


def _map_order_status_to_fhir(status: str) -> str:
    """Map clinosim OrderStatus to FHIR R4 MedicationRequest.status.
    PR3b-3 adds 'stopped' mapping for discontinued empirical regimens.

    PR3b-3 adversarial-1 I-C2 fix: known OrderStatus values map deterministically;
    unknown values still fall back to "active" (FHIR valid) but the mapping is
    explicit so a future enum addition is caught by mypy strict / code review.
    """
    # All OrderStatus values exhaustively mapped (matches clinosim/types/encounter.py).
    # Adding a new OrderStatus enum value requires updating this mapping —
    # the comment + explicit listing surface the silent-no-op risk loud at
    # code review time (adversarial-1 I-C2).
    mapping = {
        "placed": "active",  # order placed but not yet acted on
        "accepted": "active",  # default operational state
        "in_progress": "active",  # in progress
        "resulted": "active",  # not normally used for MedicationRequest (lab path)
        "reviewed": "active",  # not normally used for MedicationRequest (lab path)
        "cancelled": "cancelled",
        "stopped": "stopped",  # PR3b-3: narrowed / de-escalated empirical
    }
    return mapping.get(status, "active")


def _mr_intent_from_order(order: dict, encounter_type: str = "") -> str:
    """Pick MedicationRequest.intent from the CIF Order (C2-14).

    Mirrors `_sr_intent_from_clinical_intent` (C1-16) for medications:
    - Chronic-management refills (clinical_intent contains "Follow-up" /
      "Chronic" / "Refill") → `instance-order` (a specific instance in an
      ongoing plan).
    - Discharge / take-home prescriptions → `original-order` (starts a new
      series of encounters at another provider).
    - Outpatient AMB encounter → `instance-order` (an instance on the
      ongoing outpatient chronic-management plan). CO-7:
      broaden the inference because upstream CIF rarely populates
      `clinical_intent`; encounter_type is a reliable proxy.
    - Default → `order`.
    """
    ci = str(order.get("clinical_intent", "") or "").lower()
    protocol = str(order.get("protocol_category", "") or "").lower()
    display = str(order.get("display_name", "") or "").lower()
    if "discharge" in ci or "discharge" in protocol or display.startswith("discharge:"):
        return "original-order"
    # RM-2: expanded to match clinosim's actual CIF phrasing
    # ("Home medication (continue)" → chronic-refill / "Outpatient follow-up"
    # → chronic follow-up).
    if any(
        k in ci
        for k in (
            "follow-up",
            "follow up",
            "chronic",
            "refill",
            "maintenance",
            "home medication",
            "continue",
            "outpatient follow",
        )
    ):
        return "instance-order"
    # CO-7: outpatient encounter type → instance-order.
    if encounter_type == "outpatient":
        return "instance-order"
    return "order"


def _drug_code_table(country_code: str, route: str) -> dict[str, str]:
    """Drug name → code table the builders match order names against: RxNorm
    for the US, the catalog's JP YJ product for ``route`` for JP (Issue #2347)."""
    if is_jp(country_code):
        return jp_drug_code_table(route)
    return load_code_mapping("drug", country_code)


def _case_insensitive_code(drug_codes: dict[str, str], name: str) -> tuple[str, str] | None:
    """``(code, key)`` for the mapping keys equal to ``name`` ignoring case,
    when they all carry one code; None when absent or ambiguous."""
    keys = [k for k in drug_codes if k.lower() == name.lower()]
    codes = {drug_codes[k] for k in keys}
    return (codes.pop(), keys[0]) if len(codes) == 1 else None


def _resolve_medication_concept(
    display_name_raw: str,
    order_code: str,
    country: str,
    route: str = "",
) -> tuple[dict[str, Any], str]:
    """Resolve a raw drug display name into a FHIR `medicationCodeableConcept`.

    SINGLE resolution point for drug name -> code -> display across every
    MedicationRequest builder. Extracted from `_build_medication_request` so the
    discharge-prescription builder (Issue #445) shares the same code_mapping lookup,
    JP HOT7/HOT9/HOT13/YJ system dispatch, tx-server-unverified-YJ downgrade to the
    eCS `nocoded` slice, and locale display resolution. Re-implementing any of that
    at a second call site is the duplication this helper exists to prevent.

    JP codes come from the drug catalog by drug and ``route``
    (``clinosim.codes.drugs.jp_drug_code_table``, Issue #2347): a YJ code names
    one product form, so the order route picks it, and ``order_code`` is not
    used for JP. A drug with no listed product for the route goes to the eCS
    ``nocoded`` slice.

    Returns `(medicationCodeableConcept, rate_adjustment_note)`. The second element is
    the continuous-infusion rate-adjustment suffix peeled off the display name (session
    45); callers append it to `dosageInstruction`, never to the medication text.
    """
    drug_name_raw = display_name_raw or "Unknown medication"
    # Strip protocol prefix (e.g. "DVT_prophylaxis:") from medicationCodeableConcept.text
    # The prefix goes to dosageInstruction note instead.
    drug_name_clean, protocol_category = strip_protocol_prefix(drug_name_raw)
    # split off any "increase/decrease rate by X%" continuous-infusion
    # adjustment suffix (disease YAML pattern for Day-N drip rate changes) so
    # the medicationCodeableConcept.text stays as a clean drug name and the
    # adjustment note can be appended to dosageInstruction.
    drug_name_clean, rate_adjustment_note = _split_rate_adjustment_suffix(drug_name_clean)
    drug_name = _localize_drug_name(drug_name_clean, country)
    # Strip dose info to get base drug name for code lookup (use cleaned name)
    base_name = drug_name_clean.split(" ")[0] if drug_name_clean else ""

    country_code = "JP" if is_jp(country) else "US"
    lang = resolve_lang(country_code)
    drug_codes = _drug_code_table(country_code, route)

    # C3-10: multi-word drug names (e.g. "Normal saline",
    # "Regular insulin") previously failed the base-only lookup because
    # `.split(" ")[0]` truncated at the first space. Try progressively shorter
    # prefixes so multi-word keys match too. Longest-match-wins.
    #
    # CO-8 (Chain 4 MHLW ingestion, 2026-07-11): also normalize underscores
    # to spaces before lookup — disease YAMLs sometimes ship `Normal_saline`
    # / `Regular_insulin` (underscore variant of the same key) and previously
    # missed the code_mapping match. Simultaneously honor Order.order_code
    # when the disease YAML already supplies an authoritative `code_yj` /
    # `code_rxnorm` (Order.order_code is set at place_admission_orders time).
    code_value = "" if is_jp(country_code) else (order_code or "")
    # Hoisted (Issue #852 follow-up): tokens are needed by BOTH the
    # code_mapping lookup (when order_code is empty) AND the JA multi-
    # word extension below (which must run regardless of order_code).
    normalized = drug_name_clean.replace("_", " ") if drug_name_clean else ""
    tokens = normalized.split(" ") if normalized else []
    if not code_value and drug_name_clean:
        for n_tokens in range(len(tokens), 0, -1):
            candidate = " ".join(tokens[:n_tokens])
            if candidate in drug_codes:
                code_value = drug_codes[candidate]
                base_name = candidate
                break
        # suffix-match fallback lets qualifier-prefixed aliases
        # ("Unfractionated Heparin", "Recombinant Insulin", "Regular Human Insulin"
        # 等) resolve to their base drug entry without duplicating the same code
        # under multiple keys in code_mapping_drug.yaml (which would violate the
        # test_no_two_drugs_share_a_rxcui integrity guard).
        if not code_value and len(tokens) > 1:
            for n_tokens in range(len(tokens) - 1, 0, -1):
                candidate = " ".join(tokens[-n_tokens:])
                if candidate in drug_codes:
                    code_value = drug_codes[candidate]
                    base_name = candidate
                    break
        if not code_value:
            code_value = drug_codes.get(base_name.replace("_", " "), "")
        if not code_value:
            # Issue #2134: chronic medications carry lowercase drug ids
            # ("sertraline"); fall back to a case-insensitive match when it
            # names exactly one code (exact-case keys still win above).
            for n_tokens in range(len(tokens), 0, -1):
                hit = _case_insensitive_code(drug_codes, " ".join(tokens[:n_tokens]))
                if hit:
                    code_value, base_name = hit
                    break
    # Issue #852: extend base_name to the longest multi-word prefix that has
    # a JA-dict entry (``Cefcapene pivoxil`` / ``Magnesium Sulfate`` /
    # ``Regular insulin`` / ``ICS/LABA inhaler`` / …), so ``.text``
    # localization hits multi-word product-family names. Only prefixes that
    # BEGIN with the already-chosen ``base_name`` token are considered —
    # this keeps dose / route / frequency tails from being folded into
    # ``base_name`` (the Issue #775 invariant that ``.text`` must not carry
    # dose text). Runs unconditionally on any drug_name_clean — must NOT be
    # gated on ``code_value`` being empty, because disease-YAML-supplied
    # Order.order_code (e.g. Magnesium Sulfate = MHLW HOT7 2355002) sets
    # ``code_value`` up front and would otherwise skip the extension,
    # leaving ``.text`` as the single-token "Magnesium".
    if tokens:
        from clinosim.locale.loader import load_narrative_display_dict as _load_ja_dict

        _ja_dict = _load_ja_dict()
        _first_token = tokens[0]
        for n_tokens in range(len(tokens), 1, -1):
            candidate = " ".join(tokens[:n_tokens])
            if candidate.lower() in _ja_dict and _first_token and candidate.startswith(_first_token):
                base_name = candidate
                break
    # C6-C7 residual sweep: fallback to `protocol_category` (the "TYPE:" prefix
    # stripped by `strip_protocol_prefix`, e.g. "lactulose:" / "antibiotic:" /
    # "antipyretic:"). Supportive Orders carry the drug identity in the type
    # field rather than the detail text — the classifier already trusts
    # this signal via MEDICATION_TYPE_HINTS, so the FHIR builder should too.
    if not code_value and protocol_category:
        _pc = protocol_category.strip().lower()
        # normalize common variants
        _pc = _pc.replace("_", " ").rstrip(":")
        for cand in (protocol_category, _pc, _pc.capitalize(), _pc.title()):
            if cand and cand in drug_codes:
                code_value = drug_codes[cand]
                break
    drug_system_key = system_key_for("drug", country_code)
    # Issue #775: `medicationCodeableConcept.text` must carry the CLEAN drug
    # name only — dose / route / frequency / duration / prn conditions belong
    # in `dosageInstruction`. `base_name` above already resolved to the
    # `drug_codes` key that matched (or, per the Issue #852 extension
    # below the loop, the longest multi-word JA-dict-mappable prefix).
    # It is the drug name without usage tokens, which is what
    # ``.text`` requires.
    clean_drug_name = _localize_drug_name(base_name, country) if base_name else drug_name
    display = code_lookup(drug_system_key, code_value, lang) if code_value else clean_drug_name
    if display == code_value:
        display = clean_drug_name
    # Issue #1766: strip trailing trade-name parenthetical (e.g.
    # ``Enoxaparin (Lovenox)`` → ``Enoxaparin``) on US output. The
    # RxNorm canonical display for a drug's ingredient CUI is the
    # generic name alone; the trade-name decoration in our yaml tables
    # exists for clinician-friendly search but is rejected by the HL7
    # FHIR validator against the RxNorm binding. JP output is left
    # unchanged — the JP tx-server accepts the Japanese 括弧付き
    # annotation form (``アセトアミノフェン（カロナール）``), and the YJ /
    # HOT CodeSystems have different display conventions.
    if not is_jp(country_code) and display:
        display = _TRADE_NAME_SUFFIX_RE.sub("", display).strip()
    # F-1: JP は code 形式ごとに HOT7/HOT9/HOT13/YJ URI へ dispatch。
    # US は従来通り RxNorm URI。
    if is_jp(country_code) and drug_system_key == "yj" and code_value:
        code_system = _resolve_jp_drug_system_uri(code_value)
    else:
        code_system = get_system_uri(drug_system_key)

    med_concept: dict[str, Any] = {"text": clean_drug_name}
    # #283 JP 出力で YJ system emit する場合、tx-server が
    # verify できない code(fragment 外)は nocoded fallback にダウングレード。
    # HAPI validator の VS binding error(594 件 v5)を解消しつつ薬剤名は
    # text field で保持。US path 及び verified YJ 及び HOT/RxNorm はそのまま
    # 通常 emit。
    # #283:downgrade は YJ-code URI 経由の code だけ対象。同 drug_system_key
    # ="yj" でも `_resolve_jp_drug_system_uri` が HOT7/HOT9/HOT13 に dispatch
    # した場合(全 HOT 系は別 CodeSystem)は対象外 = 通常 emit。
    _jp_yj_unverified = (
        is_jp(country_code)
        and drug_system_key == "yj"
        and bool(code_value)
        and code_system == _JP_YJ_CODE_URI
        and not _is_yj_code_valid(code_value)
    )
    if code_value and not _jp_yj_unverified:
        med_concept["coding"] = [
            {
                "system": code_system,
                "code": code_value,
                "display": display,
            }
        ]
    elif is_jp(country_code):
        # #291 / #283:JP-CLINS eCS(JP_MedicationRequest-eCS)は
        # `medication[x].coding` min=1 を要求。code_mapping にヒットしない
        # ED 特異薬(点眼薬 / 泌尿器系一次治療薬 等)+ #283 で tx-server
        # 未収録 YJ code は eCS の "nocoded" slice に fallback。
        # slice fixedUri は spec:
        # clinical-information-sharing#1.13.0/package/
        # CodeSystem-jp-eCS-medicationcode-nocoded-cs.json
        # #305 display は権威 CodeSystem 定義通り
        # "標準コードなし" 固定(NOCODED は 1 code / 1 display の required
        # binding 相当)。薬剤名は上の med_concept["text"] で保持。session
        # 59 の drug_name-in-display は v6 で 12,891 件 display mismatch
        # を発生させた regression。
        med_concept["coding"] = [
            {
                "system": _JP_MEDICATION_CODE_NOCODED_CS,
                "code": _JP_MEDICATION_CODE_NOCODED_CODE,
                "display": _JP_MEDICATION_CODE_NOCODED_DISPLAY,
            }
        ]

    return med_concept, rate_adjustment_note


def _clamp_authored_to_earliest_admin(authored_naive: str, earliest_admin_dt: str) -> str:
    """Return an ``authoredOn`` value guaranteed to be ≤ the earliest linked MA.

    Issue #967: some daily-loop paths anchor add-on medication orders to
    ``admission_time + timedelta(days=N, hours=10)`` while the MAR anchors its
    q6h/q8h admin grid to ``datetime(admission_date, hour, 0) + timedelta(days=N)``.
    When admission_time is late in the day (e.g. 16:37), the order's authored
    stamp lands the next calendar day while the day-N MA slots stay on the
    admission_date+N calendar day — producing MAs that ostensibly precede the
    parent MR by up to ~24h. FHIR-emit-only clamp: if any linked MA precedes
    the naive authoredOn, pull authoredOn back to (earliest MA − 1 minute) so
    the temporal invariant ``MR.authoredOn ≤ min(MA.effectiveDateTime)`` holds.

    CIF ``ordered_datetime`` is unchanged — this is a per-Issue #967 emit-layer
    fix (feedback: FHIR-emit bug の data patch は code 層で完結).
    """
    if not authored_naive:
        return earliest_admin_dt or ""
    if not earliest_admin_dt:
        return authored_naive
    # Lexical compare is safe here: both values are naive ISO-8601 strings
    # (`YYYY-MM-DDTHH:MM:SS[.ffffff]`) — TZ suffix is appended downstream by
    # ``_normalize_dt_fields``, not by the builders. Same TZ-less shape → the
    # string ordering matches the chronological ordering.
    if earliest_admin_dt >= authored_naive:
        return authored_naive
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    for _fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            _parsed = _dt.strptime(earliest_admin_dt, _fmt)
        except ValueError:
            continue
        return (_parsed - _td(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S")
    # Unparseable value — better to emit the raw earliest_admin_dt than to keep
    # the known-wrong authored_naive, so the invariant still holds.
    return earliest_admin_dt


# ============================================================
# _build_medication_request sub-step helpers (hardcoded-review Phase B6)
# ============================================================
# Three logical sub-steps extracted from the 298-line
# _build_medication_request orchestrator:
#   * _resolve_mr_status_and_intent — status + intent + stop-order gate
#   * _build_mr_dispense_request    — dispenseRequest fragment
#   * _build_mr_notes               — stop-order rationale + order notes
# Each helper takes explicit parameters; the main function stays as
# the orchestrator wiring them together.


def _resolve_mr_status_and_intent(
    order: dict,
    encounter_type: str,
    structural_key: str,
    is_home_med: bool,
    is_episodic: bool,
) -> tuple[str, str, bool]:
    """Return (status, intent, is_stop_order) for an MR.

    Encodes the full status / intent dispatch described inline in
    `_build_medication_request`:
      * intent via `_mr_intent_from_order` (C2-14).
      * status via `_map_order_status_to_fhir`, promoted to
        ``completed`` when the course has an end_datetime, when the
        outpatient encounter closes, when the inpatient order is
        episodic (RM-2), or when the emergency encounter closes
        (C7a / #1099) and the order is not a home-med continuation.
      * `is_stop_order` detected via MED_STOP_ORDER_ID_MARKER on the
        structural key; when true the status is clamped to ``stopped``
        (Issue #436 F1'; JP eCS re-overrides to ``completed`` later).
    """
    intent_val = _mr_intent_from_order(order, encounter_type)
    status_val = _map_order_status_to_fhir(order.get("status", ""))
    if status_val == "active" and (
        order.get("end_datetime")
        or (encounter_type == "outpatient" and order.get("encounter_id"))
        or (is_episodic and encounter_type == "inpatient" and order.get("encounter_id"))
        or (encounter_type == "emergency" and order.get("encounter_id") and not is_home_med)
    ):
        status_val = "completed"
    is_stop_order = MED_STOP_ORDER_ID_MARKER in structural_key
    if is_stop_order:
        status_val = "stopped"
    return status_val, intent_val, is_stop_order


def _build_mr_dispense_request(
    order: dict,
    authored: str,
    is_home_med: bool,
    encounter_type: str,
    country: str,
) -> dict[str, Any]:
    """Return the MR.dispenseRequest fragment.

    Carries validityPeriod (clamped `authoredOn` to CIF `end_datetime`
    when present), `numberOfRepeatsAllowed` default (3 chronic / 0
    acute / 0 inpatient-ED), and `expectedSupplyDuration` for home-
    med / outpatient Rx windows (Issue #1175 JP-CLINS eCS fix).
    """
    _end = order.get("end_datetime", "") or ""
    disp: dict[str, Any] = {}
    if authored and _end:
        disp["validityPeriod"] = {"start": str(authored), "end": str(_end)}
    elif authored:
        disp["validityPeriod"] = {"start": str(authored)}
    if is_home_med:
        disp["numberOfRepeatsAllowed"] = 3
    elif encounter_type == "outpatient":
        disp["numberOfRepeatsAllowed"] = 0
    elif encounter_type in ("inpatient", "emergency"):
        disp["numberOfRepeatsAllowed"] = 0  # inpatient/ED dispense once per order
    _days = order.get("days_supply") or 0
    if not _days and (is_home_med or encounter_type == "outpatient"):
        _days = 30  # standard chronic-Rx cycle
    if _days and _days > 0:
        disp["expectedSupplyDuration"] = ucum_quantity(
            int(_days),
            _SUPPLY_DURATION_UNIT_JP if is_jp(country) else _SUPPLY_DURATION_UNIT_US,
            code=_SUPPLY_DURATION_CODE,
        )
    return disp


def _build_mr_notes(order: dict, is_stop_order: bool) -> list[dict[str, Any]]:
    """Compose `MedicationRequest.note` entries.

    Combines the Issue #436 F3 stop-order rationale (STOP orders carry
    `clinical_intent` naming WHY the med was discontinued) and the
    Issue #1066 drug_safety order-level note dicts (CPOE-style
    moderate-DDI cautions). Returns an empty list when neither source
    is populated so the orchestrator skips the field.
    """
    notes: list[dict[str, Any]] = []
    if is_stop_order:
        _stop_intent = str(order.get("clinical_intent", "") or "").strip()
        if _stop_intent:
            notes.append({"text": _stop_intent})
    _order_notes = order.get("notes")
    if _order_notes:
        for entry in _order_notes:
            if isinstance(entry, dict) and entry.get("text"):
                notes.append(entry)
    return notes


def _build_medication_request(
    order: dict,
    patient_id: str,
    country: str,
    encounter_id: str = "",
    primary_dx_code: str = "",
    encounter_type: str = "",
    rp_number: str = "1",
    order_in_rp: str = "1",
    chronic_condition_codes: list[str] | None = None,
    earliest_admin_dt: str = "",
) -> dict:
    """Build FHIR MedicationRequest resource.

    rp_number / order_in_rp (clinosim_feedback P1-4): JP Core
    JP_MedicationRequest.identifier:rpNumber と :orderInRp slice を満たす
    ための per-order identifier 値。caller は 1 encounter 内の医薬品
    orders に対して同じ rp_number(処方単位)+ 連番 order_in_rp を
    与える。同一 order の MedicationRequest と MedicationAdministration
    は同じ (rp_number, order_in_rp) を使い、両者の紐付けが取れる。
    """
    med_concept, rate_adjustment_note = _resolve_medication_concept(
        order.get("display_name", "Unknown medication"),
        order.get("order_code", "") or "",
        country,
        route=str(order.get("route", "") or ""),
    )
    country_code = "JP" if is_jp(country) else "US"

    # ID: order_id は fix 0 で encounter-scoped 化された
    # (grep で "ORD-{encounter_id}-..." pattern に統一済)ので、そのまま
    # resource id として使えば globally unique。以前の "prepend encounter_id"
    # 実装は二重 prefix を作り 64-char 制限を超過(iris4h-ai HAPI 732 件)
    # + Endpoint/imgst/imgrpt double-prefix と同一 class。
    #
    # Issue #349 Phase 1b: antibiotic MedicationRequest だけは
    # opaque id `mr-{sha256(order_id)[:12]}` に切替。structural key(元の
    # compound Order.order_id)は identifier[] に round-trip 保存。PR #348 の
    # tactical fix(-narrowed → -n)で 64-char 逸脱は塞いだが、compound-id-
    # as-key pattern そのものが root cause — FHIR R4 の Resource.id は
    # opaque logical identifier という intent に沿わせる。Phase 1b (PR #357)
    # では antibiotic 限定だったが、Issue #853 で非 HAI 全 MR + MA cross-ref
    # に拡張(_resolve_mr_id は unconditional opaque)。
    _structural_key = order.get("order_id") or str(uuid.uuid4())
    resource_id = _resolve_mr_id(_structural_key)

    # Status / intent / stop-order resolution (hardcoded-review Phase B6).
    # The helper owns the full C2-14 / C2-16 / RM-2 / C7a / Issue #436 F1'
    # dispatch; see its docstring for the clause-by-clause mapping.
    medication_intent = order.get("medication_intent", "")  # Issue #349 Phase 2
    _ci_lower = str(order.get("clinical_intent", "") or "").lower()
    _episodic_kw = ("supportive:", "ed treatment:", "day ", "dvt_prophylaxis", "antibiotic", "escalation")
    _is_home_med = "home medication" in _ci_lower
    _is_episodic = (not _is_home_med) and any(kw in _ci_lower for kw in _episodic_kw)
    status_val, intent_val, _is_stop_order = _resolve_mr_status_and_intent(
        order, encounter_type, _structural_key, _is_home_med, _is_episodic
    )
    resource: dict[str, Any] = {
        "resourceType": "MedicationRequest",
        "id": resource_id,
        # chain #2: JP Core MedicationRequest profile.
        **_build_medication_request_meta(country_code, medication_intent),
        # clinosim_feedback P1-4: JP_MedicationRequest.identifier
        # slice `rpNumber`(処方内 Rp グループ番号)+ `orderInRp`(Rp 内医薬品
        # 順序)の 2 slice を JP output で emit。system URL は JP Core 1.2.0
        # の StructureDefinition から取得(mhlw/IdSystem/Medication-RPGroupNumber
        # + MedicationAdministrationIndex)。
        #
        # Issue #349 Phase 1b + Issue #853: MR は opaque `.id` の
        # 逆引き用 structural-key identifier を先頭に追加(全 MR 対象)。
        # JP-only の rpNumber / orderInRp slice との共存は list 連結で実現。
        **_build_medication_request_identifiers(
            _structural_key,
            country_code,
            rp_number,
            order_in_rp,
        ),
        "status": status_val,
        "intent": intent_val,
        "medicationCodeableConcept": med_concept,
        "subject": patient_ref(patient_id),
        # Issue #967: clamp to (min linked MA − 1 min) when the naive
        # ordered_datetime is later than the earliest administration; see
        # `_clamp_authored_to_earliest_admin` for the day-N add-on root cause.
        "authoredOn": _clamp_authored_to_earliest_admin(
            str(order.get("ordered_datetime", "") or ""), earliest_admin_dt
        ),
    }
    # CY6-22 (Chain-6): MedicationRequest.category — HL7 medicationrequest-
    # category (inpatient / outpatient / community / discharge). Issue #548:
    # canonical decision tree extracted to `_derive_mr_category` — shared with
    # `_build_discharge_medication_request`.
    _is_discharge_intent = "discharge" in _ci_lower
    _cat_code, _cat_display = _derive_mr_category(
        encounter_type=encounter_type,
        is_home_med=_is_home_med,
        is_episodic=_is_episodic,
        is_discharge_intent=_is_discharge_intent,
    )
    resource["category"] = _build_category_block(_cat_code, _cat_display)

    # Encounter reference
    enc_ref = order.get("encounter_id", "") or encounter_id
    if enc_ref:
        resource["encounter"] = encounter_ref(enc_ref)

    # Requester (ordering physician)
    if order.get("ordered_by"):
        resource["requester"] = {"reference": f"Practitioner/{order['ordered_by']}"}
        # CY8-17 fix: MR.recorder = 記録者(オーダー入力者)。
        # clinosim では requester と同一 practitioner が入力する運用モデル、
        # ordered_by を fallback として emit(100% coverage)。
        resource["recorder"] = {"reference": f"Practitioner/{order['ordered_by']}"}

    # CY8-18 fix: MR.courseOfTherapyType — acute /
    # continuous / seasonal 分類。Rule is `_course_for_order` (Issue #548
    # partial extraction); the sibling `_build_discharge_medication_request`
    # uses `_course_for_discharge` instead. Displays are the spec-canonical
    # HL7 terminology R4 forms — "Continuous long term therapy" (no hyphen).
    _course_code, _course_display = _course_for_order(_is_home_med, _cat_code)
    resource["courseOfTherapyType"] = _build_course_of_therapy_block(_course_code, _course_display)

    # CY7-08 (Chain-7): MR.priority — derive from Order.urgency (routine /
    # urgent / stat / asap). FHIR R4 valueset: routine | urgent | asap | stat.
    _urgency = str(order.get("urgency", "") or "").lower()
    _priority_map = {
        "routine": "routine",
        "urgent": "urgent",
        "stat": "stat",
        "asap": "asap",
        "": "routine",  # empty → routine default
    }
    resource["priority"] = _priority_map.get(_urgency, "routine")

    # Dosage instruction
    dosage = build_dosage_instruction(order, country=country)
    # append any rate-adjustment note peeled off drug_name so the
    # continuous-infusion adjustment intent (e.g. "increase rate by 20%") lives
    # in dosageInstruction where it belongs — not in medicationCodeableConcept.text.
    if rate_adjustment_note:
        rate_note_localized = _localize_rate_adjustment(rate_adjustment_note, country)
        if dosage is None:
            dosage = {"text": rate_note_localized}
        else:
            existing = str(dosage.get("text", "") or "").strip()
            dosage["text"] = f"{existing} ({rate_note_localized})".strip() if existing else rate_note_localized
    if dosage:
        resource["dosageInstruction"] = [dosage]

    # Reason reference (link to primary diagnosis Condition). Chronic-primary
    # encounters resolve to the patient-scoped chronic Condition; acute
    # ones keep the encounter-scoped id.
    reason = order.get("reason_condition", "") or primary_dx_code
    if reason:
        from clinosim.modules.output.fhir_r4.conditions.primary_ref import (
            primary_condition_ref_from_codes,
        )

        cond_ref = primary_condition_ref_from_codes(primary_dx_code, chronic_condition_codes, patient_id, encounter_id)
        resource["reasonReference"] = [
            {
                "reference": f"Condition/{cond_ref}",
            }
        ]

    # dispenseRequest — composed by _build_mr_dispense_request.
    # Validity period uses the clamped authoredOn (Issue #967).
    # Encodes C4-15 outpatient/discharge + CY7-07 inpatient tracks and
    # Issue #1175 expectedSupplyDuration JP-CLINS eCS workaround.
    _authored = _clamp_authored_to_earliest_admin(str(order.get("ordered_datetime", "") or ""), earliest_admin_dt)
    resource["dispenseRequest"] = _build_mr_dispense_request(order, _authored, _is_home_med, encounter_type, country)

    # C5-23: MedicationRequest.substitution (0..1)
    # for generic substitution allowance. JP GE 促進 policy allows generic
    # substitution for chronic outpatient scripts unless explicitly
    # marked "brand only" — default `allowed = true` for outpatient/home-med.
    if encounter_type == "outpatient" or _is_home_med:
        resource["substitution"] = {"allowedBoolean": True}

    # Notes — composed by _build_mr_notes. Combines the Issue #436 F3
    # stop-order rationale with the Issue #1066 drug_safety order-level
    # DDI caution dicts. Only emitted when at least one entry exists so
    # the resource shape stays byte-identical for regular orders.
    _notes = _build_mr_notes(order, _is_stop_order)
    if _notes:
        resource["note"] = _notes

    return resource


def _supply_duration_days(raw: Any) -> int | None:
    """Return a positive day count, or None when the CIF value is an open-ended sentinel.

    Disease YAMLs express "no fixed supply duration" two different ways —
    `duration_days: 0   # chronic` (liver_cirrhosis_decompensated,
    atrial_fibrillation_rvr) and `duration_days: ongoing`
    (diabetic_ketoacidosis) — so the raw value is not always a usable number.
    Emitting `{"value": 0}` would assert a zero-day supply, and a JSON string in a
    FHIR `Duration.value` (type `decimal`) is a type violation. Both profiles put
    `expectedSupplyDuration` at min=0, so omitting the element is spec-legal and is
    the honest reading of a sentinel: the duration is unknown, not zero.
    """
    if isinstance(raw, bool):  # bool is an int subclass — never a day count
        return None
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return None
    return days if days > 0 else None


# ============================================================
# _build_discharge_medication_request sub-step helpers (Phase B7)
# ============================================================


def _build_discharge_rx_dispense(authored_on: str, duration_days: int | None, country_code: str) -> dict[str, Any]:
    """Compose MR.dispenseRequest for a discharge prescription item.

    Carries validityPeriod.start = authored_on and
    expectedSupplyDuration when the CIF supplied `duration_days`.
    `numberOfRepeatsAllowed` is intentionally absent (CIF carries no
    refill count — see the original inline comment).
    """
    dispense: dict[str, Any] = {}
    if authored_on:
        dispense["validityPeriod"] = {"start": authored_on}
    if duration_days is not None:
        dispense["expectedSupplyDuration"] = ucum_quantity(
            duration_days,
            _SUPPLY_DURATION_UNIT_JP if is_jp(country_code) else _SUPPLY_DURATION_UNIT_US,
            code=_SUPPLY_DURATION_CODE,
        )
    return dispense


def _build_discharge_rx_dosage(
    item: Any,
    dose: str,
    route: str,
    drug_name: str,
    rate_adjustment_note: str,
    country: str,
) -> dict[str, Any]:
    """Compose MR.dosageInstruction[0] for a discharge prescription item.

    Order of operations preserved verbatim from the inline site:
      1. route via `build_route_concept`
      2. text — authored `dose_ja` / `dose_en` wins (Issue #476),
         else auto-derived from `dose` + `rate_adjustment_note` with
         `_localize_dosage_terms` applied
      3. doseAndRate.doseQuantity + timing from `parse_dose_string` +
         `resolve_timing_repeat` (Issue #920 / #1348), only when the
         author did NOT supply authored_text (preserves "既存の
         インスリンレジメンどおり" instruction-only semantics)
      4. IV augmentation via `augment_iv_dosage_with_rate`
         (Issue #966)

    Returns the dosage dict (empty when none of the sources yield a
    field — orchestrator skips the element in that case).
    """
    dosage: dict[str, Any] = {}
    route_concept = build_route_concept(route, country)
    if route_concept:
        dosage["route"] = route_concept
    # Issue #476: authored dose_ja / dose_en wins over auto-derived text.
    dose_text_ja = str(get_attr_or_key(item, "dose_ja", "") or "")
    dose_text_en = str(get_attr_or_key(item, "dose_en", "") or "")
    authored_text = dose_text_ja if is_jp(country) else dose_text_en
    if authored_text:
        dosage["text"] = authored_text
    else:
        dose_parts = [p for p in (dose, rate_adjustment_note) if p]
        if dose_parts:
            dose_text = " ".join(dose_parts)
            dosage["text"] = _localize_dosage_terms(dose_text, resolve_lang(country))

    # Issue #920 / #1348: emit structured doseAndRate + timing from the
    # same dose/frequency fields. Skipped when authored_text is set so
    # instruction-only prescriptions (e.g. "既存のインスリンレジメン
    # どおり") don't get an inferred numeric dose.
    if not authored_text and dose:
        from clinosim.modules.order.engine import parse_dose_string
        from clinosim.modules.output.fhir_r4.lib.common import resolve_timing_repeat

        _parsed = parse_dose_string(dose)
        _qty = _parsed.get("dose_quantity")
        _unit = _parsed.get("dose_unit", "")
        if _qty is not None and _unit:
            dosage["doseAndRate"] = [{"doseQuantity": ucum_quantity(_qty, _unit)}]
        _freq_raw = str(get_attr_or_key(item, "frequency", "") or "").strip()
        if not _freq_raw and _parsed.get("frequency"):
            _freq_raw = str(_parsed["frequency"])
        _freq_per_day = _parsed.get("frequency_per_day")
        _repeat, _is_prn = resolve_timing_repeat(_freq_raw, _freq_per_day)
        if _repeat:
            dosage["timing"] = {"repeat": _repeat}
        if _is_prn:
            dosage["asNeededBoolean"] = True

    # Issue #966: IV augmentation (continuous → rateQuantity; bolus →
    # timing.repeat.duration). Per-drug defaults from
    # iv_infusion_defaults.yaml.
    from clinosim.modules.output.fhir_r4.lib.common import (
        augment_iv_dosage_with_rate as _augment_iv,
    )

    _augment_iv(dosage, dose_text=dose or "", route=route, display_name=drug_name or "")
    return dosage


def _build_discharge_medication_request(
    item: Any,
    patient_id: str,
    country: str,
    encounter_id: str,
    encounter_type: str,
    seq: int,
    authored_on: str,
    prescriber_id: str = "",
) -> dict:
    """Build a MedicationRequest for one `discharge_prescription.items[]` entry (Issue #445).

    A discharge prescription is not an inpatient Order: it has no `order_id`, no
    structured `dose_quantity` / `frequency`, and no `status` / `urgency`. Adapting it
    into `_build_medication_request` would mean threading empty values through every
    Order-specific branch, so this is a sibling builder that shares the pieces that are
    genuinely common — `_resolve_medication_concept` for the drug coding,
    `_build_medication_request_meta` for profiles, `_build_medication_request_identifiers`
    for the JP rpNumber / orderInRp slices, and `build_route_concept` for the route.

    `identifier:requestIdentifier` is deliberately NOT written here. The JP walker in
    `fhir_r4_adapter._apply_jp_clins_profile`'s sibling pass derives it from
    `resource["id"]` and skips when the system URI is already present, so hand-writing it
    would stop that derivation. `rpNumber` / `orderInRp` are the opposite case — the
    walker never adds them and JP Core requires both, so the builder must.

    `seq` is 1-based within the prescription and drives both the id suffix and
    `orderInRp`.
    """
    drug_name = str(get_attr_or_key(item, "drug_name", "") or "")
    dose = str(get_attr_or_key(item, "dose", "") or "")
    route = str(get_attr_or_key(item, "route", "") or "")
    duration_days = _supply_duration_days(get_attr_or_key(item, "duration_days", None))

    country_code = "JP" if is_jp(country) else "US"
    med_concept, rate_adjustment_note = _resolve_medication_concept(drug_name, "", country, route=route)

    # Issue #853: opaque id. Structural key = same compound the pre-#853 id
    # encoded (``{encounter_id}-{seq:02d}``) so downstream consumers can
    # recover it from identifier[] (Task 2 unconditional round-trip). Prefix
    # retained (rxdc- vs rxopd-) so a discharge script and an outpatient
    # renewal stay visually distinguishable in the URL — Issue #445 intent.
    _structural_key = f"{encounter_id}-{seq:02d}"
    _resolve = _resolve_dc_rx_id if encounter_type == "inpatient" else _resolve_opd_rx_id
    resource_id = _resolve(_structural_key)

    # A take-home script is "on" once written; the JP walker overwrites both fields to
    # the eCS patternCodes (`completed` / `order`) so these values only reach US output.
    resource: dict[str, Any] = {
        "resourceType": "MedicationRequest",
        "id": resource_id,
        **_build_medication_request_meta(country_code, ""),
        # Round-trip the compound structural key (NOT resource_id — the digest
        # is one-way). Consumers recover ``{encounter_id}-{seq:02d}`` from
        # identifier[] under MEDICATION_REQUEST_KEY_SYSTEM.
        #
        # p=500 review finding (session 89): the inpatient-orders MR
        # builder (`_bb_medication_requests` in `lib/inline_bb.py`) uses
        # `rpNumber="1"` with `orderInRp` counting 1..N per encounter.
        # Prior to this fix, the discharge builder also used
        # `rpNumber="1"` with its own `seq` counter restarting from 1,
        # so on an inpatient encounter with both inpatient orders AND a
        # discharge prescription the two MR sets produced colliding
        # (rpNumber, orderInRp) pairs (e.g. both an inpatient MR and a
        # discharge MR would have `(rp=1, orderInRp=3)`), violating the
        # JP-CLINS `orderInRp` uniqueness expectation. Model the
        # discharge prescription as a distinct Rp group (`rpNumber=2`)
        # on inpatient encounters. Outpatient renewal has no inpatient
        # orders to collide with, so `rpNumber=1` remains correct. ED
        # treatment orders take Rp group 1 too, so an ED take-home
        # prescription (Issue #2155) is group 2 as on inpatient discharge.
        **_build_medication_request_identifiers(
            _structural_key,
            country_code,
            "2" if encounter_type in ("inpatient", "emergency") else "1",
            str(seq),
        ),
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": med_concept,
        "subject": patient_ref(patient_id),
        "authoredOn": authored_on,
    }
    if encounter_id:
        resource["encounter"] = encounter_ref(encounter_id)
    if prescriber_id:
        resource["requester"] = {"reference": f"Practitioner/{prescriber_id}"}
        resource["recorder"] = {"reference": f"Practitioner/{prescriber_id}"}

    # Issue #548: canonical decision tree extracted to `_derive_mr_category`.
    # The discharge builder's caller identity implies is_discharge_intent=True
    # and no episodic-order / home-medication semantics — DischargeRxItem lacks
    # the clinical_intent tag that the order path uses to detect these. Pre-#548
    # this path used a 2-branch inline decision that silently misclassified
    # emergency-encounter discharge scripts as `community` instead of the
    # HL7-canonical `outpatient`; the unified helper now emits the correct value.
    _is_discharge = encounter_type == "inpatient"
    cat_code, cat_display = _derive_mr_category(
        encounter_type=encounter_type,
        is_home_med=False,
        is_episodic=False,
        is_discharge_intent=True,
    )
    resource["category"] = _build_category_block(cat_code, cat_display)

    # Rule = `_course_for_discharge` (Issue #548 partial extraction).
    # Non-discharge (outpatient renewal) is continuous by definition;
    # an open-ended supply (`0` / `ongoing` sentinels) means maintenance
    # therapy handed over at discharge, so it stays continuous too — a
    # lifelong anticoagulant does not become a short course by being
    # handed over at discharge. Sibling `_build_medication_request` uses
    # `_course_for_order` instead.
    course_code, course_display = _course_for_discharge(_is_discharge, duration_days)
    resource["courseOfTherapyType"] = _build_course_of_therapy_block(course_code, course_display)

    # dispenseRequest — composed by _build_discharge_rx_dispense.
    # `numberOfRepeatsAllowed` intentionally absent (CIF carries no refill count).
    dispense = _build_discharge_rx_dispense(authored_on, duration_days, country_code)
    if dispense:
        resource["dispenseRequest"] = dispense

    # dosageInstruction — composed by _build_discharge_rx_dosage.
    # Order: route → authored_text wins over auto-derived (Issue #476) →
    # doseAndRate + timing from parse_dose_string (Issue #920 / #1348) →
    # IV augmentation (Issue #966). dosageInstruction is OMITTED entirely
    # when the CIF has neither dose nor route — items transcribed from
    # `patient.current_medications` lose both upstream (Issue #452), and
    # `_apply_jp_clins_profile` withholds the eCS profile from those
    # resources so eCS min=1 is not violated.
    dosage = _build_discharge_rx_dosage(item, dose, route, drug_name, rate_adjustment_note, country)
    if dosage:
        resource["dosageInstruction"] = [dosage]

    return resource


# ============================================================
# _build_medication_admin sub-step helpers (hardcoded-review Phase B5)
# ============================================================
# The historical _build_medication_admin was 408 lines; three logical
# sub-steps are extracted as free-standing helpers so the orchestrator
# stays readable:
#   * _build_ma_dosage_block — dose/route/rate composition + mad-1 gate
#   * _build_ma_reason_block — reasonReference + reasonCode wiring
#   * _build_ma_device_block — infusion-pump Device reference
# Each helper receives explicit parameters (no shared mutable state)
# and returns the fragment the orchestrator attaches. Behavior is
# byte-identical to the pre-refactor function.


def _build_ma_dosage_block(
    mar: dict,
    parent_order: dict | None,
    drug_name_raw: str,
    drug_name_clean: str,
    drug_name: str,
    rate_adjustment_note: str,
    country: str,
) -> dict[str, Any] | None:
    """Compose the ``MedicationAdministration.dosage`` fragment.

    Returns the fragment when it carries any of: structured dose,
    rateQuantity, route, or a meaningful text (mad-1 SHOULD-emit gate
    per Issue #851). Returns ``None`` when nothing meaningful was
    composed so the orchestrator can omit the element entirely.
    """
    _mar_dose_raw = str(mar.get("dose", "") or "").strip()
    _mar_dose_is_drug_name = _mar_dose_raw == drug_name_raw or _mar_dose_raw == drug_name_clean
    if not _mar_dose_raw or _mar_dose_is_drug_name:
        # Backfill: use parent Order.dose_quantity/unit if we have them,
        # else derive from route + frequency as a route-aware summary.
        _po = parent_order or {}
        _pd_qty = _po.get("dose_quantity")
        _pd_unit = _po.get("dose_unit", "") or ""
        _pd_freq = _po.get("frequency", "") or ""
        _pd_route = _po.get("route", "") or mar.get("route", "") or ""
        _text_parts: list[str] = []
        if _pd_qty is not None and _pd_unit:
            _q_txt = f"{int(_pd_qty)}" if isinstance(_pd_qty, float) and _pd_qty.is_integer() else str(_pd_qty)
            _text_parts.append(f"{_q_txt}{_pd_unit}")
        if _pd_route:
            _text_parts.append(_pd_route)
        if _pd_freq:
            _text_parts.append(_pd_freq)
        dose_text = " ".join(_text_parts) if _text_parts else _mar_dose_raw
        dose_str = dose_text
    else:
        dose_text = _mar_dose_raw
        dose_str = _mar_dose_raw
    parsed = _parse_dose_for_mar(dose_str or drug_name)
    # C3 / Issue #1089: bolus IV drugs backfill from parent Order when
    # the MAR text parse found no numeric dose_quantity.
    if parsed.get("dose_quantity") is None:
        _po_backfill = parent_order or {}
        _po_qty = _po_backfill.get("dose_quantity")
        _po_unit = _po_backfill.get("dose_unit", "") or ""
        if _po_qty is not None and _po_unit:
            parsed["dose_quantity"] = float(_po_qty)
            parsed["dose_unit"] = _po_unit
            _q_txt = f"{int(_po_qty)}" if isinstance(_po_qty, float) and _po_qty.is_integer() else str(_po_qty)
            _dose_summary = f"{_q_txt}{_po_unit}"
            if _dose_summary not in dose_text:
                dose_text = f"{_dose_summary} {dose_text}".strip() if dose_text.strip() else _dose_summary
    # Attach rate-adjustment note peeled off drug_name to dose_text so
    # continuous-infusion titration intent surfaces in the dosage record.
    if rate_adjustment_note:
        rate_note_localized = _localize_rate_adjustment(rate_adjustment_note, country)
        dose_text = f"{dose_text} ({rate_note_localized})".strip() if dose_text.strip() else rate_note_localized
    # Issue #472: localize at the assignment only — `dose_text` itself stays English
    # because the continuous-infusion detection below matches on "CONTINUOUS" / "DRIP".
    dosage: dict[str, Any] = {"text": _localize_dosage_terms(dose_text, resolve_lang(country))}
    if parsed.get("dose_quantity") is not None and parsed.get("dose_unit"):
        dosage["dose"] = ucum_quantity(parsed["dose_quantity"], parsed["dose_unit"])
    # Rate for continuous infusions
    if "CONTINUOUS" in dose_text.upper() or "DRIP" in dose_text.upper() or "/h" in dose_text:
        rate_value = parsed.get("dose_quantity") or 1
        rate_unit = parsed.get("dose_unit", "mL") + "/h"
        dosage["rateQuantity"] = ucum_quantity(rate_value, rate_unit)

    # Issue #1067 B2: IV-route drugs missing a structured dose get the same
    # catalog-based rate/duration augmentation the MR builder gets.
    from clinosim.modules.output.fhir_r4.lib.common import (
        augment_iv_dosage_with_rate as _augment_iv,
    )

    _augment_iv(
        dosage,
        dose_text=dose_text or "",
        route=mar.get("route") or parsed.get("route"),
        display_name=drug_name_clean or "",
    )
    # Route — shared helper so the MAR and MR paths cannot drift (Issue #458).
    route_concept = build_route_concept(mar.get("route") or parsed.get("route"), country)
    if route_concept:
        dosage["route"] = route_concept
    # Issue #851: mad-1 SHOULD-emit gate. Emit dosage when it carries
    # at least a route or a meaningful non-empty text, OR has structured
    # dose / rate. Text that merely repeats the drug name is treated as
    # empty.
    _dosage_text_val = str(dosage.get("text") or "").strip()
    _text_meaningful = bool(_dosage_text_val) and _dosage_text_val not in (
        drug_name_raw,
        drug_name_clean,
        drug_name,
    )
    if "dose" in dosage or "rateQuantity" in dosage or dosage.get("route") or _text_meaningful:
        return dosage
    return None


def _build_ma_reason_block(
    primary_dx_code: str,
    chronic_condition_codes: list[str] | None,
    patient_id: str,
    encounter_id: str,
    country_code: str,
    patient_sex: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """Compose (reasonReference, reasonCode) MA fragments from the
    primary diagnosis code. Returns ``None`` when ``primary_dx_code``
    is empty so the orchestrator can skip both fields.
    """
    if not primary_dx_code:
        return None
    from clinosim.modules.output.fhir_r4.conditions.primary_ref import (
        primary_condition_ref_from_codes,
    )

    cond_ref = primary_condition_ref_from_codes(primary_dx_code, chronic_condition_codes, patient_id, encounter_id)
    reason_reference = [{"reference": f"Condition/{cond_ref}"}]
    # Issue #350: route through system_key_for("diagnosis", country).
    _icd_system = get_system_uri(system_key_for("diagnosis", country_code))
    _mapped_dx_code = map_diagnosis_code(primary_dx_code, country_code, sex=patient_sex)
    reason_code = [
        {
            "coding": [
                {
                    "system": _icd_system,
                    "code": _mapped_dx_code,
                }
            ],
        }
    ]
    return reason_reference, reason_code


def _build_ma_device_block(
    mar: dict,
    parsed_route: str | None,
    country_code: str,
) -> list[dict[str, Any]] | None:
    """Return the infusion-pump ``device`` fragment for continuous-IV
    administrations, or ``None`` to skip the element.

    Gates on the CANONICAL route key (alias-aware via
    ``canonicalize_route``) so JP-localized ``静注`` + alias-prefixed
    ``INTRAVENOUS`` both route through the IV branch — see Issue
    #479 dual-slot rationale in the original inline comment.
    """
    _canonical_route = canonicalize_route(mar.get("route") or parsed_route)
    _dose_text_up = (mar.get("dose") or "").upper()
    _is_infusion = _canonical_route == "IV" and (
        "CONTINUOUS" in _dose_text_up or "DRIP" in _dose_text_up or "/H" in _dose_text_up
    )
    if not _is_infusion:
        return None
    return [
        {
            "reference": "Device/dev-infusion-pump",
            "display": "汎用輸液ポンプ" if is_jp(country_code) else "Generic infusion pump",
        }
    ]


def _build_medication_admin(
    mar: dict,
    patient_id: str,
    index: int,
    country: str = "US",
    encounter_id: str = "",
    primary_dx_code: str = "",
    rp_number: str = "1",
    order_in_rp: str = "1",
    chronic_condition_codes: list[str] | None = None,
    parent_order: dict | None = None,
    patient_sex: str = "",  # Issue #957: threads sex to sex-conditional ICD-10-CM mapping (C50)
) -> dict:
    """Build FHIR MedicationAdministration resource.

    rp_number / order_in_rp (clinosim_feedback P1-4): 対応する
    parent MedicationRequest と同じ値を渡すことで JP Core
    JP_MedicationAdministration.identifier slice を満たす。caller は同
    encounter 内で MR と同じ per-order 連番を割当てる。
    """
    drug_name_raw = mar.get("drug_name", "")
    drug_name_clean, protocol_category = strip_protocol_prefix(drug_name_raw)
    # peel off rate-adjustment suffix (see _build_medication_request).
    drug_name_clean, rate_adjustment_note = _split_rate_adjustment_suffix(drug_name_clean)
    drug_name = _localize_drug_name(drug_name_clean, country)
    base_name = drug_name_clean.split(" ")[0] if drug_name_clean else ""
    country_code = "JP" if is_jp(country) else "US"
    lang = resolve_lang(country_code)
    drug_codes = _drug_code_table(country_code, str(mar.get("route", "") or ""))
    # C3-10: longest-match-wins for multi-word keys.
    # CO-8 (Chain 4 2026-07-11): normalize underscores + honor the MAR-carried
    # order code for the US. JP codes come from the catalog by drug and route
    # (Issue #2347), never from a MAR-carried code.
    code_value = "" if is_jp(country_code) else (mar.get("code_yj", "") or "")
    # Hoisted (Issue #852 follow-up): tokens are needed by BOTH the
    # code_mapping lookup and the JA multi-word extension below (which
    # must run regardless of code_value — see MR builder for full rationale).
    normalized = drug_name_clean.replace("_", " ") if drug_name_clean else ""
    tokens = normalized.split(" ") if normalized else []
    if not code_value and drug_name_clean:
        for n_tokens in range(len(tokens), 0, -1):
            candidate = " ".join(tokens[:n_tokens])
            if candidate in drug_codes:
                code_value = drug_codes[candidate]
                base_name = candidate
                break
        # suffix-match fallback for qualifier-prefixed aliases.
        if not code_value and len(tokens) > 1:
            for n_tokens in range(len(tokens) - 1, 0, -1):
                candidate = " ".join(tokens[-n_tokens:])
                if candidate in drug_codes:
                    code_value = drug_codes[candidate]
                    base_name = candidate
                    break
        if not code_value:
            code_value = drug_codes.get(base_name.replace("_", " "), "")
        if not code_value:
            # Issue #2134: chronic medications carry lowercase drug ids
            # ("sertraline"); fall back to a case-insensitive match when it
            # names exactly one code (exact-case keys still win above).
            for n_tokens in range(len(tokens), 0, -1):
                hit = _case_insensitive_code(drug_codes, " ".join(tokens[:n_tokens]))
                if hit:
                    code_value, base_name = hit
                    break
    # Issue #852: extend base_name to the longest multi-word prefix that has
    # a JA-dict entry so ``.text`` localization hits multi-word product-family
    # names even when Order.order_code was pre-set from the disease YAML
    # (Magnesium Sulfate = MHLW HOT7 2355002 etc.) and the code_mapping block
    # above was skipped. Only prefixes that BEGIN with the already-chosen
    # ``base_name`` token are considered so dose / route / freq tails do not
    # leak into ``.text`` (Issue #775 invariant).
    if tokens:
        from clinosim.locale.loader import load_narrative_display_dict as _load_ja_dict

        _ja_dict = _load_ja_dict()
        _first_token = tokens[0]
        for n_tokens in range(len(tokens), 1, -1):
            candidate = " ".join(tokens[:n_tokens])
            if candidate.lower() in _ja_dict and _first_token and candidate.startswith(_first_token):
                base_name = candidate
                break
    # C6-C7 residual sweep: same protocol_category fallback as MR builder.
    if not code_value and protocol_category:
        _pc = protocol_category.strip().lower().replace("_", " ").rstrip(":")
        for cand in (protocol_category, _pc, _pc.capitalize(), _pc.title()):
            if cand and cand in drug_codes:
                code_value = drug_codes[cand]
                break
    drug_system_key = system_key_for("drug", country_code)
    # F-1: JP は code 形式ごとに HOT7/HOT9/HOT13/YJ URI へ dispatch
    # (MR builder と同じ helper)。US は RxNorm URI。
    if is_jp(country_code) and drug_system_key == "yj" and code_value:
        code_system = _resolve_jp_drug_system_uri(code_value)
    else:
        code_system = get_system_uri(drug_system_key)

    # Issue #775: MAR also emits clean drug name in medicationCodeableConcept.text
    # (dose/route/freq belong in `dosage` below). Same rationale as MR builder.
    # ``base_name`` above resolved to the ``drug_codes`` key that matched, or,
    # per the Issue #852 extension, the longest multi-word JA-dict-mappable
    # prefix — either way the value is dose-free and safe for ``.text``.
    clean_drug_name = _localize_drug_name(base_name, country) if base_name else drug_name
    med_concept: dict[str, Any] = {"text": clean_drug_name}
    # #283 MR builder と同 gate — tx-server 未収録 JP YJ code は
    # nocoded fallback にダウングレード(薬剤名は text field で保持)。
    # #283:downgrade は YJ-code URI 経由の code だけ対象。同 drug_system_key
    # ="yj" でも `_resolve_jp_drug_system_uri` が HOT7/HOT9/HOT13 に dispatch
    # した場合(全 HOT 系は別 CodeSystem)は対象外 = 通常 emit。
    _jp_yj_unverified = (
        is_jp(country_code)
        and drug_system_key == "yj"
        and bool(code_value)
        and code_system == _JP_YJ_CODE_URI
        and not _is_yj_code_valid(code_value)
    )
    if code_value and not _jp_yj_unverified:
        display = code_lookup(drug_system_key, code_value, lang)
        coding: dict[str, Any] = {"system": code_system, "code": code_value}
        if display and display != code_value:
            coding["display"] = display
        med_concept["coding"] = [coding]
    elif is_jp(country_code):
        # #305 display は権威 CodeSystem 定義通り
        # "標準コードなし" 固定。薬剤名は med_concept["text"] で保持
        # (MR builder と同じ理由、v6 で MAR も同 mismatch 発生)。
        med_concept["coding"] = [
            {
                "system": _JP_MEDICATION_CODE_NOCODED_CS,
                "code": _JP_MEDICATION_CODE_NOCODED_CODE,
                "display": _JP_MEDICATION_CODE_NOCODED_DISPLAY,
            }
        ]

    # Issue #854 (PR-medication-administration): opaque MA.id + structural
    # key round-trip. See MEDICATION_ADMINISTRATION_KEY_SYSTEM docstring.
    _ma_structural_key = f"{encounter_id or patient_id}-{index:05d}"
    ma_identifiers: list[dict[str, Any]] = [
        wrap_as_identifier(_ma_structural_key, MEDICATION_ADMINISTRATION_KEY_SYSTEM)
    ]
    # clinosim_feedback P1-4: JP_MedicationAdministration.
    # identifier slice `rpNumber` + `orderInRp`(parent MR と同 URL / 同 値)。
    if is_jp(country_code):
        ma_identifiers.extend(
            [
                {
                    "system": "http://jpfhir.jp/fhir/core/mhlw/IdSystem/Medication-RPGroupNumber",
                    "value": rp_number,
                },
                {
                    "system": "http://jpfhir.jp/fhir/core/mhlw/IdSystem/MedicationAdministrationIndex",
                    "value": order_in_rp,
                },
            ]
        )
    resource: dict[str, Any] = {
        "resourceType": "MedicationAdministration",
        "id": _resolve_ma_id(_ma_structural_key),
        # chain #2: JP Core MedicationAdministration profile.
        **(
            {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_MedicationAdministration"]}}
            if is_jp(country_code)
            else {}
        ),
        "identifier": ma_identifiers,
        "status": map_mar_status(mar.get("status", "completed")),
        "medicationCodeableConcept": med_concept,
        "subject": patient_ref(patient_id),
        "effectiveDateTime": mar.get("actual_datetime") or mar.get("scheduled_datetime", ""),
    }
    # CY6-23 (Chain-6): MedicationAdministration.category — HL7 medication-
    # admin-category (inpatient / outpatient / community). clinosim MAR is
    # nurse-administered inpatient dosing (encounter_id-scoped), so default
    # to "inpatient".
    resource["category"] = {
        "coding": [
            {
                "system": "http://terminology.hl7.org/CodeSystem/medication-admin-category",
                "code": "inpatient",
                "display": "Inpatient",
            }
        ],
    }

    # Encounter context
    if encounter_id:
        resource["context"] = encounter_ref(encounter_id)

    # Cycle-1 C1-06/C1-07: MAR → MR audit-trail link. The MedicationRequest id
    # fix: MR resource id は order_id 単体(encounter-scoped で
    # globally unique)。以前は `{enc_id}-{order_id}` 二重 prefix だったが
    # 削除、reader/writer 両側を同期(imgst/imgrpt
    # double-prefix と同一 class の reference-integrity fix)。CI で 890
    # dangling references を surface。
    #
    # Issue #349 Phase 1b + Issue #853: すべての MR は opaque id に切替
    # したため、MAR の request.reference も同じ derive_opaque_id を経由して
    # opaque id へ resolve する。`_resolve_mr_id` helper が deterministic
    # なので同じ structural key → 同じ opaque id で reference-integrity 保持。
    # Phase 1b (PR #357) では antibiotic 限定だったが、Issue #853 で非 HAI
    # 全 MR (108k + 359k MA) に拡張。
    mar_order_id = mar.get("order_id", "")
    if mar_order_id:
        _mr_id = _resolve_mr_id(mar_order_id)
        resource["request"] = {"reference": f"MedicationRequest/{_mr_id}"}

    if mar.get("administered_by"):
        resource["performer"] = [{"actor": {"reference": f"Practitioner/{mar['administered_by']}"}}]

    # Dosage block — composed by _build_ma_dosage_block (sub-step helper).
    # The helper handles the full mad-1 SHOULD-emit logic (Issue #851)
    # including parent_order backfill (Issue #1089), rate-adjustment note
    # localization, IV augmentation (Issue #1067 B2), and the "drop
    # dosage.text that shadows drug name" guard.
    dosage_block = _build_ma_dosage_block(
        mar,
        parent_order,
        drug_name_raw,
        drug_name_clean,
        drug_name,
        rate_adjustment_note,
        country,
    )
    if dosage_block is not None:
        resource["dosage"] = dosage_block

    # Reason reference + reasonCode — composed by _build_ma_reason_block.
    # Routes `primary_dx_code` through `system_key_for("diagnosis",
    # country)` + `map_diagnosis_code` so JP output lands on MHLW ICD-10
    # 3-4 digit parent codes (Issue #208, #350).
    reason_pair = _build_ma_reason_block(
        primary_dx_code,
        chronic_condition_codes,
        patient_id,
        encounter_id,
        country_code,
        patient_sex,
    )
    if reason_pair is not None:
        resource["reasonReference"], resource["reasonCode"] = reason_pair

    # Device reference — composed by _build_ma_device_block for
    # continuous-IV administrations (CY8-20). Gates on canonical route
    # key via `canonicalize_route` so JP-localized `静注` + alias
    # `INTRAVENOUS` both route through the IV branch.
    _parsed_route_for_device: str | None = None
    if dosage_block is not None:
        # The helper above already computed `parsed["route"]`; redo the
        # same parse here to keep the signature free of orchestrator state.
        _p = _parse_dose_for_mar(str(mar.get("dose", "") or drug_name))
        _parsed_route_for_device = _p.get("route")
    device_block = _build_ma_device_block(mar, _parsed_route_for_device, country_code)
    if device_block is not None:
        resource["device"] = device_block

    return resource


# ─────────────────────────────────────────────────────────────────
# Class-collision guard for MedicationRequest (Issue #1176 / #1179)
# ─────────────────────────────────────────────────────────────────
#
# Empirical p=10000 audit found ≥2 drugs from the same therapeutic
# class co-authored on the same day for a small number of patients:
#   * ACE-I + ARB (dual RAAS blockade) — 70 orders / 19 patients (Class III: Harm)
#   * PPI + PPI                        — 26 buckets / 4 patients
#   * NSAID + NSAID                    — 11 buckets / 11 patients
#   * Anticoagulant + Anticoagulant    — 29 buckets / 4 patients
#
# The cause is multiple CIF order sources (chronic problem list +
# episode-specific treatment plan + inpatient add-on flow) each
# picking a different drug from the same class for the same clinical
# indication. Fix at CIF layer is preferable long-term; the emit-time
# guard below is the belt-and-braces filter that keeps the FHIR
# output clean while the CIF drift is investigated.
#
# Classification uses substring match against a small drug → class
# dictionary. Matching is intentionally conservative: only drugs on
# the explicit list contribute to a class, so a drug not covered here
# falls through as its own class ("_uncovered") and is never dropped
# by this guard.

# Therapeutic-class membership + raas supergroup live in
# `clinosim/codes/data/medication-class-members.yaml`. Module-level
# aliases below are computed from the yaml at import time so every
# existing consumer (`_classify_medication` / `_dedup_same_class_orders`
# and anything importing the names) keeps working with no call-site
# changes.


@cache
def _medication_class_rows() -> dict[str, dict[str, Any]]:
    import yaml

    path = Path(__file__).resolve().parents[4] / "codes" / "data" / "medication-class-members.yaml"
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    classes = raw.get("classes") or {}
    out: dict[str, dict[str, Any]] = {}
    for name, row in classes.items():
        if isinstance(row, dict):
            out[str(name)] = row
    return out


def _medication_class_members_dict() -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for name, row in _medication_class_rows().items():
        en = tuple(str(m) for m in (row.get("en") or []) if isinstance(m, str))
        ja = tuple(str(m) for m in (row.get("ja") or []) if isinstance(m, str))
        out[name] = en + ja
    return out


def _medication_class_supergroups_dict() -> dict[str, str]:
    out: dict[str, str] = {}
    for name, row in _medication_class_rows().items():
        sg = row.get("supergroup")
        if isinstance(sg, str):
            out[name] = sg
    return out


_MEDICATION_CLASS_MEMBERS: dict[str, tuple[str, ...]] = _medication_class_members_dict()
_MEDICATION_CLASS_SUPERGROUPS: dict[str, str] = _medication_class_supergroups_dict()


def _classify_medication(med_text: str) -> str:
    """Return the therapeutic-class key for a drug display text, or "" when uncovered."""
    if not med_text:
        return ""
    lower = med_text.lower()
    for cls, members in _MEDICATION_CLASS_MEMBERS.items():
        for m in members:
            if m in lower or m in med_text:
                # Collapse class into supergroup when defined.
                return _MEDICATION_CLASS_SUPERGROUPS.get(cls, cls)
    return ""


def _dedup_same_class_orders(mrs: list[dict]) -> list[dict]:
    """Drop later MedicationRequest orders that duplicate the therapeutic
    class of an earlier order authored on the same day for the same patient.

    Issue #1176: ACE-I + ARB (dual RAAS blockade) — 70 orders / 19 patients.
    Issue #1179: PPI + PPI (26 buckets), NSAID + NSAID (11), Anticoagulant +
    Anticoagulant (29).

    Keys off (subject.reference, authoredOn date, therapeutic class). The
    first order in a colliding pair wins; later orders in the same class
    on the same day for the same patient are dropped. Drugs not covered by
    ``_MEDICATION_CLASS_MEMBERS`` are never dropped (they classify as ""
    and skip the guard).

    Never coalesces different-formulation combinations that were already
    filtered by :func:`_dedup_medication_requests` (exact-duplicate dedup);
    that function should run first when both are chained.
    """
    seen: set[tuple[str, str, str]] = set()
    out: list[dict] = []
    for mr in mrs:
        subject_ref = ""
        subj = mr.get("subject")
        if isinstance(subj, dict):
            subject_ref = str(subj.get("reference", "") or "").strip()
        authored = str(mr.get("authoredOn", ""))[:10]
        med_text = ""
        med = mr.get("medicationCodeableConcept")
        if isinstance(med, dict):
            med_text = str(med.get("text", "") or "").strip()
        cls = _classify_medication(med_text)
        if not cls or not subject_ref or not authored:
            out.append(mr)
            continue
        key = (subject_ref, authored, cls)
        if key in seen:
            continue
        seen.add(key)
        out.append(mr)
    return out
