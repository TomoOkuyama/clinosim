"""The organism-specific code of an infection stay follows an isolate.

Pneumonia (Issue #3645): the discharge diagnosis walked from the diagnostic
confidence is non-specific (``J18.x``); a stay whose cultures grew a pneumonia
pathogen is coded to it (``J13`` pneumococcus, ``J14`` Haemophilus influenzae,
``J15.x``). Sepsis (Issue #3833): ``A41.9`` (unspecified organism) is refined
to the organism of the stay's blood culture (``A40.3``, ``A41.x``). The rules
are ``reference_data/organism_pneumonia_codes.yaml`` and
``reference_data/organism_sepsis_codes.yaml``. Draws nothing.
"""

from __future__ import annotations

import functools
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from clinosim.datafiles import load_data_yaml
from clinosim.types.microbiology import MicrobiologyResult


class SusceptibilitySplit(BaseModel):
    """One organism whose code depends on a susceptibility marker (Issue #3833):
    ``susceptible`` when the isolate tests S for ``marker_antibiotic`` (a key of
    ``antibiotics`` in microbiology.yaml), ``resistant`` when it tests R; an
    isolate with no S or R result for the marker keeps the non-specific code."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    marker_antibiotic: str = Field(min_length=1)
    susceptible: str = Field(min_length=1)
    resistant: str = Field(min_length=1)


class OrganismCodeRules(BaseModel):
    """Schema of ``reference_data/organism_{pneumonia,sepsis}_codes.yaml``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    disease_ids: tuple[str, ...] = Field(min_length=1)
    refines: tuple[str, ...] = Field(min_length=1)
    specimens: tuple[str, ...] = Field(min_length=1)
    organisms: dict[str, str] = Field(min_length=1)
    susceptibility_splits: dict[str, SusceptibilitySplit] = Field(default_factory=dict)


_REFERENCE_DIR = Path(__file__).resolve().parent / "reference_data"


@functools.cache
def organism_pneumonia_rules() -> OrganismCodeRules:
    """The validated pneumonia organism-code rules."""
    return OrganismCodeRules.model_validate(load_data_yaml(_REFERENCE_DIR / "organism_pneumonia_codes.yaml"))


@functools.cache
def organism_sepsis_rules() -> OrganismCodeRules:
    """The validated sepsis organism-code rules (Issue #3833)."""
    return OrganismCodeRules.model_validate(load_data_yaml(_REFERENCE_DIR / "organism_sepsis_codes.yaml"))


def _organism_code(rules: OrganismCodeRules, isolate: MicrobiologyResult) -> str:
    """The code of ``isolate`` under ``rules`` (``""`` when it has none)."""
    split = rules.susceptibility_splits.get(isolate.organism_snomed)
    if split is not None:
        from clinosim.modules.observation.microbiology import antibiotic_loinc_lookup

        marker = antibiotic_loinc_lookup().get(split.marker_antibiotic)
        results = {s.interpretation for s in isolate.susceptibilities if s.antibiotic_loinc == marker}
        if "R" in results:
            return split.resistant
        return split.susceptible if "S" in results else ""
    return rules.organisms.get(isolate.organism_snomed, "")


def isolate_refined_code(disease_id: str, code: str, microbiology: Iterable[MicrobiologyResult]) -> str:
    """``code`` refined to the organism of the stay's first positive culture
    (specimens in the rules' order, then by collection time) when ``code`` is a
    non-specific code of ``disease_id`` (pneumonia, sepsis) and the organism
    has a code; otherwise ``code`` unchanged."""
    for rules in (organism_pneumonia_rules(), organism_sepsis_rules()):
        if disease_id not in rules.disease_ids or code not in rules.refines:
            continue
        order = {spec: i for i, spec in enumerate(rules.specimens)}
        positive = sorted(
            (m for m in microbiology if m.growth and m.specimen in order and _organism_code(rules, m)),
            key=lambda m: (order[m.specimen], m.collected_datetime or datetime.max),
        )
        return _organism_code(rules, positive[0]) if positive else code
    return code
