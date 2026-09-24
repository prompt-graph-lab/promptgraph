"""Candidate Route Fresh Preview and Apply safety contract."""

import ast
import copy
import hashlib
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.candidate_inspection import (
    _active_candidates, _candidate_path, _candidate_prompt_metadata,
    _candidate_route_candidate_seed, _candidate_route_candidate_workflow,
)
from core.candidate_record_normalization import _normalize_candidate_path, _normalize_candidate_records
from core.candidate_route_creation_preview import build_candidate_route_creation_preview
from core.gallery_variant_promotion import normalize_candidate_line_for_main_sequence
from core.io import (
    _json_safe_source_value, build_lineage_info_from_candidate,
    build_source_generation_info_from_candidate, resolve_project_asset_path,
)
from core.operations import resolve_gallery_route_for_line
from core.parser import parse_prompt
from core.project import Project, PromptLine
from core.prompt_line_selection import is_gallery_operation_prompt_line, is_route_separator


class Session(dict):
    __getattr__ = dict.get

    def __setattr__(self, name, value):
        self[name] = value


def line(line_id, index, candidates=None, **kwargs):
    return PromptLine(
        id=line_id, original_file_name=f"{line_id}.png", original_index=index,
        current_index=index, original_text="original", current_text="positive",
        tokens=["positive"], negative_prompt="negative",
        generated_candidates=candidates or [], **kwargs,
    )


@pytest.fixture
def setup(tmp_path):
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {
        "_candidate_route_line_base_label", "_candidate_route_label",
        "_candidate_route_target_lines", "preview_candidate_route_creation",
        "_apply_candidate_prompt_to_line", "_build_candidate_route_line",
        "apply_candidate_route_creation", "_reindex_project_lines",
    }
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    events = []
    session = Session(current_project_path=str(tmp_path / "project.json"),
                      line_generated_candidates={}, focused_line_id="a")
    namespace = dict(
        st=SimpleNamespace(session_state=session), os=os, stat=stat, json=json,
        hashlib=hashlib, copy=copy, uuid=__import__("uuid"),
        datetime=__import__("datetime").datetime, timezone=__import__("datetime").timezone,
        PromptLine=PromptLine, parse_prompt=parse_prompt,
        _candidate_path=_candidate_path, _normalize_candidate_path=_normalize_candidate_path,
        _normalize_candidate_records=_normalize_candidate_records,
        _active_candidates=_active_candidates,
        _candidate_prompt_metadata=_candidate_prompt_metadata,
        _candidate_route_candidate_seed=_candidate_route_candidate_seed,
        _candidate_route_candidate_workflow=_candidate_route_candidate_workflow,
        build_source_generation_info_from_candidate=build_source_generation_info_from_candidate,
        build_lineage_info_from_candidate=build_lineage_info_from_candidate,
        normalize_candidate_line_for_main_sequence=normalize_candidate_line_for_main_sequence,
        _json_safe_source_value=_json_safe_source_value,
        resolve_project_asset_path=resolve_project_asset_path,
        build_candidate_route_creation_preview=build_candidate_route_creation_preview,
        resolve_gallery_route_for_line=resolve_gallery_route_for_line,
        is_route_separator=is_route_separator,
        is_gallery_operation_prompt_line=is_gallery_operation_prompt_line,
        get_prompt_line_label=lambda item: f"{item.original_file_name}:{item.current_index + 1}",
        route_separator_label=lambda item: item.separator_label or item.current_text or item.original_file_name,
        get_line_by_id=lambda project, line_id: next((item for item in project.prompt_lines if item.id == line_id), None),
        _gallery_route_anchor_line_id=lambda project, selected: session.get("focused_line_id") or (selected or [""])[0],
        push_history=lambda: events.append("history"),
        build_graph=lambda project: events.append("graph") or project,
        save_current_project_if_possible=lambda reason: events.append("save"),
        restore_focus_after_graph_update=lambda previous: events.append("focus"),
    )
    exec(compile(ast.Module(body=functions, type_ignores=[]), "<candidate route app>", "exec"), namespace)
    image = tmp_path / "a.png"
    image.write_bytes(b"image")
    parent = line("a", 1, [{"path": "a.png", "unknown": {"nested": [1, 2]}}])
    separator = line("route", 0, line_type="separator", separator_label="Parent")
    other = line("b", 2, [])
    project = Project(prompt_lines=[separator, parent, other])
    session.project = project
    return SimpleNamespace(ns=namespace, session=session, events=events,
                           project=project, image=image, parent=parent, other=other,
                           preview=lambda scope="selected_lines", selected=None, limit=8:
                           namespace["preview_candidate_route_creation"](
                               project, scope, ["a"] if selected is None else selected, limit),
                           apply=lambda preview, scope="selected_lines", selected=None:
                           namespace["apply_candidate_route_creation"](
                               project, scope, ["a"] if selected is None else selected, preview=preview))


