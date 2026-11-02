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

import copy
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any, ClassVar, final

from clinosim.countries import normalize_lang
from clinosim.datafiles import data_metadata, load_data_yaml

_DATA_DIR = Path(__file__).parent / "data"


@dataclass
class CodeSystem:
    """One code system, built from its registry file (spec §2.3, Issue #2470).

    The base class owns the operations every authority shares — finding a
    code's entry, choosing the entry's language, falling back to English and
    returning ``None`` on a miss. They are ``@final``: a subclass never
    overrides them (``tests/unit/codes/test_code_system_base_2470.py``). A
    subclass implements only the hooks (``parents``) and adds its
    authority's own lookups. Lookup siblings are data
    (``_SYSTEM_LOOKUP_SIBLINGS``), not code.
    """

    key: str  # short key (e.g., "icd-10-cm")
    name: str  # human-readable name
    uri: str  # FHIR system URI
    version: str  # version / year
    codes: dict[str, dict[str, str]]  # code → {en, ja, ...}
    siblings: tuple[str, ...] = field(default=())  # lookup siblings, in order

    # Operations a subclass must not override.
    FINAL_OPERATIONS: ClassVar[tuple[str, ...]] = ("entry", "own_entry", "text", "display", "code_exists")

    def parents(self, code: str) -> tuple[str, ...]:
        """Hook: the codes ``code`` generalizes to, most specific first.

        A generalization is still true of the code, so its display may stand
        in for the code's own. The base class has no hierarchy."""
        return ()

    @final
    def own_entry(self, code: str) -> dict[str, str] | None:
        """The entry of ``code`` in this system alone: exact, then its parents."""
        entry = self.codes.get(code)
        if entry:
            return entry
        for parent in self.parents(code):
            entry = self.codes.get(parent)
            if entry:
                return entry
        # No child step: a more specific code's display never stands in for
        # a less specific code (spec §4.4, Issue #2454).
        return None

    @final
    def entry(self, code: str) -> dict[str, str] | None:
        """The entry of ``code`` here, else in each lookup sibling in order."""
        if not code:
            return None
        entry = self.own_entry(code)
        if entry is not None:
            return entry
        for sibling in _sibling_systems(self):
            entry = sibling.own_entry(code)
            if entry is not None:
                return entry
        return None

    @final
    def text(self, code: str, entry: dict[str, str], lang: str) -> str | None:
        """``entry`` in ``lang``; else the same code's ``lang`` text in a
        sibling system (an ICD-10-CM code shared with WHO takes the MHLW
        Japanese name, Issue #2360); else English; else ``None`` — never
        another language (spec §6, Issue #2395). ``lang`` is normalized the
        same way as every localized value (``countries.normalize_lang``)."""
        lang = normalize_lang(lang)
        if lang in entry:
            return str(entry[lang])
        for sibling in _sibling_systems(self):
            sib = sibling.codes.get(code)
            if sib and lang in sib:
                return str(sib[lang])
        if "en" in entry:
            return str(entry["en"])
        return None

    @final
    def display(self, code: str, lang: str = "en") -> str | None:
        """Display of ``code`` in ``lang`` (then English); ``None`` on a miss."""
        entry = self.entry(code)
        return None if entry is None else self.text(code, entry, lang)

    @final
    def code_exists(self, code: str, *, exact: bool = False) -> bool:
        """Whether ``code`` is registered (``exact``) or resolves to an entry
        of this system."""
        if not code:
            return False
        if exact:
            return code in self.codes
        return self.own_entry(code) is not None


def _sibling_systems(cs: CodeSystem) -> Iterator[CodeSystem]:
    for sibling_key in cs.siblings:
        sibling = _load_system(sibling_key)
        if sibling is not None:
            yield sibling


# Subclasses by system key, as "module:Class" so the authority modules,
# which import this one, load lazily (spec §2.2). A key not listed is a plain
# CodeSystem built from its registry file.
_SYSTEM_CLASSES: dict[str, str] = {
    "icd-10-cm": "clinosim.codes.icd10:Icd10CodeSystem",
    "icd-10": "clinosim.codes.icd10:Icd10CodeSystem",
    "icd-10-mhlw": "clinosim.codes.icd10:Icd10CodeSystem",
}


