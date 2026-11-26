"""Condition-list mutex rules — clinically coherent ``chronic_conditions``.

Some ICD-10-CM codes are mutually exclusive by clinical definition. The
initial-cohort sampler (``engine.py``) and the mid-sim longitudinal
onset-event dispatch (``modules/longitudinal/engine.py``) each append
codes independently, so dual-presence has to be collapsed at every
assignment site via the helpers in this module.

The rules intentionally live outside the two engines so they can be
applied uniformly from both call sites and extended for future ICD
subsumption pairs without touching either engine's RNG shape — the
Bernoulli draws themselves are unchanged; we only filter the
already-sampled result.

Current rules
-------------
* **F31 vs F32 / F33** (``apply_depression_mutex``) — bipolar disorder's
  depressive episodes are coded under F31 (ICD-10 §F30-F39), so F32 / F33
  are dropped when F31 is present (Issue #2142).
* **F32 vs F33** (``apply_depression_mutex``) — per ICD-10-CM §F30-F39,
  ``F33`` (recurrent depressive disorder) subsumes ``F32`` (depressive
  episode, single). Once a patient becomes F33, F32 must no longer be
  present on the problem list.
* **E11.9 vs another E11.x** (``redundant_uncomplicated_diabetes_indices``) —
  ``E11.9`` is "type 2 diabetes mellitus *without* complications", which a
  patient's complication code (E11.2 nephropathy, E11.3 retinopathy, E11.4
  neuropathy, ...) contradicts. Unlike the two rules above this one does not
  edit ``chronic_conditions``: the CIF keeps ``E11.9`` as the internal driver
  of the diabetes follow-up spec, the base regimen and
  ``has_condition(..., "diabetes")``, and every *emit* site (FHIR Condition
  list, ``Encounter.diagnosis``, the outpatient visit's principal diagnosis,
  the narrative problem lists) resolves through this module so a patient with
  a complication is never listed with ``E11.9`` as well (Issue #3873).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

#: Depressive episode, single — subsumed by F33.
F32_CODE = "F32"

#: Recurrent depressive disorder — subsumes F32 by ICD-10-CM §F30-F39.
F33_CODE = "F33"

#: Bipolar disorder — its depressive episodes are coded under F31, so a
#: bipolar patient is not also coded with unipolar depression (Issue #2142).
F31_CODE = "F31"


def apply_depression_mutex(chronic_conditions: list[str]) -> None:
    """Drop F32 in-place when F33 is also present.

    F33 (recurrent depressive disorder) subsumes F32 (depressive
    episode, single) per ICD-10-CM §F30-F39. Call this at every site
    that appends F32 or F33 to a person's ``chronic_conditions`` list
    (initial-cohort sampler, longitudinal event dispatch).

    No-op when F33 is absent or F32 is already absent — safe to call
    unconditionally. Mutates in place; preserves the order of all other
    codes.
    """
    if F31_CODE in chronic_conditions:
        for code in (F32_CODE, F33_CODE):
            if code in chronic_conditions:
                chronic_conditions.remove(code)
        return
    if F33_CODE in chronic_conditions and F32_CODE in chronic_conditions:
        chronic_conditions.remove(F32_CODE)


#: Type 2 diabetes mellitus without complications — redundant once the
#: patient carries a complication code of the same category (Issue #3873).
E11_UNCOMPLICATED_CODE = "E11.9"

_E11_PREFIX = "E11."


def _code_of(item: Any) -> str:
    """The ICD code of a ``chronic_conditions`` entry: a string, a mapping with
    ``code`` or an object with a ``code`` attribute."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("code") or "")
    return str(getattr(item, "code", "") or "")


def is_complicated_diabetes_code(code: str) -> bool:
    """Whether ``code`` is an E11.x other than the uncomplicated ``E11.9``."""
    return code.startswith(_E11_PREFIX) and not code.startswith(E11_UNCOMPLICATED_CODE)


def redundant_uncomplicated_diabetes_indices(chronic: Sequence[Any]) -> frozenset[int]:
    """Positions of the entries of ``chronic`` that are a redundant ``E11.9``.

    Positions, not a filtered list, because FHIR Condition ids are derived
    from the entry's index in ``chronic_conditions``: a suppressed entry is
    skipped and the others keep their ids.
    """
    codes = [_code_of(c) for c in chronic]
    if not any(is_complicated_diabetes_code(c) for c in codes):
        return frozenset()
    return frozenset(i for i, c in enumerate(codes) if c.startswith(E11_UNCOMPLICATED_CODE))


def without_redundant_uncomplicated_diabetes(chronic: Sequence[Any]) -> list[Any]:
    """``chronic`` without a redundant ``E11.9`` entry (the problem lists of
    the narratives, which have no ids to keep)."""
    drop = redundant_uncomplicated_diabetes_indices(chronic)
    return [c for i, c in enumerate(chronic) if i not in drop]


def principal_code_for_problem_list(code: str, chronic: Sequence[Any]) -> str:
    """The code a visit's principal diagnosis takes: a redundant ``E11.9`` is
    replaced by the patient's first complication code, any other code is
    unchanged."""
    if code.startswith(E11_UNCOMPLICATED_CODE):
        for c in chronic:
            if is_complicated_diabetes_code(_code_of(c)):
                return _code_of(c)
    return code
