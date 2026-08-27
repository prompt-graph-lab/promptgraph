import ast
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core.io import (
    ProjectAssetsPreviewStaleError,
    copy_candidates_to_project,
    copy_candidates_to_project_and_save_atomically,
    preview_copy_candidates_to_project,
)
from core.project import Project, PromptLine


def _line(line_id, index, *, candidates=None, variants=None):
    return PromptLine(
        id=line_id,
        original_file_name=f"{line_id}.txt",
        original_index=index,
        current_index=index,
        original_text="prompt",
        current_text="prompt",
        tokens=["prompt"],
        generated_candidates=list(candidates or []),
        gallery_variants=list(variants or []),
    )


class ProjectAssetsPreviewTests(unittest.TestCase):
    def test_preview_counts_references_unique_sources_and_actual_copy_cost(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_dir = root / "project"
            project_dir.mkdir()
            project_path = project_dir / "project.json"
            source = root / "shared.png"
            source.write_bytes(b"0123456789")
            project = Project(
                prompt_lines=[
                    _line(
                        "line-a",
                        0,
                        candidates=[{"path": str(source)}],
                        variants=[{"id": "variant-a", "path": str(source)}],
                    ),
                    _line(
                        "line-b",
                        1,
                        candidates=[{"path": str(source)}],
                    ),
                ]
            )

            preview = preview_copy_candidates_to_project(
                project,
                str(project_path),
            )

            self.assertTrue(preview["valid"])
            self.assertEqual(preview["reference_count"], 3)
            self.assertEqual(preview["unique_source_count"], 1)
            self.assertEqual(preview["project_inside_source_count"], 0)
            self.assertEqual(preview["project_outside_source_count"], 1)
            self.assertEqual(preview["planned_copy_count"], 2)
            self.assertEqual(preview["reused_reference_count"], 1)
            self.assertEqual(preview["estimated_copy_bytes"], 20)
            self.assertFalse((project_dir / "candidates").exists())
            self.assertEqual(
                project.prompt_lines[0].generated_candidates[0]["path"],
                str(source),
            )
            self.assertEqual(
                project.prompt_lines[0].gallery_variants[0]["path"],
                str(source),
            )

    def test_project_generated_source_is_planned_and_candidates_source_is_local(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir) / "project"
            generated_dir = project_dir / "generated"
            local_dir = project_dir / "candidates" / "line_0002"
            generated_dir.mkdir(parents=True)
            local_dir.mkdir(parents=True)
            generated_source = generated_dir / "generated.png"
            local_source = local_dir / "local.png"
            generated_source.write_bytes(b"generated")
            local_source.write_bytes(b"local")
            project_path = project_dir / "project.json"
            project = Project(
                prompt_lines=[
                    _line(
                        "line-a",
                        0,
                        candidates=[{"path": "generated/generated.png"}],
                    ),
                    _line(
                        "line-b",
                        1,
                        candidates=[{"path": "candidates/line_0002/local.png"}],
                    ),
                ]
            )

            preview = preview_copy_candidates_to_project(
                project,
                str(project_path),
            )

            self.assertEqual(preview["project_inside_source_count"], 2)
            self.assertEqual(preview["project_outside_source_count"], 0)
            self.assertEqual(preview["planned_copy_count"], 1)
            self.assertEqual(preview["already_local_count"], 1)
            self.assertEqual(preview["copy_not_needed_count"], 1)
            self.assertEqual(preview["estimated_copy_bytes"], len(b"generated"))

    def test_missing_malformed_and_unreadable_sources_are_reported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_dir = root / "project"
            project_dir.mkdir()
            unreadable_directory = root / "not-a-file"
            unreadable_directory.mkdir()
            project = Project(
                prompt_lines=[
                    _line(
                        "line-a",
                        0,
                        candidates=[
                            {"path": str(root / "missing.png")},
                            {"path": "\0malformed"},
                            {"path": str(unreadable_directory)},
                        ],
                    )
                ]
            )

            preview = preview_copy_candidates_to_project(
                project,
                str(project_dir / "project.json"),
            )

            self.assertEqual(preview["unique_source_count"], 3)
            self.assertEqual(preview["missing_source_count"], 2)
            self.assertEqual(preview["unreadable_source_count"], 1)
            self.assertEqual(preview["planned_copy_count"], 0)
            self.assertEqual(preview["copy_not_needed_count"], 0)
            self.assertEqual(preview["estimated_copy_bytes"], 0)

    def test_destination_collision_is_previewed_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_dir = root / "project"
            line_dir = project_dir / "candidates" / "line_0001"
            line_dir.mkdir(parents=True)
            (line_dir / "source.png").write_bytes(b"existing")
            source = root / "source.png"
            source.write_bytes(b"new")
            project = Project(
                prompt_lines=[
                    _line(
                        "line-a",
                        0,
                        candidates=[{"path": str(source)}],
                    )
                ]
            )

            preview = preview_copy_candidates_to_project(
                project,
                str(project_dir / "project.json"),
            )

            self.assertEqual(preview["collision_count"], 1)
            self.assertTrue(
                preview["entries"][0]["target_path"].endswith("source_1.png")
            )
            self.assertEqual((line_dir / "source.png").read_bytes(), b"existing")
            self.assertFalse((line_dir / "source_1.png").exists())

    @unittest.skipUnless(os.name == "nt", "Windows path normalization coverage")
    def test_windows_case_differences_share_one_unique_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_dir = root / "project"
            project_dir.mkdir()
            source = root / "CaseSource.PNG"
            source.write_bytes(b"same")
            project = Project(
                prompt_lines=[
                    _line(
                        "line-a",
                        0,
                        candidates=[{"path": str(source).upper()}],
                    ),
                    _line(
                        "line-b",
                        1,
                        candidates=[{"path": str(source).lower()}],
                    ),
                ]
            )

            preview = preview_copy_candidates_to_project(
                project,
                str(project_dir / "project.json"),
            )

            self.assertEqual(preview["unique_source_count"], 1)
            self.assertEqual(preview["planned_copy_count"], 2)


class ProjectAssetsApplyTests(unittest.TestCase):
    def test_atomic_apply_replaces_project_json_after_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_dir = root / "project"
            project_dir.mkdir()
            project_path = project_dir / "project.json"
            project_path.write_bytes(b'{"original":"project-json"}\n')
            source = root / "source.png"
            source.write_bytes(b"image")
            project = Project(
                prompt_lines=[
                    _line(
                        "line-a",
                        0,
                        candidates=[{"path": str(source)}],
                    )
                ]
            )
            preview = preview_copy_candidates_to_project(
                project,
                str(project_path),
            )

            summary = copy_candidates_to_project_and_save_atomically(
                project,
                str(project_path),
                expected_signature=preview["signature"],
            )

            saved = json.loads(project_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["copied"], 1)
            self.assertEqual(
                saved["prompt_lines"][0]["generated_candidates"][0]["path"],
                "candidates/line_0001/source.png",
            )
            self.assertEqual(
                list(project_dir.glob(f".{project_path.name}.*.tmp")),
                [],
            )
            self.assertTrue(source.exists())

    def test_apply_preserves_source_updates_references_and_is_repeat_safe(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_dir = root / "project"
            project_dir.mkdir()
            project_path = project_dir / "project.json"
            source = root / "source.png"
            source.write_bytes(b"image-bytes")
            line = _line(
                "line-a",
                0,
                candidates=[{"path": str(source)}],
                variants=[{"id": "variant-a", "path": str(source)}],
            )
            line.generated_image_path = str(source)
            line.selected_candidate_path = str(source)
            line.lineage_info = {"candidate_image_path": str(source)}
            project = Project(prompt_lines=[line])
            preview = preview_copy_candidates_to_project(
                project,
                str(project_path),
            )

            summary = copy_candidates_to_project(
                project,
                str(project_path),
                expected_signature=preview["signature"],
            )

            self.assertEqual(summary["copied"], 1)
            self.assertTrue(source.exists())
            self.assertEqual(source.read_bytes(), b"image-bytes")
            copied_path = project.prompt_lines[0].generated_candidates[0]["path"]
            self.assertEqual(copied_path, "candidates/line_0001/source.png")
            self.assertEqual(
                project.prompt_lines[0].gallery_variants[0]["path"],
                copied_path,
            )
            self.assertEqual(project.prompt_lines[0].generated_image_path, copied_path)
            self.assertEqual(project.prompt_lines[0].selected_candidate_path, copied_path)
            self.assertEqual(
                project.prompt_lines[0].lineage_info["candidate_image_path"],
                copied_path,
            )
            self.assertEqual(
                (project_dir / copied_path).read_bytes(),
                b"image-bytes",
            )

            repeat_preview = preview_copy_candidates_to_project(
                project,
                str(project_path),
            )
            self.assertEqual(repeat_preview["planned_copy_count"], 0)
            self.assertEqual(repeat_preview["already_local_count"], 2)

    def test_stale_preview_blocks_apply_without_mutation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_dir = root / "project"
            project_dir.mkdir()
            project_path = project_dir / "project.json"
            source = root / "source.png"
            source.write_bytes(b"before")
            project = Project(
                prompt_lines=[
                    _line(
                        "line-a",
                        0,
                        candidates=[{"path": str(source)}],
                    )
                ]
            )
            preview = preview_copy_candidates_to_project(
                project,
                str(project_path),
            )
            source.write_bytes(b"after-size-change")

            with self.assertRaises(ProjectAssetsPreviewStaleError):
                copy_candidates_to_project(
                    project,
                    str(project_path),
                    expected_signature=preview["signature"],
                )

            self.assertEqual(
                project.prompt_lines[0].generated_candidates[0]["path"],
                str(source),
            )
            self.assertFalse((project_dir / "candidates").exists())

    def test_relevant_project_reference_change_makes_preview_stale(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_dir = root / "project"
            project_dir.mkdir()
            project_path = project_dir / "project.json"
            source = root / "source.png"
            source.write_bytes(b"image")
            project = Project(
                prompt_lines=[
                    _line(
                        "line-a",
                        0,
                        candidates=[{"path": str(source)}],
                    )
                ]
            )
            preview = preview_copy_candidates_to_project(
                project,
                str(project_path),
            )
            project.prompt_lines[0].lineage_info = {
                "candidate_image_path": str(source),
                "note": "changed after preview",
            }

            with self.assertRaises(ProjectAssetsPreviewStaleError):
                copy_candidates_to_project(
                    project,
                    str(project_path),
                    expected_signature=preview["signature"],
                )

            self.assertEqual(
                project.prompt_lines[0].generated_candidates[0]["path"],
                str(source),
            )
            self.assertFalse((project_dir / "candidates").exists())

    def test_copy_failure_leaves_project_unchanged_and_removes_partial_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_dir = root / "project"
            project_dir.mkdir()
            project_path = project_dir / "project.json"
            source_a = root / "a.png"
            source_b = root / "b.png"
            source_a.write_bytes(b"a")
            source_b.write_bytes(b"b")
            project = Project(
                prompt_lines=[
                    _line(
                        "line-a",
                        0,
                        candidates=[{"path": str(source_a)}],
                    ),
                    _line(
                        "line-b",
                        1,
                        candidates=[{"path": str(source_b)}],
                    ),
                ]
            )
            preview = preview_copy_candidates_to_project(
                project,
                str(project_path),
            )
            real_copy2 = __import__("shutil").copy2
            call_count = 0

            def fail_second_copy(source, target):
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise OSError("simulated copy failure")
                return real_copy2(source, target)

            with mock.patch("core.io.shutil.copy2", side_effect=fail_second_copy):
                with self.assertRaises(OSError):
                    copy_candidates_to_project(
                        project,
                        str(project_path),
                        expected_signature=preview["signature"],
                    )

            self.assertEqual(
                project.prompt_lines[0].generated_candidates[0]["path"],
                str(source_a),
            )
            self.assertEqual(
                project.prompt_lines[1].generated_candidates[0]["path"],
                str(source_b),
            )
            copied_files = [
                path
                for path in (project_dir / "candidates").rglob("*")
                if path.is_file()
            ]
            self.assertEqual(copied_files, [])


class ProjectAssetsUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (
            Path(__file__).resolve().parents[1] / "app.py"
        ).read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.app_source)
        cls.functions = {
            node.name: node
            for node in cls.tree.body
            if isinstance(node, ast.FunctionDef)
        }

    def _source(self, name):
        return ast.get_source_segment(self.app_source, self.functions[name])

    def test_sidebar_renderer_has_one_owner_and_does_not_move_to_workspace(self):
        calls = [
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "render_project_assets_sidebar_section"
        ]
        self.assertEqual(len(calls), 1)
        workspace = self._source("render_project_management_workspace")
        self.assertNotIn("render_project_assets_sidebar_section", workspace)

    def test_ui_requires_preview_confirmation_and_fresh_signature(self):
        renderer = self._source("render_project_assets_sidebar_section")
        self.assertIn("コピー内容をPreview", renderer)
        self.assertIn("copy_not_needed_count", renderer)
        self.assertIn("estimated_copy_bytes", renderer)
        self.assertIn("project_inside_source_count", renderer)
        self.assertIn("project_outside_source_count", renderer)
        self.assertIn("missing_source_count", renderer)
        self.assertIn("collision_count", renderer)
        self.assertIn("上記のcopy内容とProject参照更新を確認しました", renderer)
        self.assertIn("fresh_preview.get(\"signature\")", renderer)
        self.assertIn("preview.get(\"signature\")", renderer)
        self.assertLess(
            renderer.index("preview_copy_candidates_to_project("),
            renderer.index(
                "_copy_project_assets_and_save_with_session_rollback("
            ),
        )

    def test_preview_path_has_no_save_history_copy_or_rerun(self):
        renderer = self._source("render_project_assets_sidebar_section")
        preview_button = renderer.index('"コピー内容をPreview"')
        apply_button = renderer.index('"確認してProjectへ取り込む"')
        preview_path = renderer[preview_button:apply_button]
        for forbidden in (
            "_copy_project_assets_and_save_with_session_rollback(",
            "save_project_to_json(",
            "push_history(",
            "st.rerun(",
        ):
            self.assertNotIn(forbidden, preview_path)

    def test_apply_path_keeps_one_save_no_history_and_success_rerun_contract(self):
        renderer = self._source("render_project_assets_sidebar_section")
        self.assertEqual(renderer.count("save_project_to_json("), 0)
        self.assertEqual(
            renderer.count(
                "_copy_project_assets_and_save_with_session_rollback("
            ),
            1,
        )
        self.assertEqual(renderer.count("push_history("), 0)
        self.assertEqual(renderer.count("st.rerun("), 2)
        self.assertEqual(
            renderer.count("PROJECT_ASSETS_CONFIRM_RESET_PENDING_KEY"),
            4,
        )
        self.assertIn("_sync_project_assets_candidate_session_state(project)", renderer)
        success_path = renderer.split(
            "_sync_project_assets_candidate_session_state(project)",
            1,
        )[1]
        self.assertNotIn("st.rerun(", success_path)

    def test_save_failure_preserves_json_files_and_session_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_dir = root / "project"
            project_dir.mkdir()
            project_path = project_dir / "project.json"
            original_json = b'{"original":"project-json"}\r\n'
            project_path.write_bytes(original_json)
            source = root / "source.png"
            source.write_bytes(b"image")
            project = Project(
                prompt_lines=[
                    _line(
                        "line-a",
                        0,
                        candidates=[{"path": str(source)}],
                    )
                ]
            )
            preview = preview_copy_candidates_to_project(
                project,
                str(project_path),
            )
            previous_project = project.clone()
            previous_candidate_state = {
                "line-a": [{"path": str(source), "status": "before"}]
            }
            fake_st = SimpleNamespace(
                session_state=SimpleNamespace(
                    project=project,
                    line_generated_candidates={"changed": True},
                )
            )
            namespace = {
                "copy_candidates_to_project_and_save_atomically": (
                    copy_candidates_to_project_and_save_atomically
                ),
                "ProjectAssetsPreviewStaleError": (
                    ProjectAssetsPreviewStaleError
                ),
                "st": fake_st,
            }
            exec(self._source(
                "_copy_project_assets_and_save_with_session_rollback"
            ), namespace)
            apply_with_rollback = namespace[
                "_copy_project_assets_and_save_with_session_rollback"
            ]

            def fail_after_partial_temporary_write(_project, _output_path, handle):
                handle.write('{"partial":')
                handle.flush()
                raise UnicodeEncodeError(
                    "utf-8",
                    "\ud800",
                    0,
                    1,
                    "simulated encoding failure",
                )

            with mock.patch(
                "core.io._write_project_json",
                side_effect=fail_after_partial_temporary_write,
            ):
                with self.assertRaises(UnicodeEncodeError):
                    apply_with_rollback(
                        project,
                        str(project_path),
                        preview["signature"],
                        previous_project,
                        previous_candidate_state,
                    )

            self.assertEqual(project_path.read_bytes(), original_json)
            self.assertEqual(
                project.prompt_lines[0].generated_candidates[0]["path"],
                str(source),
            )
            self.assertIs(fake_st.session_state.project, previous_project)
            self.assertEqual(
                fake_st.session_state.line_generated_candidates,
                previous_candidate_state,
            )
            copied_files = [
                path
                for path in (project_dir / "candidates").rglob("*")
                if path.is_file()
            ]
            self.assertEqual(copied_files, [])
            self.assertEqual(
                list(project_dir.glob(f".{project_path.name}.*.tmp")),
                [],
            )
            self.assertTrue(source.exists())

    def test_successful_project_replacements_reset_preview(self):
        for name in (
            "load_project_json_into_session",
            "set_new_workspace_project",
            "render_prompt_import_export_panel",
        ):
            self.assertIn(
                "reset_project_assets_operation_state()",
                self._source(name),
            )
        failed_load_prefix = self._source("load_project_json_into_session").split(
            "reset_project_assets_operation_state()", 1
        )[0]
        self.assertIn("return False", failed_load_prefix)

    def test_ui_copy_and_ownership_explanations_are_explicit(self):
        renderer = self._source("render_project_assets_sidebar_section")
        for expected in (
            "Candidate / Variant画像をProjectへ取り込む",
            "元画像は移動・削除しません",
            "Project容量が大きく増える可能性があります",
            "通常生成した画像はすでに generated/ に保存",
            "Project Assets",
        ):
            self.assertIn(expected, renderer)


if __name__ == "__main__":
    unittest.main()
