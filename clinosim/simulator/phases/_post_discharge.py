"""Post-discharge follow-up — scheduled at discharge, dispatched on its date.

For every surviving inpatient stay (index or readmission) the forward loop
(Issue #2169) queues one follow-up visit at ``discharge + first_visit_days``
(default 14 d, ``_post_discharge`` yaml) with the same service line as the
stay — continuity of care.

RNG consumption is derive_phase_rng(master_seed, PHASE_OUTPATIENT_CAL,
opd_key) sub-seeds; no shared global generator is read.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from clinosim.seeding import PHASE_OUTPATIENT_CAL, derive_phase_rng
from clinosim.simulator._setup import _activate_cached_person
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.simulator.outpatient_dept import resolve_outpatient_department
from clinosim.types.output import CIFPatientRecord

if TYPE_CHECKING:
    from clinosim.simulator.phases._forward_loop import ForwardContext


def schedule_post_discharge(record: CIFPatientRecord, ctx: ForwardContext) -> datetime | None:
    """Follow-up visit time for a dispatched inpatient stay, or ``None``."""
    if record.deceased or not record.encounters:
        return None
    discharge = record.encounters[0].discharge_datetime
    if not discharge:
        return None
    post_dc_days = ctx.followup_data.get("_post_discharge", {}).get("first_visit_days", 14)
    return discharge + timedelta(days=post_dc_days)


def dispatch_post_discharge(record: CIFPatientRecord, followup_date: datetime, ctx: ForwardContext) -> None:
    """Simulate the follow-up visit for ``record`` on ``followup_date``."""
    pid = record.patient.patient_id
    person = ctx.population.get_person(pid)
    if not person or not person.in_population_at(followup_date.date()):
        return
    enc = record.encounters[0]
    diseases = record.condition_event.ground_truth_diseases
    disease_id = diseases[0] if diseases else ""
    post_dc_spec = ctx.followup_data.get("_post_discharge", {})
    disease_fu = ctx.followup_data.get("_post_discharge_by_disease", {}).get(disease_id, {})
    merged_spec = dict(post_dc_spec)
    if disease_fu.get("labs"):
        merged_spec["labs"] = disease_fu["labs"]
    opd_key = f"{pid}|post_discharge|{followup_date.isoformat()}"
    opd_rng = derive_phase_rng(ctx.master_seed, PHASE_OUTPATIENT_CAL, opd_key)
    opd_dept = resolve_outpatient_department("post_discharge", disease_id, enc.department_id, ctx.hospital_ops)
    ctx.patient_records.append(
        _simulate_outpatient_visit(
            _activate_cached_person(
                person,
                as_of_year=followup_date.year,
                patient_cache=ctx.patient_cache,
                master_seed=ctx.master_seed,
                demo=ctx.demo,
            ),
            "post_discharge",
            followup_date,
            ctx.roster,
            opd_rng,
            followup_spec=merged_spec,
            post_discharge_disease=disease_id,
            country=ctx.config.country,
            config=ctx.config,
            department_id=opd_dept,
        )
    )
