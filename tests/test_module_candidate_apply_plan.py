import json
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import patch

from core.module_candidate_apply import (
    apply_reviewed_module_candidates,
    build_module_candidate_apply_plan,
    preview_project_module_candidates,
)
from core.project import Project, PromptLine


def _line(number, text="red hair, outdoors"):
    return PromptLine(
        id=f"line-{number}", original_file_name="source.txt",
        original_index=number, current_index=number,
        original_text=text, current_text=text,
        tokens=[token.strip() for token in text.split(",")],
    )


def _project(count=1):
    return Project(
        prompt_lines=[_line(number) for number in range(count)],
        module_library={
            "Module A": {
                "body": "red hair, blue eyes",
                "core_tokens": ["red hair"],
                "min_match_tokens": 1,
            }
        },
    )


def _plan(project, *, example_limit=50):
    return build_module_candidate_apply_plan(
        project, "Module A", core_tokens=["red hair"],
        min_match_tokens=1, example_limit=example_limit,
    )


def _apply(project, plan):
    return apply_reviewed_module_candidates(
        project, plan, module_name="Module A",
        core_tokens=["red hair"], min_match_tokens=1,
    )


class _Opaque:
    def __deepcopy__(self, memo):
        raise AssertionError("opaque Module extension was copied")

    def __iter__(self):
        raise AssertionError("opaque Module extension was inspected")


