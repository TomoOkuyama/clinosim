"""FHIR R4 MedicationRequest / MedicationAdministration builders (FA-1 medications).

Extracted verbatim from ``fhir_r4_adapter``. Self-contained: imports only
leaf data, shared helpers, and stdlib/first-party deps — never the adapter.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from clinosim.codes import (
    get_system_uri,
    system_key_for,
)
from clinosim.codes import lookup as code_lookup
from clinosim.locale.loader import load_code_mapping
from clinosim.modules._shared import (
    MED_STOP_ORDER_ID_MARKER,
    get_attr_or_key,
    is_jp,
    resolve_lang,
)
from clinosim.modules.antibiotic.engine import ABX_ORDER_ID_PREFIX
from clinosim.modules.output.fhir_r4.lib.common import (
    _parse_dose_for_mar,
    build_dosage_instruction,
    build_route_concept,
    build_ucum_quantity,
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
#   JP_MedicationRequest_eCS (JP-CLINS 1.12.0) — StructureDefinition-JP-MedicationRequest-eCS.json
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
_MEDIS_HOT7_URI = "http://medis.or.jp/CodeSystem/master-HOT7"
_MEDIS_HOT9_URI = "http://medis.or.jp/CodeSystem/master-HOT9"
_MEDIS_HOT13_URI = "http://medis.or.jp/CodeSystem/master-HOT13"
_JP_YJ_CODE_URI = "http://capstandard.jp/iyaku.info/CodeSystem/YJ-code"

_YJ12_PATTERN = re.compile(r"^\d{7}[A-Z]\d{4}$")

# #291 JP-CLINS eCS "nocoded" slice — code_mapping にヒットしない
# 薬(ED 特異薬 等)の `medication[x].coding` min=1 を満たすための fallback。
# spec: clinical-information-sharing#1.12.0/package/
# CodeSystem-jp-eCS-medicationcode-nocoded-cs.json 権威 display "標準コードなし"。
_JP_MEDICATION_CODE_NOCODED_CS = "http://jpfhir.jp/fhir/eCS/CodeSystem/MedicationCodeNocoded_CS"
_JP_MEDICATION_CODE_NOCODED_CODE = "NOCODED"
_JP_MEDICATION_CODE_NOCODED_DISPLAY = "標準コードなし"

# #283 tx-server-verifiable YJ code set(2000 concepts fragment)。
# jpfhir-terminology 2.2606.0 の CodeSystem-jp-medicationcodeyj-cs.json は
# 25542 全 YJ codes のうち先頭 2000(11xx/12xx = 精神/神経系のみ)を fragment
# として出荷。clinosim が emit する YJ code はこの fragment 内なら通常の
# `codingYJ` slice、fragment 外なら `nocoded` slice に fallback(薬剤名は
# text field で保持)。HAPI validator が fragment 外の code を "システム URI
# を決定できません" error で報告する(v5 で 594 件)ため defensive downgrade。
# snapshot は `scripts/refresh_authoritative_yj_tx_valid.py` で更新可能。


def _load_tx_server_verified_yj_codes() -> frozenset[str]:
    """Load tx-server's verifiable YJ code set as an immutable frozenset."""
    import json as _json
    from pathlib import Path as _Path

    # PR2 (Issue #555): file moved from output/_fhir_medications.py to
    # output/fhir_r4/medications/medications.py (2 layers deeper) — parent
    # depth adjusted from 2 to 4 so the path still resolves to clinosim/codes/.
    _snapshot = _Path(__file__).resolve().parents[4] / "codes" / "authoritative" / "yj_tx_valid_codes.json"
    if not _snapshot.is_file():
        return frozenset()
    return frozenset(_json.loads(_snapshot.read_text()).get("codes", []))


_TX_SERVER_VERIFIED_YJ_CODES: frozenset[str] = _load_tx_server_verified_yj_codes()


def _is_tx_server_verified_yj(code: str) -> bool:
    """Return True when the YJ code is present in the tx-server's fragment CS.

    #283:the JP tx-server ships a 2000-concept fragment of the
    25542-concept YJ CodeSystem. Codes outside the fragment cannot be
    validator-verified even though they are real MHLW YJ codes; the caller
    routes them to the JP-CLINS eCS `nocoded` slice instead of `codingYJ`.
    """
    return code in _TX_SERVER_VERIFIED_YJ_CODES


