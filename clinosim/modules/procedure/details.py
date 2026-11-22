"""Site details of a procedure (Issue #3549).

The side of a paired-site operation, the access site and target vessel of a
PCI and the insertion vein of a central line, chosen once per (encounter,
procedure type) from ``reference_data/procedure_details.yaml``. Every choice
is deterministic and independent of the encounter's shared RNG: the stay's
canonical side where one exists (stroke lesion side, the side the stay's
imaging uses), else a draw from the dedicated sub-seed
``seeding.procedure_detail_seed`` — so recording a site moves no other draw.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from clinosim import determinism
from clinosim.codes.snomed import snomed_map
from clinosim.datafiles import load_data_yaml
from clinosim.seeding import procedure_detail_seed

__all__ = ["ProcedureDetails", "procedure_details"]

_FILE = Path(__file__).resolve().parent / "reference_data" / "procedure_details.yaml"

#: Option groups a type may draw, each the key of a ``snomed-maps.yaml`` map.
_OPTION_MAPS = ("target_vessel", "access_site", "central_vein")
_MAP_OF = {"target_vessel": "coronary_vessel", "access_site": "arterial_access_site", "central_vein": "central_vein"}


def _check_weights(weights: dict[str, float], what: str) -> dict[str, float]:
    if not weights or any(w <= 0 for w in weights.values()):
        raise ValueError(f"procedure_details.yaml: {what} needs positive weights")
    return weights


class _SideRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["lesion", "imaging", "draw"]
    imaging_site: str = ""
    imaging_diseases: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _imaging_needs_site(self) -> _SideRule:
        if self.source == "imaging" and not self.imaging_site:
            raise ValueError("procedure_details.yaml: an imaging side rule needs imaging_site")
        return self


class _Laterality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sides: dict[str, float]
    types: dict[str, _SideRule]

    @field_validator("sides")
    @classmethod
    def _sides(cls, sides: dict[str, float]) -> dict[str, float]:
        if set(sides) != {"left", "right"}:
            raise ValueError("procedure_details.yaml: laterality.sides must be left and right")
        return _check_weights(sides, "laterality.sides")


class _TypeDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_vessel: dict[str, float] = Field(default_factory=dict)
    access_site: dict[str, float] = Field(default_factory=dict)
    central_vein: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _known_keys(self) -> _TypeDetails:
        for group in _OPTION_MAPS:
            options = getattr(self, group)
            if not options:
                continue
            _check_weights(options, group)
            known = snomed_map(_MAP_OF[group])
            unknown = sorted(set(options) - set(known))
            if unknown:
                raise ValueError(
                    f"procedure_details.yaml: {group} keys {unknown} are not in snomed-maps {_MAP_OF[group]}"
                )
        return self


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    laterality: _Laterality
    details: dict[str, _TypeDetails]


@cache
def _config() -> _Config:
    return _Config.model_validate(load_data_yaml(_FILE))


@dataclass(frozen=True)
class ProcedureDetails:
    """The recorded site details of one procedure; ``""`` is "not applicable"."""

    laterality: str = ""  # "left" | "right"
    access_site: str = ""  # SNOMED CT code of the arterial access site
    target_vessel: str = ""  # SNOMED CT code of the treated coronary artery
    body_site_code: str = ""  # SNOMED CT code replacing the type-level body site (central-line vein)


def _weighted_key(rng: Any, weights: dict[str, float]) -> str:
    keys = list(weights)
    total = float(sum(weights.values()))
    cum = 0.0
    u = float(rng.random()) * total
    for key in keys:
        cum += weights[key]
        if u < cum:
            return key
    return keys[-1]


def _side(proc_type: str, encounter_id: str, disease_id: str, rng: Any) -> str:
    cfg = _config().laterality
    rule = cfg.types.get(proc_type)
    if rule is None:
        return ""
    if rule.source == "lesion":
        from clinosim.modules.disease.laterality import stroke_lesion_side
        from clinosim.modules.document.reference_data_loaders import load_disease_exam

        if disease_id in load_disease_exam().stroke.disease_ids:
            return stroke_lesion_side(encounter_id)
    elif rule.source == "imaging" and (not rule.imaging_diseases or disease_id in rule.imaging_diseases):
        from clinosim.modules.imaging.engine import imaging_laterality

        side = imaging_laterality(encounter_id, rule.imaging_site)
        if side:
            return side
    # ``draw``, and the fallback of the other sources when they give no side.
    return _weighted_key(rng, cfg.sides)


def procedure_details(proc_type: str, encounter_id: str, disease_id: str = "") -> ProcedureDetails:
    """The site details of ``proc_type`` performed in ``encounter_id`` for
    ``disease_id``. A type with no configured detail returns the empty value.
    Draws only from the sub-RNG ``procedure_detail_seed(encounter_id,
    proc_type)`` and always in the same order (side, then options), so one
    detail never shifts another."""
    cfg = _config()
    typed = cfg.details.get(proc_type)
    if proc_type not in cfg.laterality.types and typed is None:
        return ProcedureDetails()
    rng = determinism.default_rng(procedure_detail_seed(encounter_id, proc_type))
    side = _side(proc_type, encounter_id, disease_id, rng)
    vessel = access = site = ""
    if typed is not None:
        if typed.target_vessel:
            vessel = snomed_map("coronary_vessel")[_weighted_key(rng, typed.target_vessel)]
        if typed.access_site:
            access = snomed_map("arterial_access_site")[_weighted_key(rng, typed.access_site)]
        if typed.central_vein:
            site = snomed_map("central_vein")[_weighted_key(rng, typed.central_vein)]
    return ProcedureDetails(
        laterality=side if side in ("left", "right") else "",
        access_site=access,
        target_vessel=vessel,
        body_site_code=site,
    )
