"""FHIR R4 Practitioner / PractitionerRole resource builders (FA-1 Phase 4).

Extracted verbatim from ``fhir_r4_adapter``. Both builders are self-contained:
they depend only on :mod:`clinosim.codes` and the leaf reference/localization
modules, so they import no helpers back through the adapter facade.
"""

from __future__ import annotations

import hashlib
from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.locale.loader import load_practitioner_qualifications
from clinosim.modules._shared import is_jp, resolve_lang
from clinosim.modules.output.fhir_r4.lib.common import _coding_with_display
from clinosim.modules.output.fhir_r4.lib.localization import _ROLE_PREFIX_MAP_JA
from clinosim.modules.output.fhir_r4.lib.reference_data import (
    _ROLE_PREFIX_MAP,
    _SPECIALTY_SNOMED,
)


def _license_number(staff_id: str, salt: str, digits: int) -> str:
    """Derive a deterministic zero-padded license number for a staff_id.

    Issue #962: JP MHLW 免許登録番号 (医籍番号 / 看護師籍登録番号 /
    薬剤師名簿登録番号 …) is a per-practitioner identifier issued at
    license grant. clinosim does not simulate license issuance, so we
    derive a stable synthetic value from ``sha256(salt + staff_id)`` —
    an RNG-neutral additive field per
    :file:`feedback_rng_neutral_additive_field.md` — that never consumes
    the master RNG and thus can be added without shifting downstream
    determinism.
    """
    digest = hashlib.sha256(f"{salt}:{staff_id}".encode()).hexdigest()
    modulus = 10**digits
    value = int(digest[:16], 16) % modulus
    return f"{value:0{digits}d}"


def _build_jp_qualifications(staff: dict, staff_id: str) -> list[dict[str, Any]]:
    """Build JP MHLW-coded ``Practitioner.qualification`` entries (Issue #962).

    Returns:
        Empty list when the JP qualification yaml is unavailable or the
        role is unmapped — callers then fall through to the pre-#962
        v2-0360 / text-only qualification code path so we never regress
        existing coverage.

        Otherwise a 1- or 2-element list:

        * ``[0]`` — MHLW national license (医師 / 看護師 / 薬剤師 …).
        * ``[1]`` — physician specialty board (循環器専門医 / …) when the
          role is physician/radiologist AND the staff's specialty (or
          department) maps to a board in
          ``physician_specialty_boards``.
    """
    cfg = load_practitioner_qualifications("JP")
    if not cfg:
        return []
    role = staff.get("role", "")
    qual_codes = cfg.get("qualification_codes", {}) or {}
    entry = qual_codes.get(role)
    if not entry:
        return []
    system = cfg.get("code_system", "")
    qual_year = staff.get("qualification_year")

    def _qualification(code: str, display: str) -> dict[str, Any]:
        q: dict[str, Any] = {
            "code": {
                "coding": [{"system": system, "code": code, "display": display}],
                "text": display,
            }
        }
        if qual_year:
            q["period"] = {"start": f"{qual_year}-01-01"}
        return q

    qualifications: list[dict[str, Any]] = [_qualification(entry["code"], entry["display"])]

    # Physician / radiologist specialty board (専門医資格) as qualification[1].
    if role in ("physician", "radiologist"):
        specialty = staff.get("specialty", "") or staff.get("department", "")
        boards = cfg.get("physician_specialty_boards", {}) or {}
        board = boards.get(specialty) or boards.get(staff.get("department", ""))
        if board:
            qualifications.append(_qualification(board["code"], board["display"]))
    return qualifications


