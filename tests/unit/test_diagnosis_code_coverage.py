"""Coverage invariant: every diagnosis code the simulator can emit resolves to an
authoritative display entry in the code-system data (no prefix-fallback, no fabrication).

clinosim's codes/data/*.yaml are an intentional *subset* of each registry (only what the
simulator generates — see codes/README.md). This test enforces the implicit contract that
the subset is *closed over what is actually emittable*:

  - US path: code_mapping_diagnosis(US).get(C, C) must be an exact key in icd-10-cm.yaml.
  - JP path: code_mapping_diagnosis(JP).get(C, C) must be an exact key in icd-10.yaml
    (true WHO ICD-10 — JP no longer relies on ICD-10-CM cross-fallback; see AD/PR for
    JP WHO-granularity migration).

C ranges over every disease icd_codes (primary + variants) and every encounter icd10_code,
plus every value (mapped target) in either diagnosis map.

Regression guard for the "used-but-missing ICD code" gap (I21.2, I50.0, K57.11→K57.31, ...).
When you add a disease/encounter scenario, add its codes to codes/data and this test stays green.
"""

from __future__ import annotations

import glob
import os
import re

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def _codes(rel: str) -> set[str]:
    with open(os.path.join(ROOT, rel)) as f:
        return set((yaml.safe_load(f) or {}).get("codes", {}).keys())


def _map(rel: str) -> dict[str, str]:
    with open(os.path.join(ROOT, rel)) as f:
        return yaml.safe_load(f) or {}


def _emittable_internal_codes() -> set[str]:
    codes: set[str] = set()
    for fp in glob.glob(os.path.join(ROOT, "clinosim/modules/disease/reference_data/*.yaml")):
        d = yaml.safe_load(open(fp)) or {}
        ic = d.get("icd_codes", {})
        if isinstance(ic, dict):
            if ic.get("primary"):
                codes.add(ic["primary"])
            for v in ic.get("variants", []) or []:
                if isinstance(v, dict) and v.get("code"):
                    codes.add(v["code"])
    for fp in glob.glob(os.path.join(ROOT, "clinosim/modules/encounter/reference_data/*.yaml")):
        d = yaml.safe_load(open(fp)) or {}
        if d.get("icd10_code"):
            codes.add(d["icd10_code"])
    return codes


def _engine_differential_codes() -> set[str]:
    """ICD codes in the built-in differential/progression tables (3rd emittable source:
    working/discharge diagnoses) loaded from diagnosis/reference_data."""
    fp = os.path.join(ROOT, "clinosim/modules/diagnosis/reference_data/builtin_differentials.yaml")
    data = yaml.safe_load(open(fp)) or {}
    codes: set[str] = set()
    for rows in data.get("differentials", {}).values():
        for entry in rows:
            if entry.get("icd"):
                codes.add(entry["icd"])
    for rows in data.get("diagnosis_progression", {}).values():
        for row in rows:
            if len(row) >= 2 and row[1]:
                codes.add(row[1])
    return codes


def _family_history_codes() -> set[str]:
    """ICD codes in the family_history condition prevalence table (4th emittable
    source: FamilyMemberHistory.condition[]). Session 40 gap: I64 emitted from
    this channel had no icd-10-cm entry and no US mapping, so US FHIR fell back to
    "(display unavailable)". The coverage test now spans all four channels so any
    future family_history addition without a code registration fails at unit time.
    """
    fp = os.path.join(ROOT, "clinosim/modules/family_history/reference_data/family_history.yaml")
    data = yaml.safe_load(open(fp)) or {}
    return set((data.get("conditions") or {}).keys())


def _perinatal_admission_codes() -> set[str]:
    """ICD codes emitted as delivery admission diagnoses (6th emittable
    source: perinatal.yaml admission_diagnosis_code drives the mother's
    delivery Encounter primary diagnosis in FHIR emit). Issue #1035:
    O80 was the sole perinatal admission code but had no icd-10.yaml /
    icd-10-cm.yaml entry, so 186 US + 157 JP Condition resources fell
    back to "(display unavailable)". The coverage sweep now spans this
    channel too."""
    fp = os.path.join(ROOT, "clinosim/locale/shared/perinatal.yaml")
    if not os.path.exists(fp):
        return set()
    data = yaml.safe_load(open(fp)) or {}
    codes: set[str] = set()

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            for key, val in node.items():
                if key == "admission_diagnosis_code" and isinstance(val, str):
                    codes.add(val)
                else:
                    _walk(val)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(data)
    return codes


