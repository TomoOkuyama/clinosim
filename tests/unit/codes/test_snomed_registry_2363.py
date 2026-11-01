"""Procedure, device, HAI and follow-up SNOMED codes live in the registry (Issue #2363)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.codes.snomed import snomed_display, snomed_for_phrase

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3] / "clinosim"


def _load(rel: str) -> dict:
    return yaml.safe_load((_ROOT / rel).read_text(encoding="utf-8"))


def _codes() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {
        "phrase": {str(e["snomed"]) for e in _load("codes/data/procedure-phrase-to-snomed.yaml")["entries"]},
        "device": {
            str(v["snomed_code"]) for v in _load("modules/device/reference_data/devices.yaml")["devices"].values()
        },
        "hai": {str(v["snomed"]) for v in _load("modules/hai/reference_data/hai_codes.yaml")["hai_codes"].values()},
    }
    follow = set()
    for spec in _load("locale/shared/chronic_followup.yaml").values():
        for proc in (spec or {}).get("procedures") or [] if isinstance(spec, dict) else []:
            if proc.get("snomed"):
                follow.add(str(proc["snomed"]))
    out["followup"] = follow
    return out


@pytest.mark.parametrize("source", ["phrase", "device", "hai", "followup"])
def test_every_code_is_registered_with_english(source: str) -> None:
    assert not sorted(c for c in _codes()[source] if not snomed_display(c, "en"))


def test_no_display_copies_outside_the_registry() -> None:
    assert not (_ROOT / "modules/output/fhir_r4/procedures/procedure_name_snomed.yaml").exists()
    assert "snomed_display_en" not in (_ROOT / "modules/device/reference_data/devices.yaml").read_text()
    assert "display_en" not in (_ROOT / "modules/hai/reference_data/hai_codes.yaml").read_text()


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("Albuterol 2.5 mg nebulized", "127784009"),  # was 447094002 "Alkaline chemical burn of cornea"
        ("Arm sling", "52037006"),  # was 79733001 "Amputation above-knee"
        ("Closed reduction under sedation", "86052008"),  # was 268400002 "12 lead ECG"
        ("Foley catheter", "410024004"),  # was 244042001 (not a SNOMED concept)
        ("Hemodialysis 3-4h session", "302497006"),
        ("no procedure here", None),
    ],
)
def test_snomed_for_phrase(text: str, code: str | None) -> None:
    assert snomed_for_phrase(text) == code


def test_cauti_uses_the_catheter_associated_concept() -> None:
    assert _load("modules/hai/reference_data/hai_codes.yaml")["hai_codes"]["cauti"]["snomed"] == "700372006"
    assert snomed_display("700372006", "en") == "Catheter-associated urinary tract infection"
