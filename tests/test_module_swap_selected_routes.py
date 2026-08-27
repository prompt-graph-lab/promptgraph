import copy
import unittest

from core.module_swap_selected_routes import (
    apply_selected_routes_module_swap,
    build_selected_routes_module_swap_plan,
    build_selected_routes_module_swap_signature,
)
from core.operations import apply_module_swap, preview_module_swap, resolve_module_swap_target_line_ids
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
        module_library={
            "Source": {
                "body": "source hair, source eyes",
                "type": "character",
                "category": "Character",
                "core_tokens": ["source hair"],
                "custom_metadata": {"version": 1},
            },
            "Target": {
                "body": "target hair, target eyes",
                "type": "character",
                "category": "Character",
                "core_tokens": ["target hair"],
                "custom_metadata": {"version": 1},
            },
        },
        prompt_lines=[
            _separator("route_a", "Route A", current_index=100),
            _line("a1", "quality, source hair, source eyes, smile", current_index=90, image_path="a1.png"),
            _line("a2", "source hair, source eyes, beach", current_index=80),
            _line("a_workbench", "source hair, source eyes", line_type="workbench", current_index=70),
            _line("a_deleted", "source hair, source eyes", deleted=True, current_index=60),
            _separator("route_b", "Route B", current_index=50),
            _line("b1", "source hair, source eyes, city", current_index=40),
            _separator("route_c", "Route C", current_index=30),
            _line(
                "c1",
                "source hair, source eyes, night",
                current_index=20,
                selected_candidate_path="c1-selected.png",
            ),
            _line("c2", "unrelated, forest", current_index=10),
        ],
    )


