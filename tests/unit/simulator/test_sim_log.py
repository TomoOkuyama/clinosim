"""Unit tests for clinosim.simulator.log — the unified structured logger.

Covers:
- JSONL format: one JSON object per line, `ts` / `module` / `event`
  fields always present.
- `phase` context manager emits paired `_start` / `_end` events with
  `elapsed_s`.
- Per-`(stage, module)` accumulator sums call count + elapsed and emits
  one aggregate INFO line per pair on `flush_stage_totals`.
- Level filter: DEBUG events are dropped when level is INFO.
- Unicode safety: Japanese-labeled fields survive round-trip through the
  JSONL formatter.
- No handler after `reset_for_test`.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from clinosim.simulator import log as sim_log


@pytest.fixture(autouse=True)
def _reset_logger():
    sim_log.reset_for_test()
    yield
    sim_log.reset_for_test()


def _read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_configure_writes_jsonl_with_config_event(tmp_path: Path) -> None:
    log_file = tmp_path / "simulator.log"
    sim_log.configure(log_file, level="INFO")
    events = _read_lines(log_file)
    assert len(events) == 1
    assert events[0]["event"] == "log_configured"
    assert events[0]["log_file"] == str(log_file)
    assert events[0]["level"] == "INFO"
    assert "ts" in events[0]


def test_info_event_emits_single_jsonl_line(tmp_path: Path) -> None:
    log_file = tmp_path / "sim.log"
    sim_log.configure(log_file, level="INFO")
    sim_log.info("engine", "population_generated", persons=1234, catchment=40000)
    events = _read_lines(log_file)
    # events[0] = log_configured, events[1] = the info event under test.
    ev = events[1]
    assert ev == {
        **{k: ev[k] for k in ("ts",)},
        "ts": ev["ts"],
        "module": "engine",
        "event": "population_generated",
        "persons": 1234,
        "catchment": 40000,
    }


def test_phase_emits_paired_start_end_with_elapsed(tmp_path: Path) -> None:
    log_file = tmp_path / "sim.log"
    sim_log.configure(log_file, level="INFO")
    with sim_log.phase("hai", "cohort_walk", records=500):
        pass
    events = _read_lines(log_file)
    start = next(e for e in events if e["event"] == "cohort_walk_start")
    end = next(e for e in events if e["event"] == "cohort_walk_end")
    assert start["module"] == "hai"
    assert start["records"] == 500
    assert end["module"] == "hai"
    assert end["records"] == 500
    assert "elapsed_s" in end
    assert end["elapsed_s"] >= 0.0


def test_debug_event_dropped_at_info_level(tmp_path: Path) -> None:
    log_file = tmp_path / "sim.log"
    sim_log.configure(log_file, level="INFO")
    sim_log.debug("hai", "per_encounter", encounter_id="ENC-1")
    events = _read_lines(log_file)
    # Only log_configured survives at INFO — the debug event is filtered.
    assert all(e["event"] != "per_encounter" for e in events)


def test_debug_event_captured_at_debug_level(tmp_path: Path) -> None:
    log_file = tmp_path / "sim.log"
    sim_log.configure(log_file, level="DEBUG")
    sim_log.debug("hai", "per_encounter", encounter_id="ENC-1")
    events = _read_lines(log_file)
    assert any(e["event"] == "per_encounter" and e["encounter_id"] == "ENC-1" for e in events)


def test_stage_totals_accumulate_and_flush(tmp_path: Path) -> None:
    log_file = tmp_path / "sim.log"
    sim_log.configure(log_file, level="INFO")
    sim_log.record_stage_call("post_encounter", "hai", 0.5)
    sim_log.record_stage_call("post_encounter", "hai", 0.25)
    sim_log.record_stage_call("post_encounter", "antibiotic", 1.0)
    sim_log.flush_stage_totals()
    events = _read_lines(log_file)
    totals = [e for e in events if e["event"] == "stage_total"]
    by_module = {e["module"]: e for e in totals}
    assert by_module["hai"]["calls"] == 2
    assert by_module["hai"]["elapsed_s"] == 0.75
    assert by_module["antibiotic"]["calls"] == 1
    assert by_module["antibiotic"]["elapsed_s"] == 1.0
    # Aggregate should carry the stage back so `jq` filters can split by stage.
    assert by_module["hai"]["stage"] == "post_encounter"


def test_flush_stage_totals_is_idempotent(tmp_path: Path) -> None:
    """A second flush after the first should emit no additional events —
    the accumulator resets on flush."""
    log_file = tmp_path / "sim.log"
    sim_log.configure(log_file, level="INFO")
    sim_log.record_stage_call("post_records", "immunization", 0.1)
    sim_log.flush_stage_totals()
    events_first = _read_lines(log_file)
    sim_log.flush_stage_totals()
    events_second = _read_lines(log_file)
    assert len(events_first) == len(events_second)


def test_unicode_field_survives_jsonl_roundtrip(tmp_path: Path) -> None:
    log_file = tmp_path / "sim.log"
    sim_log.configure(log_file, level="INFO")
    sim_log.info("engine", "population_generated", note="日本語ラベル")
    events = _read_lines(log_file)
    ev = next(e for e in events if e["event"] == "population_generated")
    assert ev["note"] == "日本語ラベル"


def test_reset_for_test_detaches_all_handlers() -> None:
    lg = logging.getLogger("clinosim.sim")
    sim_log.configure("/tmp/does-not-matter.log")
    assert lg.handlers, "configure should have attached at least one handler"
    sim_log.reset_for_test()
    assert not lg.handlers, "reset_for_test should have detached every handler"
