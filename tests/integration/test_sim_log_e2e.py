"""Integration: end-to-end unified logging (Issues #172, #175).

Runs a tiny cohort via the `generate` CLI subcommand and asserts the
simulator log file exists, contains the expected phase-boundary INFO
events (engine + cif_writer + fhir_r4_adapter), and contains at least
one `stage_total` aggregate line per always-on POST_ENCOUNTER /
POST_RECORDS enricher.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


@pytest.mark.integration
def test_generate_writes_simulator_log_with_expected_events() -> None:
    """Run a tiny JP cohort and verify the JSONL simulator log contents."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "clinosim.simulator.cli",
                "generate",
                "--country",
                "JP",
                "--population",
                "20",
                "--seed",
                "42",
                "--format",
                "cif",
                "--output",
                str(out),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"generate failed:\n{result.stderr}"
        log_file = out / "simulator.log"
        assert log_file.exists(), f"simulator.log not created at {log_file}"

        events = [json.loads(line) for line in log_file.read_text().splitlines() if line.strip()]
        assert len(events) >= 6, f"expected several events, got {len(events)}"

        # Every JSONL event carries the schema-required keys.
        for ev in events:
            assert "ts" in ev
            assert "event" in ev
            assert "module" in ev

        # L1 phase boundaries — engine.py progress prints have paired
        # sim_log.info lines. The tiny cohort still emits every one.
        expected_engine_events = {
            "log_configured",
            "hospital_loaded",
            "population_generated",
            "life_events_generated",
            "inpatient_loop_done",
            "readmissions_done",
            "healthcare_calendar_generated",
            "outpatient_done",
            "run_beta_done",
        }
        got_events = {ev["event"] for ev in events}
        missing = expected_engine_events - got_events
        assert not missing, f"missing expected L1 events: {sorted(missing)}"

        # L2 aggregate — at least one `stage_total` line per always-on
        # POST_RECORDS enricher (allergy or nursing_flowsheets 等 always fire
        # for JP population, no gating).
        stage_totals = [ev for ev in events if ev["event"] == "stage_total"]
        assert stage_totals, "no stage_total aggregates emitted after run"
        for st in stage_totals:
            assert st["stage"] in {"post_population", "post_encounter", "post_records"}
            assert isinstance(st["calls"], int)
            assert st["calls"] >= 1
            assert isinstance(st["elapsed_s"], float)
            assert st["elapsed_s"] >= 0.0


@pytest.mark.integration
def test_generate_fhir_writes_cif_and_fhir_export_events() -> None:
    """Run a tiny JP cohort with --format fhir and verify the CIF write +
    FHIR export phase events (Issue #175) are present with the expected
    payload shape (patients / bytes_out / resources / files / elapsed_s /
    sort sub-phase)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "clinosim.simulator.cli",
                "generate",
                "--country",
                "JP",
                "--population",
                "20",
                "--seed",
                "42",
                "--format",
                "fhir",
                "--output",
                str(out),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"generate failed:\n{result.stderr}"
        log_file = out / "simulator.log"
        events = [json.loads(line) for line in log_file.read_text().splitlines() if line.strip()]
        by_event = {ev["event"]: ev for ev in events}
        # CIF write phase.
        assert "cif_write_start" in by_event, "cif_write_start missing"
        assert "cif_write_end" in by_event, "cif_write_end missing"
        cw_end = by_event["cif_write_end"]
        assert cw_end["module"] == "cif_writer"
        assert isinstance(cw_end.get("patients"), int)
        assert cw_end.get("patients", 0) >= 1
        assert isinstance(cw_end.get("bytes_out"), int)
        assert cw_end.get("bytes_out", 0) > 0
        assert isinstance(cw_end.get("elapsed_s"), float)
        # FHIR export phase.
        assert "fhir_export_start" in by_event, "fhir_export_start missing"
        assert "fhir_export_end" in by_event, "fhir_export_end missing"
        fx_end = by_event["fhir_export_end"]
        assert fx_end["module"] == "fhir_r4_adapter"
        assert isinstance(fx_end.get("patients"), int)
        assert fx_end.get("patients", 0) >= 1
        assert isinstance(fx_end.get("resources"), int)
        assert fx_end.get("resources", 0) > 0
        assert isinstance(fx_end.get("files"), int)
        assert fx_end.get("files", 0) > 0
        assert isinstance(fx_end.get("elapsed_s"), float)
        # NDJSON sort sub-phase.
        assert "ndjson_sort_start" in by_event, "ndjson_sort_start missing"
        assert "ndjson_sort_end" in by_event, "ndjson_sort_end missing"
        sort_end = by_event["ndjson_sort_end"]
        assert sort_end["module"] == "fhir_r4_adapter"
        assert isinstance(sort_end.get("elapsed_s"), float)


@pytest.mark.integration
def test_generate_writes_inpatient_loop_progress_events() -> None:
    """Issue #174: the inpatient loop emits `inpatient_loop_start`, at least
    one `inpatient_progress` at the 50-record cadence (or at final record for
    short loops), and `inpatient_loop_done` with `elapsed_s`.

    Uses `--population 300` so several inpatient events fire (~30-40 based on
    the population-level admission rate), guaranteeing at least the final
    `inpatient_progress` triggers (`idx == n_hosp - 1` branch)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "clinosim.simulator.cli",
                "generate",
                "--country",
                "JP",
                "--population",
                "300",
                "--seed",
                "42",
                "--format",
                "cif",
                "--output",
                str(out),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"generate failed:\n{result.stderr}"
        log_file = out / "simulator.log"
        events = [json.loads(line) for line in log_file.read_text().splitlines() if line.strip()]

        # start bracket event
        start = next((ev for ev in events if ev["event"] == "inpatient_loop_start"), None)
        assert start is not None, "inpatient_loop_start missing"
        assert start["module"] == "engine"
        assert isinstance(start.get("target"), int)
        assert start["target"] >= 0

        # progress events — at least one (final tick) when the loop fires
        progress = [ev for ev in events if ev["event"] == "inpatient_progress"]
        if start["target"] > 0:
            assert progress, "inpatient_progress missing despite loop having events"
            for p in progress:
                assert p["module"] == "engine"
                assert isinstance(p.get("processed"), int)
                assert isinstance(p.get("target"), int)
                assert 1 <= p["processed"] <= p["target"]
                assert isinstance(p.get("concurrent"), int)
                assert isinstance(p.get("bed_occupancy"), float)

        # done event carries elapsed_s (added by Issue #174)
        done = next((ev for ev in events if ev["event"] == "inpatient_loop_done"), None)
        assert done is not None
        assert isinstance(done.get("elapsed_s"), float)
        assert done["elapsed_s"] >= 0.0
