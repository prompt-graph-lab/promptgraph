import os
import tempfile
import unittest

from core.lightweight_fork import (
    build_lightweight_fork_preview,
    build_lightweight_fork_preview_signature,
    sanitize_filename,
    sanitize_fork_name,
)
from core.project import PromptLine


def _line(**overrides):
    data = {
        "id": "line_1",
        "original_file_name": "line_1",
        "original_index": 0,
        "current_index": 0,
        "original_text": "prompt",
        "current_text": "prompt",
        "tokens": ["prompt"],
    }
    data.update(overrides)
    return PromptLine(**data)


class LightweightForkPreviewTests(unittest.TestCase):
    def test_main_image_resolution_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            selected_path = os.path.join(tmpdir, "selected.png")
            generated_path = os.path.join(tmpdir, "generated.png")
            image_path = os.path.join(tmpdir, "image.png")
            for path in (selected_path, generated_path, image_path):
                open(path, "wb").close()

            lines = [
                _line(
                    id="selected",
                    selected_candidate_path=selected_path,
                    generated_image_path=generated_path,
                    image_path=image_path,
                ),
                _line(id="generated", generated_image_path=generated_path, image_path=image_path),
                _line(id="image", image_path=image_path),
                _line(id="empty"),
            ]

            preview = build_lightweight_fork_preview(
                lines,
                fork_name="my fork",
                path_exists=os.path.exists,
            )
            entries = {entry["line_id"]: entry for entry in preview["entries"]}

            self.assertEqual("selected_candidate_path", entries["selected"]["source_field"])
            self.assertEqual(selected_path, entries["selected"]["resolved_image_path"])
            self.assertEqual("generated_image_path", entries["generated"]["source_field"])
            self.assertEqual(generated_path, entries["generated"]["resolved_image_path"])
            self.assertEqual("image_path", entries["image"]["source_field"])
            self.assertEqual(image_path, entries["image"]["resolved_image_path"])
            self.assertFalse(entries["empty"]["materializable"])
            self.assertEqual("no resolved final image", entries["empty"]["skipped_reason"])
            self.assertEqual(3, preview["materializable_count"])
            self.assertEqual(1, preview["skipped_count"])

    def test_missing_file_and_excluded_lines_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = os.path.join(tmpdir, "image.png")
            missing_path = os.path.join(tmpdir, "missing.png")
            open(image_path, "wb").close()
            lines = [
                _line(id="route", line_type="separator", separator_label="Route A"),
                _line(id="materializable", image_path=image_path),
                _line(id="missing", image_path=missing_path),
                _line(id="deleted", image_path=image_path, deleted=True),
                _line(id="workbench", image_path=image_path, line_type="workbench"),
            ]

            preview = build_lightweight_fork_preview(lines, path_exists=os.path.exists)
            entries = {entry["line_id"]: entry for entry in preview["entries"]}

            self.assertTrue(entries["materializable"]["materializable"])
            self.assertEqual("Route A", entries["materializable"]["route_label"])
            self.assertEqual("missing resolved image file", entries["missing"]["skipped_reason"])
            self.assertEqual("deleted line", entries["deleted"]["skipped_reason"])
            self.assertEqual("Workbench line", entries["workbench"]["skipped_reason"])
            self.assertEqual(1, preview["materializable_count"])
            self.assertEqual(4, preview["skipped_count"])
            self.assertEqual(1, preview["affected_route_count"])

    def test_target_line_ids_limit_scope(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            first_path = os.path.join(tmpdir, "first.png")
            second_path = os.path.join(tmpdir, "second.png")
            for path in (first_path, second_path):
                open(path, "wb").close()

            preview = build_lightweight_fork_preview(
                [
                    _line(id="first", image_path=first_path),
                    _line(id="second", image_path=second_path),
                ],
                scope="selected_lines",
                target_line_ids=["second"],
                selected_line_ids=["second"],
                path_exists=os.path.exists,
            )

            self.assertEqual(1, preview["materializable_count"])
            self.assertEqual(["second"], [entry["line_id"] for entry in preview["entries"]])
            self.assertEqual(("second",), preview["signature"]["target_line_ids"])
            self.assertEqual(("second",), preview["signature"]["selected_line_ids"])

    def test_empty_target_line_ids_do_not_expand_to_all(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = os.path.join(tmpdir, "image.png")
            open(image_path, "wb").close()

            preview = build_lightweight_fork_preview(
                [_line(id="line", image_path=image_path)],
                scope="selected_lines",
                target_line_ids=[],
                selected_line_ids=[],
                path_exists=os.path.exists,
            )

            self.assertEqual(0, preview["materializable_count"])
            self.assertEqual(0, preview["entry_count"])
            self.assertEqual((), preview["signature"]["target_line_ids"])

    def test_destination_paths_are_sanitized_and_unique_without_creating_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            same_a = os.path.join(tmpdir, "same name.png")
            nested = os.path.join(tmpdir, "nested")
            os.mkdir(nested)
            same_b = os.path.join(nested, "same name.png")
            for path in (same_a, same_b):
                open(path, "wb").close()

            preview = build_lightweight_fork_preview(
                [
                    _line(id="a", image_path=same_a),
                    _line(id="b", image_path=same_b),
                ],
                fork_name="My Fork!",
                path_exists=os.path.exists,
            )
            destinations = [entry["planned_destination_path"] for entry in preview["entries"]]

            self.assertEqual("My_Fork", sanitize_fork_name("My Fork!"))
            self.assertEqual("same_name.png", sanitize_filename("same name.png"))
            self.assertEqual(2, len(set(destinations)))
            self.assertTrue(all(destination.startswith(os.path.join("forks", "My_Fork", "images")) for destination in destinations))
            self.assertFalse(os.path.exists(os.path.join(tmpdir, "forks")))

    def test_preview_is_non_destructive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = os.path.join(tmpdir, "image.png")
            open(image_path, "wb").close()
            line = _line(
                image_path=image_path,
                selected_candidate_path="",
                generated_image_path="",
                generated_candidates=[{"path": "candidate.png"}],
                gallery_variants=[{"path": "variant.png"}],
                current_text="keep prompt",
                negative_prompt="keep negative",
            )
            before_candidates = list(line.generated_candidates)
            before_variants = list(line.gallery_variants)

            build_lightweight_fork_preview([line], path_exists=os.path.exists)

            self.assertEqual(image_path, line.image_path)
            self.assertEqual("", line.selected_candidate_path)
            self.assertEqual("", line.generated_image_path)
            self.assertEqual(before_candidates, line.generated_candidates)
            self.assertEqual(before_variants, line.gallery_variants)
            self.assertEqual("keep prompt", line.current_text)
            self.assertEqual("keep negative", line.negative_prompt)

    def test_signature_changes_when_resolved_destination_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = os.path.join(tmpdir, "image.png")
            open(image_path, "wb").close()
            first_preview = build_lightweight_fork_preview(
                [_line(id="line", image_path=image_path)],
                fork_name="first",
                path_exists=os.path.exists,
            )
            second_preview = build_lightweight_fork_preview(
                [_line(id="line", image_path=image_path)],
                fork_name="second",
                path_exists=os.path.exists,
            )

            self.assertNotEqual(
                build_lightweight_fork_preview_signature(first_preview),
                build_lightweight_fork_preview_signature(second_preview),
            )


if __name__ == "__main__":
    unittest.main()
