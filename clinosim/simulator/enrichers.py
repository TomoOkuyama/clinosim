"""Enricher registry (AD-56) — opt-in module passes around the core simulation.

Modules contribute a post-population or post-records pass by registering an
``Enricher`` instead of editing ``run_beta``. Enrichers run in ascending ``order``
within their stage; the order is fixed and deterministic (AD-16). Each enricher
derives its own RNG sub-stream from ``ctx.master_seed`` and must NOT touch the main
simulation random stream.

Stages:
  - ``post_population`` — runs after the population is generated, before simulation
    (mutates ``ctx.population``). Example: resident identifier / insurance numbering.
  - ``post_records``    — runs after patient records are simulated (reads/extends
    ``ctx.records``; modules write to ``CIFPatientRecord.extensions[<module>]``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

POST_POPULATION = "post_population"
POST_RECORDS = "post_records"


@dataclass
class EnricherContext:
    config: Any
    master_seed: int
    population: Any = None
    records: list[Any] = field(default_factory=list)


@dataclass
class Enricher:
    name: str
    stage: str
    run: Callable[[EnricherContext], None]
    order: int = 100
    enabled: Callable[[Any], bool] = lambda config: True


_ENRICHERS: list[Enricher] = []
_BUILTINS_REGISTERED = False


def register_enricher(enricher: Enricher) -> None:
    """Register an enricher (idempotent by name)."""
    if any(e.name == enricher.name for e in _ENRICHERS):
        return
    _ENRICHERS.append(enricher)


def run_stage(stage: str, ctx: EnricherContext) -> None:
    """Run all enabled enrichers for a stage, in deterministic (order, name) sequence."""
    for enricher in sorted(
        (e for e in _ENRICHERS if e.stage == stage),
        key=lambda e: (e.order, e.name),
    ):
        if enricher.enabled(ctx.config):
            enricher.run(ctx)


def register_builtin_enrichers() -> None:
    """Register the built-in enrichers. Add new opt-in modules here (one line each)."""
    global _BUILTINS_REGISTERED
    if _BUILTINS_REGISTERED:
        return
    _BUILTINS_REGISTERED = True

    # Resident identifier & insurance numbering (AD-54). JP-only, opt-out via config.
    from clinosim.modules.identity import assign_identities

    register_enricher(
        Enricher(
            name="identity",
            stage=POST_POPULATION,
            order=10,
            enabled=lambda c: c.country == "JP" and c.jp_insurance_numbers,
            run=lambda ctx: assign_identities(ctx.population, ctx.config.country, ctx.master_seed),
        )
    )
