"""``clinosim list-diseases``: list the disease protocols and encounter conditions."""

from __future__ import annotations

import argparse
from typing import Any

from clinosim.locale.localized import localized
from clinosim.simulator.helpers import load_all_disease_protocols


def register(sub: argparse._SubParsersAction) -> None:
    # === list-diseases: show available disease protocols ===
    ld = sub.add_parser("list-diseases", help="List all available disease protocols")
    ld.set_defaults(handler=run)


def run(args: Any, parser: argparse.ArgumentParser) -> None:
    protocols = load_all_disease_protocols()
    print(f"\n{len(protocols)} inpatient disease protocols:")
    for name in sorted(protocols.keys()):
        p = protocols[name]
        # chief_complaint is `str | dict[str, str]` (multi-lang variant).
        # Coerce to str for the compact list display.
        cc = p.chief_complaint
        cc_str = cc if isinstance(cc, str) else (localized(cc, "en"))
        print(f"  {name:35s} | {cc_str[:50]}")

    from clinosim.modules.encounter.protocol import load_all_encounter_conditions

    ed_conditions = load_all_encounter_conditions()
    print(f"\n{len(ed_conditions)} ED/outpatient encounter conditions:")
    for name in sorted(ed_conditions.keys()):
        c = ed_conditions[name]
        print(f"  {name:35s} | {c.get('chief_complaint', '')[:50]}")
    return
