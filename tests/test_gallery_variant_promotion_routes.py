import copy
import os
import tempfile
import unittest
from types import SimpleNamespace

from core.gallery_variant_promotion import (
    apply_batch_variant_promotion_plan,
    build_batch_variant_promotion_plan,
    build_batch_variant_promotion_signature,
    normalize_batch_variant_promotion_scope,
    resolve_batch_variant_promotion_targets,
    resolve_variant_promotion_insert_index,
    validate_batch_variant_promotion_submit,
)
from core.project import Project, PromptLine


def _line(
    line_id,
    text="prompt",
    *,
    line_type=None,
    deleted=False,
    negative_prompt="negative",
    gallery_variants=None,
    generated_candidates=None,
    **fields,
):
    return PromptLine(
        id=line_id,
        original_file_name=f"{line_id}.png",
        original_index=0,
        current_index=0,
        original_text=text,
        current_text=text,
        tokens=[text],
        negative_prompt=negative_prompt,
        line_type=line_type,
        deleted=deleted,
        gallery_variants=list(gallery_variants or []),
        generated_candidates=list(generated_candidates or []),
        **fields,
    )


def _project(*lines):
    project = Project(prompt_lines=list(lines), source_directory="source")
    for index, line in enumerate(project.prompt_lines):
        line.current_index = index
    return project


def _variant(path, variant_id, **metadata):
    return {
        "id": variant_id,
        "kind": "gallery_variant",
        "path": path,
        **metadata,
    }


def _fixture():
    return _project(
        _line("route_a", "Route A", line_type="separator", separator_label="Route A"),
        _line("a1"),
        _line("workbench_a", line_type="workbench", workbench_source_line_id="a1"),
        _line("a_deleted", deleted=True),
        _line("a2"),
        _line("route_b", "Route B", line_type="separator", separator_label="Route B"),
        _line("b1"),
        _line("route_c", "Route C", line_type="separator", separator_label="Route C"),
        _line("c1"),
    )


