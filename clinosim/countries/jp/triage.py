"""JTAS — Japan Triage and Acuity Scale (``triage_scale`` "jtas", Issue #3144).

The level is drawn from the severity distribution shared with ESI
(:func:`clinosim.modules.triage.engine.pick_triage_level`); the scale names
the level system the level is recorded under.
"""

from __future__ import annotations

from clinosim.country_profile import register_implementation


@register_implementation("triage_scale", "jtas")
def jtas_scale() -> str:
    """Japan Triage and Acuity Scale."""
    return "JTAS"
