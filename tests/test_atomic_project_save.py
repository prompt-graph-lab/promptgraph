import ast
import copy
import hashlib
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

from core.io import (
    SetEncoder,
    _project_to_serializable_data,
    load_project_from_json,
    save_project_to_json,
    save_project_to_json_atomically,
)
from core.new_project_workspace import create_new_workspace_files
from core.project import Project, PromptLine


def _line(line_id="line-1", **overrides):
    values = {
        "id": line_id,
        "original_file_name": "001.png",
        "original_index": 0,
        "current_index": 0,
        "original_text": "original prompt",
        "current_text": "current prompt",
        "tokens": ["current", "prompt"],
        "negative_prompt": "synthetic negative",
    }
    values.update(overrides)
    return PromptLine(**values)


class AtomicProjectSaveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.previous_cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.previous_cwd)
        self.temp.cleanup()

    def _project(self, text="current prompt"):
        project = Project(source_directory=str(self.root))
        project.prompt_lines = [_line(current_text=text)]
        project.line_map = {line.id: line for line in project.prompt_lines}
        return project

    @staticmethod
    def _temp_files(destination):
        destination = Path(destination)
        return list(destination.parent.glob(f".{destination.name}.*.tmp"))

    @staticmethod
    def _partial_dump(_data, handle, **_kwargs):
        handle.write('{\n  "prompt_lines": [')
        handle.flush()
        raise OSError("synthetic disk full after temporary write")

    def test_existing_destination_survives_partial_json_dump_failure(self):
        destination = self.root / "project.json"
        save_project_to_json(self._project("before"), destination)
        before = destination.read_bytes()
        before_digest = hashlib.sha256(before).hexdigest()

        with mock.patch("core.io.json.dump", side_effect=self._partial_dump):
            with self.assertRaisesRegex(OSError, "synthetic disk full"):
                save_project_to_json(self._project("after"), destination)

        self.assertEqual(before, destination.read_bytes())
        self.assertEqual(before_digest, hashlib.sha256(destination.read_bytes()).hexdigest())
        json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual([], self._temp_files(destination))

    def test_new_destination_failure_leaves_no_final_or_temporary_file(self):
        destination = self.root / "new-project.json"

        with mock.patch("core.io.json.dump", side_effect=self._partial_dump):
            with self.assertRaisesRegex(OSError, "synthetic disk full"):
                save_project_to_json(self._project(), destination)

        self.assertFalse(destination.exists())
        self.assertEqual([], self._temp_files(destination))

    def test_success_replaces_existing_destination_and_reopens(self):
        destination = self.root / "project.json"
        save_project_to_json(self._project("before"), destination)

        updated = self._project("after")
        expected_text = json.dumps(
            _project_to_serializable_data(updated.clone(), str(destination)),
            cls=SetEncoder,
            indent=2,
            ensure_ascii=False,
        )
        expected_bytes = expected_text.replace("\n", os.linesep).encode("utf-8")
        save_project_to_json(updated, destination)
        reopened = load_project_from_json(destination)

        self.assertEqual("after", reopened.prompt_lines[0].current_text)
        self.assertEqual(expected_bytes, destination.read_bytes())
        self.assertEqual([], self._temp_files(destination))
        self.assertEqual(
            _project_to_serializable_data(updated.clone(), str(destination)),
            json.loads(destination.read_text(encoding="utf-8")),
        )

    def test_relative_paths_use_final_destination_not_temporary_name(self):
        project_dir = self.root / "作品"
        destination = project_dir / "custom-book.json"
        assets = {
            "main": project_dir / "refs" / "main.png",
            "generated": project_dir / "generated" / "generated.png",
            "candidate": project_dir / "candidates" / "candidate.png",
            "variant": project_dir / "candidates" / "variant.png",
        }
        for path in assets.values():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(path.name.encode("utf-8"))

        project = Project(source_directory=str(project_dir))
        project.module_library = {
            "synthetic": {
                "body": "one, two",
                "extension_metadata": {"future_key": "keep"},
            }
        }
        project.prompt_lines = [
            _line(
                current_text="非ASCII prompt",
                image_path=str(assets["main"]),
                generated_image_path=str(assets["generated"]),
                selected_candidate_path=str(assets["candidate"]),
                generated_candidates=[
                    {
                        "path": str(assets["candidate"]),
                        "future_candidate_key": {"keep": True},
                    }
                ],
                gallery_variants=[
                    {
                        "path": str(assets["variant"]),
                        "future_variant_key": "keep",
                        "source_generation_info": {
                            "source_image_path": str(assets["candidate"]),
                        },
                        "lineage_info": {
                            "candidate_image_path": str(assets["variant"]),
                            "parent_image_path": str(assets["main"]),
                        },
                    }
                ],
                lineage_info={
                    "candidate_image_path": str(assets["candidate"]),
                    "parent_image_path": str(assets["main"]),
                },
            )
        ]
        project.line_map = {line.id: line for line in project.prompt_lines}

        save_project_to_json(project, destination)
        serialized_text = destination.read_text(encoding="utf-8")
        serialized = json.loads(serialized_text)
        line = serialized["prompt_lines"][0]

        self.assertNotIn(f".{destination.name}.", serialized_text)
        self.assertEqual("generated/generated.png", line["generated_image_path"])
        self.assertEqual("candidates/candidate.png", line["selected_candidate_path"])
        self.assertEqual("candidates/candidate.png", line["generated_candidates"][0]["path"])
        self.assertEqual("candidates/variant.png", line["gallery_variants"][0]["path"])
        self.assertEqual(
            "candidates/candidate.png",
            line["gallery_variants"][0]["source_generation_info"]["source_image_path"],
        )
        self.assertEqual(
            "candidates/variant.png",
            line["gallery_variants"][0]["lineage_info"]["candidate_image_path"],
        )
        self.assertEqual(
            "candidates/candidate.png",
            line["lineage_info"]["candidate_image_path"],
        )
        self.assertTrue(line["generated_candidates"][0]["future_candidate_key"]["keep"])
        self.assertEqual("keep", line["gallery_variants"][0]["future_variant_key"])
        self.assertEqual(
            "keep",
            serialized["module_library"]["synthetic"]["extension_metadata"]["future_key"],
        )
        reopened = load_project_from_json(destination)
        self.assertEqual("非ASCII prompt", reopened.prompt_lines[0].current_text)
        self.assertEqual("candidates/candidate.png", reopened.prompt_lines[0].selected_candidate_path)
        self.assertEqual([], self._temp_files(destination))

    def test_fsync_failure_preserves_existing_destination_and_cleans_temp(self):
        destination = self.root / "project.json"
        save_project_to_json(self._project("before"), destination)
        before = destination.read_bytes()

        with mock.patch("core.io.os.fsync", side_effect=OSError("synthetic fsync failure")):
            with self.assertRaisesRegex(OSError, "synthetic fsync failure"):
                save_project_to_json(self._project("after"), destination)

        self.assertEqual(before, destination.read_bytes())
        self.assertEqual([], self._temp_files(destination))

    def test_replace_failure_preserves_existing_destination_and_cleans_temp(self):
        destination = self.root / "project.json"
        save_project_to_json(self._project("before"), destination)
        before = destination.read_bytes()

        with mock.patch("core.io.os.replace", side_effect=OSError("synthetic replace failure")):
            with self.assertRaisesRegex(OSError, "synthetic replace failure"):
                save_project_to_json(self._project("after"), destination)

        self.assertEqual(before, destination.read_bytes())
        self.assertEqual([], self._temp_files(destination))

    def test_cleanup_failure_does_not_mask_original_save_exception(self):
        destination = self.root / "project.json"
        save_project_to_json(self._project("before"), destination)
        before = destination.read_bytes()

        with (
            mock.patch("core.io.json.dump", side_effect=ValueError("original serialization failure")),
            mock.patch("core.io.os.remove", side_effect=OSError("cleanup failure")),
        ):
            with self.assertLogs("core.io", level="WARNING"):
                with self.assertRaisesRegex(ValueError, "original serialization failure"):
                    save_project_to_json(self._project("after"), destination)

        self.assertEqual(before, destination.read_bytes())
        for path in self._temp_files(destination):
            path.unlink()

    def test_compatibility_atomic_alias_does_not_recurse(self):
        destination = self.root / "project.json"

        save_project_to_json_atomically(self._project(), destination)

        self.assertTrue(destination.is_file())
        self.assertEqual([], self._temp_files(destination))

    def test_new_workspace_uses_atomic_writer_on_first_save_failure(self):
        project_dir = self.root / "NewProject"

        with mock.patch("core.io.json.dump", side_effect=self._partial_dump):
            with self.assertRaisesRegex(OSError, "synthetic disk full"):
                create_new_workspace_files(project_dir, "custom.json")

        self.assertFalse((project_dir / "custom.json").exists())
        self.assertEqual([], self._temp_files(project_dir / "custom.json"))


