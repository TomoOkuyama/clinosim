"""Patient types — profile, physiological profile, baseline vitals."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

from clinosim.types.allergy import Allergy  # noqa: F401 — re-exported for callers
from clinosim.types.identity import IdentityTimeline

if TYPE_CHECKING:
    from clinosim.modules.drug_safety.verdict import SafetySkipEntry


@dataclass
class TemporalStatePeriod:
    """A time-boxed clinical or biographical state a person passes through.

    Introduced by META #957 pregnancy-lifecycle refactor (Incr 1) as the
    canonical replacement for "chronic condition entries that actually
    represent a lifecycle" — currently pregnancy (Z34 + Z37 past-birth
    marker), later cancer active-treatment, warfarin courses, remission,
    etc.

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
class PatientPhysiologicalProfile:
    """Hidden constitutional parameters. Determined once, stable across visits."""

    immune_reactivity: float = 0.5
    drug_metabolism_rate: str = "normal"  # "poor" | "normal" | "rapid" | "ultra_rapid"
    renal_reserve: float = 0.8
    cardiac_reserve: float = 0.8
    hepatic_reserve: float = 0.85
    treatment_sensitivity: float = 1.0
    symptom_reporting_bias: float = 1.0
    delirium_susceptibility: float = 0.2
    dvt_susceptibility: float = 0.2


@dataclass
class BaselineVitals:
    """This person's normal values when healthy."""

    temperature: float = 36.5
    heart_rate: int = 72
    systolic_bp: int = 120
    diastolic_bp: int = 75
    respiratory_rate: int = 16
    spo2: float = 97.5


@dataclass
class Address:
    """Postal address."""

    postal_code: str = ""
    state: str = ""  # US: state, JP: prefecture
    city: str = ""
    line1: str = ""  # street address
    line2: str = ""  # apt/unit
    country: str = "US"


@dataclass
class ContactInfo:
    """Patient contact information."""

    phone_home: str = ""  # household landline
    phone_mobile: str = ""  # personal mobile
    phone_primary: str = ""  # which one to use (home or mobile)
    email: str = ""
    emergency_contact_name: str = ""
    emergency_contact_phone: str = ""
    emergency_contact_relationship: str = ""


@dataclass
class PersonName:
    """Country-appropriate name representation (AD-25)."""

    family_name: str = ""
    given_name: str = ""
    display_name: str = ""
    name_script: str = "en"
    phonetic: str | None = None


@dataclass
class ChronicCondition:
    code: str = ""
    system: str = "icd-10-cm"  # code system key (lookup via clinosim.codes)
    onset_date: date | None = None
    severity: str = "mild"
    controlled: bool = True
    severity_score: float = 0.3
    stage: str = ""  # e.g., "CKD G3a", "NYHA II", "HbA1c 7.2%"
    glycemic_control: float | None = None  # E11/E10 only; 1.0=excellent .. 0.0=very poor


@dataclass
class HomeMedication:
    """A single active home medication with the structured fields the upstream
    YAML actually carries (Issue #452).

    Pre-#452, `current_medications` was `list[str]` (drug name only), which
    silently discarded `route` / `frequency` / `dose` at the two producer
    sites (`activator._derive_home_medications` reading
    `chronic_medications.yaml`, and `helpers._deactivate_to_layer1` reading
    the previous encounter's `discharge_prescription.items`). Losing `route`
    was the root of the "PO hardcoded on inhaled and SC drugs" cascade —
    the drug name string was left to carry dose by embedding, which is
    exactly what #442 catches.

    #452 PR 3 retired the reader-side back-compat shims (`__str__`, `lower`,
    `__contains__`): every reader now accesses `.drug_name` / `.route` / etc.
    explicitly.
    """

    drug_name: str = ""  # canonical drug identifier (matches chronic YAML `drug`)
    drug_name_ja: str = ""  # optional JP display (matches chronic YAML `drug_ja`)
    route: str = ""  # PO | IV | SC | INH | NEB | ... — validated by #458's KNOWN_ROUTE_VOCABULARY
    dose: str = ""  # freeform text carried through to Order.dose
    dose_quantity: float | None = None
    dose_unit: str = ""
    frequency: str = ""  # daily | bid | tid | qid | prn


