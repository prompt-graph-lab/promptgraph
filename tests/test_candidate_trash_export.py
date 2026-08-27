import os
import tempfile
import unittest

from core.io import _selected_final_image_reference
from core.project import Project, PromptLine


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


class CandidateTrashExportTests(unittest.TestCase):
    def test_selected_trashed_candidate_is_skipped_for_final_export(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            trashed_path = os.path.join(tmpdir, "trashed.png")
            fallback_path = os.path.join(tmpdir, "fallback.png")
            open(trashed_path, "wb").close()
            open(fallback_path, "wb").close()

            line = _line(
                selected_candidate_path=trashed_path,
                image_path=fallback_path,
                generated_candidates=[
                    {"path": trashed_path, "trashed": True, "trashed_at": "2026-07-01T00:00:00+00:00"}
                ],
            )
            project = Project(prompt_lines=[line])

            reference = _selected_final_image_reference(project, line)

            self.assertEqual(os.path.abspath(fallback_path), reference["path"])
            self.assertEqual("image_path", reference["field"])

    def test_untrashed_selected_candidate_remains_final_export_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            selected_path = os.path.join(tmpdir, "selected.png")
            fallback_path = os.path.join(tmpdir, "fallback.png")
            open(selected_path, "wb").close()
            open(fallback_path, "wb").close()

            line = _line(
                selected_candidate_path=selected_path,
                image_path=fallback_path,
                generated_candidates=[{"path": selected_path}],
            )
            project = Project(prompt_lines=[line])

            reference = _selected_final_image_reference(project, line)

            self.assertEqual(os.path.abspath(selected_path), reference["path"])
            self.assertEqual("selected_candidate_path", reference["field"])

    def test_image_path_matching_trashed_candidate_is_skipped_for_final_export(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            trashed_path = os.path.join(tmpdir, "trashed_reference.png")
            open(trashed_path, "wb").close()

            line = _line(
                image_path=trashed_path,
                generated_candidates=[
                    {"path": trashed_path, "trashed": True, "trashed_at": "2026-07-01T00:00:00+00:00"}
                ],
            )
            project = Project(prompt_lines=[line])

            reference = _selected_final_image_reference(project, line)

            self.assertEqual({}, reference)


if __name__ == "__main__":
    unittest.main()