class _SessionState(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __setattr__(self, key, value):
        self[key] = value


class AtomicProjectSaveCallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.app_path = cls.repo_root / "app.py"
        cls.app_source = cls.app_path.read_text(encoding="utf-8")
        cls.app_tree = ast.parse(cls.app_source)
        cls.app_functions = {
            node.name: node
            for node in cls.app_tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.previous_cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.previous_cwd)
        self.temp.cleanup()

    def _project(self):
        project = Project(source_directory=str(self.root))
        project.prompt_lines = [_line()]
        project.line_map = {line.id: line for line in project.prompt_lines}
        return project

    def _start_app(self, name="CurrentProject"):
        project_dir = self.root / name
        project_dir.mkdir()
        project_path = project_dir / "project.json"
        project = self._project()
        save_project_to_json(project, project_path)

        at = AppTest.from_file(str(self.app_path), default_timeout=30).run(timeout=30)
        at.session_state["project"] = project
        at.session_state["current_project_path"] = str(project_path)
        at.session_state["startup_project_open_attempted"] = True
        at.run(timeout=30)
        return at, project_path

    @staticmethod
    def _partial_dump(_data, handle, **_kwargs):
        handle.write('{"partial":')
        handle.flush()
        raise OSError("synthetic UI save failure")

    @staticmethod
    def _element_by_key(elements, key):
        return next(element for element in elements if element.key == key)

    def test_quick_save_failure_preserves_disk_session_and_history(self):
        at, project_path = self._start_app()
        before = project_path.read_bytes()
        project = at.session_state["project"]
        history_before = copy.deepcopy(at.session_state["history"])
        path_before = at.session_state["current_project_path"]

        with mock.patch("core.io.json.dump", side_effect=self._partial_dump):
            self._element_by_key(at.button, "quick_save_project").click().run(timeout=30)

        self.assertEqual([], list(at.exception))
        self.assertEqual(before, project_path.read_bytes())
        self.assertIs(project, at.session_state["project"])
        self.assertEqual(path_before, at.session_state["current_project_path"])
        self.assertEqual(history_before, at.session_state["history"])
        self.assertTrue(
            any("保存できませんでした" in str(item.value) for item in at.error)
        )
        self.assertFalse(
            any("プロジェクトを保存しました" in str(item.value) for item in at.success)
        )
        self.assertEqual([], list(project_path.parent.glob(f".{project_path.name}.*.tmp")))

    def test_save_as_failures_do_not_commit_existing_or_new_destination(self):
        for destination_exists in (True, False):
            with self.subTest(destination_exists=destination_exists):
                at, project_path = self._start_app(
                    f"CurrentProject-{destination_exists}"
                )
                destination = self.root / f"SaveAs-{destination_exists}" / "custom.json"
                destination.parent.mkdir()
                if destination_exists:
                    destination.write_bytes(b'{"prompt_lines": [], "keep": true}\n')
                    before = destination.read_bytes()
                else:
                    before = None
                settings_before = copy.deepcopy(dict(at.session_state["settings"]))
                history_before = copy.deepcopy(at.session_state["history"])
                path_before = at.session_state["current_project_path"]

                self._element_by_key(
                    at.text_input,
                    "save_project_json_path",
                ).set_value(str(destination)).run(timeout=30)
                if destination_exists:
                    self._element_by_key(
                        at.button,
                        "save_project_as_json_button",
                    ).click().run(timeout=30)
                    self._element_by_key(
                        at.checkbox,
                        "_project_save_as_overwrite_acknowledged_widget",
                    ).check().run(timeout=30)
                    target_button_key = (
                        "project_save_as_confirm_overwrite_button"
                    )
                else:
                    target_button_key = "save_project_as_json_button"
                with mock.patch(
                    "core.io.json.dump",
                    side_effect=self._partial_dump,
                ):
                    self._element_by_key(
                        at.button,
                        target_button_key,
                    ).click().run(timeout=30)

                self.assertEqual([], list(at.exception))
                if destination_exists:
                    self.assertEqual(before, destination.read_bytes())
                else:
                    self.assertFalse(destination.exists())
                self.assertEqual(path_before, at.session_state["current_project_path"])
                self.assertEqual(settings_before, dict(at.session_state["settings"]))
                self.assertEqual(history_before, at.session_state["history"])
                self.assertTrue(
                    any("保存できませんでした" in str(item.value) for item in at.error)
                )
                self.assertFalse(
                    any("プロジェクトを保存しました" in str(item.value) for item in at.success)
                )
                self.assertEqual([], list(destination.parent.glob(f".{destination.name}.*.tmp")))

    def test_duplicate_aborts_before_copy_when_source_save_fails(self):
        at, project_path = self._start_app()
        before = project_path.read_bytes()
        path_before = at.session_state["current_project_path"]
        destination_name = "AtomicFailureCopy"
        destination = project_path.parent.parent / destination_name

        next(button for button in at.button if button.label == "Project Management").click().run(timeout=30)
        self._element_by_key(
            at.text_input,
            "duplicate_project_dir_name",
        ).set_value(destination_name).run(timeout=30)
        self._element_by_key(
            at.checkbox,
            "duplicate_project_confirm",
        ).check().run(timeout=30)
        with mock.patch("core.io.json.dump", side_effect=self._partial_dump):
            self._element_by_key(
                at.button,
                "duplicate_project_as_button",
            ).click().run(timeout=30)

        self.assertEqual([], list(at.exception))
        self.assertEqual(before, project_path.read_bytes())
        self.assertFalse(destination.exists())
        self.assertEqual(path_before, at.session_state["current_project_path"])
        self.assertTrue(
            any("保存に失敗" in str(item.value) for item in at.warning)
        )
        self.assertEqual([], list(project_path.parent.glob(f".{project_path.name}.*.tmp")))

    def test_duplicate_does_not_copy_stale_atomic_temporary_file(self):
        at, project_path = self._start_app()
        stale_temporary = project_path.parent / f".{project_path.name}.stale.tmp"
        stale_temporary.write_text('{"partial":', encoding="utf-8")
        destination_name = "AtomicSuccessCopy"
        destination = project_path.parent.parent / destination_name

        next(button for button in at.button if button.label == "Project Management").click().run(timeout=30)
        self._element_by_key(
            at.text_input,
            "duplicate_project_dir_name",
        ).set_value(destination_name).run(timeout=30)
        self._element_by_key(
            at.checkbox,
            "duplicate_project_confirm",
        ).check().run(timeout=30)
        self._element_by_key(
            at.button,
            "duplicate_project_as_button",
        ).click().run(timeout=30)

        self.assertEqual([], list(at.exception))
        self.assertTrue(destination.is_dir())
        self.assertFalse((destination / stale_temporary.name).exists())
        self.assertTrue(stale_temporary.is_file())
        self.assertEqual(
            os.path.abspath(destination / project_path.name),
            at.session_state["current_project_path"],
        )

    def test_autosave_failure_contract_preserves_session_state(self):
        function = self.app_functions["save_current_project_if_possible"]
        state = _SessionState(
            project=self._project(),
            current_project_path=str(self.root / "project.json"),
            history=["keep-history"],
            autosave_feedback="before",
        )
        ensured = []
        namespace = {
            "st": types.SimpleNamespace(session_state=state),
            "save_project_to_json": mock.Mock(
                side_effect=ValueError("synthetic serialization failure")
            ),
            "ensure_current_project_folder_layout": lambda path: ensured.append(path),
            "datetime": __import__("datetime").datetime,
        }
        module = ast.Module(body=[function], type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, "app.py", "exec"), namespace)

        result = namespace["save_current_project_if_possible"]("autosave-test")

        self.assertFalse(result)
        self.assertEqual([], ensured)
        self.assertEqual(["keep-history"], state.history)
        self.assertEqual(str(self.root / "project.json"), state.current_project_path)
        self.assertIn("synthetic serialization failure", state.autosave_feedback)


if __name__ == "__main__":
    unittest.main()
