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


@pytest.mark.unit
class TestRunExports:
    def test_runs_requested_adapters_and_skips_cif(self, tmp_path):
        from clinosim.simulator.cli import _run_exports

        calls = []

        class RecordingAdapter:
            format_id = "rec"
            description = "recording"
            subdir = "rec"

            def convert(self, cif_dir, out_dir, ctx):
                calls.append((cif_dir, out_dir, ctx.country))

        register_output_adapter(RecordingAdapter())
        _run_exports(
            formats=["cif", "rec"],
            cif_dir=str(tmp_path / "cif"),
            output_root=str(tmp_path),
            country="JP",
            narrative_version="v1",
        )
        assert len(calls) == 1
        assert calls[0][1].endswith("/rec")
        assert calls[0][2] == "JP"

    def test_fhir_alias_resolves(self, tmp_path):
        from clinosim.simulator.cli import _run_exports

        seen = []

        class FhirSpy:
            format_id = "fhir-r4"
            description = "spy"
            subdir = "fhir_r4"

            def convert(self, cif_dir, out_dir, ctx):
                seen.append(out_dir)

        register_output_adapter(FhirSpy())  # replaces builtin for this test
        _run_exports(["fhir"], str(tmp_path / "cif"), str(tmp_path), "US", "")
        assert seen and seen[0].endswith("/fhir_r4")

    def test_unknown_format_raises_valueerror(self, tmp_path):
        from clinosim.simulator.cli import _run_exports

        with pytest.raises(ValueError, match="Unknown output format"):
            _run_exports(["nope"], str(tmp_path / "cif"), str(tmp_path), "US", "")


@pytest.mark.unit
class TestExportFhirRoutesThroughRegistry:
    def test_export_fhir_uses_adapter(self, tmp_path):
        from argparse import Namespace

        import clinosim.simulator.cli as cli

        seen = {}

        class FhirSpy:
            format_id = "fhir-r4"
            description = "spy"
            subdir = "fhir_r4"

            def convert(self, cif_dir, out_dir, ctx):
                seen["out_dir"] = out_dir
                seen["country"] = ctx.country
                seen["nv"] = ctx.narrative_version

        register_output_adapter(FhirSpy())

        cif_dir = tmp_path / "cif"
        (cif_dir / "structural" / "patients").mkdir(parents=True)
        args = Namespace(
            cif_dir=str(cif_dir),
            output=str(tmp_path / "out"),
            country="JP",
            narrative_version="v2",
        )
        cli._run_export_fhir(args)
        assert seen["country"] == "JP"
        assert seen["nv"] == "v2"
        assert seen["out_dir"].endswith("/fhir_r4")
