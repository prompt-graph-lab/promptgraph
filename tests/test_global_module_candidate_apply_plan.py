"""Global candidate Apply binds reviewed prompt edits and import decisions."""

import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import patch

from core.global_module_candidate_apply import (
    apply_reviewed_global_module_candidates,
    build_global_module_candidate_apply_plan,
    global_module_candidate_apply_plan_is_current,
)
from core.operations import get_active_tokens, get_module_body
from core.project import Project, PromptLine


def _project(text="red hair, blue eyes, outdoors", count=1, modules=None):
    return Project(
        prompt_lines=[
            PromptLine(
                id=f"line-{number}", original_file_name="source.txt",
                original_index=number, current_index=number,
                original_text=text, current_text=text,
                tokens=[token.strip() for token in text.split(",")],
            )
            for number in range(count)
        ],
        module_library=modules if modules is not None else {},
    )


def _global(body="red hair, blue eyes", **fields):
    return {"X": {"body": body, "core_tokens": ["red hair"], **fields}}


def _plan(project, global_library, *, example_limit=50):
    return build_global_module_candidate_apply_plan(
        project, global_library, ["X"],
        min_core_match_lines=1, example_limit=example_limit,
    )


class OpaqueReferences:
    def __iter__(self):
        raise AssertionError("reference_assets was inspected")

    def __deepcopy__(self, memo):
        raise AssertionError("reference_assets was copied")


