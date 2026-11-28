"""Forced-scenario corpus and cohort runner for refactoring proofs (Issue #3976).

Used by ``scripts/refactor-diff.sh``; runnable by hand. Every command runs
the clinosim found on ``PYTHONPATH`` (the script points it at one detached
worktree per commit) and writes the fired counters of what it ran
(``clinosim.fired_counters``) to a JSON sidecar outside the output tree.

  python tests/refactor_corpus/run_corpus.py corpus --country US --out DIR --counters FILE
      Generate every scenario of ``scenarios.yaml`` (CIF, template
      narratives, FHIR R4), one output directory per scenario.

  python tests/refactor_corpus/run_corpus.py cohort --counters FILE -- <clinosim simulate args>
      Run ``clinosim simulate`` in this process and write its counters.

  python tests/refactor_corpus/run_corpus.py check FILE [FILE ...]
      Fail unless every path a scenario expects fired at least once in it.

  python tests/refactor_corpus/run_corpus.py report BASE_COUNTERS HEAD_COUNTERS
      Print the fired counters of both commits side by side.

  python tests/refactor_corpus/run_corpus.py compare BASE_DIR HEAD_DIR
      List every file that differs between two output trees (exit 1 if any),
      ignoring logs, generator metadata and the wall-clock keys of the
      metadata files.

The scenario file is read from this directory, so the script can run the
same corpus definition against two commits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

_HERE = Path(__file__).resolve().parent
SCENARIOS_FILE = _HERE / "scenarios.yaml"
SEED = 42


def load_scenarios(path: Path = SCENARIOS_FILE) -> list[dict[str, Any]]:
    """The scenario list of ``scenarios.yaml`` (validated by the unit test of the corpus)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return list(data["scenarios"])


def scenario_countries(scenario: dict[str, Any]) -> list[str]:
    return list(scenario.get("countries") or ["US", "JP"])


def expected_paths(scenario: dict[str, Any], country: str) -> list[str]:
    """The fired-counter paths the scenario must fire in ``country``."""
    expect = scenario.get("expect") or {}
    return [*(expect.get("all") or []), *(expect.get(country) or [])]


def _counters() -> Any:
    """``clinosim.fired_counters`` of the commit under test, or None when it has none."""
    try:
        from clinosim import fired_counters
    except ImportError:
        return None
    return fired_counters


def _snapshot() -> dict[str, int] | None:
    counters = _counters()
    return None if counters is None else counters.snapshot()


def _reset() -> None:
    counters = _counters()
    if counters is not None:
        counters.reset()


def _write_outputs(dataset: Any, out: Path, country: str) -> None:
    """CIF, the template narrative pass and FHIR R4, as ``clinosim simulate`` writes them."""
    from clinosim.modules.document.narrative.passes import TemplateNarrativePass
    from clinosim.modules.output.adapter import OutputContext, get_adapter
    from clinosim.modules.output.cif_writer import write_cif

    cif_dir = out / "cif"
    write_cif(dataset, str(cif_dir))
    TemplateNarrativePass(cif_dir=str(cif_dir), version_id="template", country=country, rng_seed=SEED).run()
    (cif_dir / "narratives").mkdir(parents=True, exist_ok=True)
    (cif_dir / "narratives" / "current_version.txt").write_text("template", encoding="utf-8")
    adapter = get_adapter("fhir-r4")
    adapter.convert(str(cif_dir), str(out / adapter.subdir), OutputContext(country=country))


def _forced_dataset(scenario: dict[str, Any], country: str) -> Any:
    from clinosim.simulator.engine import run_forced
    from clinosim.types.config import ForcedScenario, SimulatorConfig

    if scenario.get("force_complications") and "force_complications" not in ForcedScenario.model_fields:
        raise SystemExit(
            "this commit has no ForcedScenario.force_complications: it predates the refactoring corpus (Issue #3976)"
        )
    forced = ForcedScenario(
        disease_id=scenario["disease"],
        count=int(scenario.get("count", 1)),
        severity=scenario.get("severity"),
        archetype=scenario.get("archetype"),
        patient_overrides=dict(scenario.get("patient") or {}),
        force_hai_event=scenario.get("force_hai_event"),
        force_complications=list(scenario.get("force_complications") or []),
    )
    return run_forced(forced, SimulatorConfig(random_seed=SEED, country=country))


