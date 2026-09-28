"""The Global scanner publishes only a fresh reviewed Apply result."""

import ast
import copy
from pathlib import Path
import unittest

from core.global_module_candidate_apply import (
    apply_reviewed_global_module_candidates,
    build_global_module_candidate_apply_plan,
    global_module_candidate_apply_plan_is_current,
)
from core.operations import (
    get_active_tokens,
    get_project_module_library,
    scan_global_module_candidates,
)
from core.project import Project, PromptLine


class _State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class _Rerun(Exception):
    pass


class _UI:
    def __init__(self, project, scan, preview, signature):
        self.session_state = _State(
            settings={}, project=project,
            global_module_candidate_scan={"signature": signature, "scan": scan},
            global_module_candidate_apply_preview={
                "signature": {**signature, "selected_apply_names": ("X",)},
                "plan": preview[0], "preview": preview[1],
            },
        )
        self.button_clicks = set()
        self.selected_apply_names = ["X"]
        self.messages = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def expander(self, *args, **kwargs):
        return self

    def columns(self, count):
        return [self] * count

    def number_input(self, label, **kwargs):
        return kwargs["value"]

    def multiselect(self, label, **kwargs):
        return self.selected_apply_names if kwargs.get("key") == "global_module_candidate_apply_names" else []

    def button(self, label, **kwargs):
        return not kwargs.get("disabled", False) and kwargs.get("key") in self.button_clicks

    def caption(self, text, **kwargs):
        self.messages.append(str(text))

    def error(self, text, **kwargs):
        self.messages.append(str(text))

    def rerun(self):
        raise _Rerun()

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def _project():
    text = "red hair, blue eyes, outdoors"
    line = PromptLine(
        id="l1", original_file_name="source.txt", original_index=0,
        current_index=0, original_text=text, current_text=text,
        tokens=["red hair", "blue eyes", "outdoors"],
    )
    return Project(prompt_lines=[line])


def _global(body="red hair, blue eyes", core="red hair"):
    return {"X": {"body": body, "core_tokens": [core]}}


def _render(ui, current_library, history, *, apply=apply_reviewed_global_module_candidates):
    source = Path(__file__).resolve().parents[1].joinpath("app.py").read_text(encoding="utf-8")
    node = next(
        item for item in ast.parse(source).body
        if isinstance(item, ast.FunctionDef)
        and item.name == "render_global_module_candidate_scanner_section"
    )
    node.decorator_list = []
    namespace = {
        "st": ui,
        "is_free": lambda: False,
        "get_global_module_library_path": lambda settings: "unused",
        "load_global_module_library": lambda settings: current_library[0],
        "scan_global_module_candidates": scan_global_module_candidates,
        "get_project_module_library": get_project_module_library,
        "build_global_module_candidate_apply_plan": build_global_module_candidate_apply_plan,
        "global_module_candidate_apply_plan_is_current": global_module_candidate_apply_plan_is_current,
        "apply_reviewed_global_module_candidates": apply,
        "push_history": lambda **kwargs: history.append(ui.session_state.project.prompt_lines[0].current_text),
        "restore_focus_after_graph_update": lambda focus: None,
        "sync_text_areas": lambda: None,
        "render_batch_preview_text": lambda *args, **kwargs: None,
        "render_module_match_prompt_preview": lambda *args, **kwargs: None,
        "_short_preview": lambda text, limit: text,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), "app.py", "exec"), namespace)
    try:
        namespace[node.name](ui.session_state.project)
    except _Rerun:
        pass


def _reviewed_state(project, global_library):
    scan = scan_global_module_candidates(project, global_library)
    preview = build_global_module_candidate_apply_plan(project, global_library, ["X"])
    signature = {
        "global_modules": ("X",),
        "project_modules": tuple(sorted(project.module_library)),
        "line_signature": (("l1", project.prompt_lines[0].current_text),),
        "min_core_match_lines": 1,
        "example_limit": 3,
    }
    return _UI(project, scan, preview, signature)


