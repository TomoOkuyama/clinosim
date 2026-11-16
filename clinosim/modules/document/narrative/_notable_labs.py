"""Wording of a note's notable lab results (Issue #3230).

One wording for the progress-note Assessment ("Notable labs today: ...") and
the LLM context (``abnormal_labs_today`` / ``abnormal_labs_during_stay``):
the analytes :func:`lab_timeseries.select_notable_labs` picks, each as
``<name> <value> <unit> [<flag>] (<prior value>; <finding>)`` at the
analyte's reported precision, capped with a count of the rest.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from clinosim.codes.ucum import ucum_prose
from clinosim.locale.i18n import t
from clinosim.locale.loader import lab_display
from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules.document.narrative._localization import _localize_lab_flag
from clinosim.modules.document.narrative.lab_timeseries import NotableLab, select_notable_labs

__all__ = ["notable_lab_entries"]


def _entry(item: NotableLab, lang: str) -> str:
    from clinosim.modules.observation.engine import format_lab_value

    lab = item.lab
    raw_name = str(_get(lab, "lab_name") or _get(lab, "name") or "")
    unit = str(_get(lab, "unit") or "")
    name = lab_display(raw_name, lang)
    unit_disp = ucum_prose(unit) if unit else ""
    # A dimensionless scale (pH: unit "[pH]") does not repeat its name.
    if unit_disp and unit_disp.lower() == str(name).lower():
        unit_disp = ""
    unit_part = f" {unit_disp}" if unit_disp else ""
    flag = _localize_lab_flag(str(_get(lab, "flag") or ""), lang)
    text = f"{name} {format_lab_value(raw_name, _get(lab, 'value'), unit)}{unit_part} [{flag}]"
    details: list[str] = []
    if item.prior_value is not None:
        details.append(f"{t('list_sep.prior_word', lang)} {format_lab_value(raw_name, item.prior_value, unit)}")
    if item.finding:
        details.append(t(f"lab_finding.{item.finding}", lang))
    if details:
        text += f" ({t('list_sep.semicolon', lang).join(details)})"
    return text


def notable_lab_entries(
    lab_results: list[Any],
    admission_datetime: Any,
    day_index: int | None,
    lang: str,
    *,
    limit: int,
    as_of: datetime | None = None,
) -> list[str]:
    """The worded notable labs of hospital day ``day_index`` (``None``: the
    whole record) known at ``as_of``: at most ``limit`` analytes, then one
    ``progress.notable_labs_more`` entry counting the rest."""
    picks = select_notable_labs(lab_results, admission_datetime, day_index, as_of=as_of)
    entries = [_entry(item, lang) for item in picks[:limit]]
    rest = len(picks) - limit
    if rest > 0:
        entries.append(t("progress.notable_labs_more", lang, count=rest))
    return entries
