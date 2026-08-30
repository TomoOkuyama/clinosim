"""Staff-engine thresholds (Issue #637).

Lifts the previously-inline scalars from
:mod:`clinosim.modules.staff.engine` per policy §5 into a single
per-topic threshold file:

1. Phone-number generation formats (US area/prefix/line, JP 03-XXXX-XXXX)
2. Sex-distribution ratios (physician / nurse defaults; allied-health
   per-role female ratios)
3. Qualification-year ranges (per-role integer bands)
4. Staffing formulas (bed-scaled doctors-per-department, nurses-per-ward)
5. Fixed role counts (lab technicians, radiologists, pharmacists)
6. Extra-roles table (physical therapist / OT / ST / MSW / dietitian)
7. Fallback staff-ID digit range for missing locale name data

Byte-diff verification: the file iterates ``rng`` deterministically
(sex draws + qualification-year draws + name draws), so ANY of these
constants must extract without reordering, without type change, and
without renaming — or the entire golden cohort shifts. The named
constants below preserve the values verbatim; the extraction is
mechanical, not a retune.
"""

from __future__ import annotations

__all__ = [
    "ALLIED_HEALTH_QUALIFICATION_YEAR_END_EXCLUSIVE",
    "ALLIED_HEALTH_QUALIFICATION_YEAR_START",
    "DEFAULT_DOCTORS_PER_DEPT",
    "DEFAULT_INPATIENT_BEDS",
    "DOCTORS_PER_DEPT_FIXED",
    "DOCTORS_PER_ED_BED_DIVISOR",
    "DOCTORS_PER_INTERNAL_MED_BED_DIVISOR",
    "DOCTORS_PER_SURGERY_BED_DIVISOR",
    "ED_OPD_NURSES_PER_AREA",
    "EXTRA_STAFF_ROLES",
    "FALLBACK_BEDS_PER_WARD",
    "JP_PHONE_LINE_MAX_EXCLUSIVE",
    "JP_PHONE_LINE_MIN",
    "JP_PHONE_PREFIX_MAX_EXCLUSIVE",
    "JP_PHONE_PREFIX_MIN",
    "LAB_TECH_COUNT",
    "MIN_BEDS_PER_WARD",
    "MIN_ED_PHYSICIANS",
    "MIN_INTERNAL_MED_PHYSICIANS",
    "MIN_SURGERY_PHYSICIANS",
    "NURSE_FEMALE_RATIO",
    "NURSE_QUALIFICATION_YEAR_END_EXCLUSIVE",
    "NURSE_QUALIFICATION_YEAR_START",
    "NURSES_PER_BED_BUFFER",
    "NURSES_PER_BED_DIVISOR",
    "NURSES_PER_WARD_MIN",
    "PHARMACIST_COUNT",
    "PHARMACIST_QUALIFICATION_YEAR_END_EXCLUSIVE",
    "PHARMACIST_QUALIFICATION_YEAR_START",
    "PHYSICIAN_MALE_RATIO",
    "PHYSICIAN_QUALIFICATION_YEAR_END_EXCLUSIVE",
    "PHYSICIAN_QUALIFICATION_YEAR_START",
    "RADIOLOGIST_COUNT",
    "RADIOLOGIST_QUALIFICATION_YEAR_END_EXCLUSIVE",
    "RADIOLOGIST_QUALIFICATION_YEAR_START",
    "STAFF_ID_FALLBACK_MAX_EXCLUSIVE",
    "STAFF_ID_FALLBACK_MIN",
    "TECH_QUALIFICATION_YEAR_END_EXCLUSIVE",
    "TECH_QUALIFICATION_YEAR_START",
    "US_PHONE_AREA_MAX_EXCLUSIVE",
    "US_PHONE_AREA_MIN",
    "US_PHONE_LINE_MAX_EXCLUSIVE",
    "US_PHONE_LINE_MIN",
    "US_PHONE_PREFIX_MAX_EXCLUSIVE",
    "US_PHONE_PREFIX_MIN",
]


# ---------------------------------------------------------------------------
# Phone-number generation — synthetic identifiers only, not real numbers
# ---------------------------------------------------------------------------

