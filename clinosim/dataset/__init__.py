"""``clinosim dataset`` — named-preset dataset builder.

Presets live under ``datasets/<name>/spec.yaml`` at the repository root.
Each spec is a thin declaration of the parameters ``clinosim generate``
would use — country, population, seed, date range, output format.

The CLI does not add any generation capability of its own; it exists
purely so a user can run

    clinosim dataset build jp-100 --output ./jp-100-out

instead of having to remember the six command-line arguments that make
`jp-100` the reproducible preset it is. Presets are the versioned
public API for dataset releases; see ``datasets/README.md`` for the
full list.

Public functions:

- :func:`list_presets` — enumerate available preset names
- :func:`load_preset` — load and validate a single preset YAML
- :func:`add_dataset_subparser` — hook the CLI subparser
- :func:`dispatch_dataset` — argparse dispatch handler
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

# Preset root is resolved at import time so subprocess / test callers see the
# same location the interactive CLI does. `parents[2]` walks
# clinosim/dataset/__init__.py → clinosim/dataset → clinosim → <repo root>.
_PRESETS_DIR = Path(__file__).resolve().parents[2] / "datasets"


@dataclass(frozen=True)
class DatasetPreset:
    """Validated parameters for one dataset preset."""

    name: str
    description: str
    country: str
    population: int
    seed: int
    start: str
    end: str
    format: str

    def as_generate_args(self, output: str) -> list[str]:
        """Return the ``clinosim generate ...`` argv this preset expands to."""
        return [
            "generate",
            "--country", self.country,
            "--population", str(self.population),
            "--seed", str(self.seed),
            "--start", self.start,
            "--end", self.end,
            "--output", output,
            "--format", self.format,
        ]


def list_presets(presets_dir: Path | None = None) -> list[str]:
    """Return sorted preset names discoverable under ``datasets/``."""
    root = presets_dir or _PRESETS_DIR
    if not root.exists():
        return []
    return sorted(
        p.name for p in root.iterdir()
        if p.is_dir() and (p / "spec.yaml").exists()
    )


def load_preset(name: str, presets_dir: Path | None = None) -> DatasetPreset:
    """Load and validate the preset ``name``. Raises :class:`ValueError` on
    missing preset or malformed spec."""
    root = presets_dir or _PRESETS_DIR
    spec_path = root / name / "spec.yaml"
    if not spec_path.exists():
        available = list_presets(root)
        raise ValueError(
            f"unknown dataset preset {name!r}; available: "
            f"{', '.join(available) if available else '(none)'}"
        )
    raw = yaml.safe_load(spec_path.read_text()) or {}

    required = ("name", "description", "country", "population",
                "seed", "start", "end", "format")
    missing = [k for k in required if k not in raw]
    if missing:
        raise ValueError(
            f"preset {name!r} spec.yaml is missing required key(s): "
            f"{', '.join(missing)}"
        )
    if raw["name"] != name:
        raise ValueError(
            f"preset {name!r} spec.yaml declares name={raw['name']!r}; "
            "directory name and spec name must match."
        )
    return DatasetPreset(
        name=str(raw["name"]),
        description=str(raw["description"]),
        country=str(raw["country"]),
        population=int(raw["population"]),
        seed=int(raw["seed"]),
        start=str(raw["start"]),
        end=str(raw["end"]),
        format=str(raw["format"]),
    )


def add_dataset_subparser(sub: argparse._SubParsersAction) -> None:
    """Register the ``dataset`` subparser (called from
    :mod:`clinosim.simulator.cli`)."""
    ds = sub.add_parser(
        "dataset",
        help="Build a named preset dataset (see datasets/ at repo root).",
    )
    ds_sub = ds.add_subparsers(dest="dataset_command", required=True)

    ds_sub.add_parser(
        "list", help="List available dataset preset names."
    )

    build = ds_sub.add_parser(
        "build", help="Build one preset dataset by name."
    )
    build.add_argument(
        "name",
        help="Preset name (e.g. jp-100). Use `clinosim dataset list` to enumerate.",
    )
    build.add_argument(
        "-o", "--output", required=True,
        help="Output directory; overwritten if it exists.",
    )


def dispatch_dataset(args: argparse.Namespace) -> int:
    """Handle ``clinosim dataset ...`` invocation. Returns process exit code."""
    if args.dataset_command == "list":
        names = list_presets()
        if not names:
            print("(no dataset presets found under datasets/)")
            return 0
        for name in names:
            try:
                preset = load_preset(name)
                print(f"{preset.name:12s}  {preset.description}")
            except ValueError as exc:
                print(f"{name:12s}  <malformed: {exc}>", file=sys.stderr)
        return 0

    if args.dataset_command == "build":
        try:
            preset = load_preset(args.name)
        except ValueError as exc:
            print(f"clinosim dataset build: {exc}", file=sys.stderr)
            return 2

        # Rebuild the argv `clinosim generate` would see, then reuse the main
        # CLI dispatcher so the generate code path stays single-sourced.
        gen_argv = preset.as_generate_args(args.output)
        print(
            f"clinosim dataset build: {preset.name} — "
            f"country={preset.country} population={preset.population} "
            f"seed={preset.seed} {preset.start}..{preset.end} format={preset.format} "
            f"-> {args.output}"
        )

        # Delayed import to avoid a circular import at CLI parse time.
        from clinosim.simulator.cli import main as _cli_main
        original_argv = sys.argv[:]
        try:
            sys.argv = [sys.argv[0], *gen_argv]
            _cli_main()
        finally:
            sys.argv = original_argv
        return 0

    print(f"unknown dataset subcommand: {args.dataset_command}", file=sys.stderr)
    return 2
