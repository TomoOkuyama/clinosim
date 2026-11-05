"""Integration (Issue #2608): every MedicationAdministration references the
MedicationRequest it carries out, and the reference resolves."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tests.integration._sr_helpers import find_ndjson, load_ndjson, run_generate


@pytest.mark.integration
@pytest.mark.parametrize("country", ["US", "JP"])
def test_every_administration_resolves_to_its_request(country: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate(country, 300, 42, out)
        mrs = {r["id"] for r in load_ndjson(find_ndjson(out, "MedicationRequest.ndjson"))}
        mas = load_ndjson(find_ndjson(out, "MedicationAdministration.ndjson"))
        assert mas and mrs, "no medication resources emitted"
        missing = [ma["id"] for ma in mas if not ma.get("request")]
        dangling = [
            ma["id"] for ma in mas if ma.get("request") and ma["request"]["reference"].split("/")[-1] not in mrs
        ]
        assert not missing, f"{len(missing)} MedicationAdministrations without request: {missing[:5]}"
        assert not dangling, f"{len(dangling)} dangling MedicationAdministration.request: {dangling[:5]}"
