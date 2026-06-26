"""Pure functions for the antibiotic module (PR3b-1).

load_hai_empirical reads reference_data/hai_empirical.yaml once and
validates keys against HAI_TYPES + ANTIBIOTIC_DRUGS canonical
constants — surfacing case-mismatch / typo class of bugs at import
time (PR-90 教訓). build_regimens + generate_mar_doses produce the
typed records the enricher attaches to the CIF record.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from clinosim.modules.antibiotic import ANTIBIOTIC_DRUGS
from clinosim.modules.hai import HAI_TYPES
from clinosim.types.antibiotic import AntibioticRegimen
from clinosim.types.encounter import MedicationAdministration
from clinosim.types.hai import HAIEvent

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"
_HAI_EMPIRICAL_YAML = _REF_DIR / "hai_empirical.yaml"


FREQ_PER_DAY: dict[str, int] = {
    "q24h": 1,
    "q12h": 2,
    "q8h":  3,
    "q6h":  4,
    "q4h":  6,
}


@lru_cache(maxsize=1)
def load_hai_empirical() -> dict[str, dict[str, Any]]:
    """Load + validate empirical regimens.

    Returns ``{hai_type: {"duration_days": int, "drugs": [{"drug_key", "dose",
    "route", "frequency"}, ...]}}``. Raises ``ValueError`` at import time if
    keys violate ``HAI_TYPES`` or any drug_key violates ``ANTIBIOTIC_DRUGS``.
    """
    raw = yaml.safe_load(_HAI_EMPIRICAL_YAML.read_text(encoding="utf-8"))
    data = dict(raw["hai_empirical"])

    unknown_hai = set(data) - set(HAI_TYPES)
    if unknown_hai:
        raise ValueError(
            f"hai_empirical.yaml has unknown hai_type keys "
            f"{sorted(unknown_hai)} - must use HAI_TYPES {HAI_TYPES} "
            f"(case-sensitive)"
        )

    for hai_type, cfg in data.items():
        for drug in cfg["drugs"]:
            if drug["drug_key"] not in ANTIBIOTIC_DRUGS:
                raise ValueError(
                    f"hai_empirical.yaml [{hai_type}]: unknown drug_key "
                    f"{drug['drug_key']!r} - must be in canonical "
                    f"ANTIBIOTIC_DRUGS {ANTIBIOTIC_DRUGS}"
                )

    return data


def _drug_slug(drug_key: str) -> str:
    """canonical drug_key -> URL-safe slug for regimen_id."""
    return drug_key.lower().replace("/", "_")


def build_regimens(
    hai_event: HAIEvent,
    start_datetime: datetime,
) -> list[AntibioticRegimen]:
    """Build the empirical regimens for one HAI event.

    Returns one AntibioticRegimen per drug in the HAI type's empirical
    config. Raises ``KeyError`` if hai_event.hai_type is not present
    in hai_empirical.yaml (already gated by load_hai_empirical's
    import-time validation, so this is defense-in-depth).
    """
    cfg = load_hai_empirical()[hai_event.hai_type]
    duration_days = int(cfg["duration_days"])
    out: list[AntibioticRegimen] = []
    for drug in cfg["drugs"]:
        slug = _drug_slug(drug["drug_key"])
        out.append(AntibioticRegimen(
            regimen_id=f"abx-{hai_event.hai_id}-{slug}",
            hai_event_id=hai_event.hai_id,
            encounter_id=hai_event.encounter_id,
            drug_key=drug["drug_key"],
            dose=drug["dose"],
            route=drug["route"],
            frequency=drug["frequency"],
            start_datetime=start_datetime,
            duration_days=duration_days,
            intent="empirical",
        ))
    return out


def generate_mar_doses(
    regimen: AntibioticRegimen,
    snapshot_datetime: datetime,
    order_id: str,
) -> list[MedicationAdministration]:
    """Materialize per-dose MAR records spanning [start_dt, start_dt + duration_days).

    Doses are evenly spaced (24h / freq_per_day) starting at
    ``regimen.start_datetime``. Doses after ``snapshot_datetime`` are
    truncated (AD-32). Raises ``KeyError`` if ``regimen.frequency``
    is not in ``FREQ_PER_DAY``.
    """
    freq = FREQ_PER_DAY[regimen.frequency]
    spacing = timedelta(hours=24 // freq)
    total_doses = regimen.duration_days * freq
    out: list[MedicationAdministration] = []
    for i in range(total_doses):
        sched = regimen.start_datetime + spacing * i
        if sched > snapshot_datetime:
            break
        out.append(MedicationAdministration(
            order_id=order_id,
            drug_name=ANTIBIOTIC_DRUGS.get(regimen.drug_key, {}).get(
                "name", regimen.drug_key
            ),
            scheduled_datetime=sched,
            actual_datetime=sched,
            status="given",
            dose=regimen.dose,
            route=regimen.route,
        ))
    return out
