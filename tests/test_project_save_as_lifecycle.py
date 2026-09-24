import unittest
from types import SimpleNamespace
from unittest import mock

from ui import project_save_as_lifecycle as lifecycle


class TracedSession(dict):
    def __init__(self, events):
        super().__init__(
            project=object(),
            current_project_path="source.json",
            settings={"before": True},
            project_save_as_pending_overwrite={"target_path": "target.json"},
            project_save_as_overwrite_acknowledged=True,
        )
        self.events = events

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        if name == "events":
            object.__setattr__(self, name, value)
        else:
            self[name] = value

    def __setitem__(self, key, value):
        self.events.append(f"set:{key}")
        super().__setitem__(key, value)

    def pop(self, key, *default):
        self.events.append(f"pop:{key}")
        return super().pop(key, *default)


class ProjectSaveAsLifecycleTests(unittest.TestCase):
    def test_new_target_is_reinspected_before_write(self):
        events = []
        state = TracedSession(events)
        first = {"kind": "missing", "normalized_path": "target.json"}
        appeared = {"kind": "file", "normalized_path": "target.json"}
        callbacks = dict(
            ensure_current_project_folder_layout=lambda _path: None,
            reset_project_assets_operation_state=lambda: None,
            default_projects_dir=lambda: "root",
            request_project_directory_discovery_refresh=lambda: None,
        )
        with (
            mock.patch.object(lifecycle, "st", SimpleNamespace(session_state=state)),
            mock.patch.object(
                lifecycle, "inspect_project_save_as_destination",
                side_effect=[first, appeared],
            ) as inspect,
            mock.patch.object(lifecycle, "save_project_to_json") as write,
        ):
            lifecycle.save_project_as_requested("target.json", **callbacks)

        self.assertEqual(2, inspect.call_count)
        self.assertEqual("target.json", inspect.call_args_list[1].args[0])
        write.assert_not_called()
        self.assertEqual(
            appeared, state["project_save_as_pending_overwrite"]["target_snapshot"]
        )
        self.assertFalse(state["project_save_as_overwrite_acknowledged"])
        self.assertEqual("source.json", state["current_project_path"])

    def test_new_target_reinspection_rejects_unsupported_destination(self):
        events = []
        state = TracedSession(events)
        first = {"kind": "missing", "normalized_path": "target.json"}
        unsupported = {"kind": "unsupported", "normalized_path": "target.json"}
        callbacks = dict(
            ensure_current_project_folder_layout=lambda _path: None,
            reset_project_assets_operation_state=lambda: None,
            default_projects_dir=lambda: "root",
            request_project_directory_discovery_refresh=lambda: None,
        )
        with (
            mock.patch.object(lifecycle, "st", SimpleNamespace(session_state=state)),
            mock.patch.object(
                lifecycle, "inspect_project_save_as_destination",
                side_effect=[first, unsupported],
            ),
            mock.patch.object(lifecycle, "save_project_to_json") as write,
        ):
            lifecycle.save_project_as_requested("target.json", **callbacks)

        write.assert_not_called()
        self.assertEqual("source.json", state["current_project_path"])
        self.assertNotIn("project_save_as_pending_overwrite", state)
        self.assertEqual(
            ("error", "Project JSONを保存できませんでした: Project JSONの保存先は通常ファイルではありません。"),
            state["project_save_as_feedback"],
        )

    def _run_commit(self, *, failure=None, target_existed=False):
        events = []
        state = TracedSession(events)
        updated_settings = {"after": True}

        def step(name, result=None):
            def callback(*_args):
                events.append(name)
                if failure == name:
                    raise RuntimeError(name)
                return result
            return callback

        callbacks = dict(
            ensure_current_project_folder_layout=step("layout"),
            reset_project_assets_operation_state=step("assets"),
            default_projects_dir=step("root", "root"),
            request_project_directory_discovery_refresh=step("refresh"),
        )
        with (
            mock.patch.object(lifecycle, "st", SimpleNamespace(session_state=state)),
            mock.patch.object(lifecycle, "save_project_to_json", step("write")),
            mock.patch.object(lifecycle, "remember_project", step("remember", updated_settings)),
            mock.patch.object(lifecycle, "save_settings", step("settings")),
            mock.patch.object(lifecycle, "project_discovery_path_is_within", step("within", True)),
        ):
            if failure:
                with self.assertRaisesRegex(RuntimeError, failure):
                    lifecycle._commit_project_save_as(
                        "target.json", target_existed=target_existed, **callbacks
                    )
            else:
                lifecycle._commit_project_save_as(
                    "target.json", target_existed=target_existed, **callbacks
                )
        return events, state, updated_settings

    def test_success_publishes_in_existing_order(self):
        events, state, updated_settings = self._run_commit()
        self.assertEqual(
            [
                "write", "set:current_project_path", "layout",
                "set:last_saved_at", "set:autosave_feedback", "remember",
                "set:settings", "settings", "assets", "root", "within",
                "refresh", "pop:project_save_as_pending_overwrite",
                "pop:project_save_as_overwrite_acknowledged",
                "set:project_save_as_overwrite_ack_reset_pending",
                "set:project_save_as_feedback",
            ],
            events,
        )
        self.assertIs(updated_settings, state["settings"])
        self.assertEqual("target.json", state["current_project_path"])
        self.assertEqual("manual save", state["autosave_feedback"])
        self.assertEqual(
            ("success", "プロジェクトを保存しました。"),
            state["project_save_as_feedback"],
        )

    def test_existing_target_does_not_request_discovery_refresh(self):
        events, _, _ = self._run_commit(target_existed=True)
        self.assertNotIn("root", events)
        self.assertNotIn("within", events)
        self.assertNotIn("refresh", events)
        self.assertLess(events.index("assets"), events.index("pop:project_save_as_pending_overwrite"))

    def test_post_write_failures_keep_exact_partial_publication(self):
        expected = {
            "layout": ["write", "set:current_project_path", "layout"],
            "remember": [
                "write", "set:current_project_path", "layout",
                "set:last_saved_at", "set:autosave_feedback", "remember",
            ],
            "settings": [
                "write", "set:current_project_path", "layout",
                "set:last_saved_at", "set:autosave_feedback", "remember",
                "set:settings", "settings",
            ],
            "assets": [
                "write", "set:current_project_path", "layout",
                "set:last_saved_at", "set:autosave_feedback", "remember",
                "set:settings", "settings", "assets",
            ],
            "refresh": [
                "write", "set:current_project_path", "layout",
                "set:last_saved_at", "set:autosave_feedback", "remember",
                "set:settings", "settings", "assets", "root", "within",
                "refresh",
            ],
        }
        for failure, prefix in expected.items():
            with self.subTest(failure=failure):
                events, state, updated_settings = self._run_commit(failure=failure)
                self.assertEqual(prefix, events)
                self.assertEqual("target.json", state["current_project_path"])
                self.assertIn("project_save_as_pending_overwrite", state)
                self.assertIn("project_save_as_overwrite_acknowledged", state)
                self.assertNotIn("project_save_as_feedback", state)
                if failure in ("settings", "assets", "refresh"):
                    self.assertIs(updated_settings, state["settings"])
                else:
                    self.assertEqual({"before": True}, state["settings"])