def _chronic_followup_codes() -> set[str]:
    """ICD codes emitted from the chronic_followup.yaml prevalence table
    (7th emittable source: chronic follow-up visits key on WHO/base
    codes like C15/C25/C67 which propagate to Condition.code on the
    followup Encounter). Issue #1035: C15/C25/C67 were emitted as bare
    base codes but had no icd-10.yaml entry, so JP fell back to
    "(display unavailable)" for 93 Condition resources.

    Underscore-prefixed keys (``_post_discharge``, ``_post_discharge_by_disease``)
    are private configuration sections, not ICD codes — filter them out.
    A followup entry only actually fires when the patient carries the
    chronic disease, so the effective per-country emittable set is the
    intersection with that country's locale chronic prevalence (see
    ``_locale_chronic_codes``); this helper returns the raw keys and
    callers intersect where needed."""
    fp = os.path.join(ROOT, "clinosim/locale/shared/chronic_followup.yaml")
    if not os.path.exists(fp):
        return set()
    data = yaml.safe_load(open(fp)) or {}
    if not isinstance(data, dict):
        return set()
    return {k for k in data if not k.startswith("_")}


def _locale_chronic_codes(country: str) -> set[str]:
    """ICD codes referenced in locale demographics (5th emittable source: chronic
    condition prevalence + comorbidity_correlations tables that drive population
    generation). Session 42 gap: 7 chronic codes were added to JP demographics.yaml
    (E79/H26/K59/I84/K74/M54/F32) but 4 (E79/H26/K59/I84) had no icd-10.yaml
    entry, so 49,391 Condition resources fell back to "(display unavailable)".
    The coverage test now spans all five channels so any locale demographics
    addition without a code registration fails at unit time.

    Scoped per-country: the simulator only reads demographics.yaml for the
    country under simulation, so JP-only chronic codes should not be tested
    against the US code system.
    """
    fp = os.path.join(ROOT, f"clinosim/locale/{country}/demographics.yaml")
    if not os.path.exists(fp):
        return set()
    data = yaml.safe_load(open(fp)) or {}
    codes: set[str] = set()
    chronic = data.get("chronic_conditions") or {}
    if isinstance(chronic, dict):
        codes |= set(chronic.keys())
    # comorbidity_correlations: {source_icd: {target_icd: multiplier}} — both
    # source and target are emittable.
    corr = data.get("comorbidity_correlations") or {}
    if isinstance(corr, dict):
        for src, targets in corr.items():
            codes.add(src)
            if isinstance(targets, dict):
                codes |= set(targets.keys())
    return codes


# A genuine WHO ICD-10 code is 3-4 chars: a letter, two digits, optionally one decimal digit.
# CM granularity (5-7 chars, 7th-char extensions, X placeholders) is NOT valid WHO.
_WHO_FORMAT = re.compile(r"^[A-Z][0-9]{2}(\.[0-9])?$")

CM = _codes("clinosim/codes/data/icd-10-cm.yaml")
WHO = _codes("clinosim/codes/data/icd-10.yaml")
US_MAP = _map("clinosim/locale/us/code_mapping_diagnosis.yaml")
JP_MAP = _map("clinosim/locale/jp/code_mapping_diagnosis.yaml")
INTERNAL = _emittable_internal_codes()
_COUNTRY_AGNOSTIC = INTERNAL | _engine_differential_codes() | _family_history_codes() | _perinatal_admission_codes()
_CHRONIC_FOLLOWUP = _chronic_followup_codes()
# chronic_followup only fires for chronic conditions the locale actually
# has, so intersect with the locale demographics rather than assert every
# followup key resolves in both locales (Issue #1035: C15/C16/C25/C67/C71
# are JP-only cancers not present in US demographics).
US_EMITTABLE = _COUNTRY_AGNOSTIC | _locale_chronic_codes("us") | (_CHRONIC_FOLLOWUP & _locale_chronic_codes("us"))
JP_EMITTABLE = _COUNTRY_AGNOSTIC | _locale_chronic_codes("jp") | (_CHRONIC_FOLLOWUP & _locale_chronic_codes("jp"))


def _resolve_targets(mapping: dict, code: str) -> list[str]:
    """Return every possible mapped target for ``code``.

    A mapping entry is normally a string. Issue #957 introduced sex-
    conditional entries (currently only US C50) shaped as
    ``{default: <code>, by_sex: {F: <code>, M: <code>}}``; those expand
    to every string leaf inside the dict so the coverage sweep still
    finds them all.
    """
    value = mapping.get(code, code)
    if isinstance(value, dict):
        out: list[str] = []
        default = value.get("default")
        if isinstance(default, str):
            out.append(default)
        for leaf in (value.get("by_sex") or {}).values():
            if isinstance(leaf, str):
                out.append(leaf)
        return out or [code]
    return [str(value)]


