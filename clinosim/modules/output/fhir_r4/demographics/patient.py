"""FHIR R4 patient-demographics resource builders (FA-1 Phase 11).

Patient, JP Core Coverage (+ payor Organization), occupation Observation, and
AllergyIntolerance — plus the identity-config cache and the marital/language/
coverage display constants used only by this cluster. Extracted verbatim from
``fhir_r4_adapter``; depends only on clinosim.codes/locale and the leaf
reference/localization + _fhir_common helper modules (no adapter import cycle).
"""

from __future__ import annotations

import uuid
from datetime import date
from functools import lru_cache
from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.locale.loader import load_identity_config
from clinosim.modules._shared import is_jp, resolve_lang
from clinosim.modules.output.fhir_r4.lib.common import (
    _coding_with_display,
    _social_category,
    build_address,
    build_telecom,
    to_fhir_date,
)
from clinosim.modules.output.fhir_r4.lib.ids import (
    derive_opaque_id,
    structural_key_system,
    wrap_as_identifier,
)
from clinosim.modules.output.fhir_r4.lib.localization import (
    _OCCUPATION_DISPLAY_EN,
    _OCCUPATION_DISPLAY_JA,
    _RELATIONSHIP_DISPLAY_JA,
    _localize_display,
    _localize_drug_name,
)
from clinosim.modules.output.fhir_r4.lib.reference_data import _ALLERGEN_RXNORM

# === Issue #854 Bucket C row 18 (PR-patient): opaque Patient.id ===
# Structural key = the CIF ``patient_id`` verbatim (`POP-{n:06d}`, a
# simulation-generation-artifact slug, not a clinical identifier).
# Post-#854 every FHIR Patient.id is ``pt-<12hex>`` (15 chars, fixed);
# `POP-{n}` is preserved on `Patient.identifier[]` under the
# POPULATION_SLUG_KEY_SYSTEM so consumers who key on the human-readable
# generation slug (iris4h-ai clinical cockpit, integration tests) can
# still recover it. Every downstream `f"Patient/{patient_id}"` site is
# routed through `patient_ref` — never string-format the CIF value
# directly.
PATIENT_ID_PREFIX = "pt-"
POPULATION_SLUG_KEY_SYSTEM = structural_key_system("population-slug")


def resolve_patient_id(cif_patient_id: str) -> str:
    """Return the opaque FHIR Patient.id for a CIF ``patient_id``.

    Shape: ``pt-{sha256(cif_patient_id)[:12]}`` = 15 chars, fixed.

    Empty ``cif_patient_id`` returns an empty string rather than raising —
    the empty upstream is a data-quality bug the caller should surface,
    but the FHIR emit layer preserves the pre-#854 behaviour of emitting
    an empty reference so downstream FHIR-validator gates can flag it as
    an integrity violation (rule
    ``feedback_empty_vs_wrong_assertion`` — 空欄は無知).
    """
    if not cif_patient_id:
        return ""
    return derive_opaque_id(PATIENT_ID_PREFIX, cif_patient_id)


def patient_ref(cif_patient_id: str) -> dict[str, str]:
    """Return a FHIR ``Reference`` dict pointing at the opaque Patient id.

    All emit sites that need ``{"reference": f"Patient/{...}"}`` must
    route through this helper — never string-format the CIF
    ``patient_id`` directly into the reference slot. Empty
    ``cif_patient_id`` yields ``{"reference": "Patient/"}`` — a broken
    reference matching pre-#854 behaviour so downstream FHIR-integrity
    audits keep catching it.
    """
    return {"reference": f"Patient/{resolve_patient_id(cif_patient_id)}"}


# === Issue #854 Bucket A row 4 (PR-obs-standalone): opaque occupation id ===
# Structural key = pre-#854 id body (patient id).
OCCUPATION_ID_PREFIX = "occupation-"
OCCUPATION_KEY_SYSTEM = structural_key_system("occupation-observation-key")


def _resolve_occupation_id(structural_key: str) -> str:
    return derive_opaque_id(OCCUPATION_ID_PREFIX, structural_key)


# === Issue #854 Bucket C (PR-coverage): opaque Coverage.id ===
# Structural key = pre-#854 id body `{patient_id}-{idx}` (`cov-` prefix
# stripped); post-#854 every `.id` is `cov-<12hex>` (16 chars, fixed).
# Coverage already carries a member-id identifier[] for the JP insurance
# number; a second entry under COVERAGE_KEY_SYSTEM round-trips the
# structural key so consumers keyed on the old id still work.
COVERAGE_ID_PREFIX = "cov-"
COVERAGE_KEY_SYSTEM = structural_key_system("coverage-key")


def _resolve_coverage_id(structural_key: str) -> str:
    return derive_opaque_id(COVERAGE_ID_PREFIX, structural_key)


