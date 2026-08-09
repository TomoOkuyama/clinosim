"""CLI subcommand handler: `clinosim regenerate-goldens`.

Split from `clinosim/simulator/cli.py` — see PR K.
"""

from __future__ import annotations

import os
import sys
from typing import Any


def _run_regenerate_goldens(args: Any) -> None:
    """AD-66 α-min-2c T3: regenerate narrative goldens for canonical profiles.

    For each target profile: run test-disease pipeline into a tmpdir, walk
    cif/narratives/<version>/documents/**/*.json, write the merged dict to
    the golden path in the fixture dir. Emits stderr note prompting user to
    `git diff + commit if intentional`.

    β-JP-1 chain 1b T1: ``--provider mock|bedrock|ollama`` inserts a
    ``narrate --provider`` subprocess step on top of the structural CIF and
    writes ``<profile>.llm-<tag>.golden.json`` instead (template golden
    naming unchanged). ``<tag>`` defaults to the provider name; override
    with ``--model-tag`` (e.g. a real model id on the remote LLM server).
    """
    import json
    import subprocess
    import tempfile

    from clinosim.types.config import _PATIENT_PROFILE_DIR, load_patient_profile

    if getattr(args, "patient_filter", None):
        print(
            "ERROR: regenerate-goldens must never write partial goldens — "
            "--patient-filter is not allowed here. Iterate with "
            "`clinosim narrate --patient-filter`, then regenerate WITHOUT a filter",
            file=sys.stderr,
        )
        sys.exit(2)

    provider: str = getattr(args, "provider", "template")
    if provider == "template" and (args.model_tag or args.llm_config):
        print(
            "ERROR: --model-tag / --llm-config require an LLM --provider "
            "(mock/bedrock/ollama); they have no effect with --provider template",
            file=sys.stderr,
        )
        sys.exit(2)
    tag = args.model_tag or provider

    # Support env var override for test isolation
    fixture_dir_env = os.environ.get("CLINOSIM_PATIENT_PROFILE_DIR")
    from pathlib import Path

    fixture_dir = Path(fixture_dir_env) if fixture_dir_env else _PATIENT_PROFILE_DIR

    if args.all:
        profile_paths = sorted(p for p in fixture_dir.glob("*.yaml") if not p.name.endswith(".llm-expectations.yaml"))
    else:
        p = fixture_dir / f"{args.profile}.yaml"
        if not p.is_file():
            print(f"ERROR: profile not found: {p}", file=sys.stderr)
            sys.exit(2)
        profile_paths = [p]

    if not profile_paths:
        print(f"ERROR: no profiles found in {fixture_dir}", file=sys.stderr)
        sys.exit(2)

    def _run_step(cmd: list[str], label: str) -> None:
        """Run one pipeline subprocess; fail loud with its stderr on error."""
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            print(f"ERROR: {label} failed (exit {result.returncode}):", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            sys.exit(1)

    count = 0
    for profile_path in profile_paths:
        profile_id = profile_path.stem
        with tempfile.TemporaryDirectory() as tmpdir:
            _run_step(
                [
                    sys.executable,
                    "-m",
                    "clinosim.simulator.cli",
                    "test-disease",
                    "--patient-profile",
                    str(profile_path),
                    "--format",
                    "cif",
                    "-o",
                    str(tmpdir),
                ],
                label=f"test-disease ({profile_id})",
            )
            cif_dir = Path(tmpdir) / "cif"

            if provider == "template":
                narr_version = "template"
                golden_path = fixture_dir / f"{profile_id}.golden.json"
            else:
                # LLM golden: narrate the structural CIF with the requested
                # provider. Country/seed come from the profile (the pipeline
                # subprocess above already used them for Stage 1).
                narr_version = f"llm-{tag}"
                profile = load_patient_profile(str(profile_path))
                narrate_cmd = [
                    sys.executable,
                    "-m",
                    "clinosim.simulator.cli",
                    "narrate",
                    "--cif-dir",
                    str(cif_dir),
                    "--provider",
                    provider,
                    "--country",
                    profile.country,
                    "--seed",
                    str(profile.random_seed),
                    "--version-id",
                    narr_version,
                    "--no-set-current",
                ]
                if args.llm_config:
                    narrate_cmd += ["--llm-config", args.llm_config]
                _run_step(narrate_cmd, label=f"narrate --provider {provider} ({profile_id})")
                golden_path = fixture_dir / f"{profile_id}.llm-{tag}.golden.json"

            narr_dir = cif_dir / "narratives" / narr_version / "documents"
            actual: dict[str, dict] = {}
            if narr_dir.is_dir():
                for enc_dir in sorted(narr_dir.iterdir()):
                    if not enc_dir.is_dir():
                        continue
                    for doc_file in sorted(enc_dir.iterdir()):
                        if doc_file.suffix != ".json":
                            continue
                        actual[doc_file.stem] = json.loads(doc_file.read_text())

            golden_path.write_text(json.dumps(actual, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
            print(f"regenerated: {golden_path}", file=sys.stderr)

    # Issue #428 (F1): make the variant explicit, and remind authors that
    # narrative-changing PRs must regenerate EACH variant they touch. The old
    # message ("Regenerated 6 golden(s)") looked complete even when it was
    # only 1 of 2 variants — the llm-mock leg fell out of sync without a
    # visible signal until `pytest -m regression` was run.
    variant_name = "template" if provider == "template" else f"llm-{tag}"
    other_variants_hint = (
        "  Other variants (llm-mock, llm-<provider>) were NOT touched. If your\n"
        "  change alters narrative output, rerun with --provider mock (and any\n"
        "  LLM providers you use) or 'pytest -m regression' will fail on the\n"
        "  variants you skipped."
        if provider == "template"
        else "  The `template` variant was NOT touched. Rerun without --provider,\n"
        "  or with --provider template, to regenerate it as well when narrative\n"
        "  output changes."
    )
    print(
        f"Regenerated {count} {variant_name} golden(s). Review + git diff + commit if intentional.\n"
        f"{other_variants_hint}",
        file=sys.stderr,
    )
