"""Selected Scenes generation acknowledgement across Streamlit reruns."""

import ast
from pathlib import Path
from textwrap import dedent
import unittest

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
            from contextlib import contextmanager
            import streamlit as st
            from core.project import Project, PromptLine
            from core.gallery_generation import (
                build_selected_routes_generation_plan,
                validate_selected_routes_generation_submit,
            )

            def format_core_message_for_display(value):
                return str(value or "")

            @contextmanager
            def _gallery_operation_body_container(_label, *, expanded, embedded):
                yield

            def _gallery_operation_scope_label(scope):
                return scope

            def _gallery_route_options_with_counts(_project):
                return []

            def _render_selected_routes_gallery_generation_preview(_plan):
                pass

            def _build_selected_routes_gallery_generation_plan(project, run_count, *, full_preflight=False):
                def request_builder(line, run_index):
                    return {"workflow_json": {
                        "line": line.id,
                        "prompt": line.current_text,
                        "run": run_index,
                        "model": st.session_state.workflow_model,
                    }, "warning": ""}

                return build_selected_routes_generation_plan(
                    project,
                    st.session_state.gallery_selected_route_ids,
                    run_count=run_count,
                    generation_options={"workflow_file_signature": {"sha256": "unchanged"}},
                    project_path="C:/project/project.json",
                    request_builder=request_builder if full_preflight else None,
                )

            def push_history():
                st.session_state.events.append("history")

            def _execute_selected_routes_gallery_generation_plan(_project, _plan):
                st.session_state.events.append("execution")
                if st.session_state.candidate_count:
                    st.session_state.events.append("candidate_ingestion")
                return {"candidate_count": st.session_state.candidate_count, "failures": [],
                        "request_results": [], "reason": "no candidates"}

            def save_current_project_if_possible(_reason):
                st.session_state.events.append("save")
            """
        )
        + functions["_prepare_gallery_operation_widget_state"]
        + "\n\n"
        + functions["_sync_gallery_operation_widget_state"]
        + "\n\n"
        + functions["render_gallery_global_generation_controls"]
        + dedent(
            """

            if "project" not in st.session_state:
                st.session_state.project = Project(prompt_lines=[
                    PromptLine(id="route", original_file_name="route.txt", original_index=0,
                               current_index=0, original_text="Route", current_text="Route",
                               tokens=[], line_type="separator", separator_label="Route"),
                    PromptLine(id="line", original_file_name="line.txt", original_index=1,
                               current_index=1, original_text="prompt", current_text="prompt",
                               tokens=["prompt"]),
                ])
                st.session_state.gallery_selected_route_ids = ["route"]
                st.session_state.gallery_generation_scope = "selected_routes"
                st.session_state.workflow_model = "original"
                st.session_state.candidate_count = 0
                st.session_state.events = []
            render_gallery_global_generation_controls(
                st.session_state.project, [], [], embedded=True,
            )
            """
        )
    )


class SelectedRoutesGenerationConfirmationTests(unittest.TestCase):
    def _start(self):
        at = AppTest.from_string(_app_script(), default_timeout=30).run(timeout=30)
        self.assertEqual([], at.exception)
        at.button(key="gallery_generation_selected_routes_fresh_preview").click().run(timeout=30)
        self.assertEqual([], at.exception)
        self.assertTrue(at.session_state["gallery_generation_selected_routes_preview"]["valid"])
        return at

    def _confirm(self, at):
        at.checkbox(key="_gallery_generation_selected_routes_confirm_widget").set_value(True).run(timeout=30)
        self.assertEqual([], at.exception)
        self.assertFalse(at.button(key="pro_gallery_selected_routes_generate").disabled)

    def test_fresh_preview_resets_confirmation(self):
        at = self._start()
        self._confirm(at)
        at.button(key="gallery_generation_selected_routes_fresh_preview").click().run(timeout=30)
        self.assertEqual([], at.exception)
        self.assertFalse(at.checkbox(key="_gallery_generation_selected_routes_confirm_widget").value)
        self.assertTrue(at.button(key="pro_gallery_selected_routes_generate").disabled)

    def test_render_stale_invalidates_confirmation_even_after_exact_restoration(self):
        at = self._start()
        self._confirm(at)
        preview = at.session_state["gallery_generation_selected_routes_preview"].copy()
        at.session_state["project"].prompt_lines[1].current_text = "changed"
        at.run(timeout=30)
        self.assertEqual([], at.exception)
        self.assertTrue(at.button(key="pro_gallery_selected_routes_generate").disabled)
        self.assertFalse(at.checkbox(key="_gallery_generation_selected_routes_confirm_widget").value)
        self.assertEqual([], at.session_state["events"])
        self.assertEqual(preview, at.session_state["gallery_generation_selected_routes_preview"])

        at.session_state["project"].prompt_lines[1].current_text = "prompt"
        at.run(timeout=30)
        self.assertEqual([], at.exception)
        self.assertFalse(at.checkbox(key="_gallery_generation_selected_routes_confirm_widget").value)
        self.assertTrue(at.button(key="pro_gallery_selected_routes_generate").disabled)

    def test_submit_stale_invalidates_confirmation_and_blocks_every_side_effect(self):
        at = self._start()
        self._confirm(at)
        preview = at.session_state["gallery_generation_selected_routes_preview"].copy()
        at.session_state.workflow_model = "changed"
        at.button(key="pro_gallery_selected_routes_generate").click().run(timeout=30)
        self.assertEqual([], at.exception)
        self.assertEqual([], at.session_state["events"])
        self.assertFalse(at.checkbox(key="_gallery_generation_selected_routes_confirm_widget").value)
        self.assertTrue(at.button(key="pro_gallery_selected_routes_generate").disabled)
        self.assertTrue(any("Workflow Preview" in warning.value for warning in at.warning))
        self.assertEqual(preview, at.session_state["gallery_generation_selected_routes_preview"])

        at.session_state.workflow_model = "original"
        at.run(timeout=30)
        self.assertEqual([], at.exception)
        self.assertFalse(at.checkbox(key="_gallery_generation_selected_routes_confirm_widget").value)
        self.assertTrue(at.button(key="pro_gallery_selected_routes_generate").disabled)
        self.assertEqual([], at.session_state["events"])

    def test_generation_reset_keeps_candidate_adoption_confirmations(self):
        at = self._start()
        self._confirm(at)
        at.session_state["route_batch_candidate_adoption_confirm"] = True
        at.session_state["_route_batch_candidate_adoption_confirm_widget"] = True
        at.session_state["gallery_candidate_adoption_confirm"] = True
        at.session_state["_gallery_candidate_adoption_confirm_widget"] = True
        at.session_state["project"].prompt_lines[1].current_text = "changed"
        at.run(timeout=30)
        self.assertEqual([], at.exception)
        for key in (
            "route_batch_candidate_adoption_confirm",
            "_route_batch_candidate_adoption_confirm_widget",
            "gallery_candidate_adoption_confirm",
            "_gallery_candidate_adoption_confirm_widget",
        ):
            self.assertTrue(at.session_state[key])

        at.session_state["project"].prompt_lines[1].current_text = "prompt"
        at.checkbox(key="_gallery_generation_selected_routes_confirm_widget").set_value(True).run(timeout=30)
        at.session_state.workflow_model = "changed"
        at.button(key="pro_gallery_selected_routes_generate").click().run(timeout=30)
        self.assertEqual([], at.exception)
        for key in (
            "route_batch_candidate_adoption_confirm",
            "_route_batch_candidate_adoption_confirm_widget",
            "gallery_candidate_adoption_confirm",
            "_gallery_candidate_adoption_confirm_widget",
        ):
            self.assertTrue(at.session_state[key])

    def test_fresh_submit_preserves_history_execution_and_save_order(self):
        at = self._start()
        self._confirm(at)
        at.button(key="pro_gallery_selected_routes_generate").click().run(timeout=30)
        self.assertEqual([], at.exception)
        self.assertEqual(["history", "execution"], at.session_state["events"])

        at.session_state.events = []
        at.session_state.candidate_count = 2
        at.button(key="pro_gallery_selected_routes_generate").click().run(timeout=30)
        self.assertEqual([], at.exception)
        self.assertEqual(
            ["history", "execution", "candidate_ingestion", "save"],
            at.session_state["events"],
        )


if __name__ == "__main__":
    unittest.main()
