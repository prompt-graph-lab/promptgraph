"""Characterize Selected Routes Attribute Group Swap publication."""

import copy
import unittest
from unittest.mock import patch

from core.attribute_group_swap_selected_routes import (
    apply_selected_routes_attribute_group_swap,
    build_selected_routes_attribute_group_swap_plan,
)
from core.project import Project, PromptLine
from ui.attribute_group_swap_selected_routes_lifecycle import (
    apply_and_publish_selected_routes_attribute_group_swap,
)


class _SessionState(dict):
    def watch(self, events):
        object.__setattr__(self, "_events", events)

    def __getattr__(self, name):
        return self[name]

    def __setattr__(self, name, value):
        self[name] = value

    def __setitem__(self, key, value):
        events = self.__dict__.get("_events")
        if events is not None:
            events.append(("state_set", key, value))
        super().__setitem__(key, value)

    def pop(self, key, *default):
        events = self.__dict__.get("_events")
        if events is not None:
            events.append(("state_pop", key))
        return super().pop(key, *default)


def _project(text="black dress"):
    return Project(
        source_directory="project-source",
        attribute_groups={
            "source": {"name": "Source", "slot": "outfit", "tokens": ["black dress"]},
            "target": {"name": "Target", "slot": "outfit", "tokens": ["green dress"]},
        },
        module_library={"keep": {"body": "unrelated"}},
        prompt_lines=[
            PromptLine(
                id="route", original_file_name="route.txt", original_index=0,
                current_index=0, original_text="Route", current_text="Route",
                tokens=[], line_type="separator", separator_label="Route",
            ),
            PromptLine(
                id="line", original_file_name="line.txt", original_index=1,
                current_index=1, original_text="black dress", current_text=text,
                tokens=[part.strip() for part in text.split(",")],
                negative_prompt="keep negative", image_path="keep.png",
                generated_candidates=[{"path": "candidate.png"}],
                gallery_variants=[{"path": "variant.png"}],
                source_generation_info={"source": "keep"},
                lineage_info={"parent": "keep"},
            ),
        ],
    )


def _preview(project):
    return build_selected_routes_attribute_group_swap_plan(
        project, ["route"], from_group_key="source", to_group_key="target",
        project_path="project.json",
    )


