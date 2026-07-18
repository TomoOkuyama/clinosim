#!/usr/bin/env python3
"""Refresh the LOINC 2.82 authoritative snapshot from a local tx-server-build copy.

Usage:
    python scripts/refresh_authoritative_loinc.py \
        [--source-package-dir PATH] [--dry-run]

The default `--source-package-dir` points at the sibling `fhir-jp-validator`
checkout at `../fhir-jp-validator/`. LOINC is redistributed with the
`tx-server-build/loinc-src/Loinc_2.82/` tree (governed by the LOINC License,
freely available).

The script:
- Reads every `.yaml` and Python source under `clinosim/` where LOINC codes
  can legitimately appear (loinc.yaml, code_mapping_lab.yaml,
  code_mapping_microbiology_susceptibility.yaml, microbiology.yaml,
  body_sites.yaml, _fhir_composition.py, _fhir_nursing.py).
- Filters the LOINC master to codes clinosim references (~170).
- Writes `clinosim/codes/authoritative/loinc_2_82_tx.json` with per-code
  `display` (LONG_COMMON_NAME), `short_display` (SHORTNAME), and `status`
  fields.

Deterministic (sorted output). NEWS2 (`90557-9`) is a known gap not present
in LOINC 2.82 (tracked separately in Issue #269) and excluded from the
snapshot's `concept` list.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_SOURCE_ROOT = _REPO_ROOT.parent / "fhir-jp-validator"
_LOINC_CSV_SUBPATH = Path("tx-server-build/loinc-src/Loinc_2.82/LoincTable/Loinc.csv")
_SNAPSHOT_PATH = _REPO_ROOT / "clinosim" / "codes" / "authoritative" / "loinc_2_82_tx.json"

_LOINC_HOLDING_FILES = [
    "clinosim/codes/data/loinc.yaml",
    "clinosim/locale/us/code_mapping_lab.yaml",
    "clinosim/locale/jp/code_mapping_lab.yaml",
    "clinosim/locale/shared/code_mapping_lab.yaml",
    "clinosim/locale/jp/code_mapping_microbiology_susceptibility.yaml",
    "clinosim/modules/observation/reference_data/microbiology.yaml",
    "clinosim/modules/imaging/reference_data/body_sites.yaml",
]
_LOINC_HOLDING_PY = [
    "clinosim/modules/output/_fhir_composition.py",
    "clinosim/modules/output/_fhir_nursing.py",
]

_LOINC_CODE_RE = re.compile(r"^\d{2,7}-\d$")
_LOINC_LITERAL_RE = re.compile(r'"(\d{2,7}-\d)"')

_KNOWN_GAP_NOT_IN_LOINC_282: set[str] = {"90557-9"}


def _collect_clinosim_codes(repo_root: Path) -> set[str]:
    codes: set[str] = set()
    for relpath in _LOINC_HOLDING_FILES:
        p = repo_root / relpath
        if not p.exists():
            continue
        with p.open() as f:
            try:
                data = yaml.safe_load(f) or {}
            except Exception:
                continue

        def walk(node: object) -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    if isinstance(k, str) and _LOINC_CODE_RE.match(k):
                        codes.add(k)
                    if isinstance(v, str) and _LOINC_CODE_RE.match(v):
                        codes.add(v)
                    walk(v)
            elif isinstance(node, list):
                for it in node:
                    walk(it)

        walk(data)
    for relpath in _LOINC_HOLDING_PY:
        p = repo_root / relpath
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            for m in _LOINC_LITERAL_RE.finditer(line):
                codes.add(m.group(1))
    return codes


def _load_loinc_master(csv_path: Path) -> dict[str, dict[str, str]]:
    lookup: dict[str, dict[str, str]] = {}
    with csv_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            code = row.get("LOINC_NUM")
            if code:
                lookup[code] = row
    return lookup


def _build_snapshot(source_root: Path, repo_root: Path) -> dict:
    csv_path = source_root / _LOINC_CSV_SUBPATH
    if not csv_path.exists():
        raise SystemExit(f"LOINC master not found at {csv_path}")
    lookup = _load_loinc_master(csv_path)
    clinosim_codes = _collect_clinosim_codes(repo_root)
    concepts = []
    missing: list[str] = []
    for code in sorted(clinosim_codes):
        if code in _KNOWN_GAP_NOT_IN_LOINC_282:
            continue
        row = lookup.get(code)
        if not row:
            missing.append(code)
            continue
        concepts.append(
            {
                "code": code,
                "display": row.get("LONG_COMMON_NAME") or row.get("COMPONENT"),
                "short_display": row.get("SHORTNAME"),
                "status": row.get("STATUS"),
            }
        )
    return {
        "metadata": {
            "source_package": "LOINC 2.82",
            "source_url": "http://loinc.org",
            "source_file": "Loinc_2.82/LoincTable/Loinc.csv",
            "source_content_mode": "complete",
            "source_content_note": (
                "The LOINC master ships complete (~109k codes). The snapshot "
                "filters to codes clinosim emits so shipped size stays small. "
                "Codes marked missing indicate clinosim references a LOINC code "
                "that does not exist in LOINC 2.82 (retired / renumbered / "
                "fabricated) — treat as regression and open an issue."
            ),
            "fetched_from": "https://github.com/iryohjoho/fhir-jp-validator tx-server-build/loinc-src/",
            "extracted_at": date.today().isoformat(),
            "clinosim_codes_total": len(clinosim_codes)
            - len(_KNOWN_GAP_NOT_IN_LOINC_282 & clinosim_codes),
            "clinosim_codes_in_source": len(concepts),
            "clinosim_codes_missing_from_source": missing,
            "clinosim_known_gaps_not_in_loinc_2_82": sorted(
                _KNOWN_GAP_NOT_IN_LOINC_282 & clinosim_codes
            ),
            "note": (
                "LOINC 2.82 authoritative displays for codes clinosim emits. "
                "Includes `status` so downstream tests can WARN on non-ACTIVE."
            ),
        },
        "concept": concepts,
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

    snapshot = _build_snapshot(args.source_package_dir, _REPO_ROOT)
    meta = snapshot["metadata"]
    print(
        f"clinosim LOINC codes: {meta['clinosim_codes_total']} "
        f"(in source {meta['clinosim_codes_in_source']}, "
        f"missing {len(meta['clinosim_codes_missing_from_source'])}, "
        f"known gap {len(meta['clinosim_known_gaps_not_in_loinc_2_82'])})",
        file=sys.stderr,
    )
    if meta["clinosim_codes_missing_from_source"]:
        print(
            f"MISSING codes (regression): {meta['clinosim_codes_missing_from_source']}",
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