class VariantPromotionTargetResolutionTests(unittest.TestCase):
    def test_scope_aliases_and_default_are_safe(self):
        self.assertEqual("all_lines", normalize_batch_variant_promotion_scope("all"))
        self.assertEqual("selected_lines", normalize_batch_variant_promotion_scope("selected"))
        self.assertEqual("current_route", normalize_batch_variant_promotion_scope("invalid"))

    def test_all_five_scopes_resolve_in_physical_project_order(self):
        project = _fixture()
        cases = {
            "current_route": (
                {"current_anchor_line_id": "a2"},
                ["a1", "a2"],
                ["route_a"],
            ),
            "selected_route": (
                {"selected_route_id": "route_b"},
                ["b1"],
                ["route_b"],
            ),
            "selected_routes": (
                {"selected_route_ids": ["route_c", "route_a"]},
                ["a1", "a2", "c1"],
                ["route_a", "route_c"],
            ),
            "selected_lines": (
                {"selected_line_ids": ["c1", "a2", "workbench_a", "a_deleted"]},
                ["a2", "c1"],
                ["route_a", "route_c"],
            ),
            "all_lines": (
                {},
                ["a1", "a2", "b1", "c1"],
                ["route_a", "route_b", "route_c"],
            ),
        }
        for scope, (kwargs, expected_lines, expected_routes) in cases.items():
            with self.subTest(scope=scope):
                result = resolve_batch_variant_promotion_targets(project, scope, **kwargs)
                self.assertTrue(result["valid"], result)
                self.assertEqual(expected_lines, result["target_line_ids"])
                self.assertEqual(expected_routes, result["selected_route_handles"])
                self.assertNotIn("workbench_a", result["target_line_ids"])
                self.assertNotIn("a_deleted", result["target_line_ids"])
                self.assertNotIn("route_a", result["target_line_ids"])

    def test_selected_routes_ignore_stale_handles_but_fail_on_ambiguous_handle(self):
        project = _fixture()
        project.prompt_lines.append(_line("normal", line_type=None))
        result = resolve_batch_variant_promotion_targets(
            project,
            "selected_routes",
            selected_route_ids=["missing", "normal", "route_b"],
        )
        self.assertTrue(result["valid"])
        self.assertEqual(["route_b"], result["selected_route_handles"])
        self.assertEqual(["b1"], result["target_line_ids"])
        self.assertTrue(result["diagnostics"])

        ambiguous = _project(
            _line("route_dup", line_type="separator"),
            _line("a1"),
            _line("route_dup", line_type="separator"),
            _line("b1"),
        )
        blocked = resolve_batch_variant_promotion_targets(
            ambiguous,
            "selected_routes",
            selected_route_ids=["route_dup"],
        )
        self.assertFalse(blocked["valid"])
        self.assertIn("ambiguous", blocked["reason"])

    def test_empty_or_unresolved_scopes_fail_closed_without_fallback(self):
        project = _fixture()
        cases = (
            ("current_route", {"current_anchor_line_id": "missing"}),
            ("selected_route", {"selected_route_id": "missing"}),
            ("selected_routes", {"selected_route_ids": []}),
            ("selected_lines", {"selected_line_ids": []}),
        )
        for scope, kwargs in cases:
            with self.subTest(scope=scope):
                result = resolve_batch_variant_promotion_targets(project, scope, **kwargs)
                self.assertFalse(result["valid"])
                self.assertEqual([], result["target_line_ids"])

        head_only = _project(_line("head"))
        current = resolve_batch_variant_promotion_targets(
            head_only,
            "current_route",
            current_anchor_line_id="head",
        )
        self.assertFalse(current["valid"])

    def test_duplicate_target_line_id_fails_closed(self):
        project = _project(_line("dup"), _line("dup"))
        result = resolve_batch_variant_promotion_targets(project, "all_lines")
        self.assertFalse(result["valid"])
        self.assertIn("ambiguous", result["reason"])

    def test_selected_routes_keep_empty_route_summary_and_count(self):
        project = _project(
            _line("route_a", line_type="separator", separator_label="Route A"),
            _line("a1"),
            _line("route_b", line_type="separator", separator_label="Route B"),
            _line("b_workbench", line_type="workbench"),
            _line("b_deleted", deleted=True),
        )
        result = resolve_batch_variant_promotion_targets(
            project,
            "selected_routes",
            selected_route_ids=["route_b", "route_a"],
        )
        self.assertTrue(result["valid"])
        self.assertEqual(["route_a", "route_b"], result["selected_route_handles"])
        self.assertEqual(["Route A", "Route B"], result["selected_route_labels"])
        self.assertEqual(2, result["selected_route_count"])
        self.assertEqual(
            [("route_a", 1), ("route_b", 0)],
            [
                (summary["route_handle"], summary["target_line_count"])
                for summary in result["route_summaries"]
            ],
        )
        plan = build_batch_variant_promotion_plan(
            project,
            scope="selected_routes",
            selected_route_ids=["route_b", "route_a"],
        )
        self.assertEqual(2, plan["selected_route_count"])
        self.assertEqual(["Route A", "Route B"], plan["selected_route_labels"])
        self.assertEqual(
            [("route_a", 1, 0), ("route_b", 0, 0)],
            [
                (
                    summary["route_handle"],
                    summary["target_line_count"],
                    summary["will_promote"],
                )
                for summary in plan["route_summaries"]
            ],
        )


