"""The admissions and emergency visits between a patient's two outpatient
visits, stated in the later visit's subjective (Issue #3407).

``NarrativeContext.interval_encounters`` holds the patient's other encounters
(:func:`other_encounters`, built from the patient's other structural records
like ``prior_lab_results``). :func:`interval_events` picks those between the
previous outpatient visit and this one; :func:`interval_event_line` states
them. A note with such an event does not state "no exacerbation since the last
visit" (``no_interval_event`` of the chronic SOAP template).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from clinosim.countries import country_code
from clinosim.datafiles import load_data_yaml
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.timeutil import parse_iso_datetime

_REF_FILE = Path(__file__).resolve().parents[1] / "reference_data" / "interval_events.yaml"

_STAY_TYPES = ("inpatient", "emergency")


class IntervalEventsConfig(BaseModel):
    """Shape of interval_events.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metadata: dict[str, Any] = Field(default_factory=dict)
    lookback_days_without_prior_visit: int = Field(gt=0)
    max_events: int = Field(gt=0)
    max_procedures: int = Field(gt=0)
    non_operative_anesthesia: list[str]


@lru_cache(maxsize=1)
def interval_events_config() -> IntervalEventsConfig:
    """The validated ``interval_events.yaml`` (shared, read-only)."""
    return IntervalEventsConfig.model_validate(load_data_yaml(_REF_FILE))


_PROCEDURE_KEYS = (
    "procedure_type",
    "procedure_code",
    "procedure_code_jp",
    "procedure_code_us",
    "anesthesia_type",
    "start_datetime",
)


def other_encounters(records: list[Any]) -> list[dict[str, Any]]:
    """The encounters of a patient's structural ``records`` as
    ``{encounter_id, encounter_type, start, end, diagnosis_code, admit_source_encounter_id,
    procedures}`` (start/end ISO strings), in the order given."""
    out: list[dict[str, Any]] = []
    for record in records:
        diagnosis = _o(record, "clinical_diagnosis", None)
        code = str(_o(diagnosis, "discharge_diagnosis_code", "") or _o(diagnosis, "admission_diagnosis_code", "") or "")
        procedures = [{k: _o(p, k, None) for k in _PROCEDURE_KEYS} for p in _o(record, "procedures", []) or []]
        for enc in _o(record, "encounters", []) or []:
            start = str(_o(enc, "admission_datetime", "") or "")
            out.append(
                {
                    "encounter_id": str(_o(enc, "encounter_id", "") or ""),
                    "encounter_type": str(_o(enc, "encounter_type", "") or ""),
                    "start": start,
                    "end": str(_o(enc, "discharge_datetime", "") or "") or start,
                    "diagnosis_code": code,
                    "admit_source_encounter_id": str(_o(enc, "admit_source_encounter_id", "") or ""),
                    "procedures": procedures,
                }
            )
    return out


def _when(value: Any) -> datetime | None:
    parsed = parse_iso_datetime(value, lenient=True)
    return parsed.replace(tzinfo=None) if parsed is not None else None


def interval_events(ctx: Any) -> list[dict[str, Any]]:
    """The inpatient and emergency encounters of ``ctx.interval_encounters``
    that began after the previous outpatient visit ended (within the look-back
    when there is none) and before this visit, oldest first. An emergency visit
    inside an inpatient stay, or the one that led to it, is part of the stay."""
    enc = ctx.encounter
    this_start = _when(_o(enc, "admission_datetime", None))
    others = list(getattr(ctx, "interval_encounters", None) or [])
    if this_start is None or not others:
        return []
    cfg = interval_events_config()
    this_id = str(_o(enc, "encounter_id", "") or "")
    prior_ends = [
        end
        for o in others
        if o["encounter_type"] == "outpatient" and o["encounter_id"] != this_id
        for end in [_when(o["end"])]
        if end is not None and end <= this_start
    ]
    since = max(prior_ends) if prior_ends else this_start - timedelta(days=cfg.lookback_days_without_prior_visit)
    stays = [o for o in others if o["encounter_type"] == "inpatient"]
    led_to_stay = {s["admit_source_encounter_id"] for s in stays if s["admit_source_encounter_id"]}
    events: list[tuple[datetime, dict[str, Any]]] = []
    for o in others:
        if o["encounter_type"] not in _STAY_TYPES or o["encounter_id"] == this_id:
            continue
        start, end = _when(o["start"]), _when(o["end"])
        if start is None or end is None or start >= this_start or end <= since:
            continue
        if o["encounter_type"] == "emergency":
            if o["encounter_id"] in led_to_stay:
                continue
            if any(
                (s0 := _when(s["start"])) is not None and (s1 := _when(s["end"])) is not None and s0 <= start <= s1
                for s in stays
            ):
                continue
        events.append((start, o))
    events.sort(key=lambda e: e[0])
    return [o for _, o in events[-cfg.max_events :]]


def _operation_names(event: dict[str, Any], lang: str) -> list[str]:
    from clinosim.modules.document.narrative.renderers._shared_helpers import procedure_names

    cfg = interval_events_config()
    ops = [p for p in event["procedures"] if str(p.get("anesthesia_type") or "") not in cfg.non_operative_anesthesia]
    return procedure_names(ops, lang)[: cfg.max_procedures]


def _event_sentence(event: dict[str, Any], ctx: Any) -> str:
    from clinosim.modules.document.narrative.renderers._shared_helpers import chronic_condition_label

    lang = ctx.target_lang
    start, end = _when(event["start"]), _when(event["end"])
    if start is None or end is None:
        return ""
    sex = str(_o(ctx.patient, "sex", "") or "") if ctx.patient is not None else ""
    dx = chronic_condition_label(event["diagnosis_code"], country_code(ctx.locale), lang, sex) or ""
    for_dx = t("outpatient.interval_for_dx", lang, dx=dx) if dx else ""
    date_text = start.date().isoformat()
    if event["encounter_type"] == "emergency":
        return t("outpatient.interval_ed", lang, date=date_text, for_dx=for_dx)
    days = max((end.date() - start.date()).days, 1)
    ops = _operation_names(event, lang)
    clause = (
        t("outpatient.interval_procedure_clause", lang, procedures=t("list_sep.semicolon", lang).join(ops))
        if ops
        else ""
    )
    return t("outpatient.interval_admission", lang, date=date_text, for_dx=for_dx, days=days, procedure_clause=clause)


def interval_event_line(ctx: Any) -> str:
    """The sentences stating the visit's interval events; ``""`` when none."""
    from clinosim.modules.document.narrative._visit_reason import join_sentences

    sentences = [s for s in (_event_sentence(e, ctx) for e in interval_events(ctx)) if s]
    return join_sentences(sentences, ctx.target_lang) if sentences else ""
