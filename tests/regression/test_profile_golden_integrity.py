"""AD-66 integrity invariant: every profile YAML has an llm-mock golden (Issue #428 F6).

Motivation
----------
`tests/regression/conftest.py::llm_mock_profile_ids` discovers profiles via
`FIXTURE_DIR.glob("*.llm-mock.golden.json")` — from the golden side, not the
profile side. That is by design (LLM golden creation is opt-in / expensive)
but it creates a silent-skip risk: adding a new profile YAML without also
bootstrapping the llm-mock golden means the llm-mock regression leg is
never parametrized for that profile, and `pytest -m regression` finds
nothing to run against it.

The template leg is protected because `profile_ids()` reads from `*.yaml`
and `test_profile_narrative_byte_diff` asserts `golden_path.is_file()` —
missing golden fails loud. The llm-mock leg has no such assertion.

This test closes the gap by measuring the two discovery paths and failing
loud if they diverge. It runs under the regression marker so it does not
impose subprocess latency on the fast unit / integration suites — but
because it does no subprocess work of its own it costs milliseconds even
when included.

Failure recovery: run `clinosim regenerate-goldens --profile <name>
--provider mock` for each profile listed in the error message.
"""

from __future__ import annotations

import pytest

from tests.regression.conftest import llm_mock_profile_ids, profile_ids


@pytest.mark.regression
def test_every_profile_yaml_has_llm_mock_golden():
    """AD-66 rule "YAML と golden を同一 commit" applied at profile-set level.

    A profile YAML without its llm-mock golden slips past the llm-mock
    regression leg because that leg discovers via golden-existence rather
    than YAML-existence. Assert the two sets match, so a new-profile PR
    that forgets `regenerate-goldens --provider mock` fails at collection
    time instead of silently skipping the llm-mock regression protection.
    """
    yaml_ids = set(profile_ids())
    mock_ids = set(llm_mock_profile_ids())
    missing_mock = sorted(yaml_ids - mock_ids)
    orphan_mock = sorted(mock_ids - yaml_ids)
    msgs: list[str] = []
    if missing_mock:
        msgs.append(
            "profile YAML(s) with no matching *.llm-mock.golden.json — run "
            "`clinosim regenerate-goldens --profile <name> --provider mock` "
            "to bootstrap:\n  " + "\n  ".join(missing_mock)
        )
    if orphan_mock:
        msgs.append(
            "*.llm-mock.golden.json file(s) with no matching profile YAML "
            "(delete or restore the YAML):\n  " + "\n  ".join(orphan_mock)
        )
    assert not msgs, "profile / llm-mock golden mismatch (Issue #428):\n\n" + "\n\n".join(msgs)