class GlobalModuleCandidateApplyPlanTests(unittest.TestCase):
    def test_multiple_selected_modules_keep_every_reviewed_line(self):
        project = _project("red hair, blue eyes, outdoors", count=2)
        project.prompt_lines[1].current_text = "smile, outdoors"
        project.prompt_lines[1].tokens = ["smile", "outdoors"]
        library = {
            "X": {"body": "red hair, blue eyes", "core_tokens": ["red hair"]},
            "Y": {"body": "smile", "core_tokens": ["smile"]},
        }
        plan, preview = build_global_module_candidate_apply_plan(
            project, library, ["X", "Y"], example_limit=1,
        )
        self.assertEqual(2, preview["affected_line_count"])
        self.assertEqual(1, len(preview["examples"]))
        self.assertEqual(
            ("red hair, blue eyes, outdoors", "<mod:X>, outdoors"),
            (plan.replacements[0][2], plan.replacements[0][3]),
        )
        self.assertEqual(
            ("smile, outdoors", "<mod:Y>, outdoors"),
            (plan.replacements[1][2], plan.replacements[1][3]),
        )
        result = apply_reviewed_global_module_candidates(project, library, plan)
        self.assertTrue(result.applied)
        self.assertEqual(["<mod:X>, outdoors", "<mod:Y>, outdoors"],
                         [line.current_text for line in result.project.prompt_lines])
        self.assertEqual({"X", "Y"}, set(result.project.module_library))

    def test_complete_immutable_plan_applies_all_rows_and_frozen_import(self):
        project = _project(count=3)
        global_library = _global(description="reviewed metadata")
        plan, preview = _plan(project, global_library, example_limit=1)
        self.assertEqual(3, preview["affected_line_count"])
        self.assertEqual(1, len(preview["examples"]))
        self.assertEqual(3, len(plan.replacements))
        self.assertEqual(1, len(plan.imports))
        with self.assertRaises(FrozenInstanceError):
            plan.module_names = ("changed",)

        global_library["X"]["description"] = "later metadata"
        self.assertTrue(global_module_candidate_apply_plan_is_current(project, global_library, plan))
        result = apply_reviewed_global_module_candidates(project, global_library, plan)
        self.assertTrue(result.applied)
        self.assertFalse(result.stale)
        self.assertIsNot(project, result.project)
        self.assertEqual(["red hair, blue eyes, outdoors"] * 3,
                         [line.current_text for line in project.prompt_lines])
        self.assertEqual(["<mod:X>, outdoors"] * 3,
                         [line.current_text for line in result.project.prompt_lines])
        self.assertEqual("reviewed metadata", result.project.module_library["X"]["description"])
        self.assertNotIn("X", project.module_library)

    def test_global_definition_drift_rejects_different_replacement_or_noop(self):
        project = _project("red hair, blue eyes, green eyes, outdoors")
        global_library = _global()
        plan, preview = _plan(project, global_library)
        self.assertEqual("<mod:X>, green eyes, outdoors", preview["examples"][0]["after"])
        for body, core in (("red hair, green eyes", "red hair"),
                           ("yellow hat", "yellow hat")):
            changed_global = _global(body, core_tokens=[core])
            result = apply_reviewed_global_module_candidates(project, changed_global, plan)
            self.assertFalse(result.applied)
            self.assertTrue(result.stale)
            self.assertIs(project, result.project)
            self.assertEqual("red hair, blue eyes, green eyes, outdoors",
                             project.prompt_lines[0].current_text)
            self.assertEqual({}, project.module_library)

    def test_import_decision_drift_rejected_in_both_directions(self):
        global_library = _global()
        absent = _project()
        absent_plan, absent_preview = _plan(absent, global_library)
        self.assertEqual(["X"], absent_preview["import_needed"])
        absent.module_library["X"] = {"body": "new local definition"}
        result = apply_reviewed_global_module_candidates(absent, global_library, absent_plan)
        self.assertTrue(result.stale)
        self.assertIs(absent, result.project)
        self.assertEqual("new local definition", absent.module_library["X"]["body"])

        present = _project(modules={"X": {"body": "old local definition"}})
        present_plan, present_preview = _plan(present, global_library)
        self.assertEqual([], present_preview["import_needed"])
        del present.module_library["X"]
        result = apply_reviewed_global_module_candidates(present, global_library, present_plan)
        self.assertTrue(result.stale)
        self.assertIs(present, result.project)
        self.assertNotIn("X", present.module_library)

    def test_prompt_tokens_drift_without_text_change_is_stale(self):
        project = _project()
        plan, _ = _plan(project, _global())
        before_text = project.prompt_lines[0].current_text
        project.prompt_lines[0].tokens = ["yellow hat", "outdoors"]
        self.assertEqual(before_text, project.prompt_lines[0].current_text)
        result = apply_reviewed_global_module_candidates(project, _global(), plan)
        self.assertFalse(result.applied)
        self.assertTrue(result.stale)
        self.assertIs(project, result.project)

    def test_existing_project_definition_supplies_reference_meaning_and_is_bound(self):
        original_refs = OpaqueReferences()
        project = _project(modules={
            "X": {"body": "green eyes, smile", "reference_assets": original_refs},
        })
        global_library = _global()
        plan, preview = _plan(project, global_library)
        self.assertEqual([], preview["import_needed"])

        changed_refs = OpaqueReferences()
        project.module_library["X"]["reference_assets"] = changed_refs
        self.assertTrue(global_module_candidate_apply_plan_is_current(project, global_library, plan))
        result = apply_reviewed_global_module_candidates(project, global_library, plan)
        self.assertTrue(result.applied)
        self.assertEqual("<mod:X>, outdoors", result.project.prompt_lines[0].current_text)
        self.assertEqual(["green eyes", "smile", "outdoors"],
                         get_active_tokens(result.project.prompt_lines[0],
                                           module_library=result.project.module_library))
        self.assertEqual("green eyes, smile", get_module_body(result.project, "X"))
        self.assertIs(changed_refs, result.project.module_library["X"]["reference_assets"])
        self.assertIs(changed_refs, project.module_library["X"]["reference_assets"])

        drifting = _project(modules={"X": {"body": "green eyes, smile"}})
        drifting_plan, _ = _plan(drifting, global_library)
        drifting.module_library["X"]["body"] = "purple eyes, smile"
        self.assertTrue(apply_reviewed_global_module_candidates(
            drifting, global_library, drifting_plan).stale)

    def test_unknown_project_metadata_does_not_stale_and_live_extension_survives(self):
        project = _project(modules={
            "X": {"body": "green eyes, smile", "extension": {"value": "old"}},
            "unrelated": {"body": "unrelated", "reference_assets": OpaqueReferences()},
        })
        plan, _ = _plan(project, _global())
        new_extension = {"value": "new"}
        project.module_library["X"]["extension"] = new_extension
        result = apply_reviewed_global_module_candidates(project, _global(), plan)
        self.assertTrue(result.applied)
        self.assertIs(new_extension, result.project.module_library["X"]["extension"])
        self.assertIs(project.module_library["unrelated"],
                      result.project.module_library["unrelated"])

    def test_stale_global_reference_assets_is_never_copied_into_import(self):
        project = _project()
        refs = OpaqueReferences()
        global_library = _global(reference_assets=refs)
        plan, _ = _plan(project, global_library)
        result = apply_reviewed_global_module_candidates(project, global_library, plan)
        self.assertTrue(result.applied)
        self.assertNotIn("reference_assets", result.project.module_library["X"])
        self.assertIs(refs, global_library["X"]["reference_assets"])

    def test_noop_and_prepublication_failure_leave_project_unchanged(self):
        project = _project("yellow hat")
        plan, preview = _plan(project, _global())
        self.assertEqual(0, preview["affected_line_count"])
        result = apply_reviewed_global_module_candidates(project, _global(), plan)
        self.assertFalse(result.applied)
        self.assertFalse(result.stale)
        self.assertIs(project, result.project)

        project = _project()
        plan, _ = _plan(project, _global())
        with patch("core.global_module_candidate_apply.build_graph",
                   side_effect=RuntimeError("graph failed")):
            with self.assertRaisesRegex(RuntimeError, "graph failed"):
                apply_reviewed_global_module_candidates(project, _global(), plan)
        self.assertEqual("red hair, blue eyes, outdoors", project.prompt_lines[0].current_text)
        self.assertNotIn("X", project.module_library)


if __name__ == "__main__":
    unittest.main()