def _build_jp_license_identifier(staff: dict, staff_id: str) -> dict[str, Any] | None:
    """Build the JP MHLW regulatory-license ``identifier`` entry (Issue #962).

    Returns ``None`` when the yaml is unavailable, the role is unmapped
    (e.g. MSW — not an MHLW-licensed profession in JP), or the config
    is malformed. The value is the human-readable form
    ``{prefix}{zero-padded digits}{suffix}`` (e.g. "第012345号") so a
    reader displaying `.value` directly sees the conventional 医籍番号
    rendering.
    """
    cfg = load_practitioner_qualifications("JP")
    if not cfg:
        return None
    role = staff.get("role", "")
    lic_map = cfg.get("license_identifiers", {}) or {}
    lic = lic_map.get(role)
    if not lic:
        return None
    salt = cfg.get("license_identifier_salt", "practitioner-license")
    digits = int(lic.get("digits", 6))
    number = _license_number(staff_id, salt, digits)
    formatted = f"{lic.get('prefix', '')}{number}{lic.get('suffix', '')}"
    label = lic.get("label", "medical-license")
    return {
        "use": "official",
        "type": {"text": label},
        "system": lic["system"],
        "value": formatted,
    }


def _build_practitioner(staff_id: str, roster_map: dict[str, dict] | None = None, country: str = "US") -> dict:
    """Build FHIR Practitioner resource. Uses roster data when available."""
    resource: dict[str, Any] = {
        "resourceType": "Practitioner",
        "id": staff_id,
        # chain #2: JP Core Practitioner profile.
        **(
            {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Practitioner"]}}
            if is_jp(country)
            else {}
        ),
        "active": True,
        "identifier": [{"system": "urn:clinosim:staff", "value": staff_id}],
    }

    staff = (roster_map or {}).get(staff_id)
    # Issue #962: JP MHLW 免許登録番号 (医籍番号 / 看護師籍登録番号 /
    # 薬剤師名簿登録番号 …) as a second identifier entry alongside the
    # internal staff key. Deterministic per-staff_id (SHA-256 salted),
    # RNG-neutral (never consumes master RNG). US path unchanged.
    if staff and is_jp(country):
        lic_ident = _build_jp_license_identifier(staff, staff_id)
        if lic_ident:
            resource["identifier"].append(lic_ident)
    if staff:
        full_name = staff.get("name", "")
        role = staff.get("role", "")

        # Parse name (JP: "姓 名", US: "given family")
        parts = full_name.split(" ", 1)
        if len(parts) == 2:
            # Determine ordering by checking for non-ASCII
            if any(ord(c) > 0x3000 for c in full_name):
                family, given = parts[0], parts[1]
            else:
                given, family = parts[0], parts[1]
        else:
            family, given = full_name, ""

        name_obj: dict[str, Any] = {"family": family, "given": [given] if given else []}
        if role in ("physician", "radiologist") and not is_jp(country):
            name_obj["prefix"] = ["Dr."]
        # C3-01: JP Core requires kanji (IDE)
        # representation tag on Practitioner names as well as Patient.
        # C2-19 continuation: Kana SYL entry now
        # emitted when roster generation populated `name_phonetic`.
        # names.yaml carries kana column for every kanji entry so JP
        # rosters always fill this field.
        names_list: list[dict[str, Any]] = []
        if is_jp(country):
            names_list.append(
                {
                    **name_obj,
                    "use": "official",
                    "extension": [
                        {
                            "url": "http://hl7.org/fhir/StructureDefinition/iso21090-EN-representation",
                            "valueCode": "IDE",
                        }
                    ],
                }
            )
            phonetic = staff.get("name_phonetic", "")
            if phonetic:
                p_parts = phonetic.split(" ", 1)
                if len(p_parts) == 2:
                    p_family, p_given = p_parts[0], p_parts[1]
                else:
                    p_family, p_given = phonetic, ""
                names_list.append(
                    {
                        "use": "official",
                        "family": p_family,
                        "given": [p_given] if p_given else [],
                        "extension": [
                            {
                                "url": "http://hl7.org/fhir/StructureDefinition/iso21090-EN-representation",
                                "valueCode": "SYL",
                            }
                        ],
                    }
                )
        else:
            names_list.append(name_obj)
        resource["name"] = names_list

        # Gender
        sex = staff.get("sex", "")
        if sex == "M":
            resource["gender"] = "male"
        elif sex == "F":
            resource["gender"] = "female"

        # Telecom
        telecoms = []
        if staff.get("phone"):
            telecoms.append({"system": "phone", "value": staff["phone"], "use": "work"})
        if staff.get("email"):
            telecoms.append({"system": "email", "value": staff["email"], "use": "work"})
        if telecoms:
            resource["telecom"] = telecoms

        # Qualification
        # feedback FB-F7: HL7 v2-0360 CodeSystem に含まれない code(RD 等)は
        # validator に "code 未定義" と reject される。v2-0360 に含まれる code
        # (MD/DO/RN/PA 等)は system 付き coding、それ以外は text-only fallback。
        # v2-0360 定義済 code(HL7 official table 0360)
        # #299:PT/OT/MSW/ST は v2-0360 に存在しない code(HAPI
        # は tx-server-build/CodeSystem-v2-0360.json 権威 61 concepts のみ受理)。
        # 従来 fabricated として登録していたため v5 で 10 件 unknown-code error。
        # v2-0360 未定義 code(PT/OT/ST/MSW/RD 等)は text-only fallback へ。
        _V2_0360_VALID_CODES = {
            "MD",
            "DO",
            "RN",
            "LPN",
            "PA",
            "NP",
            "CNM",  # 医師系 + 看護系
            "BA",
            "BS",
            "MBA",
            "MS",
            "MA",
            "PHD",  # 学位系
        }
        # Issue #962: JP-CLINS MHLW-coded qualification (with physician
        # specialty board as qualification[1]). When the JP yaml is
        # available AND covers this role, the coded emit replaces the
        # v0.5.0 text-only fallback for allied-health roles (PH/PT/OT/ST/
        # RD/MSW/TECH) and lifts physicians from bare `MD` to `MD +
        # 循環器専門医`. Falls through to the pre-#962 v2-0360 / text-only
        # path when the yaml is absent or the role is unmapped so we
        # never regress existing qualification coverage.
        if is_jp(country):
            jp_quals = _build_jp_qualifications(staff, staff_id)
            if jp_quals:
                resource["qualification"] = jp_quals
                qual = None
            else:
                qual = _ROLE_PREFIX_MAP_JA.get(role)
        else:
            qual = _ROLE_PREFIX_MAP.get(role)
        if qual:
            _qual_code = qual["qual_code"]
            _qual_display = qual["qual_display"]
            if _qual_code in _V2_0360_VALID_CODES:
                qualification: dict[str, Any] = {
                    "code": {
                        "coding": [
                            {
                                "system": get_system_uri("hl7-v2-0360"),
                                "code": _qual_code,
                                "display": _qual_display,
                            }
                        ],
                    },
                }
            else:
                # v2-0360 未定義 code(RD 管理栄養士 等)は text-only
                qualification = {"code": {"text": _qual_display}}
            qual_year = staff.get("qualification_year")
            if qual_year:
                qualification["period"] = {"start": f"{qual_year}-01-01"}
            resource["qualification"] = [qualification]

    return resource


def _build_practitioner_role(
    staff_id: str,
    roster_map: dict[str, dict] | None = None,
    country: str = "US",
) -> dict | None:
    """Build FHIR PractitionerRole resource (specialty + department)."""
    staff = (roster_map or {}).get(staff_id)
    if not staff:
        return None

    role = staff.get("role", "")
    department = staff.get("department", "")
    specialty = staff.get("specialty", "") or department

    role_code_map = {
        "physician": "doctor",
        "radiologist": "doctor",
        "nurse": "nurse",
        "lab_technician": "ict",
        "pharmacist": "pharmacist",
    }
    role_code = role_code_map.get(role, "")

    # C5-25 (Chain 3): text-only PractitionerRole.code for allied-health
    # roles not covered by HL7's practitioner-role CodeSystem. FHIR R4
    # CodeableConcept accepts text-only (no fabricated code). SNOMED CT
    # occupation codes exist for these roles but registering them requires
    # per-code SNOMED verification (deferred to a separate authoritative
    # code chain — mirrors C2-15 policy).
    _text_only_role: dict[str, tuple[str, str]] = {
        "physical_therapist": ("Physical therapist", "理学療法士"),
        "occupational_therapist": ("Occupational therapist", "作業療法士"),
        "speech_therapist": ("Speech-language therapist", "言語聴覚士"),
        "medical_social_worker": ("Medical social worker", "医療ソーシャルワーカー"),
        "dietitian": ("Registered dietitian", "管理栄養士"),
    }
    _text_only_display = _text_only_role.get(role)

    spec_info = _SPECIALTY_SNOMED.get(specialty) or _SPECIALTY_SNOMED.get(department)

    resource: dict[str, Any] = {
        "resourceType": "PractitionerRole",
        "id": f"role-{staff_id}",
        # chain #2: JP Core PractitionerRole profile.
        **(
            {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_PractitionerRole"]}}
            if is_jp(country)
            else {}
        ),
        "active": True,
        "practitioner": {"reference": f"Practitioner/{staff_id}"},
    }

    # Organization (department) reference
    # CY8-08 fix:department 未指定 or 支援部門は
    # hospital-main を fallback として emit(83.8% → 100%)。
    if department and department not in ("laboratory", "radiology", "pharmacy"):
        resource["organization"] = {
            "reference": f"Organization/dept-{department.replace('_', '-')}",
        }
    else:
        resource["organization"] = {
            "reference": "Organization/hospital-main",
        }

    # Location reference (for nurses assigned to a ward)
    # CY8-07 fix:ward 未指定 staff は hospital-main
    # Location を fallback として emit(46.8% → 100%)。
    ward = staff.get("ward", "")
    if ward:
        resource["location"] = [
            {
                "reference": f"Location/loc-ward-{ward}",
            }
        ]
    else:
        resource["location"] = [
            {
                "reference": "Location/loc-hospital-main",
            }
        ]

    # CY8-06 fix:PractitionerRole.period.start を
    # データ収集開始起点(2024-01-01)を default に emit。従来 0/111 → 100%。
    # 実運用では雇用開始日を使うが、CIF に staff の hire_date は無いため
    # simulator の period 全体を staff の active period として近似。
    resource["period"] = {
        "start": staff.get("period_start", "2024-01-01"),
    }

    if role_code:
        # C2-07: resolve display via codes/data/
        # hl7-practitioner-role.yaml — was raw code with no display.
        resource["code"] = [
            {
                "coding": [
                    _coding_with_display(
                        "hl7-practitioner-role",
                        role_code,
                        resolve_lang(country),
                    )
                ],
            }
        ]
    elif _text_only_display:
        _lang = resolve_lang(country)
        _disp = _text_only_display[1] if _lang == "ja" else _text_only_display[0]
        resource["code"] = [{"text": _disp}]

    if spec_info:
        # C5-05: resolve specialty display through
        # snomed-ct.yaml so JP output uses 内科/循環器内科 etc. instead of
        # the English fallback baked into _SPECIALTY_SNOMED entries.
        _lang = resolve_lang(country)
        _snomed_code = spec_info["code"]
        _spec_display = code_lookup("snomed-ct", _snomed_code, _lang) or spec_info["display"]
        resource["specialty"] = [
            {
                "coding": [
                    {
                        "system": get_system_uri("snomed-ct"),
                        "code": _snomed_code,
                        "display": _spec_display,
                    }
                ],
                "text": _spec_display,
            }
        ]
    else:
        # CY8-05 fix:allied-health / nurse など
        # SNOMED specialty 未マッピングの staff にも text-only specialty
        # を emit(42.3% → 100%)。role table から derive、無ければ role 名。
        _lang = resolve_lang(country)
        _spec_text = None
        if _text_only_display:
            _spec_text = _text_only_display[1] if _lang == "ja" else _text_only_display[0]
        elif role:
            _spec_text = role.replace("_", " ").title()
        if _spec_text:
            resource["specialty"] = [{"text": _spec_text}]

    return resource
