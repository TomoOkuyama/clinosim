"""Locale axis — language + code-system compliance (5 checks, MVP)."""

from __future__ import annotations

from clinosim.audit.types import Cohort
from clinosim.eval.engine import EvalCheck, Outcome, Severity

_RXNORM_SYSTEM = "http://www.nlm.nih.gov/research/umls/rxnorm"
_LOINC_SYSTEM = "http://loinc.org"
_JLAC10_SYSTEM_PREFIXES = ("urn:oid:1.2.392.200119.4.1005",)  # JLAC10 canonical OID
_YJ_SYSTEM_PREFIXES = ("urn:oid:1.2.392.100495.20.2.74",)
_JP_CORE_URL_PREFIX = "http://jpfhir.jp/fhir/core/StructureDefinition/"


def _detect_country_from_cohort(cohort: Cohort, country: str) -> str:
    """When the cohort is stored in the flat layout ``<root>/fhir_r4/`` the
    directory name doesn't carry the country. Peek at the first Patient's
    ``address.country`` (or JP Core profile presence) to pick a lens."""
    if country and country.upper() in ("US", "JP"):
        return country.upper()
    # Peek at the first Patient.
    for row in _read(cohort, country, "Patient"):
        for addr in row.get("address") or []:
            c = (addr.get("country") or "").upper()
            if c in ("US", "JP"):
                return c
        profile = ((row.get("meta") or {}).get("profile")) or []
        if any(p.startswith(_JP_CORE_URL_PREFIX) for p in profile):
            return "JP"
        break
    return "US"


def run(cohort: Cohort, country: str) -> list[EvalCheck]:
    is_jp = _detect_country_from_cohort(cohort, country) == "JP"
    if is_jp:
        return [
            _jp_japanese_displays_on_condition(cohort, country),
            _jp_jlac10_or_loinc_on_lab(cohort, country),
            _jp_yj_code_on_medications(cohort, country),
            _jp_core_profile_declared(cohort, country),
            _jp_name_order(cohort, country),
        ]
    return [
        _us_ascii_only_displays(cohort, country),
        _us_rxnorm_present_on_medications(cohort, country),
        _us_loinc_present_on_lab_observations(cohort, country),
        _us_no_japanese_leakage(cohort, country),
        _us_practitioner_name_order(cohort, country),
    ]


# --------------------------------------------------------------------------- #
# JP checks

def _jp_japanese_displays_on_condition(cohort: Cohort, country: str) -> EvalCheck:
    """Condition.code.text or coding.display must contain at least one
    non-ASCII character (kanji / hiragana / katakana) — otherwise the
    display leaked English."""
    total = 0
    english_only = 0
    for row in _read(cohort, country, "Condition"):
        code = row.get("code") or {}
        parts = [code.get("text", "")]
        for c in (code.get("coding") or []):
            parts.append(c.get("display", ""))
        blob = "".join(p for p in parts if p)
        if not blob:
            continue
        total += 1
        if all(ord(ch) < 128 for ch in blob):
            english_only += 1
    if total == 0:
        return EvalCheck(
            name="japanese_displays_on_condition",
            outcome=Outcome.NA, severity=Severity.MAJOR,
            message="No Condition rows with display text found.",
        )
    if english_only == 0:
        return EvalCheck(
            name="japanese_displays_on_condition",
            outcome=Outcome.PASS, severity=Severity.MAJOR,
            message=f"All {total} Condition rows carry Japanese display text.",
        )
    ratio = english_only / total
    outcome = Outcome.WARN if ratio < 0.05 else Outcome.FAIL
    return EvalCheck(
        name="japanese_displays_on_condition",
        outcome=outcome, severity=Severity.MAJOR,
        message=f"{english_only}/{total} Condition rows carry ASCII-only display ({ratio:.1%}).",
        detail={"total": total, "english_only": english_only},
    )