# FHIR R4 standard: payer organization type
_ORG_TYPE_SYSTEM = get_system_uri("hl7-organization-type")
# FHIR R4 standard: beneficiary's relationship to the policy subscriber
_SUBSCRIBER_REL_SYSTEM = get_system_uri("hl7-subscriber-relationship")


def _default_coverage_period_year(patient_data: dict) -> int:
    """Pick a default calendar year for Coverage.period when the enrollment
    lacks explicit start/end (C2-11 fallback). Uses the patient's first
    encounter year if available; otherwise a fixed simulation year.

    Kept for backward compatibility with callers that only pass patient_data;
    the multi-FY emit path (Issue #923) uses `_derive_encounter_date_range`
    instead.
    """
    encs = patient_data.get("encounters", [])
    if encs:
        first_dt = encs[0].get("admission_datetime", "") or encs[0].get("period", {}).get("start", "")
        first_dt = str(first_dt)
        if len(first_dt) >= 4 and first_dt[:4].isdigit():
            return int(first_dt[:4])
    return 2025


def _fy_boundary(country: str) -> tuple[int, int]:
    """Return (month, day) marking the fiscal-year start for the locale.

    JP defaults to (4, 1) per identity.yaml `fiscal_year`. Non-JP locales
    without a fiscal_year block fall back to calendar-year (1, 1).
    """
    fy = _identity_cfg(country).get("fiscal_year", {}) or {}
    return (int(fy.get("start_month", 1)), int(fy.get("start_day", 1)))


def _age_gate_config(country: str) -> dict[str, int]:
    """Return the age-gate thresholds from identity.yaml.

    JP defaults (Issue #923):
      - late_elderly_min_age: 75 (mandatory 後期高齢者医療制度 enrolment)
      - primary_subscriber_min_age: 18 (被保険者 slot legal minimum)
    """
    gates = _identity_cfg(country).get("age_gates", {}) or {}
    return {
        "late_elderly_min_age": int(gates.get("late_elderly_min_age", 75)),
        "primary_subscriber_min_age": int(gates.get("primary_subscriber_min_age", 18)),
    }


def _late_elderly_payer_number(country: str) -> str:
    """Return the representative 保険者番号 for the late-elderly scheme, or empty.

    Used when Issue #923's age-gate reassigns an aging-into-≥75 patient's
    Coverage row to 後期高齢者医療制度. Falls back to the first late_elderly payer
    entry declared in identity.yaml; empty string when no such payer is
    configured (e.g., non-JP locale).
    """
    payers = _identity_cfg(country).get("payers", {}) or {}
    entries = payers.get("late_elderly") or []
    for e in entries:
        if e.get("number"):
            return str(e["number"])
    return ""


def _parse_iso_date(value: Any) -> date | None:
    """Parse an ISO-8601 date/datetime string into a `date`, ignoring the time.

    Encounter `admission_datetime` values come through as either
    'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS[+09:00]'; we only need the day
    part for FY bucketing.
    """
    if not value:
        return None
    s = str(value)
    if len(s) < 10:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _derive_encounter_date_range(encounters: list[dict] | None, patient_data: dict) -> tuple[date | None, date | None]:
    """Return (earliest, latest) encounter date across the patient's encounters.

    Falls back to `patient_data.get("encounters")` when the caller does not
    supply an explicit list (identity module or legacy tests). Returns
    (None, None) when no dates can be parsed.
    """
    src = encounters if encounters is not None else patient_data.get("encounters", []) or []
    starts: list[date] = []
    ends: list[date] = []
    for enc in src:
        if not isinstance(enc, dict):
            continue
        s = _parse_iso_date(enc.get("admission_datetime") or enc.get("period", {}).get("start"))
        if s:
            starts.append(s)
        e = _parse_iso_date(
            enc.get("discharge_datetime") or enc.get("period", {}).get("end") or enc.get("admission_datetime")
        )
        if e:
            ends.append(e)
    if not starts and not ends:
        return (None, None)
    earliest = min(starts) if starts else min(ends)
    latest = max(ends) if ends else max(starts)
    return (earliest, latest)


def _fy_bounds_containing(day: date, fy_month: int, fy_day: int) -> tuple[date, date]:
    """Return the (start, end_inclusive) of the fiscal year containing `day`.

    For JP (fy_month=4, fy_day=1): a date in Jan-Mar belongs to the prior
    FY (started April 1 of previous calendar year); April 1 onward belongs
    to the FY starting that April.
    """
    if (day.month, day.day) >= (fy_month, fy_day):
        start_year = day.year
    else:
        start_year = day.year - 1
    start = date(start_year, fy_month, fy_day)
    # end = one day before next FY start
    next_start = date(start_year + 1, fy_month, fy_day)
    end = date.fromordinal(next_start.toordinal() - 1)
    return (start, end)


