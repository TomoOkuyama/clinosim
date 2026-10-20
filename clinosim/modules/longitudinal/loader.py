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
from clinosim.modules.longitudinal.patterns.markov import MarkovSpec

_LONGITUDINAL_DIR = Path(__file__).resolve().parents[2] / "locale" / "shared" / "longitudinal"


# Review-pass I3: patterns the engine's _apply_pattern actually
# dispatches. A pattern registered in PATTERN_REGISTRY but not here
# is a half-wired state — loader fails fast at import rather than
# letting advance_one_year raise NotImplementedError inside the sim.
_IMPLEMENTED_PATTERNS: frozenset[str] = frozenset({"ar1", "markov"})


class ClinicalScope(BaseModel):
    """Which patients the attribute runs for."""

    requires_chronic_codes: list[str] = Field(default_factory=list)
    requires_age_band: list[int] = Field(default_factory=lambda: [0, 120], min_length=2, max_length=2)


class AttributeSpec(BaseModel):
    """One longitudinal attribute's full spec (frontmatter + body)."""

    model_config = {"arbitrary_types_allowed": True}

    attribute_id: str
    pattern: str
    depends_on: list[str] = Field(default_factory=list)
    clinical_scope: ClinicalScope = Field(default_factory=ClinicalScope)
    body: AR1Spec | MarkovSpec


def _build_ar1_body(body_dict: dict[str, Any]) -> tuple[AR1Spec, dict[str, Any]]:
    """Build an AR1Spec from the AR1-shaped body dict + return the
    auxiliary fields (noise, narrative, source) the caller re-attaches."""
    initial = body_dict.pop("initial", {})
    clamp = body_dict.pop("clamp", None)
    noise = body_dict.pop("per_encounter_noise", None)
    narrative = body_dict.pop("narrative_label", None)
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
    return AR1Spec(**body_payload), {"noise": noise, "narrative": narrative, "source": source}


def _build_markov_body(body_dict: dict[str, Any]) -> tuple[MarkovSpec, dict[str, Any]]:
    """Build a MarkovSpec. Pulls out narrative_label + source for the
    engine's auxiliary attachment; everything else is MarkovSpec input."""
    narrative = body_dict.pop("narrative_label", None)
    source = body_dict.pop("source", None)
    body_payload = {
        "state_name": body_dict.pop("state_name"),
        "icd_base": body_dict.pop("icd_base"),
        "states": body_dict.pop("states"),
        "initial_distribution": body_dict.pop("initial_distribution"),
        "transitions": body_dict.pop("transitions", {}) or {},
    }
    return MarkovSpec(**body_payload), {"noise": None, "narrative": narrative, "source": source}


def _load_one(path: Path) -> AttributeSpec:
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if "attribute_id" not in raw:
        raise ValueError(f"{path.name}: missing required field 'attribute_id'")
    pattern = raw.get("pattern")
    if pattern not in PATTERN_REGISTRY:
        raise ValueError(f"{path.name}: unknown pattern {pattern!r} — registered patterns: {sorted(PATTERN_REGISTRY)}")
    if pattern not in _IMPLEMENTED_PATTERNS:
        raise ValueError(
            f"{path.name}: pattern {pattern!r} is registered but not implemented in "
            f"longitudinal.engine._apply_pattern — implemented: {sorted(_IMPLEMENTED_PATTERNS)}"
        )
    body_dict: dict[str, Any] = {
        k: v for k, v in raw.items() if k not in {"attribute_id", "pattern", "depends_on", "clinical_scope"}
    }
    if pattern == "ar1":
        body, aux = _build_ar1_body(body_dict)
    elif pattern == "markov":
        body, aux = _build_markov_body(body_dict)
    else:  # pragma: no cover — guarded by _IMPLEMENTED_PATTERNS
        raise ValueError(f"{path.name}: unhandled pattern {pattern!r} in _load_one dispatch")
    noise = aux["noise"]
    narrative = aux["narrative"]
    source = aux["source"]
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
    for path in sorted(_LONGITUDINAL_DIR.rglob("*.yaml")):
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
