"""Dosage fragments: route concepts, patient instructions, IV infusion rates,
timing and ``Dosage`` construction, MAR dose parsing and status (split out of
``common.py`` in Issue #2530)."""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import Any

from clinosim.codes.ucum import ucum_quantity
from clinosim.countries import lang_for
from clinosim.datafiles import load_data_yaml
from clinosim.locale.free_text import localize_free_text
from clinosim.locale.localized import localized
from clinosim.modules._shared import is_jp, strip_protocol_prefix
from clinosim.modules.output.fhir_r4.lib.common import system_coding
from clinosim.modules.output.fhir_r4.lib.localization import (
    FREQUENCY_TEXT,
    ROUTE_TEXT,
    _localize_dosage_terms,
)
from clinosim.modules.output.fhir_r4.lib.reference_data import (
    _ROUTE_ALIASES,
    _ROUTE_SNOMED,
)

__all__ = [
    "augment_iv_dosage_with_rate",
    "build_dosage_instruction",
    "build_route_concept",
    "canonicalize_route",
    "map_mar_status",
    "resolve_iv_infusion_default",
    "strip_protocol_prefix",
]


def build_route_concept(raw_route: str | None, country: str) -> dict[str, Any] | None:
    """Build the FHIR route `CodeableConcept` for a raw route value, or None if absent.

    SINGLE lookup point for route → SNOMED across every FHIR builder (Issue #458).
    Two independent `_ROUTE_SNOMED.get(...)` sites previously existed — one in
    `build_dosage_instruction` (MedicationRequest) and one in `_build_medication_admin`
    (MedicationAdministration) — and the same missing-alias defect landed on both,
    producing 166 text-only elements on the MAR path versus 6 on the MR path. Anything
    reading a route MUST come through here; `tests/unit/output/
    test_fhir_route_alias_resolution.py` fails if a builder reaches for `_ROUTE_SNOMED`
    again. Sibling of the `classify_lab_specs` / `scenario_flags_from_protocol`
    single-edit-point pattern.

    `country` is REQUIRED (no default). A default was previously "US" and one call site
    (`build_dosage_instruction` internal) failed to forward it, silently emitting the
    US `text` form on JP output — the same J5 pattern PR #475 fixed in
    `MedicationAdministration.dosage.text`. `TypeError` at call time is preferable to
    silent locale drift.

    Resolution order: canonical key, then `_ROUTE_ALIASES` (author abbreviations such as
    `INH` / `NEB`). Case is normalised here so call sites do not each carry `.upper()`.
    The JA lookup uses the CANONICAL form, so `INHALATION` (alias) → `INHALED`
    (canonical) → `"吸入"`, not a raw miss.

    `text` field adheres to dual-slot rule (Issue #479):
    - JP (country="JP"): localized to Japanese via `ROUTE_TEXT` lookup on the canonical
      form, following the pattern of Observation.code and Procedure.code
    - US (country="US"): keeps the author's own wording (upper-cased abbreviation)
    `CodeableConcept.text` is where the source system's representation belongs, while
    `coding` carries the standard meaning.

    An unresolvable route yields `{"text": text_value}` with no `coding`. That is
    deliberate: routes needing a NEW SNOMED code (`NASAL`, `NG`, `CATHETER`, …) must be
    verified per-code against an authoritative terminology server, never aliased onto
    a nearby code — see the note on `_ROUTE_ALIASES`. The `text` is still localized for
    JP so `NG` reads `経鼻` in JP output rather than the English abbreviation.

    Note: no `.strip()`. Behaviour is intentionally byte-identical to the two call sites
    it replaces so the PR's diff is confined to alias resolution; whitespace-padded route
    values do not occur in the corpus.
    """
    route = (raw_route or "").upper()
    if not route:
        return None
    canonical = _ROUTE_ALIASES.get(route, route)
    snomed = _ROUTE_SNOMED.get(canonical)
    # Route text in the output language (translation table keyed by the
    # canonical token); English keeps the author's wording (Issue #2459).
    text_value = ROUTE_TEXT.get(canonical, lang_for(country), fallback=route)
    if snomed:
        # Registry coding (English preferred term) + the localized text above
        # (dual slot, Issue #2375).
        return {"coding": [system_coding("snomed-ct", snomed["code"], "en")], "text": text_value}
    return {"text": text_value}


def canonicalize_route(raw_route: str | None) -> str:
    """Return the canonical `_ROUTE_SNOMED` key for a raw route (upper + alias-resolved).

    Same normalization `build_route_concept` performs internally, exposed as a helper
    for downstream code that needs to gate behavior on the canonical route WITHOUT
    going through the CodeableConcept builder.

    Motivating call site: `_build_medication_admin`'s infusion-pump gate
    (`_is_infusion = canonical == "IV" and ...`). Comparing the raw upper form is
    fragile — adding an alias like `INTRAVENOUS: "IV"` to `_ROUTE_ALIASES` would
    silently break the gate (raw `INTRAVENOUS` != `"IV"`), losing every
    `resource["device"]` reference on IV continuous infusions. Same J5 pattern this
    PR is fixing elsewhere — the gate must resolve the alias first.

    Returns the upper-cased raw route when there is no alias mapping (canonical routes
    like `IV`, `PO`, SNOMED-less specials like `NG`, and truly unknown routes like
    `CATHETER` all return themselves). Empty / None inputs return `""` — the caller
    decides how to handle absence, consistent with `build_route_concept` returning
    `None` for the same case.

    Isolating this in `_fhir_common` keeps the "route maps are looked up in exactly
    one module" rule (test_no_builder_reads_the_route_maps_directly) — call sites
    import the helper, not the underlying tables.
    """
    route = (raw_route or "").upper()
    if not route:
        return ""
    return _ROUTE_ALIASES.get(route, route)


