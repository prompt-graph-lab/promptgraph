"""Characterize Selected Routes Module Swap publication only."""

import copy
import unittest
from unittest.mock import patch

from core.module_swap_selected_routes import build_selected_routes_module_swap_plan
from core.project import Project, PromptLine
from ui.module_swap_selected_routes_lifecycle import apply_and_publish_selected_routes_module_swap


class _SessionState(dict):
    def __getattr__(self, name):
        return self[name]

    def __setattr__(self, name, value):
        self[name] = value


def _project(text="source hair, source eyes"):
    return Project(
        source_directory="project-source",
        module_library={
            "Source": {"body": "source hair, source eyes", "core_tokens": ["source hair"]},
            "Target": {"body": "target hair, target eyes", "core_tokens": ["target hair"]},
        },
        prompt_lines=[
            PromptLine(
                id="route", original_file_name="route.txt", original_index=0,
                current_index=0, original_text="Route", current_text="Route",
                tokens=[], line_type="separator", separator_label="Route",
            ),
            PromptLine(
                id="line", original_file_name="line.txt", original_index=1,
                current_index=1, original_text=text, current_text=text,
                tokens=[token.strip() for token in text.split(",")],
                negative_prompt="keep negative", image_path="keep.png",
                generated_candidates=[{"path": "candidate.png"}],
                gallery_variants=[{"path": "variant.png"}],
                source_generation_info={"source": "keep"},
                lineage_info={"parent": "keep"},
            ),
        ],
    )


def _preview(project):
    return build_selected_routes_module_swap_plan(
        project, ["route"], source_module_name="Source",
        target_module_name="Target", project_path="project.json",
    )


class SelectedRoutesModuleSwapLifecycleTests(unittest.TestCase):
    def _state(self, project):
        return _SessionState(
            project=project,
            current_project_path="project.json",
            gallery_selected_route_ids=["route"],
            focused_line_id="line",
            disabled_modules={"Unrelated"},
            module_swap_preview={"stored": True},
            module_swap_selected_routes_confirm=True,
            unrelated_key={"keep": True},
        )

    def _apply(self, state, preview, events):
        def history():
            events.append(("history", state.project, copy.deepcopy(state.project)))

        def focus(value):
            events.append(("focus", value, state.project))

        def save(reason):
            events.append(("save", reason, state.project, dict(state)))

        return apply_and_publish_selected_routes_module_swap(
            preview=preview, source_module_name="Source", target_module_name="Target",
            match_mode="strict", session_state=state, push_history=history,
            restore_focus_after_graph_update=focus,
            save_current_project_if_possible=save,
        )

    def test_success_calls_core_once_and_publishes_exact_result_in_order(self):
        project = _project()
        before = copy.deepcopy(project)
        state = self._state(project)
        original_keys = set(state)
        preview = _preview(project)
        updated = copy.deepcopy(project)
        updated.prompt_lines[1].current_text = "target hair, target eyes"
        events = []

        def core(*args, **kwargs):
            events.append(("core", args[0], state.focused_line_id))
            self.assertIs(project, args[0])
            self.assertEqual(["route"], args[1])
            self.assertEqual(preview["signature"], kwargs["expected_signature"])
            self.assertEqual("project.json", kwargs["project_path"])
            self.assertEqual({"Unrelated"}, kwargs["disabled_modules"])
            return {"applied": True, "updated_project": updated}

        with patch("ui.module_swap_selected_routes_lifecycle.apply_selected_routes_module_swap", side_effect=core) as call:
            result = self._apply(state, preview, events)

        self.assertEqual(1, call.call_count)
        self.assertEqual(["core", "history", "focus", "save"], [event[0] for event in events])
        self.assertIs(project, events[1][1])
        self.assertEqual(before, events[1][2])
        self.assertIs(updated, state.project)
        self.assertIs(updated, result["updated_project"])
        self.assertEqual("line", events[2][1])
        self.assertIs(updated, events[2][2])
        self.assertEqual("Selected Routes Module Swap applied", events[3][1])
        self.assertIs(updated, events[3][2])
        self.assertIn("module_swap_preview", events[3][3])
        self.assertNotIn("module_swap_preview", state)
        self.assertEqual(original_keys - {"module_swap_preview"}, set(state))
        self.assertTrue(state.module_swap_selected_routes_confirm)
        self.assertEqual({"keep": True}, state.unrelated_key)

    def test_focus_is_captured_before_core_apply(self):
        state = self._state(_project())
        events = []

        def core(*_args, **_kwargs):
            state.focused_line_id = "changed during core"
            return {"applied": True, "updated_project": copy.deepcopy(state.project)}

        with patch("ui.module_swap_selected_routes_lifecycle.apply_selected_routes_module_swap", side_effect=core):
            self._apply(state, _preview(state.project), events)
        self.assertEqual("line", events[1][1])
        self.assertEqual("changed during core", state.focused_line_id)

    def test_stale_failure_and_no_op_do_not_publish_or_clean_preview(self):
        for case in ("stale", "failure", "no_op"):
            with self.subTest(case=case):
                project = _project("unrelated" if case == "no_op" else "source hair, source eyes")
                preview = _preview(project)
                state = self._state(project)
                before = dict(state)
                events = []
                if case == "stale":
                    project.prompt_lines[1].current_text = "source hair, source eyes, drift"
                if case == "failure":
                    with patch(
                        "ui.module_swap_selected_routes_lifecycle.apply_selected_routes_module_swap",
                        return_value={"applied": False, "stale_preview": False, "error": "failed"},
                    ) as call:
                        result = self._apply(state, preview, events)
                    self.assertEqual(1, call.call_count)
                    self.assertEqual("failed", result["error"])
                else:
                    result = self._apply(state, preview, events)
                self.assertFalse(result["applied"])
                if case == "stale":
                    self.assertTrue(result["stale_preview"])
                self.assertEqual([], events)
                self.assertIs(project, state.project)
                self.assertEqual(before, dict(state))
                self.assertIn("module_swap_preview", state)
                self.assertTrue(state.module_swap_selected_routes_confirm)


if __name__ == "__main__":
    unittest.main()
