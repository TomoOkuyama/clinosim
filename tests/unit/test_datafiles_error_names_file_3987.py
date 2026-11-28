"""A reference-YAML validation error names the file (Issue #3987).

``load_validated_yaml`` adds the path as a note to the ``ValidationError``; the
exception type, ``str(exc)`` and ``errors()`` stay as pydantic produced them.
"""

from __future__ import annotations

import traceback
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from clinosim.datafiles import load_validated_yaml


class _Inner(BaseModel):
    model_config = ConfigDict(extra="forbid")
    threshold: float


class _Rules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rules: dict[str, _Inner]


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "rules.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_unknown_key_error_names_file_and_key(tmp_path: Path) -> None:
    path = _write(tmp_path, "metadata:\n  kind: reference\nrules:\n  a:\n    threshold: 1.0\n    thresold: 2.0\n")
    with pytest.raises(ValidationError, match="thresold") as info:
        load_validated_yaml(path, _Rules)
    assert [str(path) in n for n in info.value.__notes__] == [True]
    rendered = "".join(traceback.format_exception(info.value))
    assert f"in {path}" in rendered
    assert "rules.a.thresold" in rendered


def test_message_and_errors_are_unchanged(tmp_path: Path) -> None:
    path = _write(tmp_path, "rules:\n  a:\n    threshold: oops\n")
    with pytest.raises(ValidationError) as info:
        load_validated_yaml(path, _Rules)
    with pytest.raises(ValidationError) as plain:
        _Rules.model_validate({"rules": {"a": {"threshold": "oops"}}})
    assert str(info.value) == str(plain.value)
    assert info.value.errors() == plain.value.errors()
    assert type(info.value) is ValidationError


def test_valid_file_is_returned_unchanged(tmp_path: Path) -> None:
    path = _write(tmp_path, "metadata:\n  kind: reference\nrules:\n  a:\n    threshold: 1.0\n")
    assert load_validated_yaml(path, _Rules) == {"rules": {"a": {"threshold": 1.0}}}
