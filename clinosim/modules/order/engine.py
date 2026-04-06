"""Order engine — v0.1-alpha: lab and medication orders from protocol YAML.

Expands disease protocol order definitions into concrete Order instances with timing.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from clinosim.types.encounter import Order, OrderStatus, OrderType


def place_admission_orders(
    protocol: dict,
    patient_id: str,
    encounter_id: str,
    admission_time: datetime,
    country: str,
    rng: np.random.Generator,
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

    # Lab orders (probability field: 1.0=mandatory, <1.0=optional)
    for i, lab_spec in enumerate(admission.get("labs", [])):
        prob = lab_spec.get("probability", 1.0)
        if prob < 1.0 and rng.random() > prob:
            continue  # optional test, not ordered this time

        order = Order(
            order_id=f"ORD-{patient_id}-ADM-L{i:02d}",
            encounter_id=encounter_id,
            patient_id=patient_id,
            order_type=OrderType.LAB,
            order_code=lab_spec.get("code_loinc", lab_spec.get("test", "")),
            display_name=lab_spec["test"],
            urgency=lab_spec.get("urgency", "routine"),
            clinical_intent=f"Admission workup: {lab_spec['test']}",
            ordered_datetime=admission_time + timedelta(minutes=int(rng.normal(5, 3))),
            ordered_by="STAFF-PLACEHOLDER-001",
            status=OrderStatus.PLACED,
        )
        orders.append(order)

    # Medication orders
    meds = admission.get("medications", {})
    first_line = meds.get("first_line", {}).get(country.lower(), {})
    if first_line:
        med_spec = first_line if isinstance(first_line, dict) else first_line[0] if first_line else {}
        if med_spec:
            order = Order(
                order_id=f"ORD-{patient_id}-ADM-M01",
                encounter_id=encounter_id,
                patient_id=patient_id,
                order_type=OrderType.MEDICATION,
                order_code=med_spec.get("code_yj", med_spec.get("code_rxnorm", "")),
                display_name=med_spec.get("drug", "Unknown"),
                urgency="stat",
                clinical_intent=f"Empiric antibiotic: {med_spec.get('drug', '')}",
                ordered_datetime=admission_time + timedelta(minutes=int(rng.normal(30, 10))),
                ordered_by="STAFF-PLACEHOLDER-001",
                status=OrderStatus.PLACED,
            )
            orders.append(order)

    # Supportive orders
    for i, sup in enumerate(admission.get("supportive", [])):
        order = Order(
            order_id=f"ORD-{patient_id}-ADM-S{i:02d}",
            encounter_id=encounter_id,
            patient_id=patient_id,
            order_type=OrderType.MEDICATION,
            order_code="",
            display_name=f"{sup['type']}: {sup['detail']}",
            urgency="routine",
            clinical_intent=f"Supportive: {sup['type']}",
            ordered_datetime=admission_time + timedelta(minutes=int(rng.normal(45, 15))),
            ordered_by="STAFF-PLACEHOLDER-001",
            status=OrderStatus.PLACED,
        )
        orders.append(order)

    # Imaging orders
    for i, img_spec in enumerate(admission.get("imaging", [])):
        order = Order(
            order_id=f"ORD-{patient_id}-ADM-I{i:02d}",
            encounter_id=encounter_id,
            patient_id=patient_id,
            order_type=OrderType.IMAGING,
            order_code=img_spec.get("code_cpt", ""),
            display_name=img_spec.get("test", "Imaging"),
            urgency=img_spec.get("urgency", "stat"),
            clinical_intent=f"Admission imaging: {img_spec.get('test', '')}",
            ordered_datetime=admission_time + timedelta(minutes=int(rng.normal(20, 8))),
            ordered_by="STAFF-PLACEHOLDER-001",
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
) -> list[Order]:
    """Place daily monitoring lab orders per protocol. Reads from YAML order_protocols.daily_monitoring."""
    orders: list[Order] = []

    # Read from YAML, fall back to defaults
    order_protocols = protocol.get("order_protocols", {})
    daily_monitoring = order_protocols.get("daily_monitoring", {})
    daily_labs = daily_monitoring.get("labs", [
        {"test": "CRP", "frequency": "daily"},
        {"test": "WBC", "frequency": "daily"},
        {"test": "Creatinine", "frequency": "daily"},
    ])

    for i, lab_spec in enumerate(daily_labs):
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

        order = Order(
            order_id=f"ORD-{patient_id}-D{day_number:02d}-L{i:02d}",
            encounter_id=encounter_id,
            patient_id=patient_id,
            order_type=OrderType.LAB,
            order_code=lab_spec.get("code_loinc", lab_spec.get("test", "")),
            display_name=lab_spec["test"],
            urgency="routine",
            clinical_intent=f"Day {day_number} monitoring: {lab_spec['test']}",
            ordered_datetime=order_time,
            ordered_by="STAFF-PLACEHOLDER-001",
            status=OrderStatus.PLACED,
        )
        orders.append(order)

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
            schedule_delay = float(rng.normal(60, 20))   # stat CT: ~1h
        else:
            schedule_delay = float(rng.normal(30, 10))   # stat X-ray: ~30min
    else:
        if "MRI" in imaging_name:
            schedule_delay = float(rng.normal(24 * 60, 8 * 60))  # routine MRI: 1-2 days
        elif "CT" in imaging_name:
            schedule_delay = float(rng.normal(4 * 60, 2 * 60))   # routine CT: 2-6h
        elif "ECHO" in imaging_name or "ULTRASOUND" in imaging_name:
            schedule_delay = float(rng.normal(3 * 60, 60))        # echo/US: 2-4h
        else:
            schedule_delay = float(rng.normal(60, 30))             # X-ray: ~1h

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
