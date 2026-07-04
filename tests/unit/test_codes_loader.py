"""Unit tests for clinosim.codes.loader's system_key_for (kind -> code-system-key)."""

from __future__ import annotations

import pytest

from clinosim.codes import system_key_for


@pytest.mark.unit
class TestSystemKeyFor:
    def test_microbiology_jp(self):
        assert system_key_for("microbiology", "JP") == "jlac10"

    def test_microbiology_us(self):
        assert system_key_for("microbiology", "US") == "loinc"

    def test_microbiology_case_insensitive(self):
        assert system_key_for("microbiology", "jp") == "jlac10"

    def test_unknown_kind_raises(self):
        with pytest.raises(KeyError):
            system_key_for("not_a_real_kind", "JP")