JP_PHONE_PREFIX_MIN: int = 3000
"""Inclusive lower bound of the 4-digit JP-format phone-number prefix
(``03-<prefix>-<line>``). The 3000-5999 range keeps the synthetic
number visually distinct from any real Tokyo landline prefix while
staying in the correct digit range."""

JP_PHONE_PREFIX_MAX_EXCLUSIVE: int = 6000
"""Exclusive upper bound (``integers`` high=exclusive) — combined with
:data:`JP_PHONE_PREFIX_MIN` yields prefixes 3000-5999."""

JP_PHONE_LINE_MIN: int = 1000
"""Inclusive lower bound of the JP-format line portion (last 4 digits).
1000-9998 spans the full 4-digit line range."""

JP_PHONE_LINE_MAX_EXCLUSIVE: int = 9999
"""Exclusive upper bound — combined with :data:`JP_PHONE_LINE_MIN`
yields lines 1000-9998."""

US_PHONE_AREA_MIN: int = 200
"""Inclusive lower bound of the US-format area code. NANP area codes
never start with 0 or 1 (200-999 is the valid space)."""

US_PHONE_AREA_MAX_EXCLUSIVE: int = 999
"""Exclusive upper bound of the area code."""

US_PHONE_PREFIX_MIN: int = 200
"""Inclusive lower bound of the US-format central-office prefix
(same 200-998 range as area codes per NANP)."""

US_PHONE_PREFIX_MAX_EXCLUSIVE: int = 999
"""Exclusive upper bound of the central-office prefix."""

US_PHONE_LINE_MIN: int = 1000
"""Inclusive lower bound of the US-format line portion (last 4
digits)."""

US_PHONE_LINE_MAX_EXCLUSIVE: int = 9999
"""Exclusive upper bound of the US-format line portion."""


# ---------------------------------------------------------------------------
# Sex distribution — synthetic workforce composition
# ---------------------------------------------------------------------------

PHYSICIAN_MALE_RATIO: float = 0.65
"""Probability that a synthetically-generated physician is male.

Empirical tuning for the synthetic simulator: 65% male matches
historical JP + US physician workforce composition (both countries
sit at ~63-66% male across all specialties per OECD 2022). The
gap is closing but the extant roster is still male-skewed."""

NURSE_FEMALE_RATIO: float = 0.85
"""Probability that a synthetically-generated nurse is female.

Empirical tuning for the synthetic simulator: 85% female matches
the 2022 US BLS / JP MHLW nursing workforce (both countries sit at
~85-90% female)."""


# ---------------------------------------------------------------------------
# Qualification-year ranges — controls apparent staff seniority
# ---------------------------------------------------------------------------

PHYSICIAN_QUALIFICATION_YEAR_START: int = 1985
"""Inclusive lower bound of physician qualification-year draw.

Empirical tuning for the synthetic simulator: 1985-2019 spans a
35-year career window that yields roughly the right mix of senior
attendings (near-retirement) and mid-career physicians. Anyone
qualified before 1985 would be > 65 y and mostly retired."""

PHYSICIAN_QUALIFICATION_YEAR_END_EXCLUSIVE: int = 2020
"""Exclusive upper bound of physician qualification-year draw."""

NURSE_QUALIFICATION_YEAR_START: int = 1995
"""Inclusive lower bound of nurse qualification-year draw. 10-year
narrower band than physicians — nursing careers are typically
shorter (higher attrition) so the senior tail is compressed."""

NURSE_QUALIFICATION_YEAR_END_EXCLUSIVE: int = 2023
"""Exclusive upper bound of nurse qualification-year draw."""

TECH_QUALIFICATION_YEAR_START: int = 2000
"""Inclusive lower bound of lab-technician qualification-year draw."""

TECH_QUALIFICATION_YEAR_END_EXCLUSIVE: int = 2023
"""Exclusive upper bound of lab-technician qualification-year draw."""

RADIOLOGIST_QUALIFICATION_YEAR_START: int = 1990
"""Inclusive lower bound of radiologist qualification-year draw —
5-year later than the physician baseline reflecting the longer
training pipeline (radiology fellowship adds years post-residency)."""

