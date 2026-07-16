"""Unified structured logging for simulator + enrichers + module builders.

Emits JSONL-formatted events to a text log so a running generation can be
tailed live (`tail -f simulator.log | jq -c ...`) and a completed run can
be profiled mechanically (jq / pandas one-liner over the file).

Three information levels — the caller chooses via `CLINOSIM_LOG_LEVEL` or
programmatically via :func:`configure`:

- **L1 (INFO)** — top-level phase boundaries (population spawn, calendar,
  inpatient loop, post-records enrichers, FHIR export). Answers "where is
  the run now?" and "is it stalled?" from a `tail -f`.
- **L2 (INFO)** — per-`(stage, enricher)` aggregate wall-clock and call
  count, flushed once per simulation run via :func:`flush_stage_totals`.
  Answers "which enricher is slow across a p=10000 run?" with `jq`.
- **L3 (DEBUG)** — per-invocation events (one line per `run_stage` call
  into an enricher). Opt-in only — a p=10000 JP run emits ~200k
  invocations and would blow up the log otherwise.

Determinism (AD-16): the log file is written OUTSIDE of the FHIR NDJSON
surface hashed by `scripts/reproduce.sh`, so timestamps here do not affect
the byte-identical output invariant. Only `<output-dir>/fhir_r4/*.ndjson`
is hashed; the log is at `<output-dir>/simulator.log` by default.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_LOGGER_NAME = "clinosim.sim"
_DEFAULT_LEVEL = "INFO"


class _JsonlFormatter(logging.Formatter):
    """One JSON object per log line — schema is whatever the caller passes
    to :func:`info` / :func:`phase` (`ts`, `module`, `event`, plus any
    ``**fields``). No FormatterError on missing keys — every payload is a
    self-contained dict."""

    def format(self, record: logging.LogRecord) -> str:
        payload = record.msg
        if not isinstance(payload, dict):
            payload = {"event": "raw", "message": str(payload)}
        return json.dumps(payload, ensure_ascii=False, default=str)


def _logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)


def configure(log_file: str | Path | None, level: str | None = None) -> None:
    """Attach a `RotatingFileHandler` writing JSONL to *log_file*.

    Idempotent — reconfiguring replaces prior handlers on the clinosim
    logger only (does NOT touch the root logger). ``log_file=None``
    detaches the file handler (test / library-use case).

    Level is resolved as (in order): explicit *level* arg > env var
    ``CLINOSIM_LOG_LEVEL`` > default ``INFO``.
    """
    lg = _logger()
    for handler in list(lg.handlers):
        lg.removeHandler(handler)
    lg.propagate = False
    resolved = (level or os.environ.get("CLINOSIM_LOG_LEVEL") or _DEFAULT_LEVEL).upper()
    lg.setLevel(getattr(logging, resolved, logging.INFO))
    if log_file is None:
        return
    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    from logging.handlers import RotatingFileHandler

    handler = RotatingFileHandler(
        path,
        maxBytes=64 * 1024 * 1024,  # 64 MB per rotated file
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(_JsonlFormatter())
    lg.addHandler(handler)
    _emit(logging.INFO, module="simulator", event="log_configured", log_file=str(path), level=resolved)


def _emit(_lvl: int, /, **fields: Any) -> None:
    """Emit a JSONL line at the given severity. The leading `_lvl` is
    positional-only so caller keyword `level=...` is preserved as a
    payload field (a common collision when the event itself carries a
    logging level in its data — e.g. `log_configured` emitting the
    configured level name)."""
    payload = {"ts": time.time(), **fields}
    _logger().log(_lvl, payload)


def info(module: str, event: str, **fields: Any) -> None:
    """L1 / L2 event — a single structured line."""
    _emit(logging.INFO, module=module, event=event, **fields)


def debug(module: str, event: str, **fields: Any) -> None:
    """L3 event — per-invocation trace, off by default."""
    _emit(logging.DEBUG, module=module, event=event, **fields)


@contextmanager
def phase(module: str, event: str, _lvl: int = logging.INFO, **fields: Any) -> Any:
    """Emit ``{event}_start`` on entry and ``{event}_end`` with ``elapsed_s``
    on exit. Timing uses :func:`time.perf_counter`, log timestamp uses
    :func:`time.time`.

    Use for a bounded phase whose start/end you want to correlate. For
    per-enricher aggregation across many invocations, use
    :func:`record_stage_call` + :func:`flush_stage_totals` instead.
    """
    t0 = time.perf_counter()
    _emit(_lvl, module=module, event=f"{event}_start", **fields)
    try:
        yield
    finally:
        elapsed = time.perf_counter() - t0
        _emit(_lvl, module=module, event=f"{event}_end", elapsed_s=round(elapsed, 3), **fields)


# --- Per-(stage, module) aggregate ---
#
# POST_ENCOUNTER enrichers fire per encounter — a p=10000 JP run drives
# ~200k enricher invocations. Emitting one INFO line per call would flood
# the log; instead we accumulate (call count, total elapsed) per
# (stage, module) key and emit one summary line per pair via
# `flush_stage_totals()`.

_stage_totals: dict[tuple[str, str], tuple[int, float]] = defaultdict(lambda: (0, 0.0))


def record_stage_call(stage: str, module: str, elapsed_s: float) -> None:
    """Add one call's wall-clock to the running per-(stage, module) total.

    Called by the enricher dispatch wrapper — modules do not call this
    directly.
    """
    calls, total = _stage_totals[(stage, module)]
    _stage_totals[(stage, module)] = (calls + 1, total + elapsed_s)


def flush_stage_totals() -> None:
    """Emit one INFO event per (stage, module) with total calls, total
    wall-clock, and average per-call. Resets the accumulator.

    Called once per simulation run — typically at the tail of `run_beta`
    just before FHIR export.
    """
    for (stage, module), (calls, total) in sorted(_stage_totals.items()):
        avg = total / calls if calls else 0.0
        rate = calls / total if total > 0 else 0.0
        _emit(
            logging.INFO,
            module=module,
            event="stage_total",
            stage=stage,
            calls=calls,
            elapsed_s=round(total, 3),
            avg_s=round(avg, 6),
            rate_per_s=round(rate, 2),
        )
    _stage_totals.clear()


def reset_for_test() -> None:
    """Detach handlers and clear the accumulator — test helper only."""
    lg = _logger()
    for handler in list(lg.handlers):
        lg.removeHandler(handler)
    _stage_totals.clear()
