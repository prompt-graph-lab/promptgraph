import ast
import copy
import unittest
from pathlib import Path

from core import operations
from core.project import Project


def load_app_function(name, namespace):
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    node = next(node for node in ast.parse(source).body
                if isinstance(node, ast.FunctionDef) and node.name == name)
    node.decorator_list = []
    exec(compile(ast.Module(body=[node], type_ignores=[]), "app.py", "exec"), namespace)
    return namespace[name]


class AttributeGroupTextCreationTests(unittest.TestCase):
    def setUp(self):
        self.create = operations.create_attribute_group_from_tokens

    def test_app_adapter_forwards_objects_and_result(self):
        from unittest.mock import Mock
        sentinel = object()
        operation = Mock(return_value=sentinel)
        adapter = load_app_function("_create_attribute_group_from_tokens", {
            "create_attribute_group_from_tokens": operation,
        })
        project, tokens = Project(), ["Smile"]
        self.assertIs(adapter(project, "Name", "Slot", tokens), sentinel)
        operation.assert_called_once_with(project, "Name", "Slot", tokens)
        self.assertIs(operation.call_args.args[0], project)
        self.assertIs(operation.call_args.args[3], tokens)

    def test_creation_preserves_literal_spelling_order_and_negative_defaults(self):
        project = Project()
        tokens = [" Smile, BLUE eyes ", "SMILE\n(smile:1.2)"]
        original = list(tokens)
        self.assertEqual(self.create(project, " My Outfit ", " Hair Style ", tokens), "my_outfit")
        self.assertEqual(project.attribute_groups["my_outfit"], {
            "name": "My Outfit", "slot": "hair_style",
            "tokens": ["Smile", "BLUE eyes", "(smile:1.2)"],
            "created_from": "sidebar_manager", "negative_tags": [],
            "negative_when_disabled": [], "negative_notes": "",
        })
        self.assertEqual(tokens, original)
        # The existing getter deliberately canonicalizes only on a later read.
        self.assertEqual(operations.get_project_attribute_groups(project)["my_outfit"]["tokens"],
                         ["smile", "blue eyes"])

    def test_invalid_fields_leave_existing_mapping_untouched(self):
        for name, slot, tokens in [("!!!", "outfit", ["x"]), ("A", "!!!", ["x"]),
                                   ("A", "outfit", []), ("A", "outfit", None)]:
            with self.subTest(name=name, slot=slot, tokens=tokens):
                project = Project(attribute_groups={"Legacy Key": {"name": "Legacy", "slot": "Outfit"}})
                before = project.attribute_groups
                snapshot = copy.deepcopy(before)
                self.assertIsNone(self.create(project, name, slot, tokens))
                self.assertIs(project.attribute_groups, before)
                self.assertEqual(before, snapshot)

    def test_duplicate_still_normalizes_existing_groups_and_preserves_extensions(self):
        extension = {"nested": [1, {"unknown": True}]}
        project = Project(attribute_groups={"RAW": {
            "name": "My Outfit", "slot": "Outfit", "tokens": ["Smile", "SMILE"],
            "extension": extension, "negative_tags": ["bad", "bad"],
        }})
        before = project.attribute_groups
        self.assertIsNone(self.create(project, "my outfit", "outfit", ["new"]))
        self.assertIsNot(project.attribute_groups, before)
        group = project.attribute_groups["my_outfit"]
        self.assertEqual(group["tokens"], ["smile"])
        self.assertEqual(group["negative_tags"], ["bad"])
        self.assertEqual(group["extension"], extension)
        self.assertIsNot(group["extension"], extension)
        self.assertEqual(before["RAW"]["tokens"], ["Smile", "SMILE"])

    def test_success_normalizes_existing_groups_before_insertion(self):
        project = Project(attribute_groups={"OLD": {"name": "Old", "slot": "Outfit", "tokens": ["A"]}})
        before = project.attribute_groups
        self.assertEqual(self.create(project, "New", "outfit", ["B"]), "new")
        self.assertEqual(list(project.attribute_groups), ["old", "new"])
        self.assertEqual(project.attribute_groups["old"]["tokens"], ["a"])
        self.assertIsNot(project.attribute_groups, before)

    def test_getter_failure_propagates_without_inserting(self):
        from unittest.mock import patch
        project = Project()
        with patch.dict(self.create.__globals__, get_project_attribute_groups=lambda project: (_ for _ in ()).throw(RuntimeError("read failed"))):
            with self.assertRaisesRegex(RuntimeError, "read failed"):
                self.create(project, "New", "outfit", ["B"])
        self.assertEqual(project.attribute_groups, {})


if __name__ == "__main__":
    unittest.main()
