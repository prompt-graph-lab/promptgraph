"""Keep the production Module Swap renderer's stale confirmation behavior."""

import ast
import unittest
from pathlib import Path
from textwrap import dedent

from streamlit.testing.v1 import AppTest


def _app_script():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    functions = {
        node.name: ast.get_source_segment(source, node)
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef)
    }
    return (
        dedent(
            """
            import streamlit as st
            from core.project import Project, PromptLine
            from core.route_operations import sanitize_selected_route_ids
            from core.module_swap_selected_routes import (
                build_selected_routes_module_swap_plan,
                build_selected_routes_module_swap_signature,
            )
            from ui.module_swap_selected_routes_lifecycle import (
                apply_and_publish_selected_routes_module_swap,
            )

            def is_free():
                return False

            def get_project_module_library(project):
                return project.module_library

            def get_project_line_groups(_project):
                return {}

            def get_module_swap_route_options(_project):
                return []

            def get_module_body(library, name):
                return library[name]["body"]

            def _short_preview(value, _limit):
                return value

            def format_core_message_for_display(value):
                return str(value or "")

            def render_batch_preview_text(*_args, **_kwargs):
                pass

            def push_history():
                st.session_state.history_calls = st.session_state.get("history_calls", 0) + 1

            def restore_focus_after_graph_update(_focus):
                pass

            def save_current_project_if_possible(_reason):
                pass
            """
        )
        + functions["_render_selected_routes_module_swap_preview"]
        + "\n\n"
        + functions["render_module_swap_section"]
        + dedent(
            """

            if "project" not in st.session_state:
                st.session_state.project = Project(
                    source_directory="project-source",
                    module_library={
                        "Source": {"body": "source hair, source eyes", "core_tokens": ["source hair"]},
                        "Target": {"body": "target hair, target eyes", "core_tokens": ["target hair"]},
                    },
                    prompt_lines=[
                        PromptLine(id="route", original_file_name="route.txt", original_index=0,
                            current_index=0, original_text="Route", current_text="Route",
                            tokens=[], line_type="separator", separator_label="Route"),
                        PromptLine(id="line", original_file_name="line.txt", original_index=1,
                            current_index=1, original_text="source hair, source eyes",
                            current_text="source hair, source eyes", tokens=["source hair", "source eyes"]),
                    ],
                )
                st.session_state.gallery_selected_route_ids = ["route"]
                st.session_state.module_swap_scope = "selected_routes"
            render_module_swap_section(st.session_state.project)
            """
        )
    )


class ModuleSwapConfirmationRoundTripTests(unittest.TestCase):
    def test_stale_then_exact_original_prompt_requires_new_confirmation(self):
        at = AppTest.from_string(_app_script(), default_timeout=30).run(timeout=30)
        at.button(key="module_swap_preview_btn").click().run(timeout=30)
        preview = at.session_state["module_swap_preview"]["preview"]
        self.assertTrue(preview["valid"])
        self.assertGreater(preview["changed_line_count"], 0)

        at.checkbox(key="module_swap_selected_routes_confirm").set_value(True).run(timeout=30)
        self.assertFalse(at.button(key="module_swap_selected_routes_apply_btn").disabled)

        project = at.session_state["project"]
        original_text = project.prompt_lines[1].current_text
        project.prompt_lines[1].current_text = "source hair, source eyes, drift"
        at.run(timeout=30)
        self.assertEqual(0, len(at.checkbox))

        project.prompt_lines[1].current_text = original_text
        at.run(timeout=30)
        self.assertFalse(at.checkbox(key="module_swap_selected_routes_confirm").value)
        self.assertTrue(at.button(key="module_swap_selected_routes_apply_btn").disabled)


if __name__ == "__main__":
    unittest.main()
