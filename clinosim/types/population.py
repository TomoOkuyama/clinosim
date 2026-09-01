"""Layer-1 population record types (catchment generation).

Plain runtime data types (AD-18 @dataclass) shared between the population module and
the simulator. The behaviour-bearing containers (Household, PopulationRegistry) stay in
the population module; only the data records that cross module boundaries live here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

from clinosim.types.identity import IdentityTimeline
from clinosim.types.patient import HomeMedication

if TYPE_CHECKING:
    from clinosim.types.allergy import Allergy

__all__ = ["HospitalizationSummary", "PersonRecord", "LifeEvent", "TemporalStatePeriod"]


@dataclass
class TemporalStatePeriod:
    """A time-boxed clinical or biographical state a person passes through.

    Introduced by META #957 pregnancy-lifecycle refactor (Incr 1) as the
    canonical replacement for "chronic condition entries that actually
    represent a lifecycle" — currently pregnancy (Z34), later cancer
    active-treatment, warfarin courses, remission, etc.

    Semantics:
      * ``start_date`` inclusive; ``end_date`` inclusive when set; ``None``
        end_date means the period is still open (e.g., ongoing pregnancy).
      * ``outcome`` is populated when the period closes ("delivered" /
        "aborted" / "completed" / …); empty while still open.
      * ``metadata`` carries state-specific structured fields (e.g., for
        pregnancy: ``lmp``, ``edd``, ``delivery_date``). Callers must not
        rely on unknown keys; only the state's dedicated generator writes
        or reads them.
      * ``period_seq`` is 0-indexed per (person, state_type). A woman with
        two delivered pregnancies has ``period_seq=0`` and ``period_seq=1``.
    """

    state_type: str
    start_date: date
    end_date: date | None = None
    outcome: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    period_seq: int = 0

    def is_active_at(self, day: date) -> bool:
        """Return True iff ``day`` falls inside this period (inclusive)."""
        if day < self.start_date:
            return False
        if self.end_date is None:
            return True
        return day <= self.end_date

    def overlaps_year(self, year: int) -> bool:
        """Return True iff the period intersects the calendar ``year``."""
        year_start = date(year, 1, 1)
        year_end = date(year, 12, 31)
        if self.end_date is not None and self.end_date < year_start:
            return False
        if self.start_date > year_end:
            return False
        return True


@dataclass
class HospitalizationSummary:
    """Compact record of a past hospitalization, persisted in Layer 1."""

    encounter_id: str
    disease_id: str
    admission_date: date
    discharge_date: date
    los_days: int
    outcome: str  # "discharged" | "deceased" | "transferred"
    discharge_diagnoses: list[str] = field(default_factory=list)  # ICD codes
    discharge_medications: list[str] = field(default_factory=list)  # drug names
    residual_inflammation: float = 0.0  # state at discharge
    residual_renal: float = 1.0  # state at discharge
    was_readmission: bool = False


@dataclass
class PersonRecord:
    """Layer 1 person record — lightweight but retains medical history."""

    person_id: str
    household_id: str
    age: int
    sex: str
    date_of_birth: date
    family_name: str = ""
    given_name: str = ""
    phonetic: str | None = None
    blood_type: str = "A"  # "A" | "B" | "O" | "AB"
    rh_factor: str = "+"  # "+" | "-" (RhD status)
    # Address and contact (shared at household level)
    postal_code: str = ""
    state: str = ""
    city: str = ""
    address_line: str = ""
    phone_home: str = ""
    phone_mobile: str = ""
    chronic_conditions: list[str] = field(default_factory=list)
    current_medications: list[HomeMedication] = field(default_factory=list)  # active medications (see #452)
    # Occupation category (drives work-related injury risk); see PatientProfile.occupation
    occupation: str = "other"
    # Lifestyle attributes (set at generation time; drive disease risk multipliers)
    bmi: float = 22.0
    smoking_status: str = "never"  # "never" | "former" | "current"
    alcohol_use: str = "none"  # "none" | "social" | "heavy"
    is_alive: bool = True
    care_seeking_threshold: float = 0.3
    has_visited_hospital: bool = False
    visit_count: int = 0
    last_discharge_date: date | None = None
    last_encounter_id: str | None = None
    last_disease_id: str | None = None
    hospitalization_history: list[HospitalizationSummary] = field(default_factory=list)
    # Resident identifier & insurance enrollment (AD-54); populated by a separate
    # post-generation pass (clinosim.modules.identity.assign_identities).
    identity: IdentityTimeline | None = None
    # Allergy history (Tier 1 #3 α-min-1); populated by allergy enricher
    # (POST_POPULATION). activator.py reads this instead of generating its own.
    # None = enricher hasn't run; [] = enricher ran, patient has no allergy.
    # Task 15 will make the enricher the sole source and remove the activator block.
    allergies: list[Allergy] | None = None
    # Time-boxed lifecycle states (META #957 Incr 1). Populated over the
    # life of the simulation by state-scoped generators (currently only
    # the pregnancy-lifecycle generator; cancer active-treatment / acute
    # medication courses / remission arrive in later increments). Distinct
    # from ``chronic_conditions`` which stays for truly chronic diseases
    # (HTN, DM, CKD) that do not have a lifecycle.
    state_periods: list[TemporalStatePeriod] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Issue #452 PR 1 migration shim: accept legacy `list[str]` fixtures
        for `current_medications`. Same behavior as
        `PatientProfile.__post_init__`."""
        from clinosim.types.patient import _normalize_home_medications

        self.current_medications = _normalize_home_medications(self.current_medications)

    def get_active_state(
        self, state_type: str, at_date: date | None = None
    ) -> TemporalStatePeriod | None:
        """Return the (single) active period of ``state_type`` on ``at_date``,
        or ``None`` if the person has no such active period.

        When ``at_date is None``, "active" means "still open" (``end_date``
        is None) — this is the natural query for the pregnancy generator
        checking "is she pregnant right now, unresolved".

        Assumes at most one active period per state_type at a time — this
        holds for pregnancy by biology (no overlapping pregnancies) and is
        expected to hold for the other lifecycle states as they arrive.
        """
        for period in self.state_periods:
            if period.state_type != state_type:
                continue
            if at_date is None:
                if period.end_date is None:
                    return period
            else:
                if period.is_active_at(at_date):
                    return period
        return None

    def has_active_state(
        self, state_type: str, at_date: date | None = None
    ) -> bool:
        """Convenience wrapper around ``get_active_state``."""
        return self.get_active_state(state_type, at_date) is not None

    def state_history(self, state_type: str) -> list[TemporalStatePeriod]:
        """Return every period of ``state_type`` (open + closed), in
        insertion order — which for a period-per-episode generator is
        chronological."""
        return [p for p in self.state_periods if p.state_type == state_type]


@dataclass
class LifeEvent:
    person_id: str
    event_type: str  # "acute_disease_onset" | "chronic_exacerbation" | "trauma" |
    #                   "unknown_condition" | "chronic_visit" | "health_screening" |
    #                   "ed_visit" | "followup"
    timestamp: date
    severity: float = 0.5  # 0.0-1.0
    condition_type: str = "known_disease"  # "known_disease" | "mixed" | "unknown" |
    #                                        "chronic_followup" | "screening" | "ed_visit"
    disease_id: str = ""
    encounter_type: str = "inpatient"  # "inpatient" | "outpatient" | "emergency"
    requires_hospital: bool = False
    is_readmission: bool = False
    prior_encounter_id: str | None = None
    readmission_number: int = 0
    protocol_source: str = ""  # YAML file that defines this encounter's protocol
