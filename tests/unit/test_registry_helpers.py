"""Unit tests for the AD-56 registry helpers (EXT-1 / EXT-3 / EXT-8).

- bundle-builder registry: name-based dedup + available_builders() introspection
- enricher registry: dict[str, Enricher] with last-wins override (+ warning)
"""

import pytest

from clinosim.modules.output import fhir_r4_adapter as fa
from clinosim.simulator import enrichers as en
from clinosim.simulator.enrichers import Enricher, EnricherContext


@pytest.fixture
def restore_builders():
    saved = list(fa._BUNDLE_BUILDERS)
    yield
    fa._BUNDLE_BUILDERS[:] = saved


@pytest.fixture
def restore_enrichers():
    saved = dict(en._ENRICHERS)
    yield
    en._ENRICHERS.clear()
    en._ENRICHERS.update(saved)


@pytest.mark.unit
class TestBundleBuilderRegistry:
    def test_available_builders_lists_builtins(self):
        names = fa.available_builders()
        assert "_bb_patient" in names
        assert "_bb_labs" in names

    def test_name_based_dedup(self, restore_builders):
        # Two DISTINCT callables sharing a name (same conceptual builder) must dedup —
        # identity-check would wrongly register both.
        def _bb_test_dup(ctx):
            return []
        fa.register_bundle_builder(_bb_test_dup)
        n_after_first = fa.available_builders().count("_bb_test_dup")

        def _make():
            def _bb_test_dup(ctx):  # noqa: F811 — same __name__, different object
                return [{"resourceType": "X"}]
            return _bb_test_dup
        fa.register_bundle_builder(_make())
        assert n_after_first == 1
        assert fa.available_builders().count("_bb_test_dup") == 1


@pytest.mark.unit
class TestEnricherRegistry:
    def test_last_wins_override_with_warning(self, restore_enrichers, caplog):
        calls = []
        first = Enricher(name="dup", stage="post_records", run=lambda ctx: calls.append("first"), order=10)
        second = Enricher(name="dup", stage="post_records", run=lambda ctx: calls.append("second"), order=10)
        en.register_enricher(first)
        with caplog.at_level("WARNING"):
            en.register_enricher(second)
        # last-wins: the second registration replaces the first
        assert en._ENRICHERS["dup"].run is second.run
        # run_stage executes the override exactly once
        en.run_stage("post_records", EnricherContext(config=None, master_seed=0))
        assert calls == ["second"]
        assert any("dup" in r.message for r in caplog.records)

    def test_order_name_sort_preserved(self, restore_enrichers):
        seq = []
        en._ENRICHERS.clear()
        en.register_enricher(Enricher(name="b", stage="s", run=lambda c: seq.append("b"), order=10))
        en.register_enricher(Enricher(name="a", stage="s", run=lambda c: seq.append("a"), order=10))
        en.register_enricher(Enricher(name="z", stage="s", run=lambda c: seq.append("z"), order=5))
        en.run_stage("s", EnricherContext(config=None, master_seed=0))
        assert seq == ["z", "a", "b"]  # order 5 first, then order 10 by name (a,b)
