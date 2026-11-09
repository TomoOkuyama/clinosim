"""The oxygen-delivery device is a coded concept, never an internal key
(Issue #3023).

The vital-sign Observation's device component carried the internal key
(``nasal_cannula``). It is now a SNOMED CT device concept (codes verified on
tx.fhir.org) with the SNOMED display in the coding and the clinical label
in the output language in ``text`` (nasal cannula / 鼻カニューラ); narratives
use the same label.
"""

from __future__ import annotations

import pytest

from clinosim.codes import display
from clinosim.codes.snomed import snomed_map
from clinosim.locale.loader import oxygen_device_label
from clinosim.modules.document.narrative._replacement_localization import localize_oxygen_device
from clinosim.modules.output.fhir_r4.labs.observations import _build_vital_observations

pytestmark = pytest.mark.unit

# The keys the vitals pipeline writes (vitals_pipeline._o2_for).
_GENERATED = ("nasal_cannula", "simple_mask", "non-rebreather")


def _device_component(device: str, country: str) -> dict:
    vs = {"on_supplemental_oxygen": True, "oxygen_flow_rate_lpm": 2, "oxygen_delivery_device": device}
    entries = _build_vital_observations(vs, "P1", 0, country, "E1")
    o2 = [e["resource"] for e in entries if e["resource"].get("component")][-1]
    return o2["component"][-1]


@pytest.mark.parametrize(("country", "text"), [("JP", "鼻カニューラ"), ("US", "nasal cannula")])
def test_a_nasal_cannula_reading_emits_the_snomed_device(country: str, text: str) -> None:
    comp = _device_component("nasal_cannula", country)
    assert "valueString" not in comp
    concept = comp["valueCodeableConcept"]
    (coding,) = concept["coding"]
    assert (coding["system"], coding["code"], coding["display"]) == (
        "http://snomed.info/sct",
        "336623009",
        "Oxygen nasal cannula",
    )
    assert concept["text"] == text


@pytest.mark.parametrize("device", _GENERATED)
@pytest.mark.parametrize("country", ["JP", "US"])
def test_no_device_value_is_a_key(device: str, country: str) -> None:
    concept = _device_component(device, country)["valueCodeableConcept"]
    assert concept["text"] not in snomed_map("oxygen_device")
    assert "_" not in concept["text"]


def test_every_device_key_has_an_english_and_japanese_label() -> None:
    devices = snomed_map("oxygen_device")
    assert set(_GENERATED) <= set(devices)
    for key, code in devices.items():
        assert display("snomed-ct", code, "en"), key
        assert display("snomed-ct", code, "ja"), key


def test_every_device_key_has_a_clinical_label() -> None:
    for key in snomed_map("oxygen_device"):
        assert oxygen_device_label(key, "en") and oxygen_device_label(key, "ja"), key


@pytest.mark.parametrize(
    ("device", "en", "ja"),
    [
        ("nasal_cannula", "nasal cannula", "鼻カニューラ"),
        ("simple_mask", "simple face mask", "酸素マスク"),
        ("non-rebreather", "non-rebreather mask", "リザーバー付き酸素マスク"),
        ("HFNC", "high-flow nasal cannula", "ハイフローネーザルカニューラ"),
        ("venturi", "Venturi mask", "ベンチュリーマスク"),
        ("BiPAP", "BiPAP", "BiPAP"),
        ("ventilator", "ventilator", "人工呼吸器"),
    ],
)
def test_narratives_and_fhir_use_the_same_clinical_label(device: str, en: str, ja: str) -> None:
    assert (localize_oxygen_device(device, "en"), localize_oxygen_device(device, "ja")) == (en, ja)
    for country, label in (("US", en), ("JP", ja)):
        concept = _device_component(device, country)["valueCodeableConcept"]
        assert concept["text"] == label
        assert concept["coding"][0]["display"] == display("snomed-ct", snomed_map("oxygen_device")[device], "en")