def _resolve_jp_drug_system_uri(code: str) -> str:
    """Return the JP Core NamingSystem URI matching the drug code format.

    - 7-digit numeric  → MEDIS HOT7 URI
    - 9-digit numeric  → MEDIS HOT9 URI
    - 13-digit numeric → MEDIS HOT13 URI
    - 12-char YJ pattern (`^\\d{7}[A-Z]\\d{4}$`) → YJ code URI
    - fallback → HOT9 URI(旧 clinosim 挙動維持、将来 code 追加時の safe default。
      新 format を足す時は必ず本 helper と pin test を先に拡張すること)。
    """
    if code.isdigit():
        n = len(code)
        if n == 7:
            return _MEDIS_HOT7_URI
        if n == 9:
            return _MEDIS_HOT9_URI
        if n == 13:
            return _MEDIS_HOT13_URI
    elif _YJ12_PATTERN.match(code):
        return _JP_YJ_CODE_URI
    return _MEDIS_HOT9_URI


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


def _resolve_medication_concept(
    display_name_raw: str,
    order_code: str,
    country: str,
) -> tuple[dict[str, Any], str]:
    """Resolve a raw drug display name into a FHIR `medicationCodeableConcept`.

    SINGLE resolution point for drug name -> code -> display across every
    MedicationRequest builder. Extracted from `_build_medication_request` so the
    discharge-prescription builder (Issue #445) shares the same code_mapping lookup,
    JP HOT7/HOT9/HOT13/YJ system dispatch, tx-server-unverified-YJ downgrade to the
    eCS `nocoded` slice, and locale display resolution. Re-implementing any of that
    at a second call site is the duplication this helper exists to prevent.

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
    drug_codes = load_code_mapping("drug", country_code)  # name → RxNorm/YJ

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
    code_value = order_code or ""
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
        from clinosim.locale.loader import load_drug_names_ja as _load_ja_dict

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
        and not _is_tx_server_verified_yj(code_value)
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
        # clinical-information-sharing#1.12.0/package/
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

    # C2-14: MR.intent context-aware — mirrors C1-16 which
    # applied the same idea to ServiceRequest. Chronic-management refills →
    # `instance-order`; discharge take-home meds → `original-order`; the rest
    # remain `order`.
    intent_val = _mr_intent_from_order(order, encounter_type)
    # C2-16: finished courses get status=completed. `end_datetime`
    # (or `discontinuation_datetime`) is populated in CIF when the course is
    # deliberately stopped or naturally ends; fall through to whatever
    # _map_order_status_to_fhir returns otherwise.
    # CO-9: also complete when the encounter itself is
    # finished (outpatient Rx end at encounter close in JP practice).
    # RM-2: episodic inpatient orders (Supportive / ED treatment /
    # antibiotics keyed on clinical_intent phrasing) complete at discharge.
    # Home-medication orders REMAIN active because chronic-meds continue
    # post-discharge.
    status_val = _map_order_status_to_fhir(order.get("status", ""))
    medication_intent = order.get("medication_intent", "")  # Issue #349 Phase 2
    _ci_lower = str(order.get("clinical_intent", "") or "").lower()
    _episodic_kw = ("supportive:", "ed treatment:", "day ", "dvt_prophylaxis", "antibiotic", "escalation")
    _is_home_med = "home medication" in _ci_lower
    _is_episodic = (not _is_home_med) and any(kw in _ci_lower for kw in _episodic_kw)
    if status_val == "active" and (
        order.get("end_datetime")
        or (encounter_type == "outpatient" and order.get("encounter_id"))
        or (_is_episodic and encounter_type == "inpatient" and order.get("encounter_id"))
    ):
        status_val = "completed"

    # Issue #436 F1': daily-loop STOP (discontinuation) orders are
    # emitted with the ``MED_STOP_ORDER_ID_MARKER`` id marker (see
    # ``clinosim/modules/_shared.py``). FHIR MedicationRequest.status
    # for these orders is set to ``"stopped"`` so downstream consumers
    # cannot mistake a discontinuation for an active prescription. The
    # override is at the emit layer only (F1', not F1) — investigation
    # showed that reassigning ``OrderStatus.STOPPED`` at Order creation
    # shifts ``_generate_mar``'s per-order rng cursor
    # and violates AD-16 determinism (+6 ServiceRequest / +7 Specimen /
    # +1 DiagnosticReport cascade). The id-based override at emit is
    # rng-neutral: the Order iteration order is unchanged.
    #
    # JP asymmetry: JP_MedicationRequest_eCS pins ``status`` =
    # patternCode ``"completed"`` per the JP-CLINS spec, so
    # ``fhir_r4_adapter._normalize_ecs_metadata`` (around
    # ``fhir_r4_adapter.py:1978``) forcibly re-overrides JP output
    # back to ``"completed"``. On JP, F1' is effectively no-op and
    # the STOP intent survives only via F3 (``note[].text`` below,
    # which the eCS profile does not restrict). On US, both F1' and
    # F3 survive.
    # STOP-marker check remains on the structural key (not resource_id) — the
    # opaque id has no substring recoverability. This uses the raw compound key
    # that was hashed to derive resource_id.
    _is_stop_order = MED_STOP_ORDER_ID_MARKER in _structural_key
    if _is_stop_order:
        status_val = "stopped"
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
        "subject": {"reference": f"Patient/{patient_id}"},
        "authoredOn": order.get("ordered_datetime", ""),
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
        resource["encounter"] = {"reference": f"Encounter/{enc_ref}"}

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

    # C4-15: dispenseRequest for outpatient / discharge
    # scripts. FHIR R4 MedicationRequest.dispenseRequest is 0..1; JP Core
    # recommends population for meaningful pharmacy dispense workflow. We
    # emit a light-weight dispenseRequest describing typical validity period
    # for chronic-med / discharge orders (was 100% missing in baseline).
    # CY7-07 (Chain-7): also emit dispenseRequest for inpatient orders — JP
    # 入院処方 has a distinct dispense track (病棟薬剤師 dispensing per shift).
    # Default 0 refills for acute, 3 for chronic home-med, 1 for inpatient
    # (single scheduled dispense per order).
    _authored = order.get("ordered_datetime", "") or ""
    _end = order.get("end_datetime", "") or ""
    disp: dict[str, Any] = {}
    if _authored and _end:
        disp["validityPeriod"] = {"start": str(_authored), "end": str(_end)}
    elif _authored:
        disp["validityPeriod"] = {"start": str(_authored)}
    if _is_home_med:
        disp["numberOfRepeatsAllowed"] = 3
    elif encounter_type == "outpatient":
        disp["numberOfRepeatsAllowed"] = 0
    elif encounter_type in ("inpatient", "emergency"):
        disp["numberOfRepeatsAllowed"] = 0  # inpatient/ED dispense once per order
    resource["dispenseRequest"] = disp

    # C5-23: MedicationRequest.substitution (0..1)
    # for generic substitution allowance. JP GE 促進 policy allows generic
    # substitution for chronic outpatient scripts unless explicitly
    # marked "brand only" — default `allowed = true` for outpatient/home-med.
    if encounter_type == "outpatient" or _is_home_med:
        resource["substitution"] = {"allowedBoolean": True}

    # Issue #436 F3: STOP orders' ``clinical_intent`` (e.g. "Day 2
    # sudden_deterioration: stop Warfarin") is otherwise dropped by the
    # emit path. Copy it into ``note[].text`` so downstream FHIR readers
    # (human or machine) can see WHY the medication was discontinued.
    # F1' (above) makes ``status="stopped"`` machine-actionable; F3 adds
    # the human-facing rationale. Emitted only for STOP orders — no-op
    # for regular orders (keeps their emit shape byte-identical).
    if _is_stop_order:
        _stop_intent = str(order.get("clinical_intent", "") or "").strip()
        if _stop_intent:
            resource["note"] = [{"text": _stop_intent}]

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
    med_concept, rate_adjustment_note = _resolve_medication_concept(drug_name, "", country)

    prefix = DISCHARGE_RX_ID_PREFIX if encounter_type == "inpatient" else OUTPATIENT_RX_ID_PREFIX
    resource_id = f"{prefix}{encounter_id}-{seq:02d}"

    # A take-home script is "on" once written; the JP walker overwrites both fields to
    # the eCS patternCodes (`completed` / `order`) so these values only reach US output.
    resource: dict[str, Any] = {
        "resourceType": "MedicationRequest",
        "id": resource_id,
        **_build_medication_request_meta(country_code, ""),
        **_build_medication_request_identifiers(
            resource_id,
            country_code,
            "1",
            str(seq),
        ),
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": med_concept,
        "subject": {"reference": f"Patient/{patient_id}"},
        "authoredOn": authored_on,
    }
    if encounter_id:
        resource["encounter"] = {"reference": f"Encounter/{encounter_id}"}
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

    dispense: dict[str, Any] = {}
    if authored_on:
        dispense["validityPeriod"] = {"start": authored_on}
    if duration_days is not None:
        dispense["expectedSupplyDuration"] = {
            "value": duration_days,
            "unit": _SUPPLY_DURATION_UNIT_JP if country_code == "JP" else _SUPPLY_DURATION_UNIT_US,
            "system": get_system_uri("ucum"),
            "code": _SUPPLY_DURATION_CODE,
        }
    # `numberOfRepeatsAllowed` is intentionally absent: CIF carries no refill count, and
    # guessing one would assert a dispensing policy the simulation never modelled.
    if dispense:
        resource["dispenseRequest"] = dispense

    # dosageInstruction is emitted ONLY from information the CIF actually holds. Items
    # transcribed from `patient.current_medications` have neither dose nor route (both are
    # lost upstream — Issue #452); for those the element is omitted rather than filled
    # with the drug name, which would restate `medicationCodeableConcept.text` as if it
    # were a dosage. `_apply_jp_clins_profile` withholds the eCS profile from exactly
    # these resources, because eCS raises `dosageInstruction` to min=1.
    dosage: dict[str, Any] = {}
    route_concept = build_route_concept(route, country)
    if route_concept:
        dosage["route"] = route_concept
    # Issue #476: when the disease-YAML author provided an explicit
    # country-scoped instruction (`dose_ja` / `dose_en` on the drug entry →
    # threaded through `_build_discharge_rx._append_item` into the item dict),
    # emit it as the dosage text. This wins over the auto-derived summary
    # (`dose` field text) because the authored text is what carries the
    # clinical meaning for instruction-only doses (e.g. "既存のインスリン
    # レジメンどおり" for insulin glargine restart at DKA discharge).
    dose_text_ja = str(get_attr_or_key(item, "dose_ja", "") or "")
    dose_text_en = str(get_attr_or_key(item, "dose_en", "") or "")
    authored_text = dose_text_ja if is_jp(country) else dose_text_en
    if authored_text:
        dosage["text"] = authored_text
    else:
        dose_parts = [p for p in (dose, rate_adjustment_note) if p]
        if dose_parts:
            dose_text = " ".join(dose_parts)
            dosage["text"] = _localize_dosage_terms(dose_text) if is_jp(country) else dose_text
    if dosage:
        resource["dosageInstruction"] = [dosage]

    return resource


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
    drug_codes = load_code_mapping("drug", country_code)
    # C3-10: longest-match-wins for multi-word keys.
    # CO-8 (Chain 4 2026-07-11): normalize underscores + honor MAR.code_yj
    # if downstream ever propagates the Order's code (see _build_medication_request).
    code_value = mar.get("code_yj", "") or ""
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
    # Issue #852: extend base_name to the longest multi-word prefix that has
    # a JA-dict entry so ``.text`` localization hits multi-word product-family
    # names even when Order.order_code was pre-set from the disease YAML
    # (Magnesium Sulfate = MHLW HOT7 2355002 etc.) and the code_mapping block
    # above was skipped. Only prefixes that BEGIN with the already-chosen
    # ``base_name`` token are considered so dose / route / freq tails do not
    # leak into ``.text`` (Issue #775 invariant).
    if tokens:
        from clinosim.locale.loader import load_drug_names_ja as _load_ja_dict

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
        and not _is_tx_server_verified_yj(code_value)
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

    resource: dict[str, Any] = {
        "resourceType": "MedicationAdministration",
        "id": f"mar-{encounter_id or patient_id}-{index:05d}",
        # chain #2: JP Core MedicationAdministration profile.
        **(
            {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_MedicationAdministration"]}}
            if is_jp(country_code)
            else {}
        ),
        # clinosim_feedback P1-4: JP_MedicationAdministration.
        # identifier slice `rpNumber` + `orderInRp`(parent MR と同 URL / 同 値)。
        **(
            {
                "identifier": [
                    {
                        "system": "http://jpfhir.jp/fhir/core/mhlw/IdSystem/Medication-RPGroupNumber",
                        "value": rp_number,
                    },
                    {
                        "system": "http://jpfhir.jp/fhir/core/mhlw/IdSystem/MedicationAdministrationIndex",
                        "value": order_in_rp,
                    },
                ]
            }
            if is_jp(country_code)
            else {}
        ),
        "status": map_mar_status(mar.get("status", "completed")),
        "medicationCodeableConcept": med_concept,
        "subject": {"reference": f"Patient/{patient_id}"},
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
        resource["context"] = {"reference": f"Encounter/{encounter_id}"}

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

    # Dosage with structured dose + route
    #
    # Issue #851: 23,543 (6.56 %) MedicationAdministration records
    # shipped without any `.dosage` element because ``mar.dose`` was
    # empty (or a fallback to ``drug_name``) so ``_parse_dose_for_mar``
    # yielded no structured dose_quantity, and the FHIR R4 mad-1
    # gate (SHOULD dose or rate exist when dosage is present) dropped
    # the whole element — losing the free-text description AND the
    # route that the parent MedicationRequest correctly carried. Fix:
    # backfill from ``parent_order`` when the MA fields are missing so
    # dosage.text, dosage.route, dosage.dose (numeric when available),
    # and the frequency-derived timing are all populated. Also relax
    # the mad-1 emit gate so text+route alone can carry the dosage
    # element for continue-home-med / sliding-scale / PRN orders where
    # no structured dose exists at either MA or MR level (the emitted
    # dosage is still meaningful for eMAR rendering; mad-1 is SHOULD
    # in R4).
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
        # Parse the composed text so `_parse_dose_for_mar` can extract
        # numeric dose + unit when available (same path as before).
        dose_str = dose_text
    else:
        dose_text = _mar_dose_raw
        dose_str = _mar_dose_raw
    parsed = _parse_dose_for_mar(dose_str or drug_name)
    # attach any rate-adjustment note peeled off drug_name to dose_text
    # so continuous-infusion titration intent surfaces in the dosage record.
    if rate_adjustment_note:
        rate_note_localized = _localize_rate_adjustment(rate_adjustment_note, country)
        dose_text = f"{dose_text} ({rate_note_localized})".strip() if dose_text.strip() else rate_note_localized
    # Issue #472: localize at the assignment only — `dose_text` itself stays English
    # because the continuous-infusion detection below matches on "CONTINUOUS" / "DRIP".
    # The MedicationRequest sibling applies the same call on its own dosage["text"].
    dosage: dict[str, Any] = {"text": _localize_dosage_terms(dose_text) if is_jp(country) else dose_text}
    if parsed.get("dose_quantity") is not None and parsed.get("dose_unit"):
        # Route through build_ucum_quantity so `code` is populated (JP-CLINS
        # eCS profiles require it — feedback fix PR-A, 2026-07-16).
        dosage["dose"] = build_ucum_quantity(parsed["dose_quantity"], parsed["dose_unit"])
    # Rate for continuous infusions
    if "CONTINUOUS" in dose_text.upper() or "DRIP" in dose_text.upper() or "/h" in dose_text:
        rate_value = parsed.get("dose_quantity") or 1
        rate_unit = parsed.get("dose_unit", "mL") + "/h"
        dosage["rateQuantity"] = build_ucum_quantity(rate_value, rate_unit)
    # Route — resolved through the shared helper so the MAR and MR paths cannot drift
    # apart again (Issue #458: the missing `INH` / `NEB` aliases produced 166 text-only
    # elements here versus 6 on the MR path). `.upper()` now lives in the helper.
    route_concept = build_route_concept(mar.get("route") or parsed.get("route"), country)
    if route_concept:
        dosage["route"] = route_concept
    # v3 (Chain-11, v3 feedback §保留 3 真因判明): FHIR R4
    # `mad-1` says `dosage.dose.exists() or dosage.rate.exists()` when a
    # dosage element is present. Sliding-scale insulin / PRN / infusion
    # bolus orders that only carry a `dosage.text` (no parsable numeric
    # dose) tripped 3,005 MedicationAdministration resources in the
    # original Chain-11 report.
    #
    # Issue #851 update: mad-1 is SHOULD (not SHALL) in FHIR R4, and
    # dropping the entire dosage element loses the parent order's route
    # and free-text description as well — 23,543 (6.56 %) MAs in the JP
    # p=10000 s500 sample shipped without ANY dosage element for
    # exactly this reason. The eMAR-rendering need (what was
    # administered and how) outweighs the mad-1 preference; emit the
    # dosage element when it carries at least a route or a meaningful
    # non-empty text, and keep the original ``dose | rate`` gate as an
    # OR-clause so structured-dose paths are unchanged. Text that
    # merely repeats the drug name is treated as empty (avoid
    # ``.dosage.text = <drug name>`` shadow of ``medicationCodeableConcept.text``).
    _dosage_text_val = str(dosage.get("text") or "").strip()
    _text_meaningful = bool(_dosage_text_val) and _dosage_text_val not in (
        drug_name_raw,
        drug_name_clean,
        drug_name,
    )
    if "dose" in dosage or "rateQuantity" in dosage or dosage.get("route") or _text_meaningful:
        resource["dosage"] = dosage

    # Reason reference (link to primary diagnosis). Chronic-primary
    # encounters resolve to the patient-scoped chronic Condition; acute
    # ones keep the encounter-scoped id.
    if primary_dx_code:
        from clinosim.modules.output.fhir_r4.conditions.primary_ref import (
            primary_condition_ref_from_codes,
        )

        cond_ref = primary_condition_ref_from_codes(primary_dx_code, chronic_condition_codes, patient_id, encounter_id)
        resource["reasonReference"] = [
            {
                "reference": f"Condition/{cond_ref}",
            }
        ]
        # CY8-19 fix: MAR.reasonCode — primary diagnosis
        # ICD code を CodeableConcept で並置(reasonReference との duplication は
        # FHIR R4 で recommended:code と reference は互いに補完)。
        # US = icd-10-cm、JP = icd-10。
        #
        # #208 (2026-07-17):`primary_dx_code` は CIF の
        # `admission_diagnosis_code` にセットされる disease-YAML の
        # `icd_codes.primary` 値を由来として、しばしば CM-granular な
        # 表現(S72.00 / E11.65 / …)を含む。JP output では
        # `map_diagnosis_code` を通して WHO ICD-10 3-4 桁の親コードへ
        # 畳み込む必要がある(fhir-jp-validator 2026-07-17 §【最優先 6】
        # 7,652 errors)。US では identity(既に CM billable leaf に
        # `code_mapping_diagnosis/us.yaml` で解決済み)。他 builder
        # (Encounter.reasonCode / Condition.code / FamilyMemberHistory.code)
        # は同 seam を既に通しており、これで漏れ経路が閉じる。
        # Issue #350: route through `system_key_for("diagnosis",
        # country)` — single source of truth for the JP → MHLW / US → ICD-10-CM
        # mapping. Previously this site hardcoded `"icd-10-cm" if US else
        # "icd-10"` which bypassed the country-key registry and emitted the
        # WHO URI on JP output (JP Core `jp-condition-diagnosis` required
        # binding violation, ~7,600 errors on a p=200 6mo JP cohort).
        _icd_system = get_system_uri(system_key_for("diagnosis", country_code))
        _mapped_dx_code = map_diagnosis_code(primary_dx_code, country_code)
        resource["reasonCode"] = [
            {
                "coding": [
                    {
                        "system": _icd_system,
                        "code": _mapped_dx_code,
                    }
                ],
            }
        ]

    # CY8-20 fix: MAR.device — 持続点滴 (continuous
    # infusion / drip) のとき infusion pump Device を参照。route=IV かつ
    # rate指定ある/CONTINUOUS/DRIP を含む admin のみ pump 参照 emit。
    # Device resource 自体は既存 hospital-main の generic infusion pump を
    # 参照(実 EHR 実装と同様、pump を patient に固有発行しない運用)。
    # Gate the infusion-pump reference on the CANONICAL route key, resolved through
    # `canonicalize_route` (alias-aware). Two distinct failure modes this closes:
    #  (i) `route_concept["text"]` is localized under Issue #479 dual-slot rule —
    #      `"静注"` on JP would fail `== "IV"` and drop every IV continuous-infusion
    #      `resource["device"]`. Same J5 pattern as PR #475 (`dose_text` localization
    #      dropping `rateQuantity`).
    #  (ii) A future alias for IV (e.g. `INTRAVENOUS: "IV"` in `_ROUTE_ALIASES`) would
    #      break a raw-upper comparison the same way — the raw `"INTRAVENOUS"` fails
    #      `== "IV"` even though it means IV. `canonicalize_route` resolves the alias.
    _canonical_route = canonicalize_route(mar.get("route") or parsed.get("route"))
    _dose_text_up = (mar.get("dose") or "").upper()
    _is_infusion = _canonical_route == "IV" and (
        "CONTINUOUS" in _dose_text_up or "DRIP" in _dose_text_up or "/H" in _dose_text_up
    )
    if _is_infusion:
        resource["device"] = [
            {
                "reference": "Device/dev-infusion-pump",
                "display": "汎用輸液ポンプ" if is_jp(country_code) else "Generic infusion pump",
            }
        ]

    return resource
