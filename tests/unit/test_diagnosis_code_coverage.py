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

import yaml

import pytest

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
    fp = os.path.join(
        ROOT, "clinosim/modules/diagnosis/reference_data/builtin_differentials.yaml"
    )
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


# A genuine WHO ICD-10 code is 3-4 chars: a letter, two digits, optionally one decimal digit.
# CM granularity (5-7 chars, 7th-char extensions, X placeholders) is NOT valid WHO.
_WHO_FORMAT = re.compile(r"^[A-Z][0-9]{2}(\.[0-9])?$")

CM = _codes("clinosim/codes/data/icd-10-cm.yaml")
WHO = _codes("clinosim/codes/data/icd-10.yaml")
US_MAP = _map("clinosim/locale/us/code_mapping_diagnosis.yaml")
JP_MAP = _map("clinosim/locale/jp/code_mapping_diagnosis.yaml")
INTERNAL = _emittable_internal_codes()
ALL_EMITTABLE = INTERNAL | _engine_differential_codes()


def test_us_emittable_codes_resolve_billable_cm() -> None:
    missing = sorted(c for c in ALL_EMITTABLE if US_MAP.get(c, c) not in CM)
    assert not missing, (
        "Emittable diagnosis codes whose US target is not an exact key in icd-10-cm.yaml "
        f"(add the code or a code_mapping_diagnosis/US entry): {missing}"
    )


def test_jp_emittable_codes_resolve_true_who() -> None:
    missing = sorted(c for c in ALL_EMITTABLE if JP_MAP.get(c, c) not in WHO)
    assert not missing, (
        "Emittable diagnosis codes whose JP target is not an exact WHO ICD-10 key in "
        f"icd-10.yaml (add the WHO code or a code_mapping_diagnosis/jp entry): {missing}"
    )


def test_diagnosis_map_targets_exist_in_code_data() -> None:
    bad_us = sorted(v for v in US_MAP.values() if v not in CM)
    bad_jp = sorted(v for v in JP_MAP.values() if v not in WHO)
    assert not bad_us, f"US code_mapping_diagnosis targets missing from icd-10-cm.yaml: {bad_us}"
    assert not bad_jp, f"JP code_mapping_diagnosis targets missing from icd-10.yaml (WHO): {bad_jp}"


def test_jp_never_emits_cm_granular_code() -> None:
    """JP Condition codes must be true WHO ICD-10 (3-4 char), never ICD-10-CM granularity
    (5-7 char, 7th-char extensions, X placeholders) emitted under the WHO system URI.
    Covers all three emittable sources: disease + encounter YAMLs + engine.py differentials."""
    cm_granular = sorted(
        c for c in ALL_EMITTABLE if not _WHO_FORMAT.match(JP_MAP.get(c, c))
    )
    assert not cm_granular, (
        "JP would emit non-WHO-format codes under the icd-10 (WHO) system URI; add a "
        f"code_mapping_diagnosis/jp entry folding each to its WHO 3-4 char code: {cm_granular}"
    )


def test_icd10_who_file_has_no_cm_granular_codes() -> None:
    """The WHO ICD-10 data file must not contain ICD-10-CM-granularity codes."""
    bad = sorted(c for c in WHO if not _WHO_FORMAT.match(c))
    assert not bad, f"icd-10.yaml (WHO) contains non-WHO-format (ICD-10-CM) codes: {bad}"
