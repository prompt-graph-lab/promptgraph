import copy
import os
import tempfile
import unittest

from core.io import load_project_from_json, save_project_to_json
from core.lightweight_fork import (
    LIGHTWEIGHT_FORK_SELECTED_ROUTE_STATE_KEY,
    LIGHTWEIGHT_FORK_SELECTED_ROUTE_WIDGET_KEY,
    LIGHTWEIGHT_FORK_SELECTED_ROUTE_WIDGET_RESET_PENDING_KEY,
    apply_pending_lightweight_fork_single_route_widget_reset,
    build_lightweight_fork_append_input_signature,
    build_lightweight_fork_preview,
    build_lightweight_fork_project,
    initialize_lightweight_fork_single_route_widget_state,
    request_lightweight_fork_single_route_state_reset,
    resolve_lightweight_fork_append_targets,
    resolve_selected_routes_fork_plan,
    sync_lightweight_fork_single_route_widget_state,
)
from core.project import Project, PromptLine
from core.route_operations import get_active_route_removal_records


def _line(line_id, *, current_index, text="prompt", image_path="", **overrides):
    values = {
        "id": line_id,
        "original_file_name": f"{line_id}.png",
        "original_index": current_index,
        "current_index": current_index,
        "original_text": text,
        "current_text": text,
        "tokens": [text],
        "image_path": image_path,
    }
    values.update(overrides)
    return PromptLine(**values)


