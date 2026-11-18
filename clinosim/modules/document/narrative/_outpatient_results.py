"""The results an outpatient note states behind a chronic problem (Issues #3231, #3273).

``reference_data/outpatient_results.yaml`` names the analytes whose latest
earlier result a note cites when the visit has none of its own and the
screening scores. The helpers here read them:

- :func:`prior_lab_values`: the latest result before the note of each such
  analyte, from the labs of the patient's earlier encounters
  (``NarrativeContext.prior_lab_results``) and the note's own;
- :func:`ckd_g_stage`: the CKD G category of an eGFR;
- :func:`screening_scores`: the screening scores of the visit's labs.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinosim.datafiles import load_data_yaml
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.timeutil import parse_iso_datetime

_REF_FILE = Path(__file__).resolve().parents[1] / "reference_data" / "outpatient_results.yaml"


class _Score(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    positive_from: float | None = None
    follow_up: str | None = None


class OutpatientResults(BaseModel):
    """Shape of outpatient_results.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metadata: dict[str, Any] = Field(default_factory=dict)
    prior_lab_analytes: list[str] = Field(min_length=1)
    hold_followup_days: int = Field(gt=0)
    screening_scores: dict[str, _Score]

    @model_validator(mode="after")
    def _check(self) -> OutpatientResults:
        for name, score in self.screening_scores.items():
            if (score.positive_from is None) != (score.follow_up is None):
                raise ValueError(f"screening_scores {name}: positive_from and follow_up go together")
        return self


@lru_cache(maxsize=1)
def outpatient_results() -> OutpatientResults:
    """The validated ``outpatient_results.yaml`` (shared, read-only)."""
    return OutpatientResults.model_validate(load_data_yaml(_REF_FILE))


def ckd_g_stage(egfr: float) -> str:
    """The KDIGO CKD G category of an eGFR (mL/min/1.73 m2), from
    ``modules/longitudinal/reference_data/stage_from_labs.yaml``."""
    from clinosim.modules.longitudinal.stage_refresh import ckd_g_category

    return ckd_g_category(egfr)


def note_time(ctx: Any) -> datetime | None:
    """The time a note's data is known up to: its authored time, else the
    start of its encounter; ``None`` when neither is recorded."""
    when = getattr(ctx, "authored_datetime", None)
    if when is None:
        enc = getattr(ctx, "encounter", None)
        when = parse_iso_datetime(_o(enc, "admission_datetime", None), lenient=True) if enc is not None else None
    return when.replace(tzinfo=None) if isinstance(when, datetime) else None


def prior_lab_values(ctx: Any, *, include_own: bool = False) -> dict[str, tuple[Any, str | None, str]]:
    """The latest result of each ``prior_lab_analytes`` analyte reported at or
    before the note, from the patient's earlier encounters (and, with
    ``include_own``, the note's own encounter), as
    ``{lowercase lab name: (value, unit, YYYY-MM-DD)}``. A result without a
    parseable time is skipped; with no note time, every earlier result counts."""
    from clinosim.modules.observation.engine import canonical_lab_name

    wanted = {a.lower() for a in outpatient_results().prior_lab_analytes}
    cutoff = note_time(ctx)
    labs = list(getattr(ctx, "prior_lab_results", None) or [])
    if include_own:
        labs.extend(getattr(ctx, "lab_results", None) or [])
    best: dict[str, tuple[datetime, Any]] = {}
    for lab in labs:
        name = str(_o(lab, "lab_name", "") or "")
        at = parse_iso_datetime(_o(lab, "result_datetime", None), lenient=True)
        if canonical_lab_name(name).lower() not in wanted or at is None or _o(lab, "value", None) is None:
            continue
        at = at.replace(tzinfo=None)
        if cutoff is not None and at > cutoff:
            continue
        key = name.lower()
        if key not in best or at >= best[key][0]:
            best[key] = (at, lab)
    return {k: (_o(lab, "value", None), _o(lab, "unit", None), at.date().isoformat()) for k, (at, lab) in best.items()}


def latest_lab_stage(code: str, stored: str, labs: dict[str, tuple[Any, str | None, str]]) -> str:
    """The stage of a chronic problem stated by the latest known lab (``labs``
    from :func:`prior_lab_values`): the CKD G category and eGFR of an N18
    problem, the HbA1c of a problem whose stored stage is an HbA1c. Empty when
    no lab states it (the stored stage is used)."""
    egfr = labs.get("egfr")
    if code.upper().startswith("N18") and egfr is not None:
        try:
            value = float(egfr[0])
        except (TypeError, ValueError):
            return ""
        return f"CKD {ckd_g_stage(value)}, eGFR {value:g} ({egfr[2]})"
    hba1c = labs.get("hba1c")
    if hba1c is not None and stored.startswith("HbA1c"):
        try:
            return f"HbA1c {float(hba1c[0]):g}% ({hba1c[2]})"
        except (TypeError, ValueError):
            return ""
    return ""


def screening_scores(lab_results: list[Any]) -> list[tuple[str, float, str | None]]:
    """The visit's screening scores as ``(lab name, value, follow-up key)``;
    the follow-up key is set for a positive screen. Lab order, one entry per
    score (the last draw)."""
    spec = outpatient_results().screening_scores
    seen: dict[str, tuple[str, float, str | None]] = {}
    for lab in lab_results or []:
        name = str(_o(lab, "lab_name", "") or "")
        value = _o(lab, "value", None)
        if name not in spec or isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        rule = spec[name]
        positive = rule.positive_from is not None and float(value) >= rule.positive_from
        seen[name] = (name, float(value), rule.follow_up if positive else None)
    return list(seen.values())
