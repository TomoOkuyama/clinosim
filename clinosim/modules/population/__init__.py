"""Population module — Layer-1 catchment generation and monthly life events."""

from clinosim.modules.population.engine import (
    HospitalizationSummary,
    LifeEvent,
    PersonRecord,
    generate_healthcare_calendar,
    generate_monthly_events,
    generate_population,
)

__all__ = [
    "HospitalizationSummary",
    "LifeEvent",
    "PersonRecord",
    "generate_healthcare_calendar",
    "generate_monthly_events",
    "generate_population",
]
