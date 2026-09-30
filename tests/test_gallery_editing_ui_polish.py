import ast
from pathlib import Path
from types import SimpleNamespace


APP_SOURCE = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
APP_TREE = ast.parse(APP_SOURCE)


def function_source(name):
    node = next(
        item for item in APP_TREE.body
        if isinstance(item, ast.FunctionDef) and item.name == name
    )
    return ast.get_source_segment(APP_SOURCE, node)


class SessionState(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class Rerun(Exception):
    pass


class FakeStreamlit:
    def __init__(self):
        self.session_state = SessionState(gallery_expanded_line_id=None)
        self.events = []
        self.clicked_key = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def columns(self, count):
        return [self] * (count if isinstance(count, int) else len(count))

    def button(self, label, **kwargs):
        self.events.append(("button", label, kwargs))
        return kwargs.get("key") == self.clicked_key

    def info(self, value):
        self.events.append(("info", value))

    def caption(self, _value):
        pass

    def markdown(self, _value):
        pass

    def text_input(self, *_args, **_kwargs):
        pass

    def text_area(self, *_args, **_kwargs):
        pass

    def rerun(self):
        raise Rerun


def make_card_renderer(st):
    namespace = {
        "st": st,
        "is_workbench_line": lambda line: line.workbench,
        "current_route_color_for_line": lambda *_args: "",
        "_line_thumbnail_path": lambda _line: "",
        "_workbench_thumbnail_path": lambda *_args: "",
        "_workbench_source_label": lambda *_args: "source",
        "workbench_title": lambda line: line.original_file_name,
        "_prompt_original_status_label": lambda _line: "Prompt: original",
        "_line_generated_candidate_count": lambda _line: 0,
        "_line_trashed_generated_candidates": lambda _line: [],
        "render_gallery_variant_card_controls": lambda *_args, **_kwargs: None,
    }
    exec(function_source("render_gallery_workbench_card"), namespace)
    exec(function_source("render_gallery_normal_line_card"), namespace)
    return namespace["render_gallery_normal_line_card"]


def render_card(renderer, st, line, expanded, click=False):
    st.events.clear()
    st.clicked_key = f"pro_gallery_edit_{line.id}" if click else None
    try:
        renderer(object(), line, 0, [line], {}, [], expanded)
    except Rerun:
        assert click
    edit_buttons = [
        (event[1], event[2]) for event in st.events
        if event[0] == "button" and event[2].get("key") == f"pro_gallery_edit_{line.id}"
    ]
    assert len(edit_buttons) == 1
    return edit_buttons[0]


def test_gallery_card_open_move_close_uses_only_existing_expanded_line_state():
    st = FakeStreamlit()
    renderer = make_card_renderer(st)
    first = SimpleNamespace(id="first", workbench=False, current_index=0, original_file_name="one.png")
    second = SimpleNamespace(id="second", workbench=False, current_index=1, original_file_name="two.png")

    assert render_card(renderer, st, first, None, click=True)[0:1] == ("編集",)
    assert st.session_state.gallery_expanded_line_id == "first"
    assert render_card(renderer, st, first, "first") == (
        "編集を閉じる",
        {"key": "pro_gallery_edit_first", "type": "primary"},
    )
    assert ("info", "編集中") in st.events

    assert render_card(renderer, st, second, "first", click=True)[1]["type"] == "secondary"
    assert st.session_state.gallery_expanded_line_id == "second"
    assert render_card(renderer, st, first, "second")[0] == "編集"
    assert ("info", "編集中") not in st.events

    render_card(renderer, st, second, "second", click=True)
    assert st.session_state.gallery_expanded_line_id is None
    assert set(st.session_state) == {"gallery_expanded_line_id"}


def test_workbench_card_shows_same_active_edit_indicator():
    st = FakeStreamlit()
    renderer = make_card_renderer(st)
    line = SimpleNamespace(id="bench", workbench=True, current_index=0, original_file_name="Bench", workbench_note="")

    assert render_card(renderer, st, line, "bench") == (
        "編集を閉じる",
        {"key": "pro_gallery_edit_bench", "type": "primary"},
    )
    assert ("info", "編集中") in st.events
    render_card(renderer, st, line, "bench", click=True)
    assert st.session_state.gallery_expanded_line_id is None
    assert st.session_state.highlighted_line_id == "bench"


def test_editor_heading_identifies_the_illustration_by_existing_label():
    class StopAfterHeading:
        def markdown(self, value):
            self.heading = value

        def columns(self, _widths):
            raise Rerun

    st = StopAfterHeading()
    namespace = {
        "st": st,
        "_consume_gallery_prompt_widget_sync": lambda _line: None,
        "get_prompt_line_label": lambda _line: "Scene 2 / Illustration 3",
    }
    exec(function_source("render_gallery_line_editor"), namespace)
    try:
        namespace["render_gallery_line_editor"](object(), object())
    except Rerun:
        pass
    assert st.heading == "#### イラストを編集中: `Scene 2 / Illustration 3`"
