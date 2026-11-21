"""The narrative pass stays linear in the cohort size.

A pass over a p=10000 cohort (about 43,000 structural records) took 20 times
as long as v0.7.0 because every outpatient note listed the whole structural
directory to find the patient's other records (one ``listdir`` per document,
each over every record) and re-parsed the condition stage label YAML on every
stage it printed.
"""

import json
import os

from clinosim.locale.loaders.narrative import load_condition_stage_labels
from clinosim.modules.document.narrative.passes import TemplateNarrativePass


def _write(tmp_path, stem, pid):
    rec = {"patient": {"patient_id": pid}, "encounters": [{"encounter_id": f"E-{stem}"}]}
    (tmp_path / f"{stem}.json").write_text(json.dumps(rec))


def test_record_lookup_lists_the_directory_once(tmp_path, monkeypatch):
    for i in range(5):
        _write(tmp_path, f"ENC-POP-00000{i}-a", f"POP-00000{i}")
        _write(tmp_path, f"ENC-POP-00000{i}-b", f"POP-00000{i}")
    calls = []
    real = os.listdir
    monkeypatch.setattr(os, "listdir", lambda p: calls.append(p) or real(p))
    for i in range(5):
        got = TemplateNarrativePass._patient_other_encounters(str(tmp_path), f"ENC-POP-00000{i}-a.json")
        assert [e["encounter_id"] for e in got] == [f"E-ENC-POP-00000{i}-b"]
    assert len(calls) <= 1


def test_record_lookup_sees_a_record_written_later(tmp_path):
    _write(tmp_path, "ENC-POP-000001-a", "POP-000001")
    assert TemplateNarrativePass._patient_other_encounters(str(tmp_path), "ENC-POP-000001-a.json") == []
    _write(tmp_path, "ENC-POP-000001-b", "POP-000001")
    got = TemplateNarrativePass._patient_other_encounters(str(tmp_path), "ENC-POP-000001-a.json")
    assert [e["encounter_id"] for e in got] == ["E-ENC-POP-000001-b"]


def test_condition_stage_labels_are_parsed_once():
    assert load_condition_stage_labels() is load_condition_stage_labels()
