"""Scene Restore keeps rejected operations out of bounded Undo history."""

import ast
import copy
from pathlib import Path
import unittest

from core.project import Project, PromptLine
from core.route_operations import (
    get_route_move_ui_state,
    remove_route_block,
    restore_removed_route,
)


class _State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class _History(list):
    def __init__(self, entries, events):
        super().__init__(entries)
        self.events = events

    def append(self, entry):
        self.events.append("history append")
        super().append(entry)

    def pop(self, index=-1):
        self.events.append(("history pop", index))
        return super().pop(index)


def _line(line_id, *, separator=False, deleted=False):
    return PromptLine(
        id=line_id, original_file_name=line_id, original_index=0,
        current_index=0, original_text=line_id, current_text=line_id,
        tokens=[line_id], line_type="separator" if separator else None,
        deleted=deleted,
    )


def _removed_project():
    project = Project(prompt_lines=[
        _line("route_a", separator=True), _line("line_a"),
        _line("pre_deleted", deleted=True),
        _line("route_b", separator=True), _line("line_b"),
    ])
    removed = remove_route_block(project, "route_a", removal_id="remove-a")
    assert removed["removed"]
    return project, removed["record"]


def _history(count, events):
    return _History(
        [Project(project_metadata={"history_marker": index}) for index in range(count)],
        events,
    )


def _run_restore(project, record, history, events, *, save_result=True,
                 fail_after_mutation=False):
    state = _State(
        project=project, history=history,
        focused_line_id="line_a", highlighted_line_id="line_b",
        gallery_expanded_line_id="line_a",
        gallery_selected_route_separator_id="route_b",
        gallery_move_targets={"route_a": True, "line_a": True, "line_b": True},
        **{"pro_trash_restore_route_confirm_remove-a": True},
        gallery_feedback="old feedback", gallery_feedback_kind="old kind",
    )

    def restore(current_project, removal_id):
        events.append("core restore")
        assert current_project is project
        if fail_after_mutation:
            current_project.prompt_lines[0].deleted = False
            raise ValueError("core interrupted")
        return restore_removed_route(current_project, removal_id)

    def build_graph(current_project):
        events.append("graph rebuild")
        assert current_project is project
        return current_project

    def route_state(*args, **kwargs):
        events.append("route ui state")
        return get_route_move_ui_state(*args, **kwargs)

    def save(reason):
        events.append(("save", reason))
        return save_result

    namespace = {
        "st": type("UI", (), {"session_state": state})(),
        "restore_removed_route": restore,
        "reset_gallery_route_action_session_state": lambda: events.append("route action reset"),
        "reset_gallery_route_move_preview_state": lambda: events.append("move preview reset"),
        "build_graph": build_graph,
        "_set_gallery_selected_route_ids_after_structure_change":
            lambda current_project: events.append("selected route sync"),
        "get_route_move_ui_state": route_state,
        "restore_focus_after_graph_update": lambda focus: events.append(("focus", focus)),
        "save_current_project_if_possible": save,
    }
    source = Path(__file__).resolve().parents[1].joinpath("app.py").read_text(encoding="utf-8")
    nodes = [
        node for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"push_history", "_restore_gallery_route_from_trash"}
    ]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), namespace)
    result = namespace["_restore_gallery_route_from_trash"](project, record)
    return state, result


