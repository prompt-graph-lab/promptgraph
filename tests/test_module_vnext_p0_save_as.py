"""Module vNext P0: JSON-only Advanced Save As keeps `reference_assets` resolvable.

Synthetic Projects in temporary directories only. No Module asset file is
read, copied or created by Save As.
"""

import builtins
import copy
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core.io import save_project_to_json
from core.module_container_policy import (
    MODULE_ASSET_NAMESPACE,
    MODULE_REFERENCE_ASSETS_SAVE_AS_OTHER_FOLDER_MESSAGE,
    MODULE_REFERENCE_ASSETS_SAVE_AS_UNKNOWN_ROOT_MESSAGE,
    REFERENCE_ASSETS_FIELD,
    module_reference_assets_json_save_as_block_reason,
    project_has_module_reference_assets,
)
from core.project import Project
from ui import project_save_as_lifecycle as lifecycle

ASSET_NAME = "d" * 64 + ".png"
ASSET_PATH = "refs/modules/" + ASSET_NAME


def _reference_assets():
    return {
        "format": 1,
        "assets": [{
            "id": "front",
            "role": "character_reference",
            "media_type": "image/png",
            "path": ASSET_PATH,
            "sha256": "d" * 64,
        }],
    }


def _project(with_assets=True):
    project = Project()
    project.module_library = {"char": {"body": "red hair", "notes": "keep"}}
    if with_assets:
        project.module_library["char"][REFERENCE_ASSETS_FIELD] = _reference_assets()
    return project


class _Session(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


CALLBACKS = dict(
    ensure_current_project_folder_layout=lambda _path: None,
    reset_project_assets_operation_state=lambda: None,
    default_projects_dir=lambda: "",
    request_project_directory_discovery_refresh=lambda: None,
)


class SaveAsGateHelperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "project").mkdir()
        (self.root / "other").mkdir()
        self.current = self.root / "project" / "project.json"

    def tearDown(self):
        self.temp.cleanup()

    def test_projects_without_reference_assets_are_never_restricted(self):
        for project in (_project(with_assets=False), Project(), object(), None):
            self.assertFalse(project_has_module_reference_assets(project))
            self.assertEqual("", module_reference_assets_json_save_as_block_reason(
                project, "", self.root / "other" / "x.json"))

    def test_same_folder_is_allowed_other_folder_is_refused(self):
        project = _project()
        self.assertEqual("", module_reference_assets_json_save_as_block_reason(
            project, self.current, self.root / "project" / "copy.json"))
        self.assertEqual("", module_reference_assets_json_save_as_block_reason(
            project, self.current, str(self.root / "project" / ".." / "project" / "copy.json")))
        self.assertEqual(
            MODULE_REFERENCE_ASSETS_SAVE_AS_OTHER_FOLDER_MESSAGE,
            module_reference_assets_json_save_as_block_reason(
                project, self.current, self.root / "other" / "copy.json"),
        )
        self.assertEqual(
            MODULE_REFERENCE_ASSETS_SAVE_AS_OTHER_FOLDER_MESSAGE,
            module_reference_assets_json_save_as_block_reason(
                project, self.current, self.root / "project" / "sub" / "copy.json"),
        )
        self.assertEqual(
            MODULE_REFERENCE_ASSETS_SAVE_AS_OTHER_FOLDER_MESSAGE,
            module_reference_assets_json_save_as_block_reason(project, self.current, ""),
        )

    def test_unknown_current_root_fails_closed(self):
        project = _project()
        for current in ("", None, self.root / "missing-folder" / "project.json"):
            self.assertEqual(
                MODULE_REFERENCE_ASSETS_SAVE_AS_UNKNOWN_ROOT_MESSAGE,
                module_reference_assets_json_save_as_block_reason(
                    project, current, self.root / "project" / "copy.json"),
            )

    def test_messages_are_content_free(self):
        for message in (
            MODULE_REFERENCE_ASSETS_SAVE_AS_OTHER_FOLDER_MESSAGE,
            MODULE_REFERENCE_ASSETS_SAVE_AS_UNKNOWN_ROOT_MESSAGE,
        ):
            self.assertNotIn("refs/modules", message)
            self.assertNotIn("char", message)
            self.assertIn("Duplicate Project", message)


class SaveAsLifecycleGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project_dir = self.root / "project"
        self.other_dir = self.root / "other"
        managed = self.project_dir.joinpath(*MODULE_ASSET_NAMESPACE)
        managed.mkdir(parents=True)
        self.other_dir.mkdir()
        self.asset_file = managed / ASSET_NAME
        self.asset_file.write_bytes(b"synthetic asset bytes")
        self.current = str(self.project_dir / "project.json")
        self.opened_paths = []

    def tearDown(self):
        self.temp.cleanup()

    def _run(self, project, action, *, current=None, extra_state=None):
        state = _Session(
            project=project,
            current_project_path=self.current if current is None else current,
            settings={},
        )
        state.update(extra_state or {})
        real_open = builtins.open

        def tracking_open(file, *args, **kwargs):
            self.opened_paths.append(os.fspath(file) if not isinstance(file, int) else "")
            return real_open(file, *args, **kwargs)

        with (
            mock.patch.object(lifecycle, "st", SimpleNamespace(session_state=state)),
            mock.patch.object(lifecycle, "save_settings"),
            mock.patch("builtins.open", tracking_open),
            mock.patch("shutil.copy2") as copy2,
            mock.patch("shutil.copyfile") as copyfile,
            mock.patch("shutil.copytree") as copytree,
        ):
            action(state)
        copy2.assert_not_called()
        copyfile.assert_not_called()
        copytree.assert_not_called()
        return state

    def _saved(self, with_assets=True):
        project = _project(with_assets=with_assets)
        save_project_to_json(project, self.current)
        return project

    def _assert_no_module_asset_work(self):
        self.assertEqual(b"synthetic asset bytes", self.asset_file.read_bytes())
        for path in self.opened_paths:
            self.assertNotIn("/".join(MODULE_ASSET_NAMESPACE), path.replace(os.sep, "/"))
        self.assertFalse(self.other_dir.joinpath("refs").exists())

    def _assert_refused(self, state, project, library_before, message):
        self.assertEqual(self.current, state["current_project_path"])
        self.assertIs(project, state["project"])
        self.assertEqual(library_before, project.module_library)
        self.assertNotIn(lifecycle.PROJECT_SAVE_AS_PENDING_OVERWRITE_KEY, state)
        self.assertEqual(("error", message), state[lifecycle.PROJECT_SAVE_AS_FEEDBACK_KEY])
        self.assertNotIn(ASSET_PATH, message)

    def test_same_directory_save_as_succeeds(self):
        project = self._saved()
        target = self.project_dir / "project-copy.json"

        state = self._run(project, lambda _s: lifecycle.save_project_as_requested(
            str(target), **CALLBACKS))

        self.assertTrue(target.is_file())
        self.assertIn(ASSET_PATH, target.read_text(encoding="utf-8"))
        self.assertEqual(os.path.abspath(target), state["current_project_path"])
        self.assertEqual("success", state[lifecycle.PROJECT_SAVE_AS_FEEDBACK_KEY][0])
        self._assert_no_module_asset_work()

    def test_other_directory_missing_target_is_refused_and_not_created(self):
        project = self._saved()
        library_before = copy.deepcopy(project.module_library)
        target = self.other_dir / "project.json"

        state = self._run(project, lambda _s: lifecycle.save_project_as_requested(
            str(target), **CALLBACKS))

        self.assertFalse(target.exists())
        self._assert_refused(state, project, library_before,
                             MODULE_REFERENCE_ASSETS_SAVE_AS_OTHER_FOLDER_MESSAGE)
        self._assert_no_module_asset_work()

    def test_other_directory_existing_target_is_not_armed_or_overwritten(self):
        project = self._saved()
        library_before = copy.deepcopy(project.module_library)
        target = self.other_dir / "project.json"
        target.write_bytes(b'{"existing": true}')

        state = self._run(project, lambda _s: lifecycle.save_project_as_requested(
            str(target), **CALLBACKS))

        self.assertEqual(b'{"existing": true}', target.read_bytes())
        self._assert_refused(state, project, library_before,
                             MODULE_REFERENCE_ASSETS_SAVE_AS_OTHER_FOLDER_MESSAGE)
        self._assert_no_module_asset_work()

    def test_project_without_reference_assets_keeps_cross_directory_behavior(self):
        project = self._saved(with_assets=False)
        target = self.other_dir / "project.json"

        state = self._run(project, lambda _s: lifecycle.save_project_as_requested(
            str(target), **CALLBACKS))

        self.assertTrue(target.is_file())
        self.assertEqual(os.path.abspath(target), state["current_project_path"])
        self.assertEqual("success", state[lifecycle.PROJECT_SAVE_AS_FEEDBACK_KEY][0])

    def test_unsaved_project_with_reference_assets_fails_closed(self):
        project = self._saved()
        library_before = copy.deepcopy(project.module_library)
        target = self.project_dir / "project-copy.json"
        state = _Session(project=project, current_project_path="", settings={})

        with (
            mock.patch.object(lifecycle, "st", SimpleNamespace(session_state=state)),
            mock.patch.object(lifecycle, "save_settings"),
        ):
            lifecycle.save_project_as_requested(str(target), **CALLBACKS)

        self.assertFalse(target.exists())
        self.assertEqual("", state["current_project_path"])
        self.assertEqual(library_before, project.module_library)
        self.assertEqual(
            ("error", MODULE_REFERENCE_ASSETS_SAVE_AS_UNKNOWN_ROOT_MESSAGE),
            state[lifecycle.PROJECT_SAVE_AS_FEEDBACK_KEY],
        )

    def test_armed_confirmation_cannot_bypass_the_gate(self):
        # Arm an overwrite while the Project carries no reference_assets, then
        # the same Project object gains them before the confirmation click.
        project = self._saved(with_assets=False)
        target = self.other_dir / "project.json"
        target.write_bytes(b'{"existing": true}')

        def arm_then_confirm(state):
            state["save_project_json_path"] = str(target)
            lifecycle.save_project_as_requested(str(target), **CALLBACKS)
            self.assertIn(lifecycle.PROJECT_SAVE_AS_PENDING_OVERWRITE_KEY, state)
            state[lifecycle.PROJECT_SAVE_AS_OVERWRITE_ACK_KEY] = True
            project.module_library["char"][REFERENCE_ASSETS_FIELD] = _reference_assets()
            lifecycle.confirm_project_save_as_overwrite(**CALLBACKS)

        state = self._run(project, arm_then_confirm)

        self.assertEqual(b'{"existing": true}', target.read_bytes())
        self._assert_refused(state, project, copy.deepcopy(project.module_library),
                             MODULE_REFERENCE_ASSETS_SAVE_AS_OTHER_FOLDER_MESSAGE)
        self._assert_no_module_asset_work()

    def test_same_directory_confirmed_overwrite_still_works(self):
        project = self._saved()
        target = self.project_dir / "existing.json"
        target.write_bytes(b'{"existing": true}')

        def arm_then_confirm(state):
            state["save_project_json_path"] = str(target)
            lifecycle.save_project_as_requested(str(target), **CALLBACKS)
            state[lifecycle.PROJECT_SAVE_AS_OVERWRITE_ACK_KEY] = True
            lifecycle.confirm_project_save_as_overwrite(**CALLBACKS)

        state = self._run(project, arm_then_confirm)

        self.assertIn(ASSET_PATH, target.read_text(encoding="utf-8"))
        self.assertEqual(os.path.abspath(target), state["current_project_path"])
        self.assertEqual("success", state[lifecycle.PROJECT_SAVE_AS_FEEDBACK_KEY][0])
        self._assert_no_module_asset_work()

    def test_commit_itself_refuses_as_the_last_line_of_defense(self):
        project = self._saved()
        target = self.other_dir / "project.json"

        def commit_directly(_state):
            with self.assertRaises(ValueError):
                lifecycle._commit_project_save_as(
                    str(target), target_existed=False, **CALLBACKS)

        state = self._run(project, commit_directly)

        self.assertFalse(target.exists())
        self.assertEqual(self.current, state["current_project_path"])


if __name__ == "__main__":
    unittest.main()
