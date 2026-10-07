import copy
import json
import unittest

from core.project import Project, PromptLine
from core.scene_portability import (
    SCENE_PORTABILITY_CONTRACT_VERSION,
    project_scene_portability_payload,
)


class _OpaqueAssets:
    def __deepcopy__(self, memo):
        return self


def _line(line_id, text="", *, line_type=None, deleted=False, **fields):
    values = {
        "id": line_id,
        "original_file_name": line_id,
        "original_index": 0,
        "current_index": 0,
        "original_text": text,
        "current_text": text,
        "tokens": [text] if text else [],
        "line_type": line_type,
        "deleted": deleted,
    }
    values.update(fields)
    return PromptLine(**values)


def _source_project():
    return Project(
        prompt_lines=[
            _line("before", "outside selected Scene"),
            _line(
                "scene-source",
                "Scene label text",
                line_type="separator",
                separator_label="Portable Scene",
                separator_color="violet",
            ),
            _line(
                "illustration-a",
                "  <mod:parent>, exact positive  ",
                negative_prompt=" negative stays exact ",
                image_path=r"C:\\private\\image.png",
                generated_image_path="generated.png",
                selected_candidate_path="selected.png",
                generated_candidates=[{"path": "candidate.png"}],
                gallery_variants=[{"path": "variant.png"}],
                source_generation_info={"private": True},
                lineage_info={"private": True},
                edited=True,
            ),
            _line("deleted-illustration", "deleted", deleted=True),
            _line(
                "workbench-illustration",
                "workbench",
                line_type="workbench",
                workbench_source_line_id="illustration-a",
                workbench_title="internal title",
            ),
            _line("illustration-b", "second", negative_prompt="second negative"),
            _line("scene-after", "Another Scene", line_type="separator"),
            _line("after", "outside selected Scene"),
        ],
        module_library={
            "parent": {
                "body": "red hair, <mod:child>",
                "type": "generic",
                "category": "character",
                "core_tokens": ["red hair"],
                "thumbnail_path": r"C:\\machine\\thumb.png",
                "reference_assets": _OpaqueAssets(),
                "source_url": "https://example.invalid/modules/parent",
                "extra_local": {"nested": r"C:\\machine\\private.json"},
                "nested_metadata": {
                    "label": "portable note",
                    "old_note": r"C:\\machine\\note.txt",
                },
            },
            "child": {"body": "blue eyes", "type": "generic"},
            "unrelated": {"body": "not part of closure"},
        },
    )


