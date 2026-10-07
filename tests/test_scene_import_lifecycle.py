import copy
import os
import unittest
from unittest.mock import patch

from core.graph_builder import build_graph
from core.parser import parse_prompt
from core.project import Project, PromptLine
from core.route_operations import sanitize_selected_route_ids
from core.scene_import import apply_scene_import, preview_scene_import
from ui import scene_import_lifecycle as lifecycle


SOURCE_PATH = r"C:\Projects\source.json"
TARGET_PATH = r"C:\Projects\target.json"


class _State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class _History(list):
    def __init__(self, values=(), events=None):
        super().__init__(values)
        self.events = events if events is not None else []

    def append(self, value):
        self.events.append("history append")
        super().append(value)

    def pop(self, index=-1):
        self.events.append(("history pop", index))
        return super().pop(index)


def _line(line_id, text, *, index, separator=False, **values):
    fields = {
        "id": line_id,
        "original_file_name": line_id,
        "original_index": index,
        "current_index": index,
        "original_text": text,
        "current_text": text,
        "tokens": parse_prompt(text),
        "line_type": "separator" if separator else None,
        "separator_label": text if separator else None,
    }
    fields.update(values)
    return PromptLine(**fields)


def _source_project(*, body="blue eyes"):
    return Project(
        prompt_lines=[
            _line(
                "source-separator",
                "Source Scene",
                index=0,
                separator=True,
                separator_color="violet",
            ),
            _line("source-line", "<mod:hero>, red hair", index=1),
            _line("source-next", "Next Scene", index=2, separator=True),
        ],
        module_library={"hero": {"body": body}},
    )


def _target_project():
    return build_graph(
        Project(
            prompt_lines=[
                _line(
                    "target-separator",
                    "Target Scene",
                    index=0,
                    separator=True,
                ),
                _line("target-line", "existing, target", index=1),
            ],
            project_metadata={"keep": {"unrelated": ["metadata"]}},
        )
    )


def _session_state(target=None, history=None):
    state = _State(
        project=target or _target_project(),
        history=history if history is not None else _History(),
        current_project_path=TARGET_PATH,
        focused_line_id="target-line",
        highlighted_line_id="target-line",
        gallery_expanded_line_id="target-line",
        gallery_selected_route_separator_id="target-separator",
        gallery_selected_route_ids=["target-separator"],
        gallery_move_targets={"target-line": True},
        unrelated_session_value={"keep": True},
    )
    return state


def _load_from(source_project, calls=None):
    def load(path):
        if calls is not None:
            calls.append(path)
        return copy.deepcopy(source_project)

    return load


def _build_preview(state, source_project=None, *, source_path=SOURCE_PATH):
    source_project = source_project or _source_project()
    return lifecycle.build_scene_import_preview_from_source(
        source_path,
        "source-separator",
        session_state=state,
        load_project_from_json=_load_from(source_project),
    )


def _gallery_sync(state, events):
    def synchronize(project):
        events.append("gallery sync")
        selected = sanitize_selected_route_ids(
            project,
            state.get("gallery_selected_route_ids", []),
        )
        state["gallery_selected_route_ids"] = list(selected["selected_route_ids"])

    return synchronize


