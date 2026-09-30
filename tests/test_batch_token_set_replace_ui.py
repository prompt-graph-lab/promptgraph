"""Production Batch renderer with real Streamlit widgets and core transforms."""

import ast
from functools import lru_cache
from pathlib import Path
from textwrap import dedent

import pytest
from streamlit.testing.v1 import AppTest


@lru_cache(maxsize=1)
def app_script():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    names = [
        "resolve_gallery_operation_targets", "resolve_batch_edit_target_line_ids",
        "initialize_batch_edit_defaults", "render_batch_preview_text",
        "render_compact_batch_preview_example", "render_batch_editing_section",
    ]
    functions = {
        node.name: ast.get_source_segment(source, node)
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name in names
    }
    setup = dedent("""
        import html
        import streamlit as st
        from core.project import Project, PromptLine
        from core.parser import parse_prompt
        from core.operations import *
        from core.operations import apply_batch_text_edit as core_apply
        from core.batch_preview import (
            _highlight_literal_matches, _highlight_token_matches,
            _highlight_replace_result_tokens, _highlight_duplicate_tokens,
            _batch_preview_focus_text, _removed_marker_preview, _shorten_preview_text,
        )
        from core.prompt_line_selection import get_visible_prompt_lines, is_gallery_operation_prompt_line

        def is_free():
            return False

        def render_selection_action_bar(_project):
            pass

        def render_batch_token_reorder_section(_project):
            pass

        def render_selected_line_batch_actions(_project, _ids):
            pass

        def get_line_by_id(project, line_id):
            return next((line for line in project.prompt_lines if line.id == line_id), None)

        def get_selected_line_ids(_project):
            return list(st.session_state.selected_ids)

        def batch_scope_options(_project, **_kwargs):
            return {"all": "All Illustrations", "focus": "Focus Illustration only",
                    "selected": "Selected Illustrations", "group::bundle": "Illustration Group: bundle"}

        def _render_gallery_operation_target_summary(_resolution):
            pass

        def format_core_message_for_display(value):
            return str(value or "")

        def _short_preview(text, limit):
            return text[:limit]

        def push_history():
            st.session_state.events.append("history")
            st.session_state.history.append(st.session_state.project.clone())

        def apply_batch_text_edit(*args, **kwargs):
            st.session_state.events.append("apply")
            st.session_state.apply_arguments = kwargs
            return core_apply(*args, **kwargs)

        def restore_focus_after_graph_update(_focus):
            st.session_state.events.append("focus")

        def sync_text_areas():
            st.session_state.events.append("text")
        """)
    production = "\n\n".join(functions[name] for name in names)
    main = dedent("""

        if "project" not in st.session_state:
            def make_line(line_id, text):
                return PromptLine(id=line_id, original_file_name=line_id + ".png",
                                  original_index=0, current_index=0, original_text=text,
                                  current_text=text, tokens=parse_prompt(text))
            st.session_state.project = Project(prompt_lines=[
                make_line("one", "header, (white shirt:1.7), sky, red skirt"),
                make_line("two", "red skirt, pose, white shirt"),
            ], line_groups={"bundle": ["two"]})
            st.session_state.batch_edit_operation_v14 = "replace"
            st.session_state.batch_edit_scope = "all"
            st.session_state.batch_edit_search_text = "white shirt, red skirt"
            st.session_state.batch_edit_edit_text = "black dress, (white apron:1.2)"
            st.session_state.batch_edit_preserve_replace_weights = True
            st.session_state.focused_line_id = "two"
            st.session_state.selected_ids = ["two"]
            st.session_state.events = []
            st.session_state.history = []
        render_batch_editing_section(st.session_state.project)
        """)
    return setup + "\n" + production + "\n" + main


