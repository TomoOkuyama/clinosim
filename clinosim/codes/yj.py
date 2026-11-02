"""YJ / HOT accessor — JP drug code formats and the YJ master (code-mapping
spec §2.2, Issue #2463).

A JP drug code's system follows its format (JP Core NamingSystem), and a YJ
code is checked against the national YJ CodeSystem snapshot
(``codes/authoritative/JP_MedicationCodeYJ_CS_full.json``). The drug catalog
(``clinosim.codes.drugs``) holds which product a drug has per route class and
calls this module for these authority rules.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path

__all__ = ["is_verified_yj", "jp_drug_system_key"]

_YJ12_PATTERN = re.compile(r"^\d{7}[A-Z]\d{4}$")
_YJ_FULL_CS = Path(__file__).parent / "authoritative" / "JP_MedicationCodeYJ_CS_full.json"


def jp_drug_system_key(code: str) -> str:
    """Registry key of a JP drug code by its format (JP Core NamingSystem):
    7 / 9 / 13 digits → MEDIS ``hot7`` / ``hot9`` / ``hot13``; a 12-character
    ``\\d{7}[A-Z]\\d{4}`` code → ``yj``. Other shapes fall back to ``hot9``
    (the pre-existing emit behaviour)."""
    if code.isdigit():
        return {7: "hot7", 9: "hot9", 13: "hot13"}.get(len(code), "hot9")
    if _YJ12_PATTERN.match(code):
        return "yj"
    return "hot9"


@cache
def _verified_yj_codes() -> frozenset[str]:
    if not _YJ_FULL_CS.is_file():
        return frozenset()
    data = json.loads(_YJ_FULL_CS.read_text(encoding="utf-8"))
    return frozenset(c.get("code", "") for c in data.get("concept", []) if c.get("code"))


def is_verified_yj(code: str) -> bool:
    """True when ``code`` is in the JP national YJ CodeSystem shipped as
    ``codes/authoritative/JP_MedicationCodeYJ_CS_full.json`` (MEDIS-sourced,
    content=complete; Issue #1220)."""
    return code in _verified_yj_codes()
