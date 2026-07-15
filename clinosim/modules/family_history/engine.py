"""Family history generation (AD-55 Base). Pure + seeded; codes only (AD-30)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

from clinosim.modules._shared import is_jp, is_us, normalize_probabilities
from clinosim.types.family_history import FamilyMemberHistoryRecord

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"
_LOCALE = _HERE.parents[1] / "locale"


@lru_cache(maxsize=1)
def load_reference() -> dict:
    with open(_REF_DIR / "family_history.yaml") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=2)
def load_prevalence(country: str) -> dict:
    """Load family-history prevalence for ``country``. Returns ``{}`` for
    unsupported countries rather than silently falling back to US data
    (locale-loader unsupported-country contract, 2026-07-02 grand design
    review)."""
    if not (is_us(country) or is_jp(country)):
        return {}
    key = "jp" if is_jp(country) else "us"
    with open(_LOCALE / key / "family_history_prevalence.yaml") as f:
        return (yaml.safe_load(f) or {}).get("prevalence", {})


def _condition_code(c) -> str:
    """Extract an ICD code string from a chronic condition (str | dict | object)."""
    if isinstance(c, str):
        return c
    if isinstance(c, dict):
        return str(c.get("code", ""))
    return str(getattr(c, "code", ""))


def _prevalence(prev: dict, code: str, sex: str, age: int) -> float:
    for band, rows in prev.get(code, {}).items():
        lo, hi = (int(x) for x in band.split("-"))
        if lo <= age <= hi:
            return float(rows.get(sex, 0.0))
    return 0.0


def _relative(
    prev: dict,
    conditions: dict,
    patient_codes: set[str],
    relationship: str,
    sex: str,
    age: int,
    deceased: bool,
    rng: np.random.Generator,
) -> FamilyMemberHistoryRecord:
    codes: list[str] = []
    for code, cfg in conditions.items():
        if cfg.get("sex") and cfg["sex"] != sex:
            continue
        p = _prevalence(prev, code, sex, age)
        if code in patient_codes:
            p = min(1.0, p * float(cfg.get("heritability", 1.0)))
        if rng.random() < p:
            codes.append(code)
    return FamilyMemberHistoryRecord(relationship=relationship, sex=sex, deceased=deceased, condition_codes=codes)


def generate_family_history(
    patient_age: int, patient_conditions: list[str], country: str, rng: np.random.Generator
) -> list[FamilyMemberHistoryRecord]:
    """Synthesize first-degree relatives + their diseases for one patient.

    Deterministic for a given rng. Conditions are assigned by locale prevalence
    (sex/age-banded), boosted by heritability when the patient carries the code.
    """
    ref = load_reference()
    prev = load_prevalence(country)
    conditions = ref["conditions"]
    patient_codes = {_condition_code(c).split(".")[0].upper() for c in (patient_conditions or []) if _condition_code(c)}

    po = ref["parent_age_offset"]
    out: list[FamilyMemberHistoryRecord] = []
    for rel, sex in (("MTH", "female"), ("FTH", "male")):
        age = patient_age + int(rng.integers(po["min"], po["max"] + 1))
        dp = min(
            ref["parent_deceased_max"], max(0.0, (age - ref["parent_deceased_base_age"]) / ref["parent_deceased_span"])
        )
        deceased = rng.random() < dp
        out.append(_relative(prev, conditions, patient_codes, rel, sex, age, deceased, rng))

    _sib_probs = normalize_probabilities(ref["sibling_count_weights"], fallback="raise")
    n_sib = int(rng.choice([0, 1, 2], p=_sib_probs))
    so = ref["sibling_age_offset"]
    for _ in range(n_sib):
        sex = "male" if rng.random() < 0.5 else "female"
        age = max(0, patient_age + int(rng.integers(so["min"], so["max"] + 1)))
        out.append(_relative(prev, conditions, patient_codes, "NSIB", sex, age, False, rng))
    return out
