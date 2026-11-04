"""Every random generator in clinosim comes from ``clinosim.determinism``
(Issue #2529): its proxy draws ``normal`` / ``standard_normal`` / ``beta`` /
``exponential`` bit-reproducibly across CPU architectures, and delegates
every other method to the same numpy generator."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numpy as np

from clinosim import determinism
from clinosim.seeding import text_seed

_PKG = Path(__file__).resolve().parents[2] / "clinosim"


def test_no_raw_numpy_generator_outside_determinism() -> None:
    offenders = [
        f"{p.relative_to(_PKG)}:{i}"
        for p in sorted(_PKG.rglob("*.py"))
        if p.name != "determinism.py"
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"np\.random\.default_rng\(|numpy\.random\.default_rng\(", line)
    ]
    assert not offenders, offenders


def test_proxy_keeps_uniform_draws_of_the_same_seed() -> None:
    raw, proxy = np.random.default_rng(7), determinism.default_rng(7)
    assert [raw.random(), int(raw.integers(0, 100)), int(raw.choice(5))] == [
        proxy.random(),
        int(proxy.integers(0, 100)),
        int(proxy.choice(5)),
    ]


def test_standard_normal_is_the_reproducible_unit_normal() -> None:
    assert determinism.default_rng(3).standard_normal() == determinism.default_rng(3).normal(0.0, 1.0)


def test_text_seed_formula_is_pinned() -> None:
    digest = hashlib.sha256(b"newborn-hearing-screen|P1").hexdigest()
    assert text_seed("newborn-hearing-screen|P1") == int(digest, 16) % (2**32)
