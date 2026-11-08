"""Population module — Layer-1 catchment generation and monthly life events."""

from clinosim.modules.population._population_thresholds import (
    BMI_MORBID_OBESITY_THRESHOLD,
    BMI_OBESE_THRESHOLD,
    BMI_OVERWEIGHT_THRESHOLD,
)
from clinosim.modules.population._population_workflow_thresholds import (
    FLU_VAX_MONTHS,
    is_flu_vaccination_candidate,
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
    "FLU_VAX_MONTHS",
    "HospitalizationSummary",
    "LifeEvent",
    "PersonRecord",
    "generate_healthcare_calendar",
    "generate_monthly_events",
    "generate_population",
    "is_flu_vaccination_candidate",
]
