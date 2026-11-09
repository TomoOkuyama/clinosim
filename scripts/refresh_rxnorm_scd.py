#!/usr/bin/env python3
"""Build the RxNorm SCD table from RxNav (Issue #2614).

Usage:
    python scripts/refresh_rxnorm_scd.py [--dry-run]

For every drug in ``clinosim/codes/data/drugs.yaml`` with an RxNorm
ingredient code (term type IN / PIN / MIN, or the ``rxnorm_scd_ingredient``
override when the catalog code is a class term), the script asks RxNav for
the related Semantic Clinical Drugs (``/REST/rxcui/<rxcui>/related.json?tty=SCD``)
and keeps one SCD per route class and strength:

- oral: Oral Tablet, then Oral Capsule, then the delayed / extended release
  and sublingual forms;
- injection: a vial / ampoule (``Injection``), then an injectable solution,
  a prefilled syringe, ...; the strength is the total amount of the unit
  (``2 ML ondansetron 2 MG/ML Injection`` = 4 mg);
- inhalation: an inhaler (strength per actuation), then a powder capsule or
  a nebuliser solution (total amount).

Kits, packs, brand-labelled (NDA / BLA / ANDA) and sensor products are
skipped. A multi-ingredient drug (MIN) keeps its components' strengths.

It writes:
- ``clinosim/codes/data/rxnorm_scd.yaml`` — the selection table;
- the generated SCD block of ``clinosim/codes/data/rxnorm.yaml`` (display =
  the RxNorm name), between the BEGIN / END markers, leaving the
  hand-written part untouched;
- the SCD concepts of ``clinosim/codes/authoritative/rxnorm_rxnav_snapshot.json``
  (status Active, name, tty), checked offline by
  ``tests/unit/codes/test_rxnorm_codes_name_their_drug.py``.

Deterministic: sorted output; the RxNav answer is the only input.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
from datetime import date
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_DRUGS = _ROOT / "clinosim/codes/data/drugs.yaml"
_TABLE = _ROOT / "clinosim/codes/data/rxnorm_scd.yaml"
_RXNORM = _ROOT / "clinosim/codes/data/rxnorm.yaml"
_SNAPSHOT = _ROOT / "clinosim/codes/authoritative/rxnorm_rxnav_snapshot.json"
_API = "https://rxnav.nlm.nih.gov/REST"
_BEGIN = "  # BEGIN generated RxNorm SCD (scripts/refresh_rxnorm_scd.py, Issue #2614) — do not edit by hand\n"
_END = "  # END generated RxNorm SCD\n"

FORMS = {
    "oral": [
        "Oral Tablet",
        "Oral Capsule",
        "Delayed Release Oral Tablet",
        "Delayed Release Oral Capsule",
        "Extended Release Oral Tablet",
        "Extended Release Oral Capsule",
        "Sublingual Tablet",
    ],
    "injection": [
        "Injection",
        "Injectable Solution",
        "Prefilled Syringe",
        "Injectable Suspension",
        "Auto-Injector",
        "Cartridge",
    ],
    "inhalation": [
        "Metered Dose Inhaler",
        "Dry Powder Inhaler",
        "Inhalation Spray",
        "Inhalation Powder",
        "Inhalation Solution",
    ],
}
UNITS = {"MG": ("mg", 1.0), "MCG": ("mg", 0.001), "UNT": ("unit", 1.0), "MEQ": ("meq", 1.0)}
_NUM = r"(\d+(?:\.\d+)?)"
_SKIP_PREFIX = ("Sensor", "{", "NDA", "BLA", "ANDA")


def _get(url: str) -> dict:
    for attempt in range(8):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return json.load(resp)
        except Exception:  # noqa: BLE001 — retry transient network errors
            time.sleep(2**attempt)
    raise RuntimeError(f"RxNav did not answer: {url}")


def _component(text: str, per_unit_volume: float | None) -> tuple[float, str] | None:
    """Strength of one ingredient: ``<name> <n> <UNIT>[/ML|/ACTUAT]``."""
    m = re.fullmatch(r".+? " + _NUM + r" (MG|MCG|UNT|MEQ)(/ML|/ACTUAT)?", text)
    if not m:
        return None
    unit, factor = UNITS[m.group(2)]
    value = float(m.group(1)) * factor
    if m.group(3) == "/ML":
        if per_unit_volume is None:
            return None
        value *= per_unit_volume
    return round(value, 6), unit


def parse_scd(name: str) -> tuple[str, list[float], str, int] | None:
    """``(route_class, component strengths, unit, form rank)`` of an SCD name."""
    if name.startswith(_SKIP_PREFIX) or " Pack" in name or "Kit" in name:
        return None
    text = re.sub(r"^\d+ HR ", "", name)
    for route_class, forms in FORMS.items():
        for rank, form in sorted(enumerate(forms), key=lambda x: -len(x[1])):
            if not text.endswith(" " + form):
                continue
            body = text[: -len(form) - 1]
            volume = None
            m = re.match(_NUM + r" ML (.+)$", body)
            if m:
                volume, body = float(m.group(1)), m.group(2)
            body = re.sub(r"^\d+ ACTUAT ", "", body)
            parts = [_component(p, volume) for p in body.split(" / ")]
            if not parts or any(p is None for p in parts) or len({p[1] for p in parts}) != 1:  # type: ignore[index]
                return None
            return route_class, [p[0] for p in parts], parts[0][1], rank  # type: ignore[index]
    return None


def build(catalog: dict) -> tuple[dict, dict[str, str]]:
    table: dict[str, dict[str, list]] = {}
    names: dict[str, str] = {}
    for drug_id, body in sorted(catalog.items()):
        if not isinstance(body, dict):
            continue
        rxcui = str(body.get("rxnorm_scd_ingredient") or (body.get("codes") or {}).get("rxnorm") or "")
        if not rxcui:
            continue
        tty = (_get(f"{_API}/rxcui/{rxcui}/properties.json").get("properties") or {}).get("tty")
        if tty not in ("IN", "PIN", "MIN"):
            continue
        related = _get(f"{_API}/rxcui/{rxcui}/related.json?tty=SCD").get("relatedGroup") or {}
        best: dict[tuple, tuple] = {}
        for group in related.get("conceptGroup") or []:
            for concept in group.get("conceptProperties") or []:
                parsed = parse_scd(concept["name"])
                if parsed is None:
                    continue
                route_class, strengths, unit, rank = parsed
                if (tty == "MIN") != (len(strengths) > 1):
                    continue
                key = (route_class, tuple(strengths), unit)
                actuations = int((re.match(r"(\d+) ACTUAT", concept["name"]) or [0, 0])[1])
                candidate = (rank, -actuations, int(concept["rxcui"]), concept["rxcui"], concept["name"])
                if key not in best or candidate < best[key]:
                    best[key] = candidate
        if not best:
            continue
        per_route: dict[str, list] = {}
        for (route_class, strengths, unit), cand in sorted(best.items()):
            strength: float | list[float] = strengths[0] if len(strengths) == 1 else list(strengths)
            per_route.setdefault(route_class, []).append({"strength": strength, "unit": unit, "rxcui": cand[3]})
            names[cand[3]] = cand[4]
        table[drug_id] = per_route
        time.sleep(0.05)
    return table, names


def _by_number(item: tuple[str, str]) -> int:
    return int(item[0])


def _yaml_scalar(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def write(table: dict, names: dict[str, str]) -> None:
    header = (
        "# RxNorm Semantic Clinical Drugs per drug, route class and strength (Issue #2614).\n"
        "# GENERATED by scripts/refresh_rxnorm_scd.py from NLM RxNav — do not edit by hand.\n"
        "# strength: per tablet / capsule (oral), per actuation or unit (inhalation),\n"
        "# total amount of the vial / syringe (injection); a list for a combination.\n"
        "# The order's dose selects the SCD: dose = n x strength, n = 1-4 (fewest units).\n"
    )
    meta = {"metadata": {"kind": "map", "name": "rxnorm_scd", "source": "NLM RxNav", "fetched_at": str(date.today())}}
    body = yaml.safe_dump({"drugs": table}, sort_keys=True, allow_unicode=True, default_flow_style=None, width=200)
    _TABLE.write_text(header + yaml.safe_dump(meta, sort_keys=False) + body, encoding="utf-8")

    text = _RXNORM.read_text(encoding="utf-8")
    manual = text[: text.index(_BEGIN)] + text[text.index(_END) + len(_END) :] if _BEGIN in text else text
    hand_written = set(re.findall(r"^  '(\d+)':", manual, flags=re.M))
    generated = {c: n for c, n in names.items() if c not in hand_written}
    block = (
        _BEGIN
        + "".join(
            f"  '{c}':\n    en: {_yaml_scalar(n)}\n" for c, n in sorted(generated.items(), key=lambda x: int(x[0]))
        )
        + _END
    )
    if _BEGIN in text:
        start, end = text.index(_BEGIN), text.index(_END) + len(_END)
        text = text[:start] + block + text[end:]
    else:
        text = text.rstrip("\n") + "\n" + block
    _RXNORM.write_text(text, encoding="utf-8")

    snap = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    kept = list(snap["concept"])
    known = {c["code"] for c in kept}
    added = [
        {"code": code, "status": "Active", "name": name, "tty": "SCD"}
        for code, name in sorted(names.items(), key=lambda x: int(x[0]))
        if code not in known
    ]
    snap["concept"] = kept + added
    snap["metadata"]["scd_fetched_at"] = str(date.today())
    _SNAPSHOT.write_text(json.dumps(snap, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    catalog = yaml.safe_load(_DRUGS.read_text(encoding="utf-8"))["drugs"]
    table, names = build(catalog)
    print(f"{len(table)} drugs, {len(names)} SCDs")
    if not args.dry_run:
        write(table, names)


if __name__ == "__main__":
    main()
