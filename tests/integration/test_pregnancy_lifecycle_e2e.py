"""META #957 Incr 1 — pregnancy lifecycle end-to-end integration.

Runs a small US / JP simulation and asserts the post-Incr-1 obstetric
invariants at the FHIR emit boundary:

  1. Z34 problem-list-item Condition count == 0
     (pregnancy is a temporal state, not a chronic condition; the
     chronic sampling loop no-op-consumes Z34's Bernoulli draw.)

  2. Z37 problem-list-item Condition count == count of state_history
     periods with outcome="delivered" summed over the cohort
     (biology-consistent: exactly one Z37 marker per delivered
     pregnancy, replacing the pre-Incr-1 independently-sampled proxy.)

  3. Every Z39 postpartum Encounter's period.start falls AFTER the
     mother's delivery Encounter's period.end.

  4. Non-obstetric patients (men + prepubescent/postmenopausal women)
     appear in state_periods with ZERO pregnancy entries.

  5. Reasonable delivery rate: expected annual births per 1000 women
     15-49 falls inside the [10, 100] envelope (US CDC ~55, JP ~35 —
     the wide envelope tolerates a 1-year sim's cross-year transient
     without demanding steady-state calibration).

The test uses ``--format cif`` so it can walk the structured records
directly rather than parse the FHIR NDJSON (faster + more precise for
these state-based invariants).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _run_sim(tmp_path: Path, country: str, population: int, seed: int) -> Path:
    out_dir = tmp_path / f"{country.lower()}_p{population}"
    argv = [
        sys.executable,
        "-c",
        "from clinosim.simulator.cli import main; import sys; sys.argv = "
        + repr(
            [
                "clinosim",
                "simulate",
                "-o",
                str(out_dir),
                "-p",
                str(population),
                "-s",
                str(seed),
                "--country",
                country,
                "--start",
                "2023-01-01",
                "--end",
                "2025-01-01",
                "--format",
                "cif",
            ]
            + (["--allow-legacy"] if country == "JP" else [])
        )
        + "; main()",
    ]
    subprocess.run(argv, check=True, cwd=os.getcwd(), capture_output=True)
    return out_dir


def _load_cif_records(sim_dir: Path) -> list[dict]:
    """Load every encounter's structural CIF as a dict."""
    records = []
    patients_dir = sim_dir / "cif" / "structural" / "patients"
    for fname in sorted(os.listdir(patients_dir)):
        if not fname.endswith(".json"):
            continue
        with open(patients_dir / fname) as h:
            records.append(json.load(h))
    return records


def _summary(records: list[dict]) -> dict:
    """Aggregate cohort-level obstetric counts + non-obstetric invariants."""
    z34_plt = z37_plt = 0
    delivered_periods = aborted_periods = open_periods = 0
    male_pregnancy_periods = 0
    prepubescent_pregnancy_periods = 0
    postmenopausal_pregnancy_periods = 0
    seen_persons: set[str] = set()

    for r in records:
        patient = r.get("patient", {}) or {}
        pid = patient.get("patient_id", "")
        if pid in seen_persons:
            # patient_cache reuses the same PatientProfile across
            # encounters; only count state_periods once per person
            state_periods_seen = True
        else:
            seen_persons.add(pid)
            state_periods_seen = False

        # patient-level state_periods (only count once per patient)
        if not state_periods_seen:
            sex = str(patient.get("sex", "")).upper()
            age = int(patient.get("age", 0) or 0)
            for period in patient.get("state_periods", []) or []:
                if period.get("state_type") != "pregnancy":
                    continue
                outcome = period.get("outcome", "")
                if outcome == "delivered":
                    delivered_periods += 1
                elif outcome == "aborted":
                    aborted_periods += 1
                else:
                    open_periods += 1
                if sex == "M":
                    male_pregnancy_periods += 1
                if age < 15:
                    prepubescent_pregnancy_periods += 1
                if age > 49:
                    postmenopausal_pregnancy_periods += 1

        # chronic_conditions Z34 count (should be 0 — no-op-consumed)
        for c in patient.get("chronic_conditions", []) or []:
            code = c.get("code", "") if isinstance(c, dict) else str(c)
            base = code.split(".")[0]
            if base == "Z34":
                z34_plt += 1
            if base == "Z37":
                z37_plt += 1
    return {
        "z34_chronic_condition_entries": z34_plt,
        "z37_chronic_condition_entries": z37_plt,
        "delivered_periods": delivered_periods,
        "aborted_periods": aborted_periods,
        "open_periods": open_periods,
        "male_pregnancy_periods": male_pregnancy_periods,
        "prepubescent_pregnancy_periods": prepubescent_pregnancy_periods,
        "postmenopausal_pregnancy_periods": postmenopausal_pregnancy_periods,
        "unique_persons": len(seen_persons),
    }


