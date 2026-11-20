"""The schedule of one prescription line, shared by every renderer (Issue #3389).

``NarrativeContext.discharge_medications`` entries are normalized by
``_collect_discharge_medications`` (``narrative/passes.py``) to
``drug_name`` / ``dose`` / ``route`` / ``rx_frequency`` / ``rx_duration_days``.
The ED take-home prescription, the discharge summary's medication list and the
outpatient SOAP's prescription line all state the same facts of a line, so they
read them through :func:`prescription_bits` and nowhere else: a renderer that
read a raw simulator key (``frequency`` / ``days_supply``) printed a bare dose.

The number of days is the CIF's ``duration_days`` as written (a chronic renewal
is 28-30 days); no "ongoing" label is derived from it.
"""

from __future__ import annotations

import re
from typing import Any

from clinosim.locale.i18n import t
from clinosim.locale.localized import localized_field
from clinosim.modules._shared import get_attr_or_key as _o


def _states(text: str, token: str) -> bool:
    """Whether ``text`` already states ``token`` (case-insensitive; an ASCII
    token such as ``TID`` matches as a whole word)."""
    if not token:
        return True
    if token.isascii():
        return re.search(rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])", text, re.IGNORECASE) is not None
    return token in text


def _first(med: Any, *keys: str) -> Any:
    for key in keys:
        value = _o(med, key, None)
        if value:
            return value
    return None


def prescription_bits(
    med: Any,
    lang: str,
    *,
    drug_name: str = "",
    show_route: bool = True,
) -> list[str]:
    """The dose, route, frequency and days of a prescription line, in ``lang``.

    The pieces follow the line's drug name. A route or frequency the dose text
    already carries (``"200mg 経口 1日1回"``, ``"100mg PO TID"``) is not
    repeated, and a dose already part of ``drug_name`` (``"Ibuprofen 600mg"``)
    is left out. A dose instruction authored for ``lang`` (Issue #3107) is the
    whole instruction and carries the schedule itself.
    """
    from clinosim.locale.free_text import localize_dose_text

    def term(value: str) -> str:
        try:
            return localize_dose_text(value, lang)
        except Exception:  # noqa: BLE001 - a display helper never fails a note
            return value

    dose = str(_o(med, "dose", "") or "").strip()
    route = str(_first(med, "route") or "").strip() if show_route else ""
    frequency = str(_first(med, "rx_frequency", "frequency") or "").strip()
    days = _first(med, "rx_duration_days", "duration_days", "days_supply")
    bits: list[str] = []
    authored = str(localized_field(med, "dose", lang) or "").strip()
    if authored and authored != dose:
        bits.append(authored)
        route = frequency = ""
    elif dose and dose not in drug_name:
        bits.append(term(dose))
    stated = " ".join([term(dose), authored]) if dose or authored else ""
    for raw in (route, frequency):
        if not raw:
            continue
        shown = term(raw)
        if not (_states(stated, shown) or _states(stated, raw) or _states(drug_name, raw)):
            bits.append(shown)
    if isinstance(days, (int, float)) and days > 0:
        bits.append(t("prescription.days_supply_suffix", lang, days=int(days)))
    return bits
