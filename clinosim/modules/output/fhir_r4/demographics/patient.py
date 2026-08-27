"""FHIR R4 patient-demographics resource builders (FA-1 Phase 11).

Patient, JP Core Coverage (+ payor Organization), occupation Observation, and
AllergyIntolerance — plus the identity-config cache and the marital/language/
coverage display constants used only by this cluster. Extracted verbatim from
``fhir_r4_adapter``; depends only on clinosim.codes/locale and the leaf
reference/localization + _fhir_common helper modules (no adapter import cycle).
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.locale.loader import load_identity_config
from clinosim.modules._shared import is_jp, resolve_lang
from clinosim.modules.output.fhir_r4.lib.common import (
    _coding_with_display,
    _social_category,
    build_address,
    build_telecom,
    to_fhir_date,
)
from clinosim.modules.output.fhir_r4.lib.ids import (
    derive_opaque_id,
    structural_key_system,
    wrap_as_identifier,
)
from clinosim.modules.output.fhir_r4.lib.localization import (
    _OCCUPATION_DISPLAY_EN,
    _OCCUPATION_DISPLAY_JA,
    _RELATIONSHIP_DISPLAY_JA,
    _localize_display,
    _localize_drug_name,
)
from clinosim.modules.output.fhir_r4.lib.reference_data import _ALLERGEN_RXNORM

# === Issue #854 Bucket A row 4 (PR-obs-standalone): opaque occupation id ===
# Structural key = pre-#854 id body (patient id).
OCCUPATION_ID_PREFIX = "occupation-"
OCCUPATION_KEY_SYSTEM = structural_key_system("occupation-observation-key")


def _resolve_occupation_id(structural_key: str) -> str:
    return derive_opaque_id(OCCUPATION_ID_PREFIX, structural_key)


# === Issue #854 Bucket C (PR-coverage): opaque Coverage.id ===
# Structural key = pre-#854 id body `{patient_id}-{idx}` (`cov-` prefix
# stripped); post-#854 every `.id` is `cov-<12hex>` (16 chars, fixed).
# Coverage already carries a member-id identifier[] for the JP insurance
# number; a second entry under COVERAGE_KEY_SYSTEM round-trips the
# structural key so consumers keyed on the old id still work.
COVERAGE_ID_PREFIX = "cov-"
COVERAGE_KEY_SYSTEM = structural_key_system("coverage-key")


def _resolve_coverage_id(structural_key: str) -> str:
    return derive_opaque_id(COVERAGE_ID_PREFIX, structural_key)


# FHIR R4 standard: payer organization type
_ORG_TYPE_SYSTEM = get_system_uri("hl7-organization-type")
# FHIR R4 standard: beneficiary's relationship to the policy subscriber
_SUBSCRIBER_REL_SYSTEM = get_system_uri("hl7-subscriber-relationship")


def _default_coverage_period_year(patient_data: dict) -> int:
    """Pick a default calendar year for Coverage.period when the enrollment
    lacks explicit start/end (C2-11 fallback). Uses the patient's first
    encounter year if available; otherwise a fixed simulation year.
    """
    encs = patient_data.get("encounters", [])
    if encs:
        first_dt = encs[0].get("admission_datetime", "") or encs[0].get("period", {}).get("start", "")
        first_dt = str(first_dt)
        if len(first_dt) >= 4 and first_dt[:4].isdigit():
            return int(first_dt[:4])
    return 2025


@lru_cache(maxsize=2)
def _identity_cfg(country: str) -> dict:
    """Full resident-identity locale config (AD-54).

    ``@lru_cache(maxsize=2)`` bounds the cache to the two supported
    countries (US / JP). Issue #557: replaces the pre-Aug-2026 pattern
    of a module-level `_IDENTITY_CFG_CACHE: dict` mutated across module
    boundaries — the previous 3 external re-imports (`_fhir_post_process`,
    `_fhir_inline_bb`) were unused ``noqa: F401`` re-exports and are
    removed.
    """
    return load_identity_config(country)


def _payer_name_map(country: str) -> dict[str, str]:
    """Map 保険者番号 → insurer name from locale (display resolved at output, AD-30)."""
    payers = _identity_cfg(country).get("payers", {})
    out: dict[str, str] = {}
    for entries in payers.values():
        for e in entries or []:
            if e.get("number"):
                out[str(e["number"])] = str(e.get("name", e["number"]))
    return out


def _build_coverage_resources(patient_data: dict, country: str) -> list[dict]:
    """Build JP Core Coverage + payor Organization from the patient's insurance enrollment.

    Reads CIF data only (no dependency on the identity module — module independence).
    `national_id` is never read here: the privacy chokepoint (AD-54) means individual
    numbers are never emitted to FHIR.
    """
    cfg = _identity_cfg(country).get("fhir_coverage", {})
    if not cfg:
        return []
    name_map = _payer_name_map(country)
    type_labels = _identity_cfg(country).get("coverage_type_labels", {})
    identity = patient_data.get("identity") or {}
    enrollments = identity.get("enrollments") or []
    pid = patient_data.get("patient_id", "")
    resources: list[dict] = []

    for idx, enr in enumerate(enrollments):
        insurer = enr.get("insurer_number") or ""
        number = enr.get("member_id") or ""
        symbol = enr.get("group_symbol")
        branch = enr.get("branch_number")
        category = enr.get("category") or ""
        if not insurer or not number:
            continue

        payer_org_id = f"payer-{insurer}"
        resources.append(
            {
                "resourceType": "Organization",
                "id": payer_org_id,
                "identifier": [
                    {
                        "system": cfg.get("insurer_number_system", ""),
                        "value": insurer,
                    }
                ],
                "type": [
                    {
                        "coding": [
                            {
                                "system": _ORG_TYPE_SYSTEM,
                                "code": "pay",
                                "display": "Payer",
                            }
                        ]
                    }
                ],
                "name": name_map.get(insurer, insurer),
            }
        )

        # JP Core extensions: 記号 / 番号 / 枝番
        extensions: list[dict] = []
        if symbol:
            extensions.append({"url": cfg.get("ext_symbol", ""), "valueString": symbol})
        extensions.append({"url": cfg.get("ext_number", ""), "valueString": number})
        if branch:
            extensions.append({"url": cfg.get("ext_subnumber", ""), "valueString": branch})

        # Composite member identifier: 保険者番号:記号:番号:枝番
        composite = ":".join([insurer, symbol or "", number, branch or ""])
        subscriber = f"{symbol}:{number}" if symbol else number

        _cov_structural_key = f"{pid}-{idx}"
        coverage: dict[str, Any] = {
            "resourceType": "Coverage",
            "id": _resolve_coverage_id(_cov_structural_key),
            "extension": extensions,
            "identifier": [
                {"system": cfg.get("member_id_system", ""), "value": composite},
                wrap_as_identifier(_cov_structural_key, COVERAGE_KEY_SYSTEM),
            ],
            "status": "active",
            "subscriberId": subscriber,
            # CY7-13 (Chain-7): Coverage.subscriber — the person carrying the
            # policy. For "self" relationship the subscriber IS the beneficiary
            # (JP 主たる被保険者 = 本人); for "other" (dependent) it's the
            # policy-holder relative. Without a distinct 主たる被保険者
            # Person record, we point to the patient themselves (matches
            # subscriberId derivation above and passes FHIR R4 conformance —
            # subscriber is 0..1 Reference to Patient|RelatedPerson).
            "subscriber": {"reference": f"Patient/{pid}"},
            "beneficiary": {"reference": f"Patient/{pid}"},
            "payor": [{"reference": f"Organization/{payer_org_id}"}],
        }
        if cfg.get("profile"):
            coverage["meta"] = {"profile": [cfg["profile"]]}
        if branch:
            coverage["dependent"] = branch
        # C2-06: resolve display via codes/data/
        # hl7-subscriber-relationship.yaml — was raw code emission.
        # Beneficiary's relationship to the subscriber: 被扶養者 → not self.
        rel_code = "other" if category == "dependent" else "self"
        coverage["relationship"] = {
            "coding": [
                _coding_with_display(
                    "hl7-subscriber-relationship",
                    rel_code,
                    resolve_lang(country),
                )
            ]
        }
        # Coverage.type: human label (text-only CodeableConcept — no fabricated codes).
        label = type_labels.get(category)
        if label:
            coverage["type"] = {"text": label}
        # C2-11: guarantee Coverage.period. FHIR R4
        # recommends period on active coverage. If enrollment lacks explicit
        # start/end, default to the current calendar year — clinosim's
        # 保険証 renewal cycle is annual per JP 医療保険 practice.
        # C3-08 review (cycle 3): JP 保険証 valid period actually runs
        # 4/1 → 3/31 (fiscal year), not calendar year. Use fiscal boundary.
        period = {}
        if enr.get("valid_from"):
            period["start"] = enr["valid_from"]
        if enr.get("valid_to"):
            period["end"] = enr["valid_to"]
        if not period:
            year = _default_coverage_period_year(patient_data)
            period = {"start": f"{year}-04-01", "end": f"{year + 1}-03-31"}
        coverage["period"] = period
        # C3-08: Coverage.class[] — group / plan
        # classification. For JP, class[0].type=group with 保険者番号 as
        # the coverage class identifier.
        # C5-09: diversify to include both `group` and
        # `plan` classifications when insurer symbol resolves to a plan
        # name — plan carries the human-readable insurance product name.
        _class_entries: list[dict[str, Any]] = [
            {
                "type": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/coverage-class",
                            "code": "group",
                            "display": "Group" if not is_jp(country) else "保険グループ",
                        }
                    ],
                },
                "value": insurer,
                "name": name_map.get(insurer, insurer),
            }
        ]
        if symbol:
            _class_entries.append(
                {
                    "type": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/coverage-class",
                                "code": "plan",
                                "display": "Plan" if not is_jp(country) else "保険プラン",
                            }
                        ],
                    },
                    "value": symbol,
                    "name": name_map.get(insurer, insurer),
                }
            )
        coverage["class"] = _class_entries
        # CY7-14 (Chain-7): Coverage.costToBeneficiary — JP 自己負担割合.
        # Standard JP 医療保険 co-pay: 3割 for adults, 1割 for elderly (≥70,
        # 現役並み所得除く). Population module carries age; use category as
        # a proxy (late-elderly insurer = 1割; others = 3割 default).
        _coshare_pct = 10 if insurer == "39130083" else 30  # 39130083 = 後期高齢者
        coverage["costToBeneficiary"] = [
            {
                "type": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/coverage-copay-type",
                            "code": "copaypct",
                            "display": "Copay percentage",
                        }
                    ],
                    "text": "自己負担割合" if is_jp(country) else "Copay percentage",
                },
                "valueQuantity": {
                    "value": _coshare_pct,
                    "unit": "%",
                    "system": "http://unitsofmeasure.org",
                    "code": "%",
                },
            }
        ]
        resources.append(coverage)

    return resources


def _build_patient(p: dict, country: str) -> dict:
    """Build FHIR Patient resource with locale-aware name."""
    # Extract name from patient profile
    name_data = p.get("name", {})
    family = name_data.get("family_name", p.get("patient_id", ""))
    given = name_data.get("given_name", "")

    gender = "female" if p.get("sex") == "F" else "male"
    dob = p.get("date_of_birth")

    # Build FHIR HumanName. C2-19: JP Core requires
    # kanji + kana names as TWO separate name[] entries, each tagged with the
    # ISO21090 EN-representation extension using `valueCode` (was
    # `valueString` — an FHIR schema violation, JP Core validators reject).
    # Kanji name → IDE (ideographic), phonetic (katakana / hiragana) → SYL.
    ISO21090_URL = "http://hl7.org/fhir/StructureDefinition/iso21090-EN-representation"
    # C4-12: HumanName.use = "official" per FHIR R4 spec
    # and JP Core Patient recommendation for the registered / kanji name.
    names: list[dict[str, Any]] = []
    if is_jp(country):
        # Kanji entry — always emitted for JP.
        # Issue #378: JP_Patient_eCS requires `name.text` (min=1). Concatenate
        # kanji family + given with a single space (JP clinical convention:
        # "田中 徹") so the eCS profile assertion is data-complete.
        kanji_name: dict[str, Any] = {
            "use": "official",
            "text": f"{family} {given}".strip(),
            "family": family,
            "given": [given],
            "extension": [{"url": ISO21090_URL, "valueCode": "IDE"}],
        }
        names.append(kanji_name)
        # Phonetic (kana) entry — emitted only when phonetic pair present.
        # Issue #732: population/engine.py emits `PersonName.phonetic` as a
        # single string "<family-kana> <given-kana>" (see PersonName typed as
        # `str | None`), so the historical `isinstance(phonetic, dict)` gate
        # silently skipped 100% of JP Patients — no SYL entry across the
        # baseline. Accept both shapes so the emit doesn't rely on an upstream
        # schema unification: dict-form (already correct) OR string-form
        # (split on whitespace into family + given kana).
        phonetic = name_data.get("phonetic")
        kana_family = kana_given = ""
        if isinstance(phonetic, dict):
            kana_family = phonetic.get("family_name", "")
            kana_given = phonetic.get("given_name", "")
        elif isinstance(phonetic, str) and phonetic.strip():
            _parts = phonetic.strip().split(None, 1)
            kana_family = _parts[0] if _parts else ""
            kana_given = _parts[1] if len(_parts) > 1 else ""
        if kana_family or kana_given:
            _kana_fam = kana_family or family
            _kana_giv = kana_given or given
            names.append(
                {
                    "use": "official",
                    "text": f"{_kana_fam} {_kana_giv}".strip(),
                    "family": _kana_fam,
                    "given": [_kana_giv],
                    "extension": [{"url": ISO21090_URL, "valueCode": "SYL"}],
                }
            )
    else:
        names.append({"use": "official", "family": family, "given": [given]})
    names[0]  # kept for legacy readers below

    pid = p.get("patient_id", str(uuid.uuid4()))
    # Hospital MRN identifier system (country-specific)
    mrn_system = (
        "urn:oid:1.2.392.100495.20.3.51.1"  # JP example MRN OID
        if is_jp(country)
        else "http://hospital.example.org/identifiers/mrn"
    )
    resource: dict[str, Any] = {
        "resourceType": "Patient",
        "id": pid,
        # C2-20: declare JP Core Patient conformance
        # for JP exports. US export intentionally omits — no US Core profile
        # is asserted (a separate roadmap item).
        #
        # Issue #378 (restoring #379 with data-completeness):
        # JP_Patient_eCS assertion RESTORED. #382 removed the URI because
        # #379 had shipped URI-only without emitting the required fields
        # (`name.text`, `address.text`, `meta.lastUpdated`) — the resulting
        # 5× validator cascade justified the revert (feedback:
        # `feedback_profile_assertion_requires_data_completeness`). This PR
        # emits all three required fields BEFORE claiming the profile, so
        # the assertion is now data-complete and the eCS Pattern B (3,096
        # errors on referring resources) is resolved without the earlier
        # cascade. SD-verified min=1 requirements: `meta.lastUpdated`,
        # `meta.profile`, `name`, `name.text`, `name.given`, `gender`,
        # `birthDate`, `address`, `address.text`.
        **(
            {
                "meta": {
                    "profile": [
                        "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Patient",
                        "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Patient_eCS",
                    ],
                    # Static deterministic timestamp mirrors `_fhir_facility.py`
                    # (pattern). Real-world lastUpdated is server-
                    # provided; clinosim's simulator has no such notion, so
                    # a fixed value keeps reproducibility byte-clean while
                    # satisfying the eCS min=1 requirement.
                    "lastUpdated": "2026-01-01T00:00:00+09:00",
                }
            }
            if is_jp(country)
            else {}
        ),
        "identifier": [
            {
                "use": "usual",
                "type": {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-v2-0203"),
                            "code": "MR",
                            "display": "Medical Record Number",
                        }
                    ],
                    "text": "診療録番号" if is_jp(country) else "MRN",
                },
                "system": mrn_system,
                "value": pid,
                "assigner": {"reference": "Organization/hospital-main"},
            }
        ],
        "active": True,
        "name": names,
        "gender": gender,
    }

    if dob:
        resource["birthDate"] = to_fhir_date(dob)

    # CY7-15 (Chain-7): multipleBirthBoolean — required by JP Core Patient
    # profile 0..1. Default false (majority — realistic multiple-birth
    # rate <2% for JP live-birth records but registered explicitly on
    # birth certificate). Population module doesn't currently model this,
    # so default across cohort is a defensible completeness fix (Coverage:
    # boolean false is a valid emit per FHIR R4).
    resource["multipleBirthBoolean"] = False

    # CY7-16 (Chain-7): deceased[Boolean|DateTime] — carries mortality
    # status. Default deceasedBoolean=false because Patient records in
    # clinosim represent the living cohort at snapshot time; if the CIF
    # marks the patient as deceased, override with deceasedDateTime.
    _dod = p.get("date_of_death", "") or p.get("dod", "")
    if _dod:
        resource["deceasedDateTime"] = str(_dod)
    else:
        resource["deceasedBoolean"] = False

    # Blood type: v3 fix — JP Core (as of jpfhir.jp.core#1.2.0)
    # does not define a `JP_Patient_BloodTypeCode` Extension, and neither
    # FHIR core nor US Core specifies a Patient-level BloodType extension.
    # The URL we used to emit was fabricated; v3 validation flagged all
    # 580 JP Patients with an unknown-extension warning (580 resources /
    # ext URL). The follow-up chain now emits blood type as two
    # laboratory Observations per patient (LOINC 883-9 ABO group +
    # LOINC 10331-7 Rh group, SNOMED CT valueCodeableConcept) via
    # `_bb_blood_type` (`labs/blood_type.py`); the Patient resource
    # stays free of a fabricated extension.
    _ = p.get("blood_type")  # explicit no-op: blood type is emitted as Observation, not on Patient

    # Address
    addr = p.get("address")
    if addr and isinstance(addr, dict):
        fhir_addr = build_address(addr, country)
        if fhir_addr:
            resource["address"] = [fhir_addr]

    # Telecom (phone)
    contact = p.get("contact")
    if contact and isinstance(contact, dict):
        telecoms = build_telecom(contact)
        if telecoms:
            resource["telecom"] = telecoms

    # Marital status
    marital = p.get("marital_status", "")
    if marital:
        resource["maritalStatus"] = {
            "coding": [
                {
                    "system": get_system_uri("hl7-v3-maritalstatus"),
                    "code": marital,
                    "display": code_lookup("hl7-v3-maritalstatus", marital, resolve_lang(country)),
                }
            ],
        }

    # Communication / preferred language
    lang = p.get("preferred_language", "")
    if lang:
        # BCP-47 (`urn:ietf:bcp:47`) is English-only per the fhir-jp-validator
        # tx-server loadout — the ja localization is not a registered synonym.
        # Emit the English display regardless of country.
        resource["communication"] = [
            {
                "language": {
                    "coding": [
                        {
                            "system": get_system_uri("bcp-47-language"),
                            "code": lang,
                            "display": code_lookup("bcp-47-language", lang, "en"),
                        }
                    ],
                },
                "preferred": True,
            }
        ]

    # Emergency contact
    if contact and isinstance(contact, dict):
        emer_name = contact.get("emergency_contact_name", "")
        emer_phone = contact.get("emergency_contact_phone", "")
        emer_rel = contact.get("emergency_contact_relationship", "")
        if emer_name or emer_phone:
            ec: dict[str, Any] = {}
            if emer_rel:
                ec["relationship"] = [
                    {
                        "coding": [
                            {
                                "system": get_system_uri("hl7-v2-0131"),
                                "code": "C",
                                "display": "Emergency Contact",
                            }
                        ],
                        "text": _localize_display(emer_rel, country, _RELATIONSHIP_DISPLAY_JA),
                    }
                ]
            if emer_name:
                ec["name"] = {"text": emer_name}
            if emer_phone:
                ec["telecom"] = [
                    {
                        "system": "phone",
                        "value": emer_phone,
                        "use": "mobile",
                    }
                ]
            resource["contact"] = [ec]

    # Issue #743: JP_Patient_eCS declares `JP_eCS_InstitutionNumber` as
    # must-support (the Department extension context excludes Patient).
    # Attach here (inline) because Patient's eCS profile URL is set
    # directly on this builder, not via `_apply_jp_clins_profile` post-hook.
    from clinosim.modules.output.fhir_r4.lib.common import attach_ecs_institutional_extensions

    attach_ecs_institutional_extensions(resource, country, include_department=False)

    return resource


# ============================================================
# AllergyIntolerance
# ============================================================


# Occupation category localization for Observation.valueCodeableConcept
def _build_occupation_observation(
    occupation: str,
    patient_id: str,
    country: str,
) -> dict | None:
    """Build FHIR Observation for patient occupation (social history).

    Uses US Core Patient Occupation profile (LOINC 11341-5).
    Reference: http://hl7.org/fhir/us/core/StructureDefinition/us-core-occupation
    """
    if not occupation:
        return None
    display_map = _OCCUPATION_DISPLAY_JA if is_jp(country) else _OCCUPATION_DISPLAY_EN
    display = display_map.get(occupation, occupation.title())
    _occupation_key = patient_id
    return {
        "resourceType": "Observation",
        "id": _resolve_occupation_id(_occupation_key),
        "identifier": [wrap_as_identifier(_occupation_key, OCCUPATION_KEY_SYSTEM)],
        # chain #2: JP Core Observation_Common profile.
        **(
            {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common"]}}
            if is_jp(country)
            else {}
        ),
        "status": "final",
        "category": _social_category(country),
        "code": {
            "coding": [
                {
                    "system": get_system_uri("loinc"),
                    "code": "11341-5",
                    "display": "History of Occupation",
                }
            ],
            "text": "職業" if is_jp(country) else "Occupation",
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "valueCodeableConcept": {
            "coding": [
                {
                    "system": get_system_uri("occupation-category"),
                    "code": occupation,
                    "display": display,
                }
            ],
            "text": display,
        },
    }


def _build_allergy_intolerance(
    allergy: dict,
    patient_id: str,
    index: int,
    country: str,
) -> dict | None:
    """Build FHIR AllergyIntolerance from CIF allergy data."""
    substance = allergy.get("substance", "")
    if not substance:
        return None

    # Localize substance display for JP
    substance_display = _localize_drug_name(substance, country) if is_jp(country) else substance

    rxnorm = _ALLERGEN_RXNORM.get(substance, "")
    code: dict[str, Any] = {"text": substance_display}
    if rxnorm:
        code["coding"] = [
            {
                "system": get_system_uri("rxnorm"),
                "code": rxnorm,
                "display": substance_display,
            }
        ]

    severity = allergy.get("severity", "mild").lower()
    criticality = "high" if severity == "severe" else "low"

    reaction_type = allergy.get("reaction_type", "")
    reaction: dict[str, Any] = {"severity": severity}
    if reaction_type:
        reaction["manifestation"] = [
            {
                "text": reaction_type,
            }
        ]

    return {
        "resourceType": "AllergyIntolerance",
        "id": f"allergy-{patient_id}-{index:02d}",  # patient-scoped is OK (allergies are patient-level)
        "clinicalStatus": {
            "coding": [
                {
                    "system": get_system_uri("hl7-allergyintolerance-clinical"),
                    "code": "active",
                    "display": "Active",
                }
            ],
        },
        "verificationStatus": {
            "coding": [
                {
                    "system": get_system_uri("hl7-allergyintolerance-verification"),
                    "code": "confirmed",
                    "display": "Confirmed",
                }
            ],
        },
        "type": "allergy",
        "category": ["medication"],
        "criticality": criticality,
        "code": code,
        "patient": {"reference": f"Patient/{patient_id}"},
        "reaction": [reaction],
    }
