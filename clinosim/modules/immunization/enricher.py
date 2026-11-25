"""Immunization enricher (AD-55 Base, AD-56 post_records).

Generates each patient's vaccine history with a dedicated sub-seed so the main
simulation random stream is untouched (AD-16). occurrence dates <= snapshot (AD-32).
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from clinosim import determinism
from clinosim.codes import system_key_for
from clinosim.countries import is_jp
from clinosim.datafiles import load_validated_yaml
from clinosim.locale.clinic_calendar import clinic_visit_day, is_clinic_day
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules._shared import set_attr_or_key as _set
from clinosim.modules.immunization.engine import (
    DoseInterval,
    dose_intervals_by_cvx,
    dose_windows_by_cvx,
    flu_season_of,
    generate_immunizations_for_country,
    generate_pregnancy_tdap,
    licensed_from_by_cvx,
    load_schedule,
    lot_cvx_by_cvx,
    redate,
    series_allows,
    synthetic_lot_number,
)
from clinosim.modules.immunization.visits import (
    bind_to_vaccination_visits_for_country,
    flu_season_months,
    is_flu_visit_candidate,
    vaccination_visits_by_patient,
)
from clinosim.modules.pediatric.calendar import is_acute_illness_condition
from clinosim.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed
from clinosim.types.encounter import (
    Encounter,
    EncounterStatus,
    EncounterType,
    ImmunizationRecord,
    VitalSignRecord,
)

_PRECAUTIONS_PATH = Path(__file__).parent / "reference_data" / "vaccination_precautions.yaml"
_FALLBACK_FEBRILE_CELSIUS = 38.0


class _VaccinationPrecautions(BaseModel):
    """Shape of ``reference_data/vaccination_precautions.yaml``."""

    model_config = ConfigDict(extra="forbid")

    metadata: dict[str, Any] = Field(default_factory=dict)
    febrile_celsius: float = Field(gt=0)


@lru_cache(maxsize=1)
def _febrile_celsius() -> float:
    """Temperature at or above which a visit is febrile (Issue #3655), from
    ``reference_data/vaccination_precautions.yaml``."""
    data = load_validated_yaml(_PRECAUTIONS_PATH, _VaccinationPrecautions)
    return float(data.get("febrile_celsius", _FALLBACK_FEBRILE_CELSIUS))


class _VaccinationVisit(BaseModel):
    """Shape of ``reference_data/vaccination_visit.yaml``."""

    model_config = ConfigDict(extra="forbid")

    metadata: dict[str, Any] = Field(default_factory=dict)
    duration_minutes: int = Field(gt=0)


_VISIT_PATH = Path(__file__).parent / "reference_data" / "vaccination_visit.yaml"
_FALLBACK_VISIT_MINUTES = 15


@lru_cache(maxsize=1)
def vaccination_visit_minutes() -> int:
    """Length of a synthesised vaccination visit in minutes (Issue #3656)."""
    data = load_validated_yaml(_VISIT_PATH, _VaccinationVisit)
    return int(data.get("duration_minutes", _FALLBACK_VISIT_MINUTES))


class _EdVaccineDoses(BaseModel):
    """Shape of ``reference_data/ed_vaccine_doses.yaml``."""

    model_config = ConfigDict(extra="forbid")

    metadata: dict[str, Any] = Field(default_factory=dict)
    drug_cvx: dict[str, str]
    tetanus_containing_cvx: list[str]
    after_wound_dose_days: int = Field(gt=0)


_ED_DOSES_PATH = Path(__file__).parent / "reference_data" / "ed_vaccine_doses.yaml"


@lru_cache(maxsize=1)
def _ed_vaccine_config() -> dict[str, Any]:
    return load_validated_yaml(_ED_DOSES_PATH, _EdVaccineDoses)


def ed_vaccine_cvx() -> tuple[str, ...]:
    """CVX of every vaccine an emergency-department order can give (``drug_cvx``)."""
    return tuple(dict.fromkeys(_ed_vaccine_config()["drug_cvx"].values()))


def ed_vaccine_doses(records: list) -> list[ImmunizationRecord]:
    """The Immunizations of the vaccine doses a patient was given as one-time
    orders in the emergency department (Issue #3685): each given
    administration of a drug of ``drug_cvx`` across the patient's ``records``,
    on the administration's date and its order's encounter, with a synthetic
    lot and the administering nurse. A dose appears once however many records
    carry it. Deterministic, no rng."""
    drug_cvx: dict[str, str] = _ed_vaccine_config().get("drug_cvx", {})
    out: dict[tuple[str, date, str], ImmunizationRecord] = {}
    for rec in records:
        enc_of = {
            str(_get(o, "order_id", "") or ""): str(_get(o, "encounter_id", "") or "")
            for o in _get(rec, "orders", []) or []
        }
        for mar in _get(rec, "medication_administrations", []) or []:
            cvx = drug_cvx.get(str(_get(mar, "drug_id", "") or ""))
            when = _get(mar, "actual_datetime", None)
            if cvx is None or str(_get(mar, "status", "given") or "given") != "given" or not isinstance(when, datetime):
                continue
            eid = enc_of.get(str(_get(mar, "order_id", "") or ""), "")
            key = (cvx, when.date(), eid)
            if key not in out:
                out[key] = ImmunizationRecord(
                    vaccine_cvx=cvx,
                    occurrence_date=when.date(),
                    status="completed",
                    primary_source=True,
                    lot_number=synthetic_lot_number(cvx, when.date()),
                    administered_by=str(_get(mar, "administered_by", "") or ""),
                    encounter_id=eid,
                )
    return sorted(out.values(), key=lambda i: (i.occurrence_date, i.vaccine_cvx))


def drop_wound_covered_doses(recs: list, ed_doses: list) -> list:
    """``recs`` without the scheduled tetanus-containing doses that fall within
    ``after_wound_dose_days`` after an ED tetanus dose (Issue #3685)."""
    cfg = _ed_vaccine_config()
    tetanus = set(cfg["tetanus_containing_cvx"])
    window = timedelta(days=int(cfg["after_wound_dose_days"]))
    given = [d.occurrence_date for d in ed_doses if str(d.vaccine_cvx) in tetanus]

    def covered(imm: object) -> bool:
        occ = _get(imm, "occurrence_date", None)
        if str(_get(imm, "vaccine_cvx", "") or "") not in tetanus or not isinstance(occ, date):
            return False
        return any(day < occ <= day + window for day in given)

    return [i for i in recs if not covered(i)]


def acute_visit_encounter_ids(records: list) -> set[str]:
    """Ids of the encounters a routine dose is not given at (Issue #3655): a
    pediatric acute-illness visit (``condition_event.visit_condition_id``) and
    any visit of a record whose vital set of the visit day has a temperature
    at or above the febrile threshold. Synthesized vaccination visits are
    never excluded."""
    febrile = _febrile_celsius()
    out: set[str] = set()
    for rec in records:
        encs = [
            e
            for e in (_get(rec, "encounters", []) or [])
            if (_get(e, "encounter_id", "") or "") and not str(_get(e, "encounter_id", "")).startswith("ENC-VAX-")
        ]
        cond = _get(rec, "condition_event", None)
        if (
            cond is not None
            and _get(cond, "visit_type", "") == "pediatric_visit"
            and is_acute_illness_condition(str(_get(cond, "visit_condition_id", "") or ""))
        ):
            out.update(str(_get(e, "encounter_id", "")) for e in encs)
        febrile_days = {
            vs.timestamp.date()
            for vs in (_get(rec, "vital_signs", []) or [])
            if (_get(vs, "temperature_celsius", None) or 0) >= febrile
            and isinstance(_get(vs, "timestamp", None), datetime)
        }
        for e in encs:
            adm = _get(e, "admission_datetime", None)
            if isinstance(adm, datetime) and adm.date() in febrile_days:
                out.add(str(_get(e, "encounter_id", "")))
    return out


def _as_of(ctx, rec) -> date:
    snap = _get(_get(ctx, "config"), "snapshot_date", None) if _get(ctx, "config") else None
    if snap:
        y, m, d = (int(x) for x in str(snap).split("-"))
        # Issue #926: cap `as_of` at date_of_death so the immunization
        # scheduler never emits a vaccine after the patient has died.
        # Nine of the 47 deceased patients in p=10000 v0.5.0 received
        # post-mortem flu shots (the flu scheduler picks a fixed month
        # per year — 11-01 — independent of death status). Clamping
        # here is the single seam that gates all three frequency
        # branches (annual / every_n_years / once) in
        # ``generate_immunizations`` without touching the pure engine.
        patient = _get(rec, "patient")
        dod = _get(patient, "date_of_death", None) if patient else None
        if isinstance(dod, date):
            return min(date(y, m, d), dod)
        return date(y, m, d)
    # else: latest encounter admission date
    encs = _get(rec, "encounters", []) or []
    dates = []
    for e in encs:
        adm = _get(e, "admission_datetime")
        if isinstance(adm, datetime):
            dates.append(adm.date())
    if dates:
        latest = max(dates)
        # Issue #926: same cap for the fallback branch.
        patient = _get(rec, "patient")
        dod = _get(patient, "date_of_death", None) if patient else None
        if isinstance(dod, date):
            return min(latest, dod)
        return latest
    raise ValueError(
        "immunization _as_of(): no deterministic date reference available — "
        "ctx.config.snapshot_date is unset AND the record has no encounters "
        "with a valid admission_datetime. The CLI always resolves "
        "snapshot_date (default: today, resolved once at invocation) before "
        "any record is processed, so this indicates a caller/test setup gap, "
        "not a real simulation path."
    )


def _give_stay_doses_by_ward_nurse(imm_recs: list, encounters: list, roster: Any, pid: str) -> None:
    """A dose bound to an inpatient stay is given by a nurse of that stay's
    ward (Issue #2700): the hepatitis B birth dose by a nursery nurse.
    Stable per patient (no rng)."""
    from clinosim.modules.staff.engine import scoped_nurses

    wards = {
        str(_get(e, "encounter_id", "")): (str(_get(e, "ward_id", "") or ""), str(_get(e, "department_id", "") or ""))
        for e in encounters
        if str(_get(e, "encounter_type", "") or "").lower().endswith("inpatient") or _get(e, "ward_id", "")
    }
    for imm in imm_recs:
        ward_dept = wards.get(str(_get(imm, "encounter_id", "") or ""))
        if not ward_dept or not ward_dept[0] or ward_dept[0] in ("OPD", "ER"):
            continue
        nurses = sorted(m.staff_id for m in scoped_nurses(roster, ward=ward_dept[0], department=ward_dept[1]))
        if nurses:
            _set(imm, "administered_by", nurses[sum(ord(c) for c in pid) % len(nurses)])


def _order_stay_doses(rec: Any, imm_recs: list, country: str) -> None:
    """Issue #3688: a vaccine given during an inpatient stay of ``rec`` (the
    hepatitis B birth dose in the nursery) is ordered at the admission, as the
    vitamin K and the eye prophylaxis of the stay are. The ``Immunization`` is
    the administration record, so no medication administration is added (it
    would duplicate the dose in FHIR). One order per dose, no RNG."""
    from clinosim.codes import display as registry_display
    from clinosim.codes.drugs import resolve_drug
    from clinosim.modules.immunization.engine import vaccine_administration, vaccine_order_drug
    from clinosim.modules.observation.pediatric_ranges import age_in_completed_months
    from clinosim.types.encounter import Order, OrderStatus, OrderType

    stays = {
        str(_get(e, "encounter_id", "") or ""): e
        for e in _get(rec, "encounters", []) or []
        if str(getattr(_get(e, "encounter_type", ""), "value", _get(e, "encounter_type", ""))).lower()
        in ("inpatient", "imp")
    }
    if not stays:
        return
    patient = _get(rec, "patient")
    pid = str(_get(patient, "patient_id", "") or "")
    orders = _get(rec, "orders", None)
    if orders is None:
        orders = []
        _set(rec, "orders", orders)
    have = {str(_get(o, "order_id", "") or "") for o in orders}
    for imm in imm_recs:
        enc = stays.get(str(_get(imm, "encounter_id", "") or ""))
        if enc is None or str(_get(imm, "status", "completed") or "completed") != "completed":
            continue
        cvx = str(_get(imm, "vaccine_cvx", "") or "")
        drug_id = vaccine_order_drug(country, cvx)
        record = resolve_drug(drug_id) if drug_id else None
        name = record.names.get("en", "") if record else ""
        if not name:
            # No catalog drug: the CVX display, without the comma the
            # MedicationRequest builder reads the drug name up to.
            head, sep, tail = (registry_display("cvx", cvx, "en") or "").partition(", ")
            name = f"{head} ({tail})" if sep else head
        dose = _get(imm, "dose_number", None)
        oid = f"ORD-{_get(enc, 'encounter_id', '')}-IMM-{cvx}" + (f"-{dose}" if dose else "")
        if not name or oid in have:
            continue
        have.add(oid)
        admitted = _get(enc, "admission_datetime", None)
        given = vaccine_administration(
            country,
            cvx,
            age_in_completed_months(_get(patient, "date_of_birth", None), _get(imm, "occurrence_date", None)),
        )
        orders.append(
            Order(
                order_id=oid,
                encounter_id=str(_get(enc, "encounter_id", "") or ""),
                patient_id=pid,
                order_type=OrderType.MEDICATION,
                display_name=name,
                drug_id=drug_id,
                urgency="routine",
                ordered_datetime=admitted,
                ordered_by=str(_get(enc, "attending_physician_id", "") or ""),
                status=OrderStatus.PLACED,
                frequency="once",
                frequency_per_day=1,
                route=given.route if given else "",
                dose_quantity=given.dose_ml if given else None,
                dose_unit="mL" if given and given.dose_ml is not None else "",
            )
        )


def _bind_stay_doses(imm_recs: list, encounters: list) -> None:
    """Issue #2168: a dose that falls inside an inpatient stay is given
    during that stay (the hepatitis B birth dose in the nursery), so it
    binds to the stay and keeps its date."""
    _stays: list[tuple[date, date, str]] = []
    for enc in encounters:
        _et = _get(enc, "encounter_type", "")
        if str(getattr(_et, "value", _et)).lower() not in ("inpatient", "imp"):
            continue
        _adm = _get(enc, "admission_datetime", None)
        _dis = _get(enc, "discharge_datetime", None)
        _eid = _get(enc, "encounter_id", "") or ""
        if isinstance(_adm, datetime) and isinstance(_dis, datetime) and _eid:
            _stays.append((_adm.date(), _dis.date(), _eid))
    for imm in imm_recs:
        occ = _get(imm, "occurrence_date", None)
        if not isinstance(occ, date) or _get(imm, "encounter_id", ""):
            continue
        for _lo, _hi, _eid in _stays:
            if _lo <= occ <= _hi:
                _set(imm, "encounter_id", _eid)
                break


def _align_to_encounters(
    imm_recs: list,
    encounters: list,
    season_months: dict[str, frozenset[int]] | None = None,
    earliest_by_cvx: dict[str, date] | None = None,
    min_interval_by_cvx: dict[str, dict[int, DoseInterval]] | None = None,
    lot_cvx: dict[str, str] | None = None,
    dob: date | None = None,
    dose_windows: dict[str, dict[int, tuple[int, int]]] | None = None,
    excluded_encounter_ids: frozenset[str] | set[str] = frozenset(),
) -> list:
    """Snap each immunization's occurrence_date to a nearby pediatric_visit
    encounter and stamp the encounter_id.

    Issue #1184 F4 / #1186 F6 CIF-layer fix (#1197 verify 2nd pass): the
    immunization scheduler picks occurrence_date on an age-anchored
    calendar independent of the encounter list, so the FHIR emit-time
    bridge found only ~4/1969 same-day matches. Aligning here at CIF-
    generation time bridges the gap in one seam.

    For each Immunization:
      * When the dose date falls inside an inpatient stay, bind it to that
        stay and keep the date (Issue #2168).
      * Otherwise search encounters within ±60 days whose encounter_type is
        outpatient. Prefer the nearest by absolute-day distance.
      * When a match exists, snap `occurrence_date` to that encounter's
        admission_datetime.date() and record `encounter_id`.
      * When no encounter is within window, leave both fields unchanged
        (silence beats fabrication).
      * A dose is not snapped onto a day before its vaccine's licensure
        floor (``earliest_by_cvx``; Issue #2979: no flu dose before 6 months).
      * A dose is not snapped onto a day that holds another dose of the same
        vaccine, out of series order, or closer to a neighbouring dose than
        the series' minimum interval (``min_interval_by_cvx``,
        ``dose_intervals_by_cvx``; Issues #3001 / #3006). With no allowed visit
        the dose keeps its own date.
      * A series dose is not snapped outside its schedule age window
        (``dose_windows`` = ``dose_windows_by_cvx``, measured from ``dob``;
        Issue #3567), and doses the engine gave one date move together to
        one visit (all of them, or none).
      * A dose is not snapped onto an encounter of ``excluded_encounter_ids``
        (an acute-illness or febrile visit, ``acute_visit_encounter_ids``;
        Issue #3655): the dose takes another visit or its own vaccination visit.
      * A snapped dose's lot is regenerated for its new date (Issue #3282;
        ``lot_cvx`` = ``lot_cvx_by_cvx``, the CVX the lot is keyed by).

    Never introduces a new encounter — the alignment only rebinds
    existing ones. Deterministic (no rng).
    """
    if not imm_recs or not encounters:
        return imm_recs
    _bind_stay_doses(imm_recs, encounters)
    # Collect eligible encounter dates once.
    _enc_days: list[tuple[date, str]] = []
    for enc in encounters:
        _adm = _get(enc, "admission_datetime", None)
        if not isinstance(_adm, datetime):
            continue
        _enc_type = str(_get(enc, "encounter_type", "") or "")
        # Immunizations are outpatient / ambulatory events. Filter to
        # OUTPATIENT encounter_type; inpatient / ED are not immunization
        # sites. `encounter_type` may be an enum with a `.value` attr.
        _et_val = getattr(_enc_type, "value", _enc_type)
        if str(_et_val).lower() not in ("outpatient", "amb", "ambulatory"):
            continue
        _eid = _get(enc, "encounter_id", "") or ""
        if not _eid or _eid in excluded_encounter_ids:
            continue
        _enc_days.append((_adm.date(), _eid))
    if not _enc_days:
        return imm_recs
    # Issue #3567: doses the engine scheduled for one date (the infant series
    # co-due at one well-child visit) move together to one visit, so a
    # shared dose date is never split over several visits.
    _by_date: dict[date, list] = {}
    for imm in imm_recs:
        occ = _get(imm, "occurrence_date", None)
        if isinstance(occ, date) and not _get(imm, "encounter_id", "") and _get(imm, "dose_number", None) is not None:
            _by_date.setdefault(occ, []).append(imm)
    _done: set[int] = set()
    for imm in imm_recs:
        occ = _get(imm, "occurrence_date", None)
        if not isinstance(occ, date) or _get(imm, "encounter_id", "") or id(imm) in _done:
            continue
        group = _by_date.get(occ, [imm]) if _get(imm, "dose_number", None) is not None else [imm]
        if len(group) < 2:
            group = [imm]
        _done.update(id(g) for g in group)
        # Nearest outpatient encounter within ±60 days. The window is
        # 60 rather than 14 to cover annual flu shots — the flu
        # scheduler picks a fixed month per year (Oct-Dec) that may not
        # coincide with the patient's own chronic follow-up cadence
        # (every 30-90 days). Pediatric infant series and one-off adult
        # vaccinations remain within the same window; the tightest
        # clinical constraint (immunization within one full quarter of
        # any real-world office visit) is preserved.
        best_delta: int | None = None
        best_day: date | None = None
        best_eid: str = ""
        for _day, _eid in _enc_days:
            _delta = abs((_day - occ).days)
            if _delta > 60:
                continue
            if best_delta is not None and _delta >= best_delta:
                continue
            if not all(
                _may_snap(
                    g, _day, occ, imm_recs, season_months, earliest_by_cvx, min_interval_by_cvx, dob, dose_windows
                )
                for g in group
            ):
                continue
            best_delta = _delta
            best_day = _day
            best_eid = _eid
        if best_day is not None and best_eid:
            for g in group:
                _cvx = str(_get(g, "vaccine_cvx", "") or "")
                redate(g, best_day, (lot_cvx or {}).get(_cvx, _cvx))
                _set(g, "encounter_id", best_eid)
    return imm_recs


def _may_snap(
    imm: object,
    day: date,
    occ: date,
    imm_recs: list,
    season_months: dict[str, frozenset[int]] | None,
    earliest_by_cvx: dict[str, date] | None,
    min_interval_by_cvx: dict[str, dict[int, DoseInterval]] | None,
    dob: date | None,
    dose_windows: dict[str, dict[int, tuple[int, int]]] | None,
) -> bool:
    """Whether ``imm`` (dated ``occ``) may be given on the visit day ``day``."""
    cvx = str(_get(imm, "vaccine_cvx", "") or "")
    earliest = (earliest_by_cvx or {}).get(cvx)
    if earliest is not None and day < earliest:
        return False
    months = (season_months or {}).get(cvx)
    if months is not None and (day.month not in months or flu_season_of(day) != flu_season_of(occ)):
        return False
    number = _get(imm, "dose_number", None)
    window = ((dose_windows or {}).get(cvx) or {}).get(int(number)) if number is not None else None
    if window is not None and dob is not None and not window[0] <= (day - dob).days <= window[1]:
        return False
    return series_allows(imm, day, imm_recs, (min_interval_by_cvx or {}).get(cvx))


def _clinic_day_within(day: date, country: str, first: date | None, last: date) -> date | None:
    """The clinic day a vaccination due on ``day`` is given on (Issue #3018):
    the next clinic day, else the previous one, kept within ``first`` ..
    ``last``; ``None`` when neither is."""
    later = clinic_visit_day(day, country, keep_year=False)
    if later <= last:
        return later
    earlier = day
    for _ in range(_MAX_CLOSED_RUN_DAYS):
        if is_clinic_day(earlier, country):
            break
        earlier -= timedelta(days=1)
    ok = is_clinic_day(earlier, country) and (first is None or earlier >= first)
    return earlier if ok else None


# A clinic calendar never closes this many days in a row.
_MAX_CLOSED_RUN_DAYS = 31


def _synthesize_vaccination_encounter(
    imm: object,
    patient_id: str,
    country: str,
    attending_physician_id: str = "",
) -> Encounter:
    """Create a minimal outpatient Encounter for an orphan immunization.

    Issue #1197 verify Pass 5 follow-up — companion encounter emit per the
    responsibility-decomposition design (see PR description). When
    ``_align_to_encounters`` cannot find an existing outpatient encounter
    within ±60 days of an in-sim-window immunization, this helper emits
    the encounter the FHIR world implicitly requires (a shot cannot be
    administered without an act — so the CIF must carry the visit).

    Shape: outpatient / completed / primary_care / vaccination purpose.
    Deterministic id derived from patient + occurrence_date + CVX so a
    re-run reuses the same id (idempotent verify).

    ``attending_physician_id`` (Issue #1215 follow-up): when supplied,
    stamped as the encounter's attending. Empty string leaves it unset
    (fallback for callers that lack roster access).
    """
    occ = _get(imm, "occurrence_date", None)
    if not isinstance(occ, date):
        occ = date(2000, 1, 1)
    # Issue #1700: encounter id keyed on (patient, date) only — NOT the CVX.
    # Multi-vaccine well-child visits (ACIP 2mo/4mo/6mo/12-15mo schedules
    # routinely give 3-5 vaccines simultaneously) emit ONE Encounter with
    # multiple Immunization resources, not one Encounter per CVX. All
    # Immunizations occurring on the same calendar day for the same
    # patient collapse to this single synthesized encounter_id via the
    # caller's ``hosted`` dedup set.
    _key = f"{patient_id}|{occ.isoformat()}|synth-vax".encode()
    _suffix = hashlib.sha256(_key).hexdigest()[:12]
    enc_id = f"ENC-VAX-{patient_id}-{_suffix}"
    adm = datetime(occ.year, occ.month, occ.day, 10, 0)
    chief_en = t("module_text.vaccination_visit", "en")
    chief_ja = t("module_text.vaccination_visit", "ja")
    # Issue #1215: stamp Z23 "Encounter for immunization" as the companion
    # encounter's own admission diagnosis so FHIR emit's reasonCode reflects
    # the visit purpose (vaccination) instead of inheriting the record's
    # primary IMP admission dx (e.g. T30.0 burn for a hospitalized patient
    # who happened to also receive an in-window flu shot at a follow-up
    # visit). Z23 is a visit-reason Z-code (recognized by
    # ``is_visit_reason_zcode``), so no dangling Condition reference is
    # created — the reasonCode text/coding alone carries the semantic.
    return Encounter(
        encounter_id=enc_id,
        patient_id=patient_id,
        encounter_type=EncounterType.OUTPATIENT,
        status=EncounterStatus.COMPLETED,
        department_id="primary_care",
        attending_physician_id=attending_physician_id,
        admission_datetime=adm,
        discharge_datetime=adm + timedelta(minutes=vaccination_visit_minutes()),
        chief_complaint=chief_en,
        chief_complaint_ja=chief_ja if is_jp(country) else "",
        priority="R",  # routine
        admission_diagnosis_code="Z23",
        admission_diagnosis_system=system_key_for("diagnosis", country),
    )


def _synthesize_vaccination_vitals(
    patient: object, encounter: Encounter, master_seed: int, nurse_id: str = ""
) -> VitalSignRecord | None:
    """The pre-vaccination vital signs of a companion vaccination visit (Issue #3464).

    The visit is the act of vaccinating, with the check that precedes it:
    temperature and pulse (and for an adult the blood pressure; the set is
    ``_visit_vitals`` in chronic_followup.yaml). Derived from the patient's
    physiological state by the same path as every outpatient visit, with a
    sub-RNG seeded by the encounter id, so no existing stream gains a draw.
    ``None`` when ``patient`` carries no physiology (a stub)."""
    profile = _get(patient, "physiological_profile", None)
    baseline = _get(patient, "baseline_vitals", None)
    if profile is None or baseline is None:
        return None
    from clinosim.locale.loader import visit_vitals
    from clinosim.modules.observation.pediatric_ranges import PEDIATRIC_UPPER_AGE_MONTHS, age_in_completed_months
    from clinosim.modules.physiology.engine import derive_observed_vitals, initialize_state

    when = encounter.admission_datetime
    dob = _get(patient, "date_of_birth", None)
    months = age_in_completed_months(dob if isinstance(dob, date) else None, when)
    child = months is not None and months < PEDIATRIC_UPPER_AGE_MONTHS
    fields = visit_vitals("vaccination_child" if child else "vaccination_adult")
    if not fields:
        return None
    pid = str(_get(patient, "patient_id", "") or encounter.patient_id)
    state = initialize_state(profile, _get(patient, "chronic_conditions", []) or [], pid)
    state.timestamp = when
    rng = determinism.default_rng(
        derive_sub_seed(master_seed, ENRICHER_SEED_OFFSETS["immunization"], f"{encounter.encounter_id}|vitals")
    )
    raw = derive_observed_vitals(state, baseline, when, rng, age_months=months)
    return VitalSignRecord(
        timestamp=when,
        temperature_celsius=round(raw["temperature"], 1) if "temp" in fields else None,
        heart_rate=int(round(raw["heart_rate"])) if "hr" in fields else None,
        systolic_bp=int(round(raw["systolic_bp"])) if "bp" in fields else None,
        diastolic_bp=int(round(raw["diastolic_bp"])) if "bp" in fields else None,
        respiratory_rate=int(round(raw["respiratory_rate"])) if "rr" in fields else None,
        spo2=round(raw["spo2"], 1) if "spo2" in fields else None,
        consciousness_level="",
        measured_by=nurse_id,
        data_source="manual",
    )


def _pick_primary_care_physician(pid: str, physician_ids: list[str]) -> str:
    """Deterministically pick a physician id for a given patient.

    Issue #1215 follow-up: the companion vaccination encounter must carry an
    attending so downstream CareTeam / practitioner emit does not fall back
    to ``Practitioner/UNKNOWN``. Hash the patient id and index into the
    (sorted) roster so regeneration is byte-identical (AD-16). Empty
    roster returns empty string; caller keeps the encounter unattended
    (the pre-fix behaviour) rather than fabricating a non-existent id.
    """
    if not physician_ids:
        return ""
    idx = int(hashlib.sha256(pid.encode()).hexdigest(), 16) % len(physician_ids)
    return physician_ids[idx]


def _sim_window_start(ctx) -> date | None:
    """Return the sim window's start date (inclusive) or None if unresolvable.

    Reads ``ctx.config.time_range`` (the same bound
    ``population.mortality.sim_window`` parses). Falls back to
    None on any parse failure so callers can decide policy (pre-sim
    historical doses stay unlinked when the window is unknown).
    """
    cfg = getattr(ctx, "config", None)
    if cfg is None:
        return None
    raw = getattr(cfg, "time_range", None)
    if raw is None:
        return None
    try:
        seq = tuple(raw)
    except TypeError:
        return None
    if len(seq) < 1:
        return None
    try:
        return date.fromisoformat(str(seq[0])[:10])
    except ValueError:
        return None


def enrich_immunizations(ctx) -> None:
    country = _get(_get(ctx, "config"), "country", "US") if _get(ctx, "config") else "US"
    schedule = load_schedule(country)
    # RM-3: pass a sorted nurse roster so administered_by can be
    # populated per-Immunization deterministically (real JP practice: nurses
    # administer routine vaccinations).
    roster = getattr(ctx, "roster", None)
    nurse_ids = []
    # Issue #1215 follow-up: also pull primary_care physicians so the
    # companion vaccination encounter can carry a real attending id
    # (otherwise CareTeam.participant[0].member -> Practitioner/UNKNOWN).
    # Fallback to any physician when the primary_care department is unstaffed.
    primary_care_physician_ids: list[str] = []
    if roster and hasattr(roster, "members"):
        # Issue #2700: routine vaccinations are given by the outpatient
        # (primary-care) nurses; a dose given during a stay by that ward's
        # nurses (see _ward_nurse_for below).
        from clinosim.modules.staff.engine import scoped_nurses

        nurse_ids = sorted(m.staff_id for m in scoped_nurses(roster, department="primary_care"))
        primary_care_physician_ids = sorted(
            m.staff_id
            for m in roster.members
            if getattr(m, "role", "") == "physician" and getattr(m, "department", "") == "primary_care"
        )
        if not primary_care_physician_ids:
            primary_care_physician_ids = sorted(
                m.staff_id for m in roster.members if getattr(m, "role", "") == "physician"
            )
    # Issue #1197 cross-record alignment (verify Pass 4 root fix): CIF
    # splits one patient's history into one record per encounter, so a
    # single record only sees ONE encounter — the aligner previously
    # couldn't reach the patient's other in-sim encounters. Build a
    # per-patient encounter union up-front so alignment finds any nearby
    # encounter across the patient's full record set.
    _all_encs_by_patient: dict[str, list] = {}
    # Issue #2868: every record of a patient carries the same vaccine list,
    # generated from the patient's latest record (its snapshot knows every
    # pregnancy for the maternal Tdap). Lists that differed by record gave
    # the same dose two FHIR ids.
    _latest_rec: dict[str, Any] = {}
    _latest_at: dict[str, datetime] = {}
    _records_by_patient: dict[str, list] = {}
    for rec in ctx.records:
        patient = _get(rec, "patient")
        pid = _get(patient, "patient_id", "") if patient else ""
        if not pid:
            continue
        _records_by_patient.setdefault(pid, []).append(rec)
        _latest_rec.setdefault(pid, rec)
        for enc in _get(rec, "encounters", []) or []:
            _all_encs_by_patient.setdefault(pid, []).append(enc)
            adm = _get(enc, "admission_datetime", None)
            if isinstance(adm, datetime) and (pid not in _latest_at or adm > _latest_at[pid]):
                _latest_at[pid] = adm
                _latest_rec[pid] = rec
    # Issue #1197 companion-encounter synthesis (verify Pass 5 gap): for
    # in-sim-window immunizations that could not be aligned to an
    # existing encounter (~25-39% of in-window doses, per Pass 5 verify),
    # emit a minimal `vaccination visit` outpatient encounter. Pre-sim
    # historical doses (patient interview / registry-recorded) stay
    # unlinked — a real visit was not simulated, so honesty > fabrication.
    country_upper = str(country or "US").upper()
    sim_start = _sim_window_start(ctx)
    visits_by_patient = vaccination_visits_by_patient(ctx.records)
    season_months = flu_season_months(schedule)
    _lot_cvx = lot_cvx_by_cvx(schedule)
    _acute_visits = frozenset(acute_visit_encounter_ids(ctx.records))
    # Issue #1245: a patient with N record files (per-encounter CIF sharding)
    # produced N copies of every synth VAX encounter — `generate_immunizations`
    # is deterministic per patient (same imm list on every call), so each
    # record's iteration synthesized and appended the identical companion
    # encounter. Track VAX encounter_ids we've already hosted per patient and
    # skip re-append on later iterations; the imm's encounter_id is still
    # linked so downstream (Immunization.encounter reference) resolves.
    _vax_hosted_by_patient: dict[str, set[str]] = {}
    for rec in ctx.records:
        patient = _get(rec, "patient")
        pid = _get(patient, "patient_id", "") if patient else ""
        source = _latest_rec.get(pid, rec)
        patient = _get(source, "patient") or patient
        rng = determinism.default_rng(
            derive_sub_seed(ctx.master_seed, ENRICHER_SEED_OFFSETS["immunization"], pid or "x")
        )
        as_of = _as_of(ctx, source)
        recs = generate_immunizations_for_country(country_upper, patient, schedule, as_of, rng, nurse_ids=nurse_ids)
        # Issue #3685: the tetanus toxoid the ED gave is part of the history;
        # a scheduled tetanus-containing dose soon after it is not given. Done
        # after the draws above, with no draw of its own.
        _ed_doses = [d for d in ed_vaccine_doses(_records_by_patient.get(pid, [rec])) if d.occurrence_date <= as_of]
        recs = drop_wound_covered_doses(recs, _ed_doses)
        # Issue #1283: append US maternal Tdap (CVX 115) for each
        # pregnancy period whose 27-36-week window overlaps the sim.
        # Uses the same per-patient sub-RNG the schedule pass just
        # returned from, so draws are deterministic per (patient, seed)
        # and don't cascade into unrelated modules. Non-US, non-female,
        # and no-pregnancy patients fall through without draws.
        _default_nurse = ""
        if nurse_ids and pid:
            _default_nurse = nurse_ids[sum(ord(c) for c in pid) % len(nurse_ids)]
        recs.extend(
            generate_pregnancy_tdap(
                patient,
                as_of,
                rng,
                country_upper,
                default_nurse=_default_nurse,
            )
        )
        recs.extend(_ed_doses)
        recs.sort(key=lambda r: r.occurrence_date)
        # Issue #1197 align — cross-record encounter pool.
        pool = _all_encs_by_patient.get(pid) or (_get(rec, "encounters", []) or [])
        # Issue #2868: doses given at the patient's vaccination visits are
        # bound there before the nearest-encounter alignment.
        _bind_stay_doses(recs, pool)
        recs = bind_to_vaccination_visits_for_country(
            country_upper,
            recs,
            visits_by_patient.get(pid, []),
            patient,
            schedule,
            as_of=as_of,
            sim_start=sim_start,
            flu_visit_candidate=is_flu_visit_candidate(patient),
            nurse=_default_nurse,
        )
        _min_intervals = dose_intervals_by_cvx(schedule)
        recs = _align_to_encounters(
            recs,
            pool,
            season_months,
            licensed_from_by_cvx(schedule, _get(patient, "date_of_birth", None)),
            _min_intervals,
            _lot_cvx,
            _get(patient, "date_of_birth", None),
            dose_windows_by_cvx(schedule),
            _acute_visits,
        )
        if roster is not None and hasattr(roster, "members"):
            _give_stay_doses_by_ward_nurse(recs, pool, roster, pid)
        # Companion synthesis for the residual in-window orphans.
        rec_encounters = _get(rec, "encounters", []) or []
        hosted = _vax_hosted_by_patient.setdefault(pid, set())
        for imm in recs:
            if _get(imm, "encounter_id", "") or "":
                continue  # already aligned
            occ = _get(imm, "occurrence_date", None)
            if not isinstance(occ, date):
                continue
            # Pre-sim historical dose: mark primary_source=False and
            # leave encounter_id empty (honest boundary).
            if sim_start is not None and occ < sim_start:
                _set(imm, "primary_source", False)
                continue
            # Issue #3018: the vaccination visit is held on a clinic day — a
            # dose due on a closed day (Sunday, a holiday, JP 年末年始) is given
            # on the next clinic day, or the previous one when the next is past
            # the record's as-of date, when that keeps its series' intervals.
            held = _clinic_day_within(occ, country_upper, sim_start, as_of)
            if (
                held is not None
                and held != occ
                and series_allows(imm, held, recs, _min_intervals.get(str(_get(imm, "vaccine_cvx", "") or "")))
            ):
                _cvx = str(_get(imm, "vaccine_cvx", "") or "")
                redate(imm, held, _lot_cvx.get(_cvx, _cvx))
            # In-window orphan: emit companion encounter. The FIRST record
            # we visit for this patient hosts the encounter; later records
            # only link the imm to it (no cross-record duplicate append).
            _attending = _pick_primary_care_physician(pid, primary_care_physician_ids)
            synth = _synthesize_vaccination_encounter(imm, pid, country_upper, attending_physician_id=_attending)
            if synth.encounter_id not in hosted:
                rec_encounters.append(synth)
                hosted.add(synth.encounter_id)
                # Issue #3464: the visit's pre-vaccination check.
                _vit = _synthesize_vaccination_vitals(patient, synth, ctx.master_seed, _default_nurse)
                if _vit is not None:
                    _set(rec, "vital_signs", [*(_get(rec, "vital_signs", []) or []), _vit])
            _set(imm, "encounter_id", synth.encounter_id)
        _set(rec, "encounters", rec_encounters)
        _set(rec, "immunizations", recs)
        _order_stay_doses(rec, recs, country_upper)
    # Issue #1228: dispatch document stubs for the companion vaccination
    # encounters just appended. `document_enricher` normally runs at
    # POST_ENCOUNTER (before this POST_RECORDS enricher), so any encounter
    # added here bypasses the walk. The dispatcher is idempotent (skips
    # encounters that already carry a document), so this re-invoke only
    # emits stubs for the new ENC-VAX-* encounters; existing IMP / ED /
    # outpatient documents stay byte-identical.
    if any(
        (str(_get(e, "encounter_id", "") or "")).startswith("ENC-VAX-")
        for rec in ctx.records
        for e in (_get(rec, "encounters", []) or [])
    ):
        from clinosim.modules.document.engine import document_enricher

        document_enricher(ctx)
