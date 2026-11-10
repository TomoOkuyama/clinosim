"""JP-CLINS lab coding (``lab_coding`` "jp_clins", Issue #3144).

An analyte JP-CLINS slices (``_ANALYTE_TO_SLICE_NAME``) is coded CoreLabo
JLAC10; any other — known-uncoded or unrecognised — takes the Uncoded slice
(safe fallback; the completeness unit test guards against silent takedowns of
known analytes). The strategies themselves are in
``clinosim/modules/output/fhir_r4/labs/coding_strategy.py``.
"""

from __future__ import annotations

from clinosim.country_profile import register_implementation
from clinosim.modules.output.fhir_r4.labs.coding_strategy import _ANALYTE_TO_SLICE_NAME, LabCodingKind


@register_implementation("lab_coding", "jp_clins")
def jp_clins_lab_coding(lab_name: str) -> LabCodingKind:
    """``CORELABO_JLAC10`` for a sliced analyte, else ``UNCODED``."""
    if lab_name in _ANALYTE_TO_SLICE_NAME:
        return LabCodingKind.CORELABO_JLAC10
    return LabCodingKind.UNCODED