@dataclass
class PatientProfile:
    """Full Layer 2 clinical profile."""

    patient_id: str = ""
    household_id: str = ""  # carried from Layer 1; links family members (AD-54)
    name: PersonName = field(default_factory=PersonName)
    age: int = 0  # kept for backward compat; derived from date_of_birth in output
    sex: str = "M"
    date_of_birth: date | None = None
    # seed=400 verification: mortality logic in the inpatient
    # simulator (helpers._evaluate_mortality) was firing (74 expired IMP at
    # seed=400) but the flag never propagated to Patient FHIR emit. Setting
    # this at the moment of in-hospital death lets `_fhir_patient` emit
    # `deceasedDateTime` matching the Encounter dischargeDisposition="expired".
    date_of_death: date | None = None
    blood_type: str = "A"
    rh_factor: str = "+"
    height_cm: float = 170.0
    weight_kg: float = 65.0
    bmi: float = 22.5

    address: Address = field(default_factory=Address)
    contact: ContactInfo = field(default_factory=ContactInfo)

    marital_status: str = ""  # "S" | "M" | "D" | "W" | "U" (HL7 v3-MaritalStatus)
    preferred_language: str = ""  # BCP-47 code: "en-US" | "ja-JP"

    employment_status: str = "retired"
    # Occupation category (drives work-related injury risk):
    # "manufacturing" | "construction" | "agriculture" | "healthcare" |
    # "service" | "office" | "transportation" | "education" |
    # "homemaker" | "student" | "retired" | "unemployed" | "other"
    occupation: str = "other"
    insurance_type: str = "NHI_employee"
    # Resident identifier & insurance enrollment (AD-54). Carried from Layer 1.
    # NOTE: identity.national.national_id is for internal use only — output adapters
    # MUST NOT emit it (privacy chokepoint).
    identity: IdentityTimeline | None = None
    race: str = ""  # OMB race category — US only: "white"|"black"|"asian"|"native_american"|"other"
    ethnicity: str = ""  # "hispanic" | "not_hispanic" — US only
    health_literacy: float = 0.7

    chronic_conditions: list[ChronicCondition] = field(default_factory=list)
    allergies: list[Allergy] = field(default_factory=list)
    current_medications: list[HomeMedication] = field(default_factory=list)
    # Issue #1066 (drug_safety): per-patient log of medication candidates that
    # were skipped by the contraindication gate. Populated by
    # ``clinosim.modules.patient.activator`` during home-med derivation and by
    # ``clinosim.simulator.medication_pipeline`` during per-encounter emit.
    # NOT emitted into FHIR structured resources — matches real CPOE workflow
    # where blocked orders leave no chart trace. Consumed by narrative context
    # so the physician's avoidance reasoning surfaces in progress notes.
    safety_skip_log: list[SafetySkipEntry] = field(default_factory=list)
    # Issue #433 C1: immutable snapshot of the patient's baseline chronic
    # medications, captured at Layer 1 → Layer 2 activation. `current_medications`
    # is a dynamic view that mutates across encounters (renal-hold at discharge,
    # hospital-started drug propagation, etc.); `baseline_chronic_medications`
    # preserves the original list so that a drug held during an AKI admission
    # can be re-emitted at discharge after renal function recovers, and so that
    # `_build_discharge_rx` can distinguish "held this admission" from
    # "chronic drug permanently discontinued". Populated by `activate_patient`
    # as a shallow copy of `current_medications` at activation time; never
    # mutated after that. Empty until the activator runs.
    baseline_chronic_medications: list[HomeMedication] = field(default_factory=list)
    smoking_status: str = "never"
    alcohol_use: str = "none"

    physiological_profile: PatientPhysiologicalProfile = field(default_factory=PatientPhysiologicalProfile)
    baseline_vitals: BaselineVitals = field(default_factory=BaselineVitals)
    # META #957 Incr 1: time-boxed lifecycle states (pregnancy for now).
    # Mirrors ``PersonRecord.state_periods`` and is copied through by the
    # patient activator so that FHIR emit adapters (Z37 past-birth marker
    # via ``state_history("pregnancy")``) can read it from the record dict.
    state_periods: list[TemporalStatePeriod] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Issue #452 PR 1 migration shim: accept legacy `list[str]` fixtures
        for `current_medications` and lift each string into a bare
        `HomeMedication(drug_name=s)`. Remove in PR 3 once all fixtures use
        `HomeMedication` directly."""
        self.current_medications = _normalize_home_medications(self.current_medications)


def _normalize_home_medications(items: list) -> list[HomeMedication]:
    """Accept legacy `list[str]` and current `list[HomeMedication]`. Any
    string is promoted to `HomeMedication(drug_name=s)`. Empty strings and
    Nones are dropped (matches the pre-#452 filter in activator.py:308)."""
    out: list[HomeMedication] = []
    for item in items or []:
        if item is None or item == "":
            continue
        if isinstance(item, HomeMedication):
            out.append(item)
        elif isinstance(item, str):
            out.append(HomeMedication(drug_name=item))
        elif isinstance(item, dict):
            # Rare but has appeared in test fixtures — build from keys.
            out.append(
                HomeMedication(
                    drug_name=str(item.get("drug_name") or item.get("drug") or ""),
                    drug_name_ja=str(item.get("drug_name_ja") or item.get("drug_ja") or ""),
                    route=str(item.get("route") or ""),
                    dose=str(item.get("dose") or ""),
                    frequency=str(item.get("frequency") or ""),
                )
            )
        else:
            raise TypeError(f"current_medications item must be HomeMedication / str / dict, got {type(item).__name__}")
    return out
