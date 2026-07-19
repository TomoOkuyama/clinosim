#!/usr/bin/env python3
"""Refresh the YJ authoritative snapshot from a local tx-server-build copy.

Usage:
    python scripts/refresh_authoritative_yj.py \
        [--source-package-dir PATH] [--dry-run]

The default `--source-package-dir` points at the sibling `fhir-jp-validator`
checkout at `../fhir-jp-validator/`. Fetch it once via
`git clone https://github.com/iryohjoho/fhir-jp-validator ../fhir-jp-validator`
(or update it in place).

The script:
- Reads `CodeSystem-jp-medicationcodeyj-cs.json` from the resolved package.
- Reads `clinosim/codes/data/yj.yaml` to determine clinosim's emit surface.
- Filters the CS concept list to codes clinosim references.
- Writes `clinosim/codes/authoritative/yj_tx_fragment.json` with a metadata
  block noting the source, package version, and extraction date.

Non-interactive. Deterministic (sorted output, stable JSON formatting).
Companion documentation: `docs/design-guides/code-display-authoritative-sync.md`.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_SOURCE_ROOT = _REPO_ROOT.parent / "fhir-jp-validator"
_TX_SUBPATH = Path("tx-server-build/terminology/fhir-server")
_YJ_PACKAGE_GLOB = "jpfhir-terminology#*/package/CodeSystem-jp-medicationcodeyj-cs.json"
_CURATED_YAML = _REPO_ROOT / "clinosim" / "codes" / "data" / "yj.yaml"
_SNAPSHOT_PATH = _REPO_ROOT / "clinosim" / "codes" / "authoritative" / "yj_tx_fragment.json"


def _resolve_source_cs(source_root: Path) -> tuple[Path, str]:
    """Locate `CodeSystem-jp-medicationcodeyj-cs.json` and return (path, package version)."""
    tx = source_root / _TX_SUBPATH
    if not tx.is_dir():
        raise SystemExit(
            f"tx-server-build tree not found at {tx}. Pass --source-package-dir or "
            f"clone fhir-jp-validator alongside this repo."
        )
    matches = sorted(tx.glob(_YJ_PACKAGE_GLOB))
    if not matches:
        raise SystemExit(f"No YJ CodeSystem found under {tx}")
    latest = matches[-1]
    # `jpfhir-terminology#2.2606.0/package/…` — extract the version between # and /package.
    parts = latest.parts
    for p in parts:
        if p.startswith("jpfhir-terminology#"):
            version = p.split("#", 1)[1]
            return latest, f"jpfhir-terminology {version}"
    return latest, "jpfhir-terminology (version unknown)"


def _load_curated_codes() -> set[str]:
    with _CURATED_YAML.open() as f:
        data = yaml.safe_load(f) or {}
    return {str(k) for k in (data.get("codes") or {}).keys()}


def _build_snapshot(cs_path: Path, source_package: str) -> dict:
    with cs_path.open() as f:
        cs = json.load(f)
    clinosim_codes = _load_curated_codes()
    concepts = cs.get("concept", []) or []
    in_scope = sorted(
        (c for c in concepts if isinstance(c, dict) and c.get("code") in clinosim_codes),
        key=lambda c: c["code"],
    )
    fragment_codes = {c.get("code") for c in concepts if isinstance(c, dict)}
    missing = sorted(clinosim_codes - fragment_codes)
    return {
        "metadata": {
            "source_package": source_package,
            "source_url": cs.get("url"),
            "source_file": cs_path.name,
            "source_content_mode": cs.get("content"),
            "fetched_from": "https://github.com/iryohjoho/fhir-jp-validator tx-server-build/",
            "extracted_at": date.today().isoformat(),
            "clinosim_codes_total": len(clinosim_codes),
            "clinosim_codes_in_fragment": len(in_scope),
            "clinosim_codes_missing_from_fragment": missing,
            "note": (
                "Fragment of the CodeSystem filtered to codes clinosim currently "
                "emits (yj.yaml). Codes marked as missing are outside the tx-server's "
                "loaded fragment — display verification skips them."
            ),
        },
        "concept": in_scope,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-package-dir",
        type=Path,
        default=_DEFAULT_SOURCE_ROOT,
        help=f"Root of a fhir-jp-validator checkout (default: {_DEFAULT_SOURCE_ROOT})",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print but do not write")
    args = parser.parse_args()

    cs_path, source_package = _resolve_source_cs(args.source_package_dir)
    print(f"source CodeSystem: {cs_path}", file=sys.stderr)
    print(f"source package: {source_package}", file=sys.stderr)

    snapshot = _build_snapshot(cs_path, source_package)
    meta = snapshot["metadata"]
    print(
        f"clinosim codes: {meta['clinosim_codes_total']} "
        f"(in fragment {meta['clinosim_codes_in_fragment']}, "
        f"missing {len(meta['clinosim_codes_missing_from_fragment'])})",
        file=sys.stderr,
    )

    if args.dry_run:
        print("--dry-run: not writing.", file=sys.stderr)
        return 0

    _SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _SNAPSHOT_PATH.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"wrote {_SNAPSHOT_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