def _iter_fy_periods(earliest: date, latest: date, fy_month: int, fy_day: int) -> list[tuple[date, date]]:
    """Enumerate fiscal-year (start, end) pairs covering [earliest, latest]."""
    periods: list[tuple[date, date]] = []
    cur_start, cur_end = _fy_bounds_containing(earliest, fy_month, fy_day)
    while cur_start <= latest:
        periods.append((cur_start, cur_end))
        next_start = date(cur_start.year + 1, fy_month, fy_day)
        cur_start = next_start
        cur_end = date.fromordinal(date(next_start.year + 1, fy_month, fy_day).toordinal() - 1)
    return periods


def _age_on(dob: date, when: date) -> int:
    """Age in whole years on `when` (birthday-adjusted, standard convention)."""
    years = when.year - dob.year
    if (when.month, when.day) < (dob.month, dob.day):
        years -= 1
    return years


@lru_cache(maxsize=2)
def _identity_cfg(country: str) -> dict:
    """Full resident-identity locale config (AD-54).

    ``@lru_cache(maxsize=2)`` bounds the cache to the two supported
    countries (US / JP). Issue #557: replaces the pre-Aug-2026 pattern
    of a module-level `_IDENTITY_CFG_CACHE: dict` mutated across module
    boundaries — the previous 3 external re-imports (`_fhir_post_process`,
    `_fhir_inline_bb`) were unused ``noqa: F401`` re-exports and are
    removed.
    """
    return load_identity_config(country)


def _payer_name_map(country: str) -> dict[str, str]:
    """Map 保険者番号 → insurer name from locale (display resolved at output, AD-30)."""
    payers = _identity_cfg(country).get("payers", {})
    out: dict[str, str] = {}
    for entries in payers.values():
        for e in entries or []:
            if e.get("number"):
                out[str(e["number"])] = str(e.get("name", e["number"]))
    return out


def _derive_coverage_status(period_end: str | None, snapshot_date: str | None) -> str:
    """Return the FHIR R4 ``Coverage.status`` code for a policy period.

    Rule (Issue #944): ``Coverage.status = "active"`` means "currently in
    effect". A per-FY row whose ``period.end`` is strictly before the
    simulation snapshot date has, by definition, expired — emit
    ``"cancelled"`` (the FHIR R4 status value used for a policy that has
    ended; ``"entered-in-error"`` is reserved for records the emitter
    knows were wrong).

    Boundary: ``period.end == snapshot_date`` still counts as active
    (inclusive comparison — the FY endpoint IS the last day of coverage).

    Backward compat: when ``snapshot_date`` is unknown (identity-only
    tests, callers that don't plumb the CIF metadata through) we default
    to ``"active"``, preserving the pre-#944 emit for those paths.
    """
    if not period_end or not snapshot_date:
        return "active"
    # String compare is safe for ISO-8601 YYYY-MM-DD values (lexicographic
    # order == chronological order); avoids re-parsing on the hot path.
    return "active" if period_end >= snapshot_date else "cancelled"