class SceneImportLifecycleTests(unittest.TestCase):
    def test_fresh_preview_reloads_once_stores_complete_envelope_and_never_publishes(self):
        source = _source_project()
        target = _target_project()
        target_before = copy.deepcopy(target)
        history = _History([Project(project_metadata={"history": 1})])
        history_before = list(history)
        state = _session_state(target, history)
        calls = []
        loaded_projects = []

        def load(path):
            calls.append(path)
            loaded = copy.deepcopy(source)
            loaded_projects.append(loaded)
            return loaded

        with patch.object(
            lifecycle,
            "preview_scene_import",
            wraps=preview_scene_import,
        ) as preview_spy:
            result = lifecycle.build_scene_import_preview_from_source(
                SOURCE_PATH,
                "source-separator",
                session_state=state,
                load_project_from_json=load,
            )

        self.assertTrue(result["valid"])
        self.assertTrue(result["eligible"])
        self.assertIs(result, state[lifecycle.SCENE_IMPORT_PREVIEW_KEY])
        self.assertEqual(1, len(calls))
        self.assertEqual(1, preview_spy.call_count)
        self.assertEqual(lifecycle._stored_path(SOURCE_PATH), calls[0])
        self.assertEqual(lifecycle._stored_path(SOURCE_PATH), state[lifecycle.SCENE_IMPORT_SOURCE_PATH_KEY])
        self.assertEqual("source-separator", state[lifecycle.SCENE_IMPORT_SOURCE_SEPARATOR_ID_KEY])
        self.assertEqual(target_before, target)
        self.assertEqual(history_before, list(history))
        self.assertFalse(any(value is loaded_projects[0] for value in state.values()))
        self.assertNotIn("source_project", state)
        self.assertEqual({"keep": True}, state["unrelated_session_value"])

    def test_ineligible_conflict_preview_is_stored_for_rendering(self):
        target = _target_project()
        target.module_library["hero"] = {"body": "different target meaning"}
        state = _session_state(target)

        result = _build_preview(state)

        self.assertTrue(result["valid"])
        self.assertFalse(result["eligible"])
        self.assertIs(result, state[lifecycle.SCENE_IMPORT_PREVIEW_KEY])

    def test_preview_never_loads_source_for_same_normalized_target_path(self):
        target = _target_project()
        state = _session_state(target)
        state.current_project_path = r"c:\projects\SOURCE.json"
        calls = []

        result = lifecycle.build_scene_import_preview_from_source(
            SOURCE_PATH,
            "source-separator",
            session_state=state,
            load_project_from_json=_load_from(_source_project(), calls),
        )

        self.assertFalse(result["valid"])
        self.assertEqual("same_project_path", result["reason"])
        self.assertEqual([], calls)
        self.assertNotIn(lifecycle.SCENE_IMPORT_PREVIEW_KEY, state)

    def test_preview_load_failure_has_bounded_feedback_and_preserves_inputs(self):
        state = _session_state()
        result = lifecycle.build_scene_import_preview_from_source(
            SOURCE_PATH,
            "source-separator",
            session_state=state,
            load_project_from_json=lambda _path: (_ for _ in ()).throw(
                RuntimeError("private traceback and path")
            ),
        )

        self.assertEqual("source_load_failed", result["reason"])
        self.assertEqual(SOURCE_PATH, state[lifecycle.SCENE_IMPORT_SOURCE_PATH_KEY])
        self.assertEqual("source-separator", state[lifecycle.SCENE_IMPORT_SOURCE_SEPARATOR_ID_KEY])
        self.assertNotIn(lifecycle.SCENE_IMPORT_PREVIEW_KEY, state)
        self.assertEqual(
            {"kind": "error", "code": "source_load_failed"},
            state[lifecycle.SCENE_IMPORT_FEEDBACK_KEY],
        )
        self.assertNotIn("private traceback and path", repr(state))

    def test_changing_source_path_invalidates_preview_and_apply_result(self):
        state = _session_state()
        state[lifecycle.SCENE_IMPORT_PREVIEW_KEY] = {"plan_id": "old"}
        state[lifecycle.SCENE_IMPORT_APPLY_RESULT_KEY] = {"applied": True}

        changed = lifecycle.set_scene_import_source_path(
            state,
            r"C:\Projects\other-source.json",
        )

        self.assertTrue(changed)
        self.assertNotIn(lifecycle.SCENE_IMPORT_PREVIEW_KEY, state)
        self.assertNotIn(lifecycle.SCENE_IMPORT_APPLY_RESULT_KEY, state)
        self.assertEqual("other-source.json", os.path.basename(state[lifecycle.SCENE_IMPORT_SOURCE_PATH_KEY]))

    def test_changing_selected_separator_invalidates_preview_and_apply_result(self):
        state = _session_state()
        state[lifecycle.SCENE_IMPORT_SOURCE_SEPARATOR_ID_KEY] = "source-separator"
        state[lifecycle.SCENE_IMPORT_PREVIEW_KEY] = {"plan_id": "old"}
        state[lifecycle.SCENE_IMPORT_APPLY_RESULT_KEY] = {"applied": True}

        changed = lifecycle.set_scene_import_source_separator_id(state, "another-separator")

        self.assertTrue(changed)
        self.assertNotIn(lifecycle.SCENE_IMPORT_PREVIEW_KEY, state)
        self.assertNotIn(lifecycle.SCENE_IMPORT_APPLY_RESULT_KEY, state)
        self.assertEqual("another-separator", state[lifecycle.SCENE_IMPORT_SOURCE_SEPARATOR_ID_KEY])

    def test_reset_clears_only_scene_import_operation_state(self):
        state = _session_state()
        state.update({
            lifecycle.SCENE_IMPORT_SOURCE_PATH_KEY: SOURCE_PATH,
            lifecycle.SCENE_IMPORT_SOURCE_SEPARATOR_ID_KEY: "source-separator",
            lifecycle.SCENE_IMPORT_PREVIEW_KEY: {"valid": True},
            lifecycle.SCENE_IMPORT_APPLY_RESULT_KEY: {"applied": True},
            lifecycle.SCENE_IMPORT_FEEDBACK_KEY: {"kind": "success"},
        })

        lifecycle.reset_scene_import_operation_state(state)

        self.assertFalse(any(key.startswith("scene_import_") for key in state))
        self.assertEqual({"keep": True}, state["unrelated_session_value"])
        self.assertIn("project", state)

    def test_apply_reloads_source_and_targets_active_project(self):
        first_source = _source_project()
        apply_source = _source_project()
        target = _target_project()
        state = _session_state(target)
        calls = []
        loaded = []

        def load(path):
            calls.append(path)
            project = copy.deepcopy(first_source if len(calls) == 1 else apply_source)
            loaded.append(project)
            return project

        preview = lifecycle.build_scene_import_preview_from_source(
            SOURCE_PATH,
            "source-separator",
            session_state=state,
            load_project_from_json=load,
        )
        events = []
        saved_reasons = []
        apply_calls = []
        original_apply = apply_scene_import

        def apply(source, separator, current_target, reviewed):
            events.append("core apply")
            apply_calls.append((source, separator, current_target, reviewed))
            self.assertEqual(0, len(state.history))
            return original_apply(source, separator, current_target, reviewed)

        with patch.object(lifecycle, "apply_scene_import", side_effect=apply), patch.object(
            __import__("core.scene_import", fromlist=["build_graph"]),
            "build_graph",
            wraps=__import__("core.scene_import", fromlist=["build_graph"]).build_graph,
        ) as graph_spy:
            result = lifecycle.apply_and_publish_scene_import(
                SOURCE_PATH,
                "source-separator",
                preview,
                session_state=state,
                load_project_from_json=load,
                synchronize_selected_routes=_gallery_sync(state, events),
                restore_focus_after_graph_update=lambda focus: events.append(("restore focus", focus)),
                save_current_project_if_possible=lambda reason: saved_reasons.append(reason),
            )

        self.assertTrue(result["applied"])
        self.assertEqual(2, len(calls))
        self.assertIs(apply_calls[0][0], loaded[1])
        self.assertIs(apply_calls[0][2], target)
        self.assertIs(apply_calls[0][3], preview)
        self.assertIs(state.project, target)
        self.assertEqual(1, graph_spy.call_count)
        self.assertEqual(["Scene Import applied"], saved_reasons)
        self.assertNotIn(lifecycle.SCENE_IMPORT_PREVIEW_KEY, state)
        self.assertIs(result, state[lifecycle.SCENE_IMPORT_APPLY_RESULT_KEY])
        self.assertEqual("success", state[lifecycle.SCENE_IMPORT_FEEDBACK_KEY]["kind"])
        self.assertTrue(all(value is not loaded[1] for value in state.values()))
        self.assertEqual({"keep": True}, state["unrelated_session_value"])

    def test_success_commits_pre_apply_undo_snapshot_only_after_core_success(self):
        target = _target_project()
        state = _session_state(target)
        _build_preview(state, _source_project())
        preview = state[lifecycle.SCENE_IMPORT_PREVIEW_KEY]
        before = copy.deepcopy(target)
        events = []
        history = _History([Project(project_metadata={"old": index}) for index in range(20)], events)
        originals = list(history)
        state.history = history

        original_apply = apply_scene_import

        def apply(*args):
            events.append("core apply start")
            self.assertEqual(20, len(history))
            result = original_apply(*args)
            events.append("core apply complete")
            self.assertEqual(20, len(history))
            return result

        result = None
        with patch.object(lifecycle, "apply_scene_import", side_effect=apply):
            result = lifecycle.apply_and_publish_scene_import(
                SOURCE_PATH,
                "source-separator",
                preview,
                session_state=state,
                load_project_from_json=_load_from(_source_project()),
                synchronize_selected_routes=_gallery_sync(state, events),
                restore_focus_after_graph_update=lambda focus: events.append(("restore focus", focus)),
                save_current_project_if_possible=lambda reason: events.append(("save", reason)),
            )

        self.assertTrue(result["applied"])
        self.assertEqual(20, len(history))
        self.assertTrue(all(a is b for a, b in zip(history[:-1], originals[1:])))
        self.assertEqual(before, history[-1])
        self.assertEqual(
            [
                "core apply start",
                "core apply complete",
                "history append",
                ("history pop", 0),
                "gallery sync",
                ("restore focus", "target-line"),
                ("save", "Scene Import applied"),
            ],
            events,
        )

    def test_success_preserves_and_sanitizes_gallery_state(self):
        state = _session_state()
        state.gallery_selected_route_ids = ["target-separator", "missing-route"]
        state.gallery_move_targets = {"target-line": True, "unrelated-line": True}
        preview = _build_preview(state)
        calls = []
        focus_calls = []

        result = lifecycle.apply_and_publish_scene_import(
            SOURCE_PATH,
            "source-separator",
            preview,
            session_state=state,
            load_project_from_json=_load_from(_source_project()),
            synchronize_selected_routes=_gallery_sync(state, calls),
            restore_focus_after_graph_update=lambda focus: focus_calls.append(focus),
            save_current_project_if_possible=lambda _reason: None,
        )

        self.assertTrue(result["applied"])
        self.assertEqual(["target-separator"], state.gallery_selected_route_ids)
        self.assertEqual({"target-line": True, "unrelated-line": True}, state.gallery_move_targets)
        self.assertEqual("target-separator", state.gallery_selected_route_separator_id)
        self.assertEqual("target-line", state.focused_line_id)
        self.assertEqual("target-line", state.highlighted_line_id)
        self.assertEqual("target-line", state.gallery_expanded_line_id)
        self.assertEqual(["gallery sync"], calls)
        self.assertEqual(["target-line"], focus_calls)

    def test_successful_apply_calls_autosave_exactly_once(self):
        state = _session_state()
        preview = _build_preview(state)
        save_calls = []

        result = lifecycle.apply_and_publish_scene_import(
            SOURCE_PATH,
            "source-separator",
            preview,
            session_state=state,
            load_project_from_json=_load_from(_source_project()),
            synchronize_selected_routes=lambda _project: None,
            restore_focus_after_graph_update=lambda _focus: None,
            save_current_project_if_possible=lambda reason: save_calls.append(reason),
        )

        self.assertTrue(result["applied"])
        self.assertEqual(["Scene Import applied"], save_calls)

    def test_stale_core_result_skips_all_publication_and_clears_preview(self):
        source = _source_project()
        target = _target_project()
        state = _session_state(target)
        preview = lifecycle.build_scene_import_preview_from_source(
            SOURCE_PATH,
            "source-separator",
            session_state=state,
            load_project_from_json=_load_from(source),
        )
        history_before = list(state.history)
        target_before = copy.deepcopy(target)
        source_changed = _source_project(body="new semantic body")
        publish_calls = []
        save_calls = []

        result = lifecycle.apply_and_publish_scene_import(
            SOURCE_PATH,
            "source-separator",
            preview,
            session_state=state,
            load_project_from_json=_load_from(source_changed),
            synchronize_selected_routes=lambda _project: publish_calls.append("gallery"),
            restore_focus_after_graph_update=lambda _focus: publish_calls.append("focus"),
            save_current_project_if_possible=lambda reason: save_calls.append(reason),
        )

        self.assertFalse(result["applied"])
        self.assertEqual("reviewed_preview_stale", result["reason"])
        self.assertEqual(target_before, target)
        self.assertEqual(history_before, list(state.history))
        self.assertEqual([], publish_calls)
        self.assertEqual([], save_calls)
        self.assertNotIn(lifecycle.SCENE_IMPORT_PREVIEW_KEY, state)
        self.assertIs(result, state[lifecycle.SCENE_IMPORT_APPLY_RESULT_KEY])

    def test_changed_path_or_separator_argument_invalidates_before_core_apply(self):
        for field, changed_value in (
            ("path", r"C:\Projects\other.json"),
            ("separator", "other-separator"),
        ):
            with self.subTest(field=field):
                state = _session_state()
                preview = _build_preview(state)
                values = {
                    "path": SOURCE_PATH,
                    "separator": "source-separator",
                }
                values[field] = changed_value
                calls = []
                with patch.object(lifecycle, "apply_scene_import") as apply_spy:
                    result = lifecycle.apply_and_publish_scene_import(
                        values["path"],
                        values["separator"],
                        preview,
                        session_state=state,
                        load_project_from_json=lambda _path: calls.append("load"),
                        synchronize_selected_routes=lambda _project: calls.append("gallery"),
                        restore_focus_after_graph_update=lambda _focus: calls.append("focus"),
                        save_current_project_if_possible=lambda _reason: calls.append("save"),
                    )

                self.assertFalse(result["applied"])
                self.assertEqual("source_selection_changed", result["reason"])
                self.assertEqual([], calls)
                apply_spy.assert_not_called()
                self.assertNotIn(lifecycle.SCENE_IMPORT_PREVIEW_KEY, state)

    def test_apply_rejects_same_active_target_path_before_source_load(self):
        state = _session_state()
        preview = _build_preview(state)
        state.current_project_path = r"c:\projects\SOURCE.json"
        calls = []

        result = lifecycle.apply_and_publish_scene_import(
            SOURCE_PATH,
            "source-separator",
            preview,
            session_state=state,
            load_project_from_json=lambda _path: calls.append("load"),
            synchronize_selected_routes=lambda _project: calls.append("gallery"),
            restore_focus_after_graph_update=lambda _focus: calls.append("focus"),
            save_current_project_if_possible=lambda _reason: calls.append("save"),
        )

        self.assertEqual("same_project_path", result["reason"])
        self.assertEqual([], calls)
        self.assertNotIn(lifecycle.SCENE_IMPORT_PREVIEW_KEY, state)

    def test_missing_or_session_mismatched_preview_never_applies(self):
        for stored, supplied, reason in (
            (None, None, "reviewed_preview_missing"),
            ({"plan_id": "stored"}, {"plan_id": "other"}, "reviewed_preview_session_mismatch"),
        ):
            with self.subTest(reason=reason):
                state = _session_state()
                if stored is not None:
                    state[lifecycle.SCENE_IMPORT_PREVIEW_KEY] = stored
                    state[lifecycle.SCENE_IMPORT_SOURCE_PATH_KEY] = os.path.abspath(
                        SOURCE_PATH
                    )
                    state[lifecycle.SCENE_IMPORT_SOURCE_SEPARATOR_ID_KEY] = (
                        "source-separator"
                    )
                before = copy.deepcopy(state.project)
                calls = []
                with patch.object(lifecycle, "apply_scene_import") as apply_spy:
                    result = lifecycle.apply_and_publish_scene_import(
                        SOURCE_PATH,
                        "source-separator",
                        supplied,
                        session_state=state,
                        load_project_from_json=lambda _path: calls.append("load"),
                        synchronize_selected_routes=lambda _project: calls.append("gallery"),
                        restore_focus_after_graph_update=lambda _focus: calls.append("focus"),
                        save_current_project_if_possible=lambda _reason: calls.append("save"),
                    )

                self.assertFalse(result["applied"])
                self.assertEqual(reason, result["reason"])
                self.assertEqual(before, state.project)
                self.assertEqual([], calls)
                apply_spy.assert_not_called()

    def test_source_reload_failure_during_apply_has_no_history_gallery_or_save(self):
        state = _session_state()
        preview = _build_preview(state)
        before = copy.deepcopy(state.project)
        history_before = list(state.history)
        calls = []
        def load(_path):
            raise OSError("private source path")

        # Keep the stored Preview and fail only the mandatory Apply-time reload.
        calls.append("preview already built")
        apply_result = lifecycle.apply_and_publish_scene_import(
            SOURCE_PATH,
            "source-separator",
            preview,
            session_state=state,
            load_project_from_json=load,
            synchronize_selected_routes=lambda _project: calls.append("gallery"),
            restore_focus_after_graph_update=lambda _focus: calls.append("focus"),
            save_current_project_if_possible=lambda _reason: calls.append("save"),
        )

        self.assertEqual("source_load_failed", apply_result["reason"])
        self.assertEqual(before, state.project)
        self.assertEqual(history_before, list(state.history))
        self.assertEqual(["preview already built"], calls)
        self.assertNotIn(lifecycle.SCENE_IMPORT_PREVIEW_KEY, state)
        self.assertNotIn("private source path", repr(state))

    def test_core_apply_exception_does_not_publish_history_or_exception_text(self):
        state = _session_state()
        preview = _build_preview(state)
        before = copy.deepcopy(state.project)
        history_before = list(state.history)
        calls = []
        with patch.object(
            lifecycle,
            "apply_scene_import",
            side_effect=RuntimeError("private traceback text"),
        ):
            result = lifecycle.apply_and_publish_scene_import(
                SOURCE_PATH,
                "source-separator",
                preview,
                session_state=state,
                load_project_from_json=_load_from(_source_project()),
                synchronize_selected_routes=lambda _project: calls.append("gallery"),
                restore_focus_after_graph_update=lambda _focus: calls.append("focus"),
                save_current_project_if_possible=lambda _reason: calls.append("save"),
            )

        self.assertEqual("core_apply_failed", result["reason"])
        self.assertEqual(before, state.project)
        self.assertEqual(history_before, list(state.history))
        self.assertEqual([], calls)
        self.assertNotIn("private traceback text", repr(state))
        self.assertNotIn(lifecycle.SCENE_IMPORT_PREVIEW_KEY, state)

    def test_failed_undo_snapshot_stops_before_source_load_and_core_apply(self):
        target = _target_project()
        target.clone = lambda: target
        state = _session_state(target)
        preview = _build_preview(state)
        load_calls = []

        result = lifecycle.apply_and_publish_scene_import(
            SOURCE_PATH,
            "source-separator",
            preview,
            session_state=state,
            load_project_from_json=lambda path: load_calls.append(path),
            synchronize_selected_routes=lambda _project: None,
            restore_focus_after_graph_update=lambda _focus: None,
            save_current_project_if_possible=lambda _reason: None,
        )

        self.assertEqual("undo_snapshot_failed", result["reason"])
        self.assertEqual([], load_calls)

    def test_stale_apply_clears_preview_and_never_pushes_noop_undo_entry(self):
        state = _session_state()
        preview = _build_preview(state)
        history_before = list(state.history)
        target_before = copy.deepcopy(state.project)
        state.project.prompt_lines[1].current_text = "changed target"
        stale_target = copy.deepcopy(state.project)
        calls = []

        result = lifecycle.apply_and_publish_scene_import(
            SOURCE_PATH,
            "source-separator",
            preview,
            session_state=state,
            load_project_from_json=_load_from(_source_project()),
            synchronize_selected_routes=lambda _project: calls.append("gallery"),
            restore_focus_after_graph_update=lambda _focus: calls.append("focus"),
            save_current_project_if_possible=lambda _reason: calls.append("save"),
        )

        self.assertFalse(result["applied"])
        self.assertEqual("reviewed_preview_stale", result["reason"])
        self.assertEqual(stale_target, state.project)
        self.assertNotEqual(target_before, state.project)
        self.assertEqual(history_before, list(state.history))
        self.assertEqual([], calls)
        self.assertNotIn(lifecycle.SCENE_IMPORT_PREVIEW_KEY, state)

    def test_failed_apply_result_is_stored_without_rewriting_core_evidence(self):
        state = _session_state()
        preview = _build_preview(state)
        core_result = {
            "contract_version": "promptgraph.scene-import-apply.v1",
            "operation": "scene_import",
            "applied": False,
            "reason": "reviewed_preview_stale",
            "reviewed_plan_id": preview["plan_id"],
            "projection_digest": preview["projection_digest"],
            "transfer_id": "transfer-1",
            "target_separator_id": preview["planned_separator"]["id"],
            "imported_illustration_ids": ["new-line"],
        }

        with patch.object(lifecycle, "apply_scene_import", return_value=core_result):
            result = lifecycle.apply_and_publish_scene_import(
                SOURCE_PATH,
                "source-separator",
                preview,
                session_state=state,
                load_project_from_json=_load_from(_source_project()),
                synchronize_selected_routes=lambda _project: self.fail("unexpected Gallery publication"),
                restore_focus_after_graph_update=lambda _focus: self.fail("unexpected focus restore"),
                save_current_project_if_possible=lambda _reason: self.fail("unexpected save"),
            )

        self.assertIs(core_result, result)
        self.assertIs(core_result, state[lifecycle.SCENE_IMPORT_APPLY_RESULT_KEY])
        self.assertEqual(preview["plan_id"], result["reviewed_plan_id"])
        self.assertEqual("transfer-1", result["transfer_id"])
        self.assertNotIn(lifecycle.SCENE_IMPORT_PREVIEW_KEY, state)

    def test_apply_save_exception_is_after_success_and_does_not_rollback(self):
        state = _session_state()
        preview = _build_preview(state)
        before = copy.deepcopy(state.project)
        with self.assertRaisesRegex(RuntimeError, "save failed"):
            lifecycle.apply_and_publish_scene_import(
                SOURCE_PATH,
                "source-separator",
                preview,
                session_state=state,
                load_project_from_json=_load_from(_source_project()),
                synchronize_selected_routes=lambda _project: None,
                restore_focus_after_graph_update=lambda _focus: None,
                save_current_project_if_possible=lambda _reason: (_ for _ in ()).throw(
                    RuntimeError("save failed")
                ),
            )

        self.assertNotEqual(before, state.project)
        self.assertEqual(1, len(state.history))
        self.assertEqual(before, state.history[-1])
        self.assertTrue(state[lifecycle.SCENE_IMPORT_APPLY_RESULT_KEY]["applied"])
        self.assertNotIn(lifecycle.SCENE_IMPORT_PREVIEW_KEY, state)
        self.assertEqual("success", state[lifecycle.SCENE_IMPORT_FEEDBACK_KEY]["kind"])

    def test_apply_feedback_and_result_never_retain_loaded_source_or_raw_repr(self):
        state = _session_state()
        source = _source_project()
        preview = lifecycle.build_scene_import_preview_from_source(
            SOURCE_PATH,
            "source-separator",
            session_state=state,
            load_project_from_json=_load_from(source),
        )
        loaded = copy.deepcopy(source)
        with patch.object(lifecycle, "apply_scene_import", side_effect=RuntimeError(repr(loaded))):
            result = lifecycle.apply_and_publish_scene_import(
                SOURCE_PATH,
                "source-separator",
                preview,
                session_state=state,
                load_project_from_json=lambda _path: loaded,
                synchronize_selected_routes=lambda _project: None,
                restore_focus_after_graph_update=lambda _focus: None,
                save_current_project_if_possible=lambda _reason: None,
            )

        self.assertEqual("core_apply_failed", result["reason"])
        self.assertNotIn(repr(loaded), repr(state))
        self.assertFalse(any(value is loaded for value in state.values()))


if __name__ == "__main__":
    unittest.main()
