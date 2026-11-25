"""The release catalog resolves codes through the functions the builders use (Issue #3763)."""

from __future__ import annotations

import argparse
import json

import pytest

from clinosim.codes.drugs import find_drug, jp_drug_code
from clinosim.modules.output.fhir_r4.lib.dosage import build_route_concept
from clinosim.modules.output.fhir_r4.medications.medications import _resolve_medication_concept
from clinosim.modules.output.fhir_r4.release_catalog import build_release_catalog, diff_catalogs, format_diff
from clinosim.simulator import cli_catalog_codes

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def catalogs() -> dict[str, list[dict]]:
    return {cc: list(build_release_catalog(cc).lines()) for cc in ("US", "JP")}


def _medication_pairs(lines: list[dict]) -> set[tuple[str, str, str | None]]:
    return {(x["system"], x["code"], x["route"]) for x in lines if x["kind"] == "medication"}


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize("name,token", [("Atorvastatin", "PO"), ("Ceftriaxone", "IV"), ("Metformin", "PO")])
def test_a_drug_and_route_resolve_as_order_emission_does(catalogs, country: str, name: str, token: str) -> None:
    """The catalog holds exactly the (system, code, route text) the order path resolves."""
    concept, _note = _resolve_medication_concept(name, "", country, route=token)
    route_text = build_route_concept(token, country)["text"]
    pairs = _medication_pairs(catalogs[country])
    for coding in concept["coding"]:
        assert (coding["system"], coding["code"], route_text) in pairs


def test_jp_product_code_follows_the_drug_catalog_by_route(catalogs) -> None:
    drug = find_drug("Atorvastatin")
    assert drug is not None
    code = jp_drug_code("Atorvastatin", "PO")
    assert code
    assert any(c == code and r == "経口" for _s, c, r in _medication_pairs(catalogs["JP"]))


def test_release_lines_have_the_dataset_format_without_usage_fields(catalogs) -> None:
    for country, lines in catalogs.items():
        assert lines, country
        for line in lines:
            assert line["system"] and line["code"], line
            assert "count" not in line and "patients" not in line
            assert ("route" in line) == (line["kind"] == "medication")
        keys = [(x["kind"], x["resource"], x["element"], x["system"], x["code"], x.get("route")) for x in lines]
        assert len(keys) == len(set(keys)), "one line per code"


def test_imaging_codes_follow_the_country_profile(catalogs) -> None:
    """A JP ImagingStudy omits procedureCode, so only the US lists imaging codes."""
    assert any(x["kind"] == "imaging" for x in catalogs["US"])
    assert not any(x["kind"] == "imaging" for x in catalogs["JP"])


def test_the_cli_writes_the_catalog_and_its_difference(tmp_path, catalogs) -> None:
    out = tmp_path / "codes.ndjson"
    previous = tmp_path / "previous.ndjson"
    lines = catalogs["US"]
    dropped = lines[0]
    changed = dict(lines[1], display="Another name")
    previous.write_text(
        "".join(json.dumps(x) + "\n" for x in [dict(lines[2], code="NEW-ONLY"), changed, *lines[3:]]),
        encoding="utf-8",
    )
    diff_md = tmp_path / "diff.md"
    args = argparse.Namespace(
        country="US", output=str(out), previous=str(previous), diff_label="v0.0.1", diff_output=str(diff_md)
    )
    cli_catalog_codes.run(args, argparse.ArgumentParser())
    written = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert len(written) == len(lines)
    text = diff_md.read_text(encoding="utf-8")
    assert "US code catalog changes since v0.0.1" in text
    assert dropped["code"] in text


def test_diff_reports_added_removed_and_changed() -> None:
    base = {"kind": "lab", "resource": "Observation", "element": "code", "system": "s", "code": "1", "display": "A"}
    old = [base, dict(base, code="2")]
    new = [dict(base, display="B"), dict(base, code="3")]
    diff = diff_catalogs(old, new)
    assert [x["code"] for x in diff["added"]] == ["3"]
    assert [x["code"] for x in diff["removed"]] == ["2"]
    assert [(o["display"], n["display"]) for o, n in diff["changed"]] == [("A", "B")]
    assert "display: A -> B" in format_diff("US", "v1", diff)
