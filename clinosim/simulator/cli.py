"""CLI entry point for clinosim.

Each subcommand lives in its own ``cli_<command>.py`` module with a
``register(subparsers)`` that defines its parser and sets ``handler``;
``main`` builds the parser in help order and dispatches (Issue #2534). The
audit / dataset / eval / benchmark commands are defined by their packages.
"""

from __future__ import annotations

import argparse
import sys

from clinosim.simulator import (
    cli_diff,
    cli_enumerate,
    cli_export_fhir,
    cli_list_diseases,
    cli_narrate,
    cli_regenerate,
    cli_simulate,
    cli_test_disease,
    cli_test_encounter,
    cli_validate,
)

__all__ = ["main"]


def main() -> None:
    """CLI entry point: clinosim [command] [options]"""
    parser = argparse.ArgumentParser(
        prog="clinosim",
        description="Clinically Realistic Hospital Data Simulator",
    )
    sub = parser.add_subparsers(dest="command", help="Command to run")

    # Registration order is the order of `clinosim --help`.
    cli_simulate.register(sub)
    cli_test_disease.register(sub)
    cli_validate.register(sub)
    cli_list_diseases.register(sub)
    cli_narrate.register_narrate(sub)
    cli_export_fhir.register(sub)
    cli_test_encounter.register(sub)
    cli_enumerate.register(sub)
    cli_diff.register(sub)
    cli_regenerate.register(sub)
    cli_narrate.register_check_narratives(sub)

    from clinosim.audit.cli import add_audit_subparser, dispatch_audit
    from clinosim.benchmarks.cli import add_benchmark_subparser, dispatch_benchmark
    from clinosim.dataset import add_dataset_subparser, dispatch_dataset
    from clinosim.eval import add_eval_subparser, dispatch_eval

    add_audit_subparser(sub)  # verification framework
    add_dataset_subparser(sub)  # named-preset dataset builder
    add_eval_subparser(sub)  # public 3-axis evaluation framework
    add_benchmark_subparser(sub)  # P2-15 prediction benchmark harness
    package_dispatch = {
        "audit": dispatch_audit,
        "dataset": dispatch_dataset,
        "eval": dispatch_eval,
        "benchmark": dispatch_benchmark,
    }

    args = parser.parse_args()
    if args.command in package_dispatch:
        sys.exit(package_dispatch[args.command](args))
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return
    handler(args, parser)


if __name__ == "__main__":
    main()
