"""The medications a daily note's plan names (Issue #3247).

A progress note covers the doses of its period — with an authored time, the
``window_hours`` up to it (``notable_labs.yaml``, since the previous day's
note); without one, its hospital day — and compares them with the period
before: a drug first given in the period (not even as a one-time dose
before it) is started, one given in the previous period and never
again is stopped, a dose of a one-time order is given (not continued), a
held dose is held; a drug given only as needed is neither started nor
stopped. Each list is ranked by the tiers of
``reference_data/drug_plan_priority.yaml``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinosim.datafiles import load_validated_yaml
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.timeutil import parse_iso_datetime

if TYPE_CHECKING:
    from clinosim.types.document import NarrativeContext

__all__ = [
    "MedicationPlanRules",
    "NoteMedications",
    "cap_names",
    "drug_tier",
    "medication_plan_rules",
    "note_medications",
    "ranked_medication_names",
]

_RULES_YAML = Path(__file__).resolve().parents[1] / "reference_data" / "drug_plan_priority.yaml"


class _Tier(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    classes: list[str] = Field(default_factory=list)
    route_classes: list[str] = Field(default_factory=list)


class MedicationPlanRules(BaseModel):
    """``drug_plan_priority.yaml`` (Issue #3247)."""

    model_config = ConfigDict(extra="forbid")
    tiers: list[_Tier]
    one_time_frequencies: list[str]
    as_needed_marker: str
    max_listed: int = Field(gt=0)

    @model_validator(mode="after")
    def _known_classes(self) -> MedicationPlanRules:
        from clinosim.codes.drugs import _raw_catalog, all_drug_ids, drug_classes

        known = {c for d in all_drug_ids() for c in drug_classes(d)}
        routes = set(_raw_catalog().get("route_classes") or {})
        bad = sorted(c for t in self.tiers for c in t.classes if c not in known)
        bad += sorted(r for t in self.tiers for r in t.route_classes if r not in routes)
        if bad:
            raise ValueError(f"drug_plan_priority.yaml: unknown drug or route classes {bad}")
        return self


@lru_cache(maxsize=1)
def medication_plan_rules() -> MedicationPlanRules:
    """The ranking tiers, one-time frequencies and list cap of a note's
    medication plan (``drug_plan_priority.yaml``)."""
    return MedicationPlanRules.model_validate(load_validated_yaml(_RULES_YAML, MedicationPlanRules))


@dataclass
class NoteMedications:
    """The drugs of a note's period by what happened to them, each list
    ranked and in the note's language; ``held`` carries the hold reason."""

    started: list[str] = field(default_factory=list)
    continued: list[str] = field(default_factory=list)
    given_once: list[str] = field(default_factory=list)
    held: list[str] = field(default_factory=list)
    stopped: list[str] = field(default_factory=list)


@dataclass
class _Drug:
    name: str
    route: str
    position: int
    current: bool = False
    held_reason: str | None = None
    current_scheduled: bool = False
    current_as_needed_only: bool = True
    previous_any: bool = False
    previous_scheduled: bool = False
    previous_as_needed_only: bool = True
    later: bool = False


def drug_tier(drug_ref: str, route: str) -> int:
    """Index of the first tier of ``drug_plan_priority.yaml`` the drug belongs
    to (by catalog class, else by route class); ``len(tiers)`` for none."""
    from clinosim.codes.drugs import drug_classes, route_class

    rules = medication_plan_rules()
    classes = set(drug_classes(drug_ref)) if drug_ref else set()
    rclass = route_class(route) if route else ""
    for i, tier in enumerate(rules.tiers):
        if classes & set(tier.classes) or (rclass and rclass in tier.route_classes):
            return i
    return len(rules.tiers)


def _ranked(drugs: list[_Drug], keys: dict[int, str]) -> list[_Drug]:
    tiers = {d.position: drug_tier(keys[d.position], d.route) for d in drugs}
    return sorted(drugs, key=lambda d: (tiers[d.position], d.position))


def cap_names(names: list[str], lang: str) -> str:
    """``names`` joined as a list, the drugs beyond ``max_listed`` counted."""
    from clinosim.locale.i18n import t

    cap = medication_plan_rules().max_listed
    text = t("list_sep.serial", lang).join(names[:cap])
    if len(names) > cap:
        text += t("current_medications.truncate_suffix", lang, n=len(names) - cap)
    return text


def _admission(ctx: NarrativeContext) -> datetime | None:
    enc = getattr(ctx, "encounter", None)
    raw = _o(enc, "admission_datetime", None) if enc is not None else None
    return parse_iso_datetime(raw, lenient=True) if raw is not None else None


def _when(m: Any) -> datetime | None:
    raw = _o(m, "actual_datetime", None) or _o(m, "scheduled_datetime", None)
    return parse_iso_datetime(raw, lenient=True) if raw is not None else None


def _day(m: Any, admitted: datetime | None) -> int | None:
    d = _o(m, "day", None)
    if d is None and admitted is not None:
        when = _when(m)
        if when is not None:
            d = (when.date() - admitted.date()).days
    return d


def ranked_medication_names(ctx: NarrativeContext, day: int) -> list[str]:
    """The drugs of hospital ``day``'s medication record, ranked, in the
    note's language (the admission plan's initial medications)."""
    from clinosim.locale.free_text import localize_drug_name

    admitted = _admission(ctx)
    seen: dict[str, _Drug] = {}
    keys: dict[int, str] = {}
    for m in list(getattr(ctx, "medications", None) or []):
        name = _o(m, "drug_name", None) or _o(m, "medication", None)
        d = _day(m, admitted)
        if not name or (d is not None and d != day) or name in seen:
            continue
        seen[name] = _Drug(str(name), str(_o(m, "route", "") or ""), len(seen))
        keys[len(seen) - 1] = str(_o(m, "drug_id", "") or name)
    return [localize_drug_name(d.name, ctx.target_lang) for d in _ranked(list(seen.values()), keys)]


def note_medications(ctx: NarrativeContext) -> NoteMedications:
    """The drugs of a daily note's period (module docstring), by what
    happened to them."""
    from clinosim.codes.drugs import drug_key
    from clinosim.locale.free_text import localize_drug_name
    from clinosim.locale.loader import hold_reason_display
    from clinosim.modules.document.narrative._narrative_interpretation_thresholds import notable_lab_rules

    rules = medication_plan_rules()
    lang = ctx.target_lang
    admitted = _admission(ctx)
    as_of = getattr(ctx, "authored_datetime", None)
    window = timedelta(hours=notable_lab_rules().window_hours)
    orders = {str(_o(o, "order_id", "")): o for o in list(getattr(ctx, "orders", None) or []) if _o(o, "order_id", "")}
    one_time = {f.casefold() for f in rules.one_time_frequencies}

    def order_kind(m: Any) -> tuple[bool, bool]:
        order = orders.get(str(_o(m, "order_id", "") or ""))
        if order is None:
            return False, False
        freq = str(_o(order, "frequency", "") or "").casefold()
        return bool(_o(order, "single_dose", False)) or freq in one_time, rules.as_needed_marker in freq

    def period(m: Any) -> int:
        """0 = the note's period, -1 = the one before, -2 = earlier, 1 = after
        the note."""
        when = _when(m)
        if as_of is not None and when is not None:
            if when > as_of:
                return 1
            if when > as_of - window:
                return 0
            return -1 if when > as_of - 2 * window else -2
        d = _day(m, admitted)
        if d is None:
            return 0
        offset = d - ctx.day_index
        return max(-2, min(offset, 1))

    if as_of is not None:
        has_previous = admitted is None or as_of - window > admitted
    else:
        has_previous = ctx.day_index >= 1

    drugs: dict[str, _Drug] = {}
    keys: dict[int, str] = {}
    for m in list(getattr(ctx, "medications", None) or []):
        name = _o(m, "drug_name", None) or _o(m, "medication", None) or _o(m, "name", None)
        p = period(m)
        if not name:
            continue
        ref = str(_o(m, "drug_id", "") or "") or drug_key(str(name))
        drug = drugs.get(ref)
        if drug is None:
            drug = drugs[ref] = _Drug(str(name), str(_o(m, "route", "") or ""), len(drugs))
            keys[drug.position] = ref
        is_once, as_needed = order_kind(m)
        if p == 1:
            drug.later = True
        elif p == 0:
            if not drug.current:
                drug.name, drug.route = str(name), str(_o(m, "route", "") or drug.route)
            drug.current = True
            if _o(m, "status", None) == "held" and drug.held_reason is None:
                drug.held_reason = str(_o(m, "hold_reason", None) or "")
            if not is_once:
                drug.current_scheduled = True
                drug.current_as_needed_only = drug.current_as_needed_only and as_needed
        else:
            drug.previous_any = True
        if p == -1 and not is_once:
            drug.previous_scheduled = True
            drug.previous_as_needed_only = drug.previous_as_needed_only and as_needed

    out = NoteMedications()
    for drug in _ranked(list(drugs.values()), keys):
        shown = localize_drug_name(drug.name, lang)
        if drug.held_reason is not None:
            # The reason in the note's language (Issue #3233); a measured
            # value ("SBP < 90", "K 6.5 mmol/L") is written as stored.
            out.held.append(f"{shown} ({hold_reason_display(drug.held_reason, lang)})" if drug.held_reason else shown)
        elif drug.current and not drug.current_scheduled:
            out.given_once.append(shown)
        elif drug.current:
            started = has_previous and not drug.previous_any and not drug.current_as_needed_only
            (out.started if started else out.continued).append(shown)
        elif drug.previous_scheduled and drug.later:
            out.continued.append(shown)
        elif drug.previous_scheduled and has_previous and not drug.previous_as_needed_only:
            out.stopped.append(shown)
    return out
