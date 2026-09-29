"""Duplicate Project publication and whole-folder copy characterization."""

import ast
import os
from pathlib import Path
import shutil

import pytest

from core import project_directory_duplication as planner
from ui import project_directory_duplication_lifecycle as lifecycle


class State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


def _workspace(tmp_path):
    source_dir = tmp_path / "Original"
    source_dir.mkdir()
    source_json = source_dir / "project.json"
    source_json.write_text('{"version": 1}', encoding="utf-8")
    return source_dir, source_json, State(project=object(), current_project_path=str(source_json))


def _apply(state, *, save=None, layout=None, load=None, refresh=None, name="Copy"):
    return lifecycle.duplicate_project_directory(
        name,
        session_state=state,
        save_project_to_json=save or (lambda *_: None),
        ensure_current_project_folder_layout=layout or (lambda *_: None),
        load_project_json_into_session=load or (lambda *_: True),
        request_project_directory_discovery_refresh=refresh or (lambda: None),
    )


def test_preflight_rejection_does_not_save_or_copy(tmp_path, monkeypatch):
    _, source_json, state = _workspace(tmp_path)
    destination = tmp_path / "Copy"
    destination.mkdir()
    events = []
    monkeypatch.setattr(lifecycle.shutil, "copytree", lambda *a, **k: events.append("copy"))
    result = _apply(
        state,
        save=lambda *_: events.append("save"),
        layout=lambda *_: events.append("layout"),
        load=lambda *_: events.append("load"),
        refresh=lambda: events.append("refresh"),
    )
    assert result == (False, "複製先ディレクトリは既に存在します。")
    assert events == []
    assert source_json.read_text(encoding="utf-8") == '{"version": 1}'


def test_success_saves_live_project_then_copies_all_project_assets(tmp_path, monkeypatch):
    source_dir, source_json, state = _workspace(tmp_path)
    kept = (
        "refs/modules/picture.png", "refs/other.png", "candidates/c.png",
        "routes/r.json", "exports/e.png", "workflows/w.json",
    )
    for name in kept:
        path = source_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
    ignored = (
        ".promptgraph_cache", ".scratch.tmp", ".git", "__pycache__",
        ".pytest_cache", ".mypy_cache", ".DS_Store", "Thumbs.db",
    )
    for name in ignored:
        (source_dir / name).write_bytes(b"ignored")
    events = []
    original_plan = planner.plan_project_directory_duplication
    original_copy = shutil.copytree

    def plan(*args, **kwargs):
        events.append("plan")
        return original_plan(*args, **kwargs)

    def copy(*args, **kwargs):
        events.append("copy")
        assert (source_dir / "layout_ready").exists()
        assert source_json.read_text(encoding="utf-8") == "live session saved"
        candidates = list(ignored) + list(kept) + ["project.json"]
        assert kwargs["ignore"]("unused", candidates) == set(ignored)
        monkeypatch.setattr(lifecycle.shutil, "copytree", original_copy)
        return original_copy(*args, **kwargs)

    def save(project, path):
        events.append("save")
        assert project is original_project
        assert path == str(source_json)
        Path(path).write_text("live session saved", encoding="utf-8")

    def layout(path):
        events.append("layout")
        assert path == str(source_json)
        (source_dir / "layout_ready").touch()

    def load(path):
        events.append("load")
        assert path == str(tmp_path / "Copy" / "project.json")
        assert Path(path).read_text(encoding="utf-8") == "live session saved"
        assert all((tmp_path / "Copy" / name).read_bytes() == name.encode() for name in kept)
        assert not any((tmp_path / "Copy" / name).exists() for name in ignored)
        assert (tmp_path / "Copy" / "layout_ready").exists()
        state.current_project_path = path
        return True

    original_project = state.project
    monkeypatch.setattr(planner, "plan_project_directory_duplication", plan)
    monkeypatch.setattr(lifecycle.shutil, "copytree", copy)
    success, message = _apply(
        state, save=save, layout=layout, load=load,
        refresh=lambda: events.append("refresh"),
    )
    assert success
    assert message == f"プロジェクトディレクトリを複製して開きました: {tmp_path / 'Copy' / 'project.json'}"
    assert events == ["plan", "save", "layout", "copy", "load", "refresh"]
    assert state.current_project_path == str(tmp_path / "Copy" / "project.json")
    assert state.autosave_feedback == "project duplicated"
    assert state.last_saved_at


