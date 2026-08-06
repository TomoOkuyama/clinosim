"""JP-CLINS package fail-loud gate (Issue #418).

Prior behavior: `clinosim generate --country JP` silently degraded to
legacy 5-digit JLAC10 OIDs when the JP-CLINS package was not installed
(no warning, no exit code). The `jp_clins_lab_compliance` axis surfaced
Outcome.NA in that state, but the generator itself gave no signal, so
downstream consumers (validators / iris4h-ai analysis / paper drafts)
would ingest non-compliant output without any indication.

Post-#418: `--country JP` + no pkg = fail-loud (exit 2) unless the
caller explicitly passes `--allow-legacy` to acknowledge the
non-compliance.

The `_enforce_jp_clins_pkg_gate` helper is the single choke point the CLI
calls; these tests exercise it directly so they don't depend on the full
`clinosim generate` argparse plumbing.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from clinosim.modules.output.lab_coding_package import MissingPackage
from clinosim.simulator.cli import _enforce_jp_clins_pkg_gate


@pytest.mark.unit
class TestEnforceJpClinsPkgGate:
    def test_pkg_absent_no_flag_exits_2(self, capsys):
        with (
            patch(
                "clinosim.modules.output.lab_coding_package.load_lab_coding_package",
                return_value=MissingPackage(),
            ),
            pytest.raises(SystemExit) as excinfo,
        ):
            _enforce_jp_clins_pkg_gate(allow_legacy=False)
        assert excinfo.value.code == 2
        err = capsys.readouterr().err
        assert "JP-CLINS package not detected" in err
        assert "--allow-legacy" in err
        # The error message must tell the caller both install paths, not
        # just one — the two paths are non-equivalent (fhir install ships
        # jpfhir-terminology too; the env var is a manual override).
        assert "fhir install clinical-information-sharing" in err
        assert "CLINOSIM_JP_CLINS_PKG_DIR" in err

    def test_pkg_absent_with_allow_legacy_warns_and_returns(self, capsys):
        with patch(
            "clinosim.modules.output.lab_coding_package.load_lab_coding_package",
            return_value=MissingPackage(),
        ):
            _enforce_jp_clins_pkg_gate(allow_legacy=True)  # must not raise
        err = capsys.readouterr().err
        assert "WARN: JP-CLINS package not detected" in err
        assert "--allow-legacy was passed" in err
        # The WARN must tell the caller their output will NOT be compliant,
        # so downstream consumers know they're getting legacy fallback.
        assert "NOT be JP-CLINS eCS compliant" in err

    def test_pkg_present_is_noop(self, capsys):
        """When the pkg IS available, the gate does nothing (no exit, no output)."""

        class _AvailablePkg:
            def is_available(self):
                return True

        with patch(
            "clinosim.modules.output.lab_coding_package.load_lab_coding_package",
            return_value=_AvailablePkg(),
        ):
            _enforce_jp_clins_pkg_gate(allow_legacy=False)  # must not raise
            _enforce_jp_clins_pkg_gate(allow_legacy=True)  # both branches noop
        assert capsys.readouterr().err == ""
