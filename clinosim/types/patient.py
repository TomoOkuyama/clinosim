"""Patient types — profile, physiological profile, baseline vitals."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from clinosim.types.allergy import Allergy  # noqa: F401 — re-exported for callers
from clinosim.types.identity import IdentityTimeline


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
    was the root of the "PO hardcoded on inhaled and SC drugs" cascade
    documented in #452 comments — the drug name string was left to carry
    dose by embedding, which is exactly what #442 catches.

    Reader-side backward compatibility: `__str__` returns `drug_name`, so
    existing substring checks and dedup keys (`"warfarin" in med.lower()`,
    `_dedup_key(med)`) continue to work while individual readers migrate to
    the structured fields (#452 PR 2 / PR 3).
    """

    drug_name: str = ""  # canonical drug identifier (matches chronic YAML `drug`)
    drug_name_ja: str = ""  # optional JP display (matches chronic YAML `drug_ja`)
    route: str = ""  # PO | IV | SC | INH | NEB | ... — validated by #458's KNOWN_ROUTE_VOCABULARY
    dose: str = ""  # freeform text carried through to Order.dose
    dose_quantity: float | None = None
    dose_unit: str = ""
    frequency: str = ""  # daily | bid | tid | qid | prn

    def __str__(self) -> str:
        """Substring-check + dedup back-compat: `"warfarin" in med.lower()` etc.

        Readers migrating to structured access should use `.drug_name`
        explicitly instead of relying on this shim.
        """
        return self.drug_name

    def lower(self) -> str:
        """Same purpose as __str__ — some readers call `med.lower()` directly
        (e.g. renal-hold checks in `_build_discharge_rx`). Return the lowered
        drug name so those continue to fire on the correct string."""
        return self.drug_name.lower()

    def __contains__(self, item: object) -> bool:
        """Substring-check back-compat: `"Warfarin" in home_medication` — used
        by test fixtures and legacy readers written for `list[str]`. Delegates
        to the drug_name string. Removing this in PR 3 requires migrating any
        remaining `"str" in med` call sites to `"str" in med.drug_name`."""
        if not isinstance(item, str):
            return NotImplemented  # type: ignore[return-value]
        return item in self.drug_name


@dataclass
class PatientProfile:
    """Full Layer 2 clinical profile."""

    patient_id: str = ""
    household_id: str = ""  # carried from Layer 1; links family members (AD-54)
    name: PersonName = field(default_factory=PersonName)
    age: int = 0  # kept for backward compat; derived from date_of_birth in output
    sex: str = "M"
    date_of_birth: date | None = None
    # Session 45 seed=400 verification: mortality logic in the inpatient
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
    smoking_status: str = "never"
    alcohol_use: str = "none"

    physiological_profile: PatientPhysiologicalProfile = field(default_factory=PatientPhysiologicalProfile)
    baseline_vitals: BaselineVitals = field(default_factory=BaselineVitals)

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
