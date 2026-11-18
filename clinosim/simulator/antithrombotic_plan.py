"""Antithrombotic plan of a stroke stay (Issue #3277).

A protocol's ``antithrombotic_plan`` (``DiseaseProtocol.antithrombotic_plan``)
names its antiplatelet and anticoagulant ``drugs`` blocks, the chronic
conditions that indicate an oral anticoagulant, and the in-stay start days by
country and severity. This module turns it into

- the steps of one day of the stay (:func:`steps_for_day`): start or stop an
  agent, executed by the daily loop; and
- the drugs of the discharge prescription (:func:`discharge_specs`), so the
  discharge regimen continues the in-stay one: an anticoagulant for a patient
  with an indication, otherwise aspirin (plus clopidogrel for a minor stroke),
  never both for the same indication.

Nothing here draws from a random stream: the anticoagulant of a stay is chosen
by a hash of the patient and encounter ids, the same choice in the stay and at
discharge.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from clinosim import determinism
from clinosim.codes.drugs import drug_key
from clinosim.modules.disease.protocol import AntithromboticPlanSpec, DiseaseProtocol
from clinosim.types.patient import PatientProfile

_ANTICOAGULANT_CLASSES = frozenset({"anticoagulant.doac", "anticoagulant.vka"})


@dataclass(frozen=True)
class PlanStep:
    """One action of the plan on one day: ``start`` an agent (``spec`` is its
    drug entry, the in-stay dose with its loading dose) or ``stop`` it."""

    action: str
    spec: dict[str, Any]


def _classes(drug_name: str) -> set[str]:
    from clinosim.modules import drug_safety

    return set(drug_safety.resolve_classes(drug_name) or ())


def _entries(protocol: DiseaseProtocol, block: str, country_key: str) -> list[dict[str, Any]]:
    entries = (protocol.drugs.get(block) or {}).get(country_key) or []
    return [entries] if isinstance(entries, dict) else [e for e in entries if isinstance(e, dict)]


def home_anticoagulant(patient: PatientProfile) -> bool:
    """True when the patient takes an oral anticoagulant at home."""
    meds = [*(patient.baseline_chronic_medications or []), *(patient.current_medications or [])]
    return any(_ANTICOAGULANT_CLASSES & _classes(m.drug_name) for m in meds if m.drug_name)


def anticoagulant_indicated(patient: PatientProfile, protocol: DiseaseProtocol, plan: AntithromboticPlanSpec) -> bool:
    """True when the patient has a chronic condition of the plan's
    ``oac_indication_codes`` (atrial fibrillation), or the protocol implies
    one (``implied_chronic_codes``, which the problem list carries for every
    patient of the disease), or takes an oral anticoagulant at home."""
    codes = [str(getattr(c, "code", c) or "") for c in patient.chronic_conditions or []]
    for code in [*codes, *protocol.implied_chronic_codes]:
        if code and any(code.startswith(prefix) for prefix in plan.oac_indication_codes):
            return True
    return home_anticoagulant(patient)


def is_dapt(plan: AntithromboticPlanSpec, severity: str) -> bool:
    """True when a stay of ``severity`` (a minor stroke) gets short-term dual
    antiplatelet therapy."""
    return severity in plan.dapt_severities


def chosen_anticoagulant(
    protocol: DiseaseProtocol, plan: AntithromboticPlanSpec, country_key: str, patient_id: str, encounter_id: str
) -> dict[str, Any] | None:
    """The anticoagulant of the stay: a hash-weighted choice among the block's
    oral entries by their ``probability`` (DOAC 0.8 / warfarin 0.2)."""
    entries = [
        e for e in _entries(protocol, plan.anticoagulant_block, country_key) if str(e.get("route", "PO")) == "PO"
    ]
    if not entries:
        return None
    ids = tuple(str(i) for i in range(len(entries)))
    weights = tuple(float(e.get("probability", 1.0)) for e in entries)
    pick = determinism.sha_weighted_choice(f"antithrombotic|{patient_id}|{encounter_id}", ids, weights)
    return entries[int(pick)]


def _antiplatelets(
    protocol: DiseaseProtocol, plan: AntithromboticPlanSpec, country_key: str, dapt: bool
) -> list[dict[str, Any]]:
    entries = _entries(protocol, plan.antiplatelet_block, country_key)
    # The second agent of DAPT is given for ``dapt_days`` only.
    return [
        {**e, "duration_days": plan.dapt_days} if e.get("dapt_addon") else e
        for e in entries
        if dapt or not e.get("dapt_addon")
    ]


def _in_stay_dose(spec: dict[str, Any]) -> dict[str, Any]:
    """The entry with its in-stay dose: the loading dose, then the maintenance
    dose ("160-300mg PO loading, then 100mg PO daily")."""
    loading = spec.get("loading_dose")
    if not loading:
        return spec
    return {**spec, "dose": f"{loading} loading, then {spec.get('dose', '')}"}


def steps_for_day(
    patient: PatientProfile,
    protocol: DiseaseProtocol,
    *,
    severity: str,
    country_key: str,
    encounter_id: str,
    day: int,
    is_running: Callable[[str], bool],
    hemorrhage: bool,
) -> list[PlanStep]:
    """The antithrombotic steps of ``day`` of the stay (empty for a protocol
    without a plan, or a day with none).

    A patient already on an oral anticoagulant at home continues it (the home
    medication order) and gets nothing more. A patient with an indication
    gets aspirin from the antiplatelet start day until the anticoagulant starts
    on the start day of the severity, then the anticoagulant alone. Every other
    patient gets aspirin, plus clopidogrel for a minor stroke. After an
    intracranial hemorrhage (hemorrhagic transformation) running agents are
    stopped and none is started. ``is_running`` tells whether a drug's order
    is running.
    """
    plan = getattr(protocol, "antithrombotic_plan", None)
    if plan is None:
        return []
    country_plan = plan.by_country.get(country_key)
    if country_plan is None:
        return []
    dapt = is_dapt(plan, severity)
    single = _antiplatelets(protocol, plan, country_key, dapt=dapt)
    anticoagulant = chosen_anticoagulant(protocol, plan, country_key, patient.patient_id, encounter_id)
    if hemorrhage:
        everything = [*single, *([anticoagulant] if anticoagulant else [])]
        return [PlanStep("stop", e) for e in everything if is_running(str(e.get("drug_id", "")))]
    if home_anticoagulant(patient):
        return []
    steps: list[PlanStep] = []
    if anticoagulant_indicated(patient, protocol, plan) and anticoagulant is not None:
        start_day = country_plan.anticoagulant_start_day[severity]
        aspirin = [e for e in single if not e.get("dapt_addon")]
        if day == country_plan.antiplatelet_start_day and day < start_day:
            steps.extend(PlanStep("start", _in_stay_dose(e)) for e in aspirin)
        if day == start_day:
            steps.extend(PlanStep("stop", e) for e in aspirin if is_running(str(e.get("drug_id", ""))))
            steps.append(PlanStep("start", anticoagulant))
        return steps
    start_day = country_plan.dapt_start_day if dapt else country_plan.antiplatelet_start_day
    if day == start_day:
        steps.extend(PlanStep("start", _in_stay_dose(e)) for e in single)
    return steps


def started_in_stay_keys(protocol: DiseaseProtocol, country_key: str) -> frozenset[str]:
    """Drug keys of the plan's antiplatelet and anticoagulant agents: one the
    patient was started on in this stay is carried to discharge by the plan,
    not by the generic transcription of the stay's new medications."""
    plan = getattr(protocol, "antithrombotic_plan", None)
    if plan is None:
        return frozenset()
    entries = [*_entries(protocol, plan.antiplatelet_block, country_key)]
    entries += _entries(protocol, plan.anticoagulant_block, country_key)
    return frozenset(drug_key(str(e.get("drug_id", ""))) for e in entries) - {""}