class GallerySceneRestoreHistoryTests(unittest.TestCase):
    def test_no_restorable_lines_preserves_every_history_entry_at_zero_nonfull_and_cap(self):
        for count in (0, 7, 20):
            with self.subTest(count=count):
                project, record = _removed_project()
                project.prompt_lines = [
                    line for line in project.prompt_lines
                    if line.id not in {"route_a", "line_a"}
                ]
                before_project = copy.deepcopy(project)
                events = []
                history = _history(count, events)
                originals = list(history)
                state, result = _run_restore(project, record, history, events)

                self.assertFalse(result["restored"])
                self.assertEqual("no restorable lines", result["reason"])
                self.assertEqual(count, len(history))
                self.assertTrue(all(a is b for a, b in zip(history, originals)))
                self.assertEqual(list(range(count)), [
                    entry.project_metadata["history_marker"] for entry in history
                ])
                self.assertEqual(before_project, project)
                self.assertIs(state.project, project)
                self.assertTrue(state["pro_trash_restore_route_confirm_remove-a"])
                self.assertEqual("old feedback", state.gallery_feedback)
                self.assertEqual({"route_a": True, "line_a": True, "line_b": True},
                                 state.gallery_move_targets)
                self.assertEqual(["core restore"], events)

    def test_other_core_rejections_keep_history_and_confirmation(self):
        def malformed(project, record):
            project.project_metadata["route_removals"][0]["pre_remove_deleted"] = {}

        def consumed(project, record):
            project.project_metadata["route_removals"][0]["status"] = "consumed"

        def duplicate(project, record):
            project.project_metadata["route_removals"].append(copy.deepcopy(record))

        def ambiguous(project, record):
            other = copy.deepcopy(record)
            other["id"] = "remove-b"
            project.project_metadata["route_removals"].append(other)

        def not_found(project, record):
            record["id"] = "missing-removal"

        def invalid_namespace(project, record):
            project.project_metadata["route_removals"] = {"invalid": True}

        for name, setup, reason in (
            ("malformed", malformed, "malformed removal record"),
            ("consumed", consumed, "removal record already consumed"),
            ("duplicate", duplicate, "duplicate removal id"),
            ("ambiguous", ambiguous, "ambiguous active Route handle"),
            ("not found", not_found, "removal record not found"),
            ("invalid namespace", invalid_namespace, "malformed removal record"),
        ):
            with self.subTest(name=name):
                project, record = _removed_project()
                record = copy.deepcopy(record)
                setup(project, record)
                before_project = copy.deepcopy(project)
                events = []
                history = _history(20, events)
                originals = list(history)
                state, result = _run_restore(project, record, history, events)
                self.assertFalse(result["restored"])
                self.assertEqual(reason, result["reason"])
                self.assertEqual(before_project, project)
                self.assertTrue(all(a is b for a, b in zip(history, originals)))
                self.assertEqual(20, len(history))
                self.assertEqual(["core restore"], events)
                self.assertTrue(state["pro_trash_restore_route_confirm_remove-a"])
                self.assertIs(state.project, project)

    def test_success_adds_one_pre_restore_snapshot_with_ordinary_cap(self):
        for count in (7, 20):
            with self.subTest(count=count):
                project, record = _removed_project()
                original_line = project.prompt_lines[0]
                events = []
                history = _history(count, events)
                originals = list(history)
                state, result = _run_restore(project, record, history, events)

                self.assertTrue(result["restored"])
                self.assertIs(state.project, project)
                self.assertIs(project.prompt_lines[0], original_line)
                self.assertEqual(min(20, count + 1), len(history))
                self.assertTrue(all(a is b for a, b in zip(
                    history[:-1], originals[1:] if count == 20 else originals
                )))
                snapshot = history[-1]
                self.assertIsNot(snapshot, project)
                self.assertEqual("active", snapshot.project_metadata["route_removals"][0]["status"])
                self.assertEqual("consumed", project.project_metadata["route_removals"][0]["status"])
                self.assertTrue(snapshot.prompt_lines[0].deleted)
                self.assertFalse(project.prompt_lines[0].deleted)
                self.assertTrue(snapshot.prompt_lines[2].deleted)
                self.assertTrue(project.prompt_lines[2].deleted)
                self.assertEqual(1, events.count("history append"))
                self.assertEqual([("history pop", 0)] if count == 20 else [], [
                    event for event in events if isinstance(event, tuple)
                    and event[0] == "history pop"
                ])
                self.assertEqual(1, events.count(("save", "route restored")))
                self.assertNotIn("pro_trash_restore_route_confirm_remove-a", state)
                self.assertEqual({"line_b": True}, state.gallery_move_targets)
                self.assertEqual("line_a", state.focused_line_id)
                self.assertEqual("line_b", state.highlighted_line_id)
                self.assertEqual("line_a", state.gallery_expanded_line_id)
                self.assertEqual("route_a", state.gallery_selected_route_separator_id)
                self.assertEqual("success", state.gallery_feedback_kind)
                self.assertEqual([
                    "core restore", "history append",
                    *([("history pop", 0)] if count == 20 else []),
                    "route action reset", "move preview reset", "graph rebuild",
                    "selected route sync", "route ui state", ("focus", "line_a"),
                    ("save", "route restored"),
                ], events)

    def test_partial_restore_is_success_and_save_failure_does_not_rollback(self):
        project, record = _removed_project()
        project.prompt_lines = [line for line in project.prompt_lines if line.id != "line_a"]
        events = []
        history = _history(0, events)
        state, result = _run_restore(project, record, history, events, save_result=False)

        self.assertTrue(result["restored"])
        self.assertEqual("partial restore with missing lines", result["reason"])
        self.assertEqual(["line_a"], result["missing_line_ids"])
        self.assertEqual(1, len(history))
        self.assertEqual("active", history[0].project_metadata["route_removals"][0]["status"])
        self.assertEqual("consumed", project.project_metadata["route_removals"][0]["status"])
        self.assertFalse(project.prompt_lines[0].deleted)
        self.assertTrue(next(line for line in project.prompt_lines if line.id == "pre_deleted").deleted)
        self.assertEqual([("save", "route restored")], [
            event for event in events if isinstance(event, tuple) and event[0] == "save"
        ])
        self.assertEqual("success", state.gallery_feedback_kind)
        self.assertEqual("Restored Scene 'route_a'.", state.gallery_feedback)

    def test_core_exception_preserves_partial_mutation_and_undo_snapshot(self):
        project, record = _removed_project()
        original_line = project.prompt_lines[0]
        events = []
        history = _history(20, events)
        originals = list(history)

        with self.assertRaisesRegex(ValueError, "core interrupted"):
            _run_restore(project, record, history, events, fail_after_mutation=True)

        self.assertIs(project.prompt_lines[0], original_line)
        self.assertFalse(original_line.deleted)
        self.assertTrue(history[-1].prompt_lines[0].deleted)
        self.assertTrue(all(a is b for a, b in zip(history[:-1], originals[1:])))
        self.assertEqual(20, len(history))
        self.assertEqual(["core restore", "history append", ("history pop", 0)], events)


if __name__ == "__main__":
    unittest.main()
