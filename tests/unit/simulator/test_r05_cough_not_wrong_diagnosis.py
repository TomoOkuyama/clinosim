"""Regression: R05 (a real ICD-10 code for "Cough") must NOT be treated as a
wrong-diagnosis sentinel by `inpatient.py` (Issue #551).

The engine's unresolved-diagnosis sentinel is `UNRESOLVED_DIAGNOSIS_ICD` (R69).
Previous code hardcoded `"R05"` as the sentinel, silently marking legitimate
cough presentations as `diagnosis_correct=False`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from clinosim.modules.diagnosis.nonspecific_codes import ICD_COUGH, UNRESOLVED_DIAGNOSIS_ICD


def test_named_constants_have_expected_values() -> None:
    """The engine returns R69 as its unresolved fallback (see `engine.py::get_current_diagnosis_code`),
    and R05 is a real ICD-10 code for Cough — both facts are load-bearing for
    the wrong-diagnosis fix."""
    assert UNRESOLVED_DIAGNOSIS_ICD == "R69"
    assert ICD_COUGH == "R05"


def test_inpatient_no_bare_r05_literal_and_uses_named_sentinel() -> None:
    """`inpatient.py` must NOT contain a bare ``"R05"`` literal anywhere
    (that was the wrong-dx sentinel — Issue #551 replaces it with the named
    ``UNRESOLVED_DIAGNOSIS_ICD`` constant, which resolves to R69, matching
    the engine's actual unresolved fallback)."""
    inpatient_src = (Path(__file__).parent / "../../../clinosim/simulator/inpatient.py").resolve().read_text()
    tree = ast.parse(inpatient_src)

    bare_r05_constants = [node for node in ast.walk(tree) if isinstance(node, ast.Constant) and node.value == "R05"]
    assert not bare_r05_constants, (
        f"Bare 'R05' literals found in inpatient.py at lines "
        f"{[n.lineno for n in bare_r05_constants]} — use the named constant "
        f"instead (or a comment explaining a different intent)."
    )

    # Every `diagnosis_correct=` kwarg on any `ClinicalDiagnosis(...)` call
    # must reference the named sentinel (unless it's a boolean literal for
    # test-scaffold cases like the placeholder `diagnosis_correct=False`).
    saw_named_reference = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "ClinicalDiagnosis":
            for kw in node.keywords:
                if kw.arg == "diagnosis_correct":
                    src = ast.unparse(kw.value)
                    if "UNRESOLVED_DIAGNOSIS_ICD" in src:
                        saw_named_reference = True
                    assert '"R05"' not in src and "'R05'" not in src, (
                        f"ClinicalDiagnosis(diagnosis_correct=...) at line "
                        f"{kw.value.lineno} still uses 'R05' literal: {src!r}"
                    )
    assert saw_named_reference, (
        "At least one ClinicalDiagnosis(diagnosis_correct=...) must reference UNRESOLVED_DIAGNOSIS_ICD"
    )


def test_engine_unresolved_fallback_uses_named_constant() -> None:
    """`engine.py::get_current_diagnosis_code` uses the same named
    ``UNRESOLVED_DIAGNOSIS_ICD`` constant, closing the drift between the
    engine's actual sentinel and the wrong-dx check in inpatient."""
    engine_src = (Path(__file__).parent / "../../../clinosim/modules/diagnosis/engine.py").resolve().read_text()
    assert "UNRESOLVED_DIAGNOSIS_ICD" in engine_src, "engine.py must import & use UNRESOLVED_DIAGNOSIS_ICD"
    # After migration, only `_display("R69")` should reference the bare string
    # (as the argument to a display lookup), not as a return literal for the
    # unresolved fallback itself.
    assert 'return "R69"' not in engine_src, (
        "engine.py must not return the bare R69 literal for the unresolved fallback"
    )