def _validate_route_maps() -> None:
    """Reverse-coverage guard for the route lookup tables (import-time).

    Same silent-no-op class as PR #90 — see `_validate_narrow_ladder` / `_validate_hai_*`
    for sibling shape. Two invariants:

    1. `ROUTE_TEXT.keys() ⊇ _ROUTE_SNOMED.keys()` — every canonical SNOMED route MUST
       have a JP translation. A new `_ROUTE_SNOMED` entry without a companion
       `ROUTE_TEXT` entry would silently emit the English canonical on JP output.
    2. `ROUTE_TEXT.keys() ∩ _ROUTE_ALIASES.keys() == ∅` — aliases are resolved to
       canonical BEFORE the JA lookup, so an alias entry in `ROUTE_TEXT` is dead
       (never reached) and misleads authors into thinking coverage exists.
    """
    _route_text = ROUTE_TEXT.entries()
    missing_ja = set(_ROUTE_SNOMED.keys()) - set(_route_text.keys())
    if missing_ja:
        raise ValueError(f"ROUTE_TEXT missing JP translation for canonical SNOMED routes: {sorted(missing_ja)}")
    alias_in_ja = set(_route_text.keys()) & set(_ROUTE_ALIASES.keys())
    if alias_in_ja:
        raise ValueError(
            f"ROUTE_TEXT contains alias keys — resolve via _ROUTE_ALIASES to canonical first: {sorted(alias_in_ja)}"
        )


_validate_route_maps()


# Issue #848: `Dosage.patientInstruction` template families, keyed by
# clinical administration route. Prior emit used a single oral-specific
# template ("毎日1回、指示された時間帯に内服してください") for every route
# — 33% of populated PI on the JP p=10000 s500 sample carried a
# non-oral route while asserting "内服" in the same resource (saline
# 100% wrong at 838 records). Each entry below produces the correct
# JA phrase for its route family; unknown routes yield None so
# `patientInstruction` is omitted (FHIR cardinality 0..1) rather than
# emitted with a value contradicting the resource's own `route.text`.
#
# Route markers are matched against the localized ``route`` string
# (``route.text`` after ``build_route_concept`` — Japanese for JP
# output). Matching is substring-based so composite tokens like
# "IV drip" / "点滴静注" both resolve to the parenteral verb.
@cache
def _patient_instructions_ja_from_yaml() -> dict[str, Any]:
    """Load the JA patient-instruction route-family + interval-prefix tables."""
    path = Path(__file__).resolve().parents[4] / "locale" / "jp" / "patient_instructions_ja.yaml"
    return load_data_yaml(path) or {}


