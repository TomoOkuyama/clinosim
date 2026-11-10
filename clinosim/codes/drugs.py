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
retired the legacy ``drug_names_ja.yaml`` (formerly under ``locale/shared/``)
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

import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from clinosim.country_profile import register_implementation
from clinosim.datafiles import load_data_yaml

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
    # Inpatient administration defaults (Issue #2389): the interval that
    # overrides an order's frequency (β-lactam combinations, carbapenems), the
    # interval used when an order has no frequency, and the default route.
    scheduled_interval_hours: int | None = None
    default_interval_hours: int | None = None
    default_route: str = ""

    def display_for(self, country: str) -> str:
        """Return the locale-appropriate bare generic name.

        ``country`` is matched case-insensitively. ``"JP"`` returns the
        Japanese display; everything else returns English (US is the
        default). Unknown country never raises — EN is the fallback.
        """
        from clinosim.countries import lang_for
        from clinosim.locale.localized import localized

        return localized(self.names, lang_for(country))


def _opt_int(drug_id: Any, body: dict[str, Any], key: str) -> int | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 24:
        raise ValueError(f"drugs.yaml: {drug_id!r} {key} must be an integer number of hours in 1..24")
    return value


def _route(drug_id: Any, body: dict[str, Any]) -> str:
    route = str(body.get("default_route") or "")
    if route not in ("", "IV", "SC", "IM", "PO"):
        raise ValueError(f"drugs.yaml: {drug_id!r} default_route must be IV / SC / IM / PO")
    return route


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
            scheduled_interval_hours=_opt_int(drug_id, body, "scheduled_interval_hours"),
            default_interval_hours=_opt_int(drug_id, body, "default_interval_hours"),
            default_route=_route(drug_id, body),
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
    return load_data_yaml(_DATA_FILE)


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


def drug_display(ref: str, lang: str) -> str | None:
    """Display name of a catalog drug in ``lang`` (then English): ``ref`` is a
    drug_id, English name or alias, or a free-text order name whose leading
    words name one ("Rivaroxaban 20mg"). ``None`` when no catalog drug matches.
    The one drug-name resolver for display (Issue #2271)."""
    rec = find_drug(ref) or _find_by_leading_words(ref)
    if rec is None:
        return None
    return rec.names.get(lang) or rec.names.get("en") or None


def _find_by_leading_words(text: str) -> DrugIdentity | None:
    """The catalog drug named by the longest run of leading words of ``text``
    ("Rivaroxaban 20mg" → rivaroxaban)."""
    tokens = (text or "").replace("_", " ").split()
    for n in range(len(tokens) - 1, 0, -1):
        rec = find_drug(" ".join(tokens[:n]))
        if rec is not None:
            return rec
    return None


@cache
def _name_patterns() -> tuple[tuple[re.Pattern[str], str, bool], ...]:
    """Every catalog name and alias as a pattern, longest first. ASCII names
    match as whole words (the id ``ns`` must not match inside "insulin");
    Japanese names match as substrings ("ワルファリン錠")."""
    pairs: dict[str, str] = {}
    for drug_id, rec in _load_catalog().items():
        for name in (rec.names.get("en", ""), rec.names.get("ja", ""), *rec.aliases):
            if name:
                pairs.setdefault(name.casefold(), drug_id)
    out = []
    for name in sorted(pairs, key=len, reverse=True):
        body = re.escape(name)
        pattern = rf"(?<![\w-]){body}(?![\w])" if name.isascii() else body
        out.append((re.compile(pattern), pairs[name], _is_combination(name)))
    return tuple(out)


_DOSE_START = re.compile(r"\s\d")


def _is_combination(folded: str) -> bool:
    """True when the drug-name part (before the first dose number) joins two
    names with ``/`` or ``+`` — a "mg/kg" dose does not count."""
    name_part = _DOSE_START.split(folded, maxsplit=1)[0]
    return "/" in name_part or " + " in name_part


def identify_drug(text: str) -> DrugIdentity | None:
    """The catalog drug a free-text medication string names: an exact id,
    name or alias; else its leading words ("Warfarin 3mg PO daily"); else the
    longest catalog name or alias it contains ("IV ketorolac 15 mg",
    "アムロジピン錠5mg"). Underscores read as spaces. ``None`` when no catalog
    drug matches (Issue #2298)."""
    rec = find_drug(text) or _find_by_leading_words(text)
    if rec is not None:
        return rec
    if text and "_" in text:
        # Underscore spellings ("Calcium_gluconate", "Normal_saline") name the
        # same drug as the spaced name (Issue #2415).
        return identify_drug(text.replace("_", " "))
    folded = (text or "").casefold()
    if not folded:
        return None
    # A combination product matches only a catalogued combination: an
    # uncatalogued one ("Oxycodone/Acetaminophen") is not one of its
    # ingredients (Issue #2377).
    combination = _is_combination(folded)
    for pattern, drug_id, is_combo_name in _name_patterns():
        if combination and not is_combo_name:
            continue
        if pattern.search(folded):
            return _load_catalog()[drug_id]
    return None


