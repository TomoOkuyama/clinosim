"""JP/EN localization layer for the FHIR R4 adapter (FA-1 Phase 1).

Houses lazy-loaded localization tables, drug/department/procedure display
helpers, and the shared JP display dictionaries used by
``fhir_r4_adapter.py``. The adapter re-exports every symbol defined here so
existing imports keep working.

This module must NOT import ``fhir_r4_adapter`` (no circular import).
"""

from __future__ import annotations

import re

from clinosim.codes import lookup as code_lookup
from clinosim.locale.loader import load_department_display as _load_department_display
from clinosim.locale.loader import load_drug_names_ja as _load_drug_names_ja
from clinosim.locale.loader import load_med_terms_ja as _load_med_terms_ja
from clinosim.modules._shared import is_jp, is_us, resolve_lang

# Session 52: expose the private-name loader aliases so mypy's strict export
# check passes at fhir_r4_adapter.py's import site.
__all__ = [
    "_load_department_display",
    "_load_drug_names_ja",
    "_load_med_terms_ja",
    "code_lookup",
    "is_jp",
    "is_us",
    "resolve_lang",
]

# ``_load_med_terms_ja`` / ``_load_drug_names_ja`` / ``_load_department_display``
# are thin re-export aliases of the canonical cached locale loaders. They are
# re-exported by ``fhir_r4_adapter.py`` (public import path) and exercised by
# tests via ``.cache_clear()`` / ``.cache_info()`` — sharing the underlying
# lru_cache object keeps those APIs working.


def _localize_dosage_terms(text: str) -> str:
    """Translate common medical abbreviations and dosage terms to Japanese.

    Word-level replacements with case-insensitive matching for common terms.
    """
    tables = _load_med_terms_ja()
    # Category prefixes (apply first, longest-match-wins, case-insensitive)
    # These often appear as "Category: ..." or "Category_word ..."
    for cat, ja in sorted(tables["categories"].items(), key=lambda x: -len(x[0])):
        # Match as prefix word, case-insensitive, followed by : or space or _
        pattern = r"(?i)\b" + re.escape(cat) + r"\b"
        text = re.sub(pattern, ja, text)
    # Dose/route/frequency terms (word-boundary, case-sensitive for uppercase abbrevs,
    # case-insensitive for lowercase words)
    for term, ja in sorted(tables["terms"].items(), key=lambda x: -len(x[0])):
        if term.isupper():
            # Case-sensitive for uppercase abbrevs (PRN, PO, IV)
            pattern = r"\b" + re.escape(term) + r"\b"
            text = re.sub(pattern, ja, text)
        else:
            # Case-insensitive for lowercase words
            pattern = r"(?i)\b" + re.escape(term) + r"\b"
            text = re.sub(pattern, ja, text)
    return text


# Rate-adjustment suffix pattern for continuous-infusion medications (session 45).
# Disease YAMLs (e.g. pulmonary_embolism.yaml Day-2 heparin drip) may emit
# `dose: "increase_rate_by_20%"` which upstream concatenates to display_name as
# `"Unfractionated_Heparin increase_rate_by_20%"`. That protocol notation belongs
# in dosageInstruction, not in medicationCodeableConcept.text — otherwise the
# code_mapping token loop fails to hit the base drug name and the coding is
# emitted uncoded.
_RATE_ADJUSTMENT_SUFFIX_RE = re.compile(
    r"\s*[_ ](increase|decrease)[_ ]rate[_ ]by[_ ](\d+)%\s*$",
    re.IGNORECASE,
)


def _split_rate_adjustment_suffix(drug_name: str) -> tuple[str, str]:
    """Split a drug display name into (base_drug_name, rate_adjustment_note).

    Returns ("", "") for empty input; returns (drug_name, "") when no
    adjustment suffix is present.

    Examples::

        >>> _split_rate_adjustment_suffix("Unfractionated_Heparin increase_rate_by_20%")
        ('Unfractionated_Heparin', 'increase rate by 20%')
        >>> _split_rate_adjustment_suffix("Norepinephrine decrease rate by 15%")
        ('Norepinephrine', 'decrease rate by 15%')
        >>> _split_rate_adjustment_suffix("Acetaminophen 500mg PO")
        ('Acetaminophen 500mg PO', '')
    """
    if not drug_name:
        return "", ""
    m = _RATE_ADJUSTMENT_SUFFIX_RE.search(drug_name)
    if not m:
        return drug_name, ""
    base = drug_name[: m.start()].rstrip(" _")
    direction = m.group(1).lower()
    percent = m.group(2)
    return base, f"{direction} rate by {percent}%"


