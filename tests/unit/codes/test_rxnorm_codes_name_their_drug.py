"""Every shipped RxCUI is current and names the drug it is mapped from (Issue #2150).

Checked offline against ``codes/authoritative/rxnorm_rxnav_snapshot.json``
(RxNav status / name / term type for every RxCUI in ``rxnorm.yaml``,
``drugs.yaml`` and the US drug mapping). A code that does not exist
(naloxone 7771), is not current (sliding-scale insulin 5856) or names
another drug (losartan 10156 = sucralfate) fails here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3]
_SNAPSHOT = _ROOT / "clinosim/codes/authoritative/rxnorm_rxnav_snapshot.json"

# clinosim display name → a word of the RxNorm name, for synonyms, brands and
# class terms that share no word with the RxNorm concept name.
_SYNONYMS: dict[str, str] = {
    "5-FU": "fluorouracil",
    "BCG": "tice",
    "BCG Vaccine": "tice",
    "Broad spectrum antibiotic": "piperacillin",
    "Buscopan": "butylscopolamine",
    "Buscopan 10mg": "butylscopolamine",
    "Buscopan 20mg": "butylscopolamine",
    "Crystalloid": "sodium",
    "Hypertonic Saline": "sodium",
    "Hypertonic Saline 23.4%": "sodium",
    "Hypertonic saline": "sodium",
    "Hypertonic saline 3%": "sodium",
    "ICS/LABA inhaler": "fluticasone",
    "IV normal saline": "sodium",
    "IV normal saline 1000mL": "sodium",
    "IV normal saline 1L": "sodium",
    "IV normal saline 500mL": "sodium",
    "KCl": "potassium",
    "Lactated Ringer": "lactate",
    "Lactated Ringer solution": "lactate",
    "Leuprorelin": "leuprolide",
    "NS": "sodium",
    "Nebulized Salbutamol": "albuterol",
    "Nebulized salbutamol": "albuterol",
    "Nebulized salbutamol 2.5mg": "albuterol",
    "Normal Saline": "sodium",
    "Phytonadione": "vitamin",
    "Salbutamol": "albuterol",
}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{4,}", str(text).lower()))


def _shipped_pairs() -> list[tuple[str, str, str]]:
    pairs: list[tuple[str, str, str]] = []
    rx = yaml.safe_load((_ROOT / "clinosim/codes/data/rxnorm.yaml").read_text(encoding="utf-8"))["codes"]
    pairs += [("rxnorm.yaml", str(v.get("en")), str(c)) for c, v in rx.items()]
    drugs = yaml.safe_load((_ROOT / "clinosim/codes/data/drugs.yaml").read_text(encoding="utf-8"))["drugs"]
    pairs += [
        ("drugs.yaml", str(v["names"]["en"]), str(v["codes"]["rxnorm"]))
        for v in drugs.values()
        if isinstance(v, dict) and (v.get("codes") or {}).get("rxnorm")
    ]
    us = yaml.safe_load((_ROOT / "clinosim/locale/us/code_mapping_drug.yaml").read_text(encoding="utf-8"))
    pairs += [("us_mapping", str(k), str(v)) for k, v in us.items()]
    return pairs


def test_every_rxcui_is_current_and_names_its_drug() -> None:
    snapshot = {c["code"]: c for c in json.loads(_SNAPSHOT.read_text(encoding="utf-8"))["concept"]}
    problems = []
    for source, name, code in _shipped_pairs():
        concept = snapshot.get(code)
        if concept is None:
            problems.append(f"{source}: {name} {code} missing from the RxNav snapshot")
            continue
        if concept["status"] != "Active":
            problems.append(f"{source}: {name} {code} is {concept['status']}")
            continue
        rx_words = _words(concept["name"])
        if not (_words(name) & rx_words) and _SYNONYMS.get(name) not in rx_words:
            problems.append(f"{source}: {name} {code} = {concept['name']}")
    assert not problems, "\n".join(problems)