class GlobalModuleCandidateApplyWorkspaceTests(unittest.TestCase):
    def test_opt_in_undo_snapshot_never_deepcopies_opaque_references(self):
        class Opaque:
            def __deepcopy__(self, memo):
                raise AssertionError("reference_assets copied")

        project = _project()
        refs = Opaque()
        project.module_library["X"] = {"body": "green eyes", "reference_assets": refs}
        ui = _UI(project, {"results": []}, (None, {}), {})
        ui.session_state.history = []
        source = Path(__file__).resolve().parents[1].joinpath("app.py").read_text(encoding="utf-8")
        node = next(
            item for item in ast.parse(source).body
            if isinstance(item, ast.FunctionDef) and item.name == "push_history"
        )
        namespace = {
            "st": ui,
            "copy": copy,
            "module_has_reference_assets": lambda entry: isinstance(entry, dict) and "reference_assets" in entry,
            "REFERENCE_ASSETS_FIELD": "reference_assets",
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), "app.py", "exec"), namespace)
        namespace["push_history"](preserve_module_reference_assets=True)
        self.assertEqual(1, len(ui.session_state.history))
        snapshot = ui.session_state.history[0]
        self.assertIsNot(project, snapshot)
        self.assertIs(refs, snapshot.module_library["X"]["reference_assets"])
        self.assertIsNot(project.module_library["X"], snapshot.module_library["X"])

    def test_opaque_project_reference_change_stays_current_and_is_preserved(self):
        class Opaque:
            def __iter__(self):
                raise AssertionError("reference_assets inspected")

            def __deepcopy__(self, memo):
                raise AssertionError("reference_assets copied")

        project = _project()
        project.module_library["X"] = {"body": "green eyes, smile", "reference_assets": Opaque()}
        ui = _reviewed_state(project, _global())
        newer_refs = Opaque()
        project.module_library["X"]["reference_assets"] = newer_refs
        ui.button_clicks = {"global_module_candidate_apply_btn"}
        history = []
        _render(ui, [_global()], history)
        self.assertEqual(["red hair, blue eyes, outdoors"], history)
        self.assertIs(newer_refs, ui.session_state.project.module_library["X"]["reference_assets"])
        self.assertEqual(["green eyes", "smile", "outdoors"],
                         get_active_tokens(ui.session_state.project.prompt_lines[0],
                                           module_library=ui.session_state.project.module_library))

    def test_selection_change_invalidates_preview_even_after_restoration(self):
        project = _project()
        ui = _reviewed_state(project, _global())
        ui.button_clicks = {"global_module_candidate_apply_btn"}
        ui.selected_apply_names = []
        history = []
        _render(ui, [_global()], history)
        self.assertNotIn("global_module_candidate_apply_preview", ui.session_state)

        ui.selected_apply_names = ["X"]
        _render(ui, [_global()], history)
        self.assertEqual([], history)
        self.assertNotIn("global_module_candidate_apply_preview", ui.session_state)

    def test_global_drift_invalidates_preview_even_after_exact_restoration(self):
        project = _project()
        reviewed = _global()
        ui = _reviewed_state(project, reviewed)
        library = [_global("red hair, smile")]
        history = []
        ui.button_clicks = {"global_module_candidate_apply_btn"}

        _render(ui, library, history)
        self.assertNotIn("global_module_candidate_apply_preview", ui.session_state)
        self.assertNotIn("global_module_candidate_scan", ui.session_state)
        self.assertEqual([], history)
        self.assertEqual("red hair, blue eyes, outdoors", project.prompt_lines[0].current_text)

        library[0] = reviewed
        _render(ui, library, history)
        self.assertEqual([], history)
        self.assertNotIn("global_module_candidate_apply_preview", ui.session_state)

    def test_reviewed_nonnoop_to_live_noop_does_not_push_history(self):
        project = _project()
        ui = _reviewed_state(project, _global())
        ui.button_clicks = {"global_module_candidate_apply_btn"}
        history = []
        _render(ui, [_global("yellow hat", "yellow hat")], history)
        self.assertEqual([], history)
        self.assertIs(project, ui.session_state.project)

    def test_final_gate_rejects_drift_after_renderer_check_without_history(self):
        project = _project()
        ui = _reviewed_state(project, _global())
        ui.button_clicks = {"global_module_candidate_apply_btn"}
        history = []

        def drift_while_applying(current_project, global_library, plan):
            global_library["X"]["body"] = "yellow hat"
            global_library["X"]["core_tokens"] = ["yellow hat"]
            return apply_reviewed_global_module_candidates(current_project, global_library, plan)

        _render(ui, [_global()], history, apply=drift_while_applying)
        self.assertEqual([], history)
        self.assertIs(project, ui.session_state.project)
        self.assertNotIn("global_module_candidate_apply_preview", ui.session_state)

    def test_success_pushes_one_snapshot_after_build_and_publishes_result(self):
        project = _project()
        ui = _reviewed_state(project, _global())
        ui.button_clicks = {"global_module_candidate_apply_btn"}
        history = []
        _render(ui, [_global()], history)
        self.assertEqual(["red hair, blue eyes, outdoors"], history)
        self.assertIsNot(project, ui.session_state.project)
        self.assertEqual("<mod:X>, outdoors", ui.session_state.project.prompt_lines[0].current_text)

    def test_prepublication_error_does_not_push_history_or_publish(self):
        project = _project()
        ui = _reviewed_state(project, _global())
        ui.button_clicks = {"global_module_candidate_apply_btn"}
        history = []

        def fail(*args):
            raise RuntimeError("graph failed")

        _render(ui, [_global()], history, apply=fail)
        self.assertEqual([], history)
        self.assertIs(project, ui.session_state.project)
        self.assertTrue(any("graph failed" in message for message in ui.messages))


if __name__ == "__main__":
    unittest.main()
