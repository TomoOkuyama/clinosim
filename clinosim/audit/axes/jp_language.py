"""JP-language axis: cohort-level localization integrity.

Scope (Issue #473 replaces the earlier Observation-only implementation):

- Walks every NDJSON in the cohort for both JP and US countries.
- Predicate for a JP-side violation: text contains at least one Latin
  word (``[A-Za-z]{2,}``) AND contains ZERO Japanese characters. This
  is the ``§1`` predicate agreed on Issue #473 — an allow-list of
  acronyms (``AVPU`` / ``JCCLS`` / ``SOAP`` / ``Cre`` …) would grow
  without bound, but "has JP char anywhere" naturally covers mixed
  strings like ``'意識レベル (AVPU)'``.
- Predicate for a US-side leakage: text contains ANY Japanese char.
- Slot scope: every ``.text`` field is checked. ``.coding[].display``
  is checked ONLY when the coding's system is NOT an English canonical
  system (LOINC / SNOMED / HL7 terminologies / CPT / RxNorm / …).
  Excluding those slots avoids flagging spec-mandated English displays
  (dual-slot rule: ``coding.display = EN canonical`` / ``text = JP``).
- Excluded top-level blocks: ``meta`` / ``identifier`` / ``extension``
  / ``modifierExtension`` / ``contained``. URL-shaped strings
  (``http://`` / ``https://`` / ``urn:``) are also skipped.

Cohort-level: this axis ignores ``spec`` and runs once per audit.
``clinosim.audit.engine`` routes it via ``_COHORT_RUNNERS`` and
attaches the result to a synthetic ``"_cohort_"`` module row.

Segmented rollout: the axis reports every detected violation as INFO
(counts in ``result.info``), and additionally raises a WARN finding
for slots with any violation. FAIL is reserved for slots enumerated in
``LOCKED_SLOTS`` — slots we have deliberately fixed and where any
regression is a real defect. ``LOCKED_SLOTS`` starts empty; PRs that
close specific slots (e.g. #505 for ``Procedure.code.text``) add their
slot when the cohort count drops to zero. The scan helper
``count_jp_violations`` is exported so intentional-regression tests
can assert detection directly, independent of the WARN/FAIL gating.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from clinosim.audit.registry import ModuleAuditSpec
from clinosim.audit.types import AuditFinding, AxisResult, Cohort, Severity

# ────────────────────────────────────────────────────────────────────
# Predicates

_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
_JP_CHAR = re.compile(
    r"[぀-ゟ"  # hiragana
    r"゠-ヿ"  # katakana
    r"㐀-䶿"  # CJK ext A
    r"一-鿿"  # CJK unified
    r"ｦ-ﾟ"  # half-width katakana
    r"]"
)


def _has_jp(text: str) -> bool:
    return bool(_JP_CHAR.search(text or ""))


def _is_jp_violation(text: str) -> bool:
    """JP-side rule: string looks Latin-only where JP was expected."""
    if not text:
        return False
    return bool(_LATIN_WORD.search(text)) and not _has_jp(text)


def _is_us_leakage(text: str) -> bool:
    """US-side rule: any JP char in a supposedly English output."""
    return _has_jp(text)


def _looks_like_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://") or text.startswith("urn:")


# ────────────────────────────────────────────────────────────────────
# Slot scope

# Systems whose ``coding.display`` is the English canonical text by
# design. The dual-slot rule says the JP-facing text goes
# into ``code.text`` — not into the display of a canonical coding —
# so these displays MUST NOT be flagged as JP-side violations.
#
# Matched EITHER by exact URI (``_EN_CANONICAL_SYSTEMS``) OR by prefix
# (``_EN_CANONICAL_PREFIXES``). Prefix matching covers whole HL7 /
# international terminology families; the exact-URI set is used only
# for JP-authored CodeSystems whose display is deliberately English
# (JP-CLINS canonical slice CS, whose SD Fixed values are English).
_EN_CANONICAL_PREFIXES: tuple[str, ...] = (
    # HL7 terminology families — every URI under these is English canonical.
    "http://terminology.hl7.org/",
    "http://hl7.org/fhir/",
    # International code systems
    "http://loinc.org",
    "http://snomed.info/",
    "http://www.nlm.nih.gov/research/umls/",
    "http://www.ama-assn.org/",
    "http://dicom.nema.org/",
    "http://unitsofmeasure.org",
    # IANA / ISO registered vocabularies (BCP 47 languages, ISO codes)
    "urn:ietf:",
    "urn:iso:",
)

_EN_CANONICAL_SYSTEMS: frozenset[str] = frozenset(
    {
        # JP-CLINS canonical (SD ``fixedUri``) slice displays — CoreLabo
        # / InfectionLabo / Uncoded displays are the English SD Fixed
        # values by design (dual-slot rule: JP text goes into LocalCode
        # display or ``code.text``). Exclude their displays.
        "http://jpfhir.jp/fhir/clins/CodeSystem/JLAC10/JP_CLINS_ObsLabResult_CoreLabo_CS",
        "http://jpfhir.jp/fhir/clins/CodeSystem/JLAC10/JP_CLINS_ObsLabResult_InfectionLabo_CS",
        "http://jpfhir.jp/fhir/clins/CodeSystem/JLAC10/JP_CLINS_ObsLabResult_Uncoded_CS",
    }
)


def _is_english_canonical_system(system: str) -> bool:
    if not system:
        return False
    if system in _EN_CANONICAL_SYSTEMS:
        return True
    return any(system.startswith(p) for p in _EN_CANONICAL_PREFIXES)


_EXCLUDED_KEYS: frozenset[str] = frozenset(
    {
        "meta",
        "identifier",
        "extension",
        "modifierExtension",
        "contained",
    }
)


def _iter_slots(node: Any, path: str = "") -> Iterator[tuple[str, str]]:
    """Yield ``(slot_path, value)`` for every checked slot in ``node``.

    Includes:
    - Every ``.text`` field (as ``{path}.text``).
    - Every ``.coding[].display`` whose ``system`` is not in
      ``_EN_CANONICAL_SYSTEMS`` (as ``{path}.coding[].display``).

    Excludes:
    - ``_EXCLUDED_KEYS`` top-level blocks.
    - URL-shaped string values.
    """
    if isinstance(node, dict):
        text_val = node.get("text")
        if isinstance(text_val, str) and not _looks_like_url(text_val):
            yield (f"{path}.text" if path else "text", text_val)

        codings = node.get("coding")
        if isinstance(codings, list):
            for coding in codings:
                if not isinstance(coding, dict):
                    continue
                display = coding.get("display")
                if not isinstance(display, str):
                    continue
                system = coding.get("system", "")
                if _is_english_canonical_system(system):
                    continue
                if _looks_like_url(display):
                    continue
                yield (
                    f"{path}.coding[].display" if path else "coding[].display",
                    display,
                )

        for k, v in node.items():
            if k in _EXCLUDED_KEYS or k in ("text", "coding"):
                continue
            child = f"{path}.{k}" if path else k
            yield from _iter_slots(v, child)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_slots(item, path)


# ────────────────────────────────────────────────────────────────────
# Cohort walker (public — used by intentional-regression tests)

# NDJSON files that are not FHIR resource ndjsons (metadata / index).
_NON_RESOURCE_FILES: frozenset[str] = frozenset({"manifest"})


def _resource_types_for(cohort: Cohort, country: str) -> list[str]:
    """Enumerate FHIR resource types present in ``<cohort>/<country>/fhir_r4``."""
    root = cohort.root / country / "fhir_r4"
    if not root.exists():
        return []
    out: list[str] = []
    for p in sorted(root.glob("*.ndjson")):
        stem = p.stem
        if stem.startswith("_") or stem in _NON_RESOURCE_FILES:
            continue
        out.append(stem)
    return out


def _detect_flat_country(cohort: Cohort) -> str | None:
    """Peek at the first Patient in a flat-layout cohort to infer country.

    Multi-country layouts already have ``jp`` / ``us`` sub-directories
    (``cohort.countries()`` returns them). Single-country
    ``clinosim simulate --country JP`` creates a flat layout instead —
    ``cohort.countries()`` returns ``[""]``. For those, read the first
    Patient's ``address[0].country`` to decide.
    """
    if cohort.countries() != [""]:
        return None
    for row in cohort.ndjson("", "Patient"):
        for addr in row.get("address") or []:
            code = (addr.get("country") or "").upper()
            if code in {"JP", "US"}:
                return code.lower()
        break  # only inspect the first Patient
    return None


def _country_partitions(cohort: Cohort, wanted: str) -> list[str]:
    """Return the country partitions to walk for ``wanted`` (``jp`` / ``us``).

    - Multi-country layout: return ``[wanted]`` if present.
    - Flat layout: return ``[""]`` when the flat cohort's detected
      country matches ``wanted``.
    """
    countries = cohort.countries()
    if wanted in countries:
        return [wanted]
    if countries == [""] and _detect_flat_country(cohort) == wanted:
        return [""]
    return []


def count_jp_violations(cohort: Cohort) -> dict[str, dict[str, int]]:
    """Return ``{resource_type: {slot_path: count}}`` of JP-side violations.

    Walks the ``jp`` country partition (multi-country layout) or the
    flat root when a single-country ``--country JP`` cohort was
    generated. Returns ``{}`` when neither is present.
    """
    parts = _country_partitions(cohort, "jp")
    if not parts:
        return {}
    out: dict[str, dict[str, int]] = {}
    for part in parts:
        for rtype in _resource_types_for(cohort, part):
            per_slot: dict[str, int] = out.setdefault(rtype, {})
            for row in cohort.ndjson(part, rtype):
                for slot, value in _iter_slots(row):
                    if _is_jp_violation(value):
                        per_slot[slot] = per_slot.get(slot, 0) + 1
            if not per_slot:
                out.pop(rtype, None)
    return out


def count_us_leakage(cohort: Cohort) -> dict[str, dict[str, int]]:
    """Return ``{resource_type: {slot_path: count}}`` of US-side JP leakage."""
    parts = _country_partitions(cohort, "us")
    if not parts:
        return {}
    out: dict[str, dict[str, int]] = {}
    for part in parts:
        for rtype in _resource_types_for(cohort, part):
            per_slot: dict[str, int] = out.setdefault(rtype, {})
            for row in cohort.ndjson(part, rtype):
                for slot, value in _iter_slots(row):
                    if _is_us_leakage(value):
                        per_slot[slot] = per_slot.get(slot, 0) + 1
            if not per_slot:
                out.pop(rtype, None)
    return out


# ────────────────────────────────────────────────────────────────────
# Segmented rollout: slots that MUST be zero (FAIL on any residue).
# Add ``"ResourceType|slot.path"`` here as underlying fixes land and
# the cohort count for the slot reaches zero. Empty on introduction —
# every violation starts as WARN visibility; PRs promote slots to FAIL
# as they clean them.

LOCKED_SLOTS: frozenset[str] = frozenset(
    set()  # populated incrementally; see docstring above.
)


def _key(rtype: str, slot: str) -> str:
    return f"{rtype}|{slot}"


# ────────────────────────────────────────────────────────────────────
# Axis entrypoint (cohort-level; ``spec`` is ignored)


def run(spec: ModuleAuditSpec | None, cohort: Cohort) -> AxisResult:
    result = AxisResult(axis="jp_language", module=spec.name if spec else "_cohort_")

    # US: any JP char is a leakage bug. FAIL immediately.
    if _country_partitions(cohort, "us"):
        us = count_us_leakage(cohort)
        us_total = sum(sum(slots.values()) for slots in us.values())
        result.info["us_leakage_total"] = us_total
        for rtype, slots in us.items():
            for slot, n in slots.items():
                result.info[f"us_{_key(rtype, slot)}"] = n
        if us_total > 0:
            result.findings.append(
                AuditFinding(
                    Severity.FAIL,
                    f"US output has {us_total} JP-character leakages across {sum(len(s) for s in us.values())} slots",
                )
            )

    # JP: segmented rollout — WARN for visibility, FAIL only for LOCKED_SLOTS.
    if _country_partitions(cohort, "jp"):
        jp = count_jp_violations(cohort)
        jp_total = sum(sum(slots.values()) for slots in jp.values())
        result.info["jp_violation_total"] = jp_total
        locked_hits: list[tuple[str, str, int]] = []
        for rtype, slots in jp.items():
            for slot, n in slots.items():
                result.info[f"jp_{_key(rtype, slot)}"] = n
                if _key(rtype, slot) in LOCKED_SLOTS:
                    locked_hits.append((rtype, slot, n))
        if locked_hits:
            for rtype, slot, n in locked_hits:
                result.findings.append(
                    AuditFinding(
                        Severity.FAIL,
                        f"locked slot {rtype}.{slot} has {n} JP-side violations (must be zero)",
                    )
                )
        elif jp_total > 0:
            result.findings.append(
                AuditFinding(
                    Severity.WARN,
                    f"JP output has {jp_total} Latin-only text slots across "
                    f"{sum(len(s) for s in jp.values())} slot kinds "
                    f"(visibility only — see info dict; promote slots to "
                    f"LOCKED_SLOTS once fixed)",
                )
            )

    return result
