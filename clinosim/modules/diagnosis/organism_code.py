"""The organism-specific code of a pneumonia stay follows an isolate (Issue #3645).

The discharge diagnosis walked from the diagnostic confidence is non-specific
(``J18.x``); a stay whose cultures grew a pneumonia pathogen is coded to it
(``J13`` pneumococcus, ``J14`` Haemophilus influenzae, ``J15.x``). The rule is
``reference_data/organism_pneumonia_codes.yaml``. Draws nothing.
"""

from __future__ import annotations

import functools
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from clinosim.datafiles import load_data_yaml
from clinosim.types.microbiology import MicrobiologyResult


class OrganismPneumoniaRules(BaseModel):
    """Schema of ``reference_data/organism_pneumonia_codes.yaml`` (Issue #3645)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    disease_ids: tuple[str, ...] = Field(min_length=1)
    refines: tuple[str, ...] = Field(min_length=1)
    specimens: tuple[str, ...] = Field(min_length=1)
    organisms: dict[str, str] = Field(min_length=1)


@functools.cache
def organism_pneumonia_rules() -> OrganismPneumoniaRules:
    """The validated organism-code rules."""
    return OrganismPneumoniaRules.model_validate(
        load_data_yaml(Path(__file__).resolve().parent / "reference_data" / "organism_pneumonia_codes.yaml")
    )


def isolate_refined_code(disease_id: str, code: str, microbiology: Iterable[MicrobiologyResult]) -> str:
    """``code`` refined to the organism of the stay's first positive culture
    (sputum before blood, then by collection time) when ``code`` is a
    non-specific pneumonia code of ``disease_id`` and the organism has a code;
    otherwise ``code`` unchanged."""
    rules = organism_pneumonia_rules()
    if disease_id not in rules.disease_ids or code not in rules.refines:
        return code
    order = {spec: i for i, spec in enumerate(rules.specimens)}
    positive = sorted(
        (m for m in microbiology if m.growth and m.specimen in order and m.organism_snomed in rules.organisms),
        key=lambda m: (order[m.specimen], m.collected_datetime or datetime.max),
    )
    return rules.organisms[positive[0].organism_snomed] if positive else code