def protocol_drug_name(spec: Any) -> str:
    """Name of a protocol drug entry (Issue #2414): the catalog English name of
    its ``drug_id``, else its ``drug`` text; ``""`` for neither."""
    if not isinstance(spec, dict):
        return ""
    drug_id = str(spec.get("drug_id") or "")
    rec = _load_catalog().get(drug_id) if drug_id else None
    if rec is not None:
        return rec.names.get("en", "")
    return str(spec.get("drug") or "")


@cache
def drug_ref(name_or_id: str) -> str:
    """The catalog ``drug_id`` a drug id, name, alias or free-text medication
    string names (:func:`identify_drug`); ``""`` when none (Issue #2297)."""
    rec = identify_drug(name_or_id) if name_or_id else None
    return rec.drug_id if rec is not None else ""


def drug_key(name_or_id: str) -> str:
    """Identity key of a drug reference: its catalog ``drug_id``, else the
    whitespace-normalised, case-folded name (an uncatalogued drug). Used for
    dedup and for comparing drugs without substring matching (Issue #2377)."""
    return drug_ref(name_or_id) or " ".join((name_or_id or "").casefold().split())


def same_drug(a: str, b: str) -> bool:
    """True when two drug references (ids, names, aliases, order strings with
    a dose) name the same drug (Issue #2377)."""
    key = drug_key(a)
    return bool(key) and key == drug_key(b)


def has_drug(meds: Any, drug: str) -> bool:
    """True when any record in ``meds`` is the catalog drug ``drug`` (a
    drug_id) or belongs to the catalog class ``drug`` (``"statin"``,
    ``"anticoagulant"``). A record is matched by its ``drug_id``, falling back
    to its name (Issue #2297)."""
    for med in meds or ():
        get = med.get if isinstance(med, dict) else lambda k, d=None, _m=med: getattr(_m, k, d)
        drug_id = get("drug_id", "") or drug_ref(str(get("drug_name", "") or get("display_name", "") or ""))
        if drug_id and (drug_id == drug or drug in drug_classes(drug_id)):
            return True
    return False


def medication_matches(med: Any, drugs: Any = (), classes: Any = ()) -> bool:
    """True when a medication record (object or dict with ``drug_id`` /
    ``drug_name``, or a plain name) is one of the catalog ``drugs`` or belongs
    to one of the catalog ``classes`` (Issue #2371)."""
    if isinstance(med, str):
        drug_id = drug_key(med)
    else:
        get = med.get if isinstance(med, dict) else lambda k, d=None: getattr(med, k, d)
        drug_id = (
            str(get("drug_id", "") or "")
            or drug_ref(str(get("drug_name", "") or ""))
            or drug_key(str(get("drug_name_ja", "") or get("drug_name", "") or ""))
        )
    if not drug_id:
        return False
    return drug_id in set(drugs) or bool(set(classes) & set(drug_classes(drug_id)))


def drug_classes(ref: str) -> tuple[str, ...]:
    """Catalog classes of the drug ``ref`` names (see :func:`identify_drug`),
    each followed by its dotted ancestors (``anticoagulant.vka`` also yields
    ``anticoagulant``); ``()`` for an unknown drug. The one drug-class lookup
    for decision logic (Issue #2298)."""
    rec = identify_drug(ref)
    if rec is None:
        return ()
    out: dict[str, None] = {}
    for cls in rec.classes:
        parts = cls.split(".")
        for n in range(len(parts), 0, -1):
            out.setdefault(".".join(parts[:n]))
    return tuple(out)


def jp_drug_code_for_name(name: str, route: str = "") -> str | None:
    """JP YJ product code for a free-text order name ("Furosemide 20mg",
    "Unfractionated Heparin", "Normal_saline") given by ``route``: the longest
    leading word run that names a catalog drug, then the longest trailing run,
    then a case-insensitive leading run — the matching the FHIR medication
    builders apply to the same names (Issue #2351). ``None`` when no catalog
    drug with a product for the route matches."""
    table = jp_drug_code_table(route)
    tokens = (name or "").replace("_", " ").split()
    for n in range(len(tokens), 0, -1):
        if (code := table.get(" ".join(tokens[:n]))) is not None:
            return code
    for n in range(len(tokens) - 1, 0, -1):
        if (code := table.get(" ".join(tokens[-n:]))) is not None:
            return code
    folded: dict[str, set[str]] = {}
    for key, code in table.items():
        folded.setdefault(key.casefold(), set()).add(code)
    for n in range(len(tokens), 0, -1):
        hits = folded.get(" ".join(tokens[:n]).casefold())
        if hits and len(hits) == 1:
            return next(iter(hits))
    return None


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


def all_drug_ids() -> tuple[str, ...]:
    """Return every drug_id in the catalog (sorted). Used by integrity tests
    and by audit scripts that cross-reference drug_id usage in downstream yamls."""
    return tuple(sorted(_load_catalog().keys()))


