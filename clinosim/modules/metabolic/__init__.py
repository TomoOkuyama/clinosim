"""Metabolic module (Issue #1137 cluster 2).

BMI-derived chronic conditions (E66 obesity sub-codes) and metabolic
syndrome derivation (E88.81) land here, split out of the shared
``demographics.yaml:chronic_prevalence`` sampling path so a
Bernoulli draw is never involved in deriving a condition that is a
deterministic function of ``PersonRecord.bmi``.
"""

from clinosim.modules.metabolic.engine import e66_bmi_enricher

__all__ = ["e66_bmi_enricher"]