def discharge_specs(
    patient: PatientProfile,
    protocol: DiseaseProtocol,
    block_name: str,
    *,
    severity: str,
    country_key: str,
    encounter_id: str,
    prescribed: list[str],
) -> list[dict[str, Any]] | None:
    """The drug entries the plan gives to the discharge prescription from the
    protocol's ``block_name`` block; ``None`` when the block is not one of the
    plan's (the caller reads it as any other discharge block).

    The anticoagulant block yields the stay's anticoagulant for a patient with
    an indication (nothing when ``prescribed`` already holds an anticoagulant,
    the home one); the antiplatelet block yields aspirin, plus clopidogrel for
    a minor stroke, for a patient without one.
    """
    plan = getattr(protocol, "antithrombotic_plan", None)
    if plan is None or block_name not in (plan.antiplatelet_block, plan.anticoagulant_block):
        return None
    indicated = anticoagulant_indicated(patient, protocol, plan)
    if block_name == plan.antiplatelet_block:
        if indicated:
            return []
        return _antiplatelets(protocol, plan, country_key, dapt=is_dapt(plan, severity))
    if not indicated or any(_ANTICOAGULANT_CLASSES & _classes(name) for name in prescribed if name):
        return []
    chosen = chosen_anticoagulant(protocol, plan, country_key, patient.patient_id, encounter_id)
    return [chosen] if chosen else []
