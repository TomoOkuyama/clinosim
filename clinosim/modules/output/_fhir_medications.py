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
from clinosim.modules._shared import is_us, resolve_lang
from clinosim.modules.output._fhir_common import (
    _build_dosage_instruction,
    _map_diagnosis_code,
    _map_mar_status,
    _parse_dose_for_mar,
    _strip_protocol_prefix,
    build_ucum_quantity,
)
from clinosim.modules.output._fhir_localization import (
    _localize_drug_name,
    _localize_rate_adjustment,
    _split_rate_adjustment_suffix,
)
from clinosim.modules.output._fhir_reference_data import _ROUTE_SNOMED

# session 53 iris4h-ai feedback F-1: MedicationRequest / MedicationAdministration
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

# #291 session 59:JP-CLINS eCS "nocoded" slice — code_mapping にヒットしない
# 薬(ED 特異薬 等)の `medication[x].coding` min=1 を満たすための fallback。
# spec: clinical-information-sharing#1.12.0/package/
# CodeSystem-jp-eCS-medicationcode-nocoded-cs.json 権威 display "標準コードなし"。
_JP_MEDICATION_CODE_NOCODED_CS = "http://jpfhir.jp/fhir/eCS/CodeSystem/MedicationCodeNocoded_CS"
_JP_MEDICATION_CODE_NOCODED_CODE = "NOCODED"
_JP_MEDICATION_CODE_NOCODED_DISPLAY = "標準コードなし"

# #283 session 59:tx-server-verifiable YJ code set(2000 concepts fragment)。
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

    _snapshot = _Path(__file__).resolve().parents[2] / "codes" / "authoritative" / "yj_tx_valid_codes.json"
    if not _snapshot.is_file():
        return frozenset()
    return frozenset(_json.loads(_snapshot.read_text()).get("codes", []))


_TX_SERVER_VERIFIED_YJ_CODES: frozenset[str] = _load_tx_server_verified_yj_codes()