def _localize_rate_adjustment(note_en: str, country: str) -> str:
    """Localize an English rate-adjustment note produced by ``_split_rate_adjustment_suffix``.

    Returns the input unchanged for US or empty notes.
    """
    if not note_en or is_us(country):
        return note_en
    m = re.match(r"^(increase|decrease) rate by (\d+)%\s*$", note_en, re.IGNORECASE)
    if not m:
        return note_en
    direction_ja = "増量" if m.group(1).lower() == "increase" else "減量"
    return f"注入速度を{m.group(2)}%{direction_ja}"


def _localize_drug_name(drug_name: str, country: str) -> str:
    """Resolve drug name to Japanese when country=JP.

    Matches drug names against the dictionary, handling:
    - Exact match (case-insensitive, underscore→space normalized)
    - Category prefix: "category: Drug ..." → "<ja> ..."
    - Any drug name substring found anywhere in the text (longest match wins)
    - Dosage/route/frequency terms translated at end
    """
    if is_us(country) or not drug_name:
        return drug_name
    ja_dict = _load_drug_names_ja()
    # Normalize underscores to spaces for matching
    normalized = drug_name.replace("_", " ")
    # Try exact match on normalized (case-insensitive)
    ja = ja_dict.get(normalized.lower())
    if ja:
        return _localize_dosage_terms(ja)
    # Try exact match on cleaned (prefix stripped) version
    cleaned = normalized
    if ":" in cleaned:
        cleaned = cleaned.split(":", 1)[1].strip()
    ja = ja_dict.get(cleaned.lower())
    if ja:
        return _localize_dosage_terms(ja)
    # Replace ALL known drug name occurrences (longest-first to avoid partial matches)
    # Use case-insensitive regex replacement
    result = normalized
    changed = False
    for en_key in sorted(ja_dict.keys(), key=lambda k: -len(k)):
        ja_val = ja_dict[en_key]
        pattern = re.compile(r"(?i)\b" + re.escape(en_key) + r"\b")
        new_result, n = pattern.subn(ja_val, result)
        if n > 0:
            result = new_result
            changed = True
    # Always translate dosage terms
    return (
        _localize_dosage_terms(result).strip()
        if changed or result != drug_name
        else _localize_dosage_terms(drug_name).strip()
    )  # noqa: E501


def _dept_display(dept: str, country: str) -> str:
    """Resolve a department key to its display name for the target country.

    Falls back to a title-cased key when the department is not in the table.
    """
    lang = resolve_lang(country)
    entry = _load_department_display().get(dept, {})
    return entry.get(lang) or dept.replace("_", " ").title()


_OCCUPATION_DISPLAY_JA: dict[str, str] = {
    "manufacturing": "製造業",
    "construction": "建設業",
    "agriculture": "農林水産業",
    "healthcare": "医療・福祉",
    "service": "サービス・小売",
    "office": "事務・専門職",
    "transportation": "運輸業",
    "education": "教育",
    "homemaker": "主婦/主夫",
    "student": "学生",
    "retired": "退職",
    "unemployed": "無職",
    "other": "その他",
}

_OCCUPATION_DISPLAY_EN: dict[str, str] = {
    "manufacturing": "Manufacturing worker",
    "construction": "Construction worker",
    "agriculture": "Agricultural worker",
    "healthcare": "Healthcare worker",
    "service": "Service/retail worker",
    "office": "Office/professional worker",
    "transportation": "Transportation worker",
    "education": "Education worker",
    "homemaker": "Homemaker",
    "student": "Student",
    "retired": "Retired",
    "unemployed": "Unemployed",
    "other": "Other occupation",
}


# --- Shared display dictionaries for JP localization ---

_CLASS_DISPLAY_JA: dict[str, str] = {
    "AMB": "外来",
    "ambulatory": "外来",
    "IMP": "入院",
    "inpatient encounter": "入院",
    "EMER": "救急",
    "emergency": "救急",
    "HH": "訪問看護",
    "home health": "訪問看護",
    "FLD": "現地訪問",
    "field": "現地訪問",
    # C5-22 (session 43): classHistory transition labels.
    "inpatient ward": "一般病棟",
    "ICU": "集中治療室",
    "ACUTE": "集中治療室",
}

_CATEGORY_DISPLAY_JA: dict[str, str] = {
    "laboratory": "検体検査",
    "Laboratory": "検体検査",
    "vital-signs": "バイタルサイン",
    "Vital Signs": "バイタルサイン",
    "social-history": "社会歴",
    "Social History": "社会歴",
    "encounter-diagnosis": "エンカウンター診断",
    "Encounter Diagnosis": "エンカウンター診断",
    "problem-list-item": "問題リスト",
    "Problem List Item": "問題リスト",
    "imaging": "画像検査",
    "Imaging": "画像検査",
    "procedure": "処置",
    "Procedure": "処置",
}

