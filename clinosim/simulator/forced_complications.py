"""Test-only forcing of in-stay complications for ``run_forced`` (Issue #3976).

The refactoring corpus (``tests/refactor_corpus/``) must execute complication
paths that fire about once per thousand stays. ``ForcedScenario`` already
forces the disease, severity and archetype; ``force_complications`` adds the
complication: a copy of the protocol in which each named complication fires
on its stated day. The daily loop is unchanged — it evaluates the copied
entries like any other (one draw per eligible complication and day, as for
every protocol), and a copied entry is certain to fire on its day.

``run_forced`` is the only caller. A population run never reads
``force_complications``, so its output cannot depend on this module.
"""

from __future__ import annotations

from typing import Any

from clinosim.modules.disease.protocol import DiseaseProtocol
from clinosim.types.config import ForcedComplication

#: The keys of a complication entry that decide whether and when it fires
#: (``clinical_course.engine.evaluate_complications``). A forced entry drops
#: them and fires with probability 1 inside a one-day onset window.
_FIRING_KEYS = ("onset_day_range", "parent_complication", "probability_given_parent", "probability_per_day")


def forced_complication_protocol(protocol: DiseaseProtocol, forced: list[ForcedComplication]) -> DiseaseProtocol:
    """The protocol with each ``forced`` complication certain to fire on its day.

    Returns ``protocol`` itself when nothing is forced. Otherwise a copy (the
    cached protocol is never mutated) whose named entries keep their state
    impact, actions and every other key but fire on ``day`` with probability
    1, without a parent complication or risk factors.

    Raises:
        ValueError: a forced name that is not a complication of the protocol.
    """
    if not forced:
        return protocol
    by_name = {f.name: f for f in forced}
    known = {str(c.get("name", "")) for c in protocol.complications}
    unknown = sorted(set(by_name) - known)
    if unknown:
        raise ValueError(
            f"force_complications: {unknown} are not complications of {protocol.disease_id!r} (known: {sorted(known)})"
        )
    entries: list[dict[str, Any]] = []
    for comp in protocol.complications:
        spec = by_name.get(str(comp.get("name", "")))
        if spec is None:
            entries.append(comp)
            continue
        entry = {k: v for k, v in comp.items() if k not in _FIRING_KEYS}
        entry.update(onset_day_range=[spec.day, spec.day], probability_per_day=1.0, risk_factors=[])
        entries.append(entry)
    return protocol.model_copy(update={"complications": entries})
