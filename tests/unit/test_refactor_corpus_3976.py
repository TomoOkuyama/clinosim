"""The refactoring corpus definition is valid (Issue #3976).

Static checks of ``tests/refactor_corpus/scenarios.yaml``: every scenario
names a real disease, archetype and complication, so a typo fails here and
not as a silently unforced stay in ``scripts/refactor-diff.sh``. Running the
corpus is the script's job (``run_corpus.py check`` fails when an expected
path did not fire).
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.hai import HAI_TYPES
from clinosim.types.config import ForcedComplication

_RUNNER = Path(__file__).resolve().parents[1] / "refactor_corpus" / "run_corpus.py"
_spec = importlib.util.spec_from_file_location("refactor_corpus_runner", _RUNNER)
assert _spec is not None and _spec.loader is not None
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)

SCENARIOS = runner.load_scenarios()
_FORCED_KEYS = {
    "id",
    "kind",
    "disease",
    "severity",
    "archetype",
    "patient",
    "count",
    "countries",
    "force_complications",
    "force_hai_event",
    "expect",
}
_DELIVERY_KEYS = {"id", "kind", "count", "mother_age", "delivered_at", "countries", "expect"}
_PATH = re.compile(r"^[a-z_]+(\.[A-Za-z0-9_]+)+$")


@pytest.mark.unit
def test_scenario_ids_are_unique_and_every_scenario_expects_a_path():
    ids = [s["id"] for s in SCENARIOS]
    assert len(ids) == len(set(ids))
    for s in SCENARIOS:
        assert set(s.get("expect") or {}) <= {"all", "US", "JP"}, s["id"]
        for country in runner.scenario_countries(s):
            assert country in ("US", "JP"), s["id"]
            paths = runner.expected_paths(s, country)
            assert paths, f"{s['id']} expects nothing in {country}"
            assert all(_PATH.match(p) for p in paths), (s["id"], paths)


@pytest.mark.unit
@pytest.mark.parametrize(
    "scenario", [s for s in SCENARIOS if s.get("kind", "forced") == "forced"], ids=lambda s: s["id"]
)
def test_forced_scenario_names_real_disease_archetype_and_complications(scenario):
    assert set(scenario) <= _FORCED_KEYS, set(scenario) - _FORCED_KEYS
    protocol = load_disease_protocol(scenario["disease"])
    assert scenario.get("severity") in (None, "mild", "moderate", "severe")
    if scenario.get("archetype"):
        assert scenario["archetype"] in (protocol.course_archetypes or {}), scenario["archetype"]
    names = {c["name"] for c in protocol.complications}
    for entry in scenario.get("force_complications") or []:
        assert ForcedComplication(**entry).name in names, entry
    if scenario.get("force_hai_event"):
        assert scenario["force_hai_event"]["hai_type"] in HAI_TYPES


@pytest.mark.unit
def test_delivery_scenarios_have_only_delivery_keys():
    deliveries = [s for s in SCENARIOS if s.get("kind") == "delivery"]
    assert deliveries
    for s in deliveries:
        assert set(s) <= _DELIVERY_KEYS, set(s) - _DELIVERY_KEYS


@pytest.mark.unit
def test_check_reports_a_path_that_did_not_fire(tmp_path):
    import json

    scenario = SCENARIOS[0]
    country = runner.scenario_countries(scenario)[0]
    sidecar = tmp_path / "c.json"
    sidecar.write_text(json.dumps({"country": country, "scenarios": {scenario["id"]: {}}}), encoding="utf-8")
    missing = runner.check([sidecar], SCENARIOS)
    assert missing == [f"{country}/{scenario['id']}: {p}" for p in runner.expected_paths(scenario, country)]


@pytest.mark.unit
def test_compare_ignores_wall_clock_keys_and_logs_but_not_content(tmp_path):
    import json

    a, b = tmp_path / "a", tmp_path / "b"
    for root, stamp, value in ((a, "2026-01-01T00:00:00", 1), (b, "2026-02-02T00:00:00", 1)):
        (root / "cif").mkdir(parents=True)
        (root / "cif" / "metadata.json").write_text(
            json.dumps({"generation_timestamp": stamp, "random_seed": 42}), encoding="utf-8"
        )
        (root / "simulator.log").write_text(stamp, encoding="utf-8")
        (root / "x.ndjson").write_text(str(value), encoding="utf-8")
    assert runner.compare(a, b) == []
    (b / "x.ndjson").write_text("2", encoding="utf-8")
    (b / "only.ndjson").write_text("", encoding="utf-8")
    assert runner.compare(a, b) == ["only in head: only.ndjson", "differs: x.ndjson"]
