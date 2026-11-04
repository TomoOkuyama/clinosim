"""``clinosim simulate`` (alias ``generate``): population-driven simulation
and its output pipeline (CIF, template narratives, format exports)."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Any

from clinosim.modules._shared import is_jp
from clinosim.simulator.cli_common import _print_summary, _run_exports, _validate_formats
from clinosim.simulator.engine import run_beta
from clinosim.types.config import SimulatorConfig


def _enforce_jp_clins_pkg_gate(allow_legacy: bool) -> None:
    """Fail-loud when JP-CLINS package is not detected (Issue #418).

    Called at CLI entry for `--country JP`. Prior behavior silently degraded
    to legacy 5-digit JLAC10 OIDs without any signal — the axis surfaced
    Outcome.NA but the generator itself produced non-compliant output
    invisibly. Post-#418: exit 2 unless the caller explicitly opts into the
    legacy fallback via `--allow-legacy` (option C from the Issue body).

    Env var override `CLINOSIM_ALLOW_LEGACY_JP_CLINS_PKG=1` has the same
    effect as `--allow-legacy` — meant for CI test harnesses and shell
    scripts (`scripts/reproduce.sh`) that deliberately run in a pkg-less
    environment for byte-diff / cohort verification rather than JP-CLINS
    compliance. Product code should NOT set this env var — it defeats
    the fail-loud silent-harm protection Issue #418 tracks.

    Import is inside the function so non-JP runs never pay the lookup cost
    and so the test suite can monkeypatch the loader cleanly.
    """
    from clinosim.modules.output.fhir_r4.labs.coding_package import load_lab_coding_package

    pkg = load_lab_coding_package()
    if pkg.is_available():
        return
    if os.environ.get("CLINOSIM_ALLOW_LEGACY_JP_CLINS_PKG") == "1":
        allow_legacy = True
    if not allow_legacy:
        print(
            "ERROR: JP-CLINS package not detected. `clinosim simulate --country JP`\n"
            "requires either:\n"
            "  - `fhir install clinical-information-sharing 1.13.0` (+ jpfhir-terminology 2.2606.0), OR\n"
            "  - set $CLINOSIM_JP_CLINS_PKG_DIR to the pkg's `package/` directory.\n"
            "Without the package, output would fall back to legacy 5-digit JLAC10 OIDs\n"
            "(non-JP-CLINS eCS compliant) with no signal to downstream consumers.\n"
            "Pass `--allow-legacy` to acknowledge non-compliant output and continue.",
            file=sys.stderr,
        )
        sys.exit(2)
    print(
        "WARN: JP-CLINS package not detected — --allow-legacy was passed, so\n"
        "  the run will continue with legacy 5-digit JLAC10 OID output.\n"
        "  Output will NOT be JP-CLINS eCS compliant. Downstream validators\n"
        "  (jp_clins_lab_compliance axis) will surface Outcome.NA rather than PASS.",
        file=sys.stderr,
    )


def register(sub: argparse._SubParsersAction) -> None:
    # === simulate: population-driven simulation ===
    # The original command name was "generate"; the canonical command is
    # now "simulate", reflecting that this is a physiology-driven simulator
    # rather than a random generator. "generate" is kept as a deprecation
    # alias. A deprecation warning is emitted on stderr only when the
    # alias is invoked (checked in run() via sys.argv).
    gen = sub.add_parser(
        "simulate",
        aliases=["generate"],
        help="Simulate patient data from population + physiology (alias: generate — deprecated)",
    )
    gen.add_argument("-o", "--output", default="./output", help="Output directory")
    gen.add_argument(
        "-p",
        "--population",
        type=int,
        default=argparse.SUPPRESS,
        help="Catchment population (default: hospital recommended)",
    )
    gen.add_argument("-s", "--seed", type=int, default=42, help="Random seed")
    gen.add_argument("--country", default="US", help="Country code (US or JP)")
    gen.add_argument(
        "--start",
        default=None,
        help="Simulation start date YYYY-MM-DD (default: 1 year before --end)",
    )
    gen.add_argument(
        "--end",
        default=None,
        help="Simulation end date / snapshot date YYYY-MM-DD (default: today). Inpatients still admitted on this date have no discharge.",  # noqa: E501
    )
    gen.add_argument(
        "--format",
        nargs="+",
        default=["cif"],
        help="Output formats: cif, csv, fhir-r4 (alias: fhir). Add more by registering an OutputAdapter (AD-58).",
    )
    gen.add_argument(
        "--hospital-config",
        default=None,
        help="Hospital operations YAML (default: config/hospital_operations.yaml)",
    )
    gen.add_argument(
        "--jp-insurance",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="(JP only) Include Japanese insurance enrollment / insurance-card member number "
        "(emitted as FHIR Coverage). Use --no-jp-insurance to omit. "
        "Ignored for non-JP countries.",
    )
    gen.add_argument(
        "--cache-dir",
        default=None,
        help="F4 memoize: path to a previous snapshot output "
        "directory. When provided and valid (same seed / config / country), "
        "patients whose encounters completed before the previous cursor are "
        "loaded from cache instead of re-simulated. Enables daily-cron append for "
        "large populations (p=500k advance drops from ~13h to ~minutes).",
    )
    gen.add_argument(
        "--log-file",
        default=None,
        help="Path to the structured JSONL simulator log (Issue #172). Defaults "
        "to <output-dir>/simulator.log. Each line is one JSON event with "
        "`ts` / `module` / `event` / stage timings. Use `tail -f` to watch a "
        "run live; use `jq -c '{module,event,elapsed_s}'` for post-run "
        "profiling. Log level via CLINOSIM_LOG_LEVEL (default INFO).",
    )
    gen.add_argument(
        "--allow-legacy",
        action="store_true",
        default=False,
        help="(JP only) Permit generation to proceed with legacy 5-digit JLAC10 OID "
        "output when the JP-CLINS package is not installed (Issue #418). "
        "Default is fail-loud: `--country JP` requires the pkg "
        "(`clinical-information-sharing#1.13.0` + `jpfhir-terminology#2.2606.0`) "
        "so the emitted output is JP-CLINS eCS compliant. Set this flag to "
        "acknowledge non-compliant output — the run will print a warning and "
        "produce legacy fallback codes. Ignored for non-JP countries.",
    )
    gen.set_defaults(handler=run)


def run(args: Any, parser: argparse.ArgumentParser) -> None:
    # Canonical command is "simulate"; "generate" is a deprecation alias.
    # argparse's alias mechanism returns the token the user actually typed in
    # args.command, so both are accepted and the alias path emits a
    # deprecation warning on stderr.
    if args.command == "generate":
        import sys as _sys

        print(
            "clinosim: DeprecationWarning: 'generate' subcommand is deprecated, "
            "use 'simulate' instead. Backward-compat alias will be removed in a "
            "future release.",
            file=_sys.stderr,
        )
    _validate_formats(args.format, parser)  # fail fast on bad --format (AD-58)
    from datetime import date
    from datetime import timedelta as _td

    # Default end = today, default start = end - 1 year
    end_date = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else date.today()
    start_date = datetime.strptime(args.start, "%Y-%m-%d").date() if args.start else end_date - _td(days=365)
    end = end_date.strftime("%Y-%m-%d")
    start = start_date.strftime("%Y-%m-%d")
    # Bug D fix: -p uses argparse.SUPPRESS as default, so args.population is only
    # present when the user explicitly passed -p/--population. None → engine.py
    # resolves to the hospital's recommended_population; never a silent sentinel.
    population_arg = getattr(args, "population", None)
    config = SimulatorConfig(
        catchment_population=population_arg,
        time_range=(start, end),
        random_seed=args.seed,
        country=args.country,
        snapshot_date=end,
        jp_insurance_numbers=args.jp_insurance,
    )
    hospital_ops = getattr(args, "hospital_config", None)
    pop_label = str(population_arg) if population_arg is not None else "hospital recommended"
    print(f"clinosim simulate: population={pop_label}, seed={args.seed}, country={args.country}, period={start}~{end}")
    if is_jp(args.country):
        _enforce_jp_clins_pkg_gate(allow_legacy=getattr(args, "allow_legacy", False))
        status = "on" if args.jp_insurance else "off"
        print(f"  JP insurance numbers (被保険者番号): {status}")
    if hospital_ops:
        print(f"  Hospital config: {hospital_ops}")
    # F4: reuse prior snapshot's discharged patients when
    # --cache-dir is provided. run_beta validates seed / config / country
    # match; on mismatch it prints a warn and full-recomputes.
    cache_dir_arg = getattr(args, "cache_dir", None)
    if cache_dir_arg:
        print(f"  Cache dir (F4 memoize): {cache_dir_arg}")
    # Issue #172: attach the unified simulator JSONL log before invoking
    # run_beta so its phase-boundary events and enricher aggregates are
    # captured. Default path is <output-dir>/simulator.log; overridable
    # via --log-file. Level via CLINOSIM_LOG_LEVEL (default INFO).
    from clinosim.simulator import log as sim_log

    log_path = getattr(args, "log_file", None) or os.path.join(args.output, "simulator.log")
    sim_log.configure(log_path)
    print(f"  Log: {log_path}")
    dataset = run_beta(config, hospital_config_path=hospital_ops, cache_dir=cache_dir_arg)

    # Output
    from clinosim.modules.output.cif_writer import write_cif

    cif_dir = os.path.join(args.output, "cif")
    write_cif(dataset, cif_dir)

    # F4: write _cache_manifest.json alongside the output so a
    # future `run_beta(..., cache_dir=args.output)` call (later cursor / cron
    # advance) can validate + reuse already-discharged patients from this run.
    from pathlib import Path as _Path

    from clinosim.simulator.memoize import write_cache_manifest

    write_cache_manifest(_Path(args.output), config)

    # Stage 2 (AD-65): auto-invoke the template narrative pass so cohorts are
    # always emit-ready. `clinosim narrate` remains available to regenerate
    # (or LLM-narrate, once β-JP-1 lands) on top of an existing structural CIF.
    from clinosim.modules.document.narrative.passes import TemplateNarrativePass

    _narrative_pass = TemplateNarrativePass(
        cif_dir=cif_dir,
        version_id="template",
        country=args.country,
        rng_seed=args.seed,
    )
    _narrative_pass.run()
    os.makedirs(os.path.join(cif_dir, "narratives"), exist_ok=True)
    with open(os.path.join(cif_dir, "narratives", "current_version.txt"), "w", encoding="utf-8") as f:
        f.write("template")

    # Format exports via the adapter registry (AD-58). Add a format = register an adapter.
    # DocumentReference resources are emitted from record.documents (Stage 1 enricher).
    _run_exports(
        args.format,
        cif_dir,
        args.output,
        getattr(args, "country", "US"),
    )

    # Summary
    _print_summary(dataset, args.output)
