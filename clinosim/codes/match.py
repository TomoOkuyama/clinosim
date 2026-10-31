"""Shared chronic-code / ICD-prefix matching helpers.

Multiple call sites across the simulator check whether a patient's
chronic-condition set contains any code starting with a given ICD-10
prefix (e.g. "E11" for Type 2 DM, "E78" for dyslipidemia, "I10" for
essential hypertension). Historically each caller re-expressed the
check inline, producing both duplication and drift (some callers
indexed by ``.code`` attribute on a ``ChronicCondition``, others
operated on a plain ``list[str]`` of codes, and a handful mixed the
two).

The implementation now lives in :mod:`clinosim.codes.valuesets`
(Issue #2280); this module re-exports it for existing callers.
"""

from __future__ import annotations

from clinosim.codes.valuesets import has_icd_prefix

__all__ = ["has_icd_prefix"]