def test_copied_json_resolution_keeps_primary_and_fallback_rules(tmp_path):
    destination = tmp_path / "Copy"
    destination.mkdir()
    source = str(tmp_path / "Original" / "project.json")
    assert lifecycle._find_copied_project_json(str(destination), source) == ""
    other = destination / "other.JSON"
    other.write_text("{}", encoding="utf-8")
    (destination / "ignored.json").mkdir()
    assert lifecycle._find_copied_project_json(str(destination), source) == str(other)
    second = destination / "second.json"
    second.write_text("{}", encoding="utf-8")
    assert lifecycle._find_copied_project_json(str(destination), source) == ""
    primary = destination / "project.json"
    primary.write_text("{}", encoding="utf-8")
    assert lifecycle._find_copied_project_json(str(destination), source) == str(primary)


@pytest.mark.parametrize("failure", ["save", "layout"])
def test_source_preparation_failure_stops_before_copy(tmp_path, failure):
    _, _, state = _workspace(tmp_path)
    events = []

    def save(*_):
        events.append("save")
        if failure == "save":
            raise ValueError("broken")

    def layout(*_):
        events.append("layout")
        if failure == "layout":
            raise ValueError("broken")

    result = _apply(state, save=save, layout=layout, load=lambda *_: events.append("load"))
    assert result == (False, "複製前のプロジェクト保存に失敗しました: broken")
    assert events == (["save"] if failure == "save" else ["save", "layout"])
    assert not (tmp_path / "Copy").exists()
    assert "autosave_feedback" not in state


def test_copy_error_propagates_and_preserves_partial_destination(tmp_path, monkeypatch):
    _, _, state = _workspace(tmp_path)
    def copy(source, destination, **_):
        Path(destination).mkdir()
        (Path(destination) / "partial").write_bytes(b"partial")
        raise OSError("copy interrupted")
    monkeypatch.setattr(lifecycle.shutil, "copytree", copy)
    with pytest.raises(OSError, match="copy interrupted"):
        _apply(state)
    assert (tmp_path / "Copy" / "partial").read_bytes() == b"partial"
    assert "autosave_feedback" not in state


def test_missing_copied_json_keeps_completed_copy(tmp_path, monkeypatch):
    _, _, state = _workspace(tmp_path)
    monkeypatch.setattr(lifecycle, "_find_copied_project_json", lambda *_: "")
    result = _apply(state, load=lambda *_: pytest.fail("loader must not run"))
    assert result == (False, "複製先で開くproject JSONが見つかりません。")
    assert (tmp_path / "Copy" / "project.json").exists()
    assert "autosave_feedback" not in state


@pytest.mark.parametrize("load_result,expected", [
    (False, "複製先project JSONを開けませんでした。"),
    (ValueError("loader failed"), "複製先project JSONを開けませんでした: loader failed"),
])
def test_loader_failure_keeps_copy_and_loader_partial_session_effects(tmp_path, load_result, expected):
    _, _, state = _workspace(tmp_path)
    def load(path):
        state.current_project_path = path
        if isinstance(load_result, Exception):
            raise load_result
        return load_result
    assert _apply(state, load=load) == (False, expected)
    assert (tmp_path / "Copy" / "project.json").exists()
    assert state.current_project_path == str(tmp_path / "Copy" / "project.json")
    assert "autosave_feedback" not in state


def test_refresh_failure_keeps_success_publication_and_copy(tmp_path):
    _, _, state = _workspace(tmp_path)
    def refresh():
        raise RuntimeError("refresh failed")
    with pytest.raises(RuntimeError, match="refresh failed"):
        _apply(state, refresh=refresh)
    assert (tmp_path / "Copy" / "project.json").exists()
    assert state.autosave_feedback == "project duplicated"
    assert state.last_saved_at


def test_renderer_keeps_confirmation_feedback_outer_error_and_rerun():
    source = Path(__file__).resolve().parents[1].joinpath("app.py").read_text(encoding="utf-8")
    body = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == "render_duplicate_project_management_section")
    rendered = ast.get_source_segment(source, body)
    assert 'key="duplicate_project_confirm"' in rendered
    assert 'key="duplicate_project_as_button"' in rendered
    assert "duplicate_current_project_directory(" in rendered
    assert "st.success(message)" in rendered
    assert "st.warning(message)" in rendered
    assert "except OSError as exc:" in rendered
    assert rendered.index("st.success(message)") < rendered.index("st.rerun()")