RADIOLOGIST_QUALIFICATION_YEAR_END_EXCLUSIVE: int = 2015
"""Exclusive upper bound of radiologist qualification-year draw."""

PHARMACIST_QUALIFICATION_YEAR_START: int = 2000
"""Inclusive lower bound of pharmacist qualification-year draw."""

PHARMACIST_QUALIFICATION_YEAR_END_EXCLUSIVE: int = 2023
"""Exclusive upper bound of pharmacist qualification-year draw."""

ALLIED_HEALTH_QUALIFICATION_YEAR_START: int = 2005
"""Inclusive lower bound of allied-health (PT/OT/ST/MSW/RD)
qualification-year draw. Later than pharmacists because allied-health
formal certification programs in JP scaled up post-2005."""

ALLIED_HEALTH_QUALIFICATION_YEAR_END_EXCLUSIVE: int = 2023
"""Exclusive upper bound of allied-health qualification-year draw."""


# ---------------------------------------------------------------------------
# Staffing formulas — bed-scaled headcounts (per-department minimums)
# ---------------------------------------------------------------------------

DEFAULT_INPATIENT_BEDS: int = 50
"""Fallback bed count when ``hospital_config.resource_capacity.
inpatient_beds`` is missing. Matches the default ``50-bed`` community
hospital scale used across the clinosim test-fixture set."""

MIN_INTERNAL_MED_PHYSICIANS: int = 4
"""Minimum internal-medicine physician headcount — a hospital always
has an IM team of at least 4 even at very small bed counts."""

DOCTORS_PER_INTERNAL_MED_BED_DIVISOR: int = 8
"""Divisor for the bed-scaled IM physician count: ``beds_total // 8``
yields ~1 IM doctor per 8 beds above the ``MIN_INTERNAL_MED_PHYSICIANS``
floor."""

MIN_SURGERY_PHYSICIANS: int = 2
"""Minimum general-surgery physician headcount.

Empirical tuning for the synthetic simulator: JP small-to-mid
community hospitals staff ~1-2 general surgeons per 100 beds (per
MHLW 2022 医療施設調査 general-hospital surgical staffing). A 2-doctor
floor keeps 24/7 on-call coverage viable at the smallest bed counts
without over-provisioning at the community-hospital scale that most
clinosim fixtures target.

Previously 3 (paired with a 10-bed divisor): at the default 50-bed
config that yielded 5 GS attending physicians against ~7 surgical
inpatient events / year (2 cholecystitis + 5 hip fractures in the
p=1000 JP seed=42 baseline), leaving 2 of 5 physicians permanently
unreferenced (#975 residual). See also
:data:`DOCTORS_PER_SURGERY_BED_DIVISOR`."""

DOCTORS_PER_SURGERY_BED_DIVISOR: int = 50
"""Divisor for the bed-scaled general-surgery physician count.

Yields ~1 additional GS attending per 50 inpatient beds above the
:data:`MIN_SURGERY_PHYSICIANS` floor (50-bed→2, 100-bed→2, 200-bed→4).
Reflects the reality that surgical volume scales with inpatient
capacity far more slowly than internal-medicine volume — most
inpatient events are IM-attended, not surgical.

Previously 10 (~1 per 10 beds), which over-provisioned surgeons at
every catchment size: the 50-bed default yielded 5 attendings against
~7 surgical events / year, and #975 audit surfaced 2 of 5 GS attendings
as permanently zero-referenced. See :data:`MIN_SURGERY_PHYSICIANS`
for the on-call floor rationale."""

MIN_ED_PHYSICIANS: int = 3
"""Minimum emergency-medicine physician headcount."""

DOCTORS_PER_ED_BED_DIVISOR: int = 12
"""Divisor for the bed-scaled ED physician count — sparser than IM
because ED volume scales less linearly with inpatient bed count."""