_SEVERITY_DISPLAY_JA: dict[str, str] = {
    "Mild": "軽度",
    "mild": "軽度",
    "24484000": "軽度",
    "Moderate": "中等度",
    "moderate": "中等度",
    "6736007": "中等度",
    "Severe": "重度",
    "severe": "重度",
    "24484000|severe": "重度",
    "255604002": "重度",
}

_INTERPRETATION_DISPLAY_JA: dict[str, str] = {
    "N": "正常",
    "Normal": "正常",
    "H": "高値",
    "High": "高値",
    "L": "低値",
    "Low": "低値",
    "HH": "パニック高値",
    "Critical high": "パニック高値",
    "LL": "パニック低値",
    "Critical low": "パニック低値",
    "A": "異常",
    "Abnormal": "異常",
    "AA": "パニック異常",
    "Critical abnormal": "パニック異常",
    "HU": "測定上限超",
    "LU": "測定下限未満",
    "POS": "陽性",
    "NEG": "陰性",
    # R/S/I (susceptibility) intentionally NOT here — this dict's only two
    # callers (_fhir_observations.py's lab-flag interpretation and
    # _localize_interp) never produce those codes; susceptibility display now
    # lives solely in codes/data/hl7-observation-interpretation.yaml, consumed
    # by _fhir_microbiology.py via code_lookup (2026-07-05 dedup).
}

_RELATIONSHIP_DISPLAY_JA: dict[str, str] = {
    "spouse": "配偶者",
    "child": "子",
    "parent": "親",
    "sibling": "同胞",
    "partner": "パートナー",
    "grandchild": "孫",
    "grandparent": "祖父母",
    "friend": "友人",
    "guardian": "後見人",
}

_ORG_TYPE_DISPLAY_JA: dict[str, str] = {
    "Hospital Department": "診療科",
    "Healthcare Provider": "医療機関",
    "prov": "医療機関",
    "dept": "診療科",
}

_LOCATION_TYPE_DISPLAY_JA: dict[str, str] = {
    "Operating Room": "手術室",
    "Emergency Room": "救急外来",
    "Outpatient Clinic": "外来",
    "Ward": "病棟",
    "Bed": "病床",
    "Inpatient Ward": "入院病棟",
}

_LOCATION_NAME_JA: dict[str, str] = {
    "Emergency Room": "救急外来",
    "Outpatient Clinic": "外来",
}

# C5-02 (session 43 cycle 5): HL7 v3-ParticipationType displays used by
# Encounter.participant.type.coding.display. English default per HL7 leaks
# to JP output; localize here.
_PARTICIPATION_TYPE_DISPLAY_JA: dict[str, str] = {
    "ATND": "担当医",
    "attender": "担当医",
    "ADM": "入院担当医",
    "admitter": "入院担当医",
    "DIS": "退院担当医",
    "discharger": "退院担当医",
    "CON": "コンサルタント",
    "consultant": "コンサルタント",
    "REF": "紹介元",
    "referrer": "紹介元",
    "PART": "参加者",
    "Participation": "参加者",
}

# C5-03 (session 43 cycle 5): HL7 v3-ActPriority displays used by
# Encounter.priority.coding.display.
_ACT_PRIORITY_DISPLAY_JA: dict[str, str] = {
    "R": "通常",
    "routine": "通常",
    "EM": "救急",
    "emergency": "救急",
    "S": "予定",
    "stat": "至急",
    "UR": "至急",
    "urgent": "至急",
    "A": "至急要求",
    "ASAP": "至急要求",
    "CS": "予定手術",
    "callback for scheduling": "予定手術",
    "CR": "コールバック",
    "callback results": "コールバック",
    "EL": "選択的",
    "elective": "選択的",
    "P": "予防",
    "preop": "予防",
    "T": "予定",
    "timing critical": "予定",
    "PRN": "頓用",
    "as needed": "頓用",
}

# C5-04 (session 43 cycle 5): HL7 diagnosis-role displays used by
# Encounter.diagnosis.use.coding.display.
_DIAGNOSIS_ROLE_DISPLAY_JA: dict[str, str] = {
    "AD": "入院時診断",
    "Admission diagnosis": "入院時診断",
    "DD": "退院時診断",
    "Discharge diagnosis": "退院時診断",
    "CC": "主訴",
    "Chief complaint": "主訴",
    "CM": "併存疾患",
    "Comorbidity diagnosis": "併存疾患",
    "pre-op": "術前診断",
    "pre-op diagnosis": "術前診断",
    "post-op": "術後診断",
    "post-op diagnosis": "術後診断",
    "billing": "請求診断",
    "Billing": "請求診断",
}