class ModuleCandidateApplyPlanTests(unittest.TestCase):
    def test_complete_frozen_plan_applies_exact_reviewed_text_to_isolated_result(self):
        project = _project(3)
        plan, preview = _plan(project, example_limit=1)
        self.assertEqual(preview["affected_line_count"], 3)
        self.assertEqual(len(preview["examples"]), 1)
        self.assertEqual(len(plan.replacements), 3)
        json.loads(plan.prompt_state_json)
        with self.assertRaises(FrozenInstanceError):
            plan.module_name = "changed"

        result = _apply(project, plan)
        self.assertTrue(result.applied)
        self.assertFalse(result.stale)
        self.assertIsNot(result.project, project)
        self.assertIs(result.project.module_library, project.module_library)
        self.assertEqual([line.current_text for line in project.prompt_lines],
                         ["red hair, outdoors"] * 3)
        self.assertEqual([line.current_text for line in result.project.prompt_lines],
                         ["<mod:Module A>, outdoors"] * 3)
        self.assertTrue(all(line.edited for line in result.project.prompt_lines))

    def test_line_and_module_drift_all_fail_without_mutating_project(self):
        changes = {
            "current_text": lambda p: setattr(p.prompt_lines[0], "current_text", "red hair, indoors"),
            "active_tokens": lambda p: setattr(p.prompt_lines[0], "tokens", ["other"]),
            "new_line": lambda p: p.prompt_lines.append(_line(4)),
            "removed_line": lambda p: p.prompt_lines.pop(),
            "reordered_lines": lambda p: p.prompt_lines.reverse(),
            "deleted_state": lambda p: setattr(p.prompt_lines[0], "deleted", True),
            "target_id": lambda p: setattr(p.prompt_lines[0], "id", "different-id"),
            "display_file": lambda p: setattr(p.prompt_lines[0], "original_file_name", "different.txt"),
            "display_index": lambda p: setattr(p.prompt_lines[0], "original_index", 8),
            "module_body": lambda p: p.module_library["Module A"].__setitem__("body", "red hair, smile"),
        }
        for label, change in changes.items():
            with self.subTest(label=label):
                project = _project(2)
                plan, _ = _plan(project)
                change(project)
                prior_project = project
                prior_lines = tuple(project.prompt_lines)
                prior_text = tuple(line.current_text for line in project.prompt_lines)
                result = _apply(project, plan)
                self.assertTrue(result.stale)
                self.assertFalse(result.applied)
                self.assertIs(result.project, prior_project)
                self.assertEqual(tuple(project.prompt_lines), prior_lines)
                self.assertEqual(tuple(line.current_text for line in project.prompt_lines), prior_text)

    def test_non_effective_controls_and_line_metadata_remain_fresh(self):
        changes = {
            "saved_core": lambda p: p.module_library["Module A"].__setitem__("core_tokens", ["blue eyes"]),
            "saved_minimum": lambda p: p.module_library["Module A"].__setitem__("min_match_tokens", 2),
            "line_type": lambda p: setattr(p.prompt_lines[0], "line_type", "separator"),
            "current_index": lambda p: setattr(p.prompt_lines[0], "current_index", 8),
        }
        for label, change in changes.items():
            with self.subTest(label=label):
                project = _project()
                plan, _ = _plan(project)
                change(project)
                result = _apply(project, plan)
                self.assertFalse(result.stale)
                self.assertTrue(result.applied)
                self.assertEqual(result.project.prompt_lines[0].current_text,
                                 "<mod:Module A>, outdoors")

    def test_effective_rule_and_reference_drift_stales(self):
        project = _project()
        plan, _ = _plan(project)
        for kwargs in (
            {"core_tokens": ["blue eyes"], "min_match_tokens": 1},
            {"core_tokens": ["red hair"], "min_match_tokens": 2},
            {"core_tokens": ["red hair"], "min_match_tokens": 1,
             "module_name": "Other Module"},
        ):
            with self.subTest(kwargs=kwargs):
                result = apply_reviewed_module_candidates(
                    project, plan,
                    **{
                        **{"module_name": "Module A", "core_tokens": ["red hair"],
                           "min_match_tokens": 1},
                        **kwargs,
                    },
                )
                self.assertTrue(result.stale)
                self.assertFalse(result.applied)
                self.assertIs(result.project, project)

    def test_transition_to_no_op_is_stale_and_reviewed_no_op_cannot_apply(self):
        project = _project()
        plan, _ = _plan(project)
        project.prompt_lines[0].current_text = "other"
        project.prompt_lines[0].tokens = ["other"]
        result = _apply(project, plan)
        self.assertTrue(result.stale)
        self.assertFalse(result.applied)

        new_plan, preview = _plan(project)
        self.assertEqual(preview["affected_line_count"], 0)
        result = _apply(project, new_plan)
        self.assertFalse(result.stale)
        self.assertFalse(result.applied)
        self.assertIs(result.project, project)

    def test_opaque_reference_change_is_fresh_and_preserves_current_exact_value(self):
        project = _project()
        first = _Opaque()
        current = _Opaque()
        project.module_library["Module A"]["reference_assets"] = first
        from core.operations import normalize_module_library
        with patch("core.operations.module_entry_for_prompt_only_container",
                   side_effect=AssertionError("container projection called")), patch(
            "core.module_candidate_apply.normalize_module_library", wraps=normalize_module_library
        ) as normalized:
            plan, _ = _plan(project)
            project.module_library["Module A"]["reference_assets"] = current
            result = _apply(project, plan)
        self.assertTrue(all(
            "reference_assets" not in entry
            for call in normalized.call_args_list
            for entry in call.args[0].values()
            if isinstance(entry, dict)
        ))
        self.assertTrue(result.applied)
        self.assertIs(result.project.module_library["Module A"]["reference_assets"], current)
        self.assertIs(project.module_library["Module A"]["reference_assets"], current)

    def test_unknown_metadata_is_excluded_and_preserved(self):
        project = _project()
        metadata = _Opaque()
        project.module_library["Module A"]["future_extension"] = metadata
        plan, _ = _plan(project)
        project.module_library["Module A"]["future_extension"] = {"updated": 1}
        result = _apply(project, plan)
        self.assertTrue(result.applied)
        self.assertEqual(result.project.module_library["Module A"]["future_extension"], {"updated": 1})

    def test_preview_projection_does_not_touch_opaque(self):
        project = _project()
        project.module_library["Module A"]["reference_assets"] = _Opaque()
        with patch("core.module_candidate_apply.normalize_module_library") as normalized:
            from core.operations import normalize_module_library
            normalized.side_effect = normalize_module_library
            preview = preview_project_module_candidates(
                project, "Module A", core_tokens=["red hair"], min_match_tokens=1
            )
            self.assertEqual(preview["total_candidate_count"], 1)
            self.assertTrue(all(
                "reference_assets" not in entry
                for call in normalized.call_args_list
                for entry in call.args[0].values()
                if isinstance(entry, dict)
            ))

    def test_graph_policy_and_metadata_do_not_stale_but_effective_token_drift_does(self):
        project = _project()
        plan, _ = _plan(project)
        from core.operations import normalize_module_library
        graph = normalize_module_library({"Module A": project.module_library["Module A"]})["Module A"]["graph"]
        project.module_library["Module A"]["graph"] = graph
        project.module_library["Module A"]["graph"]["replacement_policy"]["mode"] = "changed"
        project.module_library["Module A"]["graph"]["metadata"]["future"] = "unrelated"
        self.assertTrue(_apply(project, plan).applied)
        project.module_library["Module A"]["graph"]["nodes"][0]["text"] = "green hair"
        self.assertTrue(_apply(project, plan).stale)


if __name__ == "__main__":
    unittest.main()
