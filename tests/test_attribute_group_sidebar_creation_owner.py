import ast
import copy
import unittest
from contextlib import nullcontext
from pathlib import Path

from core.module_token_rules import _parse_module_rule_text
from core.operations import (
    SUGGESTED_ATTRIBUTE_SLOTS,
    create_attribute_group_from_tokens,
    get_project_attribute_groups,
    normalize_attribute_group_name,
    normalize_attribute_slot,
)
from core.project import Project


class AttributeGroupSidebarCreationOwnerTests(unittest.TestCase):
    def test_token_authored_record_keeps_sidebar_metadata_and_existing_fields(self):
        project = Project(attribute_groups={
            "existing": {
                "name": "Existing",
                "slot": "outfit",
                "tokens": ["dress"],
                "created_from": "test",
                "extension": {"keep": [1, 2]},
            },
        })

        created_key = create_attribute_group_from_tokens(
            project,
            "  Milk Swimsuit  ",
            "  Hair Style  ",
            ["Smile", "SMILE, (smile:1.2)", " sky "],
        )

        self.assertEqual(created_key, "milk_swimsuit")
        self.assertEqual(project.attribute_groups[created_key], {
            "name": "Milk Swimsuit",
            "slot": "hair_style",
            "tokens": ["Smile", "(smile:1.2)", "sky"],
            "created_from": "sidebar_manager",
            "negative_tags": [],
            "negative_when_disabled": [],
            "negative_notes": "",
        })
        self.assertEqual(project.attribute_groups["existing"]["extension"], {"keep": [1, 2]})

    def test_invalid_draft_does_not_normalize_or_replace_project_library(self):
        project = Project(attribute_groups={
            "Raw Name": {"name": "Raw Name", "slot": "outfit", "tokens": ["dress"]},
        })
        original_groups = project.attribute_groups
        before = copy.deepcopy(original_groups)

        for name, slot, tokens in (
            ("", "outfit", ["dress"]),
            ("New", "", ["dress"]),
            ("New", "outfit", ["", "  "]),
        ):
            with self.subTest(name=name, slot=slot, tokens=tokens):
                self.assertIsNone(create_attribute_group_from_tokens(project, name, slot, tokens))
                self.assertIs(project.attribute_groups, original_groups)
                self.assertEqual(project.attribute_groups, before)

    def test_duplicate_name_uses_normalized_library_and_preserves_metadata(self):
        project = Project(attribute_groups={
            "legacy": {
                "name": "Milk Swimsuit",
                "slot": "outfit",
                "tokens": ["dress"],
                "extension": {"keep": True},
            },
        })

        self.assertIsNone(create_attribute_group_from_tokens(
            project, "milk swimsuit", "outfit", ["new token"],
        ))
        self.assertEqual(list(project.attribute_groups), ["milk_swimsuit"])
        self.assertEqual(project.attribute_groups["milk_swimsuit"]["tokens"], ["dress"])
        self.assertEqual(project.attribute_groups["milk_swimsuit"]["extension"], {"keep": True})

    def test_sidebar_keeps_history_and_save_around_core_creation(self):
        source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {
            node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
        }
        renderer = copy.deepcopy(functions["render_attribute_group_sidebar_manager"])
        renderer.decorator_list = []
        module = ast.Module(
            body=[
                functions["_attribute_group_tokens_from_text"],
                functions["_attribute_group_slot_options"],
                renderer,
            ],
            type_ignores=[],
        )
        ast.fix_missing_locations(module)

        class Rerun(Exception):
            pass

        class SessionState(dict):
            def __getattr__(self, key):
                return self[key]

            def __setattr__(self, key, value):
                self[key] = value

        class StreamlitStub:
            def __init__(self, state, events):
                self.session_state = state
                self.events = events

            def expander(self, *args, **kwargs):
                return nullcontext()

            def caption(self, *args):
                pass

            def markdown(self, *args):
                pass

            def text_input(self, label, *, key, **kwargs):
                return " Milk Swimsuit " if key == "attribute_group_sidebar_create_name" else ""

            def selectbox(self, label, *, options, **kwargs):
                return "outfit"

            def text_area(self, label, *, key, **kwargs):
                return "dress, hat"

            def button(self, label, *, disabled, **kwargs):
                self.events.append(("button", label, disabled))
                return label == "Create Attribute Group" and not disabled

            def rerun(self):
                self.events.append(("rerun",))
                raise Rerun

        project = Project()
        state = SessionState(project=project, selected_node_ids=[])
        events = []
        st = StreamlitStub(state, events)

        def create(*args):
            events.append(("create", args[0] is project))
            return create_attribute_group_from_tokens(*args)

        namespace = {
            "st": st,
            "is_free": lambda: False,
            "get_project_attribute_groups": get_project_attribute_groups,
            "SUGGESTED_ATTRIBUTE_SLOTS": SUGGESTED_ATTRIBUTE_SLOTS,
            "_parse_module_rule_text": _parse_module_rule_text,
            "normalize_attribute_group_name": normalize_attribute_group_name,
            "normalize_attribute_slot": normalize_attribute_slot,
            "push_history": lambda: events.append(("history",)),
            "create_attribute_group_from_tokens": create,
            "save_current_project_if_possible": lambda reason: events.append(("save", reason)),
        }
        exec(compile(module, "app.py", "exec"), namespace)

        with self.assertRaises(Rerun):
            namespace["render_attribute_group_sidebar_manager"](project)

        self.assertEqual(events, [
            ("button", "Create Attribute Group", False),
            ("history",),
            ("create", True),
            ("save", "attribute group created"),
            ("rerun",),
        ])
        self.assertEqual(state.attribute_group_sidebar_selected_pending, "milk_swimsuit")
        self.assertEqual(state.attribute_group_sidebar_notice, "Created Attribute Group: Milk Swimsuit")
        self.assertEqual(project.attribute_groups["milk_swimsuit"]["tokens"], ["dress", "hat"])


if __name__ == "__main__":
    unittest.main()
