"""Order engine — v0.1-alpha: lab and medication orders from protocol YAML.

Expands disease protocol order definitions into concrete Order instances with timing.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from clinosim.modules._shared import get_attr_or_key as _s
from clinosim.modules.imaging.engine import (
    _resolve_imaging_procedure_code_key,
    load_body_sites,
    load_modalities,
)
from clinosim.modules.order.panel_grouping import classify_lab_specs, load_panel_definitions
from clinosim.modules.order.treatment_classifier import classify_inpatient_supportive
from clinosim.types.encounter import Order, OrderStatus, OrderType

# Mapping: text frequency token → times per day
_FREQ_PER_DAY: dict[str, int] = {
    "once": 1,
    "qd": 1,
    "daily": 1,
    "bid": 2,
    "q12h": 2,
    "tid": 3,
    "q8h": 3,
    "qid": 4,
    "q6h": 4,
    "q4h": 6,
    "q3h": 8,
    "q2h": 12,
    "continuous": 24,
    "drip": 24,
}


def place_imaging_orders(
    disease_protocol: Any,
    encounter_id: str,
    patient_id: str,
    admission_dt: datetime,
    day_index: int,
    severity: str,
    rng: np.random.Generator,
    sequence_counter: dict[str, int],
) -> list[Order]:
    """Emit one Order(OrderType.IMAGING) per matching imaging_orders[] entry.

    Filter rules:
      - spec.day must equal day_index (admission day = 0, next day = 1, …)
      - if spec.only_if_severity is non-empty, severity must be in the list
    No Order is emitted for non-matching specs.

    For matching specs:
      - resolve procedure_code via body_sites.yaml[body_site].procedure_codes[key].loinc
      - emit one Order per spec; multi-view info is preserved in Order.imaging_views
        and expanded into ImagingStudy Series by the imaging enricher (Task 4)
      - sequence_counter["I"] is incremented per-Order and used in order_id (threads
        across admission + daily calls so IDs are unique within the encounter)
      - if spec.views is empty, fall back to modalities.yaml[modality].default_views_by_body_site

    Spec access is via _s() (get_attr_or_key) so this function accepts both:
      - ImagingOrderSpec Pydantic objects (production path from DiseaseProtocol)
      - plain dicts (unit test stubs via _StubProtocol)
    """
    imaging_specs = getattr(disease_protocol, "imaging_orders", None) or []
    if not imaging_specs:
        return []

    body_sites = load_body_sites()
    modalities = load_modalities()
    orders: list[Order] = []

    for spec in imaging_specs:
        if _s(spec, "day", 0) != day_index:
            continue
        only_if = _s(spec, "only_if_severity", [])
        if only_if and severity not in only_if:
            continue

        modality_key: str = _s(spec, "modality", "")
        body_site_key: str = _s(spec, "body_site", "")
        contrast: bool = _s(spec, "contrast", False)
        urgency: str = _s(spec, "urgency", "routine")
        clinical_indication: str = _s(spec, "clinical_indication", "")
        abnormal_rate: dict = dict(_s(spec, "abnormal_rate_by_severity", {}))

        body_site = body_sites.get(body_site_key)
        if not body_site:
            raise ValueError(f"imaging_orders[].body_site='{body_site_key}' not found in body_sites.yaml")
        modality_def = modalities.get(modality_key)
        if not modality_def:
            raise ValueError(f"imaging_orders[].modality='{modality_key}' not found in modalities.yaml")

        views: list[str] = list(_s(spec, "views", []))
        if not views:
            views = list((modality_def.get("default_views_by_body_site") or {}).get(body_site_key, []))

        code_key = _resolve_imaging_procedure_code_key(modality_key, body_site_key, views, contrast)
        proc = (body_site.get("procedure_codes") or {}).get(code_key)
        if not proc:
            raise ValueError(f"body_sites.yaml[{body_site_key}].procedure_codes['{code_key}'] not found")

        sequence_counter["I"] = sequence_counter.get("I", 0) + 1
        ordered_dt = admission_dt + timedelta(days=day_index, minutes=int(rng.normal(15, 5)))
        order = Order(
            order_id=f"ORD-{encounter_id}-I{sequence_counter['I']:02d}",
            encounter_id=encounter_id,
            patient_id=patient_id,
            order_type=OrderType.IMAGING,
            order_code=proc["loinc"],
            display_name=proc["display_en"],
            urgency=urgency,
            clinical_intent=clinical_indication,
            ordered_datetime=ordered_dt,
            status=OrderStatus.PLACED,
            imaging_modality=modality_key,
            imaging_body_site_code=body_site["snomed"],
            imaging_views=views,
            imaging_spec_meta={"abnormal_rate_by_severity": abnormal_rate, "contrast": contrast},
        )
        orders.append(order)

    return orders


def enrich_medication_order(order: Order, dose_str: str = "") -> Order:
    """Populate dose/frequency/route fields by parsing display_name and dose_str.

    Idempotent — safe to call multiple times. Mutates and returns the order.
    """
    # Try the explicit dose string first, then fall back to display_name
    parsed = parse_dose_string(dose_str) if dose_str else {}
    if not parsed:
        parsed = parse_dose_string(order.display_name)

    if order.dose_quantity is None and parsed.get("dose_quantity") is not None:
        order.dose_quantity = parsed["dose_quantity"]
    if not order.dose_unit and parsed.get("dose_unit"):
        order.dose_unit = parsed["dose_unit"]
    if not order.frequency and parsed.get("frequency"):
        order.frequency = parsed["frequency"]
    if order.frequency_per_day is None and parsed.get("frequency_per_day") is not None:
        order.frequency_per_day = parsed["frequency_per_day"]
    if not order.route and parsed.get("route"):
        order.route = parsed["route"]
    # Fallback: heuristic from drug name (PO is the default for tablets)
    if not order.route and order.display_name:
        from clinosim.simulator.helpers import _determine_route

        order.route = _determine_route(order.display_name, order.clinical_intent or "")
    # Default frequency: assume daily if dose is set but no frequency parsed
    if order.dose_quantity is not None and not order.frequency:
        order.frequency = "DAILY"
        order.frequency_per_day = 1
    return order


def parse_dose_string(dose_str: str) -> dict[str, Any]:
    """Parse a dose string like '500mg PO BID' into structured fields.

    Returns dict with keys: dose_quantity, dose_unit, frequency, frequency_per_day, route.
    All keys may be missing if unparseable.
    """
    result: dict[str, Any] = {}
    if not dose_str:
        return result

    s = dose_str.strip()

    # Dose quantity + unit (e.g. "500mg", "1.5g", "1000IU", "0.4mg")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(mg|g|mcg|ug|mL|ml|L|IU|U|unit|units|%)", s, re.IGNORECASE)
    if m:
        try:
            result["dose_quantity"] = float(m.group(1))
            result["dose_unit"] = m.group(2)
        except ValueError:
            pass

    # Route (PO, IV, SC, IM, SL, topical, inhaled, PR, NG)
    route_match = re.search(r"\b(PO|IV|SC|IM|SL|PR|NG|inhaled|topical|nebulized)\b", s, re.IGNORECASE)
    if route_match:
        result["route"] = route_match.group(1).upper()

    # Frequency tokens
    s_lower = s.lower()
    for token, per_day in _FREQ_PER_DAY.items():
        # Use word boundaries for safety
        if re.search(rf"\b{re.escape(token)}\b", s_lower):
            result["frequency"] = token.upper()
            result["frequency_per_day"] = per_day
            break

    return result


def _build_lab_order(
    *,
    order_id: str,
    encounter_id: str,
    patient_id: str,
    lab_spec: dict,
    ordered_datetime: datetime,
    ordered_by: str,
    panel_key: str,
    clinical_intent: str,
) -> Order:
    """Build a single LAB Order (shared by admission + daily, panel + stand-alone).

    Urgency defaults to ``lab_spec.get("urgency", "routine")`` so YAML-declared
    urgency is honoured uniformly across all four call sites (admission panel,
    admission stand-alone, daily panel, daily stand-alone).  RNG draws happen at
    the call site BEFORE this helper is invoked, so the RNG sequence is unchanged.
    """
    return Order(
        order_id=order_id,
        encounter_id=encounter_id,
        patient_id=patient_id,
        order_type=OrderType.LAB,
        order_code=lab_spec.get("code_loinc", lab_spec.get("test", "")),
        display_name=lab_spec["test"],
        urgency=lab_spec.get("urgency", "routine"),
        clinical_intent=clinical_intent,
        ordered_datetime=ordered_datetime,
        ordered_by=ordered_by,
        status=OrderStatus.PLACED,
        panel_key=panel_key,
    )


def place_admission_orders(
    protocol: dict,
    patient_id: str,
    encounter_id: str,
    admission_time: datetime,
    country: str,
    rng: np.random.Generator,
    ordered_by: str = "",
) -> list[Order]:
    """Expand protocol admission orders into concrete Order instances.

    Reads order_protocols.admission_orders from disease YAML.
    Falls back to drugs/expected_lab_distributions if order_protocols not defined.
    """
    orders: list[Order] = []

    # Prefer YAML order_protocols, fall back to legacy structure
    order_protocols = protocol.get("order_protocols", {})
    admission = order_protocols.get("admission_orders", {})

    if not admission.get("labs"):
        # Fallback: derive from expected_lab_distributions
        lab_dists = protocol.get("expected_lab_distributions", {}).get("admission", {})
        admission["labs"] = [{"test": name, "urgency": "stat"} for name in lab_dists.keys()]

    if not admission.get("supportive"):
        admission["supportive"] = [
            {"type": "IV_fluid", "detail": "NS 80-125 mL/h"},
            {"type": "DVT_prophylaxis", "detail": "Enoxaparin 2000IU SC daily"},
        ]

    if not admission.get("imaging"):
        admission["imaging"] = [{"test": "Chest_Xray", "urgency": "stat"}]

    # Medications: from drugs.first_line (always from drugs section)
    drugs = protocol.get("drugs", {})
    first_line_list = drugs.get("first_line", {}).get(country, [])
    if isinstance(first_line_list, dict):
        first_line_list = [first_line_list]
    admission["medications"] = {"first_line": {country: first_line_list}}

    # Lab orders (panel-aware grouping for PR1 ServiceRequest).
    # Probability filter runs before classify_lab_specs so that borderline
    # panels (optional components dropping below min_components) resolve
    # correctly — the classifier only sees specs that will actually be ordered.
    panels = load_panel_definitions()
    lab_specs: list[dict[str, Any]] = []
    for lab_spec in admission.get("labs", []):
        prob = lab_spec.get("probability", 1.0)
        if prob < 1.0 and rng.random() > prob:
            continue  # optional test, not ordered this time
        lab_specs.append(lab_spec)

    panel_groups, stand_alones = classify_lab_specs(lab_specs, panels)

    # Emit panel Orders: all members share ordered_datetime for the same panel.
    # Urgency is taken from the first/anchor member of each panel — all members
    # are part of the same draw, so mixing urgency within a panel SR is ambiguous.
    # sorted() ensures deterministic emission order (AD-16).
    order_seq = 0
    for panel_name in sorted(panel_groups.keys()):
        members = panel_groups[panel_name]
        panel_time = admission_time + timedelta(minutes=int(rng.normal(5, 3)))
        for lab_spec in members:
            orders.append(
                _build_lab_order(
                    order_id=f"ORD-{encounter_id}-ADM-L{order_seq:02d}",
                    encounter_id=encounter_id,
                    patient_id=patient_id,
                    lab_spec=lab_spec,
                    ordered_datetime=panel_time,
                    ordered_by=ordered_by,
                    panel_key=panel_name,
                    clinical_intent=f"Admission workup: {lab_spec['test']}",
                )
            )
            order_seq += 1

    # Emit stand-alone Orders: each test has its own independent datetime.
    for lab_spec in stand_alones:
        orders.append(
            _build_lab_order(
                order_id=f"ORD-{encounter_id}-ADM-L{order_seq:02d}",
                encounter_id=encounter_id,
                patient_id=patient_id,
                lab_spec=lab_spec,
                ordered_datetime=admission_time + timedelta(minutes=int(rng.normal(5, 3))),
                ordered_by=ordered_by,
                panel_key="",
                clinical_intent=f"Admission workup: {lab_spec['test']}",
            )
        )
        order_seq += 1

    # Medication orders (all first-line drugs, not just the first)
    meds = admission.get("medications", {})
    first_line_raw = meds.get("first_line", {}).get(country.lower(), [])
    if isinstance(first_line_raw, dict):
        first_line_raw = [first_line_raw]
    for med_idx, med_spec in enumerate(first_line_raw):
        if not isinstance(med_spec, dict):
            continue
        dose_str = med_spec.get("dose", "")
        parsed = parse_dose_string(dose_str)
        drug_name = med_spec.get("drug", "Unknown")
        order = Order(
            order_id=f"ORD-{encounter_id}-ADM-M{med_idx + 1:02d}",
            encounter_id=encounter_id,
            patient_id=patient_id,
            order_type=OrderType.MEDICATION,
            order_code=med_spec.get("code_yj") or med_spec.get("code_rxnorm") or "",
            display_name=drug_name,
            urgency="stat",
            clinical_intent=f"First-line treatment: {drug_name}",
            ordered_datetime=admission_time + timedelta(minutes=int(rng.normal(30, 10))),
            ordered_by=ordered_by,
            status=OrderStatus.PLACED,
            dose_quantity=parsed.get("dose_quantity"),
            dose_unit=parsed.get("dose_unit", ""),
            frequency=parsed.get("frequency", ""),
            frequency_per_day=parsed.get("frequency_per_day"),
            route=parsed.get("route") or med_spec.get("route", ""),
            duration_days=med_spec.get("duration_days"),
        )
        orders.append(order)

    # Supportive orders — classify into medication vs. care plan/therapy via
    # the canonical treatment_classifier (single source of truth shared with
    # the ED treatment path in simulator/emergency.py; J5 pattern prevention).
    for i, sup in enumerate(admission.get("supportive", [])):
        sup_type = sup.get("type", "")
        # CY2-B continuation (session 43 cycle 5): disease-YAML supportive detail
        # texts sometimes carry alternatives ("NS or LR", "Enoxaparin ... or IPC").
        # Real MARs specify what was given — pick the primary (first) alternative
        # for the Order display_name so downstream FHIR emit doesn't produce
        # "生理食塩液 または 乳酸リンゲル液" as a fake compound drug name.
        detail_raw = str(sup.get("detail", "") or "")
        for splitter in (" or ", " OR ", " または "):
            if splitter in detail_raw:
                detail_raw = detail_raw.split(splitter, 1)[0].strip()
                break
        order_type = classify_inpatient_supportive(detail_raw, sup_type)
        order = Order(
            order_id=f"ORD-{encounter_id}-ADM-S{i:02d}",
            encounter_id=encounter_id,
            patient_id=patient_id,
            order_type=order_type,
            order_code="",
            display_name=f"{sup['type']}: {detail_raw}",
            urgency="routine",
            clinical_intent=f"Supportive: {sup['type']}",
            ordered_datetime=admission_time + timedelta(minutes=int(rng.normal(45, 15))),
            ordered_by=ordered_by,
            status=OrderStatus.PLACED,
        )
        # P1-3 (session 51): Enrich MEDICATION orders with dose from detail_raw
        # so dose_quantity / dose_unit are correctly set (not display_name).
        if order_type == OrderType.MEDICATION:
            enrich_medication_order(order, dose_str=detail_raw)
        orders.append(order)

    # Imaging orders
    for i, img_spec in enumerate(admission.get("imaging", [])):
        order = Order(
            order_id=f"ORD-{encounter_id}-ADM-I{i:02d}",
            encounter_id=encounter_id,
            patient_id=patient_id,
            order_type=OrderType.IMAGING,
            order_code=img_spec.get("code_cpt", ""),
            display_name=img_spec.get("test", "Imaging"),
            urgency=img_spec.get("urgency", "stat"),
            clinical_intent=f"Admission imaging: {img_spec.get('test', '')}",
            ordered_datetime=admission_time + timedelta(minutes=int(rng.normal(20, 8))),
            ordered_by=ordered_by,
            status=OrderStatus.PLACED,
        )
        orders.append(order)

    return orders


def place_daily_lab_orders(
    protocol: dict,
    patient_id: str,
    encounter_id: str,
    day_number: int,
    order_time: datetime,
    lab_frequency_multiplier: float,
    rng: np.random.Generator,
    ordered_by: str = "",
) -> list[Order]:
    """Place daily monitoring lab orders per protocol. Reads from YAML order_protocols.daily_monitoring."""
    orders: list[Order] = []

    # Read from YAML, fall back to defaults
    order_protocols = protocol.get("order_protocols", {})
    daily_monitoring = order_protocols.get("daily_monitoring", {})
    daily_labs = daily_monitoring.get(
        "labs",
        [
            {"test": "CRP", "frequency": "daily"},
            {"test": "WBC", "frequency": "daily"},
            {"test": "Creatinine", "frequency": "daily"},
        ],
    )

    # Build effective_specs (post-filter) before classify_lab_specs so that
    # borderline panels resolve on the actually-ordered set (same pattern as
    # place_admission_orders, see comment there).
    effective_specs: list[dict[str, Any]] = []
    for lab_spec in daily_labs:
        freq = lab_spec.get("frequency", "daily")
        jp_mod = lab_spec.get("japan_modifier", 1.0)

        # Optional tests (probability < 1.0): physician discretion
        prob = lab_spec.get("probability", 1.0)
        if prob < 1.0 and rng.random() > prob:
            continue

        # Every_N_days frequency
        if freq == "every_3_days" and day_number % 3 != 0:
            continue

        # Apply frequency: "daily" with modifier < 1.0 means skip some days
        effective_freq = jp_mod * lab_frequency_multiplier
        if freq == "daily" and effective_freq < 1.0:
            if rng.random() > effective_freq:
                continue

        effective_specs.append(lab_spec)

    # Panel-aware grouping — daily monitoring typically yields stand-alone Orders
    # (1-3 tests rarely meet any panel's min_components), but the same code path
    # handles both correctly.  sorted() ensures deterministic emission (AD-16).
    panels = load_panel_definitions()
    panel_groups, stand_alones = classify_lab_specs(effective_specs, panels)

    order_seq = 0
    for panel_name in sorted(panel_groups.keys()):
        members = panel_groups[panel_name]
        # Daily monitoring panels share the morning round order_time.
        for lab_spec in members:
            orders.append(
                _build_lab_order(
                    order_id=f"ORD-{encounter_id}-D{day_number:02d}-L{order_seq:02d}",
                    encounter_id=encounter_id,
                    patient_id=patient_id,
                    lab_spec=lab_spec,
                    ordered_datetime=order_time,
                    ordered_by=ordered_by,
                    panel_key=panel_name,
                    clinical_intent=f"Day {day_number} monitoring: {lab_spec['test']}",
                )
            )
            order_seq += 1

    for lab_spec in stand_alones:
        orders.append(
            _build_lab_order(
                order_id=f"ORD-{encounter_id}-D{day_number:02d}-L{order_seq:02d}",
                encounter_id=encounter_id,
                patient_id=patient_id,
                lab_spec=lab_spec,
                ordered_datetime=order_time,
                ordered_by=ordered_by,
                panel_key="",
                clinical_intent=f"Day {day_number} monitoring: {lab_spec['test']}",
            )
        )
        order_seq += 1

    return orders


def calculate_lab_result_time(
    order: Order,
    rng: np.random.Generator,
) -> datetime:
    """Calculate when a lab result becomes available.

    Models real-world delays: urgency, time of day, weekday, random congestion.
    """
    base_delay_minutes: float
    if order.urgency == "stat":
        base_delay_minutes = float(rng.normal(45, 15))
    else:
        base_delay_minutes = float(rng.normal(120, 30))

    ordered = order.ordered_datetime
    hour = ordered.hour
    weekday = ordered.weekday()  # 0=Mon, 6=Sun

    # Night: defer routine to morning
    if (hour >= 22 or hour < 6) and order.urgency != "stat":
        next_morning = ordered.replace(hour=6, minute=30, second=0)
        if hour >= 22:
            next_morning += timedelta(days=1)
        return next_morning + timedelta(minutes=float(rng.normal(90, 30)))

    # Weekend delay: lab staff reduced, processing slower
    if weekday >= 5:  # Saturday/Sunday
        base_delay_minutes *= 1.5
        if order.urgency != "stat":
            base_delay_minutes *= 1.3  # non-urgent even slower on weekends

    # Random congestion: ~15% chance of significant delay (equipment busy, batch processing)
    if rng.random() < 0.15:
        congestion_extra = float(rng.exponential(30))  # 0-90 min extra
        base_delay_minutes += congestion_extra

    # Evening (17-22): reduced staff, slight delay
    if 17 <= hour < 22:
        base_delay_minutes *= 1.2

    delay = max(15.0, base_delay_minutes)
    return ordered + timedelta(minutes=delay)


def calculate_imaging_result_time(
    order: Order,
    rng: np.random.Generator,
) -> datetime:
    """Calculate when imaging is performed and result available.

    Models: scheduling delay + exam duration + reporting delay.
    CT/MRI have longer waits than X-ray.
    """
    ordered = order.ordered_datetime
    hour = ordered.hour
    weekday = ordered.weekday()

    imaging_name = order.display_name.upper()

    # Scheduling delay (time from order to exam start)
    if order.urgency == "stat":
        if "CT" in imaging_name or "MRI" in imaging_name:
            schedule_delay = float(rng.normal(60, 20))  # stat CT: ~1h
        else:
            schedule_delay = float(rng.normal(30, 10))  # stat X-ray: ~30min
    else:
        if "MRI" in imaging_name:
            schedule_delay = float(rng.normal(24 * 60, 8 * 60))  # routine MRI: 1-2 days
        elif "CT" in imaging_name:
            schedule_delay = float(rng.normal(4 * 60, 2 * 60))  # routine CT: 2-6h
        elif "ECHO" in imaging_name or "ULTRASOUND" in imaging_name:
            schedule_delay = float(rng.normal(3 * 60, 60))  # echo/US: 2-4h
        else:
            schedule_delay = float(rng.normal(60, 30))  # X-ray: ~1h

    # Weekend: scheduling takes longer
    if weekday >= 5:
        schedule_delay *= 1.5
        if "MRI" in imaging_name and order.urgency != "stat":
            schedule_delay += 24 * 60  # MRI may defer to Monday

    # Night: non-urgent deferred to morning
    if (hour >= 22 or hour < 6) and order.urgency != "stat":
        schedule_delay += (6 - hour if hour < 6 else 30 - hour) * 60

    # Reporting delay (radiologist reads and writes report)
    if order.urgency == "stat":
        report_delay = float(rng.normal(30, 10))  # stat: ~30min
    else:
        report_delay = float(rng.normal(4 * 60, 2 * 60))  # routine: 2-6h

    total_delay = max(15, schedule_delay + report_delay)
    return ordered + timedelta(minutes=total_delay)


# ============================================================
# Hospital-state-aware delay calculation
# ============================================================


def calculate_result_time_from_state(
    order: Order,
    hospital_state: Any,
    ops_config: dict,
    rng: Any,
) -> datetime:
    """Calculate result time using hospital operational state.

    Delays emerge from resource utilization and staffing, not hardcoded values.
    Falls back to legacy calculation if hospital_state is None.
    """
    if hospital_state is None:
        return calculate_lab_result_time(order, rng)

    ordered = order.ordered_datetime

    # Determine resource type
    order_type = order.order_type.value
    name_upper = order.display_name.upper()

    if order_type == "lab":
        resource = "lab"
    elif order_type == "imaging":
        if "MRI" in name_upper:
            resource = "mri"
        elif "CT" in name_upper:
            resource = "ct"
        elif "XRAY" in name_upper or "X-RAY" in name_upper or "CHEST" in name_upper:
            resource = "xray"
        elif "ECHO" in name_upper or "ULTRA" in name_upper:
            resource = "ultrasound"
        else:
            resource = "xray"  # default imaging
    else:
        # Medication, diet, etc. — no result time needed
        return ordered + timedelta(minutes=5)

    # Update hospital state for current time
    hospital_state.update_for_time(ordered, ops_config)

    # Calculate delay from state
    delay = hospital_state.calculate_delay(resource, order.urgency, ops_config)

    # Add randomness (±20%)
    delay *= float(1.0 + rng.normal(0, 0.2))
    delay = max(10.0, delay)

    # Night deferral for non-stat
    hour = ordered.hour
    if (hour >= 22 or hour < 6) and order.urgency != "stat":
        next_morning = ordered.replace(hour=6, minute=30, second=0)
        if hour >= 22:
            next_morning += timedelta(days=1)
        delay = max(delay, (next_morning - ordered).total_seconds() / 60)

    # Update queue
    hospital_state.add_to_queue(resource, ops_config)

    return ordered + timedelta(minutes=delay)