def _build_coverage_resources(
    patient_data: dict,
    country: str,
    encounters: list[dict] | None = None,
    snapshot_date: str | None = None,
) -> list[dict]:
    """Build JP Core Coverage + payor Organization from the patient's insurance enrollment.

    Reads CIF data only (no dependency on the identity module — module independence).
    `national_id` is never read here: the privacy chokepoint (AD-54) means individual
    numbers are never emitted to FHIR.

    Issue #923: emits one Coverage row per fiscal year covered by the patient's
    encounter window (JP FY = 4/1 → 3/31 per identity.yaml `fiscal_year`), so no
    encounter falls outside its Coverage.period. Each per-FY row is *re-aged*: the
    category and payer are recomputed from the patient's age at that FY's April 1
    boundary, so a patient turning 75 mid-simulation gets a 後期高齢者医療制度 row
    starting the next FY. Falls back to the pre-#923 single-row emit for callers
    that don't pass encounters (identity-only tests, non-JP locales, etc.).
    """
    cfg = _identity_cfg(country).get("fhir_coverage", {})
    if not cfg:
        return []
    name_map = _payer_name_map(country)
    type_labels = _identity_cfg(country).get("coverage_type_labels", {})
    identity = patient_data.get("identity") or {}
    enrollments = identity.get("enrollments") or []
    pid = patient_data.get("patient_id", "")
    resources: list[dict] = []

    # Issue #923 §Fix 1: emit one Coverage per FY covered by encounters.
    # Falls back to a single row (pre-#923 behaviour) when we can't derive
    # a range — legacy callers / tests without encounters.
    fy_month, fy_day = _fy_boundary(country)
    earliest, latest = _derive_encounter_date_range(encounters, patient_data)
    if earliest and latest:
        fy_periods = _iter_fy_periods(earliest, latest, fy_month, fy_day)
    else:
        fallback_year = _default_coverage_period_year(patient_data)
        fy_periods = [
            (
                date(fallback_year, fy_month, fy_day),
                date.fromordinal(date(fallback_year + 1, fy_month, fy_day).toordinal() - 1),
            )
        ]

    gates = _age_gate_config(country)
    dob = _parse_iso_date(patient_data.get("date_of_birth"))
    late_elderly_payer = _late_elderly_payer_number(country)

    # Deduplicate payor Organization resources across FY rows — the same
    # 保険者番号 typically holds the entire encounter window; only aging-into-≥75
    # rows swap to the 後期高齢者 payer.
    emitted_payer_ids: set[str] = set()

    for enr_idx, enr in enumerate(enrollments):
        base_insurer = enr.get("insurer_number") or ""
        number = enr.get("member_id") or ""
        symbol = enr.get("group_symbol")
        branch = enr.get("branch_number")
        base_category = enr.get("category") or ""
        if not base_insurer or not number:
            continue

        for fy_start, fy_end in fy_periods:
            # Issue #923 §Fix 2: re-age the category at each FY boundary.
            # Two age checks:
            #  - late_elderly gate uses `fy_end`: if the patient is ≥75 at
            #    ANY point in the FY (i.e., turns 75 during the period),
            #    the row is 後期高齢者医療制度 for the whole FY. This models
            #    the JP legal reality that 75+ residents are auto-enrolled
            #    on their 75th birthday — since we don't split FYs at the
            #    birthday, we conservatively promote the whole FY row. It
            #    also drives the audit `older_wrong` count to 0 (the
            #    reproduction script measures age at Jan 1 mid-FY).
            #  - primary-subscriber gate uses `fy_start`: minors are demoted
            #    to 被扶養者 whenever they are still under 18 at the FY start,
            #    because the 被保険者 slot is a policy-time role.
            age_at_period_end = _age_on(dob, fy_end) if dob else -1
            age_at_period_start = _age_on(dob, fy_start) if dob else -1
            if dob:
                if age_at_period_end >= gates["late_elderly_min_age"]:
                    category = "late_elderly"
                elif age_at_period_start < gates["primary_subscriber_min_age"] and base_category == "employee":
                    category = "dependent"
                else:
                    category = base_category
            else:
                category = base_category

            # Insurer + card fields track the (possibly reassigned) category.
            if category == "late_elderly" and late_elderly_payer:
                insurer = late_elderly_payer
                # Late-elderly enrolment is per-individual: no 記号 / 枝番.
                use_symbol: str | None = None
                use_branch: str | None = None
            elif category != base_category and category == "dependent":
                # Minor demoted from 被保険者 → 被扶養者 on the same policy;
                # keep the household insurer + 記号 but 枝番 must exist.
                insurer = base_insurer
                use_symbol = symbol
                use_branch = branch or "01"
            else:
                insurer = base_insurer
                use_symbol = symbol
                use_branch = branch

            payer_org_id = f"payer-{insurer}"
            if payer_org_id not in emitted_payer_ids:
                emitted_payer_ids.add(payer_org_id)
                resources.append(
                    {
                        "resourceType": "Organization",
                        "id": payer_org_id,
                        "identifier": [
                            {
                                "system": cfg.get("insurer_number_system", ""),
                                "value": insurer,
                            }
                        ],
                        "type": [
                            {
                                "coding": [
                                    {
                                        "system": _ORG_TYPE_SYSTEM,
                                        "code": "pay",
                                        "display": "Payer",
                                    }
                                ]
                            }
                        ],
                        "name": name_map.get(insurer, insurer),
                    }
                )

            # JP Core extensions: 記号 / 番号 / 枝番
            extensions: list[dict] = []
            if use_symbol:
                extensions.append({"url": cfg.get("ext_symbol", ""), "valueString": use_symbol})
            extensions.append({"url": cfg.get("ext_number", ""), "valueString": number})
            if use_branch:
                extensions.append({"url": cfg.get("ext_subnumber", ""), "valueString": use_branch})

            # Composite member identifier: 保険者番号:記号:番号:枝番
            composite = ":".join([insurer, use_symbol or "", number, use_branch or ""])
            subscriber = f"{use_symbol}:{number}" if use_symbol else number

            # Issue #923: structural key always carries the FY year so
            # per-encounter records emitted for the same patient across
            # different FYs each land as a distinct Coverage row (the
            # write()-level dedup keys on `.id`, so a pre-#923 pid-only
            # key would silently collapse a multi-FY patient down to a
            # single row — see #923 scan showing 39.94% uncovered with
            # single-FY keys). Different-FY records for the same patient
            # now hash to distinct ids and coexist as intended; same-FY
            # duplicate records collapse as before.
            _cov_structural_key = f"{pid}-{enr_idx}-fy{fy_start.year}"
            # Issue #944: derive Coverage.status from period.end vs the
            # simulation snapshot date. Explicit enrollment valid_to (rare,
            # Phase 2) still wins over the FY-derived end below — resolve
            # the effective period.end here so both branches converge.
            _effective_period_end: str
            if enr.get("valid_to"):
                _effective_period_end = str(enr["valid_to"])
            else:
                _effective_period_end = fy_end.isoformat()
            coverage: dict[str, Any] = {
                "resourceType": "Coverage",
                "id": _resolve_coverage_id(_cov_structural_key),
                "extension": extensions,
                "identifier": [
                    {"system": cfg.get("member_id_system", ""), "value": composite},
                    wrap_as_identifier(_cov_structural_key, COVERAGE_KEY_SYSTEM),
                ],
                "status": _derive_coverage_status(_effective_period_end, snapshot_date),
                "subscriberId": subscriber,
                # CY7-13 (Chain-7): Coverage.subscriber — the person carrying the
                # policy. For "self" relationship the subscriber IS the beneficiary
                # (JP 主たる被保険者 = 本人); for "other" (dependent) it's the
                # policy-holder relative. Without a distinct 主たる被保険者
                # Person record, we point to the patient themselves (matches
                # subscriberId derivation above and passes FHIR R4 conformance —
                # subscriber is 0..1 Reference to Patient|RelatedPerson).
                "subscriber": patient_ref(pid),
                "beneficiary": patient_ref(pid),
                "payor": [{"reference": f"Organization/{payer_org_id}"}],
            }
            if cfg.get("profile"):
                coverage["meta"] = {"profile": [cfg["profile"]]}
            if use_branch:
                coverage["dependent"] = use_branch
            # C2-06: resolve display via codes/data/
            # hl7-subscriber-relationship.yaml — was raw code emission.
            # Beneficiary's relationship to the subscriber: 被扶養者 → not self.
            rel_code = "other" if category == "dependent" else "self"
            coverage["relationship"] = {
                "coding": [
                    _coding_with_display(
                        "hl7-subscriber-relationship",
                        rel_code,
                        resolve_lang(country),
                    )
                ]
            }
            # Coverage.type: human label (text-only CodeableConcept — no fabricated codes).
            label = type_labels.get(category)
            if label:
                coverage["type"] = {"text": label}
            # Coverage.period — Issue #923 §Fix 1: one FY per row.
            # Explicit enrollment valid_from / valid_to still wins (Phase 2
            # will emit period-bounded enrollments; when they do, respect
            # those over the derived FY boundary).
            if enr.get("valid_from") or enr.get("valid_to"):
                period: dict[str, str] = {}
                if enr.get("valid_from"):
                    period["start"] = str(enr["valid_from"])
                if enr.get("valid_to"):
                    period["end"] = str(enr["valid_to"])
            else:
                period = {"start": fy_start.isoformat(), "end": fy_end.isoformat()}
            coverage["period"] = period
            # C3-08: Coverage.class[] — group / plan
            # classification. For JP, class[0].type=group with 保険者番号 as
            # the coverage class identifier.
            # C5-09: diversify to include both `group` and
            # `plan` classifications when insurer symbol resolves to a plan
            # name — plan carries the human-readable insurance product name.
            _class_entries: list[dict[str, Any]] = [
                {
                    "type": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/coverage-class",
                                "code": "group",
                                "display": "Group" if not is_jp(country) else "保険グループ",
                            }
                        ],
                    },
                    "value": insurer,
                    "name": name_map.get(insurer, insurer),
                }
            ]
            if use_symbol:
                _class_entries.append(
                    {
                        "type": {
                            "coding": [
                                {
                                    "system": "http://terminology.hl7.org/CodeSystem/coverage-class",
                                    "code": "plan",
                                    "display": "Plan" if not is_jp(country) else "保険プラン",
                                }
                            ],
                        },
                        "value": use_symbol,
                        "name": name_map.get(insurer, insurer),
                    }
                )
            coverage["class"] = _class_entries
            # CY7-14 (Chain-7): Coverage.costToBeneficiary — JP 自己負担割合.
            # Standard JP 医療保険 co-pay: 3割 for adults, 1割 for elderly (≥70,
            # 現役並み所得除く). Population module carries age; use category as
            # a proxy (late-elderly insurer = 1割; others = 3割 default).
            _coshare_pct = 10 if category == "late_elderly" else 30
            coverage["costToBeneficiary"] = [
                {
                    "type": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/coverage-copay-type",
                                "code": "copaypct",
                                "display": "Copay percentage",
                            }
                        ],
                        "text": "自己負担割合" if is_jp(country) else "Copay percentage",
                    },
                    "valueQuantity": {
                        "value": _coshare_pct,
                        "unit": "%",
                        "system": "http://unitsofmeasure.org",
                        "code": "%",
                    },
                }
            ]
            resources.append(coverage)

    return resources