class ScenePortabilityTests(unittest.TestCase):
    def test_projects_active_illustrations_in_physical_order_with_verbatim_prompts(self):
        project = _source_project()
        before = copy.deepcopy(project)

        result = project_scene_portability_payload(project, "scene-source")

        self.assertTrue(result["valid"])
        self.assertEqual(SCENE_PORTABILITY_CONTRACT_VERSION, result["contract_version"])
        self.assertEqual("scene-source", result["source_separator_id"])
        self.assertEqual(
            {"label": "Portable Scene", "color": "violet", "source_index": 1},
            result["scene"],
        )
        self.assertEqual(
            ["illustration-a", "illustration-b"],
            [record["source_line_id"] for record in result["illustrations"]],
        )
        self.assertEqual([2, 5], [record["source_index"] for record in result["illustrations"]])
        self.assertEqual([0, 1], [record["scene_order"] for record in result["illustrations"]])
        self.assertEqual("  <mod:parent>, exact positive  ", result["illustrations"][0]["positive_prompt"])
        self.assertEqual(" negative stays exact ", result["illustrations"][0]["negative_prompt"])
        self.assertEqual("second negative", result["illustrations"][1]["negative_prompt"])
        self.assertEqual(before, project)

    def test_deleted_workbench_images_and_generation_state_are_not_projected_or_fingerprinted(self):
        project = _source_project()
        baseline = project_scene_portability_payload(project, "scene-source")

        line = project.prompt_lines[2]
        line.image_path = "a different image"
        line.generated_image_path = "another generated image"
        line.selected_candidate_path = "another selected candidate"
        line.generated_candidates.append({"path": "new candidate", "source_prompt": "new state"})
        line.gallery_variants.append({"path": "new variant"})
        line.source_generation_info["new"] = "metadata"
        line.lineage_info["new"] = "lineage"
        changed = project_scene_portability_payload(project, "scene-source")

        self.assertEqual(baseline["illustrations"], changed["illustrations"])
        self.assertEqual(baseline["source_scene_fingerprint"], changed["source_scene_fingerprint"])
        self.assertEqual({"source_line_id", "source_index", "scene_order", "positive_prompt", "negative_prompt"},
                         set(changed["illustrations"][0]))
        serialized = json.dumps(changed, ensure_ascii=False)
        for excluded in ("deleted-illustration", "workbench-illustration", "image_path", "candidate.png", "variant.png"):
            self.assertNotIn(excluded, serialized)

    def test_explicit_empty_scene_is_valid(self):
        project = Project(prompt_lines=[
            _line("empty", "Empty", line_type="separator", separator_label="Empty"),
            _line("next", "Next", line_type="separator"),
        ])

        result = project_scene_portability_payload(project, "empty")

        self.assertTrue(result["valid"])
        self.assertEqual([], result["illustrations"])
        self.assertEqual([], result["module_snapshots"])
        self.assertIsNotNone(result["source_scene_fingerprint"])

    def test_rejects_missing_nonseparator_deleted_and_ambiguous_handles(self):
        cases = [
            (Project(), "missing", "separator_not_found"),
            (Project(prompt_lines=[_line("line", "ordinary")]), "line", "not_a_separator"),
            (Project(prompt_lines=[_line("gone", "Gone", line_type="separator", deleted=True)]), "gone", "separator_not_active"),
            (
                Project(prompt_lines=[
                    _line(
                        "scene",
                        "",
                        line_type="separator",
                        separator_label=None,
                        current_text="",
                        original_file_name=r"C:\\private\\source.txt",
                    )
                ]),
                "scene",
                "unsafe_scene_metadata",
            ),
            (Project(prompt_lines=[
                _line("duplicate", "A", line_type="separator"),
                _line("duplicate", "B", line_type="separator"),
            ]), "duplicate", "ambiguous_separator_id"),
        ]
        for project, separator_id, expected in cases:
            with self.subTest(expected=expected):
                result = project_scene_portability_payload(project, separator_id)
                self.assertFalse(result["valid"])
                self.assertEqual([expected], result["blockers"])

    def test_rejects_project_wide_duplicate_ids_for_projected_illustrations(self):
        duplicate_rows = [
            ("another_scene", _line("illustration-a", "duplicate in another Scene")),
            ("deleted", _line("illustration-a", "deleted duplicate", deleted=True)),
            ("workbench", _line("illustration-a", "Workbench duplicate", line_type="workbench")),
            ("separator", _line("illustration-a", "separator duplicate", line_type="separator")),
        ]
        for location, duplicate in duplicate_rows:
            with self.subTest(location=location):
                project = _source_project()
                project.prompt_lines.append(duplicate)

                result = project_scene_portability_payload(project, "scene-source")

                self.assertFalse(result["valid"])
                self.assertEqual(["ambiguous_illustration_id"], result["blockers"])

    def test_unrelated_duplicate_ids_do_not_block_scene_projection(self):
        project = _source_project()
        project.prompt_lines.extend([
            _line("unrelated-duplicate", "outside the selected Scene"),
            _line("unrelated-duplicate", "another outside row"),
        ])

        result = project_scene_portability_payload(project, "scene-source")

        self.assertTrue(result["valid"])
        self.assertEqual(
            ["illustration-a", "illustration-b"],
            [record["source_line_id"] for record in result["illustrations"]],
        )

    def test_discovers_transitive_positive_prompt_module_closure_and_filters_local_metadata(self):
        result = project_scene_portability_payload(_source_project(), "scene-source")

        self.assertTrue(result["valid"])
        self.assertEqual(["child", "parent"], [item["name"] for item in result["module_snapshots"]])
        parent = next(item["definition"] for item in result["module_snapshots"] if item["name"] == "parent")
        child = next(item["definition"] for item in result["module_snapshots"] if item["name"] == "child")
        self.assertEqual("red hair, <mod:child>", parent["body"])
        self.assertEqual("blue eyes", child["body"])
        self.assertNotIn("thumbnail_path", parent)
        self.assertNotIn("reference_assets", parent)
        self.assertNotIn("extra_local", parent)
        self.assertEqual("https://example.invalid/modules/parent", parent["source_url"])
        self.assertEqual({"label": "portable note"}, parent["nested_metadata"])
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("C:\\\\machine", serialized)
        self.assertNotIn("unrelated", serialized)

    def test_module_closure_depth_boundary_blocks_without_recursion_error(self):
        module_library = {
            f"module-{index}": {"body": f"<mod:module-{index + 1}>"}
            for index in range(1, 20)
        }
        module_library["module-20"] = {"body": "last module"}
        project = Project(
            prompt_lines=[
                _line("scene", "S", line_type="separator"),
                _line("line", "<mod:module-1>"),
            ],
            module_library=module_library,
        )

        at_limit = project_scene_portability_payload(project, "scene")
        self.assertTrue(at_limit["valid"])
        self.assertEqual(20, len(at_limit["module_snapshots"]))

        module_library["module-20"]["body"] = "<mod:module-21>"
        module_library["module-21"] = {"body": "beyond the limit"}
        too_deep_project = Project(prompt_lines=project.prompt_lines, module_library=module_library)
        before = copy.deepcopy(too_deep_project)

        result = project_scene_portability_payload(too_deep_project, "scene")

        self.assertFalse(result["valid"])
        self.assertEqual(["module_closure_limit_exceeded"], result["blockers"])
        self.assertEqual(before, too_deep_project)

    def test_blocks_module_closure_over_snapshot_count(self):
        module_count = 257
        module_library = {
            f"module-{index:03d}": {"body": f"token-{index}"}
            for index in range(module_count)
        }
        prompt = ", ".join(f"<mod:module-{index:03d}>" for index in range(module_count))
        project = Project(
            prompt_lines=[
                _line("scene", "S", line_type="separator"),
                _line("line", prompt),
            ],
            module_library=module_library,
        )

        result = project_scene_portability_payload(project, "scene")

        self.assertFalse(result["valid"])
        self.assertEqual(["module_closure_limit_exceeded"], result["blockers"])

    def test_module_cycles_remain_deterministic(self):
        project = Project(
            prompt_lines=[
                _line("scene", "S", line_type="separator"),
                _line("line", "<mod:module-a>"),
            ],
            module_library={
                "module-a": {"body": "<mod:module-b>"},
                "module-b": {"body": "<mod:module-a>"},
            },
        )

        first = project_scene_portability_payload(project, "scene")
        repeated = project_scene_portability_payload(project, "scene")

        self.assertTrue(first["valid"])
        self.assertEqual(["module-a", "module-b"], [item["name"] for item in first["module_snapshots"]])
        self.assertEqual(first, repeated)

    def test_negative_module_markers_do_not_add_module_snapshots(self):
        project = Project(
            prompt_lines=[
                _line("scene", "S", line_type="separator"),
                _line("line", "ordinary prompt", negative_prompt="<mod:negative-only>"),
            ],
            module_library={"negative-only": {"body": "must not be copied"}},
        )

        result = project_scene_portability_payload(project, "scene")

        self.assertTrue(result["valid"])
        self.assertEqual([], result["module_snapshots"])

    def test_unresolved_and_malformed_module_references_block_the_projection(self):
        missing = Project(
            prompt_lines=[_line("scene", "S", line_type="separator"), _line("line", "<mod:missing>")],
            module_library={},
        )
        malformed = Project(
            prompt_lines=[_line("scene", "S", line_type="separator"), _line("line", "<mod:bad>")],
            module_library={"bad": {"body": object()}},
        )
        cases = [
            (missing, "unresolved_module_reference"),
            (malformed, "malformed_referenced_module"),
            (Project(
                prompt_lines=[_line("scene", "S", line_type="separator"), _line("line", "<mod:ref>")],
                module_library={"ref": {"body": "safe", "graph": {"nodes": [42]}}},
            ), "malformed_referenced_module"),
            (Project(
                prompt_lines=[_line("scene", "S", line_type="separator"), _line("line", "<mod:ref>")],
                module_library={"ref": {"body": "safe", "metadata": {"opaque": object()}}},
            ), "unsupported_module_content"),
            (Project(
                prompt_lines=[_line("scene", "S", line_type="separator"), _line("line", "<mod:ref>")],
                module_library={"ref": {"body": r"C:\\private\\prompt.txt"}},
            ), "unsafe_module_metadata"),
        ]
        for project, expected in cases:
            with self.subTest(expected=expected):
                result = project_scene_portability_payload(project, "scene")
                self.assertFalse(result["valid"])
                self.assertEqual([expected], result["blockers"])

    def test_fingerprint_is_deterministic_and_tracks_included_prompt_and_module_content(self):
        project = _source_project()
        first = project_scene_portability_payload(project, "scene-source")
        repeated = project_scene_portability_payload(project, "scene-source")
        self.assertEqual(first["source_scene_fingerprint"], repeated["source_scene_fingerprint"])

        project.prompt_lines[2].current_text += ", added"
        prompt_changed = project_scene_portability_payload(project, "scene-source")
        self.assertNotEqual(first["source_scene_fingerprint"], prompt_changed["source_scene_fingerprint"])

        project.prompt_lines[2].current_text = "  <mod:parent>, exact positive  "
        project.module_library["child"]["body"] = "green eyes"
        module_changed = project_scene_portability_payload(project, "scene-source")
        self.assertNotEqual(first["source_scene_fingerprint"], module_changed["source_scene_fingerprint"])

        project.module_library["child"]["body"] = "blue eyes"
        project.prompt_lines[1].separator_color = "teal"
        scene_changed = project_scene_portability_payload(project, "scene-source")
        self.assertNotEqual(first["source_scene_fingerprint"], scene_changed["source_scene_fingerprint"])

    def test_non_json_module_library_is_rejected_without_leaking_details(self):
        project = Project(
            prompt_lines=[_line("scene", "S", line_type="separator"), _line("line", "<mod:ref>")],
            module_library=[],
        )

        result = project_scene_portability_payload(project, "scene")

        self.assertFalse(result["valid"])
        self.assertEqual(["malformed_module_library"], result["blockers"])
        self.assertTrue(all(set(item) == {"code"} for item in result["diagnostics"]))

    def test_success_result_is_json_only_and_project_stays_unchanged(self):
        project = _source_project()
        before = copy.deepcopy(project)

        result = project_scene_portability_payload(project, "scene-source")

        json.dumps(result, ensure_ascii=False, allow_nan=False)
        self.assertEqual(before, project)


if __name__ == "__main__":
    unittest.main()
