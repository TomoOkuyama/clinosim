"""Issue #3446: a mother's other records do not include her newborn's."""

import json

from clinosim.modules.document.narrative.passes import TemplateNarrativePass


def _write(tmp_path, stem, pid, enc_type, labs=()):
    rec = {
        "patient": {"patient_id": pid},
        "encounters": [
            {
                "encounter_id": f"E-{stem}",
                "encounter_type": enc_type,
                "admission_datetime": "2025-03-01T09:00:00",
                "discharge_datetime": "2025-03-05T09:00:00",
            }
        ],
        "lab_results": list(labs),
    }
    (tmp_path / f"{stem}.json").write_text(json.dumps(rec))


def _pair(tmp_path):
    _write(
        tmp_path, "ENC-POP-000053-111", "POP-000053", "inpatient", [{"lab_name": "Hb", "value": 11.0, "unit": "g/dL"}]
    )
    _write(
        tmp_path,
        "ENC-POP-000053-BABY-222",
        "POP-000053-BABY",
        "inpatient",
        [{"lab_name": "Hb", "value": 17.0, "unit": "g/dL"}],
    )
    _write(tmp_path, "ENC-POP-000053-333", "POP-000053", "outpatient")
    _write(tmp_path, "ENC-POP-00005-444", "POP-00005", "outpatient")


def test_other_encounters_exclude_the_newborn(tmp_path):
    _pair(tmp_path)
    got = TemplateNarrativePass._patient_other_encounters(str(tmp_path), "ENC-POP-000053-333.json")
    assert [e["encounter_id"] for e in got] == ["E-ENC-POP-000053-111"]


def test_newborn_does_not_see_the_mother(tmp_path):
    _pair(tmp_path)
    got = TemplateNarrativePass._patient_other_encounters(str(tmp_path), "ENC-POP-000053-BABY-222.json")
    assert got == []


def test_prior_labs_are_the_patients_own(tmp_path):
    _pair(tmp_path)
    p = TemplateNarrativePass(cif_dir=str(tmp_path), country="US")
    got = p._patient_prior_labs(str(tmp_path), "ENC-POP-000053-333.json")
    assert [lab["value"] for lab in got] == [11.0]


def test_a_record_of_another_patient_id_is_skipped(tmp_path):
    _write(tmp_path, "ENC-POP-000001-aaa", "POP-000001", "inpatient")
    _write(tmp_path, "ENC-POP-000001-bbb", "POP-999999", "inpatient")
    _write(tmp_path, "ENC-POP-000001-ccc", "POP-000001", "outpatient")
    got = TemplateNarrativePass._patient_other_encounters(str(tmp_path), "ENC-POP-000001-ccc.json")
    assert len(got) == 1
