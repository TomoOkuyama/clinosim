"""Integration-test-wide fixtures.

## Environment setup for Issue #418 fail-loud gate

`_enforce_jp_clins_pkg_gate` (in `clinosim/simulator/cli.py`) exits 2 on
`clinosim generate --country JP` when the JP-CLINS package is not detected.
Many integration tests subprocess-invoke `clinosim generate --country JP`
without the JP-CLINS package installed (they verify byte-identity /
cohort structure, not JP-CLINS compliance). Without the env override
below, all such tests would fail at the gate.

The env var is set at conftest module import so it applies to every
subprocess spawned during the integration suite (subprocesses inherit
env from the parent Python process). The dedicated
`jp-clins-lab-compliance-gate.yml` workflow separately verifies that
JP-CLINS compliance holds when the pkg IS installed, so this bypass
does not weaken the compliance guarantee.
"""

from __future__ import annotations

import os

# Issue #418: bypass the CLI fail-loud gate for integration tests that
# deliberately run without the JP-CLINS pkg (byte-diff / cohort structure
# verification). Compliance is verified separately by jp-clins-lab-
# compliance-gate.yml with the pkg env var set.
os.environ.setdefault("CLINOSIM_ALLOW_LEGACY_JP_CLINS_PKG", "1")
