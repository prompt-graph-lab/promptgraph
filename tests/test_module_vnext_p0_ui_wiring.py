"""Module vNext P0: Streamlit Global <-> Project wiring for `reference_assets`.

Synthetic Project / Global fixtures only, in a temporary directory.
"""

import ast
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from core.io import load_global_module_library, save_global_module_library
from core.module_container_policy import REFERENCE_ASSETS_FIELD
from core.operations import normalize_module_library
from core.project import Project

ASSET_PATH = "refs/modules/" + "c" * 64 + ".png"


def _reference_assets():
    return {
        "format": 1,
        "assets": [{
            "id": "front",
            "role": "character_reference",
            "media_type": "image/png",
            "path": ASSET_PATH,
            "sha256": "c" * 64,
        }],
    }


class ModuleVNextP0UiWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_path = Path(__file__).resolve().parents[1] / "app.py"
        cls.app_source = cls.app_path.read_text(encoding="utf-8")

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
    def _element_by_key(elements, key):
        return next(element for element in elements if element.key == key)

    @staticmethod
    def _keys(elements):
        return {element.key for element in elements}

    def _start_app(self):
        library_path = Path(save_global_module_library({
            "with_refs": {"body": "global body", "notes": "global notes"},
            "plain": {"body": "global plain", "notes": "global plain notes"},
        }, self.settings))
        project = Project(source_directory=str(self.root))
        project.module_library = {
            "with_refs": {
                "body": "project body",
                "description": "Project-owned fixture",
                "extension": {"keep": True},
                REFERENCE_ASSETS_FIELD: _reference_assets(),
            },
            "plain": {"body": "project plain"},
        }
        at = AppTest.from_file(str(self.app_path), default_timeout=30).run(timeout=30)
        at.session_state["settings"] = self.settings
        at.session_state["project"] = project
        at.session_state["history"] = []
        at.session_state["startup_project_open_attempted"] = True
        at.session_state["active_management_workspace"] = "module_attribute_authoring"
        at.session_state["global_module_library_session_cache"] = {
            "path": str(library_path),
            "library": load_global_module_library(self.settings),
        }
        at.run(timeout=30)
        self.assertEqual([], list(at.exception))
        return at, library_path

    def _visible_text(self, at):
        parts = []
        for collection in (at.markdown, at.caption, at.success, at.info, at.warning, at.error):
            parts.extend(str(item.value) for item in collection)
        return "\n".join(parts)

    def test_global_to_project_overwrite_of_asset_bearing_module_is_not_offered(self):
        at, _library_path = self._start_app()
        project_before = copy.deepcopy(
            normalize_module_library(at.session_state["project"])
        )

        self._element_by_key(at.selectbox, "global_module_load_name").set_value("with_refs").run(timeout=30)

        self.assertEqual([], list(at.exception))
        self.assertNotIn("global_module_load_overwrite", self._keys(at.checkbox))
        load_button = self._element_by_key(at.button, "global_module_load_btn")
        self.assertTrue(load_button.disabled)
        text = self._visible_text(at)
        self.assertIn("cannot be overwritten from the Global Module Library", text)
        self.assertNotIn(ASSET_PATH, text)

        load_button.click().run(timeout=30)
        self.assertEqual(project_before, at.session_state["project"].module_library)
        self.assertEqual([], at.session_state["history"])

    def test_global_to_project_overwrite_without_assets_still_works(self):
        at, _library_path = self._start_app()
        self._element_by_key(at.selectbox, "global_module_load_name").set_value("plain").run(timeout=30)
        self._element_by_key(at.checkbox, "global_module_load_overwrite").check().run(timeout=30)

        self._element_by_key(at.button, "global_module_load_btn").click().run(timeout=30)

        self.assertEqual([], list(at.exception))
        library = at.session_state["project"].module_library
        self.assertEqual("global plain", library["plain"]["body"])
        self.assertEqual("global plain notes", library["plain"]["notes"])
        self.assertEqual(_reference_assets(), library["with_refs"][REFERENCE_ASSETS_FIELD])

    def test_project_to_global_strips_reference_assets_and_notifies(self):
        at, library_path = self._start_app()
        self._element_by_key(at.selectbox, "global_module_save_name").set_value("with_refs").run(timeout=30)
        self._element_by_key(at.checkbox, "global_module_save_overwrite").check().run(timeout=30)

        self._element_by_key(at.button, "global_module_save_btn").click().run(timeout=30)

        self.assertEqual([], list(at.exception))
        raw = json.loads(library_path.read_text(encoding="utf-8"))
        self.assertNotIn(REFERENCE_ASSETS_FIELD, raw["with_refs"])
        self.assertNotIn(ASSET_PATH, library_path.read_text(encoding="utf-8"))
        self.assertEqual("project body", raw["with_refs"]["body"])
        self.assertEqual("Project-owned fixture", raw["with_refs"]["description"])
        self.assertEqual({"keep": True}, raw["with_refs"]["extension"])
        cache = at.session_state["global_module_library_session_cache"]["library"]
        self.assertNotIn(REFERENCE_ASSETS_FIELD, cache["with_refs"])
        self.assertEqual(
            _reference_assets(),
            at.session_state["project"].module_library["with_refs"][REFERENCE_ASSETS_FIELD],
        )
        text = self._visible_text(at)
        self.assertIn("Visual references remain Project-local", text)
        self.assertNotIn(ASSET_PATH, text)

    def test_global_to_project_ui_goes_through_the_core_import_contract(self):
        tree = ast.parse(self.app_source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "project_library"
                ):
                    self.fail(
                        "direct Project Module assignment in app.py at line "
                        f"{node.lineno}; use import_global_modules_to_project"
                    )
        self.assertIn("load_result = import_global_modules_to_project(", self.app_source)
        self.assertIn(
            "project_module_entry = module_entry_for_prompt_only_container(",
            self.app_source,
        )


if __name__ == "__main__":
    unittest.main()
