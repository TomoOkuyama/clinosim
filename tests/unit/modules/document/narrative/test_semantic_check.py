"""β-JP-1 chain 1b T2: semantic check unit tests (PASS + FAIL pinned per axis)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from clinosim.modules.document.narrative.registry import load_document_type_specs
from clinosim.modules.document.narrative.semantic_check import (
    check_narratives,
    load_expectations,
)
from clinosim.types.document import DocumentType

pytestmark = pytest.mark.unit

ENC_ID = "ENC-SC-0001"
VERSION = "llm-test"

_HP_SECTIONS = tuple(load_document_type_specs()[DocumentType.ADMISSION_HP].composition_sections)


def _hp_sections(**overrides: str) -> dict[str, str]:
    """All ADMISSION_HP composition sections with benign English text."""
    sections = {key: f"Benign {key} text." for key in _HP_SECTIONS}
    sections.update(overrides)
    return sections


def _write_fixture(
    tmp_path: Path,
    *,
    generator: str = "llm-test",
    languages_used: list[str] | None = None,
    hp_sections: dict[str, str] | None = None,
    hp_facts: list[str] | None = None,
    pn_text: str = "S: stable. O: afebrile. A: improving. P: continue.",
    pn_facts: list[str] | None = None,
    skip_narrative_for: set[str] | None = None,
    orphan_file: bool = False,
) -> str:
    """Minimal on-disk structural + narrative pair: 1 admission_hp + 1 progress_note."""
    cif_dir = tmp_path / "cif"
    structural = cif_dir / "structural" / "patients"
    structural.mkdir(parents=True)
    narr_docs = cif_dir / "narratives" / VERSION / "documents" / ENC_ID
    narr_docs.mkdir(parents=True)

    stubs = [
        {"document_id": "doc-sc-hp", "task_type": "admission_hp"},
        {"document_id": "doc-sc-pn", "task_type": "progress_note"},
    ]
    (structural / "p1.json").write_text(
        json.dumps(
            {
                "patient": {"patient_id": "PT-SC-1"},
                "encounters": [{"encounter_id": ENC_ID, "encounter_type": "inpatient"}],
                "documents": stubs,
            }
        )
    )

    def _narr(doc_id: str, sections: dict[str, str], text: str, facts: list[str]) -> dict:
        return {
            "document_id": doc_id,
            "encounter_id": ENC_ID,
            "narrative": {
                "text": text,
                "sections": sections,
                "structured": {},
                "generator": generator,
                "generator_metadata": {"generator": "llm", "lang": "en"},
                "generated_at": "2020-01-01T00:00:42Z",
                "facts_used": facts,
            },
        }

    skip = skip_narrative_for or set()
    if "doc-sc-hp" not in skip:
        (narr_docs / "doc-sc-hp.json").write_text(
            json.dumps(
                _narr(
                    "doc-sc-hp",
                    hp_sections if hp_sections is not None else _hp_sections(),
                    "",
                    hp_facts if hp_facts is not None else ["ctx.patient.smoking_status"],
                )
            )
        )
    if "doc-sc-pn" not in skip:
        (narr_docs / "doc-sc-pn.json").write_text(
            json.dumps(
                _narr(
                    "doc-sc-pn",
                    {},
                    pn_text,
                    pn_facts if pn_facts is not None else [],
                )
            )
        )
    if orphan_file:
        (narr_docs / "doc-orphan.json").write_text(
            json.dumps(
                _narr(
                    "doc-orphan",
                    {},
                    "orphan",
                    [],
                )
            )
        )

    manifest = {
        "version_id": VERSION,
        "generator": generator,
        "languages_used": languages_used if languages_used is not None else ["en"],
    }
    (cif_dir / "narratives" / VERSION / "manifest.json").write_text(json.dumps(manifest))
    return str(cif_dir)


def _axes(report: Any) -> set[str]:
    return {f.axis for f in report.findings}


# --- Axis 1: structure ---


def test_structure_pass(tmp_path: Path) -> None:
    cif_dir = _write_fixture(tmp_path)
    report = check_narratives(cif_dir, VERSION)
    assert report.passed, report.findings
    assert report.document_count == 2


def test_structure_missing_narrative_file_fails(tmp_path: Path) -> None:
    cif_dir = _write_fixture(tmp_path, skip_narrative_for={"doc-sc-pn"})
    report = check_narratives(cif_dir, VERSION)
    assert not report.passed
    assert any("missing" in f.message for f in report.findings if f.axis == "structure")


def test_structure_orphan_narrative_file_fails(tmp_path: Path) -> None:
    cif_dir = _write_fixture(tmp_path, orphan_file=True)
    report = check_narratives(cif_dir, VERSION)
    assert any("orphan" in f.message for f in report.findings if f.axis == "structure")


def test_structure_section_key_drift_fails(tmp_path: Path) -> None:
    sections = _hp_sections()
    del sections["hpi"]
    sections["invented_section"] = "text"
    cif_dir = _write_fixture(tmp_path, hp_sections=sections)
    report = check_narratives(cif_dir, VERSION)
    drift = [f for f in report.findings if "drift" in f.message]
    assert drift and "hpi" in drift[0].message and "invented_section" in drift[0].message


def test_structure_empty_section_fails(tmp_path: Path) -> None:
    cif_dir = _write_fixture(tmp_path, hp_sections=_hp_sections(hpi="   "))
    report = check_narratives(cif_dir, VERSION)
    assert any(f.section == "hpi" and "empty" in f.message for f in report.findings if f.axis == "structure")


def test_structure_empty_free_text_fails(tmp_path: Path) -> None:
    cif_dir = _write_fixture(tmp_path, pn_text="")
    report = check_narratives(cif_dir, VERSION)
    assert any("empty free-text" in f.message for f in report.findings if f.axis == "structure")


def test_structure_template_fallback_on_llm_version_fails(tmp_path: Path) -> None:
    cif_dir = _write_fixture(tmp_path, generator="llm-ollama")
    # Rewrite the progress note metadata as template_fallback
    pn_path = Path(cif_dir) / "narratives" / VERSION / "documents" / ENC_ID / "doc-sc-pn.json"
    payload = json.loads(pn_path.read_text())
    payload["narrative"]["generator_metadata"]["generator"] = "template_fallback"
    pn_path.write_text(json.dumps(payload))
    report = check_narratives(cif_dir, VERSION)
    assert any(
        "template_fallback" in str(f.message) or "fell back" in f.message
        for f in report.findings
        if f.axis == "structure"
    )


# --- Axis 2: facts ---


def test_facts_bad_prefix_fails(tmp_path: Path) -> None:
    cif_dir = _write_fixture(tmp_path, hp_facts=["hallucinated.tag"])
    report = check_narratives(cif_dir, VERSION)
    assert any("hallucinated.tag" in f.message for f in report.findings if f.axis == "facts")


def test_facts_empty_on_llm_enabled_doc_fails(tmp_path: Path) -> None:
    cif_dir = _write_fixture(tmp_path, hp_facts=[])
    report = check_narratives(cif_dir, VERSION)
    assert any(f.document_id == "doc-sc-hp" and "empty" in f.message for f in report.findings if f.axis == "facts")


def test_facts_empty_on_template_only_doc_tolerated(tmp_path: Path) -> None:
    cif_dir = _write_fixture(tmp_path, pn_facts=[])
    report = check_narratives(cif_dir, VERSION)
    assert not [f for f in report.findings if f.axis == "facts"]
    assert report.info["empty_facts_template_only_docs"] == 1


# --- Axis 3: forbidden patterns ---


@pytest.mark.parametrize(
    "bad_text",
    [
        "As an AI language model I refuse.",
        "I cannot provide medical content.",
        "[Mock LLM response #3]",
        "BP {sbp}/{dbp} mmHg",
        "--- TEMPLATE SEED ---",
        "Generate an improved version of this section:",
        "改善後のセクション本文:",
    ],
)
def test_forbidden_builtin_patterns_fail(tmp_path: Path, bad_text: str) -> None:
    cif_dir = _write_fixture(tmp_path, hp_sections=_hp_sections(hpi=bad_text))
    report = check_narratives(cif_dir, VERSION)
    assert any(f.section == "hpi" for f in report.findings if f.axis == "forbidden_pattern"), (
        f"pattern not caught: {bad_text!r}"
    )


def test_forbidden_mock_marker_exempt_on_mock_generator(tmp_path: Path) -> None:
    cif_dir = _write_fixture(
        tmp_path,
        generator="llm-mock",
        hp_sections=_hp_sections(hpi="[Mock LLM response #1]"),
    )
    report = check_narratives(cif_dir, VERSION)
    assert not [f for f in report.findings if f.axis == "forbidden_pattern"]


def test_forbidden_ja_leak_in_en_version_fails(tmp_path: Path) -> None:
    cif_dir = _write_fixture(tmp_path, hp_sections=_hp_sections(chief_complaint="胸痛"))
    report = check_narratives(cif_dir, VERSION)
    assert any(
        "Japanese" in f.message and f.section == "chief_complaint"
        for f in report.findings
        if f.axis == "forbidden_pattern"
    )


def test_forbidden_ja_in_known_fallback_section_tolerated(tmp_path: Path) -> None:
    # hpi ∈ KNOWN_JA_ONLY_FALLBACK_SECTIONS (Bug A residual gap) — not counted.
    cif_dir = _write_fixture(tmp_path, hp_sections=_hp_sections(hpi="発熱を認める"))
    report = check_narratives(cif_dir, VERSION)
    assert not [f for f in report.findings if "Japanese" in f.message]


def test_forbidden_ja_not_checked_on_ja_version(tmp_path: Path) -> None:
    cif_dir = _write_fixture(
        tmp_path,
        languages_used=["ja"],
        hp_sections=_hp_sections(chief_complaint="胸痛"),
    )
    report = check_narratives(cif_dir, VERSION)
    assert not [f for f in report.findings if "Japanese" in f.message]


def test_forbidden_global_expectations_pattern_fails(tmp_path: Path) -> None:
    cif_dir = _write_fixture(tmp_path, hp_sections=_hp_sections(hpi="lorem ipsum filler"))
    expectations = {"global": {"forbidden_patterns": [r"lorem\s+ipsum"]}}
    report = check_narratives(cif_dir, VERSION, expectations)
    assert any("lorem" in f.message for f in report.findings if f.axis == "forbidden_pattern")


# --- Axes 4+5: expectations phrases + numeric ---


def _expectations(entry: dict[str, Any], section: str = "chief_complaint") -> dict[str, Any]:
    return {"admission_hp": {section: entry}}


def test_phrase_all_of_pass_and_fail(tmp_path: Path) -> None:
    cif_dir = _write_fixture(tmp_path, hp_sections=_hp_sections(chief_complaint="Chest pain and dyspnea"))
    ok = check_narratives(cif_dir, VERSION, _expectations({"all_of": ["Chest pain"]}))
    assert ok.passed, ok.findings
    bad = check_narratives(cif_dir, VERSION, _expectations({"all_of": ["Abdominal pain"]}))
    assert any(f.axis == "phrase" and "Abdominal pain" in f.message for f in bad.findings)


def test_phrase_any_of_pass_and_fail(tmp_path: Path) -> None:
    cif_dir = _write_fixture(tmp_path, hp_sections=_hp_sections(chief_complaint="Chest pain"))
    ok = check_narratives(cif_dir, VERSION, _expectations({"any_of": ["pain", "pressure"]}))
    assert ok.passed, ok.findings
    bad = check_narratives(cif_dir, VERSION, _expectations({"any_of": ["fever", "cough"]}))
    assert any(f.axis == "phrase" and "none of" in f.message for f in bad.findings)


def test_phrase_forbidden_fail(tmp_path: Path) -> None:
    cif_dir = _write_fixture(tmp_path, hp_sections=_hp_sections(chief_complaint="Chest pain"))
    bad = check_narratives(cif_dir, VERSION, _expectations({"forbidden": ["Chest"]}))
    assert any(f.axis == "phrase" and "forbidden phrase" in f.message for f in bad.findings)


def test_phrase_skipped_on_mock_llm_section(tmp_path: Path) -> None:
    """Expectations on llm_enabled_sections are skipped for the mock generator."""
    cif_dir = _write_fixture(
        tmp_path,
        generator="llm-mock",
        hp_sections=_hp_sections(hpi="[Mock LLM response #1]"),
    )
    expectations = _expectations({"all_of": ["fever history"]}, section="hpi")
    report = check_narratives(cif_dir, VERSION, expectations)
    assert not [f for f in report.findings if f.axis == "phrase"]
    assert report.info["skipped_mock_llm_sections"] == 1
    # ... but the SAME expectations fail loud on a real-provider generator.
    cif_dir2 = _write_fixture(
        tmp_path / "real",
        generator="llm-ollama",
        hp_sections=_hp_sections(hpi="something else entirely"),
    )
    report2 = check_narratives(cif_dir2, VERSION, expectations)
    assert any(f.axis == "phrase" for f in report2.findings)


def test_numeric_pass_within_tolerance_and_fail(tmp_path: Path) -> None:
    cif_dir = _write_fixture(
        tmp_path,
        hp_sections=_hp_sections(chief_complaint="Fever for 12 days, up to 38.5 C"),
    )
    ok = check_narratives(
        cif_dir,
        VERSION,
        _expectations({"numeric": [{"value": 11, "tolerance": 1}]}),
    )
    assert ok.passed, ok.findings
    bad = check_narratives(
        cif_dir,
        VERSION,
        _expectations({"numeric": [{"value": 25, "tolerance": 1}]}),
    )
    assert any(f.axis == "numeric" for f in bad.findings)


# --- load_expectations fail-loud validation ---


def _write_expectations(tmp_path: Path, data: dict[str, Any]) -> Path:
    p = tmp_path / "x.llm-expectations.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True))
    return p


def test_load_expectations_valid(tmp_path: Path) -> None:
    p = _write_expectations(
        tmp_path,
        {
            "global": {"forbidden_patterns": ["lorem"]},
            "admission_hp": {"chief_complaint": {"all_of": ["pain"]}},
            "discharge_summary": {"text": {"any_of": ["discharged"]}},
        },
    )
    data = load_expectations(p)
    assert "admission_hp" in data


def test_load_expectations_unknown_doc_type_raises(tmp_path: Path) -> None:
    p = _write_expectations(tmp_path, {"operative_note_typo": {"text": {"all_of": ["x"]}}})
    with pytest.raises(ValueError, match="unknown document type"):
        load_expectations(p)


def test_load_expectations_unknown_section_raises(tmp_path: Path) -> None:
    p = _write_expectations(tmp_path, {"admission_hp": {"not_a_section": {"all_of": ["x"]}}})
    with pytest.raises(ValueError, match="unknown section"):
        load_expectations(p)


def test_load_expectations_unknown_entry_key_raises(tmp_path: Path) -> None:
    p = _write_expectations(tmp_path, {"admission_hp": {"hpi": {"must_have": ["x"]}}})
    with pytest.raises(ValueError, match="unknown keys"):
        load_expectations(p)


def test_load_expectations_bad_regex_raises(tmp_path: Path) -> None:
    p = _write_expectations(tmp_path, {"global": {"forbidden_patterns": ["([unclosed"]}})
    with pytest.raises(ValueError, match="invalid regex"):
        load_expectations(p)


def test_load_expectations_bad_numeric_raises(tmp_path: Path) -> None:
    p = _write_expectations(tmp_path, {"admission_hp": {"hpi": {"numeric": [{"tolerance": 1}]}}})
    with pytest.raises(ValueError, match="'value'"):
        load_expectations(p)


def test_load_expectations_negative_tolerance_raises(tmp_path: Path) -> None:
    p = _write_expectations(
        tmp_path,
        {"admission_hp": {"hpi": {"numeric": [{"value": 3, "tolerance": -1}]}}},
    )
    with pytest.raises(ValueError, match="tolerance"):
        load_expectations(p)


def test_shipped_profile_expectations_all_load() -> None:
    """The 6 committed <name>.llm-expectations.yaml files pass the loader."""
    fixture_dir = Path(__file__).parents[4] / "fixtures" / "patient_profiles"
    paths = sorted(fixture_dir.glob("*.llm-expectations.yaml"))
    assert len(paths) >= 6, f"expected 6+ expectations files, found {paths}"
    for p in paths:
        load_expectations(p)
