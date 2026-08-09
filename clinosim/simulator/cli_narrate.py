"""CLI subcommand handlers: `clinosim narrate` / `check-narratives`.

Split from `clinosim/simulator/cli.py` — see PR K.
"""

from __future__ import annotations

import os
import sys
from typing import Any


def _build_llm_service_for_narrate(provider: str, llm_config: str | None) -> Any:
    """Construct the LLMService behind ``narrate --provider <llm>`` (N-chain).

    Resolution order: explicit ``--llm-config PATH`` wins; otherwise
    bedrock → ``config/llm_service.bedrock.yaml``, ollama →
    ``config/llm_service.yaml``, mock → in-code MockProvider (no YAML).
    """
    from clinosim.modules.llm_service.factory import build_from_config_file

    if llm_config:
        return build_from_config_file(llm_config)
    if provider == "mock":
        from clinosim.modules.llm_service.engine import LLMService
        from clinosim.modules.llm_service.providers import MockProvider

        return LLMService(
            mode="llm",
            narrative_provider=MockProvider(),
            narrative_model_map={"medium": "mock"},
            provider_name_narrative="mock",
        )
    import clinosim

    config_dir = os.path.join(os.path.dirname(os.path.abspath(clinosim.__file__)), "config")
    filename = "llm_service.bedrock.yaml" if provider == "bedrock" else "llm_service.yaml"
    return build_from_config_file(os.path.join(config_dir, filename))


def _run_narrate(args: Any) -> None:
    """Stage 2 handler (AD-65): run a NarrativePass over a structural CIF directory.

    --provider template runs TemplateNarrativeGenerator (deterministic,
    default). bedrock / ollama / mock run LLMNarrativePass backed by an
    LLMService (AD-11) built from config/llm_service*.yaml (or --llm-config).
    """
    from clinosim.modules.document.narrative.passes import (
        LLMNarrativePass,
        TemplateNarrativePass,
    )

    version_id = args.version_id or ("template" if args.provider == "template" else args.provider)
    tasks = [t.strip() for t in args.tasks.split(",")] if args.tasks else None

    # I-1 (chain 1b adv-1): a filtered write into a version dir that already
    # contains documents leaves stale files from the previous generation on
    # disk (mixed version; manifest records only the last run) — refuse
    # unless the user explicitly opts in with --merge-into-version.
    if args.patient_filter:
        documents_dir = os.path.join(args.cif_dir, "narratives", version_id, "documents")
        has_existing_docs = os.path.isdir(documents_dir) and any(os.scandir(documents_dir))
        if has_existing_docs and not args.merge_into_version:
            print(
                f"narrate: ERROR: --patient-filter would write into existing "
                f"version 'narratives/{version_id}/' which already contains "
                "documents. Files not matched by the filter would remain from "
                "the previous generation (stale mixed version) and "
                "manifest.json would record only this run. Use a fresh "
                "--version-id, or pass --merge-into-version to opt in.",
                file=sys.stderr,
            )
            sys.exit(2)
        if has_existing_docs:
            print(
                f"narrate: NOTICE: merging filtered run into existing version "
                f"'narratives/{version_id}/' — mixed-generation files may "
                "coexist and manifest.json reflects only this run.",
                file=sys.stderr,
            )

    pass_impl: TemplateNarrativePass | LLMNarrativePass
    if args.provider == "template":
        pass_impl = TemplateNarrativePass(
            cif_dir=args.cif_dir,
            version_id=version_id,
            country=args.country,
            tasks=tasks,
            rng_seed=args.seed,
            patient_filter=args.patient_filter,
        )
    else:
        llm = _build_llm_service_for_narrate(args.provider, args.llm_config)
        pass_impl = LLMNarrativePass(
            cif_dir=args.cif_dir,
            llm=llm,
            version_id=version_id,
            country=args.country,
            tasks=tasks,
            rng_seed=args.seed,
            patient_filter=args.patient_filter,
        )

    manifest = pass_impl.run()
    # M-3 (N-chain adv-1): tri-state --set-current. None (no flag) resolves to
    # True only for the template provider — an LLM/mock trial must not
    # silently repoint current_version.txt (export-fhir defaults to "current",
    # so a repointed trial would leak mock narratives into production
    # exports). I-1 (chain 1b adv-1): with --patient-filter the default is
    # False for ALL providers — a partial version must not silently become
    # current. Explicit --set-current / --no-set-current always wins.
    if args.set_current is not None:
        set_current = args.set_current
    else:
        set_current = args.provider == "template" and not args.patient_filter
    if set_current and args.patient_filter:
        print(
            f"narrate: WARNING: partial version set as current — "
            f"'narratives/{version_id}/' was generated with --patient-filter "
            f"{args.patient_filter!r}; export-fhir (default 'current') will "
            "find narratives only for matched patients.",
            file=sys.stderr,
        )
    if set_current:
        os.makedirs(os.path.join(args.cif_dir, "narratives"), exist_ok=True)
        with open(os.path.join(args.cif_dir, "narratives", "current_version.txt"), "w") as f:
            f.write(version_id)
        print(f"narrate: current -> {version_id}")
    print(
        f"narrate: wrote {manifest.document_count} narrative documents across "
        f"{manifest.encounter_count} encounters → narratives/{version_id}/"
    )


def _run_check_narratives(args: Any) -> None:
    """β-JP-1 chain 1b T2: semantic check CLI over one narrative version.

    Expectations resolution: explicit ``--expectations PATH`` wins; else
    ``--profile <name>`` resolves ``<fixtures>/<name>.llm-expectations.yaml``
    (CLINOSIM_PATIENT_PROFILE_DIR env override respected, mirroring
    regenerate-goldens); neither → builtin axes only. Exit code: 0 = pass,
    1 = findings, 2 = bad inputs (missing/invalid expectations file).
    """
    import json
    from pathlib import Path

    from clinosim.modules.document.narrative.semantic_check import (
        check_narratives,
        load_expectations,
    )
    from clinosim.types.config import _PATIENT_PROFILE_DIR

    expectations = None
    expectations_path: Path | None = None
    if args.expectations:
        expectations_path = Path(args.expectations)
    elif args.profile:
        fixture_dir_env = os.environ.get("CLINOSIM_PATIENT_PROFILE_DIR")
        fixture_dir = Path(fixture_dir_env) if fixture_dir_env else _PATIENT_PROFILE_DIR
        expectations_path = fixture_dir / f"{args.profile}.llm-expectations.yaml"

    if expectations_path is not None:
        try:
            expectations = load_expectations(expectations_path)
        except FileNotFoundError:
            print(f"ERROR: expectations file not found: {expectations_path}", file=sys.stderr)
            sys.exit(2)
        except ValueError as e:
            print(f"ERROR: invalid expectations file: {e}", file=sys.stderr)
            sys.exit(2)

    report = check_narratives(args.cif_dir, args.version, expectations)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"check-narratives: report written to {args.report}")

    print(
        f"check-narratives: version={args.version} documents={report.document_count} "
        f"findings={len(report.findings)} generator={report.info.get('generator', '?')}"
    )
    for finding in report.findings:
        loc = finding.document_id or "-"
        if finding.section:
            loc += f"/{finding.section}"
        print(f"  [{finding.axis}] {loc}: {finding.message}")

    if not report.passed:
        print("check-narratives: FAIL", file=sys.stderr)
        sys.exit(1)
    print("check-narratives: PASS")
