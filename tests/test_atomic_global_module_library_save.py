import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

from core.io import (
    SetEncoder,
    get_global_module_library_path,
    load_global_module_library,
    save_global_module_library,
)
from core.operations import normalize_module_library
from core.project import Project


class AtomicGlobalModuleLibrarySaveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = {
            "global_module_library_dir": str(self.root / "module-library")
        }

    def tearDown(self):
        self.temp.cleanup()

    def _library(self):
        return {
            "character": {
                "body": "alpha, beta",
                "description": "base fixture",
                "notes": "keep notes",
                "extension_metadata": {
                    "future_key": "keep",
                    "nested": {"value": 1},
                },
            },
            "outfit": {
                "body": "red dress, ribbon",
                "category": "Outfit",
                "animadex_metadata": {"source_id": "synthetic"},
            },
            "pose": {"body": "standing, looking at viewer"},
        }

    def _path(self):
        return Path(get_global_module_library_path(self.settings))

    @staticmethod
    def _partial_dump(_data, handle, **_kwargs):
        handle.write('{\n  "character": {"body": "partial')
        handle.flush()
        raise OSError("synthetic disk full after partial library write")

    @staticmethod
    def _temp_files(library_path):
        library_path = Path(library_path)
        return list(
            library_path.parent.glob(f".{library_path.name}.*.tmp")
        )

    def test_existing_destination_survives_partial_dump_failure(self):
        library_path = Path(
            save_global_module_library(self._library(), self.settings)
        )
        before = library_path.read_bytes()
        before_digest = hashlib.sha256(before).hexdigest()

        updated = self._library()
        updated["new-module"] = {"body": "must not persist"}
        with mock.patch("core.io.json.dump", side_effect=self._partial_dump):
            with self.assertRaisesRegex(OSError, "synthetic disk full"):
                save_global_module_library(updated, self.settings)

        after = library_path.read_bytes()
        self.assertEqual(before, after)
        self.assertEqual(before_digest, hashlib.sha256(after).hexdigest())
        json.loads(library_path.read_text(encoding="utf-8"))
        self.assertEqual(
            normalize_module_library(self._library()),
            load_global_module_library(self.settings),
        )
        self.assertEqual([], self._temp_files(library_path))

    def test_first_save_failure_leaves_no_destination_or_temp(self):
        library_path = self._path()

        with mock.patch("core.io.json.dump", side_effect=self._partial_dump):
            with self.assertRaisesRegex(OSError, "synthetic disk full"):
                save_global_module_library(self._library(), self.settings)

        self.assertFalse(library_path.exists())
        self.assertEqual({}, load_global_module_library(self.settings))
        self.assertEqual([], self._temp_files(library_path))

    def test_successful_replacement_preserves_legacy_successful_bytes(self):
        save_global_module_library(
            {"old": {"body": "old body"}},
            self.settings,
        )
        updated = self._library()
        normalized = normalize_module_library(copy.deepcopy(updated))
        expected_text = json.dumps(
            normalized,
            cls=SetEncoder,
            indent=2,
            ensure_ascii=False,
        )
        expected_bytes = expected_text.replace("\n", os.linesep).encode(
            "utf-8"
        )

        returned_path = save_global_module_library(updated, self.settings)
        library_path = self._path()

        self.assertEqual(str(library_path), returned_path)
        self.assertEqual(expected_bytes, library_path.read_bytes())
        self.assertEqual(normalized, load_global_module_library(self.settings))
        self.assertEqual([], self._temp_files(library_path))
        self.assertEqual(
            "keep",
            load_global_module_library(self.settings)["character"][
                "extension_metadata"
            ]["future_key"],
        )

    def test_unicode_directory_name_and_content_round_trip(self):
        settings = {
            "global_module_library_dir": str(self.root / "共有モジュール")
        }
        library = {
            "みるく": {
                "body": "笑顔, 青い瞳",
                "description": "日本語fixture",
                "notes": "保存成功",
                "extension_metadata": {"future_key": "維持"},
            }
        }

        library_path = Path(save_global_module_library(library, settings))
        reopened = load_global_module_library(settings)

        self.assertEqual("笑顔, 青い瞳", reopened["みるく"]["body"])
        self.assertEqual(
            "維持",
            reopened["みるく"]["extension_metadata"]["future_key"],
        )
        self.assertEqual([], self._temp_files(library_path))

    def test_fsync_failure_preserves_destination_and_removes_temp(self):
        library_path = Path(
            save_global_module_library(self._library(), self.settings)
        )
        before = library_path.read_bytes()

        with mock.patch(
            "core.io.os.fsync",
            side_effect=OSError("synthetic library fsync failure"),
        ):
            with self.assertRaisesRegex(OSError, "synthetic library fsync"):
                save_global_module_library(
                    {"replacement": {"body": "new"}},
                    self.settings,
                )

        self.assertEqual(before, library_path.read_bytes())
        self.assertEqual([], self._temp_files(library_path))

    def test_replace_failure_preserves_destination_and_removes_temp(self):
        library_path = Path(
            save_global_module_library(self._library(), self.settings)
        )
        before = library_path.read_bytes()

        with mock.patch(
            "core.io.os.replace",
            side_effect=OSError("synthetic library replace failure"),
        ):
            with self.assertRaisesRegex(OSError, "synthetic library replace"):
                save_global_module_library(
                    {"replacement": {"body": "new"}},
                    self.settings,
                )

        self.assertEqual(before, library_path.read_bytes())
        self.assertEqual([], self._temp_files(library_path))

    def test_cleanup_failure_does_not_mask_original_exception(self):
        library_path = Path(
            save_global_module_library(self._library(), self.settings)
        )
        before = library_path.read_bytes()

        with (
            mock.patch(
                "core.io.json.dump",
                side_effect=ValueError("original library serialization failure"),
            ),
            mock.patch(
                "core.io.os.remove",
                side_effect=OSError("synthetic library cleanup failure"),
            ),
        ):
            with self.assertLogs("core.io", level="WARNING"):
                with self.assertRaisesRegex(
                    ValueError,
                    "original library serialization failure",
                ):
                    save_global_module_library(self._library(), self.settings)

        self.assertEqual(before, library_path.read_bytes())
        for path in self._temp_files(library_path):
            path.unlink()

    def test_legacy_wrapper_and_stale_temp_remain_ignored(self):
        library_path = self._path()
        library_path.parent.mkdir(parents=True)
        library_path.write_text(
            json.dumps(
                {"module_library": self._library()},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        stale_temp = (
            library_path.parent / f".{library_path.name}.stale.tmp"
        )
        stale_temp.write_text(
            json.dumps({"wrong": {"body": "ignore me"}}),
            encoding="utf-8",
        )

        loaded = load_global_module_library(self.settings)

        self.assertEqual(normalize_module_library(self._library()), loaded)
        self.assertNotIn("wrong", loaded)
        self.assertTrue(stale_temp.is_file())


class GlobalModuleLibraryAtomicUiFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.app_path = cls.repo_root / "app.py"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.previous_cwd = os.getcwd()
        os.chdir(self.root)
        self.settings = {
            "global_module_library_dir": str(self.root / "library"),
            "last_project": "",
            "recent_projects": [],
            "projects_root_directory": "",
        }

    def tearDown(self):
        os.chdir(self.previous_cwd)
        self.temp.cleanup()

    @staticmethod
    def _partial_dump(_data, handle, **_kwargs):
        handle.write('{"partial":')
        handle.flush()
        raise OSError("synthetic UI library save failure")

    @staticmethod
    def _element_by_key(elements, key):
        return next(element for element in elements if element.key == key)

    def _start_app(self):
        old_library = {
            "existing": {
                "body": "keep body",
                "description": "keep description",
                "extension_metadata": {"future_key": "keep"},
            },
            "unrelated": {"body": "must remain"},
        }
        library_path = Path(
            save_global_module_library(old_library, self.settings)
        )
        project = Project(source_directory=str(self.root))
        project.module_library = {
            "project_module": {
                "body": "alpha, beta",
                "description": "Project-owned fixture",
            }
        }
        at = AppTest.from_file(
            str(self.app_path),
            default_timeout=30,
        ).run(timeout=30)
        cached_library = load_global_module_library(self.settings)
        at.session_state["settings"] = self.settings
        at.session_state["project"] = project
        at.session_state["history"] = ["keep-history"]
        at.session_state["startup_project_open_attempted"] = True
        at.session_state["active_management_workspace"] = (
            "module_attribute_authoring"
        )
        at.session_state["global_module_library_session_cache"] = {
            "path": str(library_path),
            "library": cached_library,
        }
        at.run(timeout=30)
        return at, library_path, project

    def _capture_state(self, at, library_path):
        return {
            "bytes": library_path.read_bytes(),
            "cache": copy.deepcopy(
                dict(
                    at.session_state[
                        "global_module_library_session_cache"
                    ]
                )
            ),
            "history": copy.deepcopy(at.session_state["history"]),
            "project_library": copy.deepcopy(
                at.session_state["project"].module_library
            ),
        }

    def _assert_failed_write_state(
        self,
        at,
        library_path,
        project,
        before,
    ):
        self.assertEqual([], list(at.exception))
        self.assertEqual(before["bytes"], library_path.read_bytes())
        json.loads(library_path.read_text(encoding="utf-8"))
        self.assertEqual(
            before["cache"],
            dict(
                at.session_state[
                    "global_module_library_session_cache"
                ]
            ),
        )
        self.assertIs(project, at.session_state["project"])
        self.assertEqual(before["history"], at.session_state["history"])
        self.assertEqual(
            before["project_library"],
            at.session_state["project"].module_library,
        )
        self.assertNotIn("global_module_library_notice", at.session_state)
        self.assertTrue(
            any(
                "Global Module Libraryを保存できませんでした"
                in str(item.value)
                for item in at.error
            )
        )
        self.assertFalse(
            any(
                "Saved global module" in str(item.value)
                or "Deleted global module" in str(item.value)
                for item in at.success
            )
        )
        self.assertEqual(
            [],
            list(library_path.parent.glob(
                f".{library_path.name}.*.tmp"
            )),
        )

    def test_project_to_global_failure_has_error_without_false_success(self):
        at, library_path, project = self._start_app()
        before = self._capture_state(at, library_path)

        with mock.patch(
            "core.io.json.dump",
            side_effect=self._partial_dump,
        ):
            self._element_by_key(
                at.button,
                "global_module_save_btn",
            ).click().run(timeout=30)

        self._assert_failed_write_state(
            at,
            library_path,
            project,
            before,
        )
        self.assertNotIn(
            "project_module",
            load_global_module_library(self.settings),
        )

    def test_global_module_edit_failure_keeps_old_record_and_cache(self):
        at, library_path, project = self._start_app()
        before = self._capture_state(at, library_path)
        self._element_by_key(
            at.text_input,
            "global_module_manager_name_existing",
        ).set_value("renamed").run(timeout=30)

        with mock.patch(
            "core.io.json.dump",
            side_effect=self._partial_dump,
        ):
            self._element_by_key(
                at.button,
                "global_module_manager_save_existing",
            ).click().run(timeout=30)

        self._assert_failed_write_state(
            at,
            library_path,
            project,
            before,
        )
        persisted = load_global_module_library(self.settings)
        self.assertIn("existing", persisted)
        self.assertNotIn("renamed", persisted)

    def test_global_module_delete_failure_keeps_module_and_cache(self):
        at, library_path, project = self._start_app()
        before = self._capture_state(at, library_path)
        self._element_by_key(
            at.text_input,
            "global_module_manager_delete_confirm_existing",
        ).set_value("existing").run(timeout=30)

        with mock.patch(
            "core.io.json.dump",
            side_effect=self._partial_dump,
        ):
            self._element_by_key(
                at.button,
                "global_module_manager_delete_existing",
            ).click().run(timeout=30)

        self._assert_failed_write_state(
            at,
            library_path,
            project,
            before,
        )
        self.assertIn(
            "existing",
            load_global_module_library(self.settings),
        )


if __name__ == "__main__":
    unittest.main()