# --------------------------------------------------------------------------- #
# Drug code systems (Issue #2262). The JP formats (YJ / HOT) and the YJ
# master live in `clinosim.codes.yj` (Issue #2463); re-exported here.

_SCD_FILE = Path(__file__).parent / "data" / "rxnorm_scd.yaml"


@cache
def _scd_table() -> dict[str, Any]:
    return (load_data_yaml(_SCD_FILE) or {}).get("drugs") or {} if _SCD_FILE.exists() else {}


@cache
def _scd_drug_dose_units(drug_id: str) -> dict[str, Any]:
    """A drug's own dose-unit conversions for SCD selection (vitamin D IU -> mg)."""
    body = (_raw_catalog().get("drugs") or {}).get(drug_id) or {}
    return dict(body.get("rxnorm_scd_dose_units") or {})


@cache
def _scd_selection() -> dict[str, Any]:
    return dict(_raw_catalog().get("rxnorm_scd_selection") or {})


def rxnorm_scd_codes(drug_id: str) -> tuple[str, ...]:
    """Every RxNorm SCD listed for a catalog drug (Issue #2614)."""
    routes = _scd_table().get(drug_id) or {}
    return tuple(str(e["rxcui"]) for entries in routes.values() for e in entries)


def rxnorm_scd_code(drug: str, route: str, dose_quantity: Any, dose_unit: str) -> str | None:
    """The RxNorm SCD a dose of ``drug`` by ``route`` is given as (Issue #2614).

    ``rxnorm_scd.yaml`` lists the drug's clinical drugs per route class and
    strength; the dose must be 1..``max_units`` units of one strength (the
    fewest units win). A combination product matches on its first
    ingredient's strength, else on its total, and only when one product fits. None when no product
    fits the dose (weight / BSA-based doses, rates, a strength not marketed).
    A combination's other ingredients are tried after the first (orders may
    list the ingredients in another order than RxNorm).
    """
    record = find_drug(drug) if drug else None
    if record is None:
        return None
    entries = (_scd_table().get(record.drug_id) or {}).get(route_class(route)) or []
    sel = _scd_selection()
    unit_map = {**(sel.get("dose_units") or {}), **_scd_drug_dose_units(record.drug_id)}
    try:
        value = float(dose_quantity)
    except (TypeError, ValueError):
        return None
    conv = unit_map.get(str(dose_unit or "").strip())
    if not entries or not conv or value <= 0:
        return None
    unit, factor = str(conv[0]), float(conv[1])
    dose = value * factor
    max_units = int(sel.get("max_units", 4))
    tol = float(sel.get("tolerance", 0.02))
    # A combination product matches on its first ingredient's strength, then on
    # another ingredient's (an order may name the ingredients in a different
    # order than RxNorm: "Trimethoprim/Sulfamethoxazole 160/800mg" is RxNorm's
    # sulfamethoxazole 800 / trimethoprim 160, Issue #2861); only when none
    # does, on its total (piperacillin 4 g / tazobactam 0.5 g = 4.5 g).
    best: dict[int, set[str]] = {}
    for pick in ("single_or_first", "other_component", "total"):
        best = {}
        for entry in entries:
            if entry.get("unit") != unit:
                continue
            strength = entry.get("strength")
            combo = isinstance(strength, list)
            if pick != "single_or_first" and not combo:
                continue
            if pick == "single_or_first":
                candidates = [float(strength[0] if combo else strength)]
            elif pick == "other_component":
                candidates = [float(x) for x in strength[1:]]
            else:
                candidates = [float(sum(strength))]
            for s in candidates:
                if s <= 0:
                    continue
                k = round(dose / s)
                if 1 <= k <= max_units and abs(dose / s - k) <= tol * k:
                    best.setdefault(k, set()).add(str(entry["rxcui"]))
        if best:
            break
    if not best:
        return None
    fewest = best[min(best)]
    return next(iter(fewest)) if len(fewest) == 1 else None


from clinosim.codes.yj import _verified_yj_codes as _verified_yj_codes  # noqa: E402
from clinosim.codes.yj import is_verified_yj as is_verified_yj  # noqa: E402
from clinosim.codes.yj import jp_drug_system_key as jp_drug_system_key  # noqa: E402


@register_implementation("drug_system", "profile_code_system")
def _profile_drug_system(code: str, country: str) -> str:
    """The country profile's drug code system (US RxNorm), whatever the code."""
    from clinosim.country_profile import country_profile

    return country_profile(country).code_system("drug")


def drug_system_key(code: str, country: str) -> str:
    """Registry key of a drug code emitted for ``country``: the ``drug_system``
    implementation the country profile names (Issue #3144) — RxNorm for the
    US, the format-dispatched JP system for JP."""
    from clinosim.country_profile import implementation

    return str(implementation("drug_system", country)(code, country))


def drug_system_uri(code: str, country: str) -> str:
    """Canonical URI of a drug code emitted for ``country``."""
    from clinosim.codes.loader import get_system_uri

    return get_system_uri(drug_system_key(code, country))