def _delivery_dataset(scenario: dict[str, Any], country: str) -> Any:
    """Delivery admissions (mother + newborn) of ``count`` mothers. The mode
    (vaginal / cesarean) is the per-mother draw of the delivery simulator,
    keyed by the mother's id, so a fixed id list gives a fixed mix."""
    from datetime import date

    from clinosim import __version__, determinism
    from clinosim.countries import lang_for
    from clinosim.locale.i18n import t
    from clinosim.locale.loader import load_demographics
    from clinosim.modules.patient.activator import activate_patient
    from clinosim.modules.population.engine import PersonRecord
    from clinosim.modules.staff.engine import generate_roster
    from clinosim.simulator.perinatal import simulate_delivery_encounter
    from clinosim.types.config import SimulatorConfig
    from clinosim.types.output import CIFDataset, CIFMetadata, distinct_patient_count

    config = SimulatorConfig(random_seed=SEED, country=country)
    rng = determinism.default_rng(SEED)
    roster = generate_roster(config.hospital_scale, country, rng)
    demo = load_demographics(country)
    delivered_at = datetime.fromisoformat(str(scenario.get("delivered_at", "2025-09-15T10:00:00")))
    age = int(scenario.get("mother_age", 31))
    records = []
    for i in range(int(scenario.get("count", 1))):
        person = PersonRecord(
            person_id=f"CORPUS-DELIVERY-{i + 1:04d}",
            household_id=f"HH-CORPUS-DELIVERY-{i + 1:04d}",
            age=age,
            sex="F",
            date_of_birth=date(delivered_at.year - age, 1, 1),
            family_name=t("module_text.test_family", lang_for(country)),
            given_name=t("module_text.test_given", lang_for(country), n=i + 1),
            chronic_conditions=[],
        )
        mother = activate_patient(person, rng, demo)
        records.extend(simulate_delivery_encounter(mother, delivered_at, roster, rng, country, config=config))
    metadata = CIFMetadata(
        clinosim_version=__version__,
        random_seed=SEED,
        country=country,
        hospital_scale=config.hospital_scale,
        total_patients=distinct_patient_count(records),
        total_records=len(records),
        llm_mode="none",
    )
    return CIFDataset(metadata=metadata, patients=records, hospital_roster=list(roster.members), hospital_config={})


