"""Coverage invariant: every diagnosis code the simulator can emit resolves to an
authoritative display entry in the code-system data (no prefix-fallback, no fabrication).

clinosim's codes/data/*.yaml are an intentional *subset* of each registry (only what the
simulator generates — see codes/README.md). This test enforces the implicit contract that
the subset is *closed over what is actually emittable*:

  - US path: code_mapping_diagnosis(US).get(C, C) must be an exact key in icd-10-cm.yaml.
  - JP path: code_mapping_diagnosis(JP).get(C, C) must be an exact key in icd-10.yaml,
    or in icd-10-cm.yaml (the FHIR adapter's documented cross-system fallback for JP).

C ranges over every disease icd_codes (primary + variants) and every encounter icd10_code,
plus every value (mapped target) in either diagnosis map.

Regression guard for the "used-but-missing ICD code" gap (I21.2, I50.0, K57.11→K57.31, ...).
When you add a disease/encounter scenario, add its codes to codes/data and this test stays green.
"""

from __future__ import annotations

import glob
import os

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


CM = _codes("clinosim/codes/data/icd-10-cm.yaml")
WHO = _codes("clinosim/codes/data/icd-10.yaml")
US_MAP = _map("clinosim/locale/us/code_mapping_diagnosis.yaml")
JP_MAP = _map("clinosim/locale/jp/code_mapping_diagnosis.yaml")
INTERNAL = _emittable_internal_codes()


def test_us_emittable_codes_resolve_billable_cm() -> None:
    missing = sorted(c for c in INTERNAL if US_MAP.get(c, c) not in CM)
    assert not missing, (
        "Emittable diagnosis codes whose US target is not an exact key in icd-10-cm.yaml "
        f"(add the code or a code_mapping_diagnosis/US entry): {missing}"
    )


def test_jp_emittable_codes_resolve_who_or_cm_fallback() -> None:
    missing = sorted(
        c for c in INTERNAL if JP_MAP.get(c, c) not in WHO and JP_MAP.get(c, c) not in CM
    )
    assert not missing, (
        "Emittable diagnosis codes whose JP target resolves in neither icd-10.yaml nor "
        f"icd-10-cm.yaml (cross-fallback): {missing}"
    )


def test_diagnosis_map_targets_exist_in_code_data() -> None:
    bad_us = sorted(v for v in US_MAP.values() if v not in CM)
    bad_jp = sorted(v for v in JP_MAP.values() if v not in WHO and v not in CM)
    assert not bad_us, f"US code_mapping_diagnosis targets missing from icd-10-cm.yaml: {bad_us}"
    assert not bad_jp, f"JP code_mapping_diagnosis targets missing from code data: {bad_jp}"