def _jp_jlac10_or_loinc_on_lab(cohort: Cohort, country: str) -> EvalCheck:
    """Every laboratory-category Observation should carry either a JLAC10 code
    (JP-primary) or a LOINC code (interop). Both is ideal (dual coding)."""
    total = 0
    without = 0
    with_dual = 0
    for row in _read(cohort, country, "Observation"):
        if not _is_lab_category(row):
            continue
        total += 1
        codings = (row.get("code") or {}).get("coding") or []
        has_jlac = any(
            any(c.get("system", "").startswith(p) for p in _JLAC10_SYSTEM_PREFIXES) for c in codings
        )
        has_loinc = any(c.get("system") == _LOINC_SYSTEM for c in codings)
        if not (has_jlac or has_loinc):
            without += 1
        if has_jlac and has_loinc:
            with_dual += 1
    if total == 0:
        return EvalCheck(
            name="jlac10_or_loinc_on_lab",
            outcome=Outcome.NA, severity=Severity.MAJOR,
            message="No laboratory-category Observations found.",
        )
    if without == 0:
        msg = f"All {total} lab Observations carry JLAC10 and/or LOINC (dual coding: {with_dual}/{total} = {with_dual/total:.1%})."
        return EvalCheck(
            name="jlac10_or_loinc_on_lab",
            outcome=Outcome.PASS, severity=Severity.MAJOR,
            message=msg, detail={"total": total, "dual_coded": with_dual},
        )
    return EvalCheck(
        name="jlac10_or_loinc_on_lab",
        outcome=Outcome.FAIL, severity=Severity.MAJOR,
        message=f"{without}/{total} lab Observations without JLAC10 or LOINC.",
    )


def _jp_yj_code_on_medications(cohort: Cohort, country: str) -> EvalCheck:
    """MedicationRequest / MedicationAdministration should carry a YJ code."""
    total = 0
    without = 0
    for row in _read_many(cohort, country, ["MedicationRequest", "MedicationAdministration"]):
        codings = ((row.get("medicationCodeableConcept") or {}).get("coding")) or []
        if not codings:
            continue
        total += 1
        if not any(any(c.get("system", "").startswith(p) for p in _YJ_SYSTEM_PREFIXES) for c in codings):
            without += 1
    if total == 0:
        return EvalCheck(
            name="yj_code_on_medications",
            outcome=Outcome.NA, severity=Severity.MAJOR,
            message="No medication resources found.",
        )
    if without == 0:
        return EvalCheck(
            name="yj_code_on_medications",
            outcome=Outcome.PASS, severity=Severity.MAJOR,
            message=f"All {total} medication resources carry a YJ code.",
        )
    return EvalCheck(
        name="yj_code_on_medications",
        outcome=Outcome.FAIL, severity=Severity.MAJOR,
        message=f"{without}/{total} medication resources missing a YJ code.",
        detail={"missing": without, "total": total},
    )


def _jp_core_profile_declared(cohort: Cohort, country: str) -> EvalCheck:
    """Delegate to the structural axis's expectation but express it as a
    locale-axis concern (JP Core is a locale profile, not a structural one)."""
    types_seen = 0
    types_all_profiled = 0
    for path in _fhir_ndjsons(cohort, country):
        rt = path.stem
        total = 0
        with_profile = 0
        for row in _iter(path):
            total += 1
            profile = ((row.get("meta") or {}).get("profile")) or []
            if any(u.startswith(_JP_CORE_URL_PREFIX) for u in profile):
                with_profile += 1
        if total == 0:
            continue
        types_seen += 1
        if with_profile == total:
            types_all_profiled += 1
    if types_seen == 0:
        return EvalCheck(
            name="jp_core_profile_declared",
            outcome=Outcome.NA, severity=Severity.MAJOR,
            message="No FHIR resources found.",
        )
    ratio = types_all_profiled / types_seen
    if ratio == 1.0:
        return EvalCheck(
            name="jp_core_profile_declared",
            outcome=Outcome.PASS, severity=Severity.MAJOR,
            message=f"All {types_seen} resource types declare JP Core meta.profile.",
        )
    outcome = Outcome.WARN if ratio > 0.7 else Outcome.FAIL
    return EvalCheck(
        name="jp_core_profile_declared",
        outcome=outcome, severity=Severity.MAJOR,
        message=f"{types_all_profiled}/{types_seen} resource types declare JP Core profile ({ratio:.1%}).",
    )


