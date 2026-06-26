"""SDOH reference data loader (AD-55 Base, data-only module variant).

No assignment / generation logic — smoking_status and alcohol_use are
demographics-driven attributes set on PatientProfile during activation
(see patient/activator.py + locale/{us,jp}/demographics.yaml). This
module only provides the enum→SNOMED + LOINC reference data needed by
FHIR builders.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"


@lru_cache(maxsize=1)
def load_social_history() -> dict:
    """Load SDOH social-history reference data.

    Returns a dict keyed by SDOH topic (currently ``smoking_status`` and
    ``alcohol_use``). Each topic value is a dict with:

      - ``loinc`` (str): US Core LOINC code for the Observation
      - ``category`` (str): FHIR Observation.category code (typically
        ``"social-history"``)
      - ``values`` (dict): enum key → ``{"snomed": "<code>"}`` mapping

    Display strings are NOT in this YAML — resolved at FHIR output time
    via ``clinosim.codes.lookup("snomed-ct", code, lang)``.
    """
    with open(_REF_DIR / "social_history.yaml") as f:
        return yaml.safe_load(f) or {}
