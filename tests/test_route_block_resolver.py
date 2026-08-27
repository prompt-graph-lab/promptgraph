import copy
import unittest

from core.project import Project, PromptLine
from core.route_operations import (
    get_route_action_dispatch_updates,
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


class RouteBlockResolverTests(unittest.TestCase):
    def test_resolves_separator_to_next_separator_with_structural_counts(self):
        separator_a = _line("route_a", "Route A", line_type="separator", separator_label="Route A")
        normal = _line(
            "line_a",
            generated_candidates=[
                {"path": "active.png"},
                {"path": "trashed.png", "trashed": True},
            ],
            gallery_variants=[
                {"id": "variant_active", "kind": "gallery_variant", "path": "variant.png"},
                {"id": "variant_trashed", "kind": "gallery_variant", "path": "old.png", "trashed": True},
            ],
        )
        workbench = _line("workbench_a", line_type="workbench", workbench_source_line_id="line_a")
        deleted = _line("line_deleted", deleted=True)
        separator_b = _line("route_b", "Route B", line_type="separator", separator_label="Route B")
        project = Project(prompt_lines=[separator_a, normal, workbench, deleted, separator_b])

        block = resolve_route_block(project, "route_a")

        self.assertTrue(block.is_valid)
        self.assertTrue(block.resolved)
        self.assertEqual("route_a", block.route_handle)
        self.assertEqual("Route A", block.separator_label)
        self.assertEqual(0, block.block_start_index)
        self.assertEqual(4, block.block_end_index)
        self.assertEqual(["route_a", "line_a", "workbench_a", "line_deleted"], [line.id for line in block.block_lines])
        self.assertEqual(["line_a", "workbench_a", "line_deleted"], [line.id for line in block.member_lines])
        self.assertEqual(["line_a", "workbench_a"], [line.id for line in block.active_member_lines])
        self.assertEqual(["line_deleted"], [line.id for line in block.deleted_member_lines])
        self.assertEqual(4, block.total_block_line_count)
        self.assertEqual(2, block.normal_member_count)
        self.assertEqual(2, block.active_member_count)
        self.assertEqual(1, block.deleted_member_count)
        self.assertEqual(1, block.workbench_count)
        self.assertEqual(1, block.active_workbench_count)
        self.assertEqual(1, block.deleted_normal_member_count)
        self.assertEqual(1, block.candidate_count)
        self.assertEqual(2, block.candidate_total_count)
        self.assertEqual(1, block.trashed_candidate_count)
        self.assertEqual(1, block.gallery_variant_count)
        self.assertEqual(2, block.gallery_variant_total_count)
        self.assertEqual(1, block.trashed_gallery_variant_count)
        self.assertIsNone(block.previous_separator)
        self.assertIs(block.next_separator, separator_b)

    def test_previous_next_and_final_route_boundaries(self):
        separator_a = _line("route_a", line_type="separator")
        separator_b = _line("route_b", line_type="separator")
        member_b = _line("line_b")
        separator_c = _line("route_c", line_type="separator")
        member_c = _line("line_c")
        project = Project(prompt_lines=[separator_a, separator_b, member_b, separator_c, member_c])

        block_b = resolve_route_block(project, "route_b")
        block_c = resolve_route_block(project, "route_c")

        self.assertIs(block_b.previous_separator, separator_a)
        self.assertIs(block_b.next_separator, separator_c)
        self.assertEqual(["route_b", "line_b"], [line.id for line in block_b.block_lines])
        self.assertEqual(["route_c", "line_c"], [line.id for line in block_c.block_lines])
        self.assertIs(block_c.previous_separator, separator_b)
        self.assertIsNone(block_c.next_separator)
        self.assertEqual(len(project.prompt_lines), block_c.block_end_index)

    def test_diagnostics_cover_missing_normal_deleted_and_empty_routes(self):
        head_line = _line("head")
        deleted_separator = _line("deleted_route", line_type="separator", deleted=True)
        empty_separator = _line("empty_route", line_type="separator")
        next_separator = _line("next_route", line_type="separator")
        project = Project(prompt_lines=[head_line, deleted_separator, empty_separator, next_separator])

        missing = resolve_route_block(project, "unknown")
        normal = resolve_route_block(project, "head")
        deleted = resolve_route_block(project, "deleted_route")
        empty = resolve_route_block(project, "empty_route")

        self.assertIn("separator id not found", missing.diagnostics)
        self.assertIn("specified line is not a separator", normal.diagnostics)
        self.assertIn("head block has no separator", normal.diagnostics)
        self.assertFalse(deleted.is_valid)
        self.assertIn("separator is deleted", deleted.diagnostics)
        self.assertTrue(empty.is_valid)
        self.assertIn("active member is missing", empty.diagnostics)
        self.assertIn("block is empty", empty.diagnostics)

    def test_resolver_does_not_mutate_project_or_prompt_line_order(self):
        lines = [
            _line("route", line_type="separator"),
            _line("line", generated_candidates=[{"path": "candidate.png"}]),
        ]
        project = Project(prompt_lines=lines)
        before = copy.deepcopy(project)

        resolve_route_block(project, "route")

        self.assertEqual(before.prompt_lines, project.prompt_lines)
        self.assertEqual([line.id for line in before.prompt_lines], [line.id for line in project.prompt_lines])


class RouteActionDispatchTests(unittest.TestCase):
    def test_each_shortcut_selects_existing_operation_and_route_scope(self):
        expected = {
            "generation": "generation",
            "candidate_adoption": "candidate_adoption",
            "final_export": "final_export",
            "lightweight_fork": "lightweight_fork",
        }

        for action, operation in expected.items():
            with self.subTest(action=action):
                updates = get_route_action_dispatch_updates(action, "route_b")
                self.assertTrue(updates["dispatch"])
                self.assertEqual(operation, updates["operation"])
                self.assertEqual("selected_route", updates["scope"])
                self.assertEqual("route_b", updates["selected_route_id"])
                self.assertEqual("route_b", updates["updates"]["gallery_selected_route_separator_id"])
                self.assertEqual(
                    {"operation": operation, "route_handle": "route_b"},
                    updates["pending"],
                )
                self.assertEqual("selected_route", updates["scope"])

    def test_invalid_deleted_or_unknown_shortcut_is_not_dispatched(self):
        self.assertFalse(get_route_action_dispatch_updates("generation", "", is_valid=False)["dispatch"])
        self.assertFalse(get_route_action_dispatch_updates("generation", "route", is_deleted=True)["dispatch"])
        self.assertFalse(get_route_action_dispatch_updates("unknown", "route")["dispatch"])
        self.assertEqual({}, get_route_action_dispatch_updates("generation", "", is_valid=False)["updates"])


if __name__ == "__main__":
    unittest.main()
