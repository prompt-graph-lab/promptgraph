import copy
import unittest

from core.project import Project, PromptLine
from core.route_operations import (
    get_route_block_move_availability,
    get_route_move_ui_state,
    move_route_block,
    move_route_block_down,
    move_route_block_up,
    resolve_route_block,
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


def _three_route_project():
    head = _line("head", "Head block")
    route_a = _line("route_a", "Route A", line_type="separator", separator_label="Route A")
    a_line = _line("a_line", "A prompt")
    route_b = _line("route_b", "Route B", line_type="separator", separator_label="Route B")
    b_line = _line(
        "b_line",
        "B prompt",
        image_path="b.png",
        generated_candidates=[{"path": "b-candidate.png", "tag": "keep"}],
        gallery_variants=[{"path": "b-variant.png", "kind": "gallery_variant"}],
    )
    b_workbench = _line(
        "b_workbench",
        "B workbench",
        line_type="workbench",
        workbench_source_line_id="b_line",
    )
    b_deleted = _line("b_deleted", "B deleted", deleted=True)
    route_c = _line("route_c", "Route C", line_type="separator", separator_label="Route C")
    c_line = _line("c_line", "C prompt")
    return Project(
        prompt_lines=[head, route_a, a_line, route_b, b_line, b_workbench, b_deleted, route_c, c_line]
    )


class RouteMoveTests(unittest.TestCase):
    def test_move_middle_route_up_keeps_the_contiguous_block_and_metadata(self):
        project = _three_route_project()
        b_line = next(line for line in project.prompt_lines if line.id == "b_line")
        before_b = copy.deepcopy(b_line)

        result = move_route_block_up(project, "route_b")

        self.assertTrue(result["moved"])
        self.assertEqual("up", result["direction"])
        self.assertEqual(3, result["source_start"])
        self.assertEqual(7, result["source_end"])
        self.assertEqual(1, result["destination_index"])
        self.assertEqual("route_a", result["previous_route_handle"])
        self.assertEqual("route_c", result["next_route_handle"])
        self.assertEqual(
            ["head", "route_b", "b_line", "b_workbench", "b_deleted", "route_a", "a_line", "route_c", "c_line"],
            [line.id for line in project.prompt_lines],
        )
        self.assertEqual(["route_b", "b_line", "b_workbench", "b_deleted"], result["affected_line_ids"])
        self.assertEqual(before_b.image_path, b_line.image_path)
        self.assertEqual(before_b.generated_candidates, b_line.generated_candidates)
        self.assertEqual(before_b.gallery_variants, b_line.gallery_variants)
        self.assertEqual(before_b.current_text, b_line.current_text)
        self.assertEqual(list(range(len(project.prompt_lines))), [line.current_index for line in project.prompt_lines])

        moved_block = resolve_route_block(project, "route_b")
        self.assertEqual(1, moved_block.block_start_index)
        self.assertEqual(5, moved_block.block_end_index)
        self.assertIsNone(moved_block.previous_separator)
        self.assertEqual("route_a", moved_block.next_separator.id)

    def test_move_middle_route_down_keeps_adjacent_route_intact(self):
        project = _three_route_project()

        result = move_route_block_down(project, "route_b")

        self.assertTrue(result["moved"])
        self.assertEqual(5, result["destination_index"])
        self.assertEqual(
            ["head", "route_a", "a_line", "route_c", "c_line", "route_b", "b_line", "b_workbench", "b_deleted"],
            [line.id for line in project.prompt_lines],
        )
        self.assertEqual(
            ["route_a", "a_line"],
            [line.id for line in resolve_route_block(project, "route_a").block_lines],
        )
        self.assertEqual(
            ["route_b", "b_line", "b_workbench", "b_deleted"],
            [line.id for line in resolve_route_block(project, "route_b").block_lines],
        )
        self.assertEqual("route_c", resolve_route_block(project, "route_b").previous_separator.id)

    def test_first_explicit_route_does_not_cross_the_head_block(self):
        project = _three_route_project()
        before_ids = [line.id for line in project.prompt_lines]

        availability = get_route_block_move_availability(project, "route_a")
        result = move_route_block(project, "route_a", "up")

        self.assertFalse(availability["can_move_up"])
        self.assertTrue(availability["can_move_down"])
        self.assertFalse(result["moved"])
        self.assertEqual("already first Route", result["reason"])
        self.assertEqual(before_ids, [line.id for line in project.prompt_lines])

    def test_last_route_does_not_move_beyond_the_list(self):
        project = _three_route_project()
        before_ids = [line.id for line in project.prompt_lines]

        availability = get_route_block_move_availability(project, "route_c")
        result = move_route_block_down(project, "route_c")

        self.assertFalse(availability["can_move_down"])
        self.assertFalse(result["moved"])
        self.assertEqual("already last Route", result["reason"])
        self.assertEqual(before_ids, [line.id for line in project.prompt_lines])

    def test_deleted_separator_and_normal_line_are_not_route_move_targets(self):
        deleted_separator = _line("deleted_route", "Deleted", line_type="separator", deleted=True)
        normal = _line("normal", "Normal")
        project = Project(prompt_lines=[deleted_separator, normal])

        deleted_result = move_route_block_up(project, "deleted_route")
        normal_result = move_route_block_down(project, "normal")

        self.assertFalse(deleted_result["moved"])
        self.assertEqual("separator is deleted", deleted_result["reason"])
        self.assertFalse(normal_result["moved"])
        self.assertEqual("target is not separator", normal_result["reason"])

    def test_deleted_separator_is_not_an_adjacent_move_destination(self):
        route_a = _line("route_a", line_type="separator")
        deleted_separator = _line("deleted_route", line_type="separator", deleted=True)
        a_line = _line("a_line")
        project = Project(prompt_lines=[route_a, deleted_separator, a_line])

        availability = get_route_block_move_availability(project, "route_a")
        result = move_route_block_down(project, "route_a")

        self.assertFalse(availability["can_move_down"])
        self.assertEqual("deleted_route", availability["next_route_handle"])
        self.assertFalse(result["moved"])
        self.assertEqual("no adjacent Route", result["reason"])
        self.assertEqual(["route_a", "deleted_route", "a_line"], [line.id for line in project.prompt_lines])

    def test_empty_and_consecutive_routes_are_structural_blocks(self):
        route_a = _line("route_a", line_type="separator")
        route_b = _line("route_b", line_type="separator")
        b_line = _line("b_line")
        project = Project(prompt_lines=[route_a, route_b, b_line])

        result = move_route_block_up(project, "route_b")

        self.assertTrue(result["moved"])
        self.assertEqual(["route_b", "b_line", "route_a"], [line.id for line in project.prompt_lines])

    def test_invalid_direction_and_missing_separator_do_not_mutate(self):
        project = _three_route_project()
        before = copy.deepcopy(project)

        invalid = move_route_block(project, "route_b", "sideways")
        missing = move_route_block(project, "missing", "up")

        self.assertFalse(invalid["moved"])
        self.assertEqual("invalid direction", invalid["reason"])
        self.assertFalse(missing["moved"])
        self.assertEqual("separator not found", missing["reason"])
        self.assertEqual(before.prompt_lines, project.prompt_lines)

    def test_move_ui_state_preserves_same_route_and_other_route_line_ids(self):
        project = _three_route_project()
        move_route_block_up(project, "route_b")

        same_route_state = get_route_move_ui_state(
            project,
            route_handle="route_b",
            focused_line_id="b_line",
            highlighted_line_id="b_workbench",
            expanded_line_id="b_line",
        )
        other_route_state = get_route_move_ui_state(
            project,
            route_handle="route_b",
            focused_line_id="c_line",
            highlighted_line_id="a_line",
            expanded_line_id="c_line",
        )

        self.assertEqual(
            {
                "focused_line_id": "b_line",
                "highlighted_line_id": "b_workbench",
                "gallery_expanded_line_id": "b_line",
                "gallery_selected_route_separator_id": "route_b",
            },
            same_route_state,
        )
        self.assertEqual("c_line", other_route_state["focused_line_id"])
        self.assertEqual("a_line", other_route_state["highlighted_line_id"])
        self.assertEqual("c_line", other_route_state["gallery_expanded_line_id"])
        self.assertEqual("route_b", other_route_state["gallery_selected_route_separator_id"])

    def test_move_ui_state_clears_missing_or_deleted_line_ids(self):
        project = _three_route_project()

        state = get_route_move_ui_state(
            project,
            route_handle="route_b",
            focused_line_id="missing",
            highlighted_line_id="b_deleted",
            expanded_line_id="missing-expanded",
        )

        self.assertIsNone(state["focused_line_id"])
        self.assertIsNone(state["highlighted_line_id"])
        self.assertIsNone(state["gallery_expanded_line_id"])
        self.assertEqual("route_b", state["gallery_selected_route_separator_id"])


if __name__ == "__main__":
    unittest.main()
