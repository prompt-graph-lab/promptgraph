import os
import shutil
import tempfile
import unittest

from core.io import load_project_from_json
from core.lightweight_fork import (
    _commit_directory_with_retry,
    _is_retryable_windows_filesystem_error,
    _remove_tree_with_retry,
    build_lightweight_fork_preview,
    materialize_lightweight_fork,
    validate_lightweight_fork_apply,
)
from core.project import Project, PromptLine


def _line(**overrides):
    data = {
        "id": "line_1",
        "original_file_name": "line_1",
        "original_index": 0,
        "current_index": 0,
        "original_text": "original prompt",
        "current_text": "current prompt",
        "tokens": ["current", "prompt"],
        "negative_prompt": "negative",
    }
    data.update(overrides)
    return PromptLine(**data)


def _project(lines):
    return Project(source_directory="", prompt_lines=lines)


def _win_error(winerror, message="Access is denied"):
    error = PermissionError(5, message)
    error.winerror = winerror
    return error


class LightweightForkMaterializationTests(unittest.TestCase):
    def _write_image(self, directory, name, content=b"image"):
        path = os.path.join(directory, name)
        with open(path, "wb") as handle:
            handle.write(content)
        return path

    def test_successful_materialization_round_trips_project_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            selected_path = self._write_image(tmpdir, "selected.png", b"selected")
            generated_path = self._write_image(tmpdir, "generated.png", b"generated")
            image_path = self._write_image(tmpdir, "image.png", b"image")
            source_project = _project([
                _line(id="route", line_type="separator", separator_label="Route A", current_text="Route A"),
                _line(
                    id="selected",
                    selected_candidate_path=selected_path,
                    generated_image_path=generated_path,
                    image_path=image_path,
                    generated_candidates=[{"path": selected_path, "trashed": True}],
                    gallery_variants=[{"path": "variant.png"}],
                    lineage_info={"old": True},
                    source_generation_info={"old": True},
                    current_text="selected prompt",
                    negative_prompt="selected negative",
                ),
                _line(id="generated", generated_image_path=generated_path, image_path=image_path),
                _line(id="image", image_path=image_path),
                _line(id="skipped"),
            ])
            source_project_path = os.path.join(tmpdir, "source_project.json")
            preview = build_lightweight_fork_preview(
                source_project.prompt_lines,
                fork_name="Final Fork",
                project_path=source_project_path,
                path_exists=os.path.exists,
            )

            result = materialize_lightweight_fork(
                source_project,
                source_project_path=source_project_path,
                stored_preview=preview,
                destination_parent_dir=tmpdir,
                fork_name="Final Fork",
                created_at_provider=lambda: "2026-07-13T00:00:00+00:00",
            )

            self.assertTrue(result["success"], result)
            self.assertEqual(3, result["materialized_count"])
            self.assertEqual(1, result["commit_attempts"])
            self.assertFalse(result["commit_retry_performed"])
            self.assertEqual(0, result["cleanup_attempts"])
            self.assertTrue(os.path.isdir(result["destination_directory"]))
            self.assertTrue(os.path.exists(result["project_path"]))
            self.assertTrue(os.path.exists(result["manifest_path"]))
            self.assertTrue(os.path.exists(selected_path))
            self.assertEqual(selected_path, source_project.prompt_lines[1].selected_candidate_path)
            self.assertEqual(generated_path, source_project.prompt_lines[1].generated_image_path)
            self.assertEqual([{"path": selected_path, "trashed": True}], source_project.prompt_lines[1].generated_candidates)
            self.assertEqual([{"path": "variant.png"}], source_project.prompt_lines[1].gallery_variants)

            fork_project = load_project_from_json(result["project_path"])
            self.assertEqual(["separator", None, None, None], [line.line_type for line in fork_project.prompt_lines])
            materialized = [line for line in fork_project.prompt_lines if line.line_type != "separator"]
            self.assertEqual(3, len(materialized))
            self.assertEqual("selected prompt", materialized[0].current_text)
            self.assertEqual("selected prompt", materialized[0].original_text)
            self.assertEqual("selected negative", materialized[0].negative_prompt)
            self.assertTrue(materialized[0].image_path.startswith("images"))
            self.assertEqual("", materialized[0].selected_candidate_path)
            self.assertEqual("", materialized[0].generated_image_path)
            self.assertEqual([], materialized[0].generated_candidates)
            self.assertEqual([], materialized[0].gallery_variants)
            self.assertEqual({}, materialized[0].lineage_info)
            self.assertEqual({}, materialized[0].source_generation_info)
            self.assertNotEqual("selected", materialized[0].id)

            with open(result["manifest_path"], "r", encoding="utf-8") as handle:
                manifest_text = handle.read()
            self.assertIn('"operation": "lightweight_fork_final_sequence"', manifest_text)
            self.assertIn('"source_line_id": "selected"', manifest_text)
            self.assertIn('"skipped_reason": "no resolved final image"', manifest_text)

    def test_selected_lines_include_needed_route_separators_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            first_path = self._write_image(tmpdir, "first.png")
            second_path = self._write_image(tmpdir, "second.png")
            third_path = self._write_image(tmpdir, "third.png")
            source_project = _project([
                _line(id="route_a", line_type="separator", separator_label="Route A", current_text="Route A"),
                _line(id="first", image_path=first_path),
                _line(id="second", image_path=second_path),
                _line(id="route_b", line_type="separator", separator_label="Route B", current_text="Route B"),
                _line(id="third", image_path=third_path),
            ])
            preview = build_lightweight_fork_preview(
                source_project.prompt_lines,
                fork_name="Scoped",
                scope="selected_lines",
                target_line_ids=["second", "third"],
                selected_line_ids=["second", "third"],
                path_exists=os.path.exists,
            )

            result = materialize_lightweight_fork(
                source_project,
                stored_preview=preview,
                destination_parent_dir=tmpdir,
                fork_name="Scoped",
            )

            self.assertTrue(result["success"], result)
            fork_project = load_project_from_json(result["project_path"])
            self.assertEqual(
                ["Route A", "current prompt", "Route B", "current prompt"],
                [line.current_text for line in fork_project.prompt_lines],
            )

    def test_destination_conflict_rejects_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = self._write_image(tmpdir, "image.png")
            source_project = _project([_line(id="line", image_path=image_path)])
            preview = build_lightweight_fork_preview(source_project.prompt_lines, fork_name="Conflict", path_exists=os.path.exists)
            destination = os.path.join(tmpdir, "forks", "Conflict")
            os.makedirs(destination)
            marker = os.path.join(destination, "keep.txt")
            with open(marker, "w", encoding="utf-8") as handle:
                handle.write("keep")

            result = materialize_lightweight_fork(
                source_project,
                stored_preview=preview,
                destination_parent_dir=tmpdir,
                fork_name="Conflict",
            )

            self.assertFalse(result["success"])
            self.assertTrue(result["conflict"])
            self.assertTrue(os.path.exists(marker))

    def test_stale_preview_rejects_changed_prompt_and_file_stat(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = self._write_image(tmpdir, "image.png", b"first")
            source_project = _project([_line(id="line", image_path=image_path, current_text="before")])
            preview = build_lightweight_fork_preview(source_project.prompt_lines, fork_name="Stale", path_exists=os.path.exists)

            source_project.prompt_lines[0].current_text = "after"
            result = materialize_lightweight_fork(
                source_project,
                stored_preview=preview,
                destination_parent_dir=tmpdir,
                fork_name="Stale",
            )
            self.assertFalse(result["success"])
            self.assertTrue(result["stale_preview"])
            self.assertFalse(os.path.exists(os.path.join(tmpdir, "forks", "Stale")))

            source_project.prompt_lines[0].current_text = "before"
            with open(image_path, "ab") as handle:
                handle.write(b"changed")
            result = materialize_lightweight_fork(
                source_project,
                stored_preview=preview,
                destination_parent_dir=tmpdir,
                fork_name="Stale",
            )
            self.assertFalse(result["success"])
            self.assertTrue(result["stale_preview"])

    def test_stale_preview_rejects_prompt_changes_after_display_preview(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = self._write_image(tmpdir, "image.png")
            prompt = "prompt " * 50
            negative_prompt = "negative " * 50
            source_project = _project([_line(
                id="line",
                image_path=image_path,
                current_text=prompt,
                negative_prompt=negative_prompt,
            )])
            preview = build_lightweight_fork_preview(
                source_project.prompt_lines,
                fork_name="Long Prompt",
                path_exists=os.path.exists,
            )
            entry = preview["entries"][0]
            self.assertEqual(prompt[:240].strip(), entry["prompt_preview"])
            self.assertEqual(negative_prompt[:240].strip(), entry["negative_prompt_preview"])

            source_project.prompt_lines[0].current_text = prompt[:280] + "changed" + prompt[287:]
            result = materialize_lightweight_fork(
                source_project,
                stored_preview=preview,
                destination_parent_dir=tmpdir,
                fork_name="Long Prompt",
            )
            self.assertFalse(result["success"])
            self.assertTrue(result["stale_preview"])

            source_project.prompt_lines[0].current_text = prompt
            source_project.prompt_lines[0].negative_prompt = negative_prompt[:280] + "changed" + negative_prompt[287:]
            result = materialize_lightweight_fork(
                source_project,
                stored_preview=preview,
                destination_parent_dir=tmpdir,
                fork_name="Long Prompt",
            )
            self.assertFalse(result["success"])
            self.assertTrue(result["stale_preview"])

    def test_prompt_whitespace_round_trips_unchanged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = self._write_image(tmpdir, "image.png")
            prompt = "\n  leading prompt,\nsecond line  \n"
            negative_prompt = "\n  negative prompt  \n"
            source_project = _project([_line(
                id="line",
                image_path=image_path,
                current_text=prompt,
                negative_prompt=negative_prompt,
            )])
            preview = build_lightweight_fork_preview(
                source_project.prompt_lines,
                fork_name="Whitespace",
                path_exists=os.path.exists,
            )

            result = materialize_lightweight_fork(
                source_project,
                stored_preview=preview,
                destination_parent_dir=tmpdir,
                fork_name="Whitespace",
            )

            self.assertTrue(result["success"], result)
            fork_project = load_project_from_json(result["project_path"])
            fork_line = fork_project.prompt_lines[0]
            self.assertEqual(prompt, fork_line.original_text)
            self.assertEqual(prompt, fork_line.current_text)
            self.assertEqual(negative_prompt, fork_line.negative_prompt)

    def test_copy_failure_cleans_staging_and_keeps_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = self._write_image(tmpdir, "image.png", b"source")
            source_project = _project([_line(id="line", image_path=image_path)])
            preview = build_lightweight_fork_preview(source_project.prompt_lines, fork_name="Rollback", path_exists=os.path.exists)

            def failing_copy(_source, _destination):
                raise OSError("copy failed")

            result = materialize_lightweight_fork(
                source_project,
                stored_preview=preview,
                destination_parent_dir=tmpdir,
                fork_name="Rollback",
                copy_file=failing_copy,
            )

            self.assertFalse(result["success"])
            self.assertTrue(result["cleanup_performed"])
            self.assertFalse(os.path.exists(os.path.join(tmpdir, "forks", "Rollback")))
            with open(image_path, "rb") as handle:
                self.assertEqual(b"source", handle.read())
            staging_dirs = [
                name for name in os.listdir(os.path.join(tmpdir, "forks"))
                if name.startswith(".Rollback.staging.")
            ]
            self.assertEqual([], staging_dirs)

    def test_tampered_planned_destination_is_stale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = self._write_image(tmpdir, "image.png")
            source_project = _project([_line(id="line", image_path=image_path)])
            preview = build_lightweight_fork_preview(source_project.prompt_lines, fork_name="Safe", path_exists=os.path.exists)
            preview["entries"][0]["planned_destination_path"] = "../escape.png"
            preview["signature"] = validate_signature = preview["signature"]

            validation = validate_lightweight_fork_apply(
                source_project,
                stored_preview=preview,
                current_preview=preview,
                destination_parent_dir=tmpdir,
                fork_name="Safe",
            )

            self.assertFalse(validation["valid"])
            self.assertTrue(validation["stale_preview"])
            self.assertEqual(validate_signature, preview["signature"])

    def test_app_connects_create_fork_ui_to_core_apply(self):
        app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))
        with open(app_path, "r", encoding="utf-8") as handle:
            app_source = handle.read()
            self.assertIn('"派生Projectを作成"', app_source)
            self.assertIn("materialize_lightweight_fork", app_source)
            self.assertNotIn("派生Projectを作成 (future)", app_source)

    def _materialization_fixture(self, tmpdir, fork_name):
        image_path = self._write_image(tmpdir, "image.png", b"source image")
        source_project = _project([_line(id="line", image_path=image_path)])
        preview = build_lightweight_fork_preview(
            source_project.prompt_lines,
            fork_name=fork_name,
            path_exists=os.path.exists,
        )
        return source_project, preview, image_path

    def test_retryable_winerror_5_then_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_project, preview, image_path = self._materialization_fixture(tmpdir, "Retry Access")
            rename_attempts = []
            sleeps = []

            def flaky_rename(source, destination):
                rename_attempts.append((source, destination))
                if len(rename_attempts) < 3:
                    raise _win_error(5)
                os.rename(source, destination)

            result = materialize_lightweight_fork(
                source_project,
                stored_preview=preview,
                destination_parent_dir=tmpdir,
                fork_name="Retry Access",
                rename=flaky_rename,
                sleep=sleeps.append,
                retry_delays=(0, 0.01, 0.02),
            )

            self.assertTrue(result["success"], result)
            self.assertEqual(3, result["commit_attempts"])
            self.assertTrue(result["commit_retry_performed"])
            self.assertTrue(result["retryable_windows_error"])
            self.assertEqual([0.01, 0.02], sleeps)
            self.assertTrue(os.path.isfile(result["project_path"]))
            self.assertTrue(os.path.isfile(result["manifest_path"]))
            self.assertTrue(os.path.isfile(os.path.join(result["destination_directory"], "images", "0001_image.png")))
            self.assertTrue(os.path.isfile(image_path))

    def test_retryable_sharing_violation_then_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_project, preview, _image_path = self._materialization_fixture(tmpdir, "Retry Sharing")
            rename_attempts = []
            sleeps = []

            def flaky_rename(source, destination):
                rename_attempts.append(True)
                if len(rename_attempts) < 3:
                    raise _win_error(32, "Sharing violation")
                os.rename(source, destination)

            result = materialize_lightweight_fork(
                source_project,
                stored_preview=preview,
                destination_parent_dir=tmpdir,
                fork_name="Retry Sharing",
                rename=flaky_rename,
                sleep=sleeps.append,
                retry_delays=(0, 0.01, 0.02),
            )

            self.assertTrue(result["success"], result)
            self.assertEqual(3, result["commit_attempts"])
            self.assertTrue(result["retryable_windows_error"])
            self.assertEqual([0.01, 0.02], sleeps)

    def test_retry_exhausted_cleans_staging_without_touching_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_project, preview, image_path = self._materialization_fixture(tmpdir, "Retry Exhausted")
            sleeps = []

            def always_locked(_source, _destination):
                raise _win_error(5)

            result = materialize_lightweight_fork(
                source_project,
                stored_preview=preview,
                destination_parent_dir=tmpdir,
                fork_name="Retry Exhausted",
                rename=always_locked,
                sleep=sleeps.append,
                retry_delays=(0, 0.01, 0.02),
            )

            self.assertFalse(result["success"])
            self.assertFalse(result["conflict"])
            self.assertEqual(3, result["commit_attempts"])
            self.assertTrue(result["retryable_windows_error"])
            self.assertIn("temporary Windows filesystem lock exhausted", result["error"])
            self.assertTrue(result["cleanup_performed"])
            self.assertEqual(1, result["cleanup_attempts"])
            self.assertFalse(os.path.exists(result["destination_directory"]))
            self.assertFalse(os.path.exists(result["staging_directory"]))
            with open(image_path, "rb") as handle:
                self.assertEqual(b"source image", handle.read())
            self.assertEqual("current prompt", source_project.prompt_lines[0].current_text)
            self.assertEqual([0.01, 0.02], sleeps)

    def test_non_retryable_commit_error_attempts_once_and_cleans(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_project, preview, _image_path = self._materialization_fixture(tmpdir, "Non Retry")
            rename_attempts = []
            sleeps = []

            def non_retryable(_source, _destination):
                rename_attempts.append(True)
                raise OSError("cross-device rename")

            result = materialize_lightweight_fork(
                source_project,
                stored_preview=preview,
                destination_parent_dir=tmpdir,
                fork_name="Non Retry",
                rename=non_retryable,
                sleep=sleeps.append,
                retry_delays=(0, 0.01, 0.02),
            )

            self.assertFalse(result["success"])
            self.assertEqual(1, len(rename_attempts))
            self.assertEqual(1, result["commit_attempts"])
            self.assertFalse(result["commit_retry_performed"])
            self.assertEqual([], sleeps)
            self.assertIn("non-retryable commit error", result["error"])
            self.assertTrue(result["cleanup_performed"])
            self.assertFalse(os.path.exists(result["destination_directory"]))

    def test_destination_conflict_during_retry_never_overwrites_marker(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_project, preview, _image_path = self._materialization_fixture(tmpdir, "Conflict Retry")
            rename_attempts = []
            sleeps = []

            def conflict_after_lock(source, destination):
                rename_attempts.append(True)
                if len(rename_attempts) == 1:
                    os.makedirs(destination)
                    with open(os.path.join(destination, "marker.txt"), "w", encoding="utf-8") as handle:
                        handle.write("keep")
                    raise _win_error(5)
                os.rename(source, destination)

            result = materialize_lightweight_fork(
                source_project,
                stored_preview=preview,
                destination_parent_dir=tmpdir,
                fork_name="Conflict Retry",
                rename=conflict_after_lock,
                sleep=sleeps.append,
                retry_delays=(0, 0.01, 0.02),
            )

            marker = os.path.join(result["destination_directory"], "marker.txt")
            self.assertFalse(result["success"])
            self.assertTrue(result["conflict"])
            self.assertEqual(1, len(rename_attempts))
            with open(marker, "r", encoding="utf-8") as handle:
                self.assertEqual("keep", handle.read())
            self.assertTrue(result["cleanup_performed"])
            self.assertFalse(os.path.exists(result["staging_directory"]))
            self.assertEqual([0.01], sleeps)

    def test_cleanup_retry_succeeds_after_temporary_lock(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_project, preview, _image_path = self._materialization_fixture(tmpdir, "Cleanup Retry")
            cleanup_attempts = []
            sleeps = []

            def failing_commit(_source, _destination):
                raise OSError("commit failed")

            def flaky_rmtree(directory):
                cleanup_attempts.append(True)
                if len(cleanup_attempts) == 1:
                    raise _win_error(5)
                shutil.rmtree(directory)

            result = materialize_lightweight_fork(
                source_project,
                stored_preview=preview,
                destination_parent_dir=tmpdir,
                fork_name="Cleanup Retry",
                rename=failing_commit,
                rmtree=flaky_rmtree,
                sleep=sleeps.append,
                retry_delays=(0, 0.01, 0.02),
            )

            self.assertFalse(result["success"])
            self.assertTrue(result["cleanup_performed"])
            self.assertEqual(2, result["cleanup_attempts"])
            self.assertNotIn("cleanup_error", result)
            self.assertFalse(os.path.exists(result["staging_directory"]))
            self.assertEqual([0.01], sleeps)

    def test_cleanup_retry_exhausted_reports_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_project, preview, image_path = self._materialization_fixture(tmpdir, "Cleanup Exhausted")
            sleeps = []

            def failing_commit(_source, _destination):
                raise OSError("commit failed")

            def always_locked(_directory):
                raise _win_error(32, "Sharing violation")

            result = materialize_lightweight_fork(
                source_project,
                stored_preview=preview,
                destination_parent_dir=tmpdir,
                fork_name="Cleanup Exhausted",
                rename=failing_commit,
                rmtree=always_locked,
                sleep=sleeps.append,
                retry_delays=(0, 0.01, 0.02),
            )

            self.assertFalse(result["success"])
            self.assertFalse(result["cleanup_performed"])
            self.assertEqual(3, result["cleanup_attempts"])
            self.assertIn("cleanup_error", result)
            self.assertTrue(result["retryable_windows_error"])
            self.assertFalse(os.path.exists(result["destination_directory"]))
            self.assertTrue(os.path.exists(result["staging_directory"]))
            self.assertTrue(os.path.isfile(image_path))
            self.assertEqual([0.01, 0.02], sleeps)

    def test_retry_classification_does_not_retry_arbitrary_oserror(self):
        self.assertTrue(_is_retryable_windows_filesystem_error(_win_error(5)))
        self.assertTrue(_is_retryable_windows_filesystem_error(_win_error(32)))
        self.assertFalse(_is_retryable_windows_filesystem_error(OSError("programming error")))

        with tempfile.TemporaryDirectory() as tmpdir:
            staging = os.path.join(tmpdir, "staging")
            final = os.path.join(tmpdir, "final")
            os.makedirs(staging)
            sleeps = []
            result = _commit_directory_with_retry(
                staging,
                final,
                rename=lambda _source, _destination: (_ for _ in ()).throw(OSError("bad rename")),
                path_exists=os.path.exists,
                sleep=sleeps.append,
                retry_delays=(0, 0, 0),
            )
            self.assertFalse(result["success"])
            self.assertEqual(1, result["attempts"])
            self.assertEqual([], sleeps)

            cleanup = _remove_tree_with_retry(
                staging,
                rmtree=shutil.rmtree,
                path_exists=os.path.exists,
                sleep=sleeps.append,
                retry_delays=(0, 0, 0),
            )
            self.assertTrue(cleanup["success"])


if __name__ == "__main__":
    unittest.main()
