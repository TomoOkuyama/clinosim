"""Sibling of PR #451: `_build_discharge_rx` chronic-transcription route
must be empty (unknown), NOT "PO" hardcode.

Pre-fix state (session 73 supervisor 5v0qgryj measurement, seed=42
JP p=300 2025-2026): DC rows in `prescriptions.csv` had 21 inhaled or
subcutaneous drugs (Tiotropium inhaler, Salbutamol inhaler, ICS/LABA
inhaler, Fluticasone/Salmeterol inhaler, Sliding scale insulin) falsely
tagged with route="PO". The upstream `patient.current_medications` is a
`list[str]` (Issue #452 root) that drops route info; the transcribe
loop at `inpatient.py:2086` was papering over the loss with a "PO"
hardcode.

Post-fix expectation:
- protocol-authored DC items (via `drugs.discharge_oral` and the
  session 72 `continue_at_discharge` loop) retain their YAML-authored
  route (usually "PO"; non-PO is filtered out for `continue_at_discharge`
  entries — see `inpatient.py:2144`).
- chronic-transcription DC items receive route="" (honestly empty).

So the DC set is a mix, NOT all-empty. This test asserts:
1. chronic-transcribed drugs whose CIF item comes from
   `patient.current_medications` do NOT have route="PO" if the
   underlying drug is inhaled/subcutaneous.
2. Some DC rows keep route="PO" (protocol-authored, unchanged).

Refs #452 (root cause: `current_medications: list[str]` schema drops
route/frequency/dose) / #451 (sibling outpatient fix landed) / #445
(FHIR MedicationRequest builder Phase 2 depends on this being fixed to
avoid emitting false SNOMED PO route).
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from clinosim.modules.output.cif_writer import write_cif
from clinosim.modules.output.csv_adapter import convert_cif_to_csv
from clinosim.simulator.engine import run_beta
from clinosim.types.config import SimulatorConfig

# Inhaled / subcutaneous drug patterns that MUST NOT carry route="PO" in
# DC rows post-fix (they come exclusively from `patient.current_medications`
# via the chronic-transcribe loop and there is no protocol path that would
# rewrite them to route="PO"). Case-insensitive because the CSV drug_name
# field mixes bare names ("Sliding scale insulin") and dose-appended
# variants ("Insulin glargine ...") — the token is stable across both.
NON_ORAL_TOKENS = ("inhaler", "insulin")


@pytest.mark.integration
def test_dc_rows_chronic_transcribed_non_oral_drugs_have_no_po_route(tmp_path: Path):
    """The 21 inhaled/insulin rows measured by session 73 supervisor MUST
    have route="" (not "PO") after this PR.
    """
    cfg = SimulatorConfig(
        random_seed=42,
        catchment_population=300,
        country="JP",
        time_range=("2025-01", "2026-01"),
    )
    ds = run_beta(cfg)
    assert ds.patients

    cif_dir = tmp_path / "cif"
    csv_dir = tmp_path / "csv"
    write_cif(ds, str(cif_dir))
    convert_cif_to_csv(str(cif_dir), str(csv_dir), country="JP")

    csv_path = csv_dir / "prescriptions.csv"
    assert csv_path.is_file(), f"prescriptions.csv not produced at {csv_path}"

    dc_rows = 0
    chronic_non_oral_rows: list[dict] = []
    chronic_non_oral_with_po = 0
    with csv_path.open() as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            pid = row.get("prescription_id", "") or ""
            if not pid.endswith("-DC"):
                continue
            dc_rows += 1
            drug = (row.get("drug_name") or "").lower()
            dose = (row.get("dose") or "").strip()
            # Chronic-transcribed items originate from
            # `patient.current_medications: list[str]`, which drops dose;
            # the transcribe loop appends `dose=""`. Protocol-authored
            # items (discharge_oral / continue_at_discharge) copy dose from
            # the disease YAML and are almost always non-empty. Using
            # `dose == ""` as the chronic-transcription proxy is not
            # airtight (a YAML entry with dose omitted would also match)
            # but it isolates the exact code path this PR modifies.
            if any(tok in drug for tok in NON_ORAL_TOKENS) and not dose:
                chronic_non_oral_rows.append(row)
                if (row.get("route") or "").strip().upper() == "PO":
                    chronic_non_oral_with_po += 1

    assert dc_rows > 0, "no DC rows produced — cohort setup regressed"
    assert chronic_non_oral_rows, (
        "cohort produced 0 chronic-transcribed inhaled/insulin DC rows — "
        "the test is vacuous. Adjust seed/population until the sample is "
        "non-empty."
    )
    assert chronic_non_oral_with_po == 0, (
        f"{chronic_non_oral_with_po}/{len(chronic_non_oral_rows)} "
        f"chronic-transcribed inhaled/insulin DC rows still have "
        f'route="PO" (false oral administration claim). Regression to '
        f"pre-#PR-A0 behavior. Sample bad rows (first 3): "
        f"{chronic_non_oral_rows[:3]}"
    )


@pytest.mark.integration
def test_dc_rows_still_contain_protocol_authored_po_route_mix(tmp_path: Path):
    """Regression guard against over-correction: the fix must NOT make
    every DC row route-empty. Protocol-authored items (from
    `drugs.discharge_oral` and `continue_at_discharge`) still keep their
    YAML-declared route, usually "PO".
    """
    cfg = SimulatorConfig(
        random_seed=42,
        catchment_population=300,
        country="JP",
        time_range=("2025-01", "2026-01"),
    )
    ds = run_beta(cfg)
    assert ds.patients

    cif_dir = tmp_path / "cif"
    csv_dir = tmp_path / "csv"
    write_cif(ds, str(cif_dir))
    convert_cif_to_csv(str(cif_dir), str(csv_dir), country="JP")

    csv_path = csv_dir / "prescriptions.csv"
    assert csv_path.is_file()

    dc_route_po = 0
    dc_total = 0
    with csv_path.open() as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            pid = row.get("prescription_id", "") or ""
            if not pid.endswith("-DC"):
                continue
            dc_total += 1
            if (row.get("route") or "").strip().upper() == "PO":
                dc_route_po += 1

    assert dc_total > 0
    assert dc_route_po > 0, (
        f"0/{dc_total} DC rows have route='PO'. The fix over-corrected: "
        f"protocol-authored items (discharge_oral / continue_at_discharge) "
        f"should still carry PO from their YAML source. Only chronic-"
        f"transcribed items should have empty route."
    )