def _build_patient(p: dict, country: str) -> dict:
    """Build FHIR Patient resource with locale-aware name."""
    # Extract name from patient profile
    name_data = p.get("name", {})
    family = name_data.get("family_name", p.get("patient_id", ""))
    given = name_data.get("given_name", "")

    gender = "female" if p.get("sex") == "F" else "male"
    dob = p.get("date_of_birth")

    # Build FHIR HumanName. C2-19: JP Core requires
    # kanji + kana names as TWO separate name[] entries, each tagged with the
    # ISO21090 EN-representation extension using `valueCode` (was
    # `valueString` — an FHIR schema violation, JP Core validators reject).
    # Kanji name → IDE (ideographic), phonetic (katakana / hiragana) → SYL.
    ISO21090_URL = "http://hl7.org/fhir/StructureDefinition/iso21090-EN-representation"
    # C4-12: HumanName.use = "official" per FHIR R4 spec
    # and JP Core Patient recommendation for the registered / kanji name.
    names: list[dict[str, Any]] = []
    if is_jp(country):
        # Kanji entry — always emitted for JP.
        # Issue #378: JP_Patient_eCS requires `name.text` (min=1). Concatenate
        # kanji family + given with a single space (JP clinical convention:
        # "田中 徹") so the eCS profile assertion is data-complete.
        kanji_name: dict[str, Any] = {
            "use": "official",
            "text": f"{family} {given}".strip(),
            "family": family,
            "given": [given],
            "extension": [{"url": ISO21090_URL, "valueCode": "IDE"}],
        }
        names.append(kanji_name)
        # Phonetic (kana) entry — emitted only when phonetic pair present.
        # Issue #732: population/engine.py emits `PersonName.phonetic` as a
        # single string "<family-kana> <given-kana>" (see PersonName typed as
        # `str | None`), so the historical `isinstance(phonetic, dict)` gate
        # silently skipped 100% of JP Patients — no SYL entry across the
        # baseline. Accept both shapes so the emit doesn't rely on an upstream
        # schema unification: dict-form (already correct) OR string-form
        # (split on whitespace into family + given kana).
        phonetic = name_data.get("phonetic")
        kana_family = kana_given = ""
        if isinstance(phonetic, dict):
            kana_family = phonetic.get("family_name", "")
            kana_given = phonetic.get("given_name", "")
        elif isinstance(phonetic, str) and phonetic.strip():
            _parts = phonetic.strip().split(None, 1)
            kana_family = _parts[0] if _parts else ""
            kana_given = _parts[1] if len(_parts) > 1 else ""
        if kana_family or kana_given:
            _kana_fam = kana_family or family
            _kana_giv = kana_given or given
            names.append(
                {
                    "use": "official",
                    "text": f"{_kana_fam} {_kana_giv}".strip(),
                    "family": _kana_fam,
                    "given": [_kana_giv],
                    "extension": [{"url": ISO21090_URL, "valueCode": "SYL"}],
                }
            )
    else:
        names.append({"use": "official", "family": family, "given": [given]})
    names[0]  # kept for legacy readers below

    pid = p.get("patient_id", str(uuid.uuid4()))
    # Hospital MRN identifier system (country-specific)
    mrn_system = (
        "urn:oid:1.2.392.100495.20.3.51.1"  # JP example MRN OID
        if is_jp(country)
        else "http://hospital.example.org/identifiers/mrn"
    )
    resource: dict[str, Any] = {
        "resourceType": "Patient",
        # Issue #854 Bucket C row 18 (PR-patient): opaque `pt-<12hex>` id.
        # The CIF `patient_id` = ``POP-{n:06d}`` slug is preserved on
        # `.identifier[]` under POPULATION_SLUG_KEY_SYSTEM for
        # round-trip / consumer lookup.
        "id": resolve_patient_id(pid),
        # C2-20: declare JP Core Patient conformance
        # for JP exports. US export intentionally omits — no US Core profile
        # is asserted (a separate roadmap item).
        #
        # Issue #378 (restoring #379 with data-completeness):
        # JP_Patient_eCS assertion RESTORED. #382 removed the URI because
        # #379 had shipped URI-only without emitting the required fields
        # (`name.text`, `address.text`, `meta.lastUpdated`) — the resulting
        # 5× validator cascade justified the revert (feedback:
        # `feedback_profile_assertion_requires_data_completeness`). This PR
        # emits all three required fields BEFORE claiming the profile, so
        # the assertion is now data-complete and the eCS Pattern B (3,096
        # errors on referring resources) is resolved without the earlier
        # cascade. SD-verified min=1 requirements: `meta.lastUpdated`,
        # `meta.profile`, `name`, `name.text`, `name.given`, `gender`,
        # `birthDate`, `address`, `address.text`.
        **(
            {
                "meta": {
                    "profile": [
                        "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Patient",
                        "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Patient_eCS",
                    ],
                    # Static deterministic timestamp mirrors `_fhir_facility.py`
                    # (pattern). Real-world lastUpdated is server-
                    # provided; clinosim's simulator has no such notion, so
                    # a fixed value keeps reproducibility byte-clean while
                    # satisfying the eCS min=1 requirement.
                    "lastUpdated": "2026-01-01T00:00:00+09:00",
                }
            }
            if is_jp(country)
            else {}
        ),
        "identifier": [
            {
                "use": "usual",
                "type": {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-v2-0203"),
                            "code": "MR",
                            "display": "Medical Record Number",
                        }
                    ],
                    "text": "診療録番号" if is_jp(country) else "MRN",
                },
                "system": mrn_system,
                "value": pid,
                "assigner": {"reference": "Organization/hospital-main"},
            },
            # Issue #854 PR-patient: preserve the CIF simulation-slug
            # `POP-{n}` on identifier[] so consumers keyed on the
            # human-readable generation id can recover it after the
            # `.id` opaque migration.
            wrap_as_identifier(pid, POPULATION_SLUG_KEY_SYSTEM),
        ],
        "active": True,
        "name": names,
        "gender": gender,
    }

    if dob:
        resource["birthDate"] = to_fhir_date(dob)

    # CY7-15 (Chain-7): multipleBirthBoolean — required by JP Core Patient
    # profile 0..1. Default false (majority — realistic multiple-birth
    # rate <2% for JP live-birth records but registered explicitly on
    # birth certificate). Population module doesn't currently model this,
    # so default across cohort is a defensible completeness fix (Coverage:
    # boolean false is a valid emit per FHIR R4).
    resource["multipleBirthBoolean"] = False

    # CY7-16 (Chain-7): deceased[Boolean|DateTime] — carries mortality
    # status. Default deceasedBoolean=false because Patient records in
    # clinosim represent the living cohort at snapshot time; if the CIF
    # marks the patient as deceased, override with deceasedDateTime.
    _dod = p.get("date_of_death", "") or p.get("dod", "")
    if _dod:
        resource["deceasedDateTime"] = str(_dod)
        # Issue #926: FHIR `Patient.active` = "Whether this patient's record
        # is in active use." A deceased patient's record is by definition no
        # longer in active use. Flip active=false whenever the CIF marks
        # the patient as deceased (deceasedDateTime is set). Living patients
        # keep the default active=true set above.
        resource["active"] = False
    else:
        resource["deceasedBoolean"] = False

    # Blood type: v3 fix — JP Core (as of jpfhir.jp.core#1.2.0)
    # does not define a `JP_Patient_BloodTypeCode` Extension, and neither
    # FHIR core nor US Core specifies a Patient-level BloodType extension.
    # The URL we used to emit was fabricated; v3 validation flagged all
    # 580 JP Patients with an unknown-extension warning (580 resources /
    # ext URL). The follow-up chain now emits blood type as two
    # laboratory Observations per patient (LOINC 883-9 ABO group +
    # LOINC 10331-7 Rh group, SNOMED CT valueCodeableConcept) via
    # `_bb_blood_type` (`labs/blood_type.py`); the Patient resource
    # stays free of a fabricated extension.
    _ = p.get("blood_type")  # explicit no-op: blood type is emitted as Observation, not on Patient

    # Address
    addr = p.get("address")
    if addr and isinstance(addr, dict):
        fhir_addr = build_address(addr, country)
        if fhir_addr:
            resource["address"] = [fhir_addr]

    # Telecom (phone)
    contact = p.get("contact")
    if contact and isinstance(contact, dict):
        telecoms = build_telecom(contact)
        if telecoms:
            resource["telecom"] = telecoms

    # Marital status
    marital = p.get("marital_status", "")
    if marital:
        resource["maritalStatus"] = {
            "coding": [
                {
                    "system": get_system_uri("hl7-v3-maritalstatus"),
                    "code": marital,
                    "display": code_lookup("hl7-v3-maritalstatus", marital, resolve_lang(country)),
                }
            ],
        }

    # Communication / preferred language
    lang = p.get("preferred_language", "")
    if lang:
        # BCP-47 (`urn:ietf:bcp:47`) is English-only per the fhir-jp-validator
        # tx-server loadout — the ja localization is not a registered synonym.
        # Emit the English display regardless of country.
        resource["communication"] = [
            {
                "language": {
                    "coding": [
                        {
                            "system": get_system_uri("bcp-47-language"),
                            "code": lang,
                            "display": code_lookup("bcp-47-language", lang, "en"),
                        }
                    ],
                },
                "preferred": True,
            }
        ]

    # Emergency contact
    if contact and isinstance(contact, dict):
        emer_name = contact.get("emergency_contact_name", "")
        emer_phone = contact.get("emergency_contact_phone", "")
        emer_rel = contact.get("emergency_contact_relationship", "")
        if emer_name or emer_phone:
            ec: dict[str, Any] = {}
            if emer_rel:
                ec["relationship"] = [
                    {
                        "coding": [
                            {
                                "system": get_system_uri("hl7-v2-0131"),
                                "code": "C",
                                "display": "Emergency Contact",
                            }
                        ],
                        "text": _localize_display(emer_rel, country, _RELATIONSHIP_DISPLAY_JA),
                    }
                ]
            if emer_name:
                ec["name"] = {"text": emer_name}
            if emer_phone:
                ec["telecom"] = [
                    {
                        "system": "phone",
                        "value": emer_phone,
                        "use": "mobile",
                    }
                ]
            resource["contact"] = [ec]

    # Issue #743: JP_Patient_eCS declares `JP_eCS_InstitutionNumber` as
    # must-support (the Department extension context excludes Patient).
    # Attach here (inline) because Patient's eCS profile URL is set
    # directly on this builder, not via `_apply_jp_clins_profile` post-hook.
    from clinosim.modules.output.fhir_r4.lib.common import attach_ecs_institutional_extensions

    attach_ecs_institutional_extensions(resource, country, include_department=False)

    return resource