def _all_map_targets(mapping: dict) -> list[str]:
    """Flatten every string leaf across the mapping (see ``_resolve_targets``)."""
    out: list[str] = []
    for value in mapping.values():
        if isinstance(value, dict):
            default = value.get("default")
            if isinstance(default, str):
                out.append(default)
            for leaf in (value.get("by_sex") or {}).values():
                if isinstance(leaf, str):
                    out.append(leaf)
        else:
            out.append(str(value))
    return out


def test_us_emittable_codes_resolve_billable_cm() -> None:
    missing = sorted(c for c in US_EMITTABLE if any(t not in CM for t in _resolve_targets(US_MAP, c)))
    assert not missing, (
        "Emittable diagnosis codes whose US target is not an exact key in icd-10-cm.yaml "
        f"(add the code or a code_mapping_diagnosis/US entry): {missing}"
    )


def test_jp_emittable_codes_resolve_true_who() -> None:
    missing = sorted(c for c in JP_EMITTABLE if any(t not in WHO for t in _resolve_targets(JP_MAP, c)))
    assert not missing, (
        "Emittable diagnosis codes whose JP target is not an exact WHO ICD-10 key in "
        f"icd-10.yaml (add the WHO code or a code_mapping_diagnosis/jp entry): {missing}"
    )


def test_diagnosis_map_targets_exist_in_code_data() -> None:
    bad_us = sorted(v for v in _all_map_targets(US_MAP) if v not in CM)
    bad_jp = sorted(v for v in _all_map_targets(JP_MAP) if v not in WHO)
    assert not bad_us, f"US code_mapping_diagnosis targets missing from icd-10-cm.yaml: {bad_us}"
    assert not bad_jp, f"JP code_mapping_diagnosis targets missing from icd-10.yaml (WHO): {bad_jp}"


def test_jp_never_emits_cm_granular_code() -> None:
    """JP Condition codes must be true WHO ICD-10 (3-4 char), never ICD-10-CM granularity
    (5-7 char, 7th-char extensions, X placeholders) emitted under the WHO system URI.
    Covers all three emittable sources: disease + encounter YAMLs + engine.py differentials."""
    cm_granular = sorted(c for c in JP_EMITTABLE if any(not _WHO_FORMAT.match(t) for t in _resolve_targets(JP_MAP, c)))
    assert not cm_granular, (
        "JP would emit non-WHO-format codes under the icd-10 (WHO) system URI; add a "
        f"code_mapping_diagnosis/jp entry folding each to its WHO 3-4 char code: {cm_granular}"
    )


def test_icd10_who_file_has_no_cm_granular_codes() -> None:
    """The WHO ICD-10 data file must not contain ICD-10-CM-granularity codes."""
    bad = sorted(c for c in WHO if not _WHO_FORMAT.match(c))
    assert not bad, f"icd-10.yaml (WHO) contains non-WHO-format (ICD-10-CM) codes: {bad}"


def test_hapi_absent_who_codes_are_remapped() -> None:
    """#284 regression: 3 WHO ICD-10 codes historically emitted by clinosim are
    absent from HAPI's ICD-10 CS (2019-covid-expanded, content=complete) and
    were remapped to HAPI-present equivalents. Pin the remap so a future
    accidental re-introduction is caught in CI.

    - I84 (Haemorrhoids) → K64.9 (WHO 2013+; I84 was retired)
    - R33.9 (Retention of urine, unspecified) → R33 (HAPI has no R33 subcodes)
    - S62.9 → S62.8 (HAPI attaches the "other/unspecified wrist/hand fracture"
      display to S62.8, not S62.9)
    """
    assert "I84" not in WHO, "I84 was retired from WHO ICD-10 2013+; use K64.9 (#284)"
    assert "R33.9" not in WHO, "HAPI ICD-10 CS has no R33 subcodes; use R33 (#284)"
    assert "S62.9" not in WHO, "HAPI ICD-10 CS attaches the display to S62.8 (#284)"
    assert "K64.9" in WHO, "K64.9 (Haemorrhoids, unspecified) required (#284)"
    assert "R33" in WHO, "R33 (Retention of urine) required (#284)"
    assert "S62.8" in WHO, "S62.8 (Fracture of other/unspecified wrist/hand) required (#284)"
    # JP code_mapping must fold CM/legacy codes to the HAPI-present WHO code.
    assert JP_MAP.get("R33.9") == "R33", "jp map R33.9 → R33 required (#284)"
    assert JP_MAP.get("S62.90XA") == "S62.8", "jp map S62.90XA → S62.8 required (#284)"
