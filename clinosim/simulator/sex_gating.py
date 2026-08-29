"""Sex-gating for ICD-10 diagnosis dispatch (Issue #947).

Every site that assigns an ICD-10 Condition / Encounter.reasonCode to a
patient MUST consult :func:`is_sex_locked_for` before emitting. When the
site iterates a *ranked* candidate list (differential diagnosis) it should
use :func:`pick_sex_compatible_dx_code` — a bounded walk over ranked
candidates that consumes no RNG state (safe for cross-platform
determinism per ``feedback_deterministic_rng_proxy_pattern``).

Rationale (Issue #947, memory:
``feedback_dispatch_table_age_sex_gate_symmetry``,
``feedback_constants_live_in_external_config``,
``feedback_check_sibling_bugs_across_modules``):

The pre-fix generator had inline ``_SEX_RESTRICTED_ICD = {"N40": "M"}``
tables at two dispatch sites (``simulator/inpatient.py``,
``simulator/helpers.py``) covering exactly one code — BPH. Every other
sex-locked ICD-10 code (prostatitis N41.0, oophoritis N70, pregnancy
O00–O9A, …) was silently emit-able onto opposite-sex patients whenever
the RNG happened to pick it. Six female patients ended up with
``急性前立腺炎`` (N41.0) in the p=6389 JP cohort.

Fix pattern:

* Move the lock list to ``clinosim/locale/shared/icd10_sex_restrictions.yaml``
  (non-engineer-editable, single source of truth).
* Every dispatch site funnels through this helper — no local per-file
  tables, no per-code inline branches.
* Differential picker uses candidate-walk (non-RNG); static tables
  (implied-chronic, chronic propagation) skip.

Sex codes: patient records store ``sex`` as ``"M"`` or ``"F"``. FHIR
Patient.gender uses ``"male"`` / ``"female"`` / ``"other"`` / ``"unknown"``.
Both spellings are accepted here; other/unknown are treated as "no lock"
(caller emits without gating).
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_LOCALE_DIR = Path(__file__).resolve().parents[1] / "locale"
_YAML_PATH = _LOCALE_DIR / "shared" / "icd10_sex_restrictions.yaml"


@lru_cache(maxsize=1)
def _load_restrictions() -> tuple[frozenset[str], frozenset[str]]:
    """Load and freeze the sex-restriction table from yaml.

    Returns ``(male_only_codes, female_only_codes)`` as frozen sets. Both
    exact codes (``"N41.0"``) and base codes (``"N41"``) are stored — the
    matcher tries exact first, then base.
    """
    if not _YAML_PATH.exists():
        # Fallback: empty tables. A missing yaml is a broken install; log
        # via ValueError so CI catches it, but do not crash the simulator
        # for developers who happen to be editing the locale tree.
        return frozenset(), frozenset()
    with open(_YAML_PATH) as f:
        data = yaml.safe_load(f) or {}
    male = frozenset(str(c) for c in (data.get("male_only") or []))
    female = frozenset(str(c) for c in (data.get("female_only") or []))
    return male, female


def _normalize_sex(sex: str | None) -> str:
    """Normalize sex spellings (``"M"``/``"F"``/``"male"``/``"female"``…).

    Returns ``"M"`` / ``"F"`` for the two anatomy-relevant sexes;
    returns ``""`` for other/unknown/missing — the caller treats an
    empty string as "no lock" (never blocks emission).
    """
    s = (sex or "").strip().upper()
    if not s:
        return ""
    if s.startswith("M"):
        return "M"
    if s.startswith("F"):
        return "F"
    return ""


def _lock_kind(code: str) -> str:
    """Return ``"M"`` if code is male-only, ``"F"`` if female-only, else ``""``."""
    if not code:
        return ""
    male, female = _load_restrictions()
    # Try exact, then base (part before the first dot).
    base = code.split(".")[0]
    if code in male or base in male:
        return "M"
    if code in female or base in female:
        return "F"
    return ""


def is_sex_locked_for(code: str, patient_sex: str | None) -> bool:
    """True when the ICD-10 ``code`` cannot be emitted for ``patient_sex``.

    ``patient_sex`` is ``"M"``/``"F"`` (CIF) or ``"male"``/``"female"``
    (FHIR gender). Other/unknown/missing sex is treated as "no lock":
    the function returns ``False`` and the caller emits the code without
    gating (there's no meaningful check to perform).
    """
    kind = _lock_kind(code)
    if not kind:
        return False
    sex = _normalize_sex(patient_sex)
    if not sex:
        return False  # unknown/other — do not block
    return kind != sex


def pick_sex_compatible_dx_code(
    candidates: Iterable[Any],
    patient_sex: str | None,
    *,
    icd_attr: str = "icd_code",
) -> Any | None:
    """Return the first candidate whose ICD is not sex-locked for ``patient_sex``.

    ``candidates`` are already ordered by probability (highest first) —
    walking them is a "redraw" that consumes NO RNG state, so it is safe
    for cross-platform bit-reproducibility (memory:
    ``feedback_deterministic_rng_proxy_pattern``). Returns ``None`` if
    every candidate is locked (extremely unlikely; caller then falls back
    to whatever default it uses for the "differential did not converge"
    branch).

    ``icd_attr`` selects the attribute on each candidate that holds the
    ICD-10 code. Default matches
    :class:`clinosim.types.diagnosis.DiagnosisCandidate`.
    """
    for c in candidates:
        code = getattr(c, icd_attr, "") or ""
        if not is_sex_locked_for(code, patient_sex):
            return c
    return None