DOCTORS_PER_DEPT_FIXED: dict[str, int] = {
    "cardiology": 2,
    "pulmonology": 2,
    "gastroenterology": 2,
    "nephrology": 1,
    "endocrinology": 1,
    "neurology": 2,
    "orthopedics": 2,
    "neurosurgery": 2,
    "trauma_surgery": 2,
    "primary_care": 2,
}
"""Fixed-count per-department physician headcounts that DO NOT scale
with bed count (specialty coverage is roughly a step function once
the specialty exists — nephrology needs at least 1 nephrologist, not
0.4)."""

DEFAULT_DOCTORS_PER_DEPT: int = 2
"""Fallback doctor count for a department not listed in
:data:`DOCTORS_PER_DEPT_FIXED` and not one of the bed-scaled special
cases (IM / surgery / ED)."""

MIN_BEDS_PER_WARD: int = 6
"""Minimum inpatient beds assumed per ward when distributing
nursing staff. Prevents a large-ward hospital with many small wards
from creating an under-staffed roster."""

FALLBACK_BEDS_PER_WARD: int = 10
"""Beds-per-ward fallback when the hospital has no inpatient wards
declared (edge case for outpatient-only fixtures)."""

NURSES_PER_WARD_MIN: int = 6
"""Minimum nurses per inpatient ward — every ward needs a minimum
skeleton crew for 24/7 shift coverage."""

NURSES_PER_BED_DIVISOR: int = 2
"""Bed → nurse ratio divisor: ``beds_per_ward // 2`` yields a ~1:2
nurse:bed staffing baseline (typical med-surg ward)."""

NURSES_PER_BED_BUFFER: int = 3
"""Nurse-count buffer added on top of the bed-scaled minimum to cover
weekends / vacations / on-call rotation."""

ED_OPD_NURSES_PER_AREA: int = 5
"""Fixed nurse count assigned to each of the ED and OPD "areas"
(shared across those two clinical areas, not per-ward). 5 is a
typical minimum crew for both an ED and an OPD across the day."""


# ---------------------------------------------------------------------------
# Fixed shared-service headcounts
# ---------------------------------------------------------------------------

LAB_TECH_COUNT: int = 10
"""Number of laboratory technicians generated for the shared
laboratory service (not per-department). 10 covers 24/7 shifts for a
50-bed hospital."""

RADIOLOGIST_COUNT: int = 4
"""Number of radiologists generated. 4 covers day + on-call rotation
for a hospital of the modeled scale."""

PHARMACIST_COUNT: int = 8
"""Number of hospital pharmacists generated. 8 covers day + evening
shifts plus a chief pharmacist role."""


# ---------------------------------------------------------------------------
# Allied-health / C5-25 (Chain 3) extra-roles table
# ---------------------------------------------------------------------------

EXTRA_STAFF_ROLES: list[tuple[str, str, str, int, float]] = [
    # (role, id_prefix, department, count, female_ratio)
    ("physical_therapist", "PT", "rehabilitation", 4, 0.55),
    ("occupational_therapist", "OT", "rehabilitation", 2, 0.65),
    ("speech_therapist", "ST", "rehabilitation", 2, 0.75),
    ("medical_social_worker", "MSW", "medical_social_work", 2, 0.70),
    ("dietitian", "RD", "nutrition", 3, 0.90),
]
"""Roster expansion for a JP community hospital of ~50 beds. Enables
β-JP-1 multi-disciplinary CareTeam expansion and nutrition-order
emit paths downstream.

Empirical tuning for the synthetic simulator: counts scaled to a
50-bed inpatient hospital; female ratios biased per JP allied-health
workforce norms (PT/OT/ST/RD ~65% female; MSW ~70%; dietitians
~90% female per JP Dietetic Association 2022)."""


# ---------------------------------------------------------------------------
# Fallback staff-ID synthesis when locale name data is missing
# ---------------------------------------------------------------------------

STAFF_ID_FALLBACK_MIN: int = 1000
"""Inclusive lower bound of the fallback staff-ID numeric range
(``Staff-<4 digits>``). Used only when locale name data returns no
surnames or given names — smoke-test paths."""

STAFF_ID_FALLBACK_MAX_EXCLUSIVE: int = 9999
"""Exclusive upper bound of the fallback staff-ID range."""