class LightweightForkSelectedRoutesTests(unittest.TestCase):
    def _project(self, tmpdir):
        route_a = _line(
            "route_a",
            current_index=20,
            text="Route A",
            line_type="separator",
            separator_label="Route A",
            separator_color="red",
        )
        a1 = _line("a1", current_index=21, image_path=os.path.join(tmpdir, "same.png"))
        workbench = _line("workbench_a", current_index=22, image_path=os.path.join(tmpdir, "workbench.png"), line_type="workbench")
        a2 = _line("a2", current_index=23, image_path=os.path.join(tmpdir, "a2.png"))
        route_b = _line(
            "route_b",
            current_index=1,
            text="Route B",
            line_type="separator",
            separator_label="Route B",
            separator_color="blue",
        )
        b1 = _line("b1", current_index=2, image_path=os.path.join(tmpdir, "b1.png"))
        route_c = _line(
            "route_c",
            current_index=0,
            text="Route C",
            line_type="separator",
            separator_label="Route C",
            separator_color="green",
        )
        c1 = _line("c1", current_index=3, image_path=os.path.join(tmpdir, "same.png"))
        return Project(prompt_lines=[route_a, a1, workbench, a2, route_b, b1, route_c, c1])

    def test_selected_routes_use_project_order_and_exclude_unselected_route(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = self._project(tmpdir)
            for name in ("same.png", "a2.png", "b1.png"):
                open(os.path.join(tmpdir, name), "wb").close()

            before_ids = [line.id for line in project.prompt_lines]
            plan = resolve_selected_routes_fork_plan(project, ["route_c", "route_a"])
            self.assertEqual(["route_a", "route_c"], plan["selected_route_ids"])
            self.assertEqual(["a1", "a2", "c1"], plan["target_line_ids"])
            self.assertEqual(1, plan["selected_workbench_count"])

            preview = build_lightweight_fork_preview(
                project.prompt_lines,
                scope="selected_routes",
                selected_route_ids=["route_c", "route_a"],
                project_path=tmpdir,
                path_exists=os.path.exists,
            )
            entries = [entry for entry in preview["entries"] if entry["materializable"]]
            self.assertEqual(["a1", "a2", "c1"], [entry["line_id"] for entry in entries])
            self.assertEqual(["route_a", "route_a", "route_c"], [entry["route_id"] for entry in entries])
            self.assertEqual(["Route A", "Route A", "Route C"], [entry["route_label"] for entry in entries])
            self.assertEqual([1, 3, 7], [entry["line_index"] for entry in entries])
            self.assertNotIn("b1", [entry["line_id"] for entry in preview["entries"]])
            self.assertEqual(before_ids, [line.id for line in project.prompt_lines])

    def test_selected_routes_materialization_preserves_boundaries_and_resets_transient_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = self._project(tmpdir)
            for name in ("same.png", "a2.png", "b1.png"):
                open(os.path.join(tmpdir, name), "wb").close()
            preview = build_lightweight_fork_preview(
                project.prompt_lines,
                scope="selected_routes",
                selected_route_ids=["route_a", "route_c"],
                project_path=tmpdir,
                path_exists=os.path.exists,
            )
            fork_project, manifest_entries = build_lightweight_fork_project(project, preview)
            self.assertEqual(
                ["separator", None, None, "separator", None],
                [line.line_type for line in fork_project.prompt_lines],
            )
            self.assertEqual(["Route A", "prompt", "prompt", "Route C", "prompt"], [
                line.current_text for line in fork_project.prompt_lines
            ])
            separator_entries = [entry for entry in manifest_entries if entry["kind"] == "route_separator"]
            materialized_entries = [entry for entry in manifest_entries if entry["kind"] == "materialized_line"]
            self.assertEqual(2, len(separator_entries))
            self.assertEqual([0, 6], [entry["source_line_index"] for entry in separator_entries])
            self.assertEqual([1, 3, 7], [entry["source_line_index"] for entry in materialized_entries])
            self.assertEqual("red", separator_entries[0]["route_color"])
            self.assertFalse(any(line.generated_candidates for line in fork_project.prompt_lines))
            self.assertFalse(any(line.gallery_variants for line in fork_project.prompt_lines))

    def test_selected_candidate_image_is_materialized_without_candidate_dependency(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            candidate_path = os.path.join(tmpdir, "candidate.png")
            open(candidate_path, "wb").close()
            line = _line(
                "candidate_line",
                current_index=1,
                selected_candidate_path=candidate_path,
                generated_candidates=[{"path": candidate_path, "prompt": "candidate prompt"}],
                gallery_variants=[{"path": os.path.join(tmpdir, "variant.png"), "kind": "gallery_variant"}],
            )
            separator = _line("route", current_index=0, text="Route", line_type="separator", separator_label="Route")
            project = Project(prompt_lines=[separator, line])
            preview = build_lightweight_fork_preview(
                project.prompt_lines,
                scope="selected_routes",
                selected_route_ids=["route"],
                project_path=tmpdir,
                path_exists=os.path.exists,
            )
            self.assertEqual("selected_candidate_path", preview["entries"][0]["source_field"])
            fork_project, _manifest = build_lightweight_fork_project(project, preview)
            fork_line = next(line for line in fork_project.prompt_lines if line.line_type != "separator")
            self.assertEqual(os.path.join("images", "0001_candidate.png"), fork_line.image_path)
            self.assertEqual([], fork_line.generated_candidates)
            self.assertEqual([], fork_line.gallery_variants)
            self.assertEqual(candidate_path, project.prompt_lines[1].selected_candidate_path)

    def test_empty_invalid_and_duplicate_selection_is_safe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = self._project(tmpdir)
            empty = resolve_selected_routes_fork_plan(project, [])
            self.assertFalse(empty["valid"])
            self.assertEqual([], empty["target_line_ids"])
            invalid = resolve_selected_routes_fork_plan(project, ["missing", "a1", "route_a", "route_a"])
            self.assertEqual(["route_a"], invalid["selected_route_ids"])
            self.assertEqual(["a1", "a2"], invalid["target_line_ids"])

    def test_append_single_route_uses_one_route_without_gallery_checkbox_selection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = self._project(tmpdir)

            target = resolve_lightweight_fork_append_targets(
                project,
                scope="selected_route",
                selected_route_id="route_b",
                selected_route_ids=[],
            )

            self.assertTrue(target["valid"])
            self.assertEqual("selected_route", target["scope"])
            self.assertEqual(["route_b"], target["raw_route_ids"])
            self.assertEqual(["route_b"], target["effective_route_ids"])
            self.assertEqual(["b1"], target["target_line_ids"])

    def test_append_selected_routes_use_gallery_selection_in_project_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = self._project(tmpdir)

            target = resolve_lightweight_fork_append_targets(
                project,
                scope="selected_routes",
                selected_route_id="route_b",
                selected_route_ids=["route_c", "route_a"],
            )

            self.assertTrue(target["valid"])
            self.assertEqual(["route_c", "route_a"], target["raw_route_ids"])
            self.assertEqual(["route_a", "route_c"], target["effective_route_ids"])
            self.assertEqual(["a1", "a2", "c1"], target["target_line_ids"])

    def test_append_scope_fallback_prefers_single_then_selected_routes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = self._project(tmpdir)

            single = resolve_lightweight_fork_append_targets(
                project,
                scope="legacy_scope",
                selected_route_id="route_b",
                selected_route_ids=["route_c"],
            )
            selected = resolve_lightweight_fork_append_targets(
                project,
                scope="legacy_scope",
                selected_route_id="missing",
                selected_route_ids=["route_c"],
            )
            empty = resolve_lightweight_fork_append_targets(
                project,
                scope="legacy_scope",
                selected_route_id="",
                selected_route_ids=[],
            )

            self.assertEqual("selected_route", single["scope"])
            self.assertEqual(["route_b"], single["effective_route_ids"])
            self.assertEqual("selected_routes", selected["scope"])
            self.assertEqual(["route_c"], selected["effective_route_ids"])
            self.assertEqual("selected_route", empty["scope"])
            self.assertFalse(empty["valid"])

    def test_append_single_route_rejects_invalid_deleted_non_separator_and_ambiguous_handles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = self._project(tmpdir)
            invalid_ids = ["missing", "b1"]
            for route_id in invalid_ids:
                target = resolve_lightweight_fork_append_targets(
                    project,
                    scope="selected_route",
                    selected_route_id=route_id,
                    selected_route_ids=["route_a"],
                )
                self.assertFalse(target["valid"])
                self.assertEqual("Select a valid Route.", target["reason"])
                self.assertEqual([], target["effective_route_ids"])

            route_b = next(line for line in project.prompt_lines if line.id == "route_b")
            route_b.deleted = True
            deleted = resolve_lightweight_fork_append_targets(
                project,
                scope="selected_route",
                selected_route_id="route_b",
                selected_route_ids=[],
            )
            self.assertFalse(deleted["valid"])

            route_b.deleted = False
            project.prompt_lines.append(copy.deepcopy(route_b))
            ambiguous = resolve_lightweight_fork_append_targets(
                project,
                scope="selected_route",
                selected_route_id="route_b",
                selected_route_ids=[],
            )
            self.assertFalse(ambiguous["valid"])
            self.assertEqual(["route_b"], ambiguous["raw_route_ids"])
            self.assertEqual([], ambiguous["effective_route_ids"])

    def test_append_selected_routes_blocks_empty_but_keeps_valid_routes_after_sanitizing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = self._project(tmpdir)
            partial = resolve_lightweight_fork_append_targets(
                project,
                scope="selected_routes",
                selected_route_id="route_b",
                selected_route_ids=["missing", "route_c", "route_c"],
            )
            empty = resolve_lightweight_fork_append_targets(
                project,
                scope="selected_routes",
                selected_route_id="route_b",
                selected_route_ids=["missing", "b1"],
            )

            self.assertTrue(partial["valid"])
            self.assertEqual(["route_c"], partial["effective_route_ids"])
            self.assertFalse(empty["valid"])
            self.assertEqual(
                "Select at least one Route using the Gallery Route checkboxes.",
                empty["reason"],
            )

    def test_append_input_signature_tracks_active_target_paths_and_route_structure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = self._project(tmpdir)
            single = resolve_lightweight_fork_append_targets(
                project,
                scope="selected_route",
                selected_route_id="route_b",
                selected_route_ids=["route_a"],
            )
            signature = build_lightweight_fork_append_input_signature(
                source_project_path=os.path.join(tmpdir, "source", "project.json"),
                destination_project_path=os.path.join(tmpdir, "fork", "project.json"),
                target_resolution=single,
            )

            inactive_selection_changed = resolve_lightweight_fork_append_targets(
                project,
                scope="selected_route",
                selected_route_id="route_b",
                selected_route_ids=["route_c"],
            )
            self.assertEqual(signature, build_lightweight_fork_append_input_signature(
                source_project_path=os.path.join(tmpdir, "source", "project.json"),
                destination_project_path=os.path.join(tmpdir, "fork", "project.json"),
                target_resolution=inactive_selection_changed,
            ))

            cases = []
            cases.append((os.path.join(tmpdir, "other-source", "project.json"), os.path.join(tmpdir, "fork", "project.json"), single))
            cases.append((os.path.join(tmpdir, "source", "project.json"), os.path.join(tmpdir, "other-fork", "project.json"), single))
            cases.append((os.path.join(tmpdir, "source", "project.json"), os.path.join(tmpdir, "fork", "project.json"), resolve_lightweight_fork_append_targets(
                project,
                scope="selected_route",
                selected_route_id="route_c",
                selected_route_ids=["route_a"],
            )))
            cases.append((os.path.join(tmpdir, "source", "project.json"), os.path.join(tmpdir, "fork", "project.json"), resolve_lightweight_fork_append_targets(
                project,
                scope="selected_routes",
                selected_route_id="route_b",
                selected_route_ids=["route_b"],
            )))
            project.prompt_lines[5], project.prompt_lines[7] = project.prompt_lines[7], project.prompt_lines[5]
            cases.append((os.path.join(tmpdir, "source", "project.json"), os.path.join(tmpdir, "fork", "project.json"), resolve_lightweight_fork_append_targets(
                project,
                scope="selected_route",
                selected_route_id="route_b",
                selected_route_ids=["route_a"],
            )))

            for source_path, destination_path, target in cases:
                changed = build_lightweight_fork_append_input_signature(
                    source_project_path=source_path,
                    destination_project_path=destination_path,
                    target_resolution=target,
                )
                self.assertNotEqual(signature, changed)

    def test_append_selected_routes_signature_ignores_inactive_single_route(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = self._project(tmpdir)
            first = resolve_lightweight_fork_append_targets(
                project,
                scope="selected_routes",
                selected_route_id="route_a",
                selected_route_ids=["route_b"],
            )
            second = resolve_lightweight_fork_append_targets(
                project,
                scope="selected_routes",
                selected_route_id="route_c",
                selected_route_ids=["route_b"],
            )
            first_signature = build_lightweight_fork_append_input_signature(
                source_project_path="source.json",
                destination_project_path="fork.json",
                target_resolution=first,
            )
            second_signature = build_lightweight_fork_append_input_signature(
                source_project_path="source.json",
                destination_project_path="fork.json",
                target_resolution=second,
            )
            self.assertEqual(first_signature, second_signature)

    def test_single_route_durable_state_survives_widget_cleanup_and_restores_selector(self):
        state = {LIGHTWEIGHT_FORK_SELECTED_ROUTE_STATE_KEY: "route_b"}

        initialized = initialize_lightweight_fork_single_route_widget_state(state)
        self.assertEqual("route_b", initialized)
        self.assertEqual("route_b", state[LIGHTWEIGHT_FORK_SELECTED_ROUTE_WIDGET_KEY])

        state.pop(LIGHTWEIGHT_FORK_SELECTED_ROUTE_WIDGET_KEY)
        self.assertEqual("route_b", state[LIGHTWEIGHT_FORK_SELECTED_ROUTE_STATE_KEY])

        restored = initialize_lightweight_fork_single_route_widget_state(state)
        self.assertEqual("route_b", restored)
        self.assertEqual("route_b", state[LIGHTWEIGHT_FORK_SELECTED_ROUTE_WIDGET_KEY])

        state[LIGHTWEIGHT_FORK_SELECTED_ROUTE_WIDGET_KEY] = "route_c"
        self.assertEqual("route_c", sync_lightweight_fork_single_route_widget_state(state))
        self.assertEqual("route_c", state[LIGHTWEIGHT_FORK_SELECTED_ROUTE_STATE_KEY])

    def test_project_transition_clears_durable_and_temporary_single_route_state(self):
        state = {
            LIGHTWEIGHT_FORK_SELECTED_ROUTE_STATE_KEY: "route_b",
            LIGHTWEIGHT_FORK_SELECTED_ROUTE_WIDGET_KEY: "route_b",
            "unrelated": "keep",
        }

        request_lightweight_fork_single_route_state_reset(state)

        self.assertNotIn(LIGHTWEIGHT_FORK_SELECTED_ROUTE_STATE_KEY, state)
        self.assertEqual("route_b", state[LIGHTWEIGHT_FORK_SELECTED_ROUTE_WIDGET_KEY])
        self.assertTrue(state[LIGHTWEIGHT_FORK_SELECTED_ROUTE_WIDGET_RESET_PENDING_KEY])

        self.assertTrue(apply_pending_lightweight_fork_single_route_widget_reset(state))
        self.assertNotIn(LIGHTWEIGHT_FORK_SELECTED_ROUTE_WIDGET_KEY, state)
        self.assertNotIn(LIGHTWEIGHT_FORK_SELECTED_ROUTE_WIDGET_RESET_PENDING_KEY, state)
        self.assertEqual("keep", state["unrelated"])
        self.assertFalse(apply_pending_lightweight_fork_single_route_widget_reset(state))

    def test_signature_changes_when_route_label_or_structure_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = self._project(tmpdir)
            for name in ("same.png", "a2.png"):
                open(os.path.join(tmpdir, name), "wb").close()
            first = build_lightweight_fork_preview(
                project.prompt_lines,
                scope="selected_routes",
                selected_route_ids=["route_a"],
                project_path=tmpdir,
                path_exists=os.path.exists,
            )
            project.prompt_lines[0].separator_label = "Renamed Route A"
            second = build_lightweight_fork_preview(
                project.prompt_lines,
                scope="selected_routes",
                selected_route_ids=["route_a"],
                project_path=tmpdir,
                path_exists=os.path.exists,
            )
            self.assertNotEqual(first["signature"], second["signature"])

    def test_fork_drops_route_removal_history_without_mutating_source_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = self._project(tmpdir)
            for name in ("same.png", "a2.png"):
                open(os.path.join(tmpdir, name), "wb").close()
            project.project_metadata = {
                "route_removals": [
                    {
                        "id": "active-remove",
                        "route_handle": "route_b",
                        "separator_line_id": "route_b",
                        "line_ids": ["route_b", "b1"],
                        "pre_remove_deleted": {"route_b": False, "b1": False},
                        "changed_to_deleted_line_ids": ["route_b", "b1"],
                        "created_at": "2026-07-15T00:00:00+00:00",
                        "status": "active",
                    },
                    {
                        "id": "consumed-remove",
                        "route_handle": "old_route",
                        "separator_line_id": "old_route",
                        "line_ids": ["old_route"],
                        "pre_remove_deleted": {"old_route": False},
                        "changed_to_deleted_line_ids": ["old_route"],
                        "created_at": "2026-07-14T00:00:00+00:00",
                        "restored_at": "2026-07-14T01:00:00+00:00",
                        "status": "consumed",
                    },
                ],
                "future_metadata": {"keep": True},
            }
            source_metadata = copy.deepcopy(project.project_metadata)
            preview = build_lightweight_fork_preview(
                project.prompt_lines,
                scope="selected_routes",
                selected_route_ids=["route_a", "route_c"],
                project_path=tmpdir,
                path_exists=os.path.exists,
            )

            fork_project, _manifest = build_lightweight_fork_project(project, preview)

            self.assertEqual(source_metadata, project.project_metadata)
            self.assertNotIn("route_removals", fork_project.project_metadata)
            self.assertEqual({"keep": True}, fork_project.project_metadata["future_metadata"])
            fork_path = os.path.join(tmpdir, "fork-project.json")
            save_project_to_json(fork_project, fork_path)
            loaded = load_project_from_json(fork_path)
            self.assertNotIn("route_removals", loaded.project_metadata)
            self.assertEqual([], get_active_route_removal_records(loaded))

    def test_malformed_candidate_and_variant_collections_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = self._project(tmpdir)
            for name in ("same.png", "a2.png"):
                open(os.path.join(tmpdir, name), "wb").close()
            project.prompt_lines[1].generated_candidates = 123
            project.prompt_lines[1].gallery_variants = object()

            plan = resolve_selected_routes_fork_plan(project, ["route_a"])
            preview = build_lightweight_fork_preview(
                project.prompt_lines,
                scope="selected_routes",
                selected_route_ids=["route_a"],
                project_path=tmpdir,
                path_exists=os.path.exists,
            )

            self.assertTrue(plan["valid"])
            self.assertEqual(0, plan["candidate_removal_count"])
            self.assertEqual(0, plan["gallery_variant_removal_count"])
            self.assertEqual(2, preview["materializable_count"])


if __name__ == "__main__":
    unittest.main()
