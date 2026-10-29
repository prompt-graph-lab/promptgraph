"""Focused tests for the read-only Public Scene Module Swap H1 export UI."""

from contextlib import nullcontext
from copy import deepcopy
import json
from pathlib import Path

import pytest

from core.agent_facade import preview_scene_module_swap
from core.graph_builder import build_graph
from core.parser import parse_prompt
from core.project import Project, PromptLine
from ui import scene_module_swap_h1_export as h1_export


class _FakeStreamlit:
    def __init__(self, session_state=None, *, clicks=()):
        self.session_state = session_state if session_state is not None else {}
        self.clicks = set(clicks)
        self.messages = []
        self.downloads = []

    def expander(self, *_args, **_kwargs):
        return nullcontext()

    def selectbox(self, _label, *, options, index=0, key, format_func=None):
        current = self.session_state.get(key)
        value = current if current in options else options[index]
        self.session_state[key] = value
        return value

    def radio(self, _label, *, options, index=0, key, **_kwargs):
        current = self.session_state.get(key)
        value = current if current in options else options[index]
        self.session_state[key] = value
        return value

    def button(self, _label, *, key, **_kwargs):
        if key in self.clicks:
            self.clicks.remove(key)
            return True
        return False

    def caption(self, value):
        self.messages.append(str(value))

    def info(self, value):
        self.messages.append(str(value))

    def warning(self, value):
        self.messages.append(str(value))

    def download_button(self, label, **kwargs):
        self.downloads.append((label, kwargs))
        return False


def _project(*, illustration_count=1, prompt="red, blue", scene_label="例示 Scene"):
    lines = [
        PromptLine(
            id="scene-1",
            original_file_name="Scene",
            original_index=0,
            current_index=0,
            original_text=scene_label,
            current_text=scene_label,
            tokens=[],
            line_type="separator",
            separator_label=scene_label,
        ),
    ]
    for index in range(illustration_count):
        text = prompt if illustration_count == 1 else f"{prompt}, row {index}"
        lines.append(PromptLine(
            id=f"illustration-{index}",
            original_file_name=rf"C:\private\{index}.png",
            original_index=index,
            current_index=index + 1,
            original_text=text,
            current_text=text,
            tokens=parse_prompt(text),
        ))
    lines.append(PromptLine(
        id="scene-2",
        original_file_name="Next Scene",
        original_index=illustration_count + 1,
        current_index=illustration_count + 1,
        original_text="Next Scene",
        current_text="Next Scene",
        tokens=[],
        line_type="separator",
        separator_label="Next Scene",
    ))
    project = Project(
        source_directory=r"C:\private\project-root",
        prompt_lines=lines,
        module_library={
            "source": {"body": "red, blue", "private_metadata": "must stay private"},
            "target": {"body": "gold, green", "reference_assets": [r"C:\private\module.png"]},
        },
    )
    return build_graph(project)


def _request():
    return {
        "scene_id": "scene-1",
        "source_module_name": "source",
        "target_module_name": "target",
        "match_mode": "strict",
    }


def _render(monkeypatch, project, state=None, *, clicks=(), preview_func=None):
    fake_st = _FakeStreamlit(state, clicks=clicks)
    monkeypatch.setattr(h1_export, "st", fake_st)
    if preview_func is not None:
        monkeypatch.setattr(h1_export, "preview_scene_module_swap", preview_func)
    h1_export.render_scene_module_swap_h1_export(project, is_free=lambda: False)
    return fake_st


def test_generate_downloads_unchanged_facade_envelope_as_utf8_and_does_not_mutate_project(monkeypatch):
    project = _project()
    before = deepcopy(project)
    calls = []
    returned = []

    def preview_spy(current_project, request):
        calls.append((current_project, request.copy()))
        observation = preview_scene_module_swap(current_project, request)
        returned.append(observation)
        return observation

    state = {"current_project_path": r"C:\private\active.json"}
    fake = _render(
        monkeypatch,
        project,
        state,
        clicks={"scene_module_swap_h1_generate"},
        preview_func=preview_spy,
    )

    assert len(calls) == 1
    assert calls[0][0] is project
    assert calls[0][1] == _request()
    assert set(calls[0][1]) == {
        "scene_id", "source_module_name", "target_module_name", "match_mode",
    }
    assert len(fake.downloads) == 1
    label, download = fake.downloads[0]
    assert label == "Download H1 JSON"
    assert download["file_name"] == "scene-module-swap-h1.json"
    assert download["mime"] == "application/json"
    payload = download["data"]
    assert type(payload) is bytes
    assert json.loads(payload.decode("utf-8")) == returned[0]
    assert "例示 Scene".encode("utf-8") in payload
    assert r"C:\private" not in payload.decode("utf-8")
    assert "must stay private" not in payload.decode("utf-8")
    assert project == before


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(review_rows_truncated=True),
    lambda value: value.update(review_rows_omitted=1),
    lambda value: value.update(blocked_count=1),
    lambda value: value.update(target_ids=["other-id"]),
    lambda value: value.update(target_count=2),
    lambda value: value["scene_label"].update(truncated=True),
    lambda value: value["review_rows"][0].update(scene_order=1),
    lambda value: value["review_rows"][0]["before_positive_prompt"].update(truncated=True),
    lambda value: value["review_rows"][0]["after_positive_prompt"].update(truncated=True),
    lambda value: value["review_rows"][0]["token_delta"].update(added_truncated=True),
    lambda value: value["review_rows"][0]["token_delta"]["removed"][0].update(truncated=True),
])
def test_incomplete_or_incoherent_facade_evidence_is_not_exportable(mutation):
    observation = preview_scene_module_swap(_project(), _request())
    mutation(observation)

    status, payload = h1_export._serialize_complete_observation(observation, _request())

    assert status == "incomplete"
    assert payload is None