# ============================================================
# AllergyIntolerance
# ============================================================


# Occupation category localization for Observation.valueCodeableConcept
def _build_occupation_observation(
    occupation: str,
    patient_id: str,
    country: str,
) -> dict | None:
    """Build FHIR Observation for patient occupation (social history).

    Uses US Core Patient Occupation profile (LOINC 11341-5).
    Reference: http://hl7.org/fhir/us/core/StructureDefinition/us-core-occupation
    """
    if not occupation:
        return None
    display_map = _OCCUPATION_DISPLAY_JA if is_jp(country) else _OCCUPATION_DISPLAY_EN
    display = display_map.get(occupation, occupation.title())
    _occupation_key = patient_id
    return {
        "resourceType": "Observation",
        "id": _resolve_occupation_id(_occupation_key),
        "identifier": [wrap_as_identifier(_occupation_key, OCCUPATION_KEY_SYSTEM)],
        # chain #2: JP Core Observation_Common profile.
        **(
            {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common"]}}
            if is_jp(country)
            else {}
        ),
        "status": "final",
        "category": _social_category(country),
        "code": {
            "coding": [
                {
                    "system": get_system_uri("loinc"),
                    "code": "11341-5",
                    "display": "History of Occupation",
                }
            ],
            "text": "職業" if is_jp(country) else "Occupation",
        },
        "subject": patient_ref(patient_id),
        "valueCodeableConcept": {
            "coding": [
                {
                    "system": get_system_uri("occupation-category"),
                    "code": occupation,
                    "display": display,
                }
            ],
            "text": display,
        },
    }


def _build_allergy_intolerance(
    allergy: dict,
    patient_id: str,
    index: int,
    country: str,
) -> dict | None:
    """Build FHIR AllergyIntolerance from CIF allergy data."""
    substance = allergy.get("substance", "")
    if not substance:
        return None

    # Localize substance display for JP
    substance_display = _localize_drug_name(substance, country) if is_jp(country) else substance

    rxnorm = _ALLERGEN_RXNORM.get(substance, "")
    code: dict[str, Any] = {"text": substance_display}
    if rxnorm:
        code["coding"] = [
            {
                "system": get_system_uri("rxnorm"),
                "code": rxnorm,
                "display": substance_display,
            }
        ]

    severity = allergy.get("severity", "mild").lower()
    criticality = "high" if severity == "severe" else "low"

    reaction_type = allergy.get("reaction_type", "")
    reaction: dict[str, Any] = {"severity": severity}
    if reaction_type:
        reaction["manifestation"] = [
            {
                "text": reaction_type,
            }
        ]

    return {
        "resourceType": "AllergyIntolerance",
        "id": f"allergy-{patient_id}-{index:02d}",  # patient-scoped is OK (allergies are patient-level)
        "clinicalStatus": {
            "coding": [
                {
                    "system": get_system_uri("hl7-allergyintolerance-clinical"),
                    "code": "active",
                    "display": "Active",
                }
            ],
        },
        "verificationStatus": {
            "coding": [
                {
                    "system": get_system_uri("hl7-allergyintolerance-verification"),
                    "code": "confirmed",
                    "display": "Confirmed",
                }
            ],
        },
        "type": "allergy",
        "category": ["medication"],
        "criticality": criticality,
        "code": code,
        "patient": patient_ref(patient_id),
        "reaction": [reaction],
    }
