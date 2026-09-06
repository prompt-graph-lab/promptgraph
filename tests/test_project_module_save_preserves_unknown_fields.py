import json
import tempfile
import unittest
from pathlib import Path

from core.io import load_project_from_json, save_project_to_json
from core.operations import create_library_module, set_module_entry
from core.project import Project


class ProjectModuleSavePreservesUnknownFieldsTests(unittest.TestCase):
    def test_existing_module_update_preserves_unknown_fields_through_save_reload(self):
        project = Project()
        project.module_library = {
            "pose": {
                "body": "old pose",
                "type": "generic",
                "category": "Other",
                "extension": {
                    "owner": "plugin",
                    "nested": {"preserve": ["metadata"]},
                },
            }
        }

        set_module_entry(
            project,
            "pose",
            "new pose, smile",
            "scene",
            ["smile"],
            1,
            "Pose / Action",
        )

        updated_entry = project.module_library["pose"]
        self.assertEqual(updated_entry["body"], "new pose, smile")
        self.assertEqual(updated_entry["type"], "scene")
        self.assertEqual(updated_entry["category"], "Pose / Action")
        self.assertEqual(updated_entry["core_tokens"], ["smile"])
        self.assertEqual(updated_entry["min_match_tokens"], 1)
        self.assertEqual(
            updated_entry["extension"],
            {
                "owner": "plugin",
                "nested": {"preserve": ["metadata"]},
            },
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "project.json"
            save_project_to_json(project, destination)
            serialized = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(
                serialized["module_library"]["pose"]["extension"],
                updated_entry["extension"],
            )

            reopened = load_project_from_json(destination)
            self.assertEqual(
                reopened.module_library["pose"]["extension"],
                updated_entry["extension"],
            )
            self.assertEqual(
                reopened.module_library["pose"]["body"],
                "new pose, smile",
            )
            self.assertEqual(reopened.module_library["pose"]["type"], "scene")

    def test_new_module_still_uses_canonical_known_fields(self):
        project = Project()

        self.assertTrue(create_library_module(project, "new pose", "smile, sky"))

        self.assertEqual(
            set(project.module_library["new pose"]),
            {
                "body",
                "type",
                "category",
                "graph",
                "core_tokens",
                "min_match_tokens",
            },
        )

    def test_omitted_category_keeps_main_default_and_unknown_fields(self):
        project = Project()
        project.module_library = {
            "pose": {
                "body": "old pose",
                "type": "generic",
                "category": "Style",
                "extension": {"nested": {"preserve": True}},
            }
        }

        set_module_entry(project, "pose", "new pose")

        updated_entry = project.module_library["pose"]
        self.assertEqual(updated_entry["category"], "Character")
        self.assertEqual(
            updated_entry["extension"],
            {"nested": {"preserve": True}},
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "project.json"
            save_project_to_json(project, destination)
            reopened = load_project_from_json(destination)
            self.assertEqual(
                reopened.module_library["pose"]["category"],
                "Character",
            )
            self.assertEqual(
                reopened.module_library["pose"]["extension"],
                {"nested": {"preserve": True}},
            )


if __name__ == "__main__":
    unittest.main()