class SelectedRoutesModuleSwapPlanTests(unittest.TestCase):
    def test_project_order_wins_over_click_order_and_stale_current_index(self):
        plan = build_selected_routes_module_swap_plan(
            _project(),
            ["route_c", "route_a"],
            source_module_name="Source",
            target_module_name="Target",
        )

        self.assertTrue(plan["valid"])
        self.assertEqual(["route_a", "route_c"], plan["selected_route_ids"])
        self.assertEqual(["a1", "a2", "c1", "c2"], plan["target_line_ids"])
        self.assertEqual([1, 2, 8, 9], [entry["project_order"] for entry in plan["entries"]])
        self.assertNotIn("b1", plan["target_line_ids"])
        self.assertEqual(3, plan["changed_line_count"])
        self.assertEqual(1, plan["no_op_count"])

    def test_target_exclusions_and_one_route_existing_semantics_equivalence(self):
        project = _project()
        plan = build_selected_routes_module_swap_plan(
            project,
            ["route_a"],
            source_module_name="Source",
            target_module_name="Target",
        )
        existing = preview_module_swap(
            copy.deepcopy(project),
            "Source",
            "Target",
            target_line_ids=["a1", "a2"],
            example_limit=100,
        )

        self.assertEqual(["a1", "a2"], plan["target_line_ids"])
        self.assertEqual(
            [example["after"] for example in existing["examples"]],
            [entry["after_positive_prompt"] for entry in plan["entries"] if not entry["no_op"]],
        )
        self.assertNotIn("a_workbench", plan["target_line_ids"])
        self.assertNotIn("a_deleted", plan["target_line_ids"])

    def test_module_reference_swap_reuses_existing_marker_semantics(self):
        project = _project()
        project.prompt_lines[1].current_text = "<mod:Source>, smile"
        project.prompt_lines[1].tokens = ["<mod:Source>", "smile"]
        plan = build_selected_routes_module_swap_plan(
            project,
            ["route_a"],
            source_module_name="Source",
            target_module_name="Target",
        )
        entry = next(item for item in plan["entries"] if item["line_id"] == "a1")
        self.assertEqual("reference", entry["swap_kind"])
        self.assertEqual("<mod:Target>, smile", entry["after_positive_prompt"])
        self.assertEqual(["<mod:Target>", "smile"], entry["after_tokens"])

    def test_positive_negative_diff_and_drift_are_explicit(self):
        plan = build_selected_routes_module_swap_plan(
            _project(),
            ["route_a", "route_c"],
            source_module_name="Source",
            target_module_name="Target",
        )
        by_id = {entry["line_id"]: entry for entry in plan["entries"]}

        self.assertEqual(["source hair", "source eyes"], by_id["a1"]["positive_removed_tokens"])
        self.assertEqual(["target hair", "target eyes"], by_id["a1"]["positive_added_tokens"])
        self.assertEqual("keep negative", by_id["a1"]["before_negative_prompt"])
        self.assertEqual("keep negative", by_id["a1"]["after_negative_prompt"])
        self.assertFalse(by_id["a1"]["negative_changed"])
        self.assertEqual("prompt changed while main image remains unchanged", by_id["a1"]["drift_risk"])
        self.assertEqual("selected_candidate_path", by_id["c1"]["main_image_field"])
        self.assertEqual("prompt changed, no representative image", by_id["a2"]["drift_risk"])
        self.assertEqual("no prompt change", by_id["c2"]["drift_risk"])

    def test_preview_is_source_immutable(self):
        project = _project()
        before = copy.deepcopy(project)

        build_selected_routes_module_swap_plan(
            project,
            ["route_a", "route_c"],
            source_module_name="Source",
            target_module_name="Target",
        )

        self.assertEqual(before, project)

    def test_empty_invalid_and_duplicate_selections_fail_closed(self):
        project = _project()
        empty = build_selected_routes_module_swap_plan(
            project,
            [],
            source_module_name="Source",
            target_module_name="Target",
        )
        invalid = build_selected_routes_module_swap_plan(
            project,
            ["missing", "a1", "route_b"],
            source_module_name="Source",
            target_module_name="Target",
        )
        project.prompt_lines.insert(3, _line("a1", "source hair, source eyes"))
        duplicate = build_selected_routes_module_swap_plan(
            project,
            ["route_a"],
            source_module_name="Source",
            target_module_name="Target",
        )

        self.assertFalse(empty["valid"])
        self.assertEqual("no selected Routes", empty["reason"])
        self.assertTrue(invalid["valid"])
        self.assertEqual(["route_b"], invalid["selected_route_ids"])
        self.assertTrue(any("missing Route id" in item for item in invalid["diagnostics"]))
        self.assertTrue(any("non-separator" in item for item in invalid["diagnostics"]))
        self.assertFalse(duplicate["valid"])
        self.assertIn("ambiguous duplicate Line", duplicate["reason"])

        project = _project()
        project.prompt_lines.insert(2, _line("", "source hair, source eyes"))
        malformed_line = build_selected_routes_module_swap_plan(
            project,
            ["route_a"],
            source_module_name="Source",
            target_module_name="Target",
        )
        self.assertTrue(malformed_line["valid"])
        self.assertNotIn("", malformed_line["target_line_ids"])
        self.assertEqual(1, malformed_line["blocked_count"])
        self.assertTrue(any("missing ids" in item for item in malformed_line["diagnostics"]))

    def test_malformed_inputs_return_diagnostics_without_mutation(self):
        cases = [
            None,
            Project(prompt_lines=None),
            Project(prompt_lines=123),
            Project(prompt_lines=[], module_library=object()),
        ]
        for project in cases:
            with self.subTest(project=project):
                plan = build_selected_routes_module_swap_plan(
                    project,
                    "route_a",
                    source_module_name="Source",
                    target_module_name="Target",
                )
                self.assertFalse(plan["valid"])
                self.assertTrue(plan["reason"])

        project = _project()
        project.prompt_lines[1].tokens = object()
        project.module_library["Source"]["body"] = None
        plan = build_selected_routes_module_swap_plan(
            project,
            ["route_a"],
            source_module_name="Source",
            target_module_name="Target",
            match_mode="invalid",
        )
        self.assertFalse(plan["valid"])
        self.assertTrue(any("malformed" in item for item in plan["diagnostics"]))

    def test_existing_module_swap_scopes_remain_available(self):
        project = _project()
        all_scope = resolve_module_swap_target_line_ids(project, "all")
        route_scope = resolve_module_swap_target_line_ids(project, "route", selected_routes=["route_a"])
        self.assertIsNone(all_scope["target_line_ids"])
        self.assertEqual(["a1", "a2"], route_scope["target_line_ids"])