def _pi_route_families_ja_from_yaml() -> tuple[tuple[tuple[str, ...], str], ...]:
    """Build the route-family dispatch tuple preserving yaml ordering."""
    raw = _patient_instructions_ja_from_yaml().get("route_families", []) or []
    out: list[tuple[tuple[str, ...], str]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        markers = tuple(str(m) for m in (row.get("markers") or []))
        template = str(row.get("template") or "")
        if markers and template:
            out.append((markers, template))
    return tuple(out)


def _interval_freq_prefix_ja_from_yaml() -> dict[str, str]:
    raw = _patient_instructions_ja_from_yaml().get("interval_prefix", {}) or {}
    return {str(k): str(v) for k, v in raw.items()}


# Route-family dispatch + interval-based frequency prefix now live in
# `clinosim/locale/jp/patient_instructions_ja.yaml`; the aliases below
# keep the Python symbols stable so every call site in this module
# stays unchanged.
_PI_ROUTE_FAMILIES_JA: tuple[tuple[tuple[str, ...], str], ...] = _pi_route_families_ja_from_yaml()
_INTERVAL_FREQ_PREFIX_JA: dict[str, str] = _interval_freq_prefix_ja_from_yaml()
# Oral frequency phrases, "1日N回" labels and timing-only instructions
# (same yaml, Issue #2402).
_ORAL_JA: dict[str, str] = {str(k): str(v) for k, v in (_patient_instructions_ja_from_yaml().get("oral") or {}).items()}
_ORAL_FREQ_PHRASE_JA: dict[int, str] = {
    int(k): str(v) for k, v in (_patient_instructions_ja_from_yaml().get("oral_freq_phrase") or {}).items()
}
_PER_DAY_LABEL_JA: dict[int, str] = {
    int(k): str(v) for k, v in (_patient_instructions_ja_from_yaml().get("per_day_label") or {}).items()
}
_TIMING_ONLY_JA: dict[str, str] = {
    str(k): str(v) for k, v in (_patient_instructions_ja_from_yaml().get("timing_only") or {}).items()
}


def _resolve_patient_instruction_ja(route: str, freq: str, freq_per_day: int | None) -> str:
    """Return a route-appropriate JA ``patientInstruction`` string.

    Issue #848: chooses the phrasing template from
    ``_PI_ROUTE_FAMILIES_JA`` based on the localized route string, then
    composes a frequency phrase for oral routes. Returns ``""`` when
    the route family is unknown — the caller drops
    ``patientInstruction`` rather than emit a template that would
    contradict the resource's own ``route.text``.
    """
    route_txt = (route or "").strip()
    if not route_txt:
        return ""
    freq_orig = str(freq or "").strip()
    freq_key = freq_orig.lower()
    # Resolve freq → per-day integer for both EN and JA labels.
    pd = freq_per_day
    if pd is None:
        if freq_key in ("qd", "q24h", "once daily", "daily", "1x/day") or freq_orig == _PER_DAY_LABEL_JA.get(1):
            pd = 1
        elif freq_key in ("bid", "q12h", "twice daily", "2x/day") or freq_orig == _PER_DAY_LABEL_JA.get(2):
            pd = 2
        elif freq_key in ("tid", "q8h", "three times daily", "3x/day") or freq_orig == _PER_DAY_LABEL_JA.get(3):
            pd = 3
        elif freq_key in ("qid", "q6h", "four times daily", "4x/day") or freq_orig == _PER_DAY_LABEL_JA.get(4):
            pd = 4

    # Interval-based labels (q2h/q3h/…/6時間ごと/…) — carry their own JA
    # prefix, not a `毎日N回、` prefix. Look up by both the raw label and
    # its lowercased form.
    interval_prefix = _INTERVAL_FREQ_PREFIX_JA.get(freq_orig) or _INTERVAL_FREQ_PREFIX_JA.get(freq_key)

    for markers, template in _PI_ROUTE_FAMILIES_JA:
        if any(m in route_txt for m in markers) or route_txt.upper() in [m.upper() for m in markers]:
            if "{freq_ph}" not in template:
                return template
            # Oral: compose the freq prefix + verb.
            if interval_prefix:
                return f"{interval_prefix}{_ORAL_JA['interval_verb']}"
            if pd:
                phrase = _ORAL_FREQ_PHRASE_JA.get(pd) or _ORAL_JA["freq_phrase_other"].format(n=pd)
            else:
                phrase = ""
            if phrase:
                return template.replace("{freq_ph}", phrase)
            # Neither pd-based nor interval-based freq matched — emit the
            # generic oral instruction rather than nothing (route IS oral,
            # so telling the patient to take it orally is not misleading).
            return _ORAL_JA["generic"]
    return ""


# ────────────────────────────────────────────────────────────────────
# Issue #966: IV rate augmentation
#
# PR #920 populated ``MedicationRequest.dosageInstruction.doseAndRate
# .doseQuantity`` to 94.4 % coverage but did NOT emit ``rateQuantity``
# (or ``timing.repeat.duration`` for intermittent bolus) for IV-route
# orders — 421/421 IV MRs shipped without any rate specification.
# Downstream drug-safety alerts (KCl > 10 mEq/h, vancomycin > 10 mg/min)
# and nursing-side administration reconstruction depend on explicit rate.
#
# Fix: at emit time, look up per-drug infusion defaults from the yaml
# catalog ``clinosim/locale/shared/iv_infusion_defaults.yaml``
# (feedback_constants_live_in_external_config.md — tunable clinical
# constants belong in yaml, not code). The Python side holds only mode
# dispatch and the fallback default block.
#
# Priority order inside ``augment_iv_dosage_with_rate``:
#   1. Dose text already carries a rate expression (``100 mL/h``,
#      ``12U/kg/h``, ``5 mcg/min``) — emit rateQuantity from that.
#   2. Catalog lookup on the display_name (normalized, then longest
#      prefix, then first token, then alias table).
#   3. ``default`` block from the yaml (generic 30-min bolus).
#   4. ``mode = push`` → emit NEITHER rate nor duration (drug is
#      legitimately given as < 5 min IV push; a fabricated rate is worse
#      than omission — feedback_semantic_correctness_over_coverage).
_IV_RATE_TEXT_RE = re.compile(
    r"(?P<val>\d+(?:\.\d+)?)\s*(?P<num>mL|mg|mcg|ug|U|units|IU|mEq)"
    r"\s*/\s*(?P<denom>kg/h|kg/min|kg/hr|hr|h|min)",
    re.IGNORECASE,
)


def _canonicalize_iv_rate_unit(numerator: str, denominator: str) -> str:
    """Normalize the (numerator, denominator) match into a UCUM rate string.

    UCUM keeps ``mL``, ``mg``, ``mcg``, ``U`` as-is; ``hr`` → ``h``. Weight-
    normalized rates (``mg/kg/h``) are emitted as authored — UCUM allows
    the compound form. ``ucum_quantity`` down-line applies its own
    unit-code canonicalization (Issue #781 test) so this just picks a
    clean surface form for ``rate_unit``.
    """
    num = numerator.strip()
    denom = denominator.strip().lower()
    if denom in ("hr",):
        denom = "h"
    return f"{num}/{denom}"


@cache
def _iv_infusion_defaults_by_drug_id() -> dict[str, dict[str, Any]]:
    """Catalog entries keyed by the ``drug_id`` their name resolves to (first
    entry wins), so a catalogued drug finds its infusion default by identity
    rather than by display name (Issue #2436)."""
    from clinosim.codes.drugs import drug_ref
    from clinosim.locale.loader import load_iv_infusion_defaults

    out: dict[str, dict[str, Any]] = {}
    for name, entry in ((load_iv_infusion_defaults() or {}).get("drugs") or {}).items():
        drug_id = drug_ref(str(name))
        if drug_id and drug_id not in out and isinstance(entry, dict):
            out[drug_id] = entry
    return out


def resolve_iv_infusion_default(display_name: str, drug_id: str = "") -> dict[str, Any] | None:
    """Return the per-drug IV infusion default entry for ``display_name`` or None.

    Lookup order (see ``iv_infusion_defaults.yaml`` header for full contract):
      1. Strip protocol prefix (``"IV_fluid: NS 80 mL/h"`` → ``"NS 80 mL/h"``)
         and lowercase.
      2. Full-string match against the ``drugs`` map.
      3. Longest-prefix token match — so ``"Ceftriaxone 1g IV q8h"``
         resolves to ``"ceftriaxone"``.
      4. First-token match (safety net for authors' whitespace variants).
      5. ``aliases`` table (``"NS"`` → ``"normal saline"``).
      6. ``default`` block.
      7. ``None`` if the yaml has no ``default`` block (misconfiguration).
    """
    from clinosim.locale.loader import load_iv_infusion_defaults

    if drug_id and drug_id in _iv_infusion_defaults_by_drug_id():
        return _iv_infusion_defaults_by_drug_id()[drug_id]
    catalog = load_iv_infusion_defaults() or {}
    drugs: dict[str, Any] = catalog.get("drugs", {}) or {}
    aliases: dict[str, str] = catalog.get("aliases", {}) or {}
    default: dict[str, Any] | None = catalog.get("default")

    cleaned, _ = strip_protocol_prefix(display_name or "")
    key = cleaned.strip().lower()
    if not key:
        return default
    # Strip a leading route qualifier ("IV normal saline 1000mL" →
    # "normal saline 1000mL"). Authors put the route into the display_name
    # for supportive orders whose type does not carry a separate
    # ``route`` field on the CIF item; the route is redundant here since
    # the caller has already gated on canonical route = IV.
    tokens = key.split()
    if tokens and tokens[0] in ("iv", "i.v.", "intravenous"):
        tokens = tokens[1:]
        key = " ".join(tokens)
    if key in drugs:
        return drugs[key]
    # Longest-prefix token match — so "Ceftriaxone 1g IV q8h" resolves to
    # "ceftriaxone", "normal saline 1000ml" to "normal saline".
    for n in range(len(tokens), 0, -1):
        cand = " ".join(tokens[:n])
        if cand in drugs:
            return drugs[cand]
    if tokens and tokens[0] in drugs:
        return drugs[tokens[0]]
    # Aliases: try the full key, then longest-prefix, then first token
    # (mirror the drugs-map resolution order).
    if key in aliases:
        return drugs.get(aliases[key], default)
    for n in range(len(tokens), 0, -1):
        cand = " ".join(tokens[:n])
        if cand in aliases:
            return drugs.get(aliases[cand], default)
    if tokens and tokens[0] in aliases:
        return drugs.get(aliases[tokens[0]], default)
    return default


def augment_iv_dosage_with_rate(
    dosage: dict[str, Any],
    dose_text: str,
    route: str | None,
    display_name: str,
    *,
    drug_id: str = "",
    frequency: str = "",
) -> None:
    """Extend ``dosage`` in-place with rateQuantity or timing.duration for IV orders.

    No-op when the route is not IV (canonical-form comparison, so
    ``INTRAVENOUS`` / ``iv`` aliases all resolve). No-op when the drug's
    catalog entry is ``mode: push`` (< 5 min IV push, e.g. fentanyl,
    naloxone — a fabricated rate here would be worse than an honest
    absence per feedback_semantic_correctness_over_coverage).

    ``continuous`` → sets ``dosage["doseAndRate"][0]["rateQuantity"]``
    (allocates the doseAndRate list if it does not exist).

    ``bolus`` → sets ``dosage["timing"]["repeat"]["duration"]`` +
    ``durationUnit = "min"`` (preserves any existing ``frequency`` /
    ``period`` block placed by the caller). ``timing.repeat.duration``
    is the FHIR-native way to express a scheduled infusion length; the
    ``MedicationAdministration`` sibling reconstructs the actual
    administered rate at nursing-record time.

    Priority: an explicit rate expression already inside ``dose_text``
    (``12 U/kg/h``, ``100 mL/h``, ``5 mcg/min``) wins over the catalog —
    the disease-YAML author wrote a specific rate that we must honour.
    """
    if not dosage:
        return
    canonical = canonicalize_route(route)
    if canonical != "IV":
        return

    # Priority 1: rate already in dose_text.
    if dose_text:
        m = _IV_RATE_TEXT_RE.search(dose_text)
        if m:
            try:
                rate_value = float(m.group("val"))
            except ValueError:
                rate_value = None
            if rate_value is not None:
                rate_unit = _canonicalize_iv_rate_unit(m.group("num"), m.group("denom"))
                dar = dosage.setdefault("doseAndRate", [{}])
                if not dar:
                    dar.append({})
                dar[0]["rateQuantity"] = ucum_quantity(rate_value, rate_unit)
                return

    # Priority 2/3: catalog lookup + default fallback. The order decides the
    # infusion mode (Issue #2436): a continuous order is never turned into a
    # timed bolus, and a one-off order (ONCE / STAT, e.g. an IV dose of a drug
    # that is also run as a drip) never gets the drip rate. Other frequencies
    # do not decide it: drips carry the enricher's DAILY default.
    entry = resolve_iv_infusion_default(display_name, drug_id)
    if not entry:
        return
    mode = str(entry.get("mode", "") or "").lower()
    freq = (frequency or "").strip().upper()
    if freq == "CONTINUOUS" and mode != "continuous":
        return
    if freq in ("ONCE", "STAT") and mode == "continuous":
        from clinosim.locale.loader import load_iv_infusion_defaults

        entry = (load_iv_infusion_defaults() or {}).get("default") or {}
        mode = str(entry.get("mode", "") or "").lower()
    if mode == "continuous":
        rate_value = entry.get("rate_value")
        rate_unit = entry.get("rate_unit", "")
        if rate_value is None or not rate_unit:
            return
        dar = dosage.setdefault("doseAndRate", [{}])
        if not dar:
            dar.append({})
        dar[0]["rateQuantity"] = ucum_quantity(rate_value, rate_unit)
        # Issue #1332: continuous IV infusions (vasopressors / inotropes /
        # nitroglycerin drip / insulin drip / propofol / heparin drip) are
        # dosed as a RATE, never as a fixed one-time bolus. Any doseQuantity
        # the generic dose parser peeled off (e.g. "0.05 ug" for
        # Norepinephrine — meaningless for a titrated drip) misleads
        # downstream consumers into reading the rate scalar as a total
        # single-dose. For continuous mode we keep only rateQuantity;
        # doseQuantity + total-volume are properly modeled by the sibling
        # MedicationAdministration records the nurse fills at bag-hang time.
        dar[0].pop("doseQuantity", None)
        # ``type`` (MedicationIngredientStrengthStrengthType 製剤量) is
        # bound to the ordered dose. Without doseQuantity it becomes an
        # orphaned qualifier — drop it so the FHIR shape stays coherent.
        dar[0].pop("type", None)
    elif mode == "bolus":
        duration = entry.get("duration_min")
        if duration is None:
            return
        # Preserve any existing timing.repeat (frequency/period from the
        # caller's frequency parse) — merge rather than clobber.
        timing = dosage.setdefault("timing", {})
        repeat = timing.setdefault("repeat", {})
        repeat["duration"] = duration
        repeat["durationUnit"] = "min"
    # mode == "push" (or unrecognized): intentional no-op.


# Issue #1348: frequency-label → FHIR Dosage.timing.repeat (frequency, period, periodUnit).
# Case-insensitive lookup. UCUM units: "h" hour, "d" day, "wk" week, "mo" month.
# `nightly` is once-daily at hs; not a distinct cadence from `qhs` but the label
# is common in disease-YAML mental-health / chronic-med lists so it gets an
# explicit entry.
# Frequency label → FHIR Timing.repeat (frequency, period, periodUnit).
# Backed by `clinosim/codes/data/frequency-tokens.yaml` (post-#1880
# review, hardcoded-audit Finding 20) — the same yaml the order
# engine's `_freq_per_day()` reads, so cadence vocabulary stays
# consistent across the two paths.


def _freq_label_timing() -> dict[str, tuple[int, int, str]]:
    from clinosim.locale.loader import load_frequency_tokens

    return dict(load_frequency_tokens())


# Issue #2613: interval ranges ("q4-6h") and PRN caps ("(max 2/day)",
# "up to 3x/day") in a frequency label.
_INTERVAL_RANGE = re.compile(r"q(\d+)\s*-\s*(\d+)\s*h")
_MAX_PER_DAY = re.compile(r"\(\s*max\s+(\d+)\s*(?:x\s*)?/\s*day\s*\)")
_UP_TO_PER_DAY = re.compile(r"up\s+to\s+(\d+)\s*(?:x\s*)?/\s*day")


def frequency_in_text(text: str) -> str:
    """The frequency label written inside a dose text ("70mg PO weekly" →
    "weekly"), or "" (Issue #2613). Interval ranges first, then the
    frequency-token table, longest token first; a trailing PRN is kept."""
    if not text:
        return ""
    m = re.search(r"q\d+\s*-\s*\d+\s*h(?:\s+prn)?", text, re.IGNORECASE)
    if m:
        return m.group(0)
    for token in sorted(_freq_label_timing(), key=len, reverse=True):
        m = re.search(rf"(?<![\w-]){re.escape(token)}(?![\w-])(?:\s+prn)?", text, re.IGNORECASE)
        if m:
            return m.group(0)
    return ""


def _split_prn_suffix(flow: str) -> tuple[str, bool]:
    """Strip a trailing ` prn` / ` as needed` suffix so `q6h PRN` splits into
    (`q6h`, True). The cadence still emits a `timing.repeat`, and PRN sets
    `asNeededBoolean=true` in parallel (FHIR-valid: "up to every 6 hours as
    needed").
    """
    for suffix in (" prn", " as needed", " when required"):
        if flow.endswith(suffix):
            return flow[: -len(suffix)].strip(), True
    return flow, False


def resolve_timing_repeat(
    freq_raw: str | None,
    freq_per_day: int | None = None,
) -> tuple[dict[str, Any] | None, bool]:
    """Resolve a raw frequency label (or explicit ``freq_per_day``) to a FHIR
    ``timing.repeat`` sub-dict + a PRN flag.

    Returns ``(repeat_dict, is_prn)``:

      * ``repeat_dict`` — ``{"frequency": N, "period": P, "periodUnit":
        "d"|"wk"|"mo"|"h"}`` or ``None`` when the label is unknown and no
        ``freq_per_day`` is supplied.
      * ``is_prn`` — ``True`` when the label is bare PRN or a PRN-suffixed
        cadence (``q6h PRN`` etc.). Callers should also set
        ``asNeededBoolean=true`` on the parent ``dosageInstruction``.

    Shared by ``build_dosage_instruction`` (inpatient / order-driven path)
    and ``_build_discharge_medication_request`` (discharge / outpatient
    renewal path) so both emit sites use one lookup table and stay in sync
    with new labels declared in disease / chronic YAML. Issue #1348.
    """
    if freq_per_day and (not freq_raw or not freq_raw.strip()):
        return {"frequency": int(freq_per_day), "period": 1, "periodUnit": "d"}, False
    if not freq_raw:
        return None, False
    # Issue #2613: "(max N/day)" / "up to Nx/day" cap a PRN regimen.
    _flow = freq_raw.lower().strip()
    _max_per_day: int | None = None
    for _cap in (_MAX_PER_DAY, _UP_TO_PER_DAY):
        _m = _cap.search(_flow)
        if _m:
            _max_per_day = int(_m.group(1))
            _flow = (_flow[: _m.start()] + _flow[_m.end() :]).strip()
    _flow = " ".join(_flow.split())
    _flow, _prn = _split_prn_suffix(_flow)
    if _flow == "prn" or _flow.startswith("prn "):
        # "PRN" / "PRN after each loose stool": as needed, no fixed cadence.
        _flow, _prn = "", True
    _range = _INTERVAL_RANGE.fullmatch(_flow)
    if _range:
        return {
            "frequency": 1,
            "period": int(_range.group(1)),
            "periodMax": int(_range.group(2)),
            "periodUnit": "h",
        }, _prn
    if _flow in ("prn", "as needed", "when required", ""):
        if _max_per_day:
            return {"frequency": 1, "frequencyMax": _max_per_day, "period": 1, "periodUnit": "d"}, True
        return None, True
    _timing = _freq_label_timing().get(_flow)
    if _timing is None:
        # Unknown label — fall back to caller-supplied freq_per_day if any.
        if freq_per_day:
            return {"frequency": int(freq_per_day), "period": 1, "periodUnit": "d"}, _prn
        return None, _prn
    _f, _p, _u = _timing
    return {"frequency": _f, "period": _p, "periodUnit": _u}, _prn


def build_dosage_instruction(order: dict, country: str = "US") -> dict[str, Any] | None:
    """Build FHIR Dosage from structured order fields."""
    dose_qty = order.get("dose_quantity")
    dose_unit = order.get("dose_unit", "")
    freq = order.get("frequency", "")
    freq_per_day = order.get("frequency_per_day")
    route_concept = build_route_concept(order.get("route"), country)
    # `text` is the localized (JP) or authored (US) route form used only for the dosage
    # text summary block below (line 670+). The JP text summary path re-derives the JA
    # form via `ROUTE_TEXT.get(p_upper)`, so a JA `route` here fails that lookup and
    # falls back to `p` (itself already JA) — net-safe.
    route = route_concept["text"] if route_concept else ""

    # Issue #476: when the disease author wrote a localized dose instruction
    # (`dose_ja` / `dose_en` on the YAML entry → `dose_text_ja` / `dose_text_en`
    # on the Order), emit it as the dosage text even when structured fields
    # are empty. This is DIFFERENT from the Issue #467 defect (which stuffed
    # `display_name` into `Dosage.text` — the drug name, not the dosage):
    # `dose_text_{ja,en}` carries an authored dose instruction that is exactly
    # what belongs in `Dosage.text` when the dose is a clinical instruction
    # rather than a numeric expression (e.g. "以前の吸入薬を再開または新規開始"
    # for `ICS/LABA inhaler` step-up-after-exacerbation).
    dose_text_ja = str(order.get("dose_text_ja", "") or "")
    dose_text_en = str(order.get("dose_text_en", "") or "")
    authored_text = localized({"ja": dose_text_ja, "en": dose_text_en}, lang_for(country))

    # If nothing structured is available, return None so the caller omits
    # `dosageInstruction`. Issue #467: the previous fallback stuffed the
    # Order's `display_name` (drug name, e.g. "Atorvastatin 10mg") into
    # `Dosage.text`. That is wrong on two counts:
    #  (1) `medicationCodeableConcept.text` already carries the drug name;
    #      duplicating it into the dosage field misrepresents "dosage".
    #  (2) The fallback was not localized — a JP MedicationRequest emitted
    #      via this path would leak an English drug string into JP output.
    # "空欄は無知、誤った断言は虚偽" (feedback_empty_vs_wrong_assertion):
    # a missing dosageInstruction is correct when we have no dosage
    # information, unlike inventing one from the drug name.
    #
    # BUT if the author provided an explicit country-scoped instruction (via
    # `dose_text_{ja,en}` — Issue #476), emit it as a text-only dosage even
    # when structured fields are absent.
    if dose_qty is None and not freq and not route:
        if authored_text:
            return {"text": authored_text}
        return None

    dosage: dict[str, Any] = {}
    parts = []

    # Dose quantity — route through ucum_quantity so `code` is populated
    # (JP-CLINS eCS profiles require it).
    if dose_qty is not None and dose_unit:
        dosage["doseAndRate"] = [
            {
                "doseQuantity": ucum_quantity(dose_qty, dose_unit),
            }
        ]
        # Issue #781: `dosageInstruction[].text` is human-readable, so drop
        # the trailing `.0` on integer-valued dose floats (`4mg` not `4.0mg`).
        # `doseQuantity.value` is unaffected — it is a JSON number and both
        # `4.0` and `4` serialize the same. `text` is the only site where
        # `.0` leaks into the rendered UI.
        _dose_txt = f"{int(dose_qty)}" if isinstance(dose_qty, float) and dose_qty.is_integer() else f"{dose_qty}"
        parts.append(f"{_dose_txt}{dose_unit}")

    # Route
    if route_concept:
        dosage["route"] = route_concept
        parts.append(route)

    # Timing — resolve to a FHIR ``timing.repeat`` via the shared helper.
    # Issue #1348: prior implementation stored only ``freq_per_day`` (int),
    # so any non-daily cadence (``weekly``, ``monthly``, ``q3weeks``,
    # ``every_3_days``, ``nightly``, ``every_other_day``) fell through to
    # the plain-text branch with no ``timing.repeat`` emit — Alendronate
    # 99.8 %, Mirtazapine 100 %, Salbutamol 100 % (PRN — kept in
    # asNeededBoolean branch), and every chemo per-cycle IV lacked
    # structured timing. ``resolve_timing_repeat`` centralises the label
    # dispatch table so the inpatient / order-driven path here and the
    # discharge / outpatient path in ``_build_discharge_medication_request``
    # stay in sync.
    _repeat, _is_prn = resolve_timing_repeat(freq, freq_per_day)
    if _repeat:
        dosage["timing"] = {"repeat": _repeat}
        if _repeat.get("periodUnit") == "d" and _repeat.get("period") == 1:
            # Preserve the freq_per_day int for downstream text-summary /
            # JA patient-instruction paths that still key off it.
            freq_per_day = _repeat["frequency"]
        parts.append(freq or f"{_repeat['frequency']}x/{_repeat['periodUnit']}")
    elif freq:
        # Label present but unknown to the table (e.g. free-form
        # ``q6h_first_24h_then_daily``) — keep the label in the text
        # summary rather than fabricating a numeric repeat we cannot
        # justify. Semantic-correctness > coverage.
        parts.append(freq)
    if _is_prn:
        dosage["asNeededBoolean"] = True

    # Dosage.patientInstruction — Issue #848 fix (route-aware).
    # Prior emit derived the phrase from the frequency label alone and
    # every generated JA template ended in "内服してください" ("take
    # orally") — so a saline IV drip (route.text="静注") shipped with
    # PI="毎日1回、指示された時間帯に内服してください" and the two
    # fields in the same resource disagreed on the route. Fix:
    # `_resolve_patient_instruction_ja` picks the phrasing template from
    # the ROUTE first (parenteral / inhalation / rectal / patch /
    # topical / eye drop / oral / …), then folds in the frequency
    # phrase only for oral. Non-JA callers keep the smaller
    # freq-timing-only map (qhs → "at bedtime" etc.) — the issue
    # measured the mismatch on JA output only.
    #
    # Explicit CIF-authored `patient_instruction` on the Order (Issue
    # #476 opt-in pattern) still takes precedence over the derived
    # phrase.
    _authored_instr = str(order.get("patient_instruction", "") or "")
    _derived_instr = ""
    # Also derive from freq_per_day when the raw freq label is absent —
    # this covers the "dose+freq_per_day-only" order shape used by the
    # discharge_prescription pipeline where `frequency` is left empty
    # (v14 review found 15 MR under this shape had text="…1日1回" but
    # `patientInstruction` empty).
    if not freq and freq_per_day:
        _pd_to_key = {1: "qd", 2: "bid", 3: "tid", 4: "qid", 6: "q4h", 8: "q3h", 12: "q2h"}
        freq = _pd_to_key.get(int(freq_per_day), "")
    if is_jp(country):
        # Timing-only labels (qhs / ac / pc / qam / qpm / prn) have no
        # route dependency — they describe WHEN, not HOW. Handle those
        # first before falling through to the route-based composer.
        _timing_only_ja = _TIMING_ONLY_JA
        _flow_instr = (freq or "").lower().strip()
        _flow_instr_orig = str(freq or "").strip()
        _derived_instr = _timing_only_ja.get(_flow_instr_orig) or _timing_only_ja.get(_flow_instr, "")
        if not _derived_instr:
            _derived_instr = _resolve_patient_instruction_ja(route, freq, freq_per_day)
    elif freq:
        _flow_instr = freq.lower().strip()
        _instr_en = {
            "qhs": "at bedtime",
            "bedtime": "at bedtime",
            "hs": "at bedtime",
            "ac": "before meals",
            "pc": "after meals",
            "prn": "as needed",
            "as needed": "as needed",
        }
        _derived_instr = _instr_en.get(_flow_instr, "")
    final_instr = _authored_instr or _derived_instr
    if final_instr:
        dosage["patientInstruction"] = final_instr

    # Text summary
    # Issue #476: when the disease author provided an explicit country-scoped
    # instruction, it wins over the auto-derived summary. This is intentional:
    # for instruction-only doses (e.g. "以前の吸入薬を再開または新規開始")
    # the authored text carries the clinical meaning the summary cannot
    # reconstruct from route + frequency alone.
    if authored_text:
        dosage["text"] = authored_text
    elif parts:
        # Route / frequency tokens in the output language, then the dosage
        # term translator for any remaining English (Issue #2459); English
        # output keeps the tokens as written.
        _lang = lang_for(country)
        translated = [
            ROUTE_TEXT.get(p.upper(), _lang)
            or FREQUENCY_TEXT.get(p.upper(), _lang)
            or FREQUENCY_TEXT.get(p, _lang)
            or p
            for p in parts
        ]
        dosage["text"] = _localize_dosage_terms(" ".join(translated), _lang)
    elif order.get("display_name"):
        name = order["display_name"]
        dosage["text"] = localize_free_text(name, "ja") if is_jp(country) else name

    # Issue #966: IV-route drugs need an infusion rate (or timing.duration)
    # in addition to doseQuantity. `augment_iv_dosage_with_rate` is a no-op
    # for non-IV routes and for drugs the yaml catalog marks as `push`.
    # The dose text source is `display_name` (authored dose string), since
    # `order["dose_quantity"]`/`order["dose_unit"]` do not preserve the raw
    # "/h" or "/min" suffix that `parse_dose_string` strips before setting
    # the numeric qty. `display_name` still carries the untouched string
    # (see `enrich_medication_order` in modules/order/engine.py).
    _display_name = str(order.get("display_name", "") or "")
    augment_iv_dosage_with_rate(
        dosage,
        dose_text=_display_name,
        route=order.get("route"),
        display_name=_display_name,
        drug_id=str(order.get("drug_id") or ""),
        frequency=str(order.get("frequency") or ""),
    )

    return dosage if dosage else None


# Promoted to clinosim/modules/_shared.py (β-JP-1 chain 1a adv-1 I-1) so the
# narrative renderer shares the same normalization; kept as an alias here for
# the existing FHIR-builder import sites.
strip_protocol_prefix = strip_protocol_prefix


def _parse_dose_for_mar(text: str) -> dict[str, Any]:
    """Lightweight dose parser for MAR (avoids importing order engine in adapter)."""
    import re

    result: dict[str, Any] = {}
    if not text:
        return result
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*(mg|g|mcg|ug|mL|ml|L|IU|U|unit|units|%)\b(\s*/\s*[A-Za-z0-9²]+)?", text, re.IGNORECASE
    )
    # Issue #2750: a per-kg / per-m² dose or a rate ("mg/m2", "mg/kg/h") is not
    # an absolute amount given; state no dose rather than the truncated number.
    if m and not m.group(3):
        try:
            result["dose_quantity"] = float(m.group(1))
            result["dose_unit"] = m.group(2)
        except ValueError:
            pass
    route_match = re.search(r"\b(PO|IV|SC|IM|SL|PR|NG|inhaled|topical)\b", text, re.IGNORECASE)
    if route_match:
        result["route"] = route_match.group(1).upper()
    return result


def map_mar_status(status: str) -> str:
    return {"given": "completed", "held": "on-hold", "refused": "not-done", "not_available": "not-done"}.get(
        status, "completed"
    )  # noqa: E501
