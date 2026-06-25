"""clinosim audit CLI subcommand wiring (called from
clinosim/simulator/cli.py).

Subcommands:
  run    Full audit (default axes + all registered modules)
  smoke  silent_no_op axis only, intended for CI plumbing
  list   Print discovered modules + their available checks
"""
from __future__ import annotations

import argparse
from pathlib import Path

from clinosim.audit.engine import AuditEngine
from clinosim.audit.registry import discover, get_registered
from clinosim.audit.reporter import render_markdown, write_markdown


def add_audit_subparser(subparsers: argparse._SubParsersAction) -> None:
    audit = subparsers.add_parser("audit", help="Verification framework")
    audit_sub = audit.add_subparsers(dest="audit_command")

    run_p = audit_sub.add_parser(
        "run", help="Run the audit framework over a generated cohort",
    )
    run_p.add_argument("-d", "--cohort-dir", required=True, type=Path)
    run_p.add_argument("--module", action="append", default=None)
    run_p.add_argument("--axis", action="append", default=None)
    run_p.add_argument("--report", type=Path, default=None)

    smoke = audit_sub.add_parser(
        "smoke", help="Fast plumbing check — silent_no_op only",
    )
    smoke.add_argument("-d", "--cohort-dir", required=True, type=Path)

    audit_sub.add_parser("list", help="List registered modules + checks")


def _dispatch_run(args) -> int:
    engine = AuditEngine(
        cohort_dir=args.cohort_dir,
        modules=args.module,
        axes=args.axis,
    )
    result = engine.run()
    print(render_markdown(result))
    if args.report:
        write_markdown(result, args.report)
        print(f"\n[wrote {args.report}]")
    return 0 if result.overall_status() != "FAIL" else 1


def _dispatch_smoke(args) -> int:
    engine = AuditEngine(cohort_dir=args.cohort_dir, axes=["silent_no_op"])
    result = engine.run()
    print(render_markdown(result))
    return 0 if result.overall_status() != "FAIL" else 1


def _dispatch_list(_args) -> int:
    discover()
    registered = get_registered()
    if not registered:
        print("(no modules with audit.py registered)")
        return 0
    print(f"Registered modules: {len(registered)}")
    for name, spec in sorted(registered.items()):
        checks: list[str] = []
        if spec.structural_obs_codes:
            checks.append(f"structural ({len(spec.structural_obs_codes)} analytes)")
        if spec.clinical_acceptance:
            checks.append(f"clinical ({len(spec.clinical_acceptance)} cohorts)")
        if spec.lift_firing_proof is not None:
            checks.append("lift-firing proof")
        if spec.yaml_keys_to_validate:
            checks.append(f"constants ({len(spec.yaml_keys_to_validate)} files)")
        print(f"  {name}: {', '.join(checks) or 'no checks declared'}")
    return 0


def dispatch_audit(args) -> int:
    cmd = getattr(args, "audit_command", None)
    if cmd == "run":
        return _dispatch_run(args)
    if cmd == "smoke":
        return _dispatch_smoke(args)
    if cmd == "list":
        return _dispatch_list(args)
    print("usage: clinosim audit {run,smoke,list} [...]")
    return 2