def run_corpus(country: str, out: Path, scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate every scenario of ``country``; returns the counters per scenario."""
    per_scenario: dict[str, dict[str, int] | None] = {}
    for scenario in scenarios:
        if country not in scenario_countries(scenario):
            continue
        name = scenario["id"]
        print(f"[corpus {country}] {name}", flush=True)
        _reset()
        kind = scenario.get("kind", "forced")
        dataset = _delivery_dataset(scenario, country) if kind == "delivery" else _forced_dataset(scenario, country)
        per_scenario[name] = _snapshot()
        _write_outputs(dataset, out / name, country)
    return {"country": country, "scenarios": per_scenario, "total": _sum(per_scenario.values())}


def _sum(parts: Any) -> dict[str, int] | None:
    total: dict[str, int] = {}
    seen = False
    for part in parts:
        if part is None:
            continue
        seen = True
        for path, n in part.items():
            total[path] = total.get(path, 0) + n
    return dict(sorted(total.items())) if seen else None


def run_cohort(argv: list[str]) -> dict[str, Any]:
    """``clinosim simulate <argv>`` in this process; returns its counters."""
    from clinosim.simulator import cli

    saved = sys.argv
    sys.argv = ["clinosim", "simulate", *argv]
    try:
        cli.main()
    finally:
        sys.argv = saved
    return {"argv": argv, "total": _snapshot()}


#: Files that hold only run metadata (git commit, wall clock) or logs; never compared.
EXCLUDED_NAMES = frozenset({"_generator_metadata.json", "simulator.log"})
#: Wall-clock keys of the metadata files that are compared otherwise (determinism spec §5):
#: the CIF ``metadata.json``, the narrative version ``manifest.json`` and the Bulk Data ``manifest.json``.
WALL_CLOCK_KEYS = frozenset({"generation_timestamp", "generated_at", "transactionTime"})


def _digest(path: Path) -> str:
    """sha256 of a file; a top-level wall-clock key of a metadata JSON is blanked first."""
    data = path.read_bytes()
    if path.name in ("metadata.json", "manifest.json"):
        try:
            doc = json.loads(data)
        except ValueError:
            doc = None
        if isinstance(doc, dict) and WALL_CLOCK_KEYS & doc.keys():
            data = json.dumps({k: v for k, v in doc.items() if k not in WALL_CLOCK_KEYS}, sort_keys=True).encode()
    return hashlib.sha256(data).hexdigest()


def compare(a: Path, b: Path) -> list[str]:
    """Every file that differs between two output trees, or exists in one only."""

    def files(root: Path) -> dict[str, Path]:
        return {
            str(p.relative_to(root)): p
            for p in root.rglob("*")
            if p.is_file() and p.name not in EXCLUDED_NAMES and not p.name.endswith(".log")
        }

    fa, fb = files(a), files(b)
    lines = [f"only in base: {rel}" for rel in sorted(fa.keys() - fb.keys())]
    lines += [f"only in head: {rel}" for rel in sorted(fb.keys() - fa.keys())]
    lines += [f"differs: {rel}" for rel in sorted(fa.keys() & fb.keys()) if _digest(fa[rel]) != _digest(fb[rel])]
    return lines


def check(files: list[Path], scenarios: list[dict[str, Any]]) -> list[str]:
    """The expected paths that did not fire, as ``country/scenario: path`` lines."""
    by_id = {s["id"]: s for s in scenarios}
    missing: list[str] = []
    for file in files:
        data = json.loads(file.read_text(encoding="utf-8"))
        country = data["country"]
        for name, fired in (data.get("scenarios") or {}).items():
            for path in expected_paths(by_id[name], country):
                if fired is None or fired.get(path, 0) < 1:
                    missing.append(f"{country}/{name}: {path}")
    return missing


#: The sidecars ``scripts/refactor-diff.sh`` writes per commit, in report column order.
REPORT_RUNS = ("corpus_US", "corpus_JP", "cohort_US", "cohort_JP")
#: Counters of every declared complication action (``count_each`` in the daily loop);
#: summarised in one line of the report instead of one row each.
_ACTION_PREFIX = "complication.action."


def _totals(directory: Path) -> dict[str, dict[str, int] | None]:
    """The ``total`` counters of each run in ``directory`` (None: the commit has no counters)."""
    totals: dict[str, dict[str, int] | None] = {}
    for run in REPORT_RUNS:
        file = directory / f"{run}.json"
        totals[run] = json.loads(file.read_text(encoding="utf-8")).get("total") if file.is_file() else None
    return totals


def report(base_dir: Path, head_dir: Path) -> list[str]:
    """A table of the fired counters of both commits, one row per path.

    A cell is the head count, or ``base->head`` when the counts differ; ``-``
    stands for a commit without counters. Different counts with identical
    output are not a failure, but a moved path should show the same count.
    """
    base, head = _totals(base_dir), _totals(head_dir)
    paths = sorted({p for side in (base, head) for counts in side.values() if counts for p in counts})

    def cell(run: str, path: str) -> str:
        b, h = base[run], head[run]
        hv = "-" if h is None else str(h.get(path, 0))
        bv = "-" if b is None else str(b.get(path, 0))
        return hv if bv == hv else f"{bv}->{hv}"

    width = max([len(p) for p in paths if not p.startswith(_ACTION_PREFIX)] + [4])
    lines = [f"{'path':<{width}}  " + "  ".join(f"{r:>12}" for r in REPORT_RUNS)]
    for path in paths:
        if not path.startswith(_ACTION_PREFIX):
            lines.append(f"{path:<{width}}  " + "  ".join(f"{cell(r, path):>12}" for r in REPORT_RUNS))
    actions = [p for p in paths if p.startswith(_ACTION_PREFIX)]
    changed = [p for p in actions if any("->" in cell(r, p) for r in REPORT_RUNS)]
    lines.append(f"{len(actions)} declared complication action kinds counted ({_ACTION_PREFIX}*)")
    lines += [f"{p:<{width}}  " + "  ".join(f"{cell(r, p):>12}" for r in REPORT_RUNS) for p in changed]
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p_corpus = sub.add_parser("corpus")
    p_corpus.add_argument("--country", required=True, choices=["US", "JP"])
    p_corpus.add_argument("--out", required=True, type=Path)
    p_corpus.add_argument("--counters", required=True, type=Path)
    p_corpus.add_argument("--only", nargs="*", default=None, help="scenario ids to run (default: all)")
    p_cohort = sub.add_parser("cohort")
    p_cohort.add_argument("--counters", required=True, type=Path)
    p_cohort.add_argument("simulate_args", nargs=argparse.REMAINDER)
    p_check = sub.add_parser("check")
    p_check.add_argument("files", nargs="+", type=Path)
    p_compare = sub.add_parser("compare")
    p_compare.add_argument("base", type=Path)
    p_compare.add_argument("head", type=Path)
    p_report = sub.add_parser("report")
    p_report.add_argument("base", type=Path, help="directory of the base commit's counter sidecars")
    p_report.add_argument("head", type=Path, help="directory of the head commit's counter sidecars")
    args = parser.parse_args(argv)

    if args.command == "report":
        print("\n".join(report(args.base, args.head)))
        return 0
    if args.command == "compare":
        differences = compare(args.base, args.head)
        for line in differences:
            print(line)
        return 1 if differences else 0
    scenarios = load_scenarios()
    if args.command == "corpus":
        chosen = [s for s in scenarios if args.only is None or s["id"] in args.only]
        result = run_corpus(args.country, args.out, chosen)
    elif args.command == "cohort":
        rest = [a for a in args.simulate_args if a != "--"]
        result = run_cohort(rest)
    else:
        missing = check(args.files, scenarios)
        for line in missing:
            print(f"NOT FIRED  {line}")
        return 1 if missing else 0
    args.counters.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
