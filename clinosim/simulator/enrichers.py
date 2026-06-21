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

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

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


_ENRICHERS: dict[str, Enricher] = {}
_BUILTINS_REGISTERED = False


def register_enricher(enricher: Enricher) -> None:
    """Register an enricher by name. Last registration wins (enables test override);
    re-registering an existing name logs a warning."""
    if enricher.name in _ENRICHERS:
        logger.warning("Enricher %r re-registered — last-wins override", enricher.name)
    _ENRICHERS[enricher.name] = enricher


def run_stage(stage: str, ctx: EnricherContext) -> None:
    """Run all enabled enrichers for a stage, in deterministic (order, name) sequence."""
    for enricher in sorted(
        (e for e in _ENRICHERS.values() if e.stage == stage),
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

    # Nursing flowsheet (AD-55 Base): NEWS2/GCS + Braden/Morse. Always-on.
    from clinosim.modules.observation.nursing_enricher import enrich_nursing

    register_enricher(
        Enricher(
            name="nursing",
            stage=POST_RECORDS,
            order=20,
            enabled=lambda c: True,
            run=enrich_nursing,
        )
    )

    # Immunization history (AD-55 Base): adult vaccine history. Always-on.
    from clinosim.modules.immunization.enricher import enrich_immunizations

    register_enricher(
        Enricher(
            name="immunization",
            stage=POST_RECORDS,
            order=30,
            enabled=lambda c: True,
            run=enrich_immunizations,
        )
    )

    # Family history (AD-55 Base): first-degree relative disease history. Always-on.
    from clinosim.modules.family_history.enricher import enrich_family_history

    register_enricher(
        Enricher(
            name="family_history",
            stage=POST_RECORDS,
            order=40,
            enabled=lambda c: True,
            run=enrich_family_history,
        )
    )

    # Code status (AD-55 Base): resuscitation status on serious encounters. Always-on.
    from clinosim.modules.code_status.enricher import enrich_code_status

    register_enricher(
        Enricher(
            name="code_status",
            stage=POST_RECORDS,
            order=50,
            enabled=lambda c: True,
            run=enrich_code_status,
        )
    )
