"""Natural-death sampling module (Issue #1114 C11g-2).

Populates ``PersonRecord.date_of_death`` for a subset of patients using
the actuarial life table in ``locale/shared/actuarial_life_table.yaml``.
POST_POPULATION enricher, per-patient sub-RNG (deterministic + isolated
from the main simulation stream).

C11g-2 scope: sampling + field populated + cohort mortality log. Does
NOT yet route event generators through ``is_alive_at(t)``; C11g-3
adds that filter across the 4+ existing ``is_alive`` boolean call
sites. Encounter emit still runs unchanged for "dead" patients this
release — a follow-up PR wires in the date-aware filter.
"""

from __future__ import annotations

from clinosim.modules.natural_death.enricher import sample_natural_deaths

__all__ = ["sample_natural_deaths"]
