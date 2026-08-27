import copy
import unittest

from core.graph_edit_illustration_browser import (
    DEFAULT_PAGE_SIZE,
    FILTER_ALL,
    FILTER_OUTSIDE_SCENES,
    PAGE_SIZE_OPTIONS,
    build_graph_edit_illustration_browser_plan,
)
from core.project import Project, PromptLine


def _line(line_id, text="prompt", *, line_type=None, deleted=False):
    return PromptLine(
        id=line_id,
        original_file_name=line_id,
        original_index=0,
        current_index=0,
        original_text=text,
        current_text=text,
        tokens=[text],
        line_type=line_type,
        deleted=deleted,
        separator_label=text if line_type == "separator" else None,
    )


def _project():
    lines = [_line("outside_1"), _line("outside_2")]
    lines.append(_line("scene_a", "Scene A", line_type="separator"))
    lines.extend(_line(f"a_{index}") for index in range(1, 16))
    lines.append(_line("scene_b", "Scene B", line_type="separator"))
    lines.extend(_line(f"b_{index}") for index in range(1, 11))
    lines.append(_line("scene_c", "Scene A", line_type="separator"))
    lines.extend(_line(f"c_{index}") for index in range(1, 9))
    lines.append(_line("c_workbench", line_type="workbench"))
    lines.append(_line("deleted", deleted=True))
    for index, line in enumerate(lines):
        line.original_index = index
        line.current_index = index
    return Project(prompt_lines=lines)


def _authoritative_lines(project):
    return [line for line in project.prompt_lines if not line.deleted]