class VariantPromotionPlanTests(unittest.TestCase):
    def test_latest_and_first_use_only_appended_variants(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            first_path = os.path.join(tmpdir, "first.png")
            latest_path = os.path.join(tmpdir, "latest.png")
            for path in (first_path, latest_path):
                with open(path, "wb") as handle:
                    handle.write(path.encode("utf-8"))
            line = _line(
                "a1",
                gallery_variants=[
                    {"id": "plain", "path": first_path},
                    None,
                    {"id": "variant_pathless", "kind": "gallery_variant", "path": ""},
                    _variant(first_path, "variant_first"),
                    {"id": "variant_trashed", "kind": "gallery_variant", "path": first_path, "trashed": True},
                    _variant(latest_path, "variant_latest"),
                ],
            )
            project = _project(_line("route_a", line_type="separator"), line)
            for source, expected_id, expected_path in (
                ("first", "variant_first", first_path),
                ("latest", "variant_latest", latest_path),
            ):
                with self.subTest(source=source):
                    plan = build_batch_variant_promotion_plan(
                        project,
                        scope="selected_route",
                        selected_route_id="route_a",
                        source=source,
                        placement="end",
                    )
                    self.assertTrue(plan["valid"])
                    self.assertEqual(1, plan["will_promote"])
                    self.assertEqual(expected_id, plan["entries"][0]["variant_id"])
                    self.assertEqual(expected_path, plan["entries"][0]["variant_path"])

    def test_missing_invalid_and_out_of_scope_variants_are_summarized(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            valid_path = os.path.join(tmpdir, "valid.png")
            with open(valid_path, "wb") as handle:
                handle.write(b"x")
            project = _project(
                _line("route_a", line_type="separator", separator_label="Route A"),
                _line("a1", gallery_variants=[_variant(valid_path, "variant_a")]),
                _line("a2", gallery_variants=[_variant(os.path.join(tmpdir, "missing.png"), "variant_missing")]),
                _line("a3", gallery_variants=[{"id": "not_appended", "path": valid_path}]),
                _line("route_b", line_type="separator", separator_label="Route B"),
                _line("b1", gallery_variants=[_variant(valid_path, "variant_b")]),
            )
            before = copy.deepcopy(project)
            plan = build_batch_variant_promotion_plan(
                project,
                scope="selected_route",
                selected_route_id="route_a",
                source="latest",
                placement="after_parent",
            )
            self.assertEqual(1, plan["selected_route_count"])
            self.assertEqual(3, plan["target_line_count"])
            self.assertEqual(2, plan["variants_found"])
            self.assertEqual(2, plan["missing_variants"])
            self.assertEqual(1, plan["will_promote"])
            self.assertEqual(1, plan["route_summaries"][0]["will_promote"])
            self.assertEqual(["a1", "a2", "a3"], [entry["parent_line_id"] for entry in plan["entries"]])
            self.assertEqual(before, project)
            self.assertNotIn("b1", plan["target_line_ids"])

    def test_selected_route_labels_follow_project_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "variant.png")
            with open(path, "wb") as handle:
                handle.write(b"x")
            project = _fixture()
            for line in project.prompt_lines:
                if line.id in {"a1", "c1"}:
                    line.gallery_variants = [_variant(path, f"variant_{line.id}")]
            plan = build_batch_variant_promotion_plan(
                project,
                scope="selected_routes",
                selected_route_ids=["route_c", "route_a"],
                source="latest",
                placement="end",
            )
            self.assertEqual(["Route A", "Route C"], plan["selected_route_labels"])
            self.assertEqual(["a1", "a2", "c1"], plan["target_line_ids"])
            self.assertEqual(["Route A", "Route C"], [row["route_label"] for row in plan["route_summaries"]])

    def test_relevant_changes_make_preview_stale(self):
        mutations = (
            "scope",
            "source",
            "placement",
            "selected_routes",
            "route_move",
            "route_remove",
            "prompt",
            "negative",
            "variant_add",
            "variant_delete",
            "variant_order",
            "variant_path",
            "image_missing",
            "metadata",
            "project_path",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmpdir:
                first_path = os.path.join(tmpdir, "first.png")
                latest_path = os.path.join(tmpdir, "latest.png")
                for path in (first_path, latest_path):
                    with open(path, "wb") as handle:
                        handle.write(b"x")
                a1 = _line(
                    "a1",
                    text="p" * 300,
                    negative_prompt="n" * 300,
                    gallery_variants=[
                        _variant(first_path, "variant_first"),
                        _variant(latest_path, "variant_latest"),
                    ],
                    source_generation_info={"steps": 20},
                    lineage_info={"kind": "source"},
                )
                project = _project(
                    _line("route_a", line_type="separator", separator_label="Route A"),
                    a1,
                    _line("route_b", line_type="separator", separator_label="Route B"),
                    _line("b1", gallery_variants=[_variant(first_path, "variant_b")]),
                )
                kwargs = {
                    "scope": "selected_routes",
                    "selected_route_ids": ["route_a"],
                    "source": "latest",
                    "placement": "end",
                    "project_path": os.path.join(tmpdir, "project.json"),
                }
                stored = build_batch_variant_promotion_plan(project, **kwargs)
                changed_kwargs = dict(kwargs)
                if mutation == "scope":
                    changed_kwargs["scope"] = "all_lines"
                elif mutation == "source":
                    changed_kwargs["source"] = "first"
                elif mutation == "placement":
                    changed_kwargs["placement"] = "after_parent"
                elif mutation == "selected_routes":
                    changed_kwargs["selected_route_ids"] = ["route_b"]
                elif mutation == "route_move":
                    project.prompt_lines = project.prompt_lines[2:] + project.prompt_lines[:2]
                elif mutation == "route_remove":
                    project.prompt_lines[0].deleted = True
                    a1.deleted = True
                elif mutation == "prompt":
                    a1.current_text = ("p" * 240) + "changed"
                elif mutation == "negative":
                    a1.negative_prompt = ("n" * 240) + "changed"
                elif mutation == "variant_add":
                    a1.gallery_variants.append(_variant(first_path, "variant_added"))
                elif mutation == "variant_delete":
                    a1.gallery_variants.pop()
                elif mutation == "variant_order":
                    a1.gallery_variants.reverse()
                elif mutation == "variant_path":
                    a1.gallery_variants[-1]["path"] = first_path
                elif mutation == "image_missing":
                    os.remove(latest_path)
                elif mutation == "metadata":
                    a1.source_generation_info["steps"] = 30
                else:
                    changed_kwargs["project_path"] = os.path.join(tmpdir, "other.json")
                for index, line in enumerate(project.prompt_lines):
                    line.current_index = index
                validation = validate_batch_variant_promotion_submit(
                    project,
                    stored,
                    **changed_kwargs,
                )
                self.assertTrue(validation["stale_preview"])
                self.assertFalse(validation["valid"])

    def test_explicit_route_and_selected_line_changes_make_preview_stale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "variant.png")
            with open(path, "wb") as handle:
                handle.write(b"x")
            project = _project(
                _line("route_a", line_type="separator"),
                _line("a1", gallery_variants=[_variant(path, "variant_a")]),
                _line("route_b", line_type="separator"),
                _line("b1", gallery_variants=[_variant(path, "variant_b")]),
            )

            selected_route_plan = build_batch_variant_promotion_plan(
                project,
                scope="selected_route",
                selected_route_id="route_a",
            )
            selected_route_validation = validate_batch_variant_promotion_submit(
                project,
                selected_route_plan,
                scope="selected_route",
                selected_route_id="route_b",
            )
            self.assertTrue(selected_route_validation["stale_preview"])

            selected_lines_plan = build_batch_variant_promotion_plan(
                project,
                scope="selected_lines",
                selected_line_ids=["a1"],
            )
            selected_lines_validation = validate_batch_variant_promotion_submit(
                project,
                selected_lines_plan,
                scope="selected_lines",
                selected_line_ids=["b1"],
            )
            self.assertTrue(selected_lines_validation["stale_preview"])

    def test_resolver_avoids_filesystem_and_signatures_stat_only_selected_variant(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = [os.path.join(tmpdir, f"variant_{index}.png") for index in range(3)]
            line = _line(
                "a1",
                gallery_variants=[
                    _variant(path, f"variant_{index}")
                    for index, path in enumerate(paths)
                ],
            )
            project = _project(_line("route_a", line_type="separator"), line)
            calls = {"exists": [], "stat": []}

            def path_exists(path):
                calls["exists"].append(path)
                return True

            def path_stat(path):
                calls["stat"].append(path)
                return SimpleNamespace(st_size=10, st_mtime_ns=20)

            resolution = resolve_batch_variant_promotion_targets(
                project,
                "selected_route",
                selected_route_id="route_a",
            )
            self.assertTrue(resolution["valid"])
            self.assertEqual([], calls["exists"])
            self.assertEqual([], calls["stat"])

            plan = build_batch_variant_promotion_plan(
                project,
                scope="selected_route",
                selected_route_id="route_a",
                source="latest",
                path_exists=path_exists,
                path_stat=path_stat,
            )
            self.assertEqual([paths[-1]], calls["exists"])
            self.assertEqual([paths[-1]], calls["stat"])

            calls["exists"].clear()
            calls["stat"].clear()
            signature = build_batch_variant_promotion_signature(
                project,
                scope="selected_route",
                selected_route_id="route_a",
                source="latest",
                path_exists=path_exists,
                path_stat=path_stat,
            )
            self.assertEqual(plan["signature"], signature)
            self.assertEqual([paths[-1]], calls["exists"])
            self.assertEqual([paths[-1]], calls["stat"])

    def test_scope_irrelevant_inputs_do_not_change_signature(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "variant.png")
            with open(path, "wb") as handle:
                handle.write(b"x")
            project = _project(
                _line("route_a", line_type="separator"),
                _line("a1", gallery_variants=[_variant(path, "variant_a")]),
                _line("route_b", line_type="separator"),
                _line("b1", gallery_variants=[_variant(path, "variant_b")]),
            )
            cases = (
                (
                    "current_route",
                    {"current_anchor_line_id": "a1"},
                    {
                        "current_anchor_line_id": "a1",
                        "selected_route_id": "route_b",
                        "selected_route_ids": ["route_b"],
                        "selected_line_ids": ["b1"],
                    },
                ),
                (
                    "selected_route",
                    {"selected_route_id": "route_a"},
                    {
                        "current_anchor_line_id": "b1",
                        "selected_route_id": "route_a",
                        "selected_route_ids": ["route_b"],
                        "selected_line_ids": ["b1"],
                    },
                ),
                (
                    "selected_routes",
                    {"selected_route_ids": ["route_a"]},
                    {
                        "current_anchor_line_id": "b1",
                        "selected_route_id": "route_b",
                        "selected_route_ids": ["route_a"],
                        "selected_line_ids": ["b1"],
                    },
                ),
                (
                    "selected_lines",
                    {"selected_line_ids": ["a1"]},
                    {
                        "current_anchor_line_id": "b1",
                        "selected_route_id": "route_b",
                        "selected_route_ids": ["route_b"],
                        "selected_line_ids": ["a1"],
                    },
                ),
                (
                    "all_lines",
                    {},
                    {
                        "current_anchor_line_id": "b1",
                        "selected_route_id": "route_b",
                        "selected_route_ids": ["route_b"],
                        "selected_line_ids": ["b1"],
                    },
                ),
            )
            for scope, relevant, noisy in cases:
                with self.subTest(scope=scope):
                    clean_signature = build_batch_variant_promotion_signature(
                        project,
                        scope=scope,
                        **relevant,
                    )
                    noisy_signature = build_batch_variant_promotion_signature(
                        project,
                        scope=scope,
                        **noisy,
                    )
                    self.assertEqual(clean_signature, noisy_signature)


class VariantPromotionAtomicApplyTests(unittest.TestCase):
    def _promoter(self, counter):
        def promote(project, parent_line_id, variant, placement):
            parent = next(line for line in project.prompt_lines if line.id == parent_line_id)
            counter["calls"] += 1
            new_line = copy.deepcopy(parent)
            new_line.id = f"promoted_{counter['calls']}"
            new_line.line_type = None
            new_line.deleted = False
            new_line.original_file_name = os.path.basename(variant["path"])
            new_line.original_text = parent.current_text
            new_line.current_text = parent.current_text
            new_line.tokens = [parent.current_text]
            new_line.image_path = variant["path"]
            new_line.generated_image_path = None
            new_line.selected_candidate_path = None
            new_line.generated_candidates = []
            new_line.gallery_variants = []
            new_line.duplicated_from = parent.id
            new_line.workbench_source_line_id = None
            new_line.workbench_title = None
            new_line.workbench_note = None
            new_line.workbench_status = None
            new_line.source_generation_info = copy.deepcopy(variant.get("source_generation_info", {}))
            new_line.lineage_info = copy.deepcopy(variant.get("lineage_info", {}))
            new_line.lineage_info.update({
                "lineage_kind": "gallery_variant_promote_to_route",
                "parent_line_id": parent.id,
                "promoted_from_variant_id": variant.get("id"),
                "promoted_from_variant_path": variant.get("path"),
                "candidate_image_path": variant.get("path"),
            })
            index = resolve_variant_promotion_insert_index(project, parent.id, placement)
            project.prompt_lines.insert(index, new_line)
            for current_index, line in enumerate(project.prompt_lines):
                line.current_index = current_index
            return new_line.id
        return promote

    def test_atomic_apply_returns_clone_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = [os.path.join(tmpdir, f"v{index}.png") for index in range(2)]
            for path in paths:
                with open(path, "wb") as handle:
                    handle.write(b"x")
            a1 = _line(
                "a1",
                image_path="main-a.png",
                generated_candidates=[{"id": "candidate_a", "path": "candidate-a.png"}],
                gallery_variants=[_variant(
                    paths[0],
                    "variant_a",
                    source_generation_info={"engine": "variant"},
                    lineage_info={"origin": "variant"},
                )],
            )
            b1 = _line("b1", gallery_variants=[_variant(paths[1], "variant_b")])
            project = _project(
                _line("route_a", line_type="separator"),
                a1,
                _line("route_b", line_type="separator"),
                b1,
            )
            before = copy.deepcopy(project)
            plan = build_batch_variant_promotion_plan(
                project,
                scope="selected_routes",
                selected_route_ids=["route_b", "route_a"],
                source="latest",
                placement="end",
            )
            counter = {"calls": 0}
            result = apply_batch_variant_promotion_plan(
                project,
                plan,
                promote_line=self._promoter(counter),
                scope="selected_routes",
                selected_route_ids=["route_b", "route_a"],
                source="latest",
                placement="end",
            )
            self.assertTrue(result["applied"])
            self.assertEqual(2, result["promoted_count"])
            self.assertEqual(before, project)
            updated = result["updated_project"]
            self.assertIsNot(updated, project)
            self.assertEqual(2, sum(line.line_type == "separator" for line in updated.prompt_lines))
            promoted = [line for line in updated.prompt_lines if line.id.startswith("promoted_")]
            self.assertEqual(["promoted_1", "promoted_2"], [line.id for line in promoted])
            self.assertEqual(paths, [line.image_path for line in promoted])
            self.assertTrue(all(line.generated_candidates == [] for line in promoted))
            self.assertTrue(all(line.gallery_variants == [] for line in promoted))
            self.assertEqual("negative", promoted[0].negative_prompt)
            self.assertEqual("gallery_variant_promote_to_route", promoted[0].lineage_info["lineage_kind"])
            self.assertEqual(before.prompt_lines[1], project.prompt_lines[1])

    def test_failure_and_noop_leave_source_unchanged_without_partial_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = [os.path.join(tmpdir, f"v{index}.png") for index in range(2)]
            for path in paths:
                with open(path, "wb") as handle:
                    handle.write(b"x")
            project = _project(
                _line("route_a", line_type="separator"),
                _line("a1", gallery_variants=[_variant(paths[0], "variant_a")]),
                _line("a2", gallery_variants=[_variant(paths[1], "variant_b")]),
            )
            before = copy.deepcopy(project)
            plan = build_batch_variant_promotion_plan(
                project,
                scope="selected_route",
                selected_route_id="route_a",
                source="latest",
                placement="end",
            )
            counter = {"calls": 0}
            real_promoter = self._promoter(counter)

            def fail_second(working, parent_line_id, variant, placement):
                if counter["calls"] == 1:
                    return None
                return real_promoter(working, parent_line_id, variant, placement)

            result = apply_batch_variant_promotion_plan(
                project,
                plan,
                promote_line=fail_second,
                scope="selected_route",
                selected_route_id="route_a",
                source="latest",
                placement="end",
            )
            self.assertFalse(result["applied"])
            self.assertIsNone(result["updated_project"])
            self.assertEqual(before, project)

            no_variant_project = _project(_line("route_a", line_type="separator"), _line("a1"))
            noop_plan = build_batch_variant_promotion_plan(
                no_variant_project,
                scope="selected_route",
                selected_route_id="route_a",
                source="latest",
                placement="end",
            )
            noop_before = copy.deepcopy(no_variant_project)
            noop = apply_batch_variant_promotion_plan(
                no_variant_project,
                noop_plan,
                promote_line=lambda *_args: self.fail("promoter should not run"),
                scope="selected_route",
                selected_route_id="route_a",
                source="latest",
                placement="end",
            )
            self.assertFalse(noop["applied"])
            self.assertEqual(0, noop["promoted_count"])
            self.assertEqual(noop_before, no_variant_project)

    def test_stale_plan_is_rejected_before_promoter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "variant.png")
            with open(path, "wb") as handle:
                handle.write(b"x")
            line = _line("a1", gallery_variants=[_variant(path, "variant_a")])
            project = _project(_line("route_a", line_type="separator"), line)
            plan = build_batch_variant_promotion_plan(
                project,
                scope="selected_route",
                selected_route_id="route_a",
                source="latest",
                placement="end",
            )
            line.current_text = "changed"
            result = apply_batch_variant_promotion_plan(
                project,
                plan,
                promote_line=lambda *_args: self.fail("promoter should not run"),
                scope="selected_route",
                selected_route_id="route_a",
                source="latest",
                placement="end",
            )
            self.assertTrue(result["stale_preview"])
            self.assertFalse(result["applied"])

    def test_insertion_index_preserves_existing_end_and_after_parent_semantics(self):
        active = _line("active")
        parent = _line("parent")
        deleted_a = _line("deleted_a", deleted=True)
        deleted_b = _line("deleted_b", deleted=True)
        project = _project(active, parent, deleted_a, deleted_b)
        self.assertEqual(2, resolve_variant_promotion_insert_index(project, "parent", "end"))
        self.assertEqual(2, resolve_variant_promotion_insert_index(project, "parent", "after_parent"))
        with self.assertRaises(ValueError):
            resolve_variant_promotion_insert_index(project, "missing", "after_parent")


if __name__ == "__main__":
    unittest.main()