def start_token_set():
    app = AppTest.from_string(app_script(), default_timeout=30).run(timeout=30)
    assert not app.exception
    # The existing default stays Contains, rather than being changed to the new mode.
    assert app.radio(key="batch_edit_replace_match_mode").value == "contains_token"
    app.radio(key="batch_edit_replace_match_mode").set_value("token_set").run(timeout=30)
    assert not app.exception
    return app


@pytest.mark.parametrize("scope", ["all", "focus", "selected", "group::bundle"])
def test_token_set_preview_apply_scope_and_existing_publication_order(scope):
    app = start_token_set()
    assert "Prompt token set (N → M)" in app.radio(key="batch_edit_replace_match_mode").options
    assert not any(item.key == "batch_edit_preserve_replace_weights" for item in app.checkbox)
    app.selectbox(key="batch_edit_scope").set_value(scope).run(timeout=30)
    app.button(key="batch_edit_preview_btn").click().run(timeout=30)
    assert not app.exception
    stored = app.session_state["batch_edit_preview"]
    assert stored["signature"]["replace_match_mode"] == "token_set"
    assert stored["signature"]["preserve_replace_weights"] is False
    assert stored["preview"]["affected_line_count"] == (2 if scope == "all" else 1)
    reviewed = {item["line_id"]: item["after"] for item in stored["preview"]["examples"]}
    before = {line.id: line.current_text for line in app.session_state["project"].prompt_lines}
    assert len(app.session_state["history"]) == 0
    assert app.session_state["events"] == []
    # Full before/after remains available alongside the multi-token highlights.
    assert set(item.value for item in app.text) >= set(reviewed.values())
    assert any(item.value.count("background-color:#cfe8ff;") == 2 for item in app.markdown)
    app.button(key="batch_edit_apply_top_btn").click().run(timeout=30)
    assert not app.exception
    assert app.session_state["events"] == ["history", "apply", "focus", "text"]
    assert app.session_state["apply_arguments"]["preserve_replace_weights"] is False
    assert len(app.session_state["history"]) == 1
    snapshot = app.session_state["history"][0]
    assert {line.id: line.current_text for line in snapshot.prompt_lines} == before
    assert "batch_edit_preview" not in app.session_state
    result = {line.id: line.current_text for line in app.session_state["project"].prompt_lines}
    assert result == {line_id: reviewed.get(line_id, text) for line_id, text in before.items()}


@pytest.mark.parametrize("field,value", [
    ("batch_edit_search_text", "white shirt, (white shirt:1.2)"),
    ("batch_edit_search_text", "<mod:outfit>, white shirt"),
    ("batch_edit_edit_text", "white apron, </mod:outfit>"),
    ("batch_edit_edit_text", ", ,"),
])
def test_token_set_invalid_input_disables_preview_without_history_or_mutation(field, value):
    app = start_token_set()
    original = [line.current_text for line in app.session_state["project"].prompt_lines]
    app.text_input(key=field).set_value(value).run(timeout=30)
    assert not app.exception
    assert app.button(key="batch_edit_preview_btn").disabled
    assert any("Token set mode requires" in item.value for item in app.warning)
    assert [line.current_text for line in app.session_state["project"].prompt_lines] == original
    assert app.session_state["events"] == []
    assert app.session_state["history"] == []


def test_switching_mode_invalidates_preview_and_restores_legacy_weight_checkbox():
    app = start_token_set()
    app.button(key="batch_edit_preview_btn").click().run(timeout=30)
    assert not app.exception
    old_signature = app.session_state["batch_edit_preview"]["signature"].copy()
    app.radio(key="batch_edit_replace_match_mode").set_value("exact_token").run(timeout=30)
    assert not app.exception
    assert app.checkbox(key="batch_edit_preserve_replace_weights").value is True
    assert not any(item.key == "batch_edit_apply_top_btn" for item in app.button)
    assert any("Preview is out of date" in item.value for item in app.caption)
    assert app.session_state["batch_edit_preview"]["signature"] == old_signature
    assert app.session_state["events"] == []
