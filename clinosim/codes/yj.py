"""YJ / HOT accessor — JP drug code formats and the YJ master (code-mapping
spec §2.2, Issue #2463).

A JP drug code's system follows its format (JP Core NamingSystem), and a YJ
code is checked against the codes of the MEDIS 医薬品HOTコードマスター that
clinosim uses (``codes/authoritative/yj_medis_hot_used.json``,
Issue #4026; the complete code system is not shipped). The drug catalog
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
_YJ_USED_CODES = Path(__file__).parent / "authoritative" / "yj_medis_hot_used.json"


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
    """The YJ codes verified against the MEDIS master. Fails loud when the
    file is missing: an empty set would silently downgrade every JP YJ
    coding to the eCS ``nocoded`` slice."""
    data = json.loads(_YJ_USED_CODES.read_text(encoding="utf-8"))
    return frozenset(c["code"] for c in data["concept"])


def is_verified_yj(code: str) -> bool:
    """True when ``code`` is a YJ code verified against the MEDIS
    医薬品HOTコードマスター: one of the codes clinosim uses, listed in
    ``codes/authoritative/yj_medis_hot_used.json`` (Issues #1220,
    #4026)."""
    return code in _verified_yj_codes()
