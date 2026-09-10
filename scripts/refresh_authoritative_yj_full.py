#!/usr/bin/env python3
"""Refresh clinosim/codes/authoritative/JP_MedicationCodeYJ_CS_full.json.

Builds a ``content=complete`` FHIR R4 CodeSystem for the JP-national YJ code
registry from the MEDIS 医薬品HOTコードマスター (public download at
https://www2.medis.or.jp/hcode/), which is the same upstream registry the
tx-server ships as ``content=fragment`` (first 2000 / 25,542 concepts) in
jpfhir-terminology 2.2606.0.

Issue #1220 (2026-09-10, JP p=10000 audit): the tx-server-fragment gate
downgraded 41.8 % of MedicationRequest / 25.1 % of MedicationAdministration
to the JP-CLINS eCS ``nocoded`` slice for clinosim-emitted YJ codes outside
the shipped fragment. Shipping the full CS as a clinosim artifact lets the
FHIR emit path always populate the ``codingYJ`` slice with a real MHLW YJ
code (semantic accuracy) and lets a validator resolve the ``required``
binding on ``codingYJ.code`` against the full JP_MedicationCodeYJ_VS
(spec-clean).

Source
------
MEDIS HOT Code Master (医薬品HOTコードマスター) — public download from
https://www2.medis.or.jp/hcode/ . The archive contains
``MEDIS<YYYYMMDD>.TXT`` (CSV, CP932-encoded) with 24-25k unique 12-char YJ
codes (column ``個別医薬品コード``) and their canonical display (column
``告示名称``). Distribution / attribution: MEDIS-DC standard master.
Contact: hot@medis.or.jp for licensing questions.

Usage
-----
    # 1. Download and extract the master (once per refresh):
    #     wget https://www2.medis.or.jp/hcode/moto_data/h<YYYYMMDD>.zip
    #     unzip h<YYYYMMDD>.zip
    #
    # 2. Run this script:
    python scripts/refresh_authoritative_yj_full.py \\
        --source h<YYYYMMDD>/MEDIS<YYYYMMDD>.TXT

Downstream
----------
The generated CodeSystem should be loaded into any FHIR validator config
that validates clinosim's JP FHIR output — via ``clinical_terminology`` IG
package precedence or by adding
``clinosim/codes/authoritative/JP_MedicationCodeYJ_CS_full.json`` to the
validator's terminology chain ahead of tx-server's fragment CS.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import date
from pathlib import Path

DEFAULT_TARGET = (
    Path(__file__).resolve().parent.parent / "clinosim" / "codes" / "authoritative" / "JP_MedicationCodeYJ_CS_full.json"
)

# Canonical URL identifying the JP national YJ CodeSystem — same URL as the
# tx-server-shipped fragment, so a validator that prefers this file over the
# tx-server package will get the complete concept set (no fragment gap).
YJ_CANONICAL_URL = "http://capstandard.jp/iyaku.info/CodeSystem/YJ-code"

# MEDIS master column indices (verified against 2026-08-31 layout).
COL_YJ = 7  # 個別医薬品コード (12-char YJ)
COL_DISPLAY = 10  # 告示名称 (canonical drug name)

WELLFORMED_YJ_RE = re.compile(r"^\d{7}[A-Z]\d{4}$")


def _extract_version_from_source(source: Path) -> str:
    """Derive a FHIR CodeSystem.version from the MEDIS filename.

    Filenames follow ``MEDIS<YYYYMMDD>.TXT`` — the calendar date is the
    natural version identifier.
    """
    stem = source.stem  # e.g. "MEDIS20260831"
    if stem.startswith("MEDIS") and len(stem) >= 13 and stem[5:13].isdigit():
        y, m, d = stem[5:9], stem[9:11], stem[11:13]
        return f"{y}.{int(m)}.{int(d)}"
    return date.today().isoformat()


def _read_medis_master(source: Path) -> dict[str, str]:
    """Return ``{yj_code: canonical_display}`` extracted from the MEDIS master.

    Reads the TXT as CP932 (Windows Shift-JIS with 半角カナ), which is the
    encoding MEDIS ships. Only well-formed 12-char YJ codes are kept
    (``^\\d{7}[A-Z]\\d{4}$`` per the JP Core NamingSystem shape); malformed
    or empty entries are skipped silently. First non-empty display per YJ
    wins (the master has multiple rows per YJ for different packages /
    manufacturers; the first canonical name is representative).
    """
    yj_display: dict[str, str] = {}
    with source.open("r", encoding="cp932", errors="replace") as f:
        reader = csv.reader(f)
        _header = next(reader)
        for row in reader:
            if len(row) <= max(COL_YJ, COL_DISPLAY):
                continue
            yj = row[COL_YJ].strip()
            if not yj or not WELLFORMED_YJ_RE.match(yj):
                continue
            display = row[COL_DISPLAY].strip()
            if yj in yj_display:
                continue
            yj_display[yj] = display
    return yj_display


def _build_code_system(yj_display: dict[str, str], version: str, source: Path) -> dict:
    """Assemble the FHIR R4 CodeSystem JSON with ``content=complete``."""
    concept = [{"code": code, "display": display or code} for code, display in sorted(yj_display.items())]
    return {
        "resourceType": "CodeSystem",
        "id": "jp-medicationcodeyj-cs-full",
        "url": YJ_CANONICAL_URL,
        "version": version,
        "name": "JP_MedicationCodeYJ_CS",
        "title": "JP MedicationCodeYJ CodeSystem (full, MEDIS-sourced)",
        "status": "active",
        "experimental": False,
        "content": "complete",
        "description": (
            "Full JP national YJ (個別医薬品コード) CodeSystem sourced from the "
            "MEDIS 医薬品HOTコードマスター. Ships as a clinosim artifact so any "
            "downstream validator can resolve JP_MedicationCodeYJ_VS "
            "against the complete concept set — the tx-server-shipped CS "
            "(jpfhir-terminology 2.2606.0) is content=fragment and covers "
            "only the first 2000 codes."
        ),
        "copyright": (
            "YJ codes and canonical displays sourced from MEDIS-DC 医薬品"
            "HOTコードマスター (https://www2.medis.or.jp/hcode/). MEDIS-DC "
            "retains ownership; clinosim redistributes for FHIR terminology "
            "resolution alongside the upstream tx-server fragment. Contact "
            "hot@medis.or.jp for licensing questions."
        ),
        "count": len(concept),
        "concept": concept,
        "meta": {
            "source_file": source.name,
            "source_registry": "MEDIS 医薬品HOTCodeMaster",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Path to the MEDIS <YYYYMMDD>.TXT (CP932 CSV) extracted from the HOT master ZIP.",
    )
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.source.is_file():
        raise SystemExit(f"source not found: {args.source}")

    yj_display = _read_medis_master(args.source)
    if not yj_display:
        raise SystemExit(f"no YJ codes extracted from {args.source} — check column layout")

    version = _extract_version_from_source(args.source)
    cs = _build_code_system(yj_display, version, args.source)

    if args.dry_run:
        print(f"[dry-run] would write {args.target} with {len(yj_display)} concepts (version={version})")
        return

    args.target.parent.mkdir(parents=True, exist_ok=True)
    args.target.write_text(json.dumps(cs, ensure_ascii=False, indent=2, sort_keys=False))
    print(f"wrote {args.target} — {len(yj_display)} concepts, version={version}")


if __name__ == "__main__":
    main()
