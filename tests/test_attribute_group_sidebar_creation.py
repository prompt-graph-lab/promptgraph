"""Characterize the Project mutation used by sidebar Attribute Group creation."""

import copy
import unittest

from core.operations import create_attribute_group_from_tokens
from core.project import Project


class AttributeGroupSidebarCreationTests(unittest.TestCase):
    def test_creation_keeps_sidebar_metadata_and_rule_token_spelling(self):
        project = Project(attribute_groups={})
        groups = project.attribute_groups

        key = create_attribute_group_from_tokens(
            project, "  Milk Swimsuit  ", "  Hair Style  ",
            ["Smile", "SMILE, (smile:1.2)", "blue hair"],
        )

        self.assertEqual(key, "milk_swimsuit")
        self.assertIsNot(project.attribute_groups, groups)
        self.assertEqual(groups, {})
        self.assertEqual(project.attribute_groups[key], {
            "name": "Milk Swimsuit",
            "slot": "hair_style",
            "tokens": ["Smile", "(smile:1.2)", "blue hair"],
            "created_from": "sidebar_manager",
            "negative_tags": [],
            "negative_when_disabled": [],
            "negative_notes": "",
        })

    def test_duplicate_does_not_replace_group_or_unknown_fields(self):
        existing = {
            "name": "Milk Swimsuit", "slot": "outfit", "tokens": ["dress"],
            "extension": {"owner": "plugin"},
        }
        project = Project(attribute_groups={"milk_swimsuit": existing})

        self.assertIsNone(create_attribute_group_from_tokens(
            project, "milk swimsuit", "hair_style", ["smile"],
        ))
        self.assertEqual(project.attribute_groups["milk_swimsuit"]["extension"],
                         {"owner": "plugin"})
        self.assertEqual(project.attribute_groups["milk_swimsuit"]["tokens"], ["dress"])

    def test_invalid_input_does_not_touch_project(self):
        for name, slot, tokens in (
            ("!!!", "outfit", ["smile"]),
            ("Good", "!!!", ["smile"]),
            ("Good", "outfit", []),
        ):
            with self.subTest(name=name, slot=slot, tokens=tokens):
                project = Project(attribute_groups={"keep": {"extension": [1]}})
                before = copy.deepcopy(project)
                self.assertIsNone(create_attribute_group_from_tokens(
                    project, name, slot, tokens,
                ))
                self.assertEqual(project, before)


if __name__ == "__main__":
    unittest.main()
