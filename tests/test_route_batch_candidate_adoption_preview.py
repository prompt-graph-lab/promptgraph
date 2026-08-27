import os
import tempfile
import unittest

from core.project import PromptLine
from core.route_batch_candidate_adoption import (
    APPLY_SUPPORTED_SCOPES,
    GALLERY_VARIANT_PREVIEW_SOURCE,
    apply_route_batch_candidate_adoption_preview,
    build_route_batch_adoption_preview_signature,
    build_route_batch_candidate_adoption_preview,
    is_route_batch_adoption_apply_button_enabled,
    is_route_batch_adoption_apply_supported,
)


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


def _variant(path="", **overrides):
    record = {
        "id": "variant_test",
        "kind": "gallery_variant",
        "path": path,
    }
    record.update(overrides)
    return record


class RouteBatchCandidateAdoptionPreviewTests(unittest.TestCase):
    def test_apply_supported_scopes_include_selected_route_but_not_all(self):
        self.assertIn("selected_lines", APPLY_SUPPORTED_SCOPES)
        self.assertIn("current_route", APPLY_SUPPORTED_SCOPES)
        self.assertIn("selected_route", APPLY_SUPPORTED_SCOPES)
        self.assertNotIn("all_lines", APPLY_SUPPORTED_SCOPES)

    def test_apply_source_scope_policy(self):
        self.assertTrue(is_route_batch_adoption_apply_supported("selected_lines", "latest"))
        self.assertTrue(is_route_batch_adoption_apply_supported("current_route", "latest"))
        self.assertTrue(is_route_batch_adoption_apply_supported("selected_route", "latest"))
        self.assertTrue(is_route_batch_adoption_apply_supported("all_lines", "latest"))
        self.assertTrue(is_route_batch_adoption_apply_supported("selected_lines", "first"))
        self.assertTrue(is_route_batch_adoption_apply_supported("current_route", "first"))
        self.assertTrue(is_route_batch_adoption_apply_supported("selected_route", "first"))
        self.assertTrue(is_route_batch_adoption_apply_supported("all_lines", "first"))
        self.assertTrue(is_route_batch_adoption_apply_supported("selected_lines", GALLERY_VARIANT_PREVIEW_SOURCE))
        self.assertTrue(is_route_batch_adoption_apply_supported("current_route", GALLERY_VARIANT_PREVIEW_SOURCE))
        self.assertTrue(is_route_batch_adoption_apply_supported("selected_route", GALLERY_VARIANT_PREVIEW_SOURCE))
        self.assertTrue(is_route_batch_adoption_apply_supported("all_lines", GALLERY_VARIANT_PREVIEW_SOURCE))
        self.assertFalse(is_route_batch_adoption_apply_supported("selected_lines", "unknown_source"))
        self.assertFalse(is_route_batch_adoption_apply_supported("all_lines", "unknown_source"))
        self.assertFalse(is_route_batch_adoption_apply_supported("unknown_scope", "latest"))

    def test_apply_button_enabled_policy_for_all_scope(self):
        self.assertTrue(
            is_route_batch_adoption_apply_button_enabled(
                scope="all_lines",
                source="latest",
                preview_current=True,
                will_adopt_count=1,
                confirmed=True,
                all_confirm_phrase=" APPLY ALL ",
            )
        )
        self.assertTrue(
            is_route_batch_adoption_apply_button_enabled(
                scope="all_lines",
                source="first",
                preview_current=True,
                will_adopt_count=1,
                confirmed=True,
                all_confirm_phrase="APPLY ALL",
            )
        )
        self.assertFalse(
            is_route_batch_adoption_apply_button_enabled(
                scope="all_lines",
                source="latest",
                preview_current=True,
                will_adopt_count=1,
                confirmed=True,
                all_confirm_phrase="apply all",
            )
        )
        self.assertTrue(
            is_route_batch_adoption_apply_button_enabled(
                scope="all_lines",
                source=GALLERY_VARIANT_PREVIEW_SOURCE,
                preview_current=True,
                will_adopt_count=1,
                confirmed=True,
                all_confirm_phrase="APPLY ALL",
            )
        )
        self.assertFalse(
            is_route_batch_adoption_apply_button_enabled(
                scope="all_lines",
                source=GALLERY_VARIANT_PREVIEW_SOURCE,
                preview_current=True,
                will_adopt_count=1,
                confirmed=True,
                all_confirm_phrase="APPLY-ALL",
            )
        )
        self.assertFalse(
            is_route_batch_adoption_apply_button_enabled(
                scope="all_lines",
                source="latest",
                preview_current=False,
                will_adopt_count=1,
                confirmed=True,
                all_confirm_phrase="APPLY ALL",
            )
        )
        self.assertFalse(
            is_route_batch_adoption_apply_button_enabled(
                scope="all_lines",
                source="latest",
                preview_current=True,
                will_adopt_count=0,
                confirmed=True,
                all_confirm_phrase="APPLY ALL",
            )
        )
        self.assertFalse(
            is_route_batch_adoption_apply_button_enabled(
                scope="all_lines",
                source="latest",
                preview_current=True,
                will_adopt_count=1,
                confirmed=False,
                all_confirm_phrase="APPLY ALL",
            )
        )
        self.assertTrue(
            is_route_batch_adoption_apply_button_enabled(
                scope="selected_route",
                source=GALLERY_VARIANT_PREVIEW_SOURCE,
                preview_current=True,
                will_adopt_count=1,
                confirmed=True,
            )
        )

    def test_all_scope_preview_signature_tracks_target_lines(self):
        signature = build_route_batch_adoption_preview_signature(
            source="latest",
            scope="all_lines",
            all_scope_line_ids=["line_1", "line_2"],
        )
        self.assertEqual(("line_1", "line_2"), signature["all_scope_line_ids"])
        self.assertEqual(2, signature["all_scope_line_count"])

        changed_signature = build_route_batch_adoption_preview_signature(
            source="latest",
            scope="all_lines",
            all_scope_line_ids=["line_1", "line_2", "line_3"],
        )
        self.assertNotEqual(signature, changed_signature)

    def test_non_all_scope_preview_signature_shape_is_unchanged(self):
        signature = build_route_batch_adoption_preview_signature(
            source="latest",
            scope="selected_route",
            selected_route_id="route_1",
            current_route_anchor_id="",
            selected_line_ids=["line_1", "line_2"],
            all_scope_line_ids=["line_1", "line_2", "line_3"],
        )
        self.assertEqual("latest", signature["source"])
        self.assertEqual("selected_route", signature["scope"])
        self.assertEqual("route_1", signature["selected_route_id"])
        self.assertEqual(("line_1", "line_2"), signature["selected_line_ids"])
        self.assertNotIn("all_scope_line_ids", signature)
        self.assertNotIn("all_scope_line_count", signature)

    def test_latest_active_candidate_becomes_swap_preview(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            main_path = os.path.join(tmpdir, "main.png")
            old_candidate_path = os.path.join(tmpdir, "old.png")
            latest_path = os.path.join(tmpdir, "latest.png")
            for path in (main_path, old_candidate_path, latest_path):
                open(path, "wb").close()

            line = _line(
                image_path=main_path,
                generated_candidates=[
                    {"path": old_candidate_path},
                    {"path": latest_path},
                ],
            )

            preview = build_route_batch_candidate_adoption_preview(
                [line],
                source="latest",
                path_exists=os.path.exists,
            )

            self.assertEqual(1, preview["will_adopt_count"])
            self.assertEqual(1, preview["swap_with_retreat_count"])
            self.assertEqual("swap_with_retreat", preview["entries"][0]["operation"])
            self.assertEqual(latest_path, preview["entries"][0]["after_image_path"])

    def test_trashed_candidate_is_excluded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            candidate_path = os.path.join(tmpdir, "trashed.png")
            open(candidate_path, "wb").close()

            line = _line(generated_candidates=[{"path": candidate_path, "trashed": True}])

            preview = build_route_batch_candidate_adoption_preview(
                [line],
                source="latest",
                path_exists=os.path.exists,
            )

            self.assertEqual(0, preview["will_adopt_count"])
            self.assertEqual(1, preview["skipped_count"])
            self.assertEqual("trashed candidate only", preview["entries"][0]["skip_reason"])

    def test_no_op_when_candidate_is_current_main(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            candidate_path = os.path.join(tmpdir, "same.png")
            open(candidate_path, "wb").close()

            line = _line(
                selected_candidate_path=candidate_path,
                generated_candidates=[{"path": candidate_path}],
            )

            preview = build_route_batch_candidate_adoption_preview(
                [line],
                source="latest",
                path_exists=os.path.exists,
            )

            self.assertEqual(0, preview["will_adopt_count"])
            self.assertEqual(1, preview["skipped_count"])
            self.assertEqual("no_op", preview["entries"][0]["operation"])
            self.assertEqual("already adopted / no-op", preview["entries"][0]["skip_reason"])

    def test_image_less_line_with_candidate_is_first_main_image(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            candidate_path = os.path.join(tmpdir, "candidate.png")
            open(candidate_path, "wb").close()

            line = _line(generated_candidates=[{"path": candidate_path}])

            preview = build_route_batch_candidate_adoption_preview(
                [line],
                source="first",
                path_exists=os.path.exists,
            )

            self.assertEqual(1, preview["will_adopt_count"])
            self.assertEqual(1, preview["first_main_image_count"])
            self.assertEqual("first_main_image", preview["entries"][0]["operation"])

    def test_route_separator_deleted_and_workbench_are_skipped(self):
        lines = [
            _line(id="separator", line_type="separator"),
            _line(id="deleted", deleted=True),
            _line(id="workbench", line_type="workbench"),
        ]

        preview = build_route_batch_candidate_adoption_preview(lines)

        self.assertEqual(0, preview["will_adopt_count"])
        self.assertEqual(3, preview["skipped_count"])
        self.assertEqual(
            ["Route separator", "deleted line", "Workbench line"],
            [entry["skip_reason"] for entry in preview["entries"]],
        )

    def test_latest_gallery_variant_becomes_preview_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            main_path = os.path.join(tmpdir, "main.png")
            first_variant_path = os.path.join(tmpdir, "variant-first.png")
            latest_variant_path = os.path.join(tmpdir, "variant-latest.png")
            for path in (main_path, first_variant_path, latest_variant_path):
                open(path, "wb").close()

            line = _line(
                image_path=main_path,
                gallery_variants=[
                    _variant(first_variant_path, id="variant_first"),
                    _variant(latest_variant_path, id="variant_latest"),
                ],
            )

            preview = build_route_batch_candidate_adoption_preview(
                [line],
                source=GALLERY_VARIANT_PREVIEW_SOURCE,
                path_exists=os.path.exists,
            )

            self.assertEqual(1, preview["will_adopt_count"])
            self.assertEqual("swap_with_retreat", preview["entries"][0]["operation"])
            self.assertEqual(latest_variant_path, preview["entries"][0]["after_image_path"])
            self.assertEqual("latest_gallery_variant", preview["entries"][0]["adoption_source"])

    def test_gallery_variant_preview_skips_missing_empty_path_and_missing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_path = os.path.join(tmpdir, "missing.png")
            pathless_line = _line(gallery_variants=[_variant("")])
            empty_line = _line(gallery_variants=[])
            missing_file_line = _line(gallery_variants=[_variant(missing_path)])

            preview = build_route_batch_candidate_adoption_preview(
                [pathless_line, empty_line, missing_file_line],
                source=GALLERY_VARIANT_PREVIEW_SOURCE,
                path_exists=os.path.exists,
            )

            self.assertEqual(0, preview["will_adopt_count"])
            self.assertEqual(
                [
                    "gallery variant target not found",
                    "gallery variant target not found",
                    "missing gallery variant file",
                ],
                [entry["skip_reason"] for entry in preview["entries"]],
            )

    def test_gallery_variant_preview_ignores_non_appended_and_trashed_variants(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            variant_path = os.path.join(tmpdir, "variant.png")
            open(variant_path, "wb").close()
            non_appended_line = _line(
                gallery_variants=[{"id": "manual_record", "source": "manual", "path": variant_path}]
            )
            trashed_line = _line(gallery_variants=[_variant(variant_path, trashed=True)])

            preview = build_route_batch_candidate_adoption_preview(
                [non_appended_line, trashed_line],
                source=GALLERY_VARIANT_PREVIEW_SOURCE,
                path_exists=os.path.exists,
            )

            self.assertEqual(0, preview["will_adopt_count"])
            self.assertEqual(
                ["gallery variant target not found", "gallery variant target not found"],
                [entry["skip_reason"] for entry in preview["entries"]],
            )

    def test_gallery_variant_preview_no_op_when_variant_is_current_main(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            variant_path = os.path.join(tmpdir, "variant.png")
            open(variant_path, "wb").close()

            line = _line(
                selected_candidate_path=variant_path,
                gallery_variants=[_variant(variant_path)],
            )

            preview = build_route_batch_candidate_adoption_preview(
                [line],
                source=GALLERY_VARIANT_PREVIEW_SOURCE,
                path_exists=os.path.exists,
            )

            self.assertEqual(0, preview["will_adopt_count"])
            self.assertEqual("no_op", preview["entries"][0]["operation"])
            self.assertEqual("already adopted / no-op", preview["entries"][0]["skip_reason"])

    def test_gallery_variant_preview_handles_first_main_and_swap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            main_path = os.path.join(tmpdir, "main.png")
            first_variant_path = os.path.join(tmpdir, "first-main-variant.png")
            swap_variant_path = os.path.join(tmpdir, "swap-variant.png")
            for path in (main_path, first_variant_path, swap_variant_path):
                open(path, "wb").close()

            first_line = _line(
                id="variant_first_main",
                gallery_variants=[_variant(first_variant_path)],
            )
            swap_line = _line(
                id="variant_swap",
                image_path=main_path,
                gallery_variants=[_variant(swap_variant_path)],
            )

            preview = build_route_batch_candidate_adoption_preview(
                [first_line, swap_line],
                source=GALLERY_VARIANT_PREVIEW_SOURCE,
                path_exists=os.path.exists,
            )

            self.assertEqual(2, preview["will_adopt_count"])
            self.assertEqual(1, preview["first_main_image_count"])
            self.assertEqual(1, preview["swap_with_retreat_count"])
            self.assertEqual(
                ["first_main_image", "swap_with_retreat"],
                [entry["operation"] for entry in preview["entries"]],
            )

    def test_gallery_variant_preview_keeps_exclusion_skips(self):
        lines = [
            _line(id="separator", line_type="separator", gallery_variants=[_variant("variant.png")]),
            _line(id="deleted", deleted=True, gallery_variants=[_variant("variant.png")]),
            _line(id="workbench", line_type="workbench", gallery_variants=[_variant("variant.png")]),
        ]

        preview = build_route_batch_candidate_adoption_preview(
            lines,
            source=GALLERY_VARIANT_PREVIEW_SOURCE,
        )

        self.assertEqual(0, preview["will_adopt_count"])
        self.assertEqual(
            ["Route separator", "deleted line", "Workbench line"],
            [entry["skip_reason"] for entry in preview["entries"]],
        )

    def test_apply_selected_lines_latest_candidate_retreats_previous_main(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = os.path.join(tmpdir, "source.png")
            generated_path = os.path.join(tmpdir, "generated.png")
            candidate_path = os.path.join(tmpdir, "candidate.png")
            for path in (image_path, generated_path, candidate_path):
                open(path, "wb").close()

            line = _line(
                id="line_apply",
                image_path=image_path,
                generated_image_path=generated_path,
                current_text="keep positive",
                negative_prompt="keep negative",
                generated_candidates=[{"path": candidate_path}],
            )

            result = apply_route_batch_candidate_adoption_preview(
                [line],
                scope="selected_lines",
                source="latest",
                path_exists=os.path.exists,
                now="2026-07-07T00:00:00+00:00",
            )

            self.assertEqual(1, result["applied_count"])
            self.assertEqual(1, result["swap_with_retreat_count"])
            self.assertEqual(candidate_path, line.selected_candidate_path)
            self.assertEqual(generated_path, line.generated_image_path)
            self.assertEqual(image_path, line.image_path)
            self.assertEqual("keep positive", line.current_text)
            self.assertEqual("keep negative", line.negative_prompt)
            retreat_records = [
                candidate
                for candidate in line.generated_candidates
                if candidate.get("path") == generated_path
            ]
            self.assertEqual(1, len(retreat_records))
            self.assertEqual(
                "route_batch_candidate_adoption_retreat",
                retreat_records[0].get("source"),
            )
            self.assertEqual(
                "generated_image_path",
                retreat_records[0].get("previous_main_image_field"),
            )
            adopted_record = next(
                candidate
                for candidate in line.generated_candidates
                if candidate.get("path") == candidate_path
            )
            self.assertEqual(
                "route_batch_candidate_adoption",
                adopted_record.get("adoption_mode"),
            )

    def test_apply_current_route_multiple_lines_and_first_main_image(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            first_candidate_path = os.path.join(tmpdir, "first.png")
            second_candidate_path = os.path.join(tmpdir, "second.png")
            for path in (first_candidate_path, second_candidate_path):
                open(path, "wb").close()

            first_line = _line(
                id="line_first",
                generated_candidates=[{"path": first_candidate_path}],
            )
            second_line = _line(
                id="line_second",
                generated_candidates=[{"path": second_candidate_path}],
            )

            result = apply_route_batch_candidate_adoption_preview(
                [first_line, second_line],
                scope="current_route",
                source="latest",
                path_exists=os.path.exists,
                now="2026-07-07T00:00:00+00:00",
            )

            self.assertEqual(2, result["applied_count"])
            self.assertEqual(2, result["first_main_image_count"])
            self.assertEqual(first_candidate_path, first_line.selected_candidate_path)
            self.assertEqual(second_candidate_path, second_line.selected_candidate_path)
            self.assertEqual(
                [
                    {
                        "path": first_candidate_path,
                        "adoption_mode": "route_batch_candidate_adoption",
                        "batch_adopted_to_main_at": "2026-07-07T00:00:00+00:00",
                    }
                ],
                first_line.generated_candidates,
            )
            self.assertEqual(
                [
                    {
                        "path": second_candidate_path,
                        "adoption_mode": "route_batch_candidate_adoption",
                        "batch_adopted_to_main_at": "2026-07-07T00:00:00+00:00",
                    }
                ],
                second_line.generated_candidates,
            )

    def test_apply_skips_trashed_missing_and_no_op_candidates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_path = os.path.join(tmpdir, "missing.png")
            trashed_path = os.path.join(tmpdir, "trashed.png")
            adopted_path = os.path.join(tmpdir, "adopted.png")
            for path in (trashed_path, adopted_path):
                open(path, "wb").close()

            trashed_line = _line(
                id="line_trashed",
                generated_candidates=[{"path": trashed_path, "trashed": True}],
            )
            missing_line = _line(
                id="line_missing",
                generated_candidates=[{"path": missing_path}],
            )
            no_op_line = _line(
                id="line_no_op",
                selected_candidate_path=adopted_path,
                generated_candidates=[{"path": adopted_path}],
            )

            result = apply_route_batch_candidate_adoption_preview(
                [trashed_line, missing_line, no_op_line],
                scope="selected_lines",
                source="latest",
                path_exists=os.path.exists,
            )

            self.assertEqual(0, result["applied_count"])
            self.assertEqual(3, result["skipped_count"])
            self.assertIn("trashed candidate only", result["skipped_reasons"])
            self.assertIn("missing candidate file", result["skipped_reasons"])
            self.assertIn("already adopted / no-op", result["skipped_reasons"])
            self.assertFalse(getattr(trashed_line, "selected_candidate_path", ""))
            self.assertFalse(getattr(missing_line, "selected_candidate_path", ""))
            self.assertEqual(adopted_path, no_op_line.selected_candidate_path)

    def test_apply_does_not_duplicate_existing_retreat_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            main_path = os.path.join(tmpdir, "main.png")
            candidate_path = os.path.join(tmpdir, "candidate.png")
            for path in (main_path, candidate_path):
                open(path, "wb").close()

            line = _line(
                image_path=main_path,
                generated_candidates=[
                    {"path": main_path, "source": "existing"},
                    {"path": candidate_path},
                ],
            )

            result = apply_route_batch_candidate_adoption_preview(
                [line],
                scope="selected_lines",
                source="latest",
                path_exists=os.path.exists,
            )

            self.assertEqual(1, result["applied_count"])
            self.assertEqual(
                1,
                len(
                    [
                        candidate
                        for candidate in line.generated_candidates
                        if candidate.get("path") == main_path
                    ]
                ),
            )

    def test_apply_selected_route_multiple_lines_with_retreat_and_skips(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            route_main_path = os.path.join(tmpdir, "route-main.png")
            route_generated_path = os.path.join(tmpdir, "route-generated.png")
            route_candidate_path = os.path.join(tmpdir, "route-candidate.png")
            image_less_candidate_path = os.path.join(tmpdir, "image-less-candidate.png")
            trashed_path = os.path.join(tmpdir, "trashed.png")
            no_op_path = os.path.join(tmpdir, "no-op.png")
            missing_path = os.path.join(tmpdir, "missing.png")
            for path in (
                route_main_path,
                route_generated_path,
                route_candidate_path,
                image_less_candidate_path,
                trashed_path,
                no_op_path,
            ):
                open(path, "wb").close()

            swap_line = _line(
                id="selected_route_swap",
                image_path=route_main_path,
                generated_image_path=route_generated_path,
                current_text="keep route prompt",
                negative_prompt="keep route negative",
                generated_candidates=[{"path": route_candidate_path}],
            )
            image_less_line = _line(
                id="selected_route_first",
                generated_candidates=[{"path": image_less_candidate_path}],
            )
            trashed_line = _line(
                id="selected_route_trashed",
                generated_candidates=[{"path": trashed_path, "trashed": True}],
            )
            missing_line = _line(
                id="selected_route_missing",
                generated_candidates=[{"path": missing_path}],
            )
            no_op_line = _line(
                id="selected_route_no_op",
                selected_candidate_path=no_op_path,
                generated_candidates=[{"path": no_op_path}],
            )

            result = apply_route_batch_candidate_adoption_preview(
                [swap_line, image_less_line, trashed_line, missing_line, no_op_line],
                scope="selected_route",
                source="latest",
                path_exists=os.path.exists,
                now="2026-07-07T00:00:00+00:00",
            )

            self.assertEqual(2, result["applied_count"])
            self.assertEqual(1, result["swap_with_retreat_count"])
            self.assertEqual(1, result["first_main_image_count"])
            self.assertEqual(3, result["skipped_count"])
            self.assertEqual("", result["unsupported_scope"])
            self.assertEqual(route_candidate_path, swap_line.selected_candidate_path)
            self.assertEqual(route_generated_path, swap_line.generated_image_path)
            self.assertEqual(route_main_path, swap_line.image_path)
            self.assertEqual("keep route prompt", swap_line.current_text)
            self.assertEqual("keep route negative", swap_line.negative_prompt)
            self.assertEqual(image_less_candidate_path, image_less_line.selected_candidate_path)
            self.assertFalse(getattr(image_less_line, "generated_image_path", ""))
            retreat_records = [
                candidate
                for candidate in swap_line.generated_candidates
                if candidate.get("path") == route_generated_path
            ]
            self.assertEqual(1, len(retreat_records))
            self.assertEqual(
                "route_batch_candidate_adoption_retreat",
                retreat_records[0].get("source"),
            )
            self.assertIn("trashed candidate only", result["skipped_reasons"])
            self.assertIn("missing candidate file", result["skipped_reasons"])
            self.assertIn("already adopted / no-op", result["skipped_reasons"])

    def test_apply_selected_route_does_not_duplicate_existing_retreat_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            main_path = os.path.join(tmpdir, "main.png")
            candidate_path = os.path.join(tmpdir, "candidate.png")
            for path in (main_path, candidate_path):
                open(path, "wb").close()

            line = _line(
                image_path=main_path,
                generated_candidates=[
                    {"path": main_path, "source": "existing"},
                    {"path": candidate_path},
                ],
            )

            result = apply_route_batch_candidate_adoption_preview(
                [line],
                scope="selected_route",
                source="latest",
                path_exists=os.path.exists,
            )

            self.assertEqual(1, result["applied_count"])
            self.assertEqual(
                1,
                len(
                    [
                        candidate
                        for candidate in line.generated_candidates
                        if candidate.get("path") == main_path
                    ]
                ),
            )

    def test_apply_selected_lines_gallery_variant_updates_reference_without_mutating_variant(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = os.path.join(tmpdir, "source.png")
            generated_path = os.path.join(tmpdir, "generated.png")
            variant_path = os.path.join(tmpdir, "variant.png")
            for path in (image_path, generated_path, variant_path):
                open(path, "wb").close()

            variant_record = _variant(variant_path, id="variant_apply")
            line = _line(
                id="line_variant_apply",
                image_path=image_path,
                generated_image_path=generated_path,
                current_text="keep variant prompt",
                negative_prompt="keep variant negative",
                generated_candidates=[{"path": "existing-candidate.png"}],
                gallery_variants=[dict(variant_record)],
            )
            before_variants = [dict(variant) for variant in line.gallery_variants]

            result = apply_route_batch_candidate_adoption_preview(
                [line],
                scope="selected_lines",
                source=GALLERY_VARIANT_PREVIEW_SOURCE,
                path_exists=os.path.exists,
                now="2026-07-07T00:00:00+00:00",
            )

            self.assertEqual(1, result["applied_count"])
            self.assertEqual(1, result["swap_with_retreat_count"])
            self.assertEqual(variant_path, line.selected_candidate_path)
            self.assertEqual(generated_path, line.generated_image_path)
            self.assertEqual(image_path, line.image_path)
            self.assertEqual("keep variant prompt", line.current_text)
            self.assertEqual("keep variant negative", line.negative_prompt)
            self.assertEqual(before_variants, line.gallery_variants)
            self.assertFalse(
                any(candidate.get("path") == variant_path for candidate in line.generated_candidates)
            )
            retreat_records = [
                candidate
                for candidate in line.generated_candidates
                if candidate.get("path") == generated_path
            ]
            self.assertEqual(1, len(retreat_records))
            self.assertEqual("route_batch_candidate_adoption_retreat", retreat_records[0].get("source"))

    def test_apply_selected_lines_gallery_variant_first_main_image(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            variant_path = os.path.join(tmpdir, "variant.png")
            open(variant_path, "wb").close()

            line = _line(gallery_variants=[_variant(variant_path)])
            before_variants = [dict(variant) for variant in line.gallery_variants]

            result = apply_route_batch_candidate_adoption_preview(
                [line],
                scope="selected_lines",
                source=GALLERY_VARIANT_PREVIEW_SOURCE,
                path_exists=os.path.exists,
            )

            self.assertEqual(1, result["applied_count"])
            self.assertEqual(1, result["first_main_image_count"])
            self.assertEqual(variant_path, line.selected_candidate_path)
            self.assertEqual(before_variants, line.gallery_variants)
            self.assertFalse(line.generated_candidates)

    def test_apply_selected_lines_gallery_variant_skips_missing_not_found_and_no_op(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_path = os.path.join(tmpdir, "missing.png")
            adopted_path = os.path.join(tmpdir, "adopted.png")
            open(adopted_path, "wb").close()

            missing_line = _line(gallery_variants=[_variant(missing_path)])
            not_found_line = _line(gallery_variants=[])
            no_op_line = _line(
                selected_candidate_path=adopted_path,
                gallery_variants=[_variant(adopted_path)],
            )

            result = apply_route_batch_candidate_adoption_preview(
                [missing_line, not_found_line, no_op_line],
                scope="selected_lines",
                source=GALLERY_VARIANT_PREVIEW_SOURCE,
                path_exists=os.path.exists,
            )

            self.assertEqual(0, result["applied_count"])
            self.assertEqual(3, result["skipped_count"])
            self.assertIn("missing gallery variant file", result["skipped_reasons"])
            self.assertIn("gallery variant target not found", result["skipped_reasons"])
            self.assertIn("already adopted / no-op", result["skipped_reasons"])

    def test_apply_selected_lines_gallery_variant_skips_excluded_lines(self):
        lines = [
            _line(id="separator", line_type="separator", gallery_variants=[_variant("variant.png")]),
            _line(id="deleted", deleted=True, gallery_variants=[_variant("variant.png")]),
            _line(id="workbench", line_type="workbench", gallery_variants=[_variant("variant.png")]),
        ]

        result = apply_route_batch_candidate_adoption_preview(
            lines,
            scope="selected_lines",
            source=GALLERY_VARIANT_PREVIEW_SOURCE,
        )

        self.assertEqual(0, result["applied_count"])
        self.assertEqual(3, result["skipped_count"])
        self.assertIn("Route separator", result["skipped_reasons"])
        self.assertIn("deleted line", result["skipped_reasons"])
        self.assertIn("Workbench line", result["skipped_reasons"])

    def test_apply_selected_lines_gallery_variant_does_not_duplicate_retreat(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            main_path = os.path.join(tmpdir, "main.png")
            variant_path = os.path.join(tmpdir, "variant.png")
            for path in (main_path, variant_path):
                open(path, "wb").close()

            line = _line(
                image_path=main_path,
                generated_candidates=[{"path": main_path, "source": "existing"}],
                gallery_variants=[_variant(variant_path)],
            )

            result = apply_route_batch_candidate_adoption_preview(
                [line],
                scope="selected_lines",
                source=GALLERY_VARIANT_PREVIEW_SOURCE,
                path_exists=os.path.exists,
            )

            self.assertEqual(1, result["applied_count"])
            self.assertEqual(
                1,
                len(
                    [
                        candidate
                        for candidate in line.generated_candidates
                        if candidate.get("path") == main_path
                    ]
                ),
            )
            self.assertFalse(
                any(candidate.get("path") == variant_path for candidate in line.generated_candidates)
            )

    def test_apply_selected_lines_gallery_variant_does_not_mutate_existing_matching_candidate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            variant_path = os.path.join(tmpdir, "variant.png")
            open(variant_path, "wb").close()

            existing_candidate = {"path": variant_path, "source": "existing_candidate"}
            line = _line(
                generated_candidates=[dict(existing_candidate)],
                gallery_variants=[_variant(variant_path)],
            )

            result = apply_route_batch_candidate_adoption_preview(
                [line],
                scope="selected_lines",
                source=GALLERY_VARIANT_PREVIEW_SOURCE,
                path_exists=os.path.exists,
            )

            self.assertEqual(1, result["applied_count"])
            self.assertEqual(variant_path, line.selected_candidate_path)
            self.assertEqual([existing_candidate], line.generated_candidates)

    def test_apply_current_route_gallery_variant_multiple_lines_and_skips(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = os.path.join(tmpdir, "source.png")
            generated_path = os.path.join(tmpdir, "generated.png")
            swap_variant_path = os.path.join(tmpdir, "swap-variant.png")
            first_variant_path = os.path.join(tmpdir, "first-variant.png")
            missing_variant_path = os.path.join(tmpdir, "missing-variant.png")
            no_op_variant_path = os.path.join(tmpdir, "no-op-variant.png")
            for path in (
                image_path,
                generated_path,
                swap_variant_path,
                first_variant_path,
                no_op_variant_path,
            ):
                open(path, "wb").close()

            swap_variant = _variant(swap_variant_path, id="variant_current_route_swap")
            first_variant = _variant(first_variant_path, id="variant_current_route_first")
            swap_line = _line(
                id="current_route_swap",
                image_path=image_path,
                generated_image_path=generated_path,
                current_text="keep current route prompt",
                negative_prompt="keep current route negative",
                generated_candidates=[{"path": "existing-candidate.png"}],
                gallery_variants=[dict(swap_variant)],
            )
            first_line = _line(
                id="current_route_first",
                gallery_variants=[dict(first_variant)],
            )
            missing_line = _line(
                id="current_route_missing",
                gallery_variants=[_variant(missing_variant_path)],
            )
            not_found_line = _line(
                id="current_route_not_found",
                gallery_variants=[],
            )
            no_op_line = _line(
                id="current_route_no_op",
                selected_candidate_path=no_op_variant_path,
                gallery_variants=[_variant(no_op_variant_path)],
            )
            skipped_lines = [
                _line(id="separator", line_type="separator", gallery_variants=[_variant(swap_variant_path)]),
                _line(id="deleted", deleted=True, gallery_variants=[_variant(swap_variant_path)]),
                _line(id="workbench", line_type="workbench", gallery_variants=[_variant(swap_variant_path)]),
            ]
            before_swap_variants = [dict(variant) for variant in swap_line.gallery_variants]
            before_first_variants = [dict(variant) for variant in first_line.gallery_variants]

            result = apply_route_batch_candidate_adoption_preview(
                [
                    swap_line,
                    first_line,
                    missing_line,
                    not_found_line,
                    no_op_line,
                    *skipped_lines,
                ],
                scope="current_route",
                source=GALLERY_VARIANT_PREVIEW_SOURCE,
                path_exists=os.path.exists,
                now="2026-07-07T00:00:00+00:00",
            )

            self.assertEqual(2, result["applied_count"])
            self.assertEqual(1, result["swap_with_retreat_count"])
            self.assertEqual(1, result["first_main_image_count"])
            self.assertEqual(6, result["skipped_count"])
            self.assertEqual(swap_variant_path, swap_line.selected_candidate_path)
            self.assertEqual(generated_path, swap_line.generated_image_path)
            self.assertEqual(image_path, swap_line.image_path)
            self.assertEqual("keep current route prompt", swap_line.current_text)
            self.assertEqual("keep current route negative", swap_line.negative_prompt)
            self.assertEqual(first_variant_path, first_line.selected_candidate_path)
            self.assertEqual(before_swap_variants, swap_line.gallery_variants)
            self.assertEqual(before_first_variants, first_line.gallery_variants)
            self.assertFalse(
                any(candidate.get("path") == swap_variant_path for candidate in swap_line.generated_candidates)
            )
            retreat_records = [
                candidate
                for candidate in swap_line.generated_candidates
                if candidate.get("path") == generated_path
            ]
            self.assertEqual(1, len(retreat_records))
            self.assertEqual("route_batch_candidate_adoption_retreat", retreat_records[0].get("source"))
            self.assertFalse(first_line.generated_candidates)
            self.assertIn("missing gallery variant file", result["skipped_reasons"])
            self.assertIn("gallery variant target not found", result["skipped_reasons"])
            self.assertIn("already adopted / no-op", result["skipped_reasons"])
            self.assertIn("Route separator", result["skipped_reasons"])
            self.assertIn("deleted line", result["skipped_reasons"])
            self.assertIn("Workbench line", result["skipped_reasons"])

    def test_apply_current_route_gallery_variant_does_not_duplicate_retreat(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            main_path = os.path.join(tmpdir, "main.png")
            variant_path = os.path.join(tmpdir, "variant.png")
            for path in (main_path, variant_path):
                open(path, "wb").close()

            line = _line(
                image_path=main_path,
                generated_candidates=[{"path": main_path, "source": "existing"}],
                gallery_variants=[_variant(variant_path)],
            )

            result = apply_route_batch_candidate_adoption_preview(
                [line],
                scope="current_route",
                source=GALLERY_VARIANT_PREVIEW_SOURCE,
                path_exists=os.path.exists,
            )

            self.assertEqual(1, result["applied_count"])
            self.assertEqual(
                1,
                len(
                    [
                        candidate
                        for candidate in line.generated_candidates
                        if candidate.get("path") == main_path
                    ]
                ),
            )
            self.assertFalse(
                any(candidate.get("path") == variant_path for candidate in line.generated_candidates)
            )

    def test_apply_selected_route_gallery_variant_multiple_lines_and_skips(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = os.path.join(tmpdir, "selected-route-source.png")
            generated_path = os.path.join(tmpdir, "selected-route-generated.png")
            swap_variant_path = os.path.join(tmpdir, "selected-route-swap-variant.png")
            first_variant_path = os.path.join(tmpdir, "selected-route-first-variant.png")
            missing_variant_path = os.path.join(tmpdir, "selected-route-missing-variant.png")
            no_op_variant_path = os.path.join(tmpdir, "selected-route-no-op-variant.png")
            for path in (
                image_path,
                generated_path,
                swap_variant_path,
                first_variant_path,
                no_op_variant_path,
            ):
                open(path, "wb").close()

            swap_variant = _variant(swap_variant_path, id="variant_selected_route_swap")
            first_variant = _variant(first_variant_path, id="variant_selected_route_first")
            swap_line = _line(
                id="selected_route_variant_swap",
                image_path=image_path,
                generated_image_path=generated_path,
                current_text="keep selected route prompt",
                negative_prompt="keep selected route negative",
                generated_candidates=[{"path": "existing-candidate.png"}],
                gallery_variants=[dict(swap_variant)],
            )
            first_line = _line(
                id="selected_route_variant_first",
                gallery_variants=[dict(first_variant)],
            )
            missing_line = _line(
                id="selected_route_variant_missing",
                gallery_variants=[_variant(missing_variant_path)],
            )
            not_found_line = _line(
                id="selected_route_variant_not_found",
                gallery_variants=[],
            )
            no_op_line = _line(
                id="selected_route_variant_no_op",
                selected_candidate_path=no_op_variant_path,
                gallery_variants=[_variant(no_op_variant_path)],
            )
            skipped_lines = [
                _line(id="separator", line_type="separator", gallery_variants=[_variant(swap_variant_path)]),
                _line(id="deleted", deleted=True, gallery_variants=[_variant(swap_variant_path)]),
                _line(id="workbench", line_type="workbench", gallery_variants=[_variant(swap_variant_path)]),
            ]
            before_swap_variants = [dict(variant) for variant in swap_line.gallery_variants]
            before_first_variants = [dict(variant) for variant in first_line.gallery_variants]

            result = apply_route_batch_candidate_adoption_preview(
                [
                    swap_line,
                    first_line,
                    missing_line,
                    not_found_line,
                    no_op_line,
                    *skipped_lines,
                ],
                scope="selected_route",
                source=GALLERY_VARIANT_PREVIEW_SOURCE,
                path_exists=os.path.exists,
                now="2026-07-07T00:00:00+00:00",
            )

            self.assertEqual(2, result["applied_count"])
            self.assertEqual(1, result["swap_with_retreat_count"])
            self.assertEqual(1, result["first_main_image_count"])
            self.assertEqual(6, result["skipped_count"])
            self.assertEqual(swap_variant_path, swap_line.selected_candidate_path)
            self.assertEqual(generated_path, swap_line.generated_image_path)
            self.assertEqual(image_path, swap_line.image_path)
            self.assertEqual("keep selected route prompt", swap_line.current_text)
            self.assertEqual("keep selected route negative", swap_line.negative_prompt)
            self.assertEqual(first_variant_path, first_line.selected_candidate_path)
            self.assertEqual(before_swap_variants, swap_line.gallery_variants)
            self.assertEqual(before_first_variants, first_line.gallery_variants)
            self.assertFalse(
                any(candidate.get("path") == swap_variant_path for candidate in swap_line.generated_candidates)
            )
            retreat_records = [
                candidate
                for candidate in swap_line.generated_candidates
                if candidate.get("path") == generated_path
            ]
            self.assertEqual(1, len(retreat_records))
            self.assertEqual("route_batch_candidate_adoption_retreat", retreat_records[0].get("source"))
            self.assertFalse(first_line.generated_candidates)
            self.assertIn("missing gallery variant file", result["skipped_reasons"])
            self.assertIn("gallery variant target not found", result["skipped_reasons"])
            self.assertIn("already adopted / no-op", result["skipped_reasons"])
            self.assertIn("Route separator", result["skipped_reasons"])
            self.assertIn("deleted line", result["skipped_reasons"])
            self.assertIn("Workbench line", result["skipped_reasons"])

    def test_apply_selected_route_gallery_variant_does_not_duplicate_retreat(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            main_path = os.path.join(tmpdir, "main.png")
            variant_path = os.path.join(tmpdir, "variant.png")
            for path in (main_path, variant_path):
                open(path, "wb").close()

            line = _line(
                image_path=main_path,
                generated_candidates=[{"path": main_path, "source": "existing"}],
                gallery_variants=[_variant(variant_path)],
            )

            result = apply_route_batch_candidate_adoption_preview(
                [line],
                scope="selected_route",
                source=GALLERY_VARIANT_PREVIEW_SOURCE,
                path_exists=os.path.exists,
            )

            self.assertEqual(1, result["applied_count"])
            self.assertEqual(
                1,
                len(
                    [
                        candidate
                        for candidate in line.generated_candidates
                        if candidate.get("path") == main_path
                    ]
                ),
            )
            self.assertFalse(
                any(candidate.get("path") == variant_path for candidate in line.generated_candidates)
            )

    def test_apply_all_scope_candidate_sources_apply_and_preserve_state(self):
        for source in ("latest", "first"):
            with self.subTest(source=source):
                with tempfile.TemporaryDirectory() as tmpdir:
                    main_path = os.path.join(tmpdir, f"{source}-main.png")
                    generated_path = os.path.join(tmpdir, f"{source}-generated.png")
                    first_candidate_path = os.path.join(tmpdir, f"{source}-first.png")
                    latest_candidate_path = os.path.join(tmpdir, f"{source}-latest.png")
                    first_image_less_path = os.path.join(tmpdir, f"{source}-image-less-first.png")
                    latest_image_less_path = os.path.join(tmpdir, f"{source}-image-less-latest.png")
                    trashed_path = os.path.join(tmpdir, f"{source}-trashed.png")
                    no_op_path = os.path.join(tmpdir, f"{source}-no-op.png")
                    missing_path = os.path.join(tmpdir, f"{source}-missing.png")
                    for path in (
                        main_path,
                        generated_path,
                        first_candidate_path,
                        latest_candidate_path,
                        first_image_less_path,
                        latest_image_less_path,
                        trashed_path,
                        no_op_path,
                    ):
                        open(path, "wb").close()

                    expected_swap_path = latest_candidate_path if source == "latest" else first_candidate_path
                    expected_first_path = latest_image_less_path if source == "latest" else first_image_less_path
                    gallery_variants = [_variant(os.path.join(tmpdir, f"{source}-variant.png"))]
                    swap_line = _line(
                        id=f"{source}_all_swap",
                        image_path=main_path,
                        generated_image_path=generated_path,
                        current_text="keep all prompt",
                        negative_prompt="keep all negative",
                        generated_candidates=[
                            {"path": first_candidate_path, "source": "first"},
                            {"path": latest_candidate_path, "source": "latest"},
                        ],
                        gallery_variants=[dict(variant) for variant in gallery_variants],
                    )
                    image_less_line = _line(
                        id=f"{source}_all_first",
                        generated_candidates=[
                            {"path": first_image_less_path},
                            {"path": latest_image_less_path},
                        ],
                    )
                    trashed_line = _line(
                        id=f"{source}_all_trashed",
                        generated_candidates=[{"path": trashed_path, "trashed": True}],
                    )
                    missing_line = _line(
                        id=f"{source}_all_missing",
                        generated_candidates=[{"path": missing_path}],
                    )
                    not_found_line = _line(
                        id=f"{source}_all_not_found",
                        generated_candidates=[],
                    )
                    no_op_line = _line(
                        id=f"{source}_all_no_op",
                        selected_candidate_path=no_op_path,
                        generated_candidates=[{"path": no_op_path}],
                    )
                    skipped_lines = [
                        _line(id=f"{source}_all_separator", line_type="separator", generated_candidates=[{"path": expected_swap_path}]),
                        _line(id=f"{source}_all_deleted", deleted=True, generated_candidates=[{"path": expected_swap_path}]),
                        _line(id=f"{source}_all_workbench", line_type="workbench", generated_candidates=[{"path": expected_swap_path}]),
                    ]

                    result = apply_route_batch_candidate_adoption_preview(
                        [
                            swap_line,
                            image_less_line,
                            trashed_line,
                            missing_line,
                            not_found_line,
                            no_op_line,
                            *skipped_lines,
                        ],
                        scope="all_lines",
                        source=source,
                        path_exists=os.path.exists,
                        now="2026-07-07T00:00:00+00:00",
                    )

                    self.assertEqual(2, result["applied_count"])
                    self.assertEqual(1, result["swap_with_retreat_count"])
                    self.assertEqual(1, result["first_main_image_count"])
                    self.assertEqual(7, result["skipped_count"])
                    self.assertEqual("", result["unsupported_scope"])
                    self.assertEqual("", result["unsupported_source"])
                    self.assertEqual(expected_swap_path, swap_line.selected_candidate_path)
                    self.assertEqual(generated_path, swap_line.generated_image_path)
                    self.assertEqual(main_path, swap_line.image_path)
                    self.assertEqual("keep all prompt", swap_line.current_text)
                    self.assertEqual("keep all negative", swap_line.negative_prompt)
                    self.assertEqual(gallery_variants, swap_line.gallery_variants)
                    self.assertEqual(expected_first_path, image_less_line.selected_candidate_path)
                    adopted_record = next(
                        candidate
                        for candidate in swap_line.generated_candidates
                        if candidate.get("path") == expected_swap_path
                    )
                    self.assertEqual("route_batch_candidate_adoption", adopted_record.get("adoption_mode"))
                    self.assertEqual(
                        "2026-07-07T00:00:00+00:00",
                        adopted_record.get("batch_adopted_to_main_at"),
                    )
                    retreat_records = [
                        candidate
                        for candidate in swap_line.generated_candidates
                        if candidate.get("path") == generated_path
                    ]
                    self.assertEqual(1, len(retreat_records))
                    self.assertEqual("route_batch_candidate_adoption_retreat", retreat_records[0].get("source"))
                    self.assertIn("trashed candidate only", result["skipped_reasons"])
                    self.assertIn("missing candidate file", result["skipped_reasons"])
                    self.assertIn("adoption target not found", result["skipped_reasons"])
                    self.assertIn("already adopted / no-op", result["skipped_reasons"])
                    self.assertIn("Route separator", result["skipped_reasons"])
                    self.assertIn("deleted line", result["skipped_reasons"])
                    self.assertIn("Workbench line", result["skipped_reasons"])

    def test_apply_all_scope_candidate_source_does_not_duplicate_existing_retreat_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            main_path = os.path.join(tmpdir, "main.png")
            candidate_path = os.path.join(tmpdir, "candidate.png")
            for path in (main_path, candidate_path):
                open(path, "wb").close()

            line = _line(
                image_path=main_path,
                generated_candidates=[
                    {"path": main_path, "source": "existing"},
                    {"path": candidate_path},
                ],
            )

            result = apply_route_batch_candidate_adoption_preview(
                [line],
                scope="all_lines",
                source="latest",
                path_exists=os.path.exists,
            )

            self.assertEqual(1, result["applied_count"])
            self.assertEqual(
                1,
                len(
                    [
                        candidate
                        for candidate in line.generated_candidates
                        if candidate.get("path") == main_path
                    ]
                ),
            )

    def test_apply_rejects_unknown_source_without_state_changes(self):
        line = _line(
            image_path="source.png",
            generated_image_path="generated.png",
            current_text="keep prompt",
            negative_prompt="keep negative",
            generated_candidates=[{"path": "candidate.png"}],
            gallery_variants=[_variant("variant.png")],
        )
        before_candidates = list(line.generated_candidates)
        before_variants = list(line.gallery_variants)

        result = apply_route_batch_candidate_adoption_preview(
            [line],
            scope="selected_route",
            source="unknown_source",
        )

        self.assertEqual(0, result["applied_count"])
        self.assertEqual(1, result["skipped_count"])
        self.assertEqual("unknown_source", result["unsupported_source"])
        self.assertFalse(getattr(line, "selected_candidate_path", ""))
        self.assertEqual("generated.png", line.generated_image_path)
        self.assertEqual("source.png", line.image_path)
        self.assertEqual("keep prompt", line.current_text)
        self.assertEqual("keep negative", line.negative_prompt)
        self.assertEqual(before_candidates, line.generated_candidates)
        self.assertEqual(before_variants, line.gallery_variants)

    def test_apply_all_scope_gallery_variant_multiple_lines_and_skips(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = os.path.join(tmpdir, "source.png")
            generated_path = os.path.join(tmpdir, "generated.png")
            swap_variant_path = os.path.join(tmpdir, "swap-variant.png")
            first_variant_path = os.path.join(tmpdir, "first-variant.png")
            missing_variant_path = os.path.join(tmpdir, "missing-variant.png")
            no_op_variant_path = os.path.join(tmpdir, "no-op-variant.png")
            for path in (
                image_path,
                generated_path,
                swap_variant_path,
                first_variant_path,
                no_op_variant_path,
            ):
                open(path, "wb").close()

            swap_variant = _variant(swap_variant_path, id="variant_all_swap")
            first_variant = _variant(first_variant_path, id="variant_all_first")
            swap_line = _line(
                id="all_variant_swap",
                image_path=image_path,
                generated_image_path=generated_path,
                current_text="keep all variant prompt",
                negative_prompt="keep all variant negative",
                generated_candidates=[{"path": "existing-candidate.png"}],
                gallery_variants=[dict(swap_variant)],
            )
            first_line = _line(
                id="all_variant_first",
                gallery_variants=[dict(first_variant)],
            )
            missing_line = _line(
                id="all_variant_missing",
                gallery_variants=[_variant(missing_variant_path)],
            )
            not_found_line = _line(
                id="all_variant_not_found",
                gallery_variants=[],
            )
            no_op_line = _line(
                id="all_variant_no_op",
                selected_candidate_path=no_op_variant_path,
                gallery_variants=[_variant(no_op_variant_path)],
            )
            skipped_lines = [
                _line(id="separator", line_type="separator", gallery_variants=[_variant(swap_variant_path)]),
                _line(id="deleted", deleted=True, gallery_variants=[_variant(swap_variant_path)]),
                _line(id="workbench", line_type="workbench", gallery_variants=[_variant(swap_variant_path)]),
            ]
            before_swap_variants = [dict(variant) for variant in swap_line.gallery_variants]
            before_first_variants = [dict(variant) for variant in first_line.gallery_variants]

            result = apply_route_batch_candidate_adoption_preview(
                [
                    swap_line,
                    first_line,
                    missing_line,
                    not_found_line,
                    no_op_line,
                    *skipped_lines,
                ],
                scope="all_lines",
                source=GALLERY_VARIANT_PREVIEW_SOURCE,
                path_exists=os.path.exists,
                now="2026-07-08T00:00:00+00:00",
            )

            self.assertEqual(2, result["applied_count"])
            self.assertEqual(1, result["swap_with_retreat_count"])
            self.assertEqual(1, result["first_main_image_count"])
            self.assertEqual(6, result["skipped_count"])
            self.assertEqual("", result["unsupported_scope"])
            self.assertEqual("", result["unsupported_source"])
            self.assertEqual(swap_variant_path, swap_line.selected_candidate_path)
            self.assertEqual(generated_path, swap_line.generated_image_path)
            self.assertEqual(image_path, swap_line.image_path)
            self.assertEqual("keep all variant prompt", swap_line.current_text)
            self.assertEqual("keep all variant negative", swap_line.negative_prompt)
            self.assertEqual(first_variant_path, first_line.selected_candidate_path)
            self.assertEqual(before_swap_variants, swap_line.gallery_variants)
            self.assertEqual(before_first_variants, first_line.gallery_variants)
            self.assertFalse(
                any(candidate.get("path") == swap_variant_path for candidate in swap_line.generated_candidates)
            )
            retreat_records = [
                candidate
                for candidate in swap_line.generated_candidates
                if candidate.get("path") == generated_path
            ]
            self.assertEqual(1, len(retreat_records))
            self.assertEqual("route_batch_candidate_adoption_retreat", retreat_records[0].get("source"))
            self.assertFalse(first_line.generated_candidates)
            self.assertIn("missing gallery variant file", result["skipped_reasons"])
            self.assertIn("gallery variant target not found", result["skipped_reasons"])
            self.assertIn("already adopted / no-op", result["skipped_reasons"])
            self.assertIn("Route separator", result["skipped_reasons"])
            self.assertIn("deleted line", result["skipped_reasons"])
            self.assertIn("Workbench line", result["skipped_reasons"])

    def test_apply_all_scope_gallery_variant_does_not_duplicate_retreat(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            main_path = os.path.join(tmpdir, "main.png")
            variant_path = os.path.join(tmpdir, "variant.png")
            for path in (main_path, variant_path):
                open(path, "wb").close()

            line = _line(
                image_path=main_path,
                generated_candidates=[{"path": main_path, "source": "existing"}],
                gallery_variants=[_variant(variant_path)],
            )

            result = apply_route_batch_candidate_adoption_preview(
                [line],
                scope="all_lines",
                source=GALLERY_VARIANT_PREVIEW_SOURCE,
                path_exists=os.path.exists,
            )

            self.assertEqual(1, result["applied_count"])
            self.assertEqual(
                1,
                len(
                    [
                        candidate
                        for candidate in line.generated_candidates
                        if candidate.get("path") == main_path
                    ]
                ),
            )
            self.assertFalse(
                any(candidate.get("path") == variant_path for candidate in line.generated_candidates)
            )

    def test_apply_rejects_unknown_scope_without_state_changes(self):
        line = _line(
            image_path="source.png",
            generated_image_path="generated.png",
            current_text="keep prompt",
            negative_prompt="keep negative",
            generated_candidates=[{"path": "candidate.png"}],
            gallery_variants=[_variant("variant.png")],
        )
        before_candidates = list(line.generated_candidates)
        before_variants = list(line.gallery_variants)

        result = apply_route_batch_candidate_adoption_preview(
            [line],
            scope="unknown_scope",
            source=GALLERY_VARIANT_PREVIEW_SOURCE,
        )

        self.assertEqual(0, result["applied_count"])
        self.assertEqual(1, result["skipped_count"])
        self.assertEqual("unknown_scope", result["unsupported_scope"])
        self.assertEqual(GALLERY_VARIANT_PREVIEW_SOURCE, result["unsupported_source"])
        self.assertFalse(getattr(line, "selected_candidate_path", ""))
        self.assertEqual("generated.png", line.generated_image_path)
        self.assertEqual("source.png", line.image_path)
        self.assertEqual("keep prompt", line.current_text)
        self.assertEqual("keep negative", line.negative_prompt)
        self.assertEqual(before_candidates, line.generated_candidates)
        self.assertEqual(before_variants, line.gallery_variants)


if __name__ == "__main__":
    unittest.main()
