#!/usr/bin/env python3
"""Refresh clinosim/codes/authoritative/yj_medis_hot_used.json.

The file lists the YJ codes (個別医薬品コード) that clinosim uses — the codes of
``clinosim/codes/data/yj.yaml`` — which the MEDIS 医薬品HOTコードマスター lists.
``clinosim.codes.yj.is_verified_yj`` reads it to decide whether a JP drug code
is emitted in the YJ slice or in the JP-CLINS eCS ``nocoded`` slice (Issues
#1220, #4026). The complete code system is not shipped.

What is copied: only the code. The ``name`` of each entry is the ``ja`` name
``yj.yaml`` already curates; no other text of the master is written.

Source
------
MEDIS HOT Code Master (医薬品HOTコードマスター), download page
https://www2.medis.or.jp/hcode/ . The archive ``h<YYYYMMDD>.zip`` contains
``MEDIS<YYYYMMDD>.TXT`` (CSV, CP932-encoded); the 12-character YJ code is the
column ``個別医薬品コード`` (index 7 in the 2026-08-31 layout — check the
header of the edition you read).

Usage
-----
    # 1. Download and extract the master:
    #     https://www2.medis.or.jp/hcode/moto_data/h<YYYYMMDD>.zip
    # 2. Check the registry against it and write the subset:
    python scripts/refresh_authoritative_yj_used.py \\
        --source h<YYYYMMDD>/MEDIS<YYYYMMDD>.TXT --fetched <YYYY-MM-DD>

The script exits non-zero and writes nothing when a ``yj.yaml`` code is not in
the master: such a code is not a verified YJ code (remove it, or keep the drug
in the ``nocoded`` slice).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import date
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parent.parent
DEFAULT_TARGET = _REPO / "clinosim" / "codes" / "authoritative" / "yj_medis_hot_used.json"
REGISTRY = _REPO / "clinosim" / "codes" / "data" / "yj.yaml"

YJ_CANONICAL_URL = "http://capstandard.jp/iyaku.info/CodeSystem/YJ-code"
COL_YJ = 7  # 個別医薬品コード (12-char YJ), 2026-08-31 layout
WELLFORMED_YJ_RE = re.compile(r"^\d{7}[A-Z]\d{4}$")


def _edition_from_source(source: Path) -> str:
    """``MEDIS<YYYYMMDD>.TXT`` → ``YYYY.M.D`` (the form the earlier full
    CodeSystem recorded as its version)."""
    stem = source.stem
    if stem.startswith("MEDIS") and len(stem) >= 13 and stem[5:13].isdigit():
        y, m, d = stem[5:9], stem[9:11], stem[11:13]
        return f"{y}.{int(m)}.{int(d)}"
    raise SystemExit(f"cannot read the edition from {source.name}; expected MEDIS<YYYYMMDD>.TXT")


def _master_codes(source: Path) -> set[str]:
    """The well-formed YJ codes of the master's ``個別医薬品コード`` column."""
    codes: set[str] = set()
    with source.open("r", encoding="cp932", errors="replace") as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if len(row) > COL_YJ and WELLFORMED_YJ_RE.match(row[COL_YJ].strip()):
                codes.add(row[COL_YJ].strip())
    return codes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True, help="MEDIS<YYYYMMDD>.TXT from the HOT master ZIP")
    parser.add_argument("--fetched", required=True, help="date the master was downloaded (YYYY-MM-DD)")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.source.is_file():
        raise SystemExit(f"source not found: {args.source}")

    master = _master_codes(args.source)
    if not master:
        raise SystemExit(f"no YJ codes read from {args.source}; check the column layout")
    registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))["codes"]
    missing = sorted(set(registry) - master)
    if missing:
        raise SystemExit(f"{len(missing)} yj.yaml codes are not in {args.source.name}: {missing}")

    doc = {
        "metadata": {
            "system": YJ_CANONICAL_URL,
            "scope": "subset: the YJ codes of clinosim/codes/data/yj.yaml that the MEDIS master lists (Issue #4026)",
            "source_package": "MEDIS-DC 医薬品HOTコードマスター",
            "source_file": args.source.name,
            "edition": _edition_from_source(args.source),
            "fetched": args.fetched,
            "extracted_at": date.today().isoformat(),
            "provenance": f"Codes of yj.yaml checked against the 個別医薬品コード column of {args.source.name}.",
            "name": "the ja name of the code in codes/data/yj.yaml (clinosim-curated); "
            "no other text of the master is copied",
            "verify_new_code": "clinosim/codes/authoritative/README.md, section 'Verifying a new YJ code'",
        },
        "concept": [{"code": c, "name": registry[c]["ja"]} for c in sorted(registry)],
    }
    if args.dry_run:
        print(f"[dry-run] {len(doc['concept'])} codes, all in the master (edition {doc['metadata']['edition']})")
        return
    with args.target.open("w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"wrote {args.target}: {len(doc['concept'])} codes, edition {doc['metadata']['edition']}")


if __name__ == "__main__":
    main()
