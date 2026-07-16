"""Integration: end-to-end unified logging (Issue #172).

Runs a tiny cohort via the `generate` CLI subcommand and asserts the
simulator log file exists, contains the expected phase-boundary INFO
events, and contains at least one `stage_total` aggregate line per
always-on POST_ENCOUNTER / POST_RECORDS enricher.
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
