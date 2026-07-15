"""Contract test: a brand-new output format plugs in via the registry with no core edits."""

import json
from pathlib import Path

import pytest

from clinosim.modules.output.adapter import (
    OutputContext,
    get_adapter,
    register_output_adapter,
)


class _MemoAdapter:
    """A minimal third-party-style adapter that writes one sentinel file from CIF."""

    format_id = "memo"
    description = "Sentinel memo (contract test)"
    subdir = "memo"

    def convert(self, cif_dir, out_dir, ctx: OutputContext) -> None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "memo.json").write_text(json.dumps({"cif_dir": cif_dir, "country": ctx.country}), encoding="utf-8")


@pytest.mark.integration
def test_new_format_plugs_in(tmp_path):
    register_output_adapter(_MemoAdapter())
    adapter = get_adapter("memo")
    out_dir = tmp_path / "memo"
    adapter.convert(str(tmp_path / "cif"), str(out_dir), OutputContext(country="JP"))
    data = json.loads((out_dir / "memo.json").read_text())
    assert data["country"] == "JP"
    assert (out_dir / "memo.json").exists()
