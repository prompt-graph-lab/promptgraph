import unittest

from core.project import Project, PromptLine
from core.route_operations import (
    clear_selected_routes,
    duplicate_route_as_baseline,
    get_selectable_route_handles,
    get_selected_route_summary,
    initialize_selected_route_widget_state,
    invert_selected_routes,
    move_route_block,
    remove_route_block,
    restore_removed_route,
    sanitize_selected_route_ids,
    select_all_routes,
    toggle_selected_route,
)


def _line(line_id, text="prompt", *, line_type=None, deleted=False, **fields):
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
        **fields,
    )


def _project():
    lines = [
        _line("head", "Head"),
        _line("route_a", "Route A", line_type="separator", separator_label="Route A"),
        _line(
            "a_line",
            "A prompt",
            generated_candidates=[{"path": "a.png"}],
            gallery_variants=[{"path": "a-variant.png", "kind": "gallery_variant"}],
        ),
        _line(
            "a_workbench",
            "A workbench",
            line_type="workbench",
            workbench_source_line_id="a_line",
        ),
        _line("a_deleted", "A deleted", deleted=True),
        _line("route_b", "Route B", line_type="separator", separator_label="Route B"),
        _line("b_line", "B prompt"),
        _line("route_c", "Route C", line_type="separator", separator_label="Route C"),
        _line("route_d", "Route D", line_type="separator", separator_label="Route D"),
        _line("d_line", "D prompt"),
    ]
    for index, line in enumerate(lines):
        line.current_index = index
    return Project(prompt_lines=lines)


def _fixed_id_factory(source_id, role):
    return f"selected_{role}_{source_id}"


class SelectedRoutesResolverTests(unittest.TestCase):
    def test_selectable_routes_follow_project_order_and_exclude_head_workbench_and_deleted(self):
        project = _project()
        self.assertEqual(
            ["route_a", "route_b", "route_c", "route_d"],
            get_selectable_route_handles(project),
        )
        project.prompt_lines[5].deleted = True
        self.assertEqual(
            ["route_a", "route_c", "route_d"],
            get_selectable_route_handles(project),
        )

    def test_sanitize_normalizes_project_order_and_reports_invalid_ids_without_mutation(self):
        project = _project()
        selected = ["route_d", "route_a", "route_a", "a_line", "missing", "route_c", None, ""]
        original = list(selected)

        result = sanitize_selected_route_ids(project, selected)

        self.assertEqual(["route_a", "route_c", "route_d"], result["selected_route_ids"])
        self.assertEqual(["route_a", "route_c", "route_d"], result["selected_route_handles"])
        self.assertCountEqual(["missing", "", ""], result["removed_missing_ids"])
        self.assertEqual(["route_a"], result["removed_duplicate_ids"])
        self.assertEqual(["a_line"], result["removed_non_separator_ids"])
        self.assertEqual(original, selected)

        project.prompt_lines[5].deleted = True
        deleted_result = sanitize_selected_route_ids(project, ["route_b"])
        self.assertEqual(["route_b"], deleted_result["removed_deleted_ids"])
        self.assertEqual([], deleted_result["selected_route_ids"])

    def test_summary_counts_block_active_main_workbench_deleted_candidates_and_variants(self):
        result = get_selected_route_summary(_project(), ["route_d", "route_a"])

        self.assertEqual(2, result["selected_route_count"])
        self.assertEqual(6, result["selected_line_count"])
        self.assertEqual(5, result["selected_active_line_count"])
        self.assertEqual(2, result["selected_main_line_count"])
        self.assertEqual(1, result["selected_workbench_count"])
        self.assertEqual(1, result["selected_deleted_member_count"])
        self.assertEqual(1, result["selected_candidate_count"])
        self.assertEqual(1, result["selected_gallery_variant_count"])
        self.assertEqual(["Route A", "Route D"], result["selected_route_labels"])
        self.assertEqual(
            ["route_a", "route_d"],
            [summary["route_handle"] for summary in result["selected_route_summaries"]],
        )

    def test_empty_and_consecutive_routes_are_selectable(self):
        result = sanitize_selected_route_ids(_project(), ["route_c"])
        self.assertEqual(["route_c"], result["selected_route_ids"])
        self.assertEqual(1, result["selected_line_count"])
        self.assertEqual(0, result["selected_main_line_count"])

    def test_duplicate_separator_ids_are_ambiguous_and_not_selectable(self):
        project = _project()
        project.prompt_lines.insert(
            8,
            _line("route_a", "Duplicate Route A", line_type="separator"),
        )
        result = sanitize_selected_route_ids(project, ["route_a"])

        self.assertEqual([], result["selected_route_ids"])
        self.assertEqual(["route_a"], result["removed_duplicate_ids"])
        self.assertTrue(any("ambiguous separator id: route_a" in item for item in result["diagnostics"]))
        self.assertNotIn("route_a", get_selectable_route_handles(project))

    def test_malformed_project_input_is_safe(self):
        result = sanitize_selected_route_ids(Project(prompt_lines="invalid"), ["route_a"])
        self.assertEqual([], result["selected_route_ids"])
        self.assertEqual([], result["selectable_route_ids"])
        self.assertTrue(any("prompt_lines is not a list" in item for item in result["diagnostics"]))