def test_scene_row_cap_and_utf8_byte_limit_fail_closed():
    over_row_cap = preview_scene_module_swap(_project(illustration_count=101), _request())
    assert h1_export._serialize_complete_observation(over_row_cap, _request()) == ("incomplete", None)

    oversized = preview_scene_module_swap(_project(), _request())
    oversized["future_canonical_field"] = "x" * h1_export.SCENE_MODULE_SWAP_H1_MAX_BYTES
    status, payload = h1_export._serialize_complete_observation(oversized, _request())
    assert status == "oversized"
    assert payload is None


def test_text_truncation_and_zero_change_do_not_offer_a_download():
    long_project = _project(prompt="red, blue, " + "x" * 4010)
    long = preview_scene_module_swap(long_project, _request())
    assert long["valid"] is True
    assert h1_export._serialize_complete_observation(long, _request()) == ("incomplete", None)

    no_change = preview_scene_module_swap(_project(prompt="unrelated words"), _request())
    assert no_change["valid"] is True
    assert h1_export._serialize_complete_observation(no_change, _request())[0] == "zero_change"


def test_selection_or_project_change_invalidates_snapshot_and_requires_new_click(monkeypatch):
    project = _project()
    state = {"current_project_path": "active.json"}
    first = _render(monkeypatch, project, state, clicks={"scene_module_swap_h1_generate"})
    assert len(first.downloads) == 1

    state["scene_module_swap_h1_source_module"] = "target"
    changed_selection = _render(monkeypatch, project, state)
    assert changed_selection.downloads == []
    assert h1_export.SCENE_MODULE_SWAP_H1_SNAPSHOT_KEY not in state
    assert any("選択が変わった" in message for message in changed_selection.messages)

    state["scene_module_swap_h1_source_module"] = "source"
    _render(monkeypatch, project, state, clicks={"scene_module_swap_h1_generate"})
    replacement_project = deepcopy(project)
    changed_project = _render(monkeypatch, replacement_project, state)
    assert changed_project.downloads == []
    assert h1_export.SCENE_MODULE_SWAP_H1_SNAPSHOT_KEY not in state


def test_in_place_project_edits_invalidate_snapshot(monkeypatch):
    project = _project()
    state = {"current_project_path": "active.json"}
    _render(monkeypatch, project, state, clicks={"scene_module_swap_h1_generate"})
    project.prompt_lines[1].current_text = "red, blue, changed"

    rerun = _render(monkeypatch, project, state)

    assert rerun.downloads == []
    assert h1_export.SCENE_MODULE_SWAP_H1_SNAPSHOT_KEY not in state


def test_module_or_path_change_invalidates_snapshot(monkeypatch):
    project = _project()
    state = {"current_project_path": "active.json"}
    _render(monkeypatch, project, state, clicks={"scene_module_swap_h1_generate"})
    project.module_library["target"]["body"] = "violet, orange"

    module_rerun = _render(monkeypatch, project, state)

    assert module_rerun.downloads == []
    assert h1_export.SCENE_MODULE_SWAP_H1_SNAPSHOT_KEY not in state

    _render(monkeypatch, project, state, clicks={"scene_module_swap_h1_generate"})
    state["current_project_path"] = "other.json"
    path_rerun = _render(monkeypatch, project, state)

    assert path_rerun.downloads == []
    assert h1_export.SCENE_MODULE_SWAP_H1_SNAPSHOT_KEY not in state


def test_zero_change_and_incomplete_previews_are_visible_without_download(monkeypatch):
    no_change = _project(prompt="unrelated words")
    zero = _render(
        monkeypatch,
        no_change,
        {"current_project_path": "active.json"},
        clicks={"scene_module_swap_h1_generate"},
    )
    assert zero.downloads == []
    assert any("ありません" in message and "D2" in message for message in zero.messages)

    too_many = _project(illustration_count=101)
    incomplete = _render(
        monkeypatch,
        too_many,
        {"current_project_path": "active.json"},
        clicks={"scene_module_swap_h1_generate"},
    )
    assert incomplete.downloads == []
    assert any("D1の受け入れ条件を満たさない" in message for message in incomplete.messages)


def test_facade_exception_is_generic_and_does_not_leak_details(monkeypatch):
    state = {"current_project_path": "active.json"}

    def private_failure(*_args, **_kwargs):
        raise RuntimeError(r"private C:\secret\do-not-show")

    fake = _render(
        monkeypatch,
        _project(),
        state,
        clicks={"scene_module_swap_h1_generate"},
        preview_func=private_failure,
    )

    rendered = "\n".join(fake.messages)
    assert "private" not in rendered
    assert "secret" not in rendered
    assert "do-not-show" not in rendered
    assert fake.downloads == []


def test_h1_export_is_wired_only_to_the_normal_gallery_module_swap_operation():
    root = Path(__file__).resolve().parents[1]
    source = (root / "app.py").read_text(encoding="utf-8")
    assert "from ui.scene_module_swap_h1_export import render_scene_module_swap_h1_export" in source
    branch = source.split('if active_operation == "module_swap":', 1)[1].split(
        'elif active_operation == "attribute_group_swap":', 1
    )[0]
    assert "render_module_swap_section(project)" in branch
    assert "render_scene_module_swap_h1_export(project, is_free=is_free)" in branch
    assert "render_agent_scene_module_swap_review_panel" not in branch
