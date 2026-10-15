"""Population module — Layer-1 catchment generation and monthly life events."""

from clinosim.modules.population._population_thresholds import (
    BMI_MORBID_OBESITY_THRESHOLD,
    BMI_OBESE_THRESHOLD,
    BMI_OVERWEIGHT_THRESHOLD,
)
from clinosim.modules.population.engine import (
    HospitalizationSummary,
    LifeEvent,
    PersonRecord,
    generate_healthcare_calendar,
    generate_monthly_events,
    generate_population,
)

__all__ = [
    "BMI_MORBID_OBESITY_THRESHOLD",
    "BMI_OBESE_THRESHOLD",
    "BMI_OVERWEIGHT_THRESHOLD",
    "HospitalizationSummary",
    "LifeEvent",
    "PersonRecord",
    "generate_healthcare_calendar",
    "generate_monthly_events",
    "generate_population",
]