class GraphEditIllustrationBrowserPlanTests(unittest.TestCase):
    def test_default_plan_preserves_authoritative_input_and_project_order(self):
        project = _project()
        before = copy.deepcopy(project)
        authoritative = _authoritative_lines(project)

        plan = build_graph_edit_illustration_browser_plan(project, authoritative)

        self.assertEqual((12, 24, 48), PAGE_SIZE_OPTIONS)
        self.assertEqual(12, DEFAULT_PAGE_SIZE)
        self.assertEqual(FILTER_ALL, plan["filter_value"])
        self.assertEqual(len(authoritative), plan["total_count"])
        self.assertEqual(authoritative[:12], [entry["line"] for entry in plan["page_entries"]])
        self.assertEqual(12, len(plan["page_entries"]))
        self.assertEqual(1, plan["page"])
        self.assertEqual(1, plan["page_start"])
        self.assertEqual(12, plan["page_end"])
        self.assertEqual(before, project)

    def test_existing_separator_and_workbench_inclusion_contract_is_preserved(self):
        project = _project()
        plan = build_graph_edit_illustration_browser_plan(
            project,
            _authoritative_lines(project),
            page_size=48,
        )

        by_id = {entry["line_id"]: entry for entry in plan["all_entries"]}
        self.assertEqual("separator", by_id["scene_a"]["line_type"])
        self.assertEqual("scene_a", by_id["scene_a"]["scene_handle"])
        self.assertEqual("workbench", by_id["c_workbench"]["line_type"])
        self.assertEqual("scene_c", by_id["c_workbench"]["scene_handle"])
        self.assertNotIn("deleted", by_id)

    def test_filters_use_handles_and_disambiguate_duplicate_scene_labels(self):
        project = _project()
        authoritative = _authoritative_lines(project)
        all_plan = build_graph_edit_illustration_browser_plan(project, authoritative)

        labels = [option["label"] for option in all_plan["filter_options"]]
        values = [option["value"] for option in all_plan["filter_options"]]
        self.assertTrue(any(label.startswith("Scene A —") for label in labels))
        self.assertTrue(any(label.startswith("Scene A [2] —") for label in labels))
        self.assertIn("scene:scene_a", values)
        self.assertIn("scene:scene_c", values)

        scene_c = build_graph_edit_illustration_browser_plan(
            project,
            authoritative,
            filter_value="scene:scene_c",
            page_size=48,
        )
        self.assertTrue(scene_c["visible_entries"])
        self.assertEqual(
            {"scene_c"},
            {entry["scene_handle"] for entry in scene_c["visible_entries"]},
        )

        outside = build_graph_edit_illustration_browser_plan(
            project,
            authoritative,
            filter_value=FILTER_OUTSIDE_SCENES,
        )
        self.assertEqual(
            ["outside_1", "outside_2"],
            [entry["line_id"] for entry in outside["visible_entries"]],
        )

    def test_pagination_and_clamp_are_safe(self):
        project = _project()
        authoritative = _authoritative_lines(project)

        second = build_graph_edit_illustration_browser_plan(
            project,
            authoritative,
            page=2,
            page_size=12,
        )
        last = build_graph_edit_illustration_browser_plan(
            project,
            authoritative,
            page=999,
            page_size=12,
        )
        invalid_size = build_graph_edit_illustration_browser_plan(
            project,
            authoritative,
            page_size="All",
        )

        self.assertEqual(authoritative[12:24], [entry["line"] for entry in second["page_entries"]])
        self.assertEqual(last["page_count"], last["page"])
        self.assertLessEqual(len(last["page_entries"]), 12)
        self.assertEqual(DEFAULT_PAGE_SIZE, invalid_size["page_size"])

    def test_all_filter_applies_collapse_before_pagination(self):
        project = _project()
        authoritative = _authoritative_lines(project)

        collapsed = build_graph_edit_illustration_browser_plan(
            project,
            authoritative,
            collapsed_group_keys={"scene:scene_a", FILTER_OUTSIDE_SCENES},
            page_size=48,
        )
        self.assertTrue(collapsed["hidden_by_collapse_count"])
        self.assertFalse(
            {"", "scene_a"}
            & {entry["scene_handle"] for entry in collapsed["visible_entries"]}
        )

        specific = build_graph_edit_illustration_browser_plan(
            project,
            authoritative,
            filter_value="scene:scene_a",
            collapsed_group_keys={"scene:scene_a"},
            page_size=48,
        )
        self.assertTrue(specific["visible_entries"])
        self.assertEqual(0, specific["hidden_by_collapse_count"])

        outside = build_graph_edit_illustration_browser_plan(
            project,
            authoritative,
            filter_value=FILTER_OUTSIDE_SCENES,
            collapsed_group_keys={FILTER_OUTSIDE_SCENES},
        )
        self.assertEqual(2, outside["visible_count"])

    def test_all_collapsed_and_empty_results_are_distinct(self):
        project = _project()
        authoritative = _authoritative_lines(project)
        all_collapsed = build_graph_edit_illustration_browser_plan(
            project,
            authoritative,
            collapsed_group_keys={
                FILTER_OUTSIDE_SCENES,
                "scene:scene_a",
                "scene:scene_b",
                "scene:scene_c",
            },
        )
        empty = build_graph_edit_illustration_browser_plan(
            Project(prompt_lines=[]),
            [],
        )

        self.assertTrue(all_collapsed["all_groups_collapsed"])
        self.assertEqual(0, all_collapsed["visible_count"])
        self.assertFalse(empty["all_groups_collapsed"])
        self.assertEqual(0, empty["total_count"])
        self.assertEqual(1, empty["page"])

    def test_invalid_or_removed_scene_filter_falls_back_to_all(self):
        project = _project()
        authoritative = _authoritative_lines(project)
        invalid = build_graph_edit_illustration_browser_plan(
            project,
            authoritative,
            filter_value="scene:missing",
        )
        self.assertTrue(invalid["filter_fallback"])
        self.assertEqual(FILTER_ALL, invalid["filter_value"])
        self.assertEqual(1, invalid["page"])

        next(line for line in project.prompt_lines if line.id == "scene_b").deleted = True
        after_delete = build_graph_edit_illustration_browser_plan(
            project,
            _authoritative_lines(project),
            filter_value="scene:scene_b",
        )
        self.assertTrue(after_delete["filter_fallback"])
        self.assertEqual(FILTER_ALL, after_delete["filter_value"])

    def test_ambiguous_handles_and_records_outside_project_fail_safe(self):
        project = _project()
        duplicate_separator = _line("scene_a", "Duplicate", line_type="separator")
        project.prompt_lines.extend([duplicate_separator, _line("after_duplicate")])
        external = _line("external")

        plan = build_graph_edit_illustration_browser_plan(
            project,
            _authoritative_lines(project) + [external],
            page_size=48,
        )

        self.assertTrue(any("ambiguous" in item for item in plan["diagnostics"]))
        self.assertTrue(any("outside project.prompt_lines" in item for item in plan["diagnostics"]))
        self.assertNotIn("scene:scene_a", [option["value"] for option in plan["filter_options"]])

    def test_current_illustration_visibility_and_explicit_reveal_target(self):
        project = _project()
        authoritative = _authoritative_lines(project)
        hidden = build_graph_edit_illustration_browser_plan(
            project,
            authoritative,
            page=1,
            page_size=12,
            current_illustration_id="c_8",
        )
        current_page = build_graph_edit_illustration_browser_plan(
            project,
            authoritative,
            filter_value=hidden["reveal_filter_value"],
            page=hidden["reveal_page"],
            page_size=12,
            current_illustration_id="c_8",
        )

        self.assertFalse(hidden["current_on_page"])
        self.assertTrue(hidden["current_reveal_available"])
        self.assertEqual("scene:scene_c", hidden["reveal_filter_value"])
        self.assertTrue(current_page["current_on_page"])

        special = build_graph_edit_illustration_browser_plan(
            project,
            authoritative,
            current_illustration_id="scene_a",
        )
        self.assertFalse(special["current_reveal_available"])

    def test_reserved_scene_ids_use_typed_group_keys_without_collision(self):
        project = Project(
            prompt_lines=[
                _line("outside_item"),
                _line("outside_scenes", "Reserved Scene", line_type="separator"),
                _line("reserved_inside"),
                _line("all", "All Scene", line_type="separator"),
                _line("all_inside"),
            ]
        )
        for index, line in enumerate(project.prompt_lines):
            line.original_index = index
            line.current_index = index
        authoritative = _authoritative_lines(project)

        plan = build_graph_edit_illustration_browser_plan(project, authoritative)
        scene_by_handle = {
            summary["handle"]: summary for summary in plan["scene_summaries"]
        }
        self.assertEqual(
            "scene:outside_scenes",
            scene_by_handle["outside_scenes"]["group_key"],
        )
        self.assertEqual("scene:all", scene_by_handle["all"]["group_key"])
        self.assertEqual(
            FILTER_OUTSIDE_SCENES,
            plan["outside_summary"]["group_key"],
        )
        self.assertIn(
            "scene:outside_scenes",
            [option["value"] for option in plan["filter_options"]],
        )
        self.assertIn(
            FILTER_OUTSIDE_SCENES,
            [option["value"] for option in plan["filter_options"]],
        )

        scene_collapsed = build_graph_edit_illustration_browser_plan(
            project,
            authoritative,
            collapsed_group_keys={"scene:outside_scenes"},
            page_size=48,
        )
        self.assertIn(
            "outside_item",
            [entry["line_id"] for entry in scene_collapsed["visible_entries"]],
        )
        self.assertNotIn(
            "reserved_inside",
            [entry["line_id"] for entry in scene_collapsed["visible_entries"]],
        )

        outside_collapsed = build_graph_edit_illustration_browser_plan(
            project,
            authoritative,
            collapsed_group_keys={FILTER_OUTSIDE_SCENES},
            page_size=48,
        )
        self.assertNotIn(
            "outside_item",
            [entry["line_id"] for entry in outside_collapsed["visible_entries"]],
        )
        self.assertIn(
            "reserved_inside",
            [entry["line_id"] for entry in outside_collapsed["visible_entries"]],
        )

        all_collapsed = build_graph_edit_illustration_browser_plan(
            project,
            authoritative,
            collapsed_group_keys={
                FILTER_OUTSIDE_SCENES,
                "scene:outside_scenes",
                "scene:all",
            },
        )
        self.assertTrue(all_collapsed["all_groups_collapsed"])


if __name__ == "__main__":
    unittest.main()
