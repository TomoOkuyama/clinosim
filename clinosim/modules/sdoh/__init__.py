"""SDOH (social determinants of health) module — AD-55 Base.

Currently scopes social-history attributes that the simulator populates
on PatientProfile during activation: smoking_status (US Core LOINC
72166-2 + SNOMED) and alcohol_use (LOINC 11331-6 + SNOMED).

Data-only module variant (see CONTRIBUTING-modules.md): engine.py
provides a loader for reference data; assignment logic lives in the
patient activator (smoking/alcohol are demographics-driven attributes,
not post-records enrichment).

Future SDOH expansions (occupation, education, housing status, food
insecurity, etc.) should slot in here — add a topic to
reference_data/social_history.yaml or a new reference_data/<topic>.yaml
file. Builders that consume the data live in clinosim/modules/output/.
"""

from clinosim.modules.sdoh.engine import load_social_history

__all__ = ["load_social_history"]
