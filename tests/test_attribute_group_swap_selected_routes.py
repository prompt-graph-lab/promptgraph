import copy
import unittest

from core.attribute_group_swap_selected_routes import (
    apply_selected_routes_attribute_group_swap,
    build_selected_routes_attribute_group_swap_plan,
    build_selected_routes_attribute_group_swap_signature,
    get_attribute_groups_snapshot,
)
from core.operations import apply_attribute_group_swap, preview_attribute_group_swap
from core.project import Project, PromptLine


def _line(
    line_id,
    text,
    *,
    line_type=None,
    deleted=False,
    current_index=0,
    negative_prompt="keep negative",
    image_path=None,
    selected_candidate_path=None,
):
    return PromptLine(
        id=line_id,
        original_file_name=f"{line_id}.txt",
        original_index=current_index,
        current_index=current_index,
        original_text=f"original {line_id}",
        current_text=text,
        tokens=[token.strip() for token in str(text or "").split(",") if token.strip()],
        negative_prompt=negative_prompt,
        line_type=line_type,
        deleted=deleted,
        image_path=image_path,
        selected_candidate_path=selected_candidate_path,
        generated_candidates=[{"id": f"candidate_{line_id}", "path": f"{line_id}-candidate.png"}],
        gallery_variants=[{"id": f"variant_{line_id}", "path": f"{line_id}-variant.png"}],
        source_generation_info={"source_image_path": f"source-{line_id}.png"},
        lineage_info={"parent_line_id": f"parent-{line_id}"},
    )


def _separator(line_id, label, *, deleted=False, current_index=0):
    return PromptLine(
        id=line_id,
        original_file_name=f"{line_id}.txt",
        original_index=current_index,
        current_index=current_index,
        original_text=label,
        current_text=label,
        tokens=[],
        line_type="separator",
        separator_label=label,
        separator_color="#123456",
        deleted=deleted,
    )


def _project():
    return Project(
        source_directory="project-source",
        attribute_groups={
            "black_outfit": {
                "name": "Black Outfit",
                "slot": " Outfit ",
                "tokens": ["black dress", "ribbon"],
                "negative_tags": ["black dress"],
                "negative_when_disabled": ["black dress"],
                "negative_notes": "source metadata",
                "custom_metadata": {"keep": True},
            },
            "green_outfit": {
                "name": "Green Outfit",
                "slot": "OUTFIT",
                "tokens": ["green dress", "ribbon"],
                "negative_tags": ["green dress"],
                "negative_when_disabled": ["green dress"],
                "negative_notes": "replacement metadata",
            },
            "expression": {
                "name": "Expression",
                "slot": "expression_set",
                "tokens": ["smile"],
                "negative_tags": [],
                "negative_when_disabled": [],
                "negative_notes": "",
            },
            "same_outfit": {
                "name": "Same Outfit",
                "slot": "outfit",
                "tokens": ["black dress", "ribbon"],
                "negative_tags": [],
                "negative_when_disabled": [],
                "negative_notes": "",
            },
        },
        module_library={"Keep": {"body": "keep", "custom_metadata": {"v": 1}}},
        prompt_lines=[
            _separator("route_a", "Route A", current_index=100),
            _line("a1", "quality, black dress, ribbon, smile", current_index=90, image_path="a1.png"),
            _line("a2", "black dress, beach", current_index=80),
            _line("a_workbench", "black dress, ribbon", line_type="workbench", current_index=70),
            _line("a_deleted", "black dress, ribbon", deleted=True, current_index=60),
            _separator("route_b", "Route B", current_index=50),
            _line("b1", "black dress, ribbon, city", current_index=40),
            _separator("route_c", "Route C", current_index=30),
            _line(
                "c1",
                "black dress, ribbon, night",
                current_index=20,
                selected_candidate_path="c1-selected.png",
            ),
            _line("c2", "unrelated, forest", current_index=10),
        ],
    )


