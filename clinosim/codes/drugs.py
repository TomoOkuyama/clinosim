"""Drug identity catalog loader — single source of truth for drug display
+ authority code pointers.

Resolves an internal, authority-neutral ``drug_id`` (snake_case key)
to the display SoT and the pointers into the authority code-system
tables (RxNorm / YJ / HOT7).

Design: this module is the drug-identity Single Source of Truth. The
authority code tables themselves (``rxnorm.yaml``, ``yj.yaml``,
``hot7.yaml``) remain the canonical home of their respective codes with
their own ``metadata.source`` provenance — this module only names which
codes identify a given drug and what to display.

History: META #1792 established the catalog + migrated downstream yamls
to ``drug_id`` references (Phases 1-6, closed). META #1849 Phase 5
retired the legacy ``clinosim/locale/shared/drug_names_ja.yaml``
display source (deleted in #1876) in favour of this catalog + the
four narrative display catalogs under ``clinosim/codes/data/`` — the
free-text EN→JA lookup `load_narrative_display_dict()` in
`clinosim/locale/loader.py` UNIONs them all.

Usage::

    from clinosim.codes.drugs import resolve_drug

    rec = resolve_drug("atorvastatin")
    rec.names["en"]        # "Atorvastatin"
    rec.names["ja"]        # "アトルバスタチン"
    rec.codes.get("rxnorm")  # "83367"
    rec.display_for("US")  # "Atorvastatin"
    rec.display_for("JP")  # "アトルバスタチン"
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml

_DATA_FILE = Path(__file__).parent / "data" / "drugs.yaml"


@dataclass(frozen=True)
class DrugIdentity:
    """One drug's identity record.

    ``names`` carries the display SoT (``en`` + ``ja`` required). ``codes``
    maps authority keys (``rxnorm`` / ``yj``) to the code strings that
    identify this drug in each registry; omitted when the drug has no code
    in that registry. ``yj_by_route`` holds the JP YJ product code per route
    class (``codes.yj`` in the yaml, most-used route first); ``codes["yj"]``
    is the first of them (Issue #2347). ``classes`` carries drug-class
    tags (optional, free-form). ``aliases`` carries alternate English
    name forms (synonyms, trade-name variants, salt-form variants) that
    all resolve to this drug_id — the loader unions them into the shared
    `_load_narrative_display_dict` return value so free-text display translation
    picks them up (META #1849 Phase 5 Step 2.g).
    """

    drug_id: str
    names: dict[str, str]
    codes: dict[str, str] = field(default_factory=dict)
    yj_by_route: dict[str, str] = field(default_factory=dict)
    classes: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()

    def display_for(self, country: str) -> str:
        """Return the locale-appropriate bare generic name.

        ``country`` is matched case-insensitively. ``"JP"`` returns the
        Japanese display; everything else returns English (US is the
        default). Unknown country never raises — EN is the fallback.
        """
        if (country or "").strip().upper() == "JP":
            return self.names.get("ja") or self.names.get("en", "")
        return self.names.get("en", "")


def _parse_catalog(raw: dict[str, Any]) -> dict[str, DrugIdentity]:
    """Build the ``drug_id -> DrugIdentity`` map from the parsed yaml.

    Validates that each entry has at least ``names.en`` and ``names.ja``
    (the display SoT invariant). Missing fields raise ``ValueError``
    with the drug_id so the yaml author sees exactly which row is bad.
    """
    out: dict[str, DrugIdentity] = {}
    for drug_id, body in (raw.get("drugs") or {}).items():
        if not isinstance(body, dict):
            raise ValueError(f"drugs.yaml: {drug_id!r} body must be a mapping, got {type(body).__name__}")
        names = body.get("names") or {}
        if not isinstance(names, dict):
            raise ValueError(f"drugs.yaml: {drug_id!r} names must be a mapping")
        if not names.get("en"):
            raise ValueError(f"drugs.yaml: {drug_id!r} missing required names.en")
        if not names.get("ja"):
            raise ValueError(f"drugs.yaml: {drug_id!r} missing required names.ja")
        codes = body.get("codes") or {}
        if not isinstance(codes, dict):
            raise ValueError(f"drugs.yaml: {drug_id!r} codes must be a mapping")
        classes = body.get("classes") or []
        if not isinstance(classes, list):
            raise ValueError(f"drugs.yaml: {drug_id!r} classes must be a list")
        aliases = body.get("aliases") or []
        if not isinstance(aliases, list):
            raise ValueError(f"drugs.yaml: {drug_id!r} aliases must be a list")
        yj = codes.get("yj") or {}
        if not isinstance(yj, dict):
            raise ValueError(f"drugs.yaml: {drug_id!r} codes.yj must map a route class to a YJ code")
        yj_by_route = {str(k): str(v) for k, v in yj.items() if v}
        flat = {str(k): str(v) for k, v in codes.items() if v and k != "yj"}
        if yj_by_route:
            flat["yj"] = next(iter(yj_by_route.values()))
        out[str(drug_id)] = DrugIdentity(
            drug_id=str(drug_id),
            names={str(k): str(v) for k, v in names.items()},
            codes=flat,
            yj_by_route=yj_by_route,
            classes=tuple(str(c) for c in classes),
            aliases=tuple(str(a) for a in aliases if a),
        )
    return out


@cache
def _load_catalog() -> dict[str, DrugIdentity]:
    """Load and cache the drug catalog. Fail-loud on missing file: the
    catalog is a required dependency of the loader, not optional."""
    return _parse_catalog(_raw_catalog())


def _raw_catalog() -> dict[str, Any]:
    if not _DATA_FILE.exists():
        raise FileNotFoundError(f"drugs.yaml not found at {_DATA_FILE}")
    with _DATA_FILE.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@cache
def _route_class_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for route_class, routes in (_raw_catalog().get("route_classes") or {}).items():
        for route in routes or []:
            index[str(route).strip().casefold()] = str(route_class)
    return index


def route_class(route: str) -> str:
    """Route class (``oral`` / ``injection`` / ``inhalation`` / ``rectal`` /
    ``topical``) of an order route, from ``route_classes`` in drugs.yaml;
    ``""`` for an empty or unknown route (Issue #2347)."""
    return _route_class_index().get((route or "").strip().casefold(), "")


def jp_drug_code(drug_ref: str, route: str = "") -> str | None:
    """JP YJ product code of a drug (catalog id, English name or alias) given by
    ``route``; ``None`` when the drug has no listed product for that route
    class. With no route class, a drug listed for exactly one route class
    returns that code (Issue #2347)."""
    rec = find_drug(drug_ref)
    if rec is None or not rec.yj_by_route:
        return None
    rc = route_class(route)
    if rc:
        return rec.yj_by_route.get(rc)
    return next(iter(rec.yj_by_route.values())) if len(rec.yj_by_route) == 1 else None


@cache
def jp_drug_code_table(route: str = "") -> dict[str, str]:
    """Drug name → JP YJ code for drugs given by ``route``: every English name,
    alias and Japanese name of a catalog drug that has a product for that route
    class. The name-keyed lookup the FHIR medication builders match free-text
    order names against (Issue #2347)."""
    table: dict[str, str] = {}
    for drug_id in all_drug_ids():
        code = jp_drug_code(drug_id, route)
        if not code:
            continue
        rec = _load_catalog()[drug_id]
        for name in (rec.names.get("en", ""), *rec.aliases, rec.names.get("ja", "")):
            if name:
                table.setdefault(name, code)
    return table


def resolve_drug(drug_id: str) -> DrugIdentity:
    """Return the ``DrugIdentity`` for ``drug_id``.

    Raises ``KeyError`` with the drug_id when not catalogued. Callers
    that need to probe without raising should use :func:`get_drug`.
    """
    catalog = _load_catalog()
    rec = catalog.get(drug_id)
    if rec is None:
        raise KeyError(f"resolve_drug: {drug_id!r} not in drugs.yaml catalog")
    return rec


def get_drug(drug_id: str) -> DrugIdentity | None:
    """Return the ``DrugIdentity`` for ``drug_id``, or None when not catalogued."""
    return _load_catalog().get(drug_id)


@cache
def _name_index() -> dict[str, str]:
    """Case-folded English name and alias -> drug_id."""
    index: dict[str, str] = {}
    for drug_id, rec in _load_catalog().items():
        for name in (rec.names.get("en", ""), *rec.aliases):
            if name:
                index.setdefault(name.casefold(), drug_id)
    return index


def find_drug(ref: str) -> DrugIdentity | None:
    """Return the drug for a catalog id, English name or alias (case-insensitive).

    ``None`` when nothing matches. Exact ids win over names (Issue #2292).
    """
    catalog = _load_catalog()
    if ref in catalog:
        return catalog[ref]
    drug_id = _name_index().get((ref or "").strip().casefold())
    return catalog.get(drug_id) if drug_id else None


@cache
def drug_name_needles(drug_id: str) -> tuple[str, ...]:
    """Case-folded id, English and Japanese names and aliases of a catalog drug."""
    rec = resolve_drug(drug_id)
    names = (drug_id, rec.names.get("en", ""), rec.names.get("ja", ""), *rec.aliases)
    return tuple(dict.fromkeys(n.casefold() for n in names if n))


def names_drug(text: str, drug_id: str) -> bool:
    """True when free-text medication ``text`` names the catalog drug: one of its
    names or aliases occurs in it, case-insensitively ("Warfarin 3mg PO",
    "ワルファリン錠"). The one name match for "is this drug X" (Issue #2293)."""
    folded = (text or "").casefold()
    return bool(folded) and any(n in folded for n in drug_name_needles(drug_id))


def all_drug_ids() -> tuple[str, ...]:
    """Return every drug_id in the catalog (sorted). Used by integrity tests
    and by audit scripts that cross-reference drug_id usage in downstream yamls."""
    return tuple(sorted(_load_catalog().keys()))


# --------------------------------------------------------------------------- #
# Drug code systems (Issue #2262)

_YJ12_PATTERN = re.compile(r"^\d{7}[A-Z]\d{4}$")
_YJ_FULL_CS = Path(__file__).parent / "authoritative" / "JP_MedicationCodeYJ_CS_full.json"


def jp_drug_system_key(code: str) -> str:
    """Registry key of a JP drug code by its format (JP Core NamingSystem):
    7 / 9 / 13 digits → MEDIS ``hot7`` / ``hot9`` / ``hot13``; a 12-character
    ``\\d{7}[A-Z]\\d{4}`` code → ``yj``. Other shapes fall back to ``hot9``
    (the pre-existing emit behaviour)."""
    if code.isdigit():
        return {7: "hot7", 9: "hot9", 13: "hot13"}.get(len(code), "hot9")
    if _YJ12_PATTERN.match(code):
        return "yj"
    return "hot9"


def drug_system_key(code: str, country: str) -> str:
    """Registry key of a drug code emitted for ``country``: RxNorm for the US,
    the format-dispatched JP system for JP."""
    return jp_drug_system_key(code) if str(country).strip().upper() == "JP" else "rxnorm"


def drug_system_uri(code: str, country: str) -> str:
    """Canonical URI of a drug code emitted for ``country``."""
    from clinosim.codes.loader import get_system_uri

    return get_system_uri(drug_system_key(code, country))


@cache
def _verified_yj_codes() -> frozenset[str]:
    if not _YJ_FULL_CS.is_file():
        return frozenset()
    data = json.loads(_YJ_FULL_CS.read_text(encoding="utf-8"))
    return frozenset(c.get("code", "") for c in data.get("concept", []) if c.get("code"))


def is_verified_yj(code: str) -> bool:
    """True when ``code`` is in the JP national YJ CodeSystem shipped as
    ``codes/authoritative/JP_MedicationCodeYJ_CS_full.json`` (MEDIS-sourced,
    content=complete; Issue #1220)."""
    return code in _verified_yj_codes()
