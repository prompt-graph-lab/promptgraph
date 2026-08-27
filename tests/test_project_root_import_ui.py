import ast
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
CORE_PATH = Path(__file__).resolve().parents[1] / "core" / "project_root_import.py"


class AttrDict(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class ProjectRootImportUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_PATH.read_text(encoding="utf-8")
        cls.core_source = CORE_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    @classmethod
    def _function_source(cls, name):
        node = next(
            item
            for item in cls.tree.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == name
        )
        return ast.get_source_segment(cls.source, node)

    def test_section_has_one_project_management_owner(self):
        workspace = self._function_source("render_project_management_workspace")
        self.assertEqual(
            1,
            workspace.count("render_existing_project_import_section()"),
        )
        self.assertEqual(
            2,
            self.source.count("render_existing_project_import_section()"),
        )
        section = self._function_source("render_existing_project_import_section")
        self.assertIn("既存ProjectをProject rootへ取り込む", section)
        self.assertIn("Import Existing Project into Project Root", section)
        self.assertIn("元のProject directoryは削除されません", section)

    def test_widget_owners_and_confirmation_are_unique(self):
        section = self._function_source("render_existing_project_import_section")
        for key in (
            "project_root_import_preview_button",
            "project_root_import_apply_button",
            "project_root_import_open_result",
        ):
            self.assertEqual(1, self.source.count(f'key="{key}"'))
            self.assertIn(key, section)
        self.assertEqual(
            1,
            self.core_source.count(
                'PROJECT_ROOT_IMPORT_CONFIRM_PHRASE = "COPY PROJECT"'
            ),
        )
        self.assertIn("phrase == PROJECT_ROOT_IMPORT_CONFIRM_PHRASE", section)
        self.assertIn("and confirmed", section)

    def test_recursive_preview_and_apply_have_no_passive_owner(self):
        section = self._function_source("render_existing_project_import_section")
        self.assertEqual(1, section.count("build_project_root_import_preview("))
        self.assertEqual(1, section.count("apply_project_root_import("))
        preview_button = section.index('key="project_root_import_preview_button"')
        preview_call = section.index("build_project_root_import_preview(")
        apply_button = section.index('key="project_root_import_apply_button"')
        apply_call = section.index("apply_project_root_import(")
        self.assertLess(preview_button, preview_call)
        self.assertLess(apply_button, apply_call)

    def test_success_updates_recent_without_last_project_or_auto_open(self):
        section = self._function_source("render_existing_project_import_section")
        finalize = self._function_source("_finalize_project_root_import_success")
        self.assertIn("update_last_project=False", finalize)
        self.assertIn("request_project_directory_discovery_refresh()", finalize)
        self.assertNotIn("current_project_path = destination_project_path", section)
        self.assertLess(
            section.index('key="project_root_import_open_result"'),
            section.index("load_project_json_into_session("),
        )

    def test_success_finalizer_preserves_last_project_and_requests_refresh(self):
        finalize = self._function_source("_finalize_project_root_import_success")
        calls = []
        settings = {"last_project": "source.json", "recent_projects": []}
        namespace = {
            "st": SimpleNamespace(session_state=AttrDict(settings=settings)),
            "remember_project": lambda current, path, update_last_project: (
                calls.append((path, update_last_project))
                or {
                    **current,
                    "recent_projects": [{"path": path}],
                }
            ),
            "save_settings": lambda current: calls.append(("save", current)) or True,
            "request_project_directory_discovery_refresh": lambda: calls.append(
                ("refresh",)
            ),
        }
        exec(finalize, namespace)
        result = namespace["_finalize_project_root_import_success"](
            {"success": True, "destination_project_path": "imported.json"}
        )
        self.assertTrue(result["success"])
        self.assertEqual("source.json", namespace["st"].session_state["settings"]["last_project"])
        self.assertIn(("imported.json", False), calls)
        self.assertIn(("refresh",), calls)

    def test_workspace_reset_preserves_preview_but_clears_confirmation(self):
        reset = self._function_source("reset_management_workspace_session_state")
        operation_reset = self._function_source(
            "reset_project_root_import_operation_state"
        )
        self.assertNotIn("project_root_import_preview", reset)
        self.assertIn('pop("project_root_import_confirm"', reset)
        self.assertIn('pop("project_root_import_phrase"', reset)
        self.assertIn("PROJECT_ROOT_IMPORT_PREVIEW_KEY", operation_reset)
        self.assertIn("PROJECT_ROOT_IMPORT_CONFIRM_RESET_PENDING_KEY", operation_reset)

    def test_current_and_recent_shortcuts_only_accept_external_files(self):
        external_source = self._function_source(
            "_project_root_import_external_source"
        )
        recent_source = self._function_source("_project_root_import_recent_sources")
        namespace = {
            "os": os,
            "normalize_project_import_path": lambda value: os.path.realpath(
                os.path.abspath(str(value or ""))
            )
            if value
            else "",
        }
        exec(external_source, namespace)
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "projects"
            inside = root / "Inside" / "project.json"
            outside = base / "old" / "project.json"
            inside.parent.mkdir(parents=True)
            outside.parent.mkdir(parents=True)
            inside.write_text("{}", encoding="utf-8")
            outside.write_text("{}", encoding="utf-8")
            self.assertEqual(
                "", namespace["_project_root_import_external_source"](inside, root)
            )
            self.assertEqual(
                str(outside),
                namespace["_project_root_import_external_source"](outside, root),
            )

            namespace.update(
                {
                    "st": SimpleNamespace(
                        session_state={
                            "settings": {
                                "recent_projects": [
                                    {"name": "Outside", "path": str(outside)},
                                    {"name": "Inside", "path": str(inside)},
                                ]
                            }
                        }
                    ),
                    "get_recent_projects": lambda settings: settings[
                        "recent_projects"
                    ],
                }
            )
            exec(recent_source, namespace)
            self.assertEqual(
                [{"name": "Outside", "path": str(outside)}],
                namespace["_project_root_import_recent_sources"](str(root)),
            )


if __name__ == "__main__":
    unittest.main()
