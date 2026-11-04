"""``clinosim validate``: simulate a cohort and run the data-quality checks."""

from __future__ import annotations

import argparse
from typing import Any

from clinosim.simulator.cli_common import _run_quality_checks
from clinosim.simulator.engine import run_beta
from clinosim.types.config import SimulatorConfig


def register(sub: argparse._SubParsersAction) -> None:
    # === validate: run quality checks on generated data ===
    val = sub.add_parser("validate", help="Run data quality checks on generated data")
    val.add_argument("-p", "--population", type=int, default=5_000, help="Population size")
    val.add_argument("-s", "--seed", type=int, default=42, help="Random seed")
    val.add_argument("--country", default="US", help="Country code")
    val.set_defaults(handler=run)


def run(args: Any, parser: argparse.ArgumentParser) -> None:
    config = SimulatorConfig(
        catchment_population=args.population,
        random_seed=args.seed,
        country=args.country,
    )
    print(f"clinosim validate: pop={args.population}, country={args.country}")
    dataset = run_beta(config)
    _run_quality_checks(dataset)
    # Issue #2208: the rule-based consistency checks of the validator
    # module (inpatient Hb at discharge, deceased status, lab / vital
    # ranges, medication holds, LOS, sex-specific conditions).
    from clinosim.modules.validator import consistency

    report = consistency.run_consistency_checks(dataset, country=args.country)
    print(f"  {report.summary()}")
    return
