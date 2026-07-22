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
from functools import lru_cache
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


# Issue #350 (session 63): system keys that share underlying code data with
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


# Issue #358: system keys whose canonical CodeSystem publishes only a
# Japanese ``display`` for each concept — emitting an English display against
# this system URI produces a display-mismatch error at conformance time
# (validator compares against the authoritative CS). Consumers building
# multilingual CodeableConcepts (e.g. ``_build_diagnosis_codeable_concept``)
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


def is_japanese_only_display_system(system_key: str) -> bool:
    """True if ``system_key`` publishes displays in Japanese only.

    Callers that build multilingual CodeableConcepts use this to decide
    whether to emit an English secondary coding entry: for Japanese-only
    systems the English display cannot match the authoritative CS and must
    be omitted (Issue #358). See ``_JAPANESE_ONLY_DISPLAY_SYSTEMS``.
    """
    return system_key in _JAPANESE_ONLY_DISPLAY_SYSTEMS


@lru_cache(maxsize=32)
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


def lookup(system: str, code: str, lang: str = "en") -> str:
    """Look up display text for a code in the given language.

    Resolution order:
    1. Exact match
    2. Base code (e.g. "E11.9" → "E11")
    3. Any sub-code starting with the given base (e.g. "I63" → "I63.9")
    4. Return the code itself as fallback
    """
    cs = _load_system(system)
    if not cs:
        return code

    entry = cs.codes.get(code)
    if not entry:
        # Base code lookup (strip subcode)
        base = code.split(".")[0]
        entry = cs.codes.get(base)

    if not entry:
        # Reverse: try to find a child code if the query is a base code
        prefix = code + "."
        for k, v in cs.codes.items():
            if k.startswith(prefix) or k == code:
                entry = v
                break

    if not entry:
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

    US → en, JP → ja.
    """
    lang = {"JP": "ja", "US": "en"}.get(country, "en")
    return lookup(system, code, lang=lang)


def get_system_uri(system: str) -> str:
    """Get the FHIR canonical system URI for a code system key."""
    cs = _load_system(system)
    if cs:
        return cs.uri
    # Built-in fallbacks for known systems
    return _BUILTIN_URIS.get(system, f"urn:clinosim:{system}")


# Country → code-system key selection for clinical data kinds (common-logic
# unification, 2026-07-02). Single source of truth for the "JP uses
# JLAC10 / ICD-10 / YJ / K-codes, everyone else uses LOINC / ICD-10-CM /
# RxNorm / CPT" selection previously inlined at each builder / simulator site.
_COUNTRY_SYSTEM_KEYS: dict[str, dict[str, str]] = {
    "lab": {"jp": "jlac10", "default": "loinc"},
    # Issue #350 (session 63): JP path uses `icd-10-mhlw` (aliased to the
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
    # Issue #350 (session 63): JP-locale ICD-10 canonical URI. Same code
    # data as `icd-10` (WHO) via `_SYSTEM_DATA_ALIASES` above. The URI is
    # the required binding target on JP Core `jp-condition-diagnosis`.
    "icd-10-mhlw": "http://jpfhir.jp/fhir/core/mhlw/CodeSystem/ICD10-2013-full",
    "loinc": "http://loinc.org",
    "snomed-ct": "http://snomed.info/sct",
    "rxnorm": "http://www.nlm.nih.gov/research/umls/rxnorm",
    "cpt": "http://www.ama-assn.org/go/cpt",
    "jlac10": "urn:oid:1.2.392.200119.4.1005",
    "yj": "urn:oid:1.2.392.100495.20.2.74",
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
    # C1-19 (session 41 cycle 1): Immunization.statusReason for status="not-done".
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
}