class SelectedRoutesMutationTests(unittest.TestCase):
    def test_toggle_select_all_clear_and_invert_are_project_ordered_and_non_mutating(self):
        project = _project()
        selected = ["route_d", "route_a"]
        original = list(selected)

        self.assertEqual(
            ["route_a", "route_b", "route_d"],
            toggle_selected_route(project, selected, "route_b", selected=True),
        )
        self.assertEqual(original, selected)
        self.assertEqual(
            ["route_a"],
            toggle_selected_route(project, selected, "route_d", selected=False),
        )
        self.assertEqual(["route_a", "route_b", "route_c", "route_d"], select_all_routes(project))
        self.assertEqual([], clear_selected_routes(project))
        self.assertEqual(["route_b", "route_c"], invert_selected_routes(project, ["route_a", "route_d"]))
        self.assertEqual(
            ["route_a", "route_b", "route_c", "route_d"],
            invert_selected_routes(project, []),
        )

    def test_invalid_toggle_is_a_no_op(self):
        project = _project()
        self.assertEqual(
            ["route_a"],
            toggle_selected_route(project, ["route_a"], "a_line"),
        )
        self.assertEqual(
            ["route_a"],
            toggle_selected_route(project, ["route_a"], "missing"),
        )


class SelectedRouteWidgetStateTests(unittest.TestCase):
    PREFIX = "pro_gallery_route_selected_"

    def test_uncreated_widget_uses_selected_route_state_without_mutating_it(self):
        selected = ["route_c"]
        widget_state = {}

        widget_key = initialize_selected_route_widget_state(
            widget_state,
            self.PREFIX,
            "route_c",
            selected,
        )

        self.assertTrue(widget_state[widget_key])
        self.assertEqual(["route_c"], selected)

    def test_uncreated_widget_reflects_select_all_invert_and_clear(self):
        for selected, expected in (
            (["route_a", "route_b", "route_c"], True),
            (["route_b"], True),
            ([], False),
        ):
            widget_state = {}
            widget_key = initialize_selected_route_widget_state(
                widget_state,
                self.PREFIX,
                "route_b",
                selected,
            )
            self.assertEqual(expected, widget_state[widget_key])

    def test_existing_widget_is_not_overwritten_by_late_initialization(self):
        widget_key = f"{self.PREFIX}route_c"
        widget_state = {widget_key: False}

        initialize_selected_route_widget_state(
            widget_state,
            self.PREFIX,
            "route_c",
            ["route_c"],
        )

        self.assertFalse(widget_state[widget_key])


class SelectedRoutesStructureChangeTests(unittest.TestCase):
    def test_move_preserves_handles_and_resolver_reorders_them(self):
        project = _project()
        selected = ["route_a", "route_b"]
        result = move_route_block(project, "route_b", "up")

        self.assertTrue(result["moved"])
        self.assertEqual(["route_b", "route_a"], sanitize_selected_route_ids(project, selected)["selected_route_ids"])

    def test_remove_excludes_only_removed_route_and_restore_does_not_auto_select_it(self):
        project = _project()
        selected = ["route_a", "route_b", "route_d"]
        remove_result = remove_route_block(project, "route_b", removal_id="remove-b")
        self.assertTrue(remove_result["removed"])
        after_remove = sanitize_selected_route_ids(project, selected)
        self.assertEqual(["route_a", "route_d"], after_remove["selected_route_ids"])

        restore_result = restore_removed_route(project, "remove-b")
        self.assertTrue(restore_result["restored"])
        after_restore = sanitize_selected_route_ids(project, after_remove["selected_route_ids"])
        self.assertEqual(["route_a", "route_d"], after_restore["selected_route_ids"])
        self.assertIn("route_b", after_restore["selectable_route_ids"])

    def test_duplicate_does_not_auto_select_new_route_or_change_source_selection(self):
        project = _project()
        selected = ["route_a"]
        result = duplicate_route_as_baseline(
            project,
            "route_a",
            id_factory=_fixed_id_factory,
        )
        self.assertTrue(result["duplicated"])
        after_duplicate = sanitize_selected_route_ids(project, selected)
        self.assertEqual(["route_a"], after_duplicate["selected_route_ids"])
        self.assertIn(result["new_route_handle"], after_duplicate["selectable_route_ids"])
        self.assertNotIn(result["new_route_handle"], after_duplicate["selected_route_ids"])

    def test_selection_is_independent_of_collapse_and_pagination(self):
        project = _project()
        selected = ["route_d", "route_a"]
        collapsed = {"route_a": True, "route_d": False}
        page_one = ["route_a"]
        page_two = ["route_d"]
        self.assertEqual(["route_a", "route_d"], sanitize_selected_route_ids(project, selected)["selected_route_ids"])
        self.assertEqual(["route_a"], page_one)
        self.assertEqual(["route_d"], page_two)
        self.assertTrue(collapsed["route_a"])
        self.assertFalse(collapsed["route_d"])


if __name__ == "__main__":
    unittest.main()