class SelectedRoutesAttributeGroupSwapPlanTests(unittest.TestCase):
    def _plan(self, project=None, selected=("route_c", "route_a"), **kwargs):
        return build_selected_routes_attribute_group_swap_plan(
            project or _project(),
            list(selected),
            from_group_key="black_outfit",
            to_group_key="green_outfit",
            project_path="project.json",
            **kwargs,
        )

    def test_project_order_match_classification_and_target_exclusions(self):
        plan = self._plan()

        self.assertTrue(plan["valid"])
        self.assertEqual(["route_a", "route_c"], plan["selected_route_ids"])
        self.assertEqual(["a1", "a2", "c1", "c2"], plan["target_line_ids"])
        self.assertEqual(["a1", "a2", "c1", "c2"], [entry["line_id"] for entry in plan["entries"]])
        self.assertEqual(2, plan["full_match_count"])
        self.assertEqual(1, plan["partial_match_count"])
        self.assertEqual(1, plan["no_match_count"])
        self.assertEqual(3, plan["changed_line_count"])
        self.assertNotIn("b1", plan["target_line_ids"])
        self.assertNotIn("a_workbench", plan["target_line_ids"])
        self.assertNotIn("a_deleted", plan["target_line_ids"])

    def test_display_snapshot_normalizes_without_mutating_source_library(self):
        project = _project()
        before = copy.deepcopy(project)

        groups = get_attribute_groups_snapshot(project)

        self.assertEqual("outfit", groups["black_outfit"]["slot"])
        self.assertEqual("outfit", groups["green_outfit"]["slot"])
        self.assertEqual(before, project)
        self.assertEqual({"keep": True}, project.attribute_groups["black_outfit"]["custom_metadata"])
        self.assertEqual(" Outfit ", project.attribute_groups["black_outfit"]["slot"])

    def test_stale_current_index_does_not_change_physical_order(self):
        project = _project()
        project.prompt_lines[1].current_index = 999
        project.prompt_lines[8].current_index = -10

        plan = self._plan(project)

        self.assertEqual(["a1", "a2", "c1", "c2"], plan["target_line_ids"])
        self.assertEqual([1, 2, 8, 9], [entry["project_order"] for entry in plan["entries"]])
        self.assertEqual([0, 1, 0, 1], [entry["route_line_order"] for entry in plan["entries"]])

    def test_normalized_same_slot_is_compatible_and_cross_slot_is_blocked(self):
        compatible = self._plan()
        mismatch = build_selected_routes_attribute_group_swap_plan(
            _project(),
            ["route_a"],
            from_group_key="black_outfit",
            to_group_key="expression",
        )

        self.assertEqual("outfit", compatible["from_slot"])
        self.assertEqual("outfit", compatible["to_slot"])
        self.assertTrue(compatible["slot_compatible"])
        self.assertFalse(mismatch["valid"])
        self.assertIn("Attribute Slot mismatch", mismatch["reason"])
        self.assertEqual(0, mismatch["changed_line_count"])

    def test_missing_and_malformed_slot_or_tokens_fail_closed(self):
        mutations = {
            "missing_slot": lambda project: project.attribute_groups["black_outfit"].__setitem__("slot", None),
            "object_slot": lambda project: project.attribute_groups["black_outfit"].__setitem__("slot", object()),
            "string_tokens": lambda project: project.attribute_groups["black_outfit"].__setitem__("tokens", "black dress"),
            "object_tokens": lambda project: project.attribute_groups["black_outfit"].__setitem__("tokens", object()),
            "object_token_value": lambda project: project.attribute_groups["black_outfit"].__setitem__(
                "tokens", ["black dress", object()]
            ),
        }
        for name, mutate in mutations.items():
            project = _project()
            mutate(project)
            with self.subTest(name=name):
                plan = self._plan(project)
                self.assertFalse(plan["valid"])
                self.assertEqual(0, plan["changed_line_count"])

    def test_require_full_match_preserves_existing_partial_semantics(self):
        permissive = self._plan()
        full_only = self._plan(require_full_match=True)
        permissive_by_id = {entry["line_id"]: entry for entry in permissive["entries"]}
        full_by_id = {entry["line_id"]: entry for entry in full_only["entries"]}

        self.assertTrue(permissive_by_id["a2"]["positive_changed"])
        self.assertEqual("green dress, beach", permissive_by_id["a2"]["after_positive_prompt"])
        self.assertFalse(full_by_id["a2"]["positive_changed"])
        self.assertEqual("partial match blocked by require full match", full_by_id["a2"]["skip_reason"])
        self.assertEqual(2, full_only["changed_line_count"])

    def test_one_route_matches_existing_preview_semantics(self):
        project = _project()
        selected = build_selected_routes_attribute_group_swap_plan(
            project,
            ["route_a"],
            from_group_key="black_outfit",
            to_group_key="green_outfit",
        )
        existing = preview_attribute_group_swap(
            copy.deepcopy(project),
            "black_outfit",
            "green_outfit",
            target_line_ids=["a1", "a2"],
            example_limit=100,
            include_unchanged_examples=True,
        )

        self.assertEqual(existing["affected_line_count"], selected["changed_line_count"])
        self.assertEqual(existing["tokens_to_remove"], selected["tokens_to_remove"])
        self.assertEqual(existing["tokens_to_add"], selected["tokens_to_add"])
        self.assertEqual(
            [entry["after"] for entry in existing["examples"]],
            [entry["after_positive_prompt"] for entry in selected["entries"]],
        )

    def test_negative_metadata_is_preview_only_and_source_is_immutable(self):
        project = _project()
        before = copy.deepcopy(project)

        plan = self._plan(project)
        entry = next(item for item in plan["entries"] if item["line_id"] == "a1")

        self.assertEqual("keep negative", entry["before_negative_prompt"])
        self.assertEqual("keep negative", entry["after_negative_prompt"])
        self.assertEqual(["black dress"], entry["source_negative_metadata_preview"]["negative_when_disabled"])
        self.assertEqual(["green dress"], entry["replacement_negative_metadata_preview"]["negative_when_disabled"])
        self.assertEqual("source metadata", entry["source_negative_metadata_preview"]["negative_notes"])
        self.assertEqual("replacement metadata", entry["replacement_negative_metadata_preview"]["negative_notes"])
        self.assertEqual(0, plan["negative_change_count"])
        self.assertIn("preview-only", plan["negative_prompt_semantics"])
        self.assertEqual(before, project)

    def test_malformed_negative_metadata_matches_diagnostics_and_preview(self):
        project = _project()
        invalid_tag = object()
        invalid_disabled = object()
        invalid_notes = object()
        source = project.attribute_groups["black_outfit"]
        source["negative_tags"] = ["valid tag", invalid_tag]
        source["negative_when_disabled"] = [invalid_disabled, "valid disabled"]
        source["negative_notes"] = invalid_notes

        plan = self._plan(project)
        entry = next(item for item in plan["entries"] if item["line_id"] == "a1")

        self.assertTrue(plan["valid"])
        self.assertEqual(["valid tag"], plan["from_group_snapshot"]["negative_tags"])
        self.assertEqual(["valid disabled"], plan["from_group_snapshot"]["negative_when_disabled"])
        self.assertEqual("", plan["from_group_snapshot"]["negative_notes"])
        self.assertEqual(
            ["valid tag"], entry["source_negative_metadata_preview"]["negative_tags"]
        )
        self.assertEqual(
            ["valid disabled"],
            entry["source_negative_metadata_preview"]["negative_when_disabled"],
        )
        self.assertEqual("", entry["source_negative_metadata_preview"]["negative_notes"])
        self.assertTrue(any("non-string values" in item for item in plan["diagnostics"]))
        self.assertTrue(any("negative_notes" in item for item in plan["diagnostics"]))
        self.assertIs(invalid_tag, source["negative_tags"][1])
        self.assertIs(invalid_disabled, source["negative_when_disabled"][0])
        self.assertIs(invalid_notes, source["negative_notes"])

    def test_drift_classification_uses_resolved_main_image_priority(self):
        plan = self._plan()
        entries = {entry["line_id"]: entry for entry in plan["entries"]}

        self.assertEqual("image_path", entries["a1"]["main_image_field"])
        self.assertEqual("prompt changed while main image remains unchanged", entries["a1"]["drift_risk"])
        self.assertEqual("prompt changed, no representative image", entries["a2"]["drift_risk"])
        self.assertEqual("selected_candidate_path", entries["c1"]["main_image_field"])
        self.assertEqual("no prompt change", entries["c2"]["drift_risk"])

    def test_empty_invalid_and_duplicate_line_selection_fail_safely(self):
        empty = self._plan(selected=())
        project = _project()
        project.prompt_lines[2].id = "a1"
        duplicate = self._plan(project, selected=("route_a",))

        self.assertFalse(empty["valid"])
        self.assertIn("no selected Routes", empty["reason"])
        self.assertFalse(duplicate["valid"])
        self.assertIn("duplicate Line", duplicate["reason"])

    def test_malformed_project_and_library_return_diagnostics(self):
        project = _project()
        project.attribute_groups = object()
        malformed_library = self._plan(project)
        project = _project()
        project.prompt_lines[1].current_text = None
        project.prompt_lines[1].tokens = object()
        malformed_line = self._plan(project)
        project = _project()
        project.prompt_lines[1].tokens = {"bad": "tokens"}
        malformed_tokens = self._plan(project)

        self.assertFalse(malformed_library["valid"])
        self.assertTrue(malformed_library["diagnostics"])
        self.assertFalse(malformed_line["valid"])
        self.assertIn("malformed tokens", malformed_line["reason"])
        self.assertFalse(malformed_tokens["valid"])
        self.assertIn("malformed tokens", malformed_tokens["reason"])

    def test_identical_group_tokens_are_no_op(self):
        plan = build_selected_routes_attribute_group_swap_plan(
            _project(),
            ["route_a"],
            from_group_key="black_outfit",
            to_group_key="same_outfit",
        )

        self.assertTrue(plan["valid"])
        self.assertEqual(0, plan["changed_line_count"])
        self.assertEqual(plan["target_line_count"], plan["no_op_count"])


