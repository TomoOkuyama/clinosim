"""Per-attribute yaml loader + `AttributeSpec` + DAG topological sort.

Loads every ``*.yaml`` under ``clinosim/locale/shared/longitudinal/``
and resolves it into an ``AttributeSpec`` keyed by ``attribute_id``.
The pattern-specific body deserialises through the pydantic model
registered in ``patterns.PATTERN_REGISTRY``. Dependency edges from
``depends_on`` go into a topological-sort that the engine consumes
per sim year — a cycle is a yaml authoring error and raises here,
not at engine runtime.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from clinosim.modules.longitudinal.patterns import PATTERN_REGISTRY
from clinosim.modules.longitudinal.patterns.ar1 import AR1Spec

_LONGITUDINAL_DIR = Path(__file__).resolve().parents[2] / "locale" / "shared" / "longitudinal"


class ClinicalScope(BaseModel):
    """Which patients the attribute runs for."""

    requires_chronic_codes: list[str] = Field(default_factory=list)
    requires_age_band: list[int] = Field(default_factory=lambda: [0, 120], min_length=2, max_length=2)


class AttributeSpec(BaseModel):
    """One longitudinal attribute's full spec (frontmatter + body)."""

    attribute_id: str
    pattern: str
    depends_on: list[str] = Field(default_factory=list)
    clinical_scope: ClinicalScope = Field(default_factory=ClinicalScope)
    body: AR1Spec


def _load_one(path: Path) -> AttributeSpec:
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if "attribute_id" not in raw:
        raise ValueError(f"{path.name}: missing required field 'attribute_id'")
    pattern = raw.get("pattern")
    if pattern not in PATTERN_REGISTRY:
        raise ValueError(f"{path.name}: unknown pattern {pattern!r} — registered patterns: {sorted(PATTERN_REGISTRY)}")
    body_cls = PATTERN_REGISTRY[pattern]["spec"]
    body_dict: dict[str, Any] = {
        k: v for k, v in raw.items() if k not in {"attribute_id", "pattern", "depends_on", "clinical_scope"}
    }
    initial = body_dict.pop("initial", {})
    clamp = body_dict.pop("clamp", None)
    noise = body_dict.pop("per_encounter_noise", None)  # read by callers, not AR1Spec
    narrative = body_dict.pop("narrative_label", None)  # same
    source = body_dict.pop("source", None)
    ar1_section = body_dict.pop("ar1", {}) or {}
    body_payload = {
        "latent_name": body_dict.pop("latent_name"),
        "phi": ar1_section.get("phi", body_dict.get("phi")),
        "sigma": ar1_section.get("sigma", body_dict.get("sigma")),
        "mean_reversion_target": ar1_section.get("mean_reversion_target", body_dict.get("mean_reversion_target")),
        "clamp": clamp,
        "initial_mu": initial.get("mu"),
        "initial_sigma": initial.get("sigma"),
        "initial_clamp": initial.get("clamp"),
    }
    body = body_cls(**body_payload)
    # Preserve the auxiliary bits as model_extra on AttributeSpec via a wrapping dict
    frontmatter = {
        "attribute_id": raw["attribute_id"],
        "pattern": pattern,
        "depends_on": raw.get("depends_on", []),
        "clinical_scope": raw.get("clinical_scope", {}),
        "body": body,
    }
    spec = AttributeSpec(**frontmatter)
    # Attach the auxiliary fields the engine / callers need.
    object.__setattr__(spec, "_per_encounter_noise", noise or {})
    object.__setattr__(spec, "_narrative_label", narrative or {})
    object.__setattr__(spec, "_source", source or [])
    return spec


@cache
def load_attribute_specs() -> dict[str, AttributeSpec]:
    """Return every registered attribute keyed by ``attribute_id``.
    lru_cached (no args) so repeated calls hit the parsed dict."""
    if not _LONGITUDINAL_DIR.exists():
        return {}
    specs: dict[str, AttributeSpec] = {}
    for path in sorted(_LONGITUDINAL_DIR.glob("*.yaml")):
        spec = _load_one(path)
        specs[spec.attribute_id] = spec
    return specs


def topological_order(specs: dict[str, AttributeSpec]) -> list[str]:
    """Kahn's algorithm. Raise ``ValueError`` on cycle or unknown
    dependency, naming the offending node(s)."""
    for aid, spec in specs.items():
        for dep in spec.depends_on:
            if dep not in specs:
                raise ValueError(f"attribute {aid!r}: unknown dependency {dep!r}")
    in_degree: dict[str, int] = {aid: 0 for aid in specs}
    for aid, spec in specs.items():
        for dep in spec.depends_on:
            in_degree[aid] += 1
    order: list[str] = []
    frontier = [aid for aid, deg in in_degree.items() if deg == 0]
    while frontier:
        frontier.sort()  # deterministic order among ties
        current = frontier.pop(0)
        order.append(current)
        for aid, spec in specs.items():
            if current in spec.depends_on:
                in_degree[aid] -= 1
                if in_degree[aid] == 0:
                    frontier.append(aid)
    if len(order) < len(specs):
        unresolved = [aid for aid in specs if aid not in order]
        raise ValueError(f"dependency cycle detected among attributes: {sorted(unresolved)}")
    return order