def _jp_name_order(cohort: Cohort, country: str) -> EvalCheck:
    """JP practice: family + given, and a kana (SYL) variant should exist
    when the primary name is kanji (IDE)."""
    total = 0
    without_kana = 0
    for row in _read(cohort, country, "Patient"):
        names = row.get("name") or []
        if not names:
            continue
        total += 1
        has_ide = any(_name_use(n) == "IDE" for n in names)
        has_syl = any(_name_use(n) == "SYL" for n in names)
        if has_ide and not has_syl:
            without_kana += 1
    if total == 0:
        return EvalCheck(
            name="jp_name_order",
            outcome=Outcome.NA, severity=Severity.MINOR,
            message="No Patient.name found.",
        )
    if without_kana == 0:
        return EvalCheck(
            name="jp_name_order",
            outcome=Outcome.PASS, severity=Severity.MINOR,
            message=f"All {total} JP Patient names carry both IDE (kanji) and SYL (kana) variants.",
        )
    return EvalCheck(
        name="jp_name_order",
        outcome=Outcome.WARN, severity=Severity.MINOR,
        message=f"{without_kana}/{total} JP Patient names missing SYL (kana) variant.",
    )


# --------------------------------------------------------------------------- #
# US checks

def _us_ascii_only_displays(cohort: Cohort, country: str) -> EvalCheck:
    """No non-ASCII characters should appear in US Condition displays."""
    problems: list[str] = []
    for row in _read(cohort, country, "Condition"):
        code = row.get("code") or {}
        parts = [code.get("text", "")] + [
            c.get("display", "") for c in (code.get("coding") or [])
        ]
        blob = "".join(p for p in parts if p)
        if any(ord(ch) > 127 for ch in blob):
            problems.append(f"Condition/{row.get('id', '?')}: {blob[:60]}")
            if len(problems) > 20:
                break
    if not problems:
        return EvalCheck(
            name="ascii_only_displays",
            outcome=Outcome.PASS, severity=Severity.MAJOR,
            message="All Condition displays are ASCII.",
        )
    return EvalCheck(
        name="ascii_only_displays",
        outcome=Outcome.FAIL, severity=Severity.MAJOR,
        message=f"{len(problems)} Condition display(s) contain non-ASCII characters.",
        detail={"problems_sample": problems[:10]},
    )


def _us_rxnorm_present_on_medications(cohort: Cohort, country: str) -> EvalCheck:
    total = 0
    without = 0
    for row in _read_many(cohort, country, ["MedicationRequest", "MedicationAdministration"]):
        codings = ((row.get("medicationCodeableConcept") or {}).get("coding")) or []
        if not codings:
            continue
        total += 1
        if not any(c.get("system") == _RXNORM_SYSTEM for c in codings):
            without += 1
    if total == 0:
        return EvalCheck(
            name="rxnorm_present_on_medications",
            outcome=Outcome.NA, severity=Severity.MAJOR,
            message="No medication resources found.",
        )
    if without == 0:
        return EvalCheck(
            name="rxnorm_present_on_medications",
            outcome=Outcome.PASS, severity=Severity.MAJOR,
            message=f"All {total} medication resources carry an RxNorm code.",
        )
    return EvalCheck(
        name="rxnorm_present_on_medications",
        outcome=Outcome.FAIL, severity=Severity.MAJOR,
        message=f"{without}/{total} medication resources missing RxNorm.",
    )


def _us_loinc_present_on_lab_observations(cohort: Cohort, country: str) -> EvalCheck:
    total = 0
    without = 0
    for row in _read(cohort, country, "Observation"):
        if not _is_lab_category(row):
            continue
        total += 1
        codings = (row.get("code") or {}).get("coding") or []
        if not any(c.get("system") == _LOINC_SYSTEM for c in codings):
            without += 1
    if total == 0:
        return EvalCheck(
            name="loinc_present_on_lab_observations",
            outcome=Outcome.NA, severity=Severity.MAJOR,
            message="No laboratory-category Observations found.",
        )
    if without == 0:
        return EvalCheck(
            name="loinc_present_on_lab_observations",
            outcome=Outcome.PASS, severity=Severity.MAJOR,
            message=f"All {total} lab Observations carry LOINC.",
        )
    return EvalCheck(
        name="loinc_present_on_lab_observations",
        outcome=Outcome.FAIL, severity=Severity.MAJOR,
        message=f"{without}/{total} lab Observations missing LOINC.",
    )


