"""Code system loader — unified API for clinical code lookups.

Usage:
    from clinosim.codes import lookup, get_system_uri

    # Get display text in English
    display = lookup("icd-10-cm", "N10", lang="en")
    # → "Acute tubulo-interstitial nephritis"

    # Get display text in Japanese
    display = lookup("icd-10-cm", "N10", lang="ja")
    # → "急性腎盂腎炎"

    # Get FHIR system URI
    uri = get_system_uri("icd-10-cm")
    # → "http://hl7.org/fhir/sid/icd-10-cm"
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

_DATA_DIR = Path(__file__).parent / "data"


@dataclass
class CodeSystem:
    """A clinical code system with metadata and entries."""

    key: str  # short key (e.g., "icd-10-cm")
    name: str  # human-readable name
    uri: str  # FHIR system URI
    version: str  # version / year
    codes: dict[str, dict[str, str]]  # code → {en, ja, ...}


# Issue #350: system keys that share underlying code data with
# another system but carry a distinct canonical URI. Concrete case:
# `icd-10-mhlw` uses the same 3-4 character ICD-10 codes as `icd-10` (WHO)
# but its canonical URI is the JP Core / MHLW 2013 registry
# `http://jpfhir.jp/fhir/core/mhlw/CodeSystem/ICD10-2013-full`. The alias
# avoids duplicating the codes/data yaml (thousands of codes) while giving
# the JP path its required binding URI.
#
# The aliased system's URI is drawn from `_BUILTIN_URIS[system_key]`
# (below), NOT from the underlying yaml's `metadata.uri` — that way the
# alias is a genuine namespace refinement, not a value clash.
_SYSTEM_DATA_ALIASES: dict[str, str] = {
    "icd-10-mhlw": "icd-10",
}


# Issue #415: sibling systems consulted as read-only lookup
# fallbacks. When ``lookup(primary, code, lang)`` finds no entry in
# ``primary``, ``lookup`` retries each sibling in order until one hits.
# Concrete case: ``system_key_for("drug", "JP") = "yj"`` and callers pass
# both YJ12 (12-char) codes AND HOT7 (7-digit MEDIS) codes with the same
# ``"yj"`` key. Splitting HOT7 into ``codes/data/hot7.yaml`` would break
# HOT7 display lookup at the ``"yj"`` call sites; declaring ``"hot7"``
# as a sibling of ``"yj"`` restores it without touching those consumers.
#
# The FHIR emit path (``_fhir_medications._resolve_jp_drug_system_uri``)
# already dispatches to the correct canonical URI per code format, so
# only ``lookup`` (display resolution) needs this fallback — the URI
# side is unaffected.
#
# Each sibling still lives in its own YAML with its own canonical URI:
# this is a display-only fallback, NOT a data merge. ``get_system_uri
# ("hot7")`` still returns the MEDIS-HOT7 URI, ``get_system_uri("yj")``
# still returns the capstandard YJ URI.
_SYSTEM_LOOKUP_SIBLINGS: dict[str, tuple[str, ...]] = {
    "yj": ("hot7",),
    # Phase 1d-74 (2026-09-25): SDOH-derived chronic Conditions are
    # authored in ICD-10-CM (F17.210 nicotine dependence, E66.3
    # overweight, F10.20 alcohol dependence, …). When those codes flow
    # into a JP narrative context — which looks up display against
    # ``icd-10`` (WHO) / ``icd-10-mhlw`` — the ICD-10-CM leaf misses
    # (WHO ICD-10 has no ``.210`` extension) and the narrative falls
    # back to raw code (「慢性疾患（F17.210）」, 「E66.3（E66.3）」).
    #
    # Sibling to icd-10-cm as a display-only fallback: preserves the
    # JP-specific detailed display already authored in the ICD-10-CM
    # yaml (「ニコチン依存症（紙巻きたばこ、合併症なし）」,「過体重」)
    # without fabricating WHO ICD-10 entries for codes that don't
    # exist in WHO. The reverse fallback (``icd-10-cm`` → ``icd-10``)
    # covers the opposite gap: WHO-only codes that a US narrative
    # might encounter.
    "icd-10": ("icd-10-cm",),
    "icd-10-mhlw": ("icd-10-cm",),
    "icd-10-cm": ("icd-10",),
}


# Issue #358: system keys whose canonical CodeSystem publishes only a
# Japanese ``display`` for each concept — emitting an English display against
# this system URI produces a display-mismatch error at conformance time
# (validator compares against the authoritative CS). Consumers building
# multilingual CodeableConcepts (e.g. ``build_diagnosis_codeable_concept``)
# must skip the English secondary coding when the primary system is here.
#
# Concrete case: MHLW ICD-10 2013 registry
# (``http://jpfhir.jp/fhir/core/mhlw/CodeSystem/ICD10-2013-full``) is a
# Japanese-only registry — its concepts have no English display, so a coding
# with an English ``display`` field can never match. v19 validation
# (2026-07-22) surfaced 189 such errors on FamilyMemberHistory.condition.
#
# Membership is opt-in: adding a system to the set silently drops English
# secondary coding for it in every diagnosis-CodeableConcept build site.
# Keep this a very small, deliberately-audited allowlist.
_JAPANESE_ONLY_DISPLAY_SYSTEMS: frozenset[str] = frozenset(
    {
        "icd-10-mhlw",
    }
)


# CodeSystems that publish English displays only (Issue #2276: the one
# registry, moved from post_process/strip.py). On JP output their
# ``coding.display`` stays English canonical and the Japanese label goes in
# ``CodeableConcept.text`` (the dual-slot pattern); a Japanese display in the
# coding fails validation as "Wrong Display Name". JP-specific CodeSystems
# (JP Core / JP-CLINS / MEDIS HOT / YJ / clinosim custom) are not listed.
ENGLISH_ONLY_SYSTEM_PREFIXES: tuple[str, ...] = (
    "http://loinc.org",
    "http://snomed.info/sct",
    "http://terminology.hl7.org/",
    "http://hl7.org/fhir/",
    "http://dicom.nema.org/",
    "http://unitsofmeasure.org",
)


def is_english_only_system(system_key_or_uri: str) -> bool:
    """True when the CodeSystem (registry key or URI) publishes English
    displays only — see :data:`ENGLISH_ONLY_SYSTEM_PREFIXES` (Issue #2276)."""
    value = str(system_key_or_uri or "")
    uri = value if value.startswith(("http://", "https://", "urn:")) else get_system_uri(value)
    return uri.startswith(ENGLISH_ONLY_SYSTEM_PREFIXES)


def is_japanese_only_display_system(system_key: str) -> bool:
    """True if ``system_key`` publishes displays in Japanese only.

    Callers that build multilingual CodeableConcepts use this to decide
    whether to emit an English secondary coding entry: for Japanese-only
    systems the English display cannot match the authoritative CS and must
    be omitted (Issue #358). See ``_JAPANESE_ONLY_DISPLAY_SYSTEMS``.
    """
    return system_key in _JAPANESE_ONLY_DISPLAY_SYSTEMS


# maxsize=None (unbounded): the set of code-system keys is bounded at
# module scope (~32 yaml files + a handful of aliases + at most one None
# entry per missing key), so unbounded cache carries no growth risk while
# eliminating the off-by-one LRU thrash. Pre-#1062 the ceiling was 32 vs
# 33 distinct keys, so every full pass evicted the LRU tail and the next
# access re-parsed the evicted yaml from disk — profile showed
# ``_load_system`` accumulating ~22s / 6,538 calls despite the decorator.
@cache
def _load_system(system_key: str) -> CodeSystem | None:
    """Load a code system yaml file. Returns None if not found."""
    data_key = _SYSTEM_DATA_ALIASES.get(system_key, system_key)
    path = _DATA_DIR / f"{data_key}.yaml"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    meta = data.get("metadata", {}) or {}
    # For aliased systems, override the URI from `_BUILTIN_URIS` so the alias
    # carries its distinct canonical URI while sharing the underlying code
    # data. Non-aliased systems continue to read their URI from the yaml
    # `metadata.uri` field as before.
    if system_key in _SYSTEM_DATA_ALIASES:
        uri = _BUILTIN_URIS.get(system_key, f"urn:clinosim:{system_key}")
    else:
        uri = meta.get("uri", f"urn:clinosim:{system_key}")
    return CodeSystem(
        key=system_key,
        name=meta.get("name", system_key),
        uri=uri,
        version=meta.get("version", ""),
        codes=data.get("codes", {}) or {},
    )


def _lookup_in_system(cs: CodeSystem, code: str) -> dict[str, str] | None:
    """Return the code entry from ``cs`` or None. Same resolution order as
    ``lookup``: exact → base (E11.9→E11) → child of base."""
    entry = cs.codes.get(code)
    if entry:
        return entry
    base = code.split(".")[0]
    entry = cs.codes.get(base)
    if entry:
        return entry
    prefix = code + "."
    for k, v in cs.codes.items():
        if k.startswith(prefix) or k == code:
            return v
    return None


def _resolve_entry(system: str, code: str) -> dict[str, str] | None:
    cs = _load_system(system)
    entry: dict[str, str] | None = None
    if cs:
        entry = _lookup_in_system(cs, code)
    if entry is None:
        for sibling_key in _SYSTEM_LOOKUP_SIBLINGS.get(system, ()):
            sibling = _load_system(sibling_key)
            if not sibling:
                continue
            entry = _lookup_in_system(sibling, code)
            if entry is not None:
                break
    return entry


def display(system: str, code: str, lang: str = "en") -> str | None:
    """Display text for a code, or ``None`` when the code is not registered.

    Same resolution as :func:`lookup` (exact, base, child, sibling systems;
    requested language, then English) but a miss is ``None`` instead of the
    code itself, so callers can write ``display(...) or fallback``
    (Issue #2256).
    """
    entry = _resolve_entry(system, code) if code else None
    if entry is None:
        return None
    if lang in entry:
        return str(entry[lang])
    if "en" in entry:
        return str(entry["en"])
    for candidate in entry.values():
        if isinstance(candidate, str):
            return candidate
    return None


def code_exists(system: str, code: str, *, exact: bool = False) -> bool:
    """True when ``code`` is registered in ``system``.

    ``exact=False`` uses the :func:`lookup` resolution (exact, base or child
    match); ``exact=True`` requires the code itself. Raises ``ValueError``
    when ``system`` is not a registered code system, so a typo fails loud.
    """
    cs = _load_system(system)
    if cs is None:
        raise ValueError(f"code system {system!r} is not registered in clinosim/codes/data/")
    if not code:
        return False
    if exact:
        return code in cs.codes
    return _lookup_in_system(cs, code) is not None


def system_key_for_uri(uri: str) -> str | None:
    """Code-system key for a FHIR system URI, the inverse of :func:`get_system_uri`."""
    return _URI_TO_KEY.get(uri)


def lookup(system: str, code: str, lang: str = "en") -> str:
    """Look up display text for a code in the given language.

    Resolution order:
    1. Exact match in ``system``
    2. Base code (e.g. "E11.9" → "E11") in ``system``
    3. Any sub-code starting with the given base (e.g. "I63" → "I63.9") in ``system``
    4. Steps 1-3 in each sibling system declared in
       ``_SYSTEM_LOOKUP_SIBLINGS[system]`` (Issue #415 — e.g. ``"yj"`` falls
       back to ``"hot7"`` so a HOT7 code passed with the ``"yj"`` key still
       resolves after the split).
    5. Return the code itself as fallback. Use :func:`display` when a miss
       should fall through to a caller-supplied fallback instead.
    """
    entry = _resolve_entry(system, code)
    if entry is None:
        return code

    if lang in entry:
        return str(entry[lang])
    if "en" in entry:
        return str(entry["en"])
    for candidate in entry.values():
        if isinstance(candidate, str):
            return candidate
    return code


def get_display(system: str, code: str, country: str = "US") -> str:
    """Convenience: look up display using country → language mapping.

    Country matching is case-insensitive; unmapped countries get English
    (``clinosim.countries.lang_for``, Issue #2274).
    """
    from clinosim.countries import lang_for

    lang = lang_for(country)
    return lookup(system, code, lang=lang)


def get_system_uri(system: str) -> str:
    """Get the FHIR canonical system URI for a code system key."""
    cs = _load_system(system)
    if cs:
        return cs.uri
    # Built-in fallbacks for known systems
    return _BUILTIN_URIS.get(system, f"urn:clinosim:{system}")


@cache
def slug_to_code(system_key: str) -> dict[str, str]:
    """Return the clinosim-internal slug → authoritative-code map from
    a code system yaml's optional ``slug_to_code:`` block.

    Some code systems (OMB race/ethnicity, …) are consumed by emit code
    through a stable short slug (``"white"``, ``"hispanic"``) rather
    than the authority code itself. Co-locating the slug table with
    the yaml that defines the codes keeps both faces of the same
    code system in one authoritative file; this helper surfaces that
    block without ``_load_system``'s ``codes:``-specific parsing.

    Returns an empty dict when the yaml is missing or has no
    ``slug_to_code:`` block, so callers can treat absence as "no slugs
    defined" uniformly.
    """
    data_key = _SYSTEM_DATA_ALIASES.get(system_key, system_key)
    path = _DATA_DIR / f"{data_key}.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return dict(data.get("slug_to_code", {}) or {})


# Country → code-system key selection for clinical data kinds (common-logic
# unification, 2026-07-02). Single source of truth for the "JP uses
# JLAC10 / ICD-10 / YJ / K-codes, everyone else uses LOINC / ICD-10-CM /
# RxNorm / CPT" selection previously inlined at each builder / simulator site.
_COUNTRY_SYSTEM_KEYS: dict[str, dict[str, str]] = {
    "lab": {"jp": "jlac10", "default": "loinc"},
    # Issue #350: JP path uses `icd-10-mhlw` (aliased to the
    # same code data as `icd-10` but carrying the MHLW canonical URI
    # `http://jpfhir.jp/fhir/core/mhlw/CodeSystem/ICD10-2013-full`). JP Core
    # `jp-condition-diagnosis` declares a required binding to that ValueSet;
    # emitting WHO `http://hl7.org/fhir/sid/icd-10` violates the binding
    # regardless of whether the code itself is valid.
    "diagnosis": {"jp": "icd-10-mhlw", "default": "icd-10-cm"},
    "drug": {"jp": "yj", "default": "rxnorm"},
    "procedure": {"jp": "k-codes", "default": "cpt"},
    "microbiology": {"jp": "jlac10", "default": "loinc"},
}


def system_key_for(kind: str, country: str) -> str:
    """Return the code-system key a country uses for a clinical data kind.

    Args:
        kind: one of ``"lab"``, ``"diagnosis"``, ``"drug"``, ``"procedure"``,
            ``"microbiology"``.
        country: country code (``"US"`` / ``"JP"``, case-insensitive).

    Raises:
        KeyError: on unknown ``kind`` — fail loud rather than silently
            falling back to a wrong code system (PR-90 silent-no-op class).
    """
    if kind not in _COUNTRY_SYSTEM_KEYS:
        raise KeyError(f"system_key_for: unknown kind {kind!r}; expected one of {sorted(_COUNTRY_SYSTEM_KEYS)}")
    entry = _COUNTRY_SYSTEM_KEYS[kind]
    # JP test inlined (codes/ must not import from modules/ — dependency direction).
    return entry["jp"] if str(country).strip().lower() == "jp" else entry["default"]


# Built-in fallback URIs when the yaml doesn't define one
_BUILTIN_URIS: dict[str, str] = {
    "icd-10-cm": "http://hl7.org/fhir/sid/icd-10-cm",
    "icd-10": "http://hl7.org/fhir/sid/icd-10",
    # Issue #350: JP-locale ICD-10 canonical URI. Same code
    # data as `icd-10` (WHO) via `_SYSTEM_DATA_ALIASES` above. The URI is
    # the required binding target on JP Core `jp-condition-diagnosis`.
    "icd-10-mhlw": "http://jpfhir.jp/fhir/core/mhlw/CodeSystem/ICD10-2013-full",
    "loinc": "http://loinc.org",
    "snomed-ct": "http://snomed.info/sct",
    "rxnorm": "http://www.nlm.nih.gov/research/umls/rxnorm",
    "cpt": "http://www.ama-assn.org/go/cpt",
    "jlac10": "urn:oid:1.2.392.200119.4.1005",
    # JP Core NamingSystem preferred=True fixedUri (iris4h-ai F-1
    # rationale + B2 2026-07-26 registry drift 訂正)。旧値 `.74` は HOT9 alias OID、
    # YJ 本来の OID は `.73`。emit 側は既に capstandard URI へ dispatch 済み。
    "yj": "http://capstandard.jp/iyaku.info/CodeSystem/YJ-code",
    # JP MEDIS medication code families — JP Core NamingSystem preferred fixedUri
    # 直接引用 (iris4h-ai/jp_core/package/NamingSystem-jp-medis-medicationcode*.json)。
    # code data 自体は現状 clinosim 側に持たない (URI resolve 目的の registry
    # entry のみ)。emit 側 `_fhir_medications.py:_resolve_jp_drug_system_uri`
    # の format 別 dispatch から eval axis が同一 canonical を参照するため。
    "hot7": "http://medis.or.jp/CodeSystem/master-HOT7",
    "hot9": "http://medis.or.jp/CodeSystem/master-HOT9",
    "hot13": "http://medis.or.jp/CodeSystem/master-HOT13",
    # JP-CLINS eCS Nocoded fallback CS — clinical-information-sharing#1.13.0
    # の CodeSystem-jp-eCS-medicationcode-nocoded-cs.json `url` 直接引用。
    # medication[x].coding min=1 を code_mapping 不在薬でも満たすための slice。
    "medication-nocoded": "http://jpfhir.jp/fhir/eCS/CodeSystem/MedicationCodeNocoded_CS",
    "k-codes": "urn:oid:1.2.392.200119.4.401",
    "ucum": "http://unitsofmeasure.org",
    "hl7-v3-actcode": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
    "hl7-v3-maritalstatus": "http://terminology.hl7.org/CodeSystem/v3-MaritalStatus",
    "hl7-observation-interpretation": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
    "hl7-observation-category": "http://terminology.hl7.org/CodeSystem/observation-category",
    "hl7-diagnostic-service-section": "http://terminology.hl7.org/CodeSystem/v2-0074",
    "cvx": "http://hl7.org/fhir/sid/cvx",
    # HL7 terminology CodeSystems used in FHIR resources (URI-1)
    "hl7-condition-clinical": "http://terminology.hl7.org/CodeSystem/condition-clinical",
    "hl7-condition-ver-status": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
    "hl7-condition-category": "http://terminology.hl7.org/CodeSystem/condition-category",
    "hl7-location-physical-type": "http://terminology.hl7.org/CodeSystem/location-physical-type",
    "hl7-referencerange-meaning": "http://terminology.hl7.org/CodeSystem/referencerange-meaning",
    "hl7-organization-type": "http://terminology.hl7.org/CodeSystem/organization-type",
    "hl7-v3-rolecode": "http://terminology.hl7.org/CodeSystem/v3-RoleCode",
    "hl7-v3-participationtype": "http://terminology.hl7.org/CodeSystem/v3-ParticipationType",
    "hl7-v3-administrativegender": "http://terminology.hl7.org/CodeSystem/v3-AdministrativeGender",
    "hl7-v3-actpriority": "http://terminology.hl7.org/CodeSystem/v3-ActPriority",
    # C1-19: Immunization.statusReason for status="not-done".
    "hl7-v3-actreason": "http://terminology.hl7.org/CodeSystem/v3-ActReason",
    "hl7-v2-0360": "http://terminology.hl7.org/CodeSystem/v2-0360",
    "hl7-v2-0203": "http://terminology.hl7.org/CodeSystem/v2-0203",
    "hl7-v2-0131": "http://terminology.hl7.org/CodeSystem/v2-0131",
    "hl7-v2-0092": "http://terminology.hl7.org/CodeSystem/v2-0092",
    "hl7-service-type": "http://terminology.hl7.org/CodeSystem/service-type",
    "hl7-practitioner-role": "http://terminology.hl7.org/CodeSystem/practitioner-role",
    "hl7-discharge-disposition": "http://terminology.hl7.org/CodeSystem/discharge-disposition",
    "hl7-diagnosis-role": "http://terminology.hl7.org/CodeSystem/diagnosis-role",
    "hl7-allergyintolerance-verification": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
    "hl7-allergyintolerance-clinical": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
    "hl7-admit-source": "http://terminology.hl7.org/CodeSystem/admit-source",
    "hl7-endpoint-connection-type": "http://terminology.hl7.org/CodeSystem/endpoint-connection-type",
    "hl7-endpoint-payload-type": "http://terminology.hl7.org/CodeSystem/endpoint-payload-type",
    "hl7-subscriber-relationship": "http://terminology.hl7.org/CodeSystem/subscriber-relationship",
    "us-core-documentreference-category": "http://hl7.org/fhir/us/core/CodeSystem/us-core-documentreference-category",
    # clinosim-owned CodeSystems for values that have no authoritative
    # standard-body CodeSystem URI (patient occupation category is a good
    # example: FHIR core has no ValueSet binding, US Core uses text-only,
    # JP Standard Occupation Classification has no registered FHIR URI).
    # Namespace under `clinosim.dev` — a non-example TLD so HAPI validator
    # does not reject it with the hard-coded "Example URL not allowed"
    # rule (#212, 2026-07-17).
    "occupation-category": "http://clinosim.dev/fhir/CodeSystem/occupation-category",
    # DICOM code systems (Tier 1 #2 Imaging, PR1)
    "dicom-modality": "http://dicom.nema.org/resources/ontology/DCM",
    # Issue #2265: JP document, allergen, severity and medication CodeSystems
    # and US identifier systems that emitters used to hard-code. Each URI is
    # the spec fixedUri the emitter already used (JP Core 1.2.0 / JP-CLINS
    # 1.13.0 / jpfhir-terminology 2.2606.0 / US Core 6.1.0); no code data is
    # held for them.
    "jpfhir-doc-subtypecodes": "http://jpfhir.jp/fhir/Common/CodeSystem/doc-subtypecodes",
    "jpfhir-echeckup-doc-typecodes": "http://jpfhir.jp/fhir/eCheckup/CodeSystem/doc-typecodes",
    "jp-document-codes": "http://jpfhir.jp/fhir/core/CodeSystem/JP_DocumentCodes_CS",
    "jp-jfagy-food-allergen": "http://jpfhir.jp/fhir/core/CodeSystem/JP_JfagyFoodAllergen_CS",
    "jp-jfagy-medication-allergen": "http://jpfhir.jp/fhir/core/CodeSystem/YCM/JP_JfagyMedicationAllergen_CS",
    "jp-jfagy-nonfood-nonmedication-allergen": (
        "http://jpfhir.jp/fhir/core/CodeSystem/JP_JfagyNonFoodNonMedicationAllergen_CS"
    ),
    "jp-condition-severity": "http://jpfhir.jp/fhir/core/CodeSystem/JP_ConditionSeverity_CS",
    "jp-clins-medication-usage-uncoded": "http://jpfhir.jp/fhir/clins/CodeSystem/JP_CLINS_MedicationUsage_Uncoded_CS",
    "jp-medication-usage-eprescription": "http://jpfhir.jp/fhir/core/mhlw/CodeSystem/MedicationUsage_ePrescription",
    "jp-medication-ingredient-strength-type": (
        "http://jpfhir.jp/fhir/core/mhlw/CodeSystem/MedicationIngredientStrengthStrengthType"
    ),
    "us-ssn": "http://hl7.org/fhir/sid/us-ssn",
    "us-npi": "http://hl7.org/fhir/sid/us-npi",
}

# Inverse of ``_BUILTIN_URIS`` (every URI is registered once) for
# :func:`system_key_for_uri` (Issue #2256).
_URI_TO_KEY: dict[str, str] = {uri: key for key, uri in _BUILTIN_URIS.items()}
