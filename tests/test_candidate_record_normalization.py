"""Characterize the runtime Candidate normalization contract separately from I/O."""

import ntpath
import os
from pathlib import Path
import posixpath
from types import SimpleNamespace

import pytest

from core import candidate_record_normalization as normalization


@pytest.mark.parametrize("value", [None, False, 0, "", [], {}])
def test_falsey_values_are_empty(value):
    assert normalization._normalize_candidate_path(value) == ""
    assert normalization._normalize_candidate_record(value) is None
    assert normalization._normalize_candidate_record({"path": value}) is None
    assert normalization._normalize_candidate_records(value) == []


@pytest.mark.parametrize("path_module", [ntpath, posixpath])
def test_platform_path_semantics(monkeypatch, path_module):
    monkeypatch.setattr(normalization, "os", SimpleNamespace(path=path_module))
    for path in [r"C:\images\..\a.png", r"\\server\share\a.png", "/images/../a.png"]:
        expected = path_module.abspath(path) if path_module.isabs(path) else path.replace("\\", "/")
        assert normalization._normalize_candidate_path(path) == expected


@pytest.mark.parametrize("value, expected", [
    (r"images\..\a.png", "images/../a.png"),
    (" ./images//a.png ", " ./images//a.png "),
    ("~/image.png", "~/image.png"),
    (7, "7"),
    (Path("images") / "a.png", "images/a.png"),
])
def test_relative_values_keep_whitespace_dot_segments_and_no_home_expansion(value, expected):
    assert normalization._normalize_candidate_path(value) == expected
    assert normalization._normalize_candidate_record(value) == {"path": expected}


def test_native_absolute_path_normalizes_without_requiring_a_file(tmp_path):
    path = str(tmp_path / "missing" / ".." / "image.png")
    assert normalization._normalize_candidate_path(path) == os.path.abspath(path)


def test_dictionary_copy_preserves_unknown_fields_and_nested_aliases():
    metadata = {"future": []}
    candidate = {"path": r"images\a.png", "unknown": metadata, "pinned": False}
    record = normalization._normalize_candidate_record(candidate)
    assert record == {"path": "images/a.png", "unknown": metadata, "pinned": False}
    assert record is not candidate
    assert record["unknown"] is metadata
    assert candidate["path"] == r"images\a.png"


def test_first_normalized_occurrence_wins_without_merging_or_case_folding():
    nested = []
    first = {"path": r"images\a.png", "metadata": nested}
    candidates = [None, first, {"path": "images/a.png", "later": True},
                  "images/b.png", "images/b.png", "images/A.png", {"path": ""}]
    result = normalization._normalize_candidate_records(iter(candidates))
    assert result == [{"path": "images/a.png", "metadata": []},
                      {"path": "images/b.png"}, {"path": "images/A.png"}]
    assert result[0] is not first
    assert result[0]["metadata"] is nested
    assert len(candidates) == 7


def test_absolute_dot_segments_deduplicate_but_relative_dot_segments_do_not(tmp_path):
    path = str(tmp_path / "a.png")
    result = normalization._normalize_candidate_records([
        str(tmp_path / "missing" / ".." / "a.png"), path, "a.png", "./a.png",
    ])
    assert result == [{"path": os.path.abspath(path)}, {"path": "a.png"}, {"path": "./a.png"}]


def test_string_conversion_exception_propagates_unchanged_and_stops_iteration():
    error = ValueError("cannot stringify candidate path")

    class BrokenPath:
        def __str__(self):
            raise error

    for candidate in [BrokenPath(), {"path": BrokenPath()}]:
        with pytest.raises(ValueError) as caught:
            normalization._normalize_candidate_record(candidate)
        assert caught.value is error

    visited = []

    def candidates():
        yield "valid.png"
        yield {"path": BrokenPath()}
        visited.append("after failure")

    with pytest.raises(ValueError) as caught:
        normalization._normalize_candidate_records(candidates())
    assert caught.value is error
    assert visited == []


def test_path_resolution_exception_propagates_unchanged(monkeypatch):
    error = OSError("cannot resolve absolute path")

    def fail(path):
        raise error

    monkeypatch.setattr(normalization, "os", SimpleNamespace(path=SimpleNamespace(
        isabs=lambda path: True, abspath=fail,
    )))
    with pytest.raises(OSError) as caught:
        normalization._normalize_candidate_records(["image.png"])
    assert caught.value is error


def test_truthy_non_iterable_collection_keeps_type_error():
    with pytest.raises(TypeError):
        normalization._normalize_candidate_records(1)
