"""Unit tests for the output-format adapter registry (AD-58)."""

import pytest

from clinosim.modules.output.adapter import (
    OutputAdapter,
    OutputContext,
    available_formats,
    get_adapter,
    register_output_adapter,
)


class _DummyAdapter:
    format_id = "dummy"
    description = "Dummy test adapter"
    subdir = "dummy"

    def __init__(self):
        self.calls = []

    def convert(self, cif_dir, out_dir, ctx):
        self.calls.append((cif_dir, out_dir, ctx))


@pytest.mark.unit
class TestAdapterRegistry:
    def test_register_and_get(self):
        a = _DummyAdapter()
        register_output_adapter(a)
        assert get_adapter("dummy") is a

    def test_register_is_idempotent_replace(self):
        a1, a2 = _DummyAdapter(), _DummyAdapter()
        register_output_adapter(a1)
        register_output_adapter(a2)
        assert get_adapter("dummy") is a2  # last registration wins

    def test_unknown_format_raises_keyerror(self):
        with pytest.raises(KeyError):
            get_adapter("does-not-exist")

    def test_available_formats_includes_registered(self):
        register_output_adapter(_DummyAdapter())
        ids = [fid for fid, _desc in available_formats()]
        assert "dummy" in ids

    def test_dummy_satisfies_protocol(self):
        assert isinstance(_DummyAdapter(), OutputAdapter)

    def test_output_context_defaults(self):
        ctx = OutputContext()
        assert ctx.country == "US"
        assert ctx.narrative_version == ""
        assert ctx.options == {}


@pytest.mark.unit
class TestBuiltinAdapters:
    def test_builtins_registered(self):
        ids = {fid for fid, _ in available_formats()}
        assert {"csv", "fhir-r4"} <= ids

    def test_fhir_adapter_metadata(self):
        a = get_adapter("fhir-r4")
        assert a.subdir == "fhir_r4"
        assert "FHIR" in a.description

    def test_csv_adapter_metadata(self):
        a = get_adapter("csv")
        assert a.subdir == "csv"
