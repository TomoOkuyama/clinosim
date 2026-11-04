"""Procedure rule tables name only real disease or ED condition ids
(Issue #2526): matching is exact, so an unknown key never fires."""

from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.modules.procedure import engine

_ROOT = Path(engine.__file__).resolve().parents[1]
_KNOWN = {p.stem for d in ("disease", "encounter") for p in (_ROOT / d / "reference_data").glob("*.yaml")}


@pytest.mark.parametrize("table", ["_PROCEDURE_RULES", "_ISSUE939_PROCEDURE_RULES"])
def test_every_rule_key_is_a_known_condition(table: str) -> None:
    unknown = sorted(
        key
        for match, _rules in getattr(engine, table)
        for key in (match if isinstance(match, list) else [match])
        if key not in _KNOWN
    )
    assert not unknown, unknown


def test_heart_failure_admissions_get_the_severe_catheter_rule() -> None:
    probs = [
        p
        for match, rules in engine._PROCEDURE_RULES
        if "heart_failure_exacerbation" in match
        for t, p in rules
        if t == "urinary_catheter"
    ]
    assert max(probs) == 0.85


def test_unknown_rule_ids_fail_at_load(tmp_path, monkeypatch) -> None:
    import clinosim.modules.procedure.engine as eng

    bad = {
        "bedside_rules": [{"diseases": ["heart_failure"], "procedures": {"urinary_catheter": 0.85}}],
        "isolated_rules": [],
    }
    monkeypatch.setattr(eng, "load_data_yaml", lambda _path: bad)
    with pytest.raises(ValueError, match="heart_failure"):
        eng._load_procedure_rules()