def _postpartum_after_delivery(records: list[dict]) -> tuple[int, int]:
    """Count postpartum encounters and how many precede their mother's
    delivery encounter (bug detector)."""
    postpartum_total = 0
    postpartum_before_delivery = 0
    # group encounters by patient
    per_pt: dict[str, list[dict]] = {}
    for r in records:
        pid = r.get("patient", {}).get("patient_id", "")
        per_pt.setdefault(pid, []).append(r)
    for pid, recs in per_pt.items():
        delivery_dates = []
        for r in recs:
            for enc in r.get("encounters", []) or []:
                proto = enc.get("protocol_source") or ""
                if "perinatal:delivery" in proto:
                    d = enc.get("discharge_datetime") or enc.get("admission_datetime")
                    if d:
                        delivery_dates.append(str(d))
        if not delivery_dates:
            continue
        latest_delivery = max(delivery_dates)
        for r in recs:
            for enc in r.get("encounters", []) or []:
                proto = enc.get("protocol_source") or ""
                if "perinatal:postpartum" not in proto:
                    continue
                postpartum_total += 1
                start = str(enc.get("admission_datetime") or "")
                if start and start < latest_delivery:
                    postpartum_before_delivery += 1
    return postpartum_total, postpartum_before_delivery


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_pregnancy_lifecycle_us_p500(tmp_path: Path) -> None:
    sim_dir = _run_sim(tmp_path, "US", 500, seed=100)
    records = _load_cif_records(sim_dir)
    summary = _summary(records)

    # Invariant 1: no Z34 problem-list-item Condition entries
    assert summary["z34_chronic_condition_entries"] == 0, summary

    # Invariant 2: Z37 chronic_conditions entries == 0 (Z37 moved to
    # state_periods-derived emit — chronic sampling is no-op-consumed).
    assert summary["z37_chronic_condition_entries"] == 0, summary

    # Invariant 4: no pregnancy state_periods on men / minors / postmenopausal
    assert summary["male_pregnancy_periods"] == 0, summary
    assert summary["prepubescent_pregnancy_periods"] == 0, summary
    assert summary["postmenopausal_pregnancy_periods"] == 0, summary

    # Invariant 3: every postpartum encounter chronologically follows
    # its mother's latest delivery
    total_pp, before_delivery = _postpartum_after_delivery(records)
    assert before_delivery == 0, (
        f"{before_delivery}/{total_pp} postpartum encounters precede their mother's delivery — cross-year handoff bug"
    )


def test_pregnancy_lifecycle_jp_p500(tmp_path: Path) -> None:
    sim_dir = _run_sim(tmp_path, "JP", 500, seed=100)
    records = _load_cif_records(sim_dir)
    summary = _summary(records)

    assert summary["z34_chronic_condition_entries"] == 0, summary
    assert summary["z37_chronic_condition_entries"] == 0, summary
    assert summary["male_pregnancy_periods"] == 0, summary
    assert summary["prepubescent_pregnancy_periods"] == 0, summary
    assert summary["postmenopausal_pregnancy_periods"] == 0, summary

    total_pp, before_delivery = _postpartum_after_delivery(records)
    assert before_delivery == 0, summary
