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
* **F32 vs F33** (``apply_depression_mutex``) — per ICD-10-CM §F30-F39,
  ``F33`` (recurrent depressive disorder) subsumes ``F32`` (depressive
  episode, single). Once a patient becomes F33, F32 must no longer be
  present on the problem list.
"""

from __future__ import annotations

#: Depressive episode, single — subsumed by F33.
F32_CODE = "F32"

#: Recurrent depressive disorder — subsumes F32 by ICD-10-CM §F30-F39.
F33_CODE = "F33"


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
    if F33_CODE in chronic_conditions and F32_CODE in chronic_conditions:
        chronic_conditions.remove(F32_CODE)
