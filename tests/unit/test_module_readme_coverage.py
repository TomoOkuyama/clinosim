"""Every runtime module directory must ship a README.md (session 82 hygiene).

The `clinosim/modules/` tree is the OSS-visible surface: each module is a
self-contained unit with an owner and a documented API. A missing README
is a smell — it means the module was added without the documentation gate
in `TEMPLATE_MODULE_README.md` being followed.

This test walks `clinosim/modules/` and enforces one README per package
directory. Exemptions listed below are intentional non-modules.
"""

from __future__ import annotations

from pathlib import Path

MODULES_DIR = Path(__file__).resolve().parents[2] / "clinosim" / "modules"

# Intentional non-modules living alongside real ones (build cache, shared
# helper file, etc.). Anything NOT in this set that lacks a README fails
# the test.
_NOT_A_MODULE: frozenset[str] = frozenset(
    {
        "__pycache__",
    }
)


def test_every_module_has_readme():
    missing: list[str] = []
    for child in sorted(MODULES_DIR.iterdir()):
        if not child.is_dir():
            continue
        if child.name in _NOT_A_MODULE:
            continue
        if not (child / "README.md").exists():
            missing.append(child.name)

    assert not missing, (
        f"{len(missing)} module(s) under clinosim/modules/ lack a README.md: "
        f"{missing}. Use `.github/TEMPLATE_MODULE_README.md` as the starting "
        "point. This gate prevents new modules from shipping without the "
        "documentation baseline OSS visitors depend on."
    )
