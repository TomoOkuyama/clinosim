"""Pure FHIR reference-data dictionaries (code/SNOMED/region lookup tables).

FA-1 Phase 2: module-level data literals extracted verbatim from
fhir_r4_adapter.py. These are pure data (no functions, no dependencies on
other adapter symbols) and are re-exported by fhir_r4_adapter as a facade.
"""

from __future__ import annotations

_ALLERGEN_RXNORM: dict[str, str] = {
    # RxNorm ingredient codes for common drug allergens
    "Penicillin": "7980",
    "Sulfonamide": "10180",
    "NSAIDs": "5640",  # ibuprofen as representative
    "Cephalosporin": "2173",
    "Aspirin": "1191",
}


_SEVERITY_SNOMED: dict[str, dict[str, str]] = {
    "mild": {"code": "255604002", "display": "Mild"},
    "moderate": {"code": "6736007", "display": "Moderate"},
    "severe": {"code": "24484000", "display": "Severe"},
}

# session 53 iris4h-ai feedback F-4: JP Core `JP_ConditionSeverity_VS` は
# JP_ConditionSeverity_CS の 4 code(MI/MO/SE/UK)のみを許容。SNOMED は
# ValueSet 外 = ~5k info。JP output では JP CS を primary、SNOMED を
# secondary(国際互換性のため保持)として emit する。
#
# URI 出典:iris4h-ai/tx-server-build/.../CodeSystem-jp-conditionseverity-cs.json
# (JP CS の display は `中度`、`中等度` ではないので注意)
_JP_CONDITION_SEVERITY_CS = "http://jpfhir.jp/fhir/core/CodeSystem/JP_ConditionSeverity_CS"
_SEVERITY_JP: dict[str, dict[str, str]] = {
    "mild": {"code": "MI", "display": "軽度"},
    "moderate": {"code": "MO", "display": "中度"},
    "severe": {"code": "SE", "display": "重度"},
}
# NOTE: 過去に定義していた `_JP_OBSERVATION_REFERENCE_RANGE_SOURCE_URL`
# (`.../StructureDefinition/JP_Observation_ReferenceRangeSource`)は削除。
# 2026-07-17 fhir-jp-validator report で以下 2 点が判明したため:
# (1) URL は JP Core 1.2.0 / JP-CLINS 1.12.0 / jpfhir-terminology 2.2606.0
#     の StructureDefinition カタログに存在せず、HAPI が "extension is
#     unknown" として reject する。
# (2) `JP_Observation_LabResult_eCS` は `Observation.referenceRange.
#     extension max=0` を定めており、たとえ spec-valid URL でも emit 不可。
# → clinosim は referenceRangeSource extension を emit しない。
# 該当 issue: #202、削除の PR は fix/observation-reference-range-strip-extension。


_PREFECTURE_CODE: dict[str, str] = {
    "北海道": "01",
    "青森県": "02",
    "岩手県": "03",
    "宮城県": "04",
    "秋田県": "05",
    "山形県": "06",
    "福島県": "07",
    "茨城県": "08",
    "栃木県": "09",
    "群馬県": "10",
    "埼玉県": "11",
    "千葉県": "12",
    "東京都": "13",
    "神奈川県": "14",
    "新潟県": "15",
    "富山県": "16",
    "石川県": "17",
    "福井県": "18",
    "山梨県": "19",
    "長野県": "20",
    "岐阜県": "21",
    "静岡県": "22",
    "愛知県": "23",
    "三重県": "24",
    "滋賀県": "25",
    "京都府": "26",
    "大阪府": "27",
    "兵庫県": "28",
    "奈良県": "29",
    "和歌山県": "30",
    "鳥取県": "31",
    "島根県": "32",
    "岡山県": "33",
    "広島県": "34",
    "山口県": "35",
    "徳島県": "36",
    "香川県": "37",
    "愛媛県": "38",
    "高知県": "39",
    "福岡県": "40",
    "佐賀県": "41",
    "長崎県": "42",
    "熊本県": "43",
    "大分県": "44",
    "宮崎県": "45",
    "鹿児島県": "46",
    "沖縄県": "47",
}


# Encounter type -> SNOMED code. Display text (en/ja) lives in
# codes/data/snomed-ct.yaml, resolved via code_lookup — not duplicated here
# (session 37 display-dict migration; this mapping itself, enum -> code, is
# not display text and stays in Python).
_ENCOUNTER_TYPE_SNOMED_CODE: dict[str, str] = {
    "inpatient": "32485007",
    "emergency": "50849002",
    "outpatient": "270427003",
    "icu": "183452005",
}


_ROUTE_SNOMED: dict[str, dict[str, str]] = {
    "PO": {"code": "26643006", "display": "Oral"},
    "IV": {"code": "47625008", "display": "Intravenous"},
    "SC": {"code": "34206005", "display": "Subcutaneous"},
    "IM": {"code": "78421000", "display": "Intramuscular"},
    "SL": {"code": "37161004", "display": "Sublingual"},
    "PR": {"code": "37161004", "display": "Per rectum"},
    "INHALED": {"code": "447694001", "display": "Inhalation"},
    "TOPICAL": {"code": "6064005", "display": "Topical"},
    "NEBULIZED": {"code": "447694001", "display": "Inhalation"},
}


_ROLE_PREFIX_MAP: dict[str, dict[str, str]] = {
    "physician": {"qual_code": "MD", "qual_display": "Doctor of Medicine"},
    "nurse": {"qual_code": "RN", "qual_display": "Registered Nurse"},
    "lab_technician": {"qual_code": "MT", "qual_display": "Medical Technologist"},
    "radiologist": {"qual_code": "MD", "qual_display": "Doctor of Medicine"},
    "pharmacist": {"qual_code": "PharmD", "qual_display": "Doctor of Pharmacy"},
    # CY6-02 (Chain-6): allied-health qualifications for the roster
    # expansion added in session 44 C5-25. Codes follow HL7 v2-0360
    # convention where possible (PT/OT/ST are widely-used qual codes;
    # MSW / RD are text-only since v2-0360 does not enumerate them —
    # FHIR R4 CodeableConcept allows text-only representations).
    "physical_therapist": {"qual_code": "PT", "qual_display": "Physical Therapist"},
    "occupational_therapist": {"qual_code": "OT", "qual_display": "Occupational Therapist"},
    "speech_therapist": {"qual_code": "ST", "qual_display": "Speech-Language Therapist"},
    "medical_social_worker": {"qual_code": "MSW", "qual_display": "Medical Social Worker"},
    "dietitian": {"qual_code": "RD", "qual_display": "Registered Dietitian"},
}


_SPECIALTY_SNOMED: dict[str, dict[str, str]] = {
    "general": {"code": "419192003", "display": "Internal Medicine"},
    "cardiology": {"code": "394579002", "display": "Cardiology"},
    "pulmonology": {"code": "418112009", "display": "Pulmonary medicine"},
    "gastro": {"code": "394584008", "display": "Gastroenterology"},
    "nephro": {"code": "394589003", "display": "Nephrology"},
    "endo": {"code": "394583003", "display": "Endocrinology"},
    "internal_medicine": {"code": "419192003", "display": "Internal Medicine"},
    "radiology": {"code": "394914008", "display": "Radiology"},
    "laboratory": {"code": "722414000", "display": "Laboratory medicine"},
    "pharmacy": {"code": "405623001", "display": "Pharmacy"},
}