def _us_no_japanese_leakage(cohort: Cohort, country: str) -> EvalCheck:
    """No CJK characters anywhere in US output."""
    def has_cjk(s: str) -> bool:
        return any(
            0x3040 <= ord(ch) <= 0x30FF        # hiragana + katakana
            or 0x4E00 <= ord(ch) <= 0x9FFF     # CJK unified ideographs
            for ch in s
        )
    leaks: list[str] = []
    for path in _fhir_ndjsons(cohort, country):
        for row in _iter(path):
            blob = _dump_strings(row)
            if has_cjk(blob):
                leaks.append(f"{path.name}: {row.get('id', '?')}")
                if len(leaks) > 20:
                    break
        if len(leaks) > 20:
            break
    if not leaks:
        return EvalCheck(
            name="no_japanese_leakage",
            outcome=Outcome.PASS, severity=Severity.CRITICAL,
            message="No CJK characters in US output.",
        )
    return EvalCheck(
        name="no_japanese_leakage",
        outcome=Outcome.FAIL, severity=Severity.CRITICAL,
        message=f"{len(leaks)} US resource(s) contain CJK characters.",
        detail={"leaks_sample": leaks[:10]},
    )


def _us_practitioner_name_order(cohort: Cohort, country: str) -> EvalCheck:
    """US Practitioner.name should follow given + family order (not JP-style
    family + given). Heuristic: given is a list, both present."""
    total = 0
    problems = 0
    for row in _read(cohort, country, "Practitioner"):
        names = row.get("name") or []
        if not names:
            continue
        total += 1
        for n in names:
            if not n.get("given") or not n.get("family"):
                problems += 1
                break
    if total == 0:
        return EvalCheck(
            name="us_practitioner_name_order",
            outcome=Outcome.NA, severity=Severity.MINOR,
            message="No Practitioner names found.",
        )
    if problems == 0:
        return EvalCheck(
            name="us_practitioner_name_order",
            outcome=Outcome.PASS, severity=Severity.MINOR,
            message=f"All {total} US Practitioner names have both given + family.",
        )
    return EvalCheck(
        name="us_practitioner_name_order",
        outcome=Outcome.WARN, severity=Severity.MINOR,
        message=f"{problems}/{total} US Practitioner names missing given or family.",
    )


# --------------------------------------------------------------------------- #
# helpers

def _read(cohort: Cohort, country: str, resource_type: str):
    return _iter(cohort.root / country / "fhir_r4" / f"{resource_type}.ndjson")


def _read_many(cohort: Cohort, country: str, types: list[str]):
    for t in types:
        yield from _read(cohort, country, t)


def _iter(path):
    import json
    if not path.exists():
        return iter(())
    def _gen():
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    return _gen()


def _fhir_ndjsons(cohort: Cohort, country: str):
    base = cohort.root / country / "fhir_r4"
    if not base.exists():
        return []
    return sorted(base.glob("*.ndjson"))


def _is_lab_category(row: dict) -> bool:
    for cat in row.get("category") or []:
        for c in cat.get("coding") or []:
            if c.get("code") == "laboratory":
                return True
    return False


def _name_use(name: dict) -> str:
    """FHIR HumanName.extension carries JP Core representation tags."""
    for ext in name.get("extension") or []:
        if ext.get("url", "").endswith("iso21090-EN-representation"):
            code = ext.get("valueCode")
            if code:
                return code
    return name.get("use", "").upper()


def _dump_strings(obj) -> str:
    parts: list[str] = []
    if isinstance(obj, dict):
        for v in obj.values():
            parts.append(_dump_strings(v))
    elif isinstance(obj, list):
        for item in obj:
            parts.append(_dump_strings(item))
    elif isinstance(obj, str):
        parts.append(obj)
    return "".join(parts)