def assert_stale_without_effects(setup, preview):
    before = copy.deepcopy(setup.project)
    result = setup.apply(preview)
    assert result["stale_preview"] is True
    assert setup.events == []
    assert setup.project == before
    assert setup.session.project is setup.project


def test_plan_covers_all_candidates_even_when_examples_are_limited(setup, tmp_path):
    for index in range(12):
        path = tmp_path / f"extra-{index}.png"
        path.write_bytes(b"x")
        setup.parent.generated_candidates.append({"path": path.name, "unknown": index})
    small = setup.preview(limit=0)
    shown = setup.preview(limit=8)
    assert small["examples"] == []
    assert small["fingerprint"] == shown["fingerprint"]
    assert small["apply_plan"] == shown["apply_plan"]
    plan = json.loads(small["apply_plan"])
    assert plan["placement"] == "after_source"
    assert len(plan["routes"][0]["candidates"]) == 13
    assert small["add_line_count"] == 13


@pytest.mark.parametrize("change", [
    "candidate_add", "candidate_remove", "candidate_reorder", "candidate_path",
    "candidate_trash", "candidate_restore", "persisted_metadata", "session_candidate",
    "session_metadata",
    "file_disappear", "file_appear", "file_type", "file_size", "file_mtime",
    "duplicate_route", "source_positive", "source_negative", "source_copied",
    "source_image", "source_generated_image", "source_selected_image",
    "target_delete", "target_order", "target_index", "parent_route_id",
    "parent_route_membership", "route_label_collision", "scope", "target_plan",
])
def test_relevant_change_rejects_apply_without_effects(setup, tmp_path, change):
    if change == "candidate_restore":
        setup.parent.generated_candidates.append({"path": "restored.png", "trashed": True})
        (tmp_path / "restored.png").write_bytes(b"x")
    if change == "file_appear":
        setup.parent.generated_candidates.append({"path": "appears.png"})
    if change == "candidate_reorder":
        setup.parent.generated_candidates.append({"path": "second.png"})
        (tmp_path / "second.png").write_bytes(b"x")
    if change == "session_metadata":
        setup.session.line_generated_candidates["a"] = [{"path": "session.png", "unknown": {"nested": 1}}]
    preview = setup.preview()

    if change == "candidate_add":
        setup.parent.generated_candidates.append({"path": "new.png"})
    elif change == "candidate_remove":
        setup.parent.generated_candidates.clear()
    elif change == "candidate_reorder":
        setup.parent.generated_candidates.reverse()
    elif change == "candidate_path":
        setup.parent.generated_candidates[0]["path"] = "other.png"
    elif change == "candidate_trash":
        setup.parent.generated_candidates[0]["trashed"] = True
    elif change == "candidate_restore":
        setup.parent.generated_candidates[1]["trashed"] = False
    elif change == "persisted_metadata":
        setup.parent.generated_candidates[0]["unknown"]["nested"].append(3)
    elif change == "session_candidate":
        setup.session.line_generated_candidates["a"] = [{"path": "session.png", "unknown": 1}]
    elif change == "session_metadata":
        setup.session.line_generated_candidates["a"][0]["unknown"]["nested"] = 2
    elif change == "file_disappear":
        setup.image.unlink()
    elif change == "file_appear":
        (tmp_path / "appears.png").write_bytes(b"new")
    elif change == "file_type":
        setup.image.unlink()
        setup.image.mkdir()
    elif change == "file_size":
        setup.image.write_bytes(b"longer image")
    elif change == "file_mtime":
        old = setup.image.stat().st_mtime_ns
        os.utime(setup.image, ns=(old + 10_000_000_000, old + 10_000_000_000))
    elif change == "duplicate_route":
        setup.other.lineage_info = {"source": "candidate_route_creation", "parent_line_id": "a", "candidate_path": "a.png"}
    elif change == "source_positive":
        setup.parent.current_text = "new positive"
    elif change == "source_negative":
        setup.parent.negative_prompt = "new negative"
    elif change == "source_copied":
        setup.parent.node_path = ["changed"]
    elif change == "source_image":
        setup.parent.image_path = "changed.png"
    elif change == "source_generated_image":
        setup.parent.generated_image_path = "changed.png"
    elif change == "source_selected_image":
        setup.parent.selected_candidate_path = "changed.png"
    elif change == "target_delete":
        setup.parent.deleted = True
    elif change == "target_order":
        setup.project.prompt_lines[1:] = reversed(setup.project.prompt_lines[1:])
    elif change == "target_index":
        setup.parent.current_index += 1
    elif change == "parent_route_id":
        setup.project.prompt_lines[0].id = "different-route"
    elif change == "parent_route_membership":
        setup.project.prompt_lines.insert(1, line("new-route", 0, line_type="separator", separator_label="Other"))
    elif change == "route_label_collision":
        setup.project.prompt_lines[0].separator_label = "a.png:2 Candidates"
    elif change == "scope":
        assert_stale_without_effects_for_call(setup, preview, scope="all_lines")
        return
    elif change == "target_plan":
        assert_stale_without_effects_for_call(setup, preview, selected=["b"])
        return
    assert_stale_without_effects(setup, preview)