class SelectedRoutesAttributeGroupSwapApplyTests(unittest.TestCase):
    def _preview(self, project, selected=("route_c", "route_a"), **kwargs):
        return build_selected_routes_attribute_group_swap_plan(
            project,
            list(selected),
            from_group_key="black_outfit",
            to_group_key="green_outfit",
            project_path="project.json",
            **kwargs,
        )

    def _apply(self, project, preview, selected=("route_c", "route_a"), **kwargs):
        return apply_selected_routes_attribute_group_swap(
            project,
            list(selected),
            expected_signature=preview["signature"],
            from_group_key="black_outfit",
            to_group_key="green_outfit",
            project_path="project.json",
            **kwargs,
        )

    def test_atomic_apply_changes_only_expected_prompt_fields(self):
        project = _project()
        source_before = copy.deepcopy(project)
        preview = self._preview(project)
        apply_calls = []

        def counted_apply(*args, **kwargs):
            apply_calls.append(1)
            return apply_attribute_group_swap(*args, **kwargs)

        result = self._apply(project, preview, apply_func=counted_apply)

        self.assertTrue(result["applied"])
        self.assertEqual(3, result["applied_count"])
        self.assertEqual(1, len(apply_calls))
        self.assertEqual(source_before, project)
        updated = result["updated_project"]
        updated_by_id = {line.id: line for line in updated.prompt_lines}
        source_by_id = {line.id: line for line in source_before.prompt_lines}
        self.assertEqual("quality, green dress, ribbon, smile", updated_by_id["a1"].current_text)
        self.assertEqual(["quality", "green dress", "ribbon", "smile"], updated_by_id["a1"].tokens)
        self.assertEqual("black dress, ribbon, city", updated_by_id["b1"].current_text)
        self.assertEqual("unrelated, forest", updated_by_id["c2"].current_text)
        for line_id in source_by_id:
            before = source_by_id[line_id]
            after = updated_by_id[line_id]
            self.assertEqual(before.negative_prompt, after.negative_prompt)
            self.assertEqual(before.image_path, after.image_path)
            self.assertEqual(before.generated_image_path, after.generated_image_path)
            self.assertEqual(before.selected_candidate_path, after.selected_candidate_path)
            self.assertEqual(before.generated_candidates, after.generated_candidates)
            self.assertEqual(before.gallery_variants, after.gallery_variants)
            self.assertEqual(before.source_generation_info, after.source_generation_info)
            self.assertEqual(before.lineage_info, after.lineage_info)
            self.assertEqual(before.original_text, after.original_text)
        self.assertEqual(source_before.attribute_groups, updated.attribute_groups)
        self.assertEqual(source_before.module_library, updated.module_library)
        self.assertEqual([line.id for line in source_before.prompt_lines], [line.id for line in updated.prompt_lines])

    def test_require_full_match_apply_skips_partial_line(self):
        project = _project()
        preview = self._preview(project, require_full_match=True)
        result = self._apply(project, preview, require_full_match=True)
        updated = {line.id: line for line in result["updated_project"].prompt_lines}

        self.assertTrue(result["applied"])
        self.assertEqual(2, result["applied_count"])
        self.assertEqual("black dress, beach", updated["a2"].current_text)

    def test_prompt_image_group_option_route_and_project_changes_make_preview_stale(self):
        mutations = {
            "prompt": lambda project: setattr(project.prompt_lines[1], "current_text", "changed"),
            "negative": lambda project: setattr(project.prompt_lines[1], "negative_prompt", "changed"),
            "tokens": lambda project: setattr(project.prompt_lines[1], "tokens", ["changed"]),
            "selected_image": lambda project: setattr(project.prompt_lines[2], "selected_candidate_path", "new.png"),
            "generated_image": lambda project: setattr(project.prompt_lines[2], "generated_image_path", "new.png"),
            "image_path": lambda project: setattr(project.prompt_lines[1], "image_path", "new.png"),
            "source_tokens": lambda project: project.attribute_groups["black_outfit"].__setitem__("tokens", ["changed"]),
            "target_tokens": lambda project: project.attribute_groups["green_outfit"].__setitem__("tokens", ["changed"]),
            "source_slot": lambda project: project.attribute_groups["black_outfit"].__setitem__("slot", "changed"),
            "negative_tags": lambda project: project.attribute_groups["black_outfit"].__setitem__("negative_tags", ["changed"]),
            "negative_disabled": lambda project: project.attribute_groups["green_outfit"].__setitem__("negative_when_disabled", ["changed"]),
            "negative_notes": lambda project: project.attribute_groups["green_outfit"].__setitem__("negative_notes", "changed"),
            "route_move": lambda project: project.prompt_lines.__setitem__(
                slice(None), project.prompt_lines[5:8] + project.prompt_lines[0:5] + project.prompt_lines[8:]
            ),
        }
        for name, mutate in mutations.items():
            project = _project()
            preview = self._preview(project)
            mutate(project)
            current = build_selected_routes_attribute_group_swap_signature(
                project,
                ["route_a", "route_c"],
                from_group_key="black_outfit",
                to_group_key="green_outfit",
                project_path="project.json",
            )
            with self.subTest(name=name):
                self.assertNotEqual(preview["signature"], current)

        project = _project()
        preview = self._preview(project)
        self.assertNotEqual(
            preview["signature"],
            build_selected_routes_attribute_group_swap_signature(
                project,
                ["route_a", "route_c"],
                from_group_key="black_outfit",
                to_group_key="green_outfit",
                require_full_match=True,
                project_path="project.json",
            ),
        )
        self.assertNotEqual(
            preview["signature"],
            build_selected_routes_attribute_group_swap_signature(
                project,
                ["route_a", "route_c"],
                from_group_key="black_outfit",
                to_group_key="green_outfit",
                project_path="other.json",
            ),
        )

    def test_stale_and_injected_failure_leave_source_unchanged(self):
        project = _project()
        preview = self._preview(project)
        project.prompt_lines[1].image_path = "changed.png"
        stale_before = copy.deepcopy(project)

        stale = self._apply(project, preview)

        self.assertTrue(stale["stale_preview"])
        self.assertEqual(stale_before, project)

        project = _project()
        before = copy.deepcopy(project)
        preview = self._preview(project)

        def fail_after_apply(_working_project, _working_plan):
            raise RuntimeError("injected second Route failure")

        failed = self._apply(project, preview, mutation_hook=fail_after_apply)
        self.assertFalse(failed["applied"])
        self.assertIn("injected", failed["error"])
        self.assertEqual(before, project)

    def test_no_op_and_slot_mismatch_do_not_apply(self):
        project = _project()
        no_op = build_selected_routes_attribute_group_swap_plan(
            project,
            ["route_a"],
            from_group_key="black_outfit",
            to_group_key="same_outfit",
        )
        no_op_result = apply_selected_routes_attribute_group_swap(
            project,
            ["route_a"],
            expected_signature=no_op["signature"],
            from_group_key="black_outfit",
            to_group_key="same_outfit",
        )
        mismatch = build_selected_routes_attribute_group_swap_plan(
            project,
            ["route_a"],
            from_group_key="black_outfit",
            to_group_key="expression",
        )
        mismatch_result = apply_selected_routes_attribute_group_swap(
            project,
            ["route_a"],
            expected_signature=mismatch["signature"],
            from_group_key="black_outfit",
            to_group_key="expression",
        )

        self.assertFalse(no_op_result["applied"])
        self.assertFalse(mismatch_result["applied"])
        self.assertIsNone(no_op_result["updated_project"])
        self.assertIsNone(mismatch_result["updated_project"])


if __name__ == "__main__":
    unittest.main()
