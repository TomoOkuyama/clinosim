"""Enricher registry (AD-56) — opt-in module passes around the core simulation.

Modules contribute a post-population or post-records pass by registering an
``Enricher`` instead of editing ``run_beta``. Enrichers run in ascending ``order``
within their stage; the order is fixed and deterministic (AD-16). Each enricher
derives its own RNG sub-stream from ``ctx.master_seed`` and must NOT touch the main
simulation random stream.

Stages:
  - ``post_population`` — runs after the population is generated, before simulation
    (mutates ``ctx.population``). Example: resident identifier / insurance numbering.
  - ``post_encounter`` — runs **per encounter, immediately after the daily loop
    completes** but **inside** the encounter simulator (before the final
    ``CIFPatientRecord`` is returned to the global ``patient_records`` list).
    The encounter's complete clinical course (lab_results, vital_signs, ICU
    transfer flag, full state history) is available, but no other patient's
    records are. Phase 3a (2026-06-25) uses this stage for the encounter-bound
    Module pair device/hai whose probabilistic sampling depends on the
    encounter's icu_transferred + state and whose output (HAI events) the
    physiology layer post-applies as a forward delta to existing WBC + CRP
    lab values (via state-history-derived recompute). ``EnricherContext.records``
    is passed with **exactly one** partial ``CIFPatientRecord`` for the
    encounter being generated.
  - ``post_records``    — runs after **all** patient records are simulated
    (reads/extends ``ctx.records``; modules write to
    ``CIFPatientRecord.extensions[<module>]``). Use for cross-record Modules
    (immunization / family_history / code_status / care_level / sdoh) and Base
    enrichers (nursing).

Module classification:
  - **encounter-bound Module** (device, hai): runs in ``POST_ENCOUNTER`` so
    physiology layer's ``derive_lab_values`` can consume the output at
    observation time.
  - **cross-record Module** (immunization, family_history, code_status,
    care_level): runs in ``POST_RECORDS`` after the full patient timeline
    is built (these read patient-wide history, not single-encounter context).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

POST_POPULATION = "post_population"
POST_ENCOUNTER = "post_encounter"
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

    # JP 要介護度 (AD-55 Base): long-term-care need level. JP only.
    from clinosim.modules.care_level.enricher import enrich_care_level

    register_enricher(
        Enricher(
            name="care_level",
            stage=POST_RECORDS,
            order=60,
            enabled=lambda c: getattr(c, "country", "US") == "JP",
            run=enrich_care_level,
        )
    )

    # ICU device placement (AD-55 Module, PR-A): CVC + indwelling catheter +
    # ventilator on inpatient encounters where the patient transferred to ICU.
    # Phase 2 hai enricher will consume extensions["device"]. Always-on.
    from clinosim.modules.device.enricher import enrich_device

    register_enricher(
        Enricher(
            name="device",
            stage=POST_ENCOUNTER,
            order=70,
            enabled=lambda c: True,
            run=enrich_device,
        )
    )

    # Hospital-acquired infection (AD-55 Module, PR-B): CLABSI/CAUTI/VAP
    # onset sampling from PR-A device line-days using CDC NHSN baseline
    # per-line-day risk rates. Reads extensions["device"], writes
    # extensions["hai"] + appends MicrobiologyResult to record.microbiology
    # (existing _fhir_microbiology.py emits the culture chain). Always-on.
    # Order 80 ensures hai runs AFTER device (70) so extensions["device"]
    # is populated by the time hai walks it.
    from clinosim.modules.hai.enricher import enrich_hai

    register_enricher(
        Enricher(
            name="hai",
            stage=POST_ENCOUNTER,
            order=80,
            enabled=lambda c: True,
            run=enrich_hai,
        )
    )

    # Empirical antibiotic regimen for HAI events (AD-55 always-on
    # Module = near-essential clinical cascade, PR3b-1). Consumes
    # extensions["hai"] (PR-B output); HAI 不在時は no-op. Order 85
    # ensures it runs AFTER hai (80) so extensions["hai"] is populated.
    from clinosim.modules.antibiotic.enricher import enrich_antibiotic

    register_enricher(
        Enricher(
            name="antibiotic",
            stage=POST_ENCOUNTER,
            order=85,
            enabled=lambda c: True,
            run=enrich_antibiotic,
        )
    )

    # Imaging study enricher (Tier 1 #2, AD-55 always-on Module). Consumes
    # Order(IMAGING) from record.orders; skips CANCELLED. Writes
    # extensions["imaging"] = list[ImagingStudyRecord]. Order 90 ensures
    # it runs after antibiotic (85) — imaging is independent of HAI cascade
    # but runs last in the POST_ENCOUNTER stage to avoid interfering with
    # WBC/CRP lab-lift logic.
    from clinosim.modules.imaging.engine import imaging_enricher

    register_enricher(
        Enricher(
            name="imaging",
            stage=POST_ENCOUNTER,
            order=90,
            enabled=lambda c: True,
            run=imaging_enricher,
        )
    )