def _system_class(system_key: str) -> type[CodeSystem]:
    target = _SYSTEM_CLASSES.get(system_key)
    if target is None:
        return CodeSystem
    import importlib

    module, _, name = target.partition(":")
    cls = getattr(importlib.import_module(module), name)
    assert isinstance(cls, type) and issubclass(cls, CodeSystem), target
    return cls


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
    data = load_data_yaml(path)
    meta = data_metadata(path)
    # For aliased systems, override the URI from `_BUILTIN_URIS` so the alias
    # carries its distinct canonical URI while sharing the underlying code
    # data. Non-aliased systems continue to read their URI from the yaml
    # `metadata.uri` field as before.
    if system_key in _SYSTEM_DATA_ALIASES:
        uri = _BUILTIN_URIS.get(system_key, f"urn:clinosim:{system_key}")
    else:
        uri = meta.get("uri", f"urn:clinosim:{system_key}")
    return _system_class(system_key)(
        key=system_key,
        name=meta.get("name", system_key),
        uri=uri,
        version=meta.get("version", ""),
        codes=data.get("codes", {}) or {},
        siblings=_SYSTEM_LOOKUP_SIBLINGS.get(system_key, ()),
    )


def code_system(system_key: str) -> CodeSystem | None:
    """The :class:`CodeSystem` instance of a system key, or ``None`` when the
    key has no registry file."""
    return _load_system(system_key)


def system_keys() -> tuple[str, ...]:
    """Every system key: the registry files' keys, their data aliases and the
    URI-only keys of ``_BUILTIN_URIS`` (so tests can iterate all systems)."""
    keys = {p.stem for p in _DATA_DIR.glob("*.yaml")} | set(_SYSTEM_DATA_ALIASES) | set(_BUILTIN_URIS)
    return tuple(sorted(keys))


def _resolve_entry(system: str, code: str) -> dict[str, str] | None:
    """Entry of ``code`` in ``system`` (or a lookup sibling when ``system``
    has no registry file of its own)."""
    cs = _load_system(system)
    if cs is not None:
        return cs.entry(code)
    for sibling_key in _SYSTEM_LOOKUP_SIBLINGS.get(system, ()):
        sibling = _load_system(sibling_key)
        if sibling is not None and code:
            entry = sibling.own_entry(code)
            if entry is not None:
                return entry
    return None


def display(system: str, code: str, lang: str = "en") -> str | None:
    """Display text for a code, or ``None`` when the code is not registered.

    Resolved by the system's :class:`CodeSystem` (exact, parents, sibling
    systems; requested language, then English), so callers can write
    ``display(...) or fallback`` (Issue #2256).
    """
    cs = _load_system(system)
    if cs is not None:
        return cs.display(code, lang)
    entry = _resolve_entry(system, code) if code else None
    if entry is None:
        return None
    return _entry_text(system, code, entry, lang)


def _entry_text(system: str, code: str, entry: dict[str, str], lang: str) -> str | None:
    """Language choice for a system with no registry file of its own (only
    its siblings'): ``lang``, else the sibling's ``lang`` text, else English."""
    lang = normalize_lang(lang)
    if lang in entry:
        return str(entry[lang])
    for sibling_key in _SYSTEM_LOOKUP_SIBLINGS.get(system, ()):
        sibling = _load_system(sibling_key)
        sib = sibling.codes.get(code) if sibling else None
        if sib and lang in sib:
            return str(sib[lang])
    if "en" in entry:
        return str(entry["en"])
    return None


