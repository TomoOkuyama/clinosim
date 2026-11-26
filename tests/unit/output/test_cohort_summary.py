"""Unit tests for the cohort summary builder (``summary/cohort-summary.json``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from clinosim.modules.output.cohort_summary import (
    METADATA_KEY,
    build_cohort_summary,
    summary_path_for,
    write_cohort_summary,
)
from clinosim.types.output import CIFDataset, CIFMetadata, CIFPatientRecord, distinct_patient_count
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_PERIOD = {
    "period_start": "2026-01-01",
    "period_end": "2026-06-30",
    "snapshot_date": "2026-06-30",
}


def _rec(
    pid: str,
    *,
    sex: str = "M",
    dob: str = "1980-06-30",
    chronic: tuple[str, ...] = (),
    encounters: tuple[tuple[str, str, str | None, str], ...] = (("outpatient", "2026-02-01T09:00:00", None, "home"),),
    discharge_dx: str = "",
    admission_dx: str = "",
    died_on: str | None = None,
) -> dict[str, Any]:
    return {
        "patient": {
            "patient_id": pid,
            "sex": sex,
            "date_of_birth": dob,
            "date_of_death": died_on,
            "chronic_conditions": [{"code": c} for c in chronic],
        },
        "encounters": [
            {
                "encounter_type": t,
                "admission_datetime": adm,
                "discharge_datetime": dis,
                "discharge_disposition": disp,
            }
            for t, adm, dis, disp in encounters
        ],
        "clinical_diagnosis": {"discharge_diagnosis_code": discharge_dx, "admission_diagnosis_code": admission_dx},
    }


def _build(records: list[dict[str, Any]], country: str = "US") -> dict[str, Any]:
    return build_cohort_summary(records, country=country, **_PERIOD)


def test_patients_are_counted_once_across_records() -> None:
    s = _build([_rec("P1"), _rec("P1"), _rec("P2", sex="F")])
    assert s["patients"]["total"] == 2
    assert s["patients"]["by_sex"] == {"F": 1, "M": 1}
    assert s["encounters"]["total"] == 3


def test_age_band_is_on_the_snapshot_date() -> None:
    # Snapshot 2026-06-30: born 1971-06-30 is 55 ("55-64"); born 1971-07-01 is 54 ("45-54").
    s = _build([_rec("A", dob="1971-06-30"), _rec("B", dob="1971-07-01"), _rec("C", dob="1920-01-01")])
    bands = {b["band"]: b["patients"] for b in s["patients"]["by_age_band"]}
    assert bands["55-64"] == 1 and bands["45-54"] == 1
    # C is 106, above the last band: counted in the last band.
    assert bands["85-99"] == 1
    assert sum(bands.values()) == 3
    # Bands come in ascending order, zero bands included.
    order = [b["band"] for b in s["patients"]["by_age_band"]]
    assert order[0] == "0-14" and order[-1] == "85-99" and len(order) == 9


def test_deaths_in_period_and_in_hospital() -> None:
    s = _build(
        [
            _rec(
                "D1",
                died_on="2026-03-02",
                encounters=(("inpatient", "2026-02-27T10:00:00", "2026-03-02T10:00:00", "exp"),),
            ),
            _rec("D2", died_on="2026-04-01"),  # died after an outpatient visit
            _rec("D3", died_on="2025-12-31"),  # before the period
            _rec("L1"),
        ]
    )
    assert s["patients"]["deaths"] == {"total": 2, "in_hospital": 1}
    assert s["encounters"]["inpatient"]["in_hospital_deaths"] == 1


def test_length_of_stay_counts_finished_stays_only() -> None:
    s = _build(
        [
            _rec("P1", encounters=(("inpatient", "2026-03-01T00:00:00", "2026-03-04T00:00:00", "home"),)),
            _rec("P2", encounters=(("inpatient", "2026-03-01T00:00:00", "2026-03-08T12:00:00", "home"),)),
            _rec("P3", encounters=(("inpatient", "2026-03-01T00:00:00", "2026-03-02T00:00:00", "home"),)),
            _rec("P4", encounters=(("inpatient", "2026-06-29T00:00:00", None, ""),)),  # still admitted
        ]
    )
    inp = s["encounters"]["inpatient"]
    assert inp["stays"] == 4 and inp["finished_stays"] == 3
    assert inp["length_of_stay_days"] == {"mean": 3.83, "median": 3.0}
    assert s["encounters"]["by_type"] == {"inpatient": 4}


def test_no_finished_stay_gives_null_length_of_stay() -> None:
    s = _build([_rec("P1")])
    assert s["encounters"]["inpatient"]["length_of_stay_days"] == {"mean": None, "median": None}


def test_conditions_sorted_by_patients_then_code_and_mapped_to_country_codes() -> None:
    stay = (("inpatient", "2026-03-01T00:00:00", "2026-03-04T00:00:00", "home"),)
    records = [
        _rec("P1", chronic=("I50", "E11")),
        _rec("P2", chronic=("E11",)),
        _rec("P3", chronic=("I10",)),
        _rec("P1", chronic=("I50", "E11"), encounters=stay, discharge_dx="J18.9"),
        _rec("P2", chronic=("E11",), encounters=stay, admission_dx="A41.9"),
        _rec("P3", chronic=("I10",), encounters=stay, discharge_dx="J18.9"),
        _rec("P3", chronic=("I10",), encounters=stay, discharge_dx="J18.9"),  # one patient, two stays
    ]
    s = _build(records)
    chronic = s["conditions"]["chronic"]
    assert [(c["code"], c["patients"]) for c in chronic] == [("E11.9", 2), ("I10", 1), ("I50.9", 1)]
    assert chronic[0]["system"] == "http://hl7.org/fhir/sid/icd-10-cm"
    assert chronic[0]["display"] and chronic[0]["display"].isascii()
    principal = s["conditions"]["inpatient_principal_diagnosis"]
    assert [(c["code"], c["patients"]) for c in principal] == [("J18.9", 2), ("A41.9", 1)]


def test_chronic_conditions_come_from_the_latest_record() -> None:
    old = _rec("P1", chronic=("E11",), encounters=(("outpatient", "2026-01-10T09:00:00", None, "home"),))
    new = _rec("P1", chronic=("I10",), encounters=(("outpatient", "2026-05-10T09:00:00", None, "home"),))
    for order in ([old, new], [new, old]):
        assert [c["code"] for c in _build(order)["conditions"]["chronic"]] == ["I10"]


def test_jp_display_is_japanese_and_unknown_code_has_null_display() -> None:
    s = _build([_rec("P1", chronic=("I50", "Z99X"))], country="JP")
    by_code = {c["code"]: c for c in s["conditions"]["chronic"]}
    assert by_code["I50.9"]["display"] == "心不全，詳細不明"
    assert by_code["Z99X"]["display"] is None
    assert s["language"] == "ja"
    us = _build([_rec("P1", chronic=("I50",))], country="US")
    assert all(c["display"] is None or c["display"].isascii() for c in us["conditions"]["chronic"])


def test_us_summary_has_no_japanese() -> None:
    s = _build([_rec("P1", chronic=("I50", "E11", "J44")), _rec("P2", chronic=("I10",))])
    text = json.dumps(s, ensure_ascii=False)
    assert text.isascii()


def test_summary_is_deterministic_and_independent_of_record_order() -> None:
    records = [_rec(f"P{i}", sex="MF"[i % 2], chronic=("E11", "I10")[: 1 + i % 2]) for i in range(7)]
    a = json.dumps(_build(records), sort_keys=True)
    b = json.dumps(_build(list(reversed(records))), sort_keys=True)
    assert a == b


def test_header_carries_inputs_only() -> None:
    s = _build([_rec("P1")])
    assert set(s) == {
        "schema_version",
        "country",
        "language",
        "period",
        "snapshot_date",
        "patients",
        "conditions",
        "encounters",
    }
    assert s["period"] == {"start": "2026-01-01", "end": "2026-06-30"}
    assert s["schema_version"] == 1


def test_distinct_patient_count_vs_records() -> None:
    def rec(pid: str) -> CIFPatientRecord:
        return CIFPatientRecord(patient=PatientProfile(patient_id=pid))

    assert distinct_patient_count([rec("A"), rec("A"), rec("B")]) == 2


def test_write_cohort_summary_writes_file_and_points_metadata_at_it(tmp_path: Path) -> None:
    from clinosim.modules.output.cif_writer import write_cif

    meta = CIFMetadata(
        country="US",
        snapshot_date="2026-06-30",
        total_patients=1,
        total_records=1,
    )
    rec = CIFPatientRecord(patient=PatientProfile(patient_id="P1", sex="M", date_of_birth="1980-01-01"))
    cif_dir = tmp_path / "cif"
    write_cif(CIFDataset(metadata=meta, patients=[rec]), str(cif_dir))
    md = json.loads((cif_dir / "metadata.json").read_text())
    assert "total_patients_generated" not in md
    assert md["total_patients"] == 1 and md["total_records"] == 1

    path = write_cohort_summary(str(cif_dir))
    assert path == summary_path_for(str(cif_dir)) == str(tmp_path / "summary" / "cohort-summary.json")
    md = json.loads((cif_dir / "metadata.json").read_text())
    assert md[METADATA_KEY] == "summary/cohort-summary.json"
    first = Path(path).read_bytes()
    assert json.loads(first)["patients"]["total"] == 1
    write_cohort_summary(str(cif_dir))
    assert Path(path).read_bytes() == first