class SelectedRoutesAttributeGroupSwapLifecycleTests(unittest.TestCase):
    def _state(self, project):
        return _SessionState(
            project=project,
            current_project_path="project.json",
            gallery_selected_route_ids=["route"],
            focused_line_id="line",
            swap_preview={"stored": True},
            swap_confirm=True,
        )

    def _apply(self, state, preview, events, mode="gallery"):
        state.watch(events)
        return apply_and_publish_selected_routes_attribute_group_swap(
            preview=preview,
            from_group_key="source",
            to_group_key="target",
            require_full_match=False,
            preview_state_key="swap_preview",
            confirm_key="swap_confirm",
            feedback_mode=mode,
            session_state=state,
            push_history=lambda: events.append(("history", copy.deepcopy(state.project))),
            restore_focus_after_graph_update=lambda focus: events.append(("focus", focus, state.project)),
            sync_text_areas=lambda: events.append(("text", state.project)),
            save_current_project_if_possible=lambda reason: events.append(("save", reason, dict(state))),
        )

    def test_success_calls_core_once_and_publishes_in_order_for_both_surfaces(self):
        for mode in ("gallery", "sidebar"):
            with self.subTest(mode=mode):
                project = _project()
                before = copy.deepcopy(project)
                state = self._state(project)
                preview = _preview(project)
                events = []

                def apply_once(*args, **kwargs):
                    events.append(("core", args[0]))
                    return apply_selected_routes_attribute_group_swap(*args, **kwargs)

                with patch(
                    "ui.attribute_group_swap_selected_routes_lifecycle.apply_selected_routes_attribute_group_swap",
                    side_effect=apply_once,
                ) as core_call:
                    result = self._apply(state, preview, events, mode)

                self.assertTrue(result["applied"])
                self.assertEqual(1, core_call.call_count)
                expected_events = [
                    ("core", None),
                    ("history", None),
                    ("state_set", "project"),
                    ("focus", None),
                    ("text", None),
                    ("state_pop", "swap_preview"),
                    ("state_pop", "swap_confirm"),
                    ("state_set", "gallery_feedback" if mode == "gallery" else "attribute_group_swap_notice"),
                ]
                if mode == "gallery":
                    expected_events.append(("state_set", "gallery_feedback_kind"))
                expected_events.append(("save", None))
                self.assertEqual(
                    expected_events,
                    [(event[0], event[1] if event[0] in ("state_set", "state_pop") else None) for event in events],
                )
                self.assertIs(project, events[0][1])
                self.assertEqual(before, events[1][1])
                self.assertIs(state.project, events[2][2])
                self.assertEqual("line", events[3][1])
                self.assertIs(state.project, events[3][2])
                self.assertIs(state.project, events[4][1])
                self.assertEqual("selected Routes attribute group swap applied", events[-1][1])
                self.assertNotIn("swap_preview", events[-1][2])
                self.assertNotIn("swap_confirm", events[-1][2])
                self.assertEqual("green dress", state.project.prompt_lines[1].current_text)
                self.assertEqual(before.prompt_lines[1].negative_prompt, state.project.prompt_lines[1].negative_prompt)
                for field in (
                    "image_path", "generated_candidates", "gallery_variants",
                    "source_generation_info", "lineage_info",
                ):
                    self.assertEqual(getattr(before.prompt_lines[1], field), getattr(state.project.prompt_lines[1], field))
                self.assertEqual(before.attribute_groups, state.project.attribute_groups)
                self.assertEqual(before.module_library, state.project.module_library)
                self.assertEqual(["route"], state.gallery_selected_route_ids)
                message = "Attribute Group Swap applied to 1 line(s)."
                if mode == "gallery":
                    self.assertEqual(message, state.gallery_feedback)
                    self.assertEqual("success", state.gallery_feedback_kind)
                    self.assertNotIn("attribute_group_swap_notice", state)
                else:
                    self.assertEqual(message, state.attribute_group_swap_notice)
                    self.assertNotIn("gallery_feedback", state)

    def test_stale_core_result_does_not_publish(self):
        project = _project()
        preview = _preview(project)
        project.prompt_lines[1].current_text = "black dress, drift"
        before = copy.deepcopy(project)
        state = self._state(project)
        events = []

        result = self._apply(state, preview, events)

        self.assertTrue(result["stale_preview"])
        self.assertFalse(result["applied"])
        self.assertEqual([], events)
        self.assertIs(project, state.project)
        self.assertEqual(before, state.project)
        self.assertIn("swap_preview", state)
        self.assertTrue(state.swap_confirm)
        self.assertNotIn("gallery_feedback", state)

    def test_no_op_and_invalid_preview_do_not_publish(self):
        for project in (_project("unrelated"), _project()):
            with self.subTest(text=project.prompt_lines[1].current_text):
                preview = _preview(project)
                if project.prompt_lines[1].current_text != "unrelated":
                    preview = {**preview, "signature": ""}
                state = self._state(project)
                events = []
                result = self._apply(state, preview, events)
                self.assertFalse(result["applied"])
                self.assertEqual([], events)
                self.assertIs(project, state.project)
                self.assertIn("swap_preview", state)
                self.assertTrue(state.swap_confirm)

    def test_ordinary_core_failure_does_not_publish(self):
        project = _project()
        state = self._state(project)
        events = []
        with patch(
            "ui.attribute_group_swap_selected_routes_lifecycle.apply_selected_routes_attribute_group_swap",
            return_value={"applied": False, "stale_preview": False, "error": "failed"},
        ) as core_call:
            result = self._apply(state, _preview(project), events)
        self.assertEqual(1, core_call.call_count)
        self.assertEqual("failed", result["error"])
        self.assertEqual([], events)
        self.assertIs(project, state.project)
        self.assertIn("swap_preview", state)
        self.assertTrue(state.swap_confirm)


if __name__ == "__main__":
    unittest.main()
