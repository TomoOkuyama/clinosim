#!/usr/bin/env python3
"""Refresh clinosim/codes/authoritative/yj_tx_valid_codes.json.

Extracts the tx-server-verifiable YJ code set from the fhir-jp-validator
tx-server package (jpfhir-terminology 2.2606.0's
`CodeSystem-jp-medicationcodeyj-cs.json`), a `content=fragment` snapshot
of 2000 concepts out of the full 25542-concept YJ CodeSystem.

Session 59 #283:used by `_fhir_medications._is_tx_server_verified_yj`
to gate whether to emit under the JP-CLINS eCS `codingYJ` slice (verified)
or fall back to the `nocoded` slice (unverified — drug name preserved in
`medicationCodeableConcept.text`).

Usage:
    python scripts/refresh_authoritative_yj_tx_valid.py
        [--source PATH]  # tx-server CS file (default: local sibling checkout)
        [--dry-run]      # print delta, do not write
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

DEFAULT_SOURCE = (
    Path(__file__).resolve().parent.parent.parent
    / "fhir-jp-validator"
    / "tx-server-build"
    / "terminology-2"
    / "fhir-server"
    / "jpfhir-terminology#2.2606.0"
    / "package"
    / "CodeSystem-jp-medicationcodeyj-cs.json"
)
TARGET = (
    Path(__file__).resolve().parent.parent
    / "clinosim"
    / "codes"
    / "authoritative"
    / "yj_tx_valid_codes.json"
)
CLINOSIM_YJ_YAML = (
    Path(__file__).resolve().parent.parent / "clinosim" / "codes" / "data" / "yj.yaml"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--extracted-at", default="2026-07-19")
    args = parser.parse_args()

    if not args.source.is_file():
        raise SystemExit(f"source not found: {args.source}")
    src = json.loads(args.source.read_text())
    tx_codes = sorted({c["code"] for c in src.get("concept", []) if c.get("code")})
    print(f"tx-server YJ CS fragment: {len(tx_codes)} concepts")

    clinosim_yj = set((yaml.safe_load(CLINOSIM_YJ_YAML.read_text()) or {}).get("codes", {}).keys())
    verified = clinosim_yj & set(tx_codes)
    missing = clinosim_yj - set(tx_codes)
    print(f"clinosim yj.yaml: {len(clinosim_yj)} codes")
    print(f"  verified: {len(verified)}")
    print(f"  missing (would use nocoded fallback): {len(missing)}")

    out = {
        "metadata": {
            "source_package": "jpfhir-terminology 2.2606.0",
            "source_url": src.get("url"),
            "source_file": args.source.name,
            "source_content_mode": src.get("content"),
            "source_content_note": (
                "The tx-server ships this CodeSystem as content=fragment. The upstream "
                "note reads '最初の2000 件だけの表示に限定(fragment化)' out of 25542 total "
                "concepts. The fragment is scoped to therapeutic areas 11xx/12xx "
                "(psychiatric/neurological drugs). Codes clinosim emits outside these "
                "ranges (cardiovascular/respiratory/etc.) cannot be verified upstream, "
                "so JP MedicationRequest / MedicationAdministration emit paths fall "
                "back to the JP-CLINS eCS 'nocoded' slice for those codes (drug name "
                "preserved in medicationCodeableConcept.text)."
            ),
            "fetched_from": "https://github.com/iryohjoho/fhir-jp-validator tx-server-build/",
            "extracted_at": args.extracted_at,
            "clinosim_codes_total": len(clinosim_yj),
            "clinosim_codes_in_source": len(verified),
            "clinosim_codes_missing_from_source": sorted(missing),
            "tx_server_codes_total": len(tx_codes),
            "note": (
                "Used by clinosim/modules/output/_fhir_medications."
                "_is_tx_server_verified_yj to gate whether to emit under the "
                "codingYJ slice (verified) or the nocoded slice (unverified but "
                "drug name preserved in text). Session 59 #283."
            ),
        },
        "codes": tx_codes,
    }

    if args.dry_run:
        print("--dry-run: not writing")
        return
    TARGET.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