def assert_stale_without_effects_for_call(setup, preview, **kwargs):
    before = copy.deepcopy(setup.project)
    result = setup.apply(preview, **kwargs)
    assert result["stale_preview"] is True
    assert setup.events == []
    assert setup.project == before
    assert setup.session.project is setup.project


def test_resolved_target_change_rejects_apply(setup, tmp_path):
    preview = setup.preview()
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    (other_dir / "a.png").write_bytes(b"image")
    setup.session.current_project_path = str(other_dir / "project.json")
    assert_stale_without_effects(setup, preview)


def test_symlink_target_change_rejects_apply(setup, tmp_path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"same")
    second.write_bytes(b"same")
    link = tmp_path / "linked.png"
    try:
        link.symlink_to(first)
    except (OSError, NotImplementedError):
        pytest.skip("File symlinks are unavailable on this host")
    setup.parent.generated_candidates[0]["path"] = link.name
    preview = setup.preview()
    link.unlink()
    link.symlink_to(second)
    assert_stale_without_effects(setup, preview)


def test_session_only_candidate_record_is_materialized(setup, tmp_path):
    (tmp_path / "session.png").write_bytes(b"image")
    setup.session.line_generated_candidates["a"] = [
        {"path": "session.png", "unknown_session": {"note": "retained"}},
    ]
    preview = setup.preview()
    assert setup.apply(preview)["applied"] is True
    derived = [item for item in setup.project.prompt_lines if item.duplicated_from == "a"]
    assert len(derived) == 2
    assert derived[1].source_generation_info["source_raw_metadata"]["unknown_session"] == {
        "note": "retained"}
    assert any(item.get("unknown_session") for item in setup.parent.generated_candidates)


def test_apply_without_preview_has_no_effects(setup):
    assert_stale_without_effects(setup, None)


def test_unrelated_state_and_overwritten_source_fields_remain_fresh(setup):
    setup.parent.generated_candidates.append({"path": "trashed.png", "trashed": True, "note": "old"})
    preview = setup.preview()
    setup.project.module_library["new"] = {"body": "module"}
    setup.project.project_metadata["setting"] = 1
    setup.other.generated_candidates.append({"path": "non-target.png", "unknown": 1})
    setup.other.gallery_variants.append({"path": "variant.png"})
    setup.session.focused_line_id = "b"
    setup.session["irrelevant_ui"] = "changed"
    setup.parent.generated_candidates[1]["note"] = "new"
    setup.parent.original_text = "overwritten"
    setup.parent.tokens = ["overwritten"]
    setup.parent.source_generation_info["overwritten"] = True
    setup.parent.lineage_info["overwritten"] = True
    assert setup.preview(limit=0)["fingerprint"] == preview["fingerprint"]
    result = setup.apply(preview)
    assert result["applied"] is True
    assert result["route_count"] == result["line_count"] == 1
    assert setup.events == ["history", "graph", "save"]


def test_apply_materializes_stored_plan_after_final_recheck(setup):
    preview = setup.preview()
    original_preview = setup.ns["preview_candidate_route_creation"]

    def change_live_record_after_check(*args, **kwargs):
        current = original_preview(*args, **kwargs)
        setup.parent.generated_candidates[0]["unknown"]["nested"] = [999]
        return current

    setup.ns["preview_candidate_route_creation"] = change_live_record_after_check
    result = setup.apply(preview)
    assert result["applied"] is True
    derived = next(item for item in setup.project.prompt_lines if item.duplicated_from == "a")
    assert derived.source_generation_info["source_raw_metadata"]["unknown"] == {"nested": [1, 2]}
    assert derived.lineage_info["parent_route_id"] == "route"
    assert setup.events == ["history", "graph", "save"]