def code_exists(system: str, code: str, *, exact: bool = False) -> bool:
    """True when ``code`` is registered in ``system``.

    ``exact=False`` uses the :func:`lookup` resolution (exact or parent
    match); ``exact=True`` requires the code itself. Raises ``ValueError``
    when ``system`` is not a registered code system, so a typo fails loud.
    """
    cs = _load_system(system)
    if cs is None:
        raise ValueError(f"code system {system!r} is not registered in clinosim/codes/data/")
    return cs.code_exists(code, exact=exact)


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
    5. ``""`` on a miss — never the code itself (spec §6.2, Issue #2416);
       callers choose their own fallback (or use :func:`display`, which
       returns ``None``).
    """
    return display(system, code, lang) or ""


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
    return dict(load_data_yaml(path).get("slug_to_code", {}) or {})


@cache
def _data_table(name: str) -> dict[str, Any]:
    return load_data_yaml(_DATA_DIR / f"{name}.yaml")


def data_table(name: str) -> dict[str, Any]:
    """Parsed ``codes/data/<name>.yaml`` (a copy, so callers may reshape it).

    The one way code outside ``clinosim.codes`` reads a code-data table that
    has no dedicated accessor (Issue #2266); FileNotFoundError when the table
    does not exist.
    """
    return copy.deepcopy(_data_table(name))


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
    # MEDIS 標準病名マスター 病名管理番号 (JP-CLINS JP_Condition_eCS
    # `code.coding:medisRecordNo` fixedUri). Crosswalk data:
    # codes/data/medis-disease-keyno.yaml via codes.icd10 (Issue #2257).
    "medis-disease-keyno": "http://medis.or.jp/CodeSystem/master-disease-keyNumber",
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
    # Issue #2349: HL7 systems emitters referenced by URI literal.
    "hl7-medicationrequest-category": "http://terminology.hl7.org/CodeSystem/medicationrequest-category",
    "hl7-medicationrequest-course-of-therapy": "http://terminology.hl7.org/CodeSystem/medicationrequest-course-of-therapy",
    "hl7-medication-admin-category": "http://terminology.hl7.org/CodeSystem/medication-admin-category",
    "hl7-v3-substanceadminsubstitution": "http://terminology.hl7.org/CodeSystem/v3-substanceAdminSubstitution",
    "hl7-coverage-class": "http://terminology.hl7.org/CodeSystem/coverage-class",
    "hl7-coverage-copay-type": "http://terminology.hl7.org/CodeSystem/coverage-copay-type",
    "hl7-ex-diagnosistype": "http://terminology.hl7.org/CodeSystem/ex-diagnosistype",
    "hl7-v3-confidentiality": "http://terminology.hl7.org/CodeSystem/v3-Confidentiality",
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
    # Issue #2261: JP lab CodeSystems (JP-CLINS 1.13.0 lab-result slices, the
    # MEDIS JLAC10 17-digit master, the JLAC10 specimen-material CS). URIs
    # are the SD fixedUri values the lab coding package already used.
    "jp-clins-lab-corelabo-jlac10": "http://jpfhir.jp/fhir/clins/CodeSystem/JLAC10/JP_CLINS_ObsLabResult_CoreLabo_CS",
    "jp-clins-lab-corelabo-jlac11": "http://jpfhir.jp/fhir/clins/CodeSystem/JLAC11/JP_CLINS_ObsLabResult_CoreLabo_CS",
    "jp-clins-lab-infectionlabo-jlac10": (
        "http://jpfhir.jp/fhir/clins/CodeSystem/JLAC10/JP_CLINS_ObsLabResult_InfectionLabo_CS"
    ),
    "jp-clins-lab-infectionlabo-jlac11": (
        "http://jpfhir.jp/fhir/clins/CodeSystem/JLAC11/JP_CLINS_ObsLabResult_InfectionLabo_CS"
    ),
    "jp-clins-lab-uncoded": "http://jpfhir.jp/fhir/clins/CodeSystem/JP_CLINS_ObsLabResult_Uncoded_CS",
    "jp-clins-lab-localcode": "http://jpfhir.jp/fhir/clins/CodeSystem/JP_CLINS_ObsLabResult_LocalCode_CS",
    "jlac10-17digits": "http://medis.or.jp/CodeSystem/master-JLAC10-17digits",
    "jp-specimen-material-jlac10": "http://jpfhir.jp/fhir/core/CodeSystem/JP_ObservationSampleMaterialCodeJLAC10_CS",
    "us-ssn": "http://hl7.org/fhir/sid/us-ssn",
    "us-npi": "http://hl7.org/fhir/sid/us-npi",
}

# Inverse of ``_BUILTIN_URIS`` (every URI is registered once) for
# :func:`system_key_for_uri` (Issue #2256).
_URI_TO_KEY: dict[str, str] = {uri: key for key, uri in _BUILTIN_URIS.items()}