class SelectedRoutesModuleSwapApplyTests(unittest.TestCase):
    def _preview(self, project, selected=("route_a", "route_c"), **kwargs):
        return build_selected_routes_module_swap_plan(
            project,
            list(selected),
            source_module_name="Source",
            target_module_name="Target",
            project_path="project.json",
            disabled_modules={"Disabled"},
            **kwargs,
        )

    def test_apply_returns_atomic_clone_and_preserves_non_prompt_state(self):
        project = _project()
        source_before = copy.deepcopy(project)
        plan = self._preview(project)
        apply_calls = []

        def counted_apply(*args, **kwargs):
            apply_calls.append(1)
            return apply_module_swap(*args, **kwargs)

        result = apply_selected_routes_module_swap(
            project,
            ["route_c", "route_a"],
            expected_signature=plan["signature"],
            source_module_name="Source",
            target_module_name="Target",
            project_path="project.json",
            disabled_modules={"Disabled"},
            apply_func=counted_apply,
        )

        self.assertTrue(result["applied"])
        self.assertEqual(3, result["applied_count"])
        self.assertEqual(1, len(apply_calls))
        self.assertEqual(source_before, project)
        updated = result["updated_project"]
        updated_by_id = {line.id: line for line in updated.prompt_lines}
        source_by_id = {line.id: line for line in source_before.prompt_lines}
        self.assertEqual("quality, target hair, target eyes, smile", updated_by_id["a1"].current_text)
        self.assertEqual(
            ["quality", "target hair", "target eyes", "smile"],
            updated_by_id["a1"].tokens,
        )
        self.assertEqual("source hair, source eyes, city", updated_by_id["b1"].current_text)
        self.assertEqual("unrelated, forest", updated_by_id["c2"].current_text)
        self.assertTrue(updated_by_id["a1"].edited)
        for line_id in ("a1", "a2", "b1", "c1", "c2"):
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
        self.assertEqual(source_before.module_library, updated.module_library)
        self.assertEqual(
            [line.id for line in source_before.prompt_lines],
            [line.id for line in updated.prompt_lines],
        )

    def test_no_op_plan_does_not_apply(self):
        project = _project()
        for line in project.prompt_lines:
            if line.line_type not in {"separator", "workbench"}:
                line.current_text = "unrelated"
                line.tokens = ["unrelated"]
        plan = self._preview(project, selected=("route_a",))
        result = apply_selected_routes_module_swap(
            project,
            ["route_a"],
            expected_signature=plan["signature"],
            source_module_name="Source",
            target_module_name="Target",
            project_path="project.json",
            disabled_modules={"Disabled"},
        )
        self.assertEqual(0, plan["changed_line_count"])
        self.assertFalse(result["applied"])
        self.assertIsNone(result["updated_project"])

    def test_full_prompt_tokens_route_order_library_options_and_project_path_make_preview_stale(self):
        mutations = {
            "prompt_tail": lambda project: setattr(
                project.prompt_lines[1], "current_text", ("p" * 300) + "changed"
            ),
            "negative_tail": lambda project: setattr(
                project.prompt_lines[1], "negative_prompt", ("n" * 300) + "changed"
            ),
            "tokens": lambda project: setattr(project.prompt_lines[1], "tokens", ["changed token"]),
            "route_move": lambda project: project.prompt_lines.__setitem__(
                slice(None), project.prompt_lines[5:8] + project.prompt_lines[0:5] + project.prompt_lines[8:]
            ),
            "module_body": lambda project: project.module_library["Target"].__setitem__("body", "new target"),
            "module_metadata": lambda project: project.module_library["Target"].__setitem__(
                "custom_metadata", {"version": 2}
            ),
        }
        for name, mutate in mutations.items():
            project = _project()
            before = self._preview(project)
            mutate(project)
            current = build_selected_routes_module_swap_signature(
                project,
                ["route_a", "route_c"],
                source_module_name="Source",
                target_module_name="Target",
                project_path="project.json",
                disabled_modules={"Disabled"},
            )
            with self.subTest(name=name):
                self.assertNotEqual(before["signature"], current)

        project = _project()
        before = self._preview(project)
        self.assertNotEqual(
            before["signature"],
            build_selected_routes_module_swap_signature(
                project,
                ["route_a", "route_c"],
                source_module_name="Source",
                target_module_name="Target",
                project_path="other.json",
                disabled_modules={"Disabled"},
            ),
        )
        self.assertNotEqual(
            before["signature"],
            build_selected_routes_module_swap_signature(
                project,
                ["route_a", "route_c"],
                source_module_name="Source",
                target_module_name="Target",
                project_path="project.json",
                disabled_modules={"Different"},
            ),
        )

    def test_main_image_reference_changes_make_preview_stale(self):
        mutations = {
            "image_less_to_selected_candidate": lambda project: setattr(
                project.prompt_lines[2], "selected_candidate_path", "a2-selected.png"
            ),
            "selected_candidate_changed": lambda project: setattr(
                project.prompt_lines[8], "selected_candidate_path", "c1-other-selected.png"
            ),
            "generated_image_changed": lambda project: setattr(
                project.prompt_lines[2], "generated_image_path", "a2-generated.png"
            ),
            "image_path_changed": lambda project: setattr(
                project.prompt_lines[1], "image_path", "a1-other.png"
            ),
        }
        for name, mutate in mutations.items():
            project = _project()
            preview = self._preview(project)
            mutate(project)
            result = apply_selected_routes_module_swap(
                project,
                ["route_a", "route_c"],
                expected_signature=preview["signature"],
                source_module_name="Source",
                target_module_name="Target",
                project_path="project.json",
                disabled_modules={"Disabled"},
            )
            with self.subTest(name=name):
                self.assertTrue(result["stale_preview"])
                self.assertFalse(result["applied"])

    def test_unchanged_main_image_references_allow_apply(self):
        project = _project()
        preview = self._preview(project)

        result = apply_selected_routes_module_swap(
            project,
            ["route_a", "route_c"],
            expected_signature=preview["signature"],
            source_module_name="Source",
            target_module_name="Target",
            project_path="project.json",
            disabled_modules={"Disabled"},
        )

        self.assertTrue(result["applied"])
        self.assertFalse(result["stale_preview"])

    def test_stale_apply_and_injected_failure_leave_source_unchanged(self):
        project = _project()
        before = copy.deepcopy(project)
        plan = self._preview(project)
        project.prompt_lines[1].current_text += ", changed after preview"
        stale_source = copy.deepcopy(project)
        stale = apply_selected_routes_module_swap(
            project,
            ["route_a", "route_c"],
            expected_signature=plan["signature"],
            source_module_name="Source",
            target_module_name="Target",
            project_path="project.json",
            disabled_modules={"Disabled"},
        )
        self.assertTrue(stale["stale_preview"])
        self.assertEqual(stale_source, project)

        project = before
        plan = self._preview(project)

        def fail_after_clone(_working_project, _working_plan):
            raise RuntimeError("injected second Route failure")

        failed = apply_selected_routes_module_swap(
            project,
            ["route_a", "route_c"],
            expected_signature=plan["signature"],
            source_module_name="Source",
            target_module_name="Target",
            project_path="project.json",
            disabled_modules={"Disabled"},
            mutation_hook=fail_after_clone,
        )
        self.assertFalse(failed["applied"])
        self.assertIn("injected", failed["error"])
        self.assertEqual(before, project)

    def test_invalid_apply_tokens_are_rejected_without_source_mutation(self):
        project = _project()
        before = copy.deepcopy(project)
        plan = self._preview(project)

        def corrupt_tokens(*args, **kwargs):
            updated = apply_module_swap(*args, **kwargs)
            updated.prompt_lines[1].tokens = ["wrong"]
            return updated

        result = apply_selected_routes_module_swap(
            project,
            ["route_a", "route_c"],
            expected_signature=plan["signature"],
            source_module_name="Source",
            target_module_name="Target",
            project_path="project.json",
            disabled_modules={"Disabled"},
            apply_func=corrupt_tokens,
        )
        self.assertFalse(result["applied"])
        self.assertIn("tokens changed", result["error"])
        self.assertEqual(before, project)


if __name__ == "__main__":
    unittest.main()