# Procedure names (from disease YAML procedure.type) — EN→JA
def _procedure_display(code: str, lang: str, fallback: str = "") -> str:
    """Look up procedure display in k-codes.yaml / cpt.yaml.

    Tries k-codes first (JP codes) then cpt (US codes). Falls back to the
    provided `fallback` string if neither has an entry.
    """
    if not code:
        return fallback
    for system_key in ("k-codes", "cpt"):
        disp = code_lookup(system_key, code, lang)
        if disp and disp != code:
            return disp
    return fallback


def _localize_display(value: str, country: str, dictionary: dict[str, str]) -> str:
    """Look up JP display for an English value when country=JP.
    Returns original value if no mapping exists."""
    if not is_jp(country) or not value:
        return value
    return dictionary.get(value, value)


def _localize_interp(coded: dict[str, str], country: str) -> dict[str, str]:
    """Localize interpretation display dict in place (returns new dict)."""
    if not is_jp(country):
        return coded
    d = dict(coded)
    d["display"] = _INTERPRETATION_DISPLAY_JA.get(d.get("code", ""), d.get("display", ""))
    return d


_ROUTE_JA: dict[str, str] = {
    "PO": "経口",
    "IV": "静注",
    "SC": "皮下注",
    "IM": "筋注",
    "SL": "舌下",
    "PR": "直腸",
    "INH": "吸入",
    "TOPICAL": "外用",
    "NG": "経鼻",
    "INHALED": "吸入",
}
_FREQ_JA: dict[str, str] = {
    "DAILY": "1日1回",
    "BID": "1日2回",
    "TID": "1日3回",
    "QID": "1日4回",
    "Q4H": "4時間毎",
    "Q6H": "6時間毎",
    "Q8H": "8時間毎",
    "Q12H": "12時間毎",
    "PRN": "必要時",
    "STAT": "緊急",
    "ONCE": "1回",
    "1x/day": "1日1回",
    "2x/day": "1日2回",
    "3x/day": "1日3回",
    "4x/day": "1日4回",
}

# FHIR fixed-label JA dictionary (FP-UNIFY-3, session 40): centralizes short
# free-text FHIR field labels that used to be scattered as inline conditionals
# ("放射線科" if lang == "ja" else "Radiology"). Add a new EN → JA row here rather
# than reintroducing an inline conditional. Consumed via ``localize_fixed_label``.
_FIXED_LABEL_JA: dict[str, str] = {
    "Radiology": "放射線科",
    "No growth": "発育なし",
    "Imaging procedure": "画像診断",
    "Laboratory procedure": "臨床検査",
}


def localize_fixed_label(en_label: str, country: str) -> str:
    """Return the JA label for JP, the EN label otherwise.

    Small, focused helper for the FHIR fixed-label dictionary above. Fails
    loudly (silently returning the EN label unchanged) is intentional for
    US / non-JP paths — the same behavior every inline conditional used.
    New callers must add the EN key to ``_FIXED_LABEL_JA`` before use to
    make the JA branch fire.
    """
    from clinosim.modules._shared import is_jp

    if is_jp(country):
        return _FIXED_LABEL_JA.get(en_label, en_label)
    return en_label


_ROLE_PREFIX_MAP_JA: dict[str, dict[str, str]] = {
    "physician": {"qual_code": "MD", "qual_display": "医師", "prefix": ""},
    "nurse": {"qual_code": "RN", "qual_display": "看護師", "prefix": ""},
    "lab_technician": {"qual_code": "MT", "qual_display": "臨床検査技師", "prefix": ""},
    "radiologist": {"qual_code": "MD", "qual_display": "放射線科医", "prefix": ""},
    "pharmacist": {"qual_code": "PharmD", "qual_display": "薬剤師", "prefix": ""},
    # CY6-02 (Chain-6): allied-health qualifications (session 44 C5-25 roster).
    "physical_therapist": {"qual_code": "PT", "qual_display": "理学療法士", "prefix": ""},
    "occupational_therapist": {"qual_code": "OT", "qual_display": "作業療法士", "prefix": ""},
    "speech_therapist": {"qual_code": "ST", "qual_display": "言語聴覚士", "prefix": ""},
    "medical_social_worker": {"qual_code": "MSW", "qual_display": "医療ソーシャルワーカー", "prefix": ""},
    "dietitian": {"qual_code": "RD", "qual_display": "管理栄養士", "prefix": ""},
}
