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


@lru_cache(maxsize=32)
def _load_system(system_key: str) -> CodeSystem | None:
    """Load a code system yaml file. Returns None if not found."""
    path = _DATA_DIR / f"{system_key}.yaml"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    meta = data.get("metadata", {}) or {}
    return CodeSystem(
        key=system_key,
        name=meta.get("name", system_key),
        uri=meta.get("uri", f"urn:clinosim:{system_key}"),
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
    for v in entry.values():
        if isinstance(v, str):
            return v
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
    "diagnosis": {"jp": "icd-10", "default": "icd-10-cm"},
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
        raise KeyError(
            f"system_key_for: unknown kind {kind!r}; expected one of "
            f"{sorted(_COUNTRY_SYSTEM_KEYS)}"
        )
    entry = _COUNTRY_SYSTEM_KEYS[kind]
    # JP test inlined (codes/ must not import from modules/ — dependency direction).
    return entry["jp"] if str(country).strip().lower() == "jp" else entry["default"]


# Built-in fallback URIs when the yaml doesn't define one
_BUILTIN_URIS: dict[str, str] = {
    "icd-10-cm": "http://hl7.org/fhir/sid/icd-10-cm",
    "icd-10": "http://hl7.org/fhir/sid/icd-10",
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
    "hl7-allergyintolerance-verification":
        "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
    "hl7-allergyintolerance-clinical":
        "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
    "hl7-admit-source": "http://terminology.hl7.org/CodeSystem/admit-source",
    "hl7-endpoint-connection-type":
        "http://terminology.hl7.org/CodeSystem/endpoint-connection-type",
    "hl7-endpoint-payload-type":
        "http://terminology.hl7.org/CodeSystem/endpoint-payload-type",
    "hl7-subscriber-relationship":
        "http://terminology.hl7.org/CodeSystem/subscriber-relationship",
    "us-core-documentreference-category":
        "http://hl7.org/fhir/us/core/CodeSystem/us-core-documentreference-category",
    "occupation-category": "http://clinosim.example.org/CodeSystem/occupation-category",
    # DICOM code systems (Tier 1 #2 Imaging, PR1)
    "dicom-modality": "http://dicom.nema.org/resources/ontology/DCM",
}
