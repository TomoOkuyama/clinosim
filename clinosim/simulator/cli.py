"""CLI entry point for clinosim."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

from clinosim.modules._shared import is_jp
from clinosim.simulator.cli_common import (
    _print_debug_record,
    _print_summary,
    _run_exports,
    _run_quality_checks,
    _validate_formats,
)
from clinosim.simulator.cli_enumerate import _run_enumerate
from clinosim.simulator.cli_export_fhir import _run_export_fhir
from clinosim.simulator.cli_narrate import _run_check_narratives, _run_narrate
from clinosim.simulator.cli_regenerate import _run_regenerate_goldens
from clinosim.simulator.cli_test_disease import _run_test_disease
from clinosim.simulator.cli_test_encounter import _run_test_encounter
from clinosim.simulator.engine import run_beta
from clinosim.simulator.helpers import _load_all_disease_protocols
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
    from clinosim.modules.output.lab_coding_package import load_lab_coding_package

    pkg = load_lab_coding_package()
    if pkg.is_available():
        return
    if os.environ.get("CLINOSIM_ALLOW_LEGACY_JP_CLINS_PKG") == "1":
        allow_legacy = True
    if not allow_legacy:
        print(
            "ERROR: JP-CLINS package not detected. `clinosim generate --country JP`\n"
            "requires either:\n"
            "  - `fhir install clinical-information-sharing 1.12.0` (+ jpfhir-terminology 2.2606.0), OR\n"
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


def main() -> None:
    """CLI entry point: clinosim [command] [options]"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="clinosim",
        description="Clinically Realistic Hospital Data Simulator",
    )
    sub = parser.add_subparsers(dest="command", help="Command to run")

    # === simulate: population-driven simulation ===
    # session 48 cleanup (g): 元 command 名は "generate" だったが
    # physiology-driven simulator という実態を反映して "simulate" を canonical に
    # し、"generate" は deprecation alias として残す。alias 利用時のみ
    # deprecation warning を stderr に出す(run() で sys.argv 検査)。
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
        help="(JP only) Include Japanese insurance enrollment / 被保険者番号 "
        "(emitted as FHIR Coverage). Use --no-jp-insurance to omit. "
        "Ignored for non-JP countries.",
    )
    gen.add_argument(
        "--cache-dir",
        default=None,
        help="F4 memoize (session 49): path to a previous snapshot output "
        "directory. When provided and valid (same seed / config / country), "
        "patients whose encounters completed before the previous cursor are "
        "loaded from cache instead of re-simulated. Enables cron 日次追記 for "
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
        "(`clinical-information-sharing#1.12.0` + `jpfhir-terminology#2.2606.0`) "
        "so the emitted output is JP-CLINS eCS compliant. Set this flag to "
        "acknowledge non-compliant output — the run will print a warning and "
        "produce legacy fallback codes. Ignored for non-JP countries.",
    )

    # === test-disease: generate specific disease/archetype ===
    td = sub.add_parser("test-disease", help="Generate data for a specific disease and archetype")
    td.add_argument(
        "disease_id",
        nargs="?",
        default=None,
        help="Disease ID (e.g., bacterial_pneumonia); optional when --patient-profile is set",
    )
    td.add_argument(
        "--patient-profile",
        default=None,
        help="Patient profile fixture name or path (AD-66); CLI args override profile fields with stderr WARN",
    )
    # adv-1 F-2: -n/--seed/--country default to None (not 3/42/US) so an EXPLICIT
    # value equal to the old default is distinguishable from "flag omitted" when
    # resolving against a --patient-profile. Legacy defaults are applied in
    # _resolve_test_disease_defaults when the flag is omitted and no profile
    # supplies a value — non-profile behavior is unchanged.
    td.add_argument(
        "-n",
        "--count",
        type=int,
        default=None,
        help="Number of patients (default: 3, or profile count)",
    )
    td.add_argument("--severity", default=None, help="Force severity: mild/moderate/severe")
    td.add_argument("--archetype", default=None, help="Force archetype name")
    td.add_argument(
        "-s",
        "--seed",
        type=int,
        default=None,
        help="Random seed (default: 42, or profile random_seed)",
    )
    td.add_argument(
        "--country",
        default=None,
        help="Country code (US or JP; default: US, or profile country)",
    )
    # AD-65 Phase 4 (Task 16): when -o is set, run the full 3-stage pipeline
    # (structural + narrative + FHIR/CSV) for a tiny disease-specific cohort — a
    # 10-second targeted verify without regenerating a full cohort. When -o is
    # omitted (default), the original stdout debug print is unchanged.
    td.add_argument(
        "--format",
        nargs="+",
        default=None,
        choices=["cif", "fhir-r4", "csv", "all"],
        help="Output formats (requires -o/--output; if omitted, stdout debug only)",
    )
    td.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output directory (required when --format is set)",
    )

    # === validate: run quality checks on generated data ===
    val = sub.add_parser("validate", help="Run data quality checks on generated data")
    val.add_argument("-p", "--population", type=int, default=5_000, help="Population size")
    val.add_argument("-s", "--seed", type=int, default=42, help="Random seed")
    val.add_argument("--country", default="US", help="Country code")

    # === list-diseases: show available disease protocols ===
    sub.add_parser("list-diseases", help="List all available disease protocols")

    # === narrate: Stage 2 template narrative generation (AD-65) ===
    nr = sub.add_parser(
        "narrate",
        help="Generate narrative CIF from a structural CIF directory (AD-65 Stage 2)",
    )
    nr.add_argument("--cif-dir", required=True, help="Path to structural CIF directory")
    nr.add_argument(
        "--provider",
        default="template",
        choices=["template", "bedrock", "ollama", "mock"],
        help=(
            "Narrative generator: 'template' (default, deterministic) or an "
            "LLM provider run through LLMNarrativePass — 'bedrock' / 'ollama' "
            "(configured via config/llm_service*.yaml or --llm-config) or "
            "'mock' (deterministic MockProvider, dev/test only)"
        ),
    )
    nr.add_argument(
        "--llm-config",
        default=None,
        help=(
            "Path to an LLM service YAML (see clinosim/config/llm_service*.yaml). "
            "Default: bedrock -> config/llm_service.bedrock.yaml, "
            "ollama -> config/llm_service.yaml, mock -> in-code MockProvider"
        ),
    )
    nr.add_argument(
        "--version-id",
        default=None,
        help="Narrative version directory name (default: provider name)",
    )
    nr.add_argument("--tasks", default=None, help="Comma-separated LLMTaskType filter (default: all)")
    nr.add_argument("--country", default="US")
    nr.add_argument(
        "--set-current",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Update current_version.txt to point to the new version. "
            "Default: yes for --provider template, no for LLM providers "
            "(bedrock/ollama/mock) so a trial run cannot silently repoint "
            "production exports (M-3, N-chain adv-1), and no for ANY "
            "provider when --patient-filter is set (a partial version "
            "must not silently become current — chain 1b adv-1 I-1). "
            "Explicit --set-current / --no-set-current always wins"
        ),
    )
    nr.add_argument("--seed", type=int, default=42, help="RNG seed for determinism")
    nr.add_argument(
        "--patient-filter",
        default=None,
        help=(
            "Regex over patient filename stem / patient_id — narrate only "
            "matching patients (remote per-patient iteration, chain 1b T3). "
            "The version manifest records the filter. Default: all patients"
        ),
    )
    nr.add_argument(
        "--merge-into-version",
        action="store_true",
        help=(
            "With --patient-filter: allow writing into an existing version "
            "directory that already contains documents (iterate-one-patient "
            "loop). Files from previous runs remain on disk and "
            "manifest.json reflects only the last run. Without this flag a "
            "filtered write into a non-empty version is refused "
            "(chain 1b adv-1 I-1)"
        ),
    )

    # === export-fhir: Stage 3 — convert CIF to FHIR NDJSON ===
    ef = sub.add_parser(
        "export-fhir",
        help="Convert an existing CIF directory to FHIR R4 Bulk Data NDJSON",
    )
    ef.add_argument("--cif-dir", required=True, help="Path to an existing CIF directory")
    ef.add_argument(
        "-o",
        "--output",
        default=None,
        help="FHIR output directory (default: <cif-dir>/../fhir_r4)",
    )
    ef.add_argument("--country", default="US", help="Country code (US or JP)")
    ef.add_argument(
        "--narrative-version",
        default="current",
        help="Narrative version to select (default: current from pointer file)",
    )

    # === test-encounter: debug single encounter condition ===
    te = sub.add_parser("test-encounter", help="Simulate one patient for an encounter condition (debug)")
    te.add_argument("condition_id", help="Condition ID (e.g., chest_pain_noncardiac, flu_vaccination)")
    te.add_argument("-n", "--count", type=int, default=1, help="Number of patients")
    te.add_argument("-s", "--seed", type=int, default=42, help="Random seed")
    te.add_argument("--country", default="US", help="Country code")
    te.add_argument("--age", type=int, default=None, help="Force patient age")
    te.add_argument("--sex", default=None, help="Force patient sex (M/F)")
    # AD-65 Phase 4 (Task 17): mirrors test-disease pattern — when -o is set, run the
    # full 3-stage pipeline (structural CIF + template narrative + FHIR/CSV) for a tiny
    # encounter-specific cohort. When -o is omitted (default), original stdout debug
    # print is unchanged.
    te.add_argument(
        "--format",
        nargs="+",
        default=None,
        choices=["cif", "fhir-r4", "csv", "all"],
        help="Output formats (requires -o/--output; if omitted, stdout debug only)",
    )
    te.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output directory (required when --format is set)",
    )

    # === enumerate: exhaustive debug enumeration (Issue #345, session 63) ===
    # Generates exactly one patient per (disease × severity × course_archetype)
    # plus per (encounter × severity). Purpose: comprehensive FHIR validation
    # coverage and pattern regression detection — population-driven sampling
    # can leave rare patterns unfired even at large P, but enumeration
    # deterministically covers every combination.
    en = sub.add_parser(
        "enumerate",
        help="Exhaustively enumerate all clinical scenarios (debug: 1 patient per pattern)",
    )
    en.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output directory (writes cif/, cif/narratives/template/, fhir_r4/, enumeration_manifest.json)",
    )
    en.add_argument(
        "--level",
        default="full",
        choices=["basic", "severity", "full"],
        help=(
            "Coverage level. basic=1 per scenario, severity=1 per (scenario × severity), "
            "full=1 per (disease × severity × course_archetype) + (encounter × severity). "
            "Default: full."
        ),
    )
    en.add_argument("--country", default="JP", choices=["JP", "US"], help="Country locale (single). Default: JP.")
    en.add_argument(
        "--include-both-countries",
        action="store_true",
        help="Emit both JP and US patients in one run (approximately doubles the case count).",
    )
    en.add_argument("--seed", type=int, default=42, help="Base seed for deterministic sub-seed derivation.")
    en.add_argument(
        "--yes-large",
        action="store_true",
        help=(
            "Bypass the coverage-explosion guard (threshold 2000 patients). Required if "
            "the case count would exceed the threshold."
        ),
    )
    en.add_argument(
        "--format",
        nargs="+",
        default=["cif", "fhir-r4"],
        choices=["cif", "fhir-r4", "csv", "all"],
        help="Output formats. Default: cif + fhir-r4.",
    )
    en.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan only — print discovered scenarios and case count, do not simulate or write output.",
    )

    # === diff: F3 snapshot diff → Bundle transaction (session 49) ===
    df = sub.add_parser(
        "diff",
        help="Generate FHIR Bundle transaction from 2 snapshot outputs (session 49 F3)",
    )
    df.add_argument("--old", required=True, help="前 snapshot の FHIR output directory")
    df.add_argument("--new", required=True, help="現 snapshot の FHIR output directory")
    df.add_argument("--output-bundle", required=True, help="Bundle transaction JSON の出力 path")
    df.add_argument("--output-summary", default=None, help="Summary text の出力 path (省略時は stdout)")
    df.add_argument(
        "--old-cursor", default=None, help="前 snapshot の cursor 日付(summary 表示用、省略時は --old dir 名)"
    )
    df.add_argument(
        "--new-cursor", default=None, help="現 snapshot の cursor 日付(summary 表示用、省略時は --new dir 名)"
    )

    # === regenerate-goldens: AD-66 α-min-2c golden narrative bootstrap ===
    rg = sub.add_parser(
        "regenerate-goldens",
        help="Regenerate narrative goldens for canonical patient profiles (AD-66)",
    )
    rg_group = rg.add_mutually_exclusive_group(required=True)
    rg_group.add_argument(
        "--profile",
        default=None,
        help="Regenerate a single profile by name",
    )
    rg_group.add_argument(
        "--all",
        action="store_true",
        help="Regenerate goldens for all profiles in the fixtures dir",
    )
    # β-JP-1 chain 1b T1: LLM parallel goldens. template (default) keeps the
    # historical <name>.golden.json naming; LLM providers write
    # <name>.llm-<tag>.golden.json via a `narrate --provider` subprocess step.
    rg.add_argument(
        "--provider",
        default="template",
        choices=["template", "mock", "bedrock", "ollama"],
        help=(
            "Narrative generator for the golden run: 'template' (default, "
            "writes <name>.golden.json — unchanged) or an LLM provider "
            "(mock/bedrock/ollama, writes <name>.llm-<tag>.golden.json)"
        ),
    )
    rg.add_argument(
        "--llm-config",
        default=None,
        help="LLM service YAML passed through to narrate (LLM providers only)",
    )
    rg.add_argument(
        "--model-tag",
        default=None,
        help=(
            "Filename tag for LLM goldens: <name>.llm-<tag>.golden.json "
            "(default: provider name, e.g. mock). LLM providers only"
        ),
    )
    # T3 guard: declared ONLY so that combining it with regenerate-goldens is
    # rejected loudly (goldens must always cover the full profile cohort —
    # a partial golden would silently pass byte-diff on the subset).
    rg.add_argument(
        "--patient-filter",
        default=None,
        help="NOT allowed here — goldens must never be partial. Use `narrate --patient-filter`",
    )

    # === check-narratives: β-JP-1 chain 1b T2 semantic check ===
    cn = sub.add_parser(
        "check-narratives",
        help=(
            "Semantic check of a narrative version (5 axes; the LLM-output "
            "gate where byte-diff does not apply). Exit 0 = pass, 1 = findings"
        ),
    )
    cn.add_argument("--cif-dir", required=True, help="Path to a CIF directory")
    cn.add_argument(
        "--version",
        required=True,
        help="Narrative version id to check (e.g. llm-mock, ollama)",
    )
    cn.add_argument(
        "--profile",
        default=None,
        help=(
            "Patient profile name — resolves expectations to "
            "tests/fixtures/patient_profiles/<name>.llm-expectations.yaml"
        ),
    )
    cn.add_argument(
        "--expectations",
        default=None,
        help="Explicit expectations YAML path (overrides --profile resolution)",
    )
    cn.add_argument(
        "--report",
        default=None,
        help="Write the full SemanticCheckReport as JSON to this path",
    )

    # === audit: verification framework ===
    from clinosim.audit.cli import add_audit_subparser

    add_audit_subparser(sub)

    # === dataset: named-preset dataset builder ===
    from clinosim.dataset import add_dataset_subparser

    add_dataset_subparser(sub)

    # === eval: public 3-axis evaluation framework ===
    from clinosim.eval import add_eval_subparser

    add_eval_subparser(sub)

    # === benchmark: session 48 P2-15 prediction benchmark harness ===
    from clinosim.benchmarks.cli import add_benchmark_subparser

    add_benchmark_subparser(sub)

    args = parser.parse_args()

    if args.command == "audit":
        import sys

        from clinosim.audit.cli import dispatch_audit

        sys.exit(dispatch_audit(args))

    if args.command == "dataset":
        import sys

        from clinosim.dataset import dispatch_dataset

        sys.exit(dispatch_dataset(args))

    if args.command == "eval":
        import sys

        from clinosim.eval import dispatch_eval

        sys.exit(dispatch_eval(args))

    if args.command == "benchmark":
        import sys

        from clinosim.benchmarks.cli import dispatch_benchmark

        sys.exit(dispatch_benchmark(args))

    if args.command == "list-diseases":
        protocols = _load_all_disease_protocols()
        print(f"\n{len(protocols)} inpatient disease protocols:")
        for name in sorted(protocols.keys()):
            p = protocols[name]
            # chief_complaint is `str | dict[str, str]` (multi-lang variant).
            # Coerce to str for the compact list display.
            cc = p.chief_complaint
            cc_str = cc if isinstance(cc, str) else (cc.get("en") or cc.get("ja") or "")
            print(f"  {name:35s} | {cc_str[:50]}")

        from clinosim.modules.encounter.protocol import load_all_encounter_conditions

        ed_conditions = load_all_encounter_conditions()
        print(f"\n{len(ed_conditions)} ED/outpatient encounter conditions:")
        for name in sorted(ed_conditions.keys()):
            c = ed_conditions[name]
            print(f"  {name:35s} | {c.get('chief_complaint', '')[:50]}")
        return

    if args.command == "test-encounter":
        if args.format and not args.output:
            parser.error("--format requires -o/--output to be set")
        _run_test_encounter(args)
        return

    if args.command == "enumerate":
        _run_enumerate(args)
        return

    if args.command == "diff":
        from pathlib import Path

        from clinosim.simulator.diff import build_diff_bundle, format_summary

        old_dir = Path(args.old)
        new_dir = Path(args.new)
        bundle_path = Path(args.output_bundle)

        old_cursor = args.old_cursor or old_dir.name
        new_cursor = args.new_cursor or new_dir.name

        bundle_id = f"clinosim-diff-{old_cursor}-to-{new_cursor}"
        last_updated = datetime.now().isoformat(timespec="seconds")

        bundle = build_diff_bundle(old_dir, new_dir, bundle_id, last_updated)
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text(
            json.dumps(bundle, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        summary = format_summary(bundle, old_cursor, new_cursor)
        if args.output_summary:
            summary_path = Path(args.output_summary)
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(summary, encoding="utf-8")
        else:
            print(summary)
        return

    if args.command == "test-disease":
        if args.format and not args.output:
            parser.error("--format requires -o/--output to be set")
        _run_test_disease(args)
        return

    if args.command == "regenerate-goldens":
        _run_regenerate_goldens(args)
        return

    if args.command == "narrate":
        _run_narrate(args)
        return

    if args.command == "check-narratives":
        _run_check_narratives(args)
        return

    if args.command == "export-fhir":
        _run_export_fhir(args)
        return

    if args.command == "validate":
        config = SimulatorConfig(
            catchment_population=args.population,
            random_seed=args.seed,
            country=args.country,
        )
        print(f"clinosim validate: pop={args.population}, country={args.country}")
        dataset = run_beta(config)
        _run_quality_checks(dataset)
        return

    # session 48 cleanup (g): canonical は "simulate"、"generate" は
    # deprecation alias。argparse の alias は args.command に打鍵された表記を
    # そのまま返すため、両方を受け入れつつ alias 側では stderr に warn を出す。
    if args.command in ("simulate", "generate"):
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
        hospital_cfg = getattr(args, "hospital_config", None)
        pop_label = str(population_arg) if population_arg is not None else "hospital recommended"
        print(
            f"clinosim generate: population={pop_label}, seed={args.seed}, country={args.country}, period={start}~{end}"
        )
        if is_jp(args.country):
            _enforce_jp_clins_pkg_gate(allow_legacy=getattr(args, "allow_legacy", False))
            status = "on" if args.jp_insurance else "off"
            print(f"  JP insurance numbers (被保険者番号): {status}")
        if hospital_cfg:
            print(f"  Hospital config: {hospital_cfg}")
        # F4 (session 49): reuse prior snapshot's discharged patients when
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
        dataset = run_beta(config, hospital_config_path=hospital_cfg, cache_dir=cache_dir_arg)

    else:
        parser.print_help()
        return

    # Output
    from clinosim.modules.output.cif_writer import write_cif

    cif_dir = os.path.join(args.output, "cif")
    write_cif(dataset, cif_dir)

    # F4 (session 49): write _cache_manifest.json alongside the output so a
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
    with open(os.path.join(cif_dir, "narratives", "current_version.txt"), "w") as f:
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


# `_FORMAT_ALIASES` moved to `cli_common.py` alongside `_run_exports` /
# `_validate_formats` (session 82 PR K split).

# Backward-compat re-exports for test callers that import from this module
# directly. The canonical homes are the sub-modules below; these aliases stay
# until tests migrate their imports.
from clinosim.simulator.cli_test_disease import (  # noqa: E402
    _apply_profile_cli_overrides,
    _resolve_test_disease_defaults,
)

__all__ = [
    "main",
    "_apply_profile_cli_overrides",
    "_enforce_jp_clins_pkg_gate",
    "_print_debug_record",
    "_print_summary",
    "_resolve_test_disease_defaults",
    "_run_exports",
    "_run_quality_checks",
    "_validate_formats",
]


if __name__ == "__main__":
    main()
