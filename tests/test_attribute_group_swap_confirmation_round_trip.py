"""Exercise the current Selected Routes swap widget through Streamlit reruns."""

import ast
import unittest
from pathlib import Path
from textwrap import dedent

from streamlit.testing.v1 import AppTest


def _app_script():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {
        node.name: ast.get_source_segment(source, node)
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    return (
        dedent(
            """
            import streamlit as st
            from core.project import Project, PromptLine
            from core.operations import normalize_attribute_slot
            from core.route_operations import sanitize_selected_route_ids
            from core.attribute_group_swap_selected_routes import (
                apply_selected_routes_attribute_group_swap,
                build_selected_routes_attribute_group_swap_plan,
                build_selected_routes_attribute_group_swap_signature,
                get_attribute_groups_snapshot,
            )

            def format_core_message_for_display(value):
                return str(value or "")

            def _short_preview(value, _limit):
                return value

            def render_batch_preview_text(*_args, **_kwargs):
                pass

            def push_history():
                st.session_state.history_calls = st.session_state.get("history_calls", 0) + 1

            def restore_focus_after_graph_update(_focus):
                pass

            def sync_text_areas():
                pass

            def save_current_project_if_possible(_reason):
                pass
            """
        )
        + functions["_render_selected_routes_attribute_group_swap_preview"]
        + "\n\n"
        + functions["_render_selected_routes_attribute_group_swap_flow"]
        + dedent(
            """

            if "project" not in st.session_state:
                st.session_state.project = Project(
                    source_directory="project-source",
                    attribute_groups={
                        "source": {"name": "Source", "slot": "outfit", "tokens": ["black dress"]},
                        "target": {"name": "Target", "slot": "outfit", "tokens": ["green dress"]},
                    },
                    prompt_lines=[
                        PromptLine(id="route", original_file_name="route.txt", original_index=0,
                            current_index=0, original_text="Route", current_text="Route",
                            tokens=[], line_type="separator", separator_label="Route"),
                        PromptLine(id="line", original_file_name="line.txt", original_index=1,
                            current_index=1, original_text="black dress", current_text="black dress",
                            tokens=["black dress"]),
                    ],
                )
                st.session_state.gallery_selected_route_ids = ["route"]
            _render_selected_routes_attribute_group_swap_flow(
                st.session_state.project,
                get_attribute_groups_snapshot(st.session_state.project),
                "source", "target", False,
                key_prefix="roundtrip", preview_state_key="roundtrip_preview",
                feedback_mode="gallery",
            )
            """
        )
    )


class ConfirmationRoundTripTests(unittest.TestCase):
    def test_stale_then_exact_original_fingerprint_requires_new_confirmation(self):
        at = AppTest.from_string(_app_script(), default_timeout=30).run(timeout=30)
        at.button(key="roundtrip_preview_btn").click().run(timeout=30)
        self.assertTrue(at.session_state["roundtrip_preview"]["preview"]["valid"])
        self.assertGreater(at.session_state["roundtrip_preview"]["preview"]["changed_line_count"], 0)

        at.checkbox(key="roundtrip_selected_routes_confirm").set_value(True).run(timeout=30)
        self.assertFalse(at.button(key="roundtrip_apply_btn").disabled)

        project = at.session_state["project"]
        original_text = project.prompt_lines[1].current_text
        project.prompt_lines[1].current_text = "black dress, changed"
        at.run(timeout=30)
        self.assertEqual(0, len(at.checkbox))

        project.prompt_lines[1].current_text = original_text
        at.run(timeout=30)
        self.assertFalse(at.checkbox(key="roundtrip_selected_routes_confirm").value)
        self.assertTrue(at.button(key="roundtrip_apply_btn").disabled)


if __name__ == "__main__":
    unittest.main()