def _is_tx_server_verified_yj(code: str) -> bool:
    """Return True when the YJ code is present in the tx-server's fragment CS.

    Session 59 #283:the JP tx-server ships a 2000-concept fragment of the
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
    """Pick MedicationRequest.intent from the CIF Order (C2-14, session 42).

    Mirrors `_sr_intent_from_clinical_intent` (C1-16) for medications:
    - Chronic-management refills (clinical_intent contains "Follow-up" /
      "Chronic" / "Refill") → `instance-order` (a specific instance in an
      ongoing plan).
    - Discharge / take-home prescriptions → `original-order` (starts a new
      series of encounters at another provider).
    - Outpatient AMB encounter → `instance-order` (an instance on the
      ongoing outpatient chronic-management plan). CO-7 (session 42 cycle 3):
      broaden the inference because upstream CIF rarely populates
      `clinical_intent`; encounter_type is a reliable proxy.
    - Default → `order`.
    """
    ci = str(order.get("clinical_intent", "") or "").lower()
    protocol = str(order.get("protocol_category", "") or "").lower()
    display = str(order.get("display_name", "") or "").lower()
    if "discharge" in ci or "discharge" in protocol or display.startswith("discharge:"):
        return "original-order"
    # RM-2 (session 42): expanded to match clinosim's actual CIF phrasing
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
    # CO-7 (session 42 cycle 3): outpatient encounter type → instance-order.
    if encounter_type == "outpatient":
        return "instance-order"
    return "order"


def _build_medication_request(
    order: dict,
    patient_id: str,
    country: str,
    encounter_id: str = "",
    primary_dx_code: str = "",
    encounter_type: str = "",
    rp_number: str = "1",
    order_in_rp: str = "1",
) -> dict:
    """Build FHIR MedicationRequest resource.

    rp_number / order_in_rp (session 49 clinosim_feedback P1-4): JP Core
    JP_MedicationRequest.identifier:rpNumber と :orderInRp slice を満たす
    ための per-order identifier 値。caller は 1 encounter 内の医薬品
    orders に対して同じ rp_number(処方単位)+ 連番 order_in_rp を
    与える。同一 order の MedicationRequest と MedicationAdministration
    は同じ (rp_number, order_in_rp) を使い、両者の紐付けが取れる。
    """
    drug_name_raw = order.get("display_name", "Unknown medication")
    # Strip protocol prefix (e.g. "DVT_prophylaxis:") from medicationCodeableConcept.text
    # The prefix goes to dosageInstruction note instead.
    drug_name_clean, protocol_category = _strip_protocol_prefix(drug_name_raw)
    # Session 45: split off any "increase/decrease rate by X%" continuous-infusion
    # adjustment suffix (disease YAML pattern for Day-N drip rate changes) so
    # the medicationCodeableConcept.text stays as a clean drug name and the
    # adjustment note can be appended to dosageInstruction.
    drug_name_clean, rate_adjustment_note = _split_rate_adjustment_suffix(drug_name_clean)
    drug_name = _localize_drug_name(drug_name_clean, country)
    # Strip dose info to get base drug name for code lookup (use cleaned name)
    base_name = drug_name_clean.split(" ")[0] if drug_name_clean else ""

    country_code = "US" if is_us(country) else "JP"
    lang = resolve_lang(country_code)
    drug_codes = load_code_mapping("drug", country_code)  # name → RxNorm/YJ

    # C3-10 (session 42 cycle 3): multi-word drug names (e.g. "Normal saline",
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
    code_value = order.get("order_code", "") or ""
    if not code_value and drug_name_clean:
        normalized = drug_name_clean.replace("_", " ")
        tokens = normalized.split(" ")
        for n_tokens in range(len(tokens), 0, -1):
            candidate = " ".join(tokens[:n_tokens])
            if candidate in drug_codes:
                code_value = drug_codes[candidate]
                base_name = candidate
                break
        # Session 45: suffix-match fallback lets qualifier-prefixed aliases
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
    # C6-C7 residual sweep: fallback to `protocol_category` (the "TYPE:" prefix
    # stripped by `_strip_protocol_prefix`, e.g. "lactulose:" / "antibiotic:" /
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
    display = code_lookup(drug_system_key, code_value, lang) if code_value else drug_name
    if display == code_value:
        display = drug_name
    # session 53 F-1: JP は code 形式ごとに HOT7/HOT9/HOT13/YJ URI へ dispatch。
    # US は従来通り RxNorm URI。
    if country_code == "JP" and drug_system_key == "yj" and code_value:
        code_system = _resolve_jp_drug_system_uri(code_value)
    else:
        code_system = get_system_uri(drug_system_key)

    med_concept: dict[str, Any] = {"text": drug_name}
    # #283 session 59:JP 出力で YJ system emit する場合、tx-server が
    # verify できない code(fragment 外)は nocoded fallback にダウングレード。
    # HAPI validator の VS binding error(594 件 v5)を解消しつつ薬剤名は
    # text field で保持。US path 及び verified YJ 及び HOT/RxNorm はそのまま
    # 通常 emit。
    # #283:downgrade は YJ-code URI 経由の code だけ対象。同 drug_system_key
    # ="yj" でも `_resolve_jp_drug_system_uri` が HOT7/HOT9/HOT13 に dispatch
    # した場合(全 HOT 系は別 CodeSystem)は対象外 = 通常 emit。
    _jp_yj_unverified = (
        country_code == "JP"
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
    elif country_code == "JP":
        # #291:JP-CLINS eCS(JP_MedicationRequest-eCS)は
        # `medication[x].coding` min=1 を要求。code_mapping にヒットしない
        # ED 特異薬(点眼薬 / 泌尿器系一次治療薬 等)+ #283 で tx-server
        # 未収録 YJ code は eCS の "nocoded" slice に fallback。drug_name を
        # display に流用(text field と重複するが nocoded slice の
        # `display` min=1 制約を満たすため)。
        # slice fixedUri は spec:
        # clinical-information-sharing#1.12.0/package/
        # CodeSystem-jp-eCS-medicationcode-nocoded-cs.json
        med_concept["coding"] = [
            {
                "system": _JP_MEDICATION_CODE_NOCODED_CS,
                "code": _JP_MEDICATION_CODE_NOCODED_CODE,
                "display": drug_name or _JP_MEDICATION_CODE_NOCODED_DISPLAY,
            }
        ]

    # ID: order_id は session 52 fix 0 で encounter-scoped 化された
    # (grep で "ORD-{encounter_id}-..." pattern に統一済)ので、そのまま
    # resource id として使えば globally unique。以前の "prepend encounter_id"
    # 実装は二重 prefix を作り 64-char 制限を超過(iris4h-ai HAPI 732 件)
    # + Endpoint/imgst/imgrpt double-prefix (session 51) と同一 class。
    resource_id = order.get("order_id") or str(uuid.uuid4())

    # C2-14 (session 42 cycle 2): MR.intent context-aware — mirrors C1-16 which
    # applied the same idea to ServiceRequest. Chronic-management refills →
    # `instance-order`; discharge take-home meds → `original-order`; the rest
    # remain `order`.
    intent_val = _mr_intent_from_order(order, encounter_type)
    # C2-16 (session 42): finished courses get status=completed. `end_datetime`
    # (or `discontinuation_datetime`) is populated in CIF when the course is
    # deliberately stopped or naturally ends; fall through to whatever
    # _map_order_status_to_fhir returns otherwise.
    # CO-9 (session 42 cycle 3): also complete when the encounter itself is
    # finished (outpatient Rx end at encounter close in JP practice).
    # RM-2 (session 42): episodic inpatient orders (Supportive / ED treatment /
    # antibiotics keyed on clinical_intent phrasing) complete at discharge.
    # Home-medication orders REMAIN active because chronic-meds continue
    # post-discharge.
    status_val = _map_order_status_to_fhir(order.get("status", ""))
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
    resource: dict[str, Any] = {
        "resourceType": "MedicationRequest",
        "id": resource_id,
        # Session 46 chain #2: JP Core MedicationRequest profile.
        **(
            {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_MedicationRequest"]}}
            if country_code == "JP"
            else {}
        ),
        # session 49 clinosim_feedback P1-4: JP_MedicationRequest.identifier
        # slice `rpNumber`(処方内 Rp グループ番号)+ `orderInRp`(Rp 内医薬品
        # 順序)の 2 slice を JP output で emit。system URL は JP Core 1.2.0
        # の StructureDefinition から取得(mhlw/IdSystem/Medication-RPGroupNumber
        # + MedicationAdministrationIndex)。
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
            if country_code == "JP"
            else {}
        ),
        "status": status_val,
        "intent": intent_val,
        "medicationCodeableConcept": med_concept,
        "subject": {"reference": f"Patient/{patient_id}"},
        "authoredOn": order.get("ordered_datetime", ""),
    }
    # CY6-22 (Chain-6): MedicationRequest.category — HL7 medicationrequest-
    # category (inpatient / outpatient / community / discharge). Derived
    # from encounter_type + is_home_med + is_episodic (already computed above).
    # ED encounters (encounter_type == "emergency") map to "outpatient" because
    # the patient is not admitted; discharge from ED emits under the same
    # community-Rx-at-discharge category as chronic outpatient scripts when
    # clinical_intent indicates the Rx is a take-home.
    _cat_code = _cat_display = ""
    if _is_home_med or (encounter_type == "outpatient" and not _is_episodic):
        _cat_code, _cat_display = "community", "Community"
    elif encounter_type == "outpatient":
        _cat_code, _cat_display = "outpatient", "Outpatient"
    elif encounter_type == "emergency":
        # ED order — outpatient by FHIR classification (no admission episode)
        _cat_code, _cat_display = "outpatient", "Outpatient"
    elif encounter_type == "inpatient":
        # Discharge medication if the clinical_intent explicitly says so
        if "discharge" in _ci_lower:
            _cat_code, _cat_display = "discharge", "Discharge"
        else:
            _cat_code, _cat_display = "inpatient", "Inpatient"
    else:
        # encounter_type not set (edge cases) — safe fallback to inpatient
        # since intent already indicated an order was authored (not a plan).
        _cat_code, _cat_display = "inpatient", "Inpatient"
    if _cat_code:
        resource["category"] = [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/medicationrequest-category",
                        "code": _cat_code,
                        "display": _cat_display,
                    }
                ],
            }
        ]

    # Encounter reference
    enc_ref = order.get("encounter_id", "") or encounter_id
    if enc_ref:
        resource["encounter"] = {"reference": f"Encounter/{enc_ref}"}

    # Requester (ordering physician)
    if order.get("ordered_by"):
        resource["requester"] = {"reference": f"Practitioner/{order['ordered_by']}"}
        # CY8-17 fix (session 48 cycle 8): MR.recorder = 記録者(オーダー入力者)。
        # clinosim では requester と同一 practitioner が入力する運用モデル、
        # ordered_by を fallback として emit(100% coverage)。
        resource["recorder"] = {"reference": f"Practitioner/{order['ordered_by']}"}

    # CY8-18 fix (session 48 cycle 8): MR.courseOfTherapyType — acute / continuous /
    # seasonal 分類。慢性処方(is_home_med / community intent)は continuous、
    # 急性期治療は acute、その他は継続困難なため無指定にせず acute default。
    # HL7 CodeSystem: http://terminology.hl7.org/CodeSystem/medicationrequest-course-of-therapy
    _course_code = "continuous" if (_is_home_med or _cat_code == "community") else "acute"
    # Displays follow the authoritative HL7 terminology R4 CodeSystem
    # `medicationrequest-course-of-therapy` (verified via
    # `hl7.terminology.r4#7.2.0/package/CodeSystem-medicationrequest-course-of-therapy.json`).
    # "Continuous long term therapy" (no hyphen) is the spec-canonical form —
    # the hyphenated variant produced 854 v4 fullset errors.
    _course_display = "Continuous long term therapy" if _course_code == "continuous" else "Short course (acute) therapy"
    resource["courseOfTherapyType"] = {
        "coding": [
            {
                "system": "http://terminology.hl7.org/CodeSystem/medicationrequest-course-of-therapy",
                "code": _course_code,
                "display": _course_display,
            }
        ],
    }

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
    dosage = _build_dosage_instruction(order, country=country)
    # Session 45: append any rate-adjustment note peeled off drug_name so the
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

    # Reason reference (link to primary diagnosis Condition)
    reason = order.get("reason_condition", "") or primary_dx_code
    if reason:
        cond_ref = f"cond-{encounter_id}-primary" if encounter_id else f"cond-{patient_id}-primary"
        resource["reasonReference"] = [
            {
                "reference": f"Condition/{cond_ref}",
            }
        ]

    # C4-15 (session 43 cycle 4): dispenseRequest for outpatient / discharge
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

    # C5-23 (session 43 cycle 5): MedicationRequest.substitution (0..1)
    # for generic substitution allowance. JP GE 促進 policy allows generic
    # substitution for chronic outpatient scripts unless explicitly
    # marked "brand only" — default `allowed = true` for outpatient/home-med.
    if encounter_type == "outpatient" or _is_home_med:
        resource["substitution"] = {"allowedBoolean": True}

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
) -> dict:
    """Build FHIR MedicationAdministration resource.

    rp_number / order_in_rp (session 49 clinosim_feedback P1-4): 対応する
    parent MedicationRequest と同じ値を渡すことで JP Core
    JP_MedicationAdministration.identifier slice を満たす。caller は同
    encounter 内で MR と同じ per-order 連番を割当てる。
    """
    drug_name_raw = mar.get("drug_name", "")
    drug_name_clean, protocol_category = _strip_protocol_prefix(drug_name_raw)
    # Session 45: peel off rate-adjustment suffix (see _build_medication_request).
    drug_name_clean, rate_adjustment_note = _split_rate_adjustment_suffix(drug_name_clean)
    drug_name = _localize_drug_name(drug_name_clean, country)
    base_name = drug_name_clean.split(" ")[0] if drug_name_clean else ""
    country_code = "US" if is_us(country) else "JP"
    lang = resolve_lang(country_code)
    drug_codes = load_code_mapping("drug", country_code)
    # C3-10 (session 42 cycle 3): longest-match-wins for multi-word keys.
    # CO-8 (Chain 4 2026-07-11): normalize underscores + honor MAR.code_yj
    # if downstream ever propagates the Order's code (see _build_medication_request).
    code_value = mar.get("code_yj", "") or ""
    if not code_value and drug_name_clean:
        normalized = drug_name_clean.replace("_", " ")
        tokens = normalized.split(" ")
        for n_tokens in range(len(tokens), 0, -1):
            candidate = " ".join(tokens[:n_tokens])
            if candidate in drug_codes:
                code_value = drug_codes[candidate]
                base_name = candidate
                break
        # Session 45: suffix-match fallback for qualifier-prefixed aliases.
        if not code_value and len(tokens) > 1:
            for n_tokens in range(len(tokens) - 1, 0, -1):
                candidate = " ".join(tokens[-n_tokens:])
                if candidate in drug_codes:
                    code_value = drug_codes[candidate]
                    base_name = candidate
                    break
        if not code_value:
            code_value = drug_codes.get(base_name.replace("_", " "), "")
    # C6-C7 residual sweep: same protocol_category fallback as MR builder.
    if not code_value and protocol_category:
        _pc = protocol_category.strip().lower().replace("_", " ").rstrip(":")
        for cand in (protocol_category, _pc, _pc.capitalize(), _pc.title()):
            if cand and cand in drug_codes:
                code_value = drug_codes[cand]
                break
    drug_system_key = system_key_for("drug", country_code)
    # session 53 F-1: JP は code 形式ごとに HOT7/HOT9/HOT13/YJ URI へ dispatch
    # (MR builder と同じ helper)。US は RxNorm URI。
    if country_code == "JP" and drug_system_key == "yj" and code_value:
        code_system = _resolve_jp_drug_system_uri(code_value)
    else:
        code_system = get_system_uri(drug_system_key)

    med_concept: dict[str, Any] = {"text": drug_name}
    # #283 session 59:MR builder と同 gate — tx-server 未収録 JP YJ code は
    # nocoded fallback にダウングレード(薬剤名は text field で保持)。
    # #283:downgrade は YJ-code URI 経由の code だけ対象。同 drug_system_key
    # ="yj" でも `_resolve_jp_drug_system_uri` が HOT7/HOT9/HOT13 に dispatch
    # した場合(全 HOT 系は別 CodeSystem)は対象外 = 通常 emit。
    _jp_yj_unverified = (
        country_code == "JP"
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
    elif country_code == "JP":
        med_concept["coding"] = [
            {
                "system": _JP_MEDICATION_CODE_NOCODED_CS,
                "code": _JP_MEDICATION_CODE_NOCODED_CODE,
                "display": drug_name or _JP_MEDICATION_CODE_NOCODED_DISPLAY,
            }
        ]

    resource: dict[str, Any] = {
        "resourceType": "MedicationAdministration",
        "id": f"mar-{encounter_id or patient_id}-{index:05d}",
        # Session 46 chain #2: JP Core MedicationAdministration profile.
        **(
            {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_MedicationAdministration"]}}
            if country_code == "JP"
            else {}
        ),
        # session 49 clinosim_feedback P1-4: JP_MedicationAdministration.
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
            if country_code == "JP"
            else {}
        ),
        "status": _map_mar_status(mar.get("status", "completed")),
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
    # Session 52 fix: MR resource id は order_id 単体(encounter-scoped で
    # globally unique)。以前は `{enc_id}-{order_id}` 二重 prefix だったが
    # session 52 で削除、reader/writer 両側を同期(session 51 imgst/imgrpt
    # double-prefix と同一 class の reference-integrity fix)。CI で 890
    # dangling references を surface。
    mar_order_id = mar.get("order_id", "")
    if mar_order_id:
        resource["request"] = {"reference": f"MedicationRequest/{mar_order_id}"}

    if mar.get("administered_by"):
        resource["performer"] = [{"actor": {"reference": f"Practitioner/{mar['administered_by']}"}}]

    # Dosage with structured dose + route
    dose_text = mar.get("dose", "") or drug_name
    dose_str = mar.get("dose", "")
    parsed = _parse_dose_for_mar(dose_str or drug_name)
    # Session 45: attach any rate-adjustment note peeled off drug_name to dose_text
    # so continuous-infusion titration intent surfaces in the dosage record.
    if rate_adjustment_note:
        rate_note_localized = _localize_rate_adjustment(rate_adjustment_note, country)
        dose_text = f"{dose_text} ({rate_note_localized})".strip() if dose_text.strip() else rate_note_localized
    dosage: dict[str, Any] = {"text": dose_text}
    if parsed.get("dose_quantity") is not None and parsed.get("dose_unit"):
        # Route through build_ucum_quantity so `code` is populated (JP-CLINS
        # eCS profiles require it — feedback fix PR-A, 2026-07-16).
        dosage["dose"] = build_ucum_quantity(parsed["dose_quantity"], parsed["dose_unit"])
    # Rate for continuous infusions
    if "CONTINUOUS" in dose_text.upper() or "DRIP" in dose_text.upper() or "/h" in dose_text:
        rate_value = parsed.get("dose_quantity") or 1
        rate_unit = parsed.get("dose_unit", "mL") + "/h"
        dosage["rateQuantity"] = build_ucum_quantity(rate_value, rate_unit)
    # Route
    route = (mar.get("route") or parsed.get("route") or "").upper()
    if route:
        snomed = _ROUTE_SNOMED.get(route)
        if snomed:
            dosage["route"] = {
                "coding": [{"system": get_system_uri("snomed-ct"), **snomed}],
                "text": route,
            }
        else:
            dosage["route"] = {"text": route}
    # Session 57 v3 (Chain-11, v3 feedback §保留 3 真因判明): FHIR R4
    # `mad-1` requires `dosage.dose.exists() or dosage.rate.exists()` when a
    # dosage element is present. Sliding-scale insulin / PRN / infusion
    # bolus orders that only carry a `dosage.text` (no parsable numeric
    # dose) tripped 3,005 MedicationAdministration resources. Drop the
    # dosage element entirely when neither `dose` nor `rateQuantity` is
    # populated — CIF still carries the free-text order description via
    # the Order's `dose` field for downstream consumers.
    if "dose" in dosage or "rateQuantity" in dosage:
        resource["dosage"] = dosage

    # Reason reference (link to primary diagnosis)
    if primary_dx_code:
        cond_ref = f"cond-{encounter_id}-primary" if encounter_id else f"cond-{patient_id}-primary"
        resource["reasonReference"] = [
            {
                "reference": f"Condition/{cond_ref}",
            }
        ]
        # CY8-19 fix (session 48 cycle 8): MAR.reasonCode — primary diagnosis
        # ICD code を CodeableConcept で並置(reasonReference との duplication は
        # FHIR R4 で recommended:code と reference は互いに補完)。
        # US = icd-10-cm、JP = icd-10。
        #
        # #208 (2026-07-17):`primary_dx_code` は CIF の
        # `admission_diagnosis_code` にセットされる disease-YAML の
        # `icd_codes.primary` 値を由来として、しばしば CM-granular な
        # 表現(S72.00 / E11.65 / …)を含む。JP output では
        # `_map_diagnosis_code` を通して WHO ICD-10 3-4 桁の親コードへ
        # 畳み込む必要がある(fhir-jp-validator 2026-07-17 §【最優先 6】
        # 7,652 errors)。US では identity(既に CM billable leaf に
        # `code_mapping_diagnosis/us.yaml` で解決済み)。他 builder
        # (Encounter.reasonCode / Condition.code / FamilyMemberHistory.code)
        # は同 seam を既に通しており、これで漏れ経路が閉じる。
        _icd_system = get_system_uri("icd-10-cm" if country_code == "US" else "icd-10")
        _mapped_dx_code = _map_diagnosis_code(primary_dx_code, country_code)
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

    # CY8-20 fix (session 48 cycle 8): MAR.device — 持続点滴 (continuous
    # infusion / drip) のとき infusion pump Device を参照。route=IV かつ
    # rate指定ある/CONTINUOUS/DRIP を含む admin のみ pump 参照 emit。
    # Device resource 自体は既存 hospital-main の generic infusion pump を
    # 参照(実 EHR 実装と同様、pump を patient に固有発行しない運用)。
    _dose_text_up = (mar.get("dose") or "").upper()
    _is_infusion = route == "IV" and ("CONTINUOUS" in _dose_text_up or "DRIP" in _dose_text_up or "/H" in _dose_text_up)
    if _is_infusion:
        resource["device"] = [
            {
                "reference": "Device/dev-infusion-pump",
                "display": "汎用輸液ポンプ" if country_code == "JP" else "Generic infusion pump",
            }
        ]

    return resource
