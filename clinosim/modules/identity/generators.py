"""Check-digit number generators for resident / insurance identifiers (AD-54).

Country-agnostic pure functions. Number structures follow published Japanese
specifications. Algorithms are deterministic given the rng; check-digit formulas
marked `# TODO: verify` are pending authoritative source confirmation (see TODO.md
AD-54 verification items).
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "my_number",
    "my_number_check_digit",
    "mod10_check_digit",
    "insurer_number",
    "numeric_id",
    "branch_number",
]


def my_number_check_digit(base11: list[int]) -> int:
    """Check digit for a 12-digit 個人番号 from its 11-digit base.

    Formula: 11 - ((Σ P_n·Q_n) mod 11); 0 if the remainder is 0 or 1.
      P_n = n-th digit counted from the right of the 11-digit base (n = 1..11)
      Q_n = n + 1 for 1 ≤ n ≤ 6, else n - 5
    """
    total = 0
    for n in range(1, 12):
        p = base11[11 - n]  # n-th digit from the right
        q = (n + 1) if n <= 6 else (n - 5)
        total += p * q
    r = total % 11
    return 0 if r <= 1 else 11 - r


def my_number(rng: np.random.Generator) -> str:
    """Generate a 12-digit 個人番号 with a valid check digit."""
    base = [int(rng.integers(0, 10)) for _ in range(11)]
    return "".join(str(d) for d in base) + str(my_number_check_digit(base))


def mod10_check_digit(body: str) -> int:
    """検証番号 (modulus 10, weights 2,1,2,1… from the right; product digits summed).

    Used for 保険者番号. # TODO: verify exact weighting against official spec.
    """
    total = 0
    for i, ch in enumerate(reversed(body)):
        prod = int(ch) * (2 if i % 2 == 0 else 1)
        total += prod if prod < 10 else prod - 9
    return (10 - (total % 10)) % 10


def insurer_number(houbetsu: str, prefecture: str, serial: str, *, national: bool = False) -> str:
    """Compose a 保険者番号 with a trailing 検証番号.

    Employee / late-elderly: 法別番号(2) + 都道府県(2) + 保険者別(3) + 検証(1) = 8 digits.
    National (国保): 都道府県(2) + 保険者別(3) + 検証(1) = 6 digits (no 法別番号).
    """
    serial3 = serial[-3:].zfill(3)
    body = (prefecture + serial3) if national else (houbetsu + prefecture + serial3)
    return body + str(mod10_check_digit(body))


def numeric_id(rng: np.random.Generator, width: int) -> str:
    """Generate a zero-padded numeric identifier of the given width."""
    return "".join(str(int(rng.integers(0, 10))) for _ in range(width))


def branch_number(index: int) -> str:
    """枝番 (2-digit, individual within a 被保険者 record)."""
    return f"{index:02d}"
