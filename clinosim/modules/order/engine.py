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
    """Calculate when a lab result becomes available."""
    base_delay_minutes: float
    if order.urgency == "stat":
        base_delay_minutes = float(rng.normal(45, 15))
    else:
        base_delay_minutes = float(rng.normal(120, 30))

    # Night: defer routine to morning
    hour = order.ordered_datetime.hour
    if (hour >= 22 or hour < 6) and order.urgency != "stat":
        # Defer to 06:30 next morning
        next_morning = order.ordered_datetime.replace(hour=6, minute=30, second=0)
        if hour >= 22:
            next_morning += timedelta(days=1)
        return next_morning + timedelta(minutes=float(rng.normal(90, 30)))

    delay = max(15.0, base_delay_minutes)
    return order.ordered_datetime + timedelta(minutes=delay)
