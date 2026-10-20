"""Layer-1 population record types (catchment generation).

Plain runtime data types (AD-18 @dataclass) shared between the population module and
the simulator. The behaviour-bearing containers (Household, PopulationRegistry) stay in
the population module; only the data records that cross module boundaries live here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

from clinosim.types.identity import IdentityTimeline
from clinosim.types.patient import HomeMedication, TemporalStatePeriod

if TYPE_CHECKING:
    from clinosim.modules.longitudinal.snapshot import YearSnapshot

if TYPE_CHECKING:
    from clinosim.types.allergy import Allergy

__all__ = ["HospitalizationSummary", "PersonRecord", "LifeEvent", "TemporalStatePeriod"]


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
    # Issue #1114 C11g-2: natural-death date, populated by the
    # ``natural_death`` POST_POPULATION enricher when the actuarial
    # Bernoulli against ``locale/shared/actuarial_life_table.yaml``
    # qx hits within the sim window. Stays ``None`` for patients who
    # survive the window. Consumed by ``is_alive_at(t)`` (this file)
    # and (from C11g-3 onward) by event-emit filters + FHIR
    # deceasedDateTime. Distinct from in-hospital death which flips
    # ``PatientProfile.deceased`` inside the discharge gate.
    date_of_death: date | None = None
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
    # Atopic-march inheritance multiplier (Issue #1581 Phase C.2). Scales
    # the annual Bernoulli rate for new-allergy emergence in
    # ``aging._allergy_drift``. The initial-cohort generator leaves this
    # at 1.0 (no bump); ``register_newborn`` reads the mother's allergy
    # list at registration and raises the multiplier when the mother is
    # atopic, so children of allergic mothers have a higher per-year
    # chance of developing their own allergy. 1.0 is clinically neutral,
    # 2.0 is the single-atopic-parent rough OR from standard allergy
    # epidemiology (Bousquet et al 2008 Allergy; Hong et al 2012
    # Pediatr Allergy Immunol). Deliberately capped since we currently
    # only observe the mother — a two-parent model would push toward
    # ~3-4x per the same literature (Phase C.2 follow-up).
    atopic_predisposition: float = 1.0
    # Phase 1 longitudinal state-evolution subsystem (Issue #1695,
    # ``docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md``).
    # One entry per sim year per alive person, populated by
    # ``clinosim.modules.longitudinal.engine.initial_snapshot`` at
    # Layer-1 generation and ``advance_one_year`` from the aging
    # driver. Replaces ``glycemic_trajectory`` as the single source
    # of truth for continuous latents (HbA1c, LDL in later phases) and
    # discrete stages (CKD, CCS, NYHA, CDR in later phases). Empty
    # list for pre-engine fixtures.
    longitudinal_history: list[YearSnapshot] = field(default_factory=list)
    # Issue #1581 Phase C.3 — single-gene disease carrier status.
    # Keyed by ICD code, valued with one of:
    #   "normal"   — no disease allele
    #   "carrier"  — heterozygous (asymptomatic for recessive conditions)
    #   "affected" — homozygous (autosomal) or hemizygous male
    #                (X-linked), symptomatic
    # Populated at initial-cohort generation via race-conditional SHA
    # sampling, and at ``register_newborn`` time via Mendelian Punnett
    # from parent phenotypes. Affected persons also carry the ICD
    # code on ``chronic_conditions`` so the condition emits through
    # the standard FHIR disease pipeline. Empty for codes outside the
    # catalog.
    carrier_status: dict[str, str] = field(default_factory=dict)
    # Issue #1581 — race / ethnicity (US only). Previously resampled on
    # every ``activate_patient`` call, which meant the same person could
    # see a different race across encounters within a sim. Now stored
    # once on the PersonRecord so activation reads a stable value, and
    # the newborn's ``register_newborn`` can inherit the mother's race
    # / ethnicity (family-level attribute). Empty string means
    # "unassigned" — the locale has no race_distribution yaml
    # (JP) or the person pre-dates this field (test fixtures). The
    # activator falls back to its original per-call sampling in that
    # case so backwards compatibility is preserved.
    race: str = ""
    ethnicity: str = ""
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

    def get_active_state(self, state_type: str, at_date: date | None = None) -> TemporalStatePeriod | None:
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

    def has_active_state(self, state_type: str, at_date: date | None = None) -> bool:
        """Convenience wrapper around ``get_active_state``."""
        return self.get_active_state(state_type, at_date) is not None

    def is_alive_at(self, when: date) -> bool:
        """Return True if the person is alive at ``when`` (Issue #1114 C11g-2).

        Rule: alive iff ``date_of_birth <= when`` (the person has already
        been born) AND (``date_of_death is None`` OR ``when < date_of_death``).
        The death day itself counts as not-alive — matches the standard
        actuarial convention that a person "dies on" their death date and
        is unavailable for events scheduled on that day or later. The
        pre-birth guard (Issue #1564 Phase 1 follow-up) protects newborns
        registered mid-sim from receiving events dated before their
        delivery (healthcare calendar iterates every cal_year including
        years before a newborn's birth; without this guard a pediatric
        well-child visit scheduled at month=3 of a baby's birth year
        would fire for a date the baby did not yet exist).
        """
        if self.date_of_birth is not None and when < self.date_of_birth:
            return False
        if self.date_of_death is None:
            return True
        return when < self.date_of_death

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
