"""Streaming external merge sort for NDJSON output.

The historical ``_sort_ndjson_by_id_inplace`` read the whole file into
RAM, which OOM-crashed p=10k × 5-year cohorts whose Observation.ndjson
alone grows multi-GB. The replacement is a chunked external merge
sort with bounded peak RAM.

These tests pin:
  * fast path (single-chunk) still produces the pre-fix ordering,
  * external path (multi-chunk) produces the same ordering,
  * both paths handle blank lines + empty files + regex-missing lines,
  * the merge is a true id-ascending global order even when chunk
    boundaries would otherwise interleave ids.
"""

from __future__ import annotations

import importlib
import json

import pytest

from clinosim.modules.output.fhir_r4 import builder as _builder


def _write_ndjson(path, records):
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")


def _read_ids(path):
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            s = line.rstrip("\n")
            if s:
                out.append(json.loads(s).get("id", ""))
    return out


@pytest.fixture
def tiny_chunk_limit(monkeypatch):
    """Force the external-merge path by shrinking the per-chunk line budget."""
    monkeypatch.setattr(_builder, "_NDJSON_SORT_CHUNK_LINES", 3)
    yield 3
    importlib.reload(_builder)


@pytest.mark.unit
def test_sort_single_chunk_fast_path(tmp_path):
    """Small file (< chunk_limit) takes the in-memory fast path, no temp files."""
    path = tmp_path / "Patient.ndjson"
    _write_ndjson(path, [{"id": "c"}, {"id": "a"}, {"id": "b"}])

    _builder._sort_ndjson_by_id_inplace(str(path))

    assert _read_ids(path) == ["a", "b", "c"]
    # No stray chunk tempfiles survived in the output dir.
    assert not list(tmp_path.glob("._sort_chunk_*"))


@pytest.mark.unit
def test_sort_external_merge_crosses_chunk_boundary(tmp_path, tiny_chunk_limit):
    """IDs that would land in separate chunks still produce a global sort."""
    path = tmp_path / "Observation.ndjson"
    # 7 ids, chunk limit 3 → three chunks. Deliberately write them so
    # a chunk-local sort alone would not produce the global order.
    _write_ndjson(
        path,
        [
            {"id": "obs-04"},  # chunk 1
            {"id": "obs-01"},
            {"id": "obs-07"},
            {"id": "obs-02"},  # chunk 2
            {"id": "obs-06"},
            {"id": "obs-03"},
            {"id": "obs-05"},  # chunk 3
        ],
    )

    _builder._sort_ndjson_by_id_inplace(str(path))

    assert _read_ids(path) == [
        "obs-01",
        "obs-02",
        "obs-03",
        "obs-04",
        "obs-05",
        "obs-06",
        "obs-07",
    ]
    # Temp chunk files are unlinked on success.
    assert not list(tmp_path.glob("._sort_chunk_*"))


@pytest.mark.unit
def test_sort_preserves_full_line_content(tmp_path, tiny_chunk_limit):
    """The merge reorders lines; it does not mutate their payload."""
    path = tmp_path / "Patient.ndjson"
    records = [
        {"id": "p-02", "name": "second"},
        {"id": "p-01", "name": "first"},
        {"id": "p-04", "name": "fourth"},
        {"id": "p-03", "name": "third"},
    ]
    _write_ndjson(path, records)

    _builder._sort_ndjson_by_id_inplace(str(path))

    with path.open(encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]
    assert [rec["id"] for rec in lines] == ["p-01", "p-02", "p-03", "p-04"]
    assert [rec["name"] for rec in lines] == ["first", "second", "third", "fourth"]


@pytest.mark.unit
def test_sort_handles_blank_lines_and_empty_file(tmp_path, tiny_chunk_limit):
    """Blank lines drop out; an empty file stays empty."""
    path = tmp_path / "Patient.ndjson"
    path.write_text(
        '\n{"id":"b"}\n\n{"id":"a"}\n\n',
        encoding="utf-8",
    )

    _builder._sort_ndjson_by_id_inplace(str(path))

    assert _read_ids(path) == ["a", "b"]

    empty = tmp_path / "Empty.ndjson"
    empty.write_text("", encoding="utf-8")
    _builder._sort_ndjson_by_id_inplace(str(empty))
    assert empty.read_text(encoding="utf-8") == ""


@pytest.mark.unit
def test_sort_falls_back_on_regex_miss(tmp_path, tiny_chunk_limit):
    """A line whose ``id`` field is formatted unusually still sorts via the json.loads fallback."""
    path = tmp_path / "Patient.ndjson"
    # Mix a regex-fast line with one that has whitespace around the colon
    # — the fast regex pattern is strict, so this exercises the fallback.
    path.write_text(
        '{"id":"p-02"}\n{ "id" : "p-01" }\n{"id":"p-04"}\n{"id":"p-03"}\n',
        encoding="utf-8",
    )

    _builder._sort_ndjson_by_id_inplace(str(path))

    assert _read_ids(path) == ["p-01", "p-02", "p-03", "p-04"]
