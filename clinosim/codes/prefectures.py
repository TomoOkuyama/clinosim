"""JIS X 0401 prefecture codes (Issue #2265).

Reads ``codes/data/jis-x-0401-prefectures.yaml``. The JP-locale FHIR Address
emit path uses :func:`prefecture_code` for the ``Address.state`` code.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml

_DATA_FILE = Path(__file__).parent / "data" / "jis-x-0401-prefectures.yaml"


@cache
def _prefecture_codes() -> dict[str, str]:
    raw = yaml.safe_load(_DATA_FILE.read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in (raw.get("prefectures") or {}).items()}


def prefecture_code(name: str) -> str:
    """The 2-digit JIS X 0401 code of a prefecture name ("東京都" → "13");
    empty when the name is not a prefecture."""
    return _prefecture_codes().get(name, "")
