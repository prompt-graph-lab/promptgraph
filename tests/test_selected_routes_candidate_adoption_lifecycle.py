from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ui import selected_routes_candidate_adoption_lifecycle as lifecycle


class Session(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class SelectedRoutesCandidateAdoptionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.project = object()
        self.updated_project = object()
        self.line = SimpleNamespace(id="adopted", generated_candidates=[{"path": "candidate.png"}])
        self.other_line = SimpleNamespace(id="untouched")
        self.graph_project = SimpleNamespace(prompt_lines=[self.other_line, self.line])
        self.preview = {"signature": "fresh"}
        self.session = Session(
            project=self.project,
            current_project_path="project.json",
            focused_line_id="previous-focus",
            route_batch_candidate_adoption_preview=self.preview,
        )
        self.selected_route_ids = ["route_b", "route_a"]
        self.resolve_path = lambda path: path
        self.path_exists = lambda path: True
        self.fail_at = None

    def run_lifecycle(self):
        def history():
            self.events.append(("history", self.session.project))
            if self.fail_at == "history":
                raise RuntimeError("history failure")

        def graph(project):
            self.events.append(("graph", project, self.session.project))
            if self.fail_at == "graph":
                raise RuntimeError("graph failure")
            return self.graph_project

        def candidates(line):
            self.events.append(("candidates", line, self.session.project))
            return line.generated_candidates

        def sync(line, records):
            self.events.append(("sync", line, records, self.session.project))
            if self.fail_at == "sync":
                raise RuntimeError("sync failure")

        def focus(line_id):
            self.events.append(("focus", line_id, self.session.project))

        def text_areas():
            self.events.append(("text", self.session.project))

        def save(reason):
            self.events.append(("save", reason, self.session.project,
                                self.session.get("route_batch_candidate_adoption_preview"),
                                self.session.get("route_batch_candidate_adoption_apply_result")))
            if self.fail_at == "save":
                raise RuntimeError("save failure")

        return lifecycle.apply_and_publish_selected_routes_candidate_adoption(
            self.project,
            self.selected_route_ids,
            expected_signature="fresh",
            source="latest",
            session_state=self.session,
            resolve_path=self.resolve_path,
            path_exists=self.path_exists,
            push_history=history,
            build_graph=graph,
            get_persistent_line_candidates=candidates,
            sync_line_generated_candidates_to_session=sync,
            restore_focus_after_graph_update=focus,
            sync_text_areas=text_areas,
            save_current_project_if_possible=save,
        )

    def test_success_publishes_once_in_existing_order_and_hands_result_to_renderer(self):
        result = {
            "applied": True,
            "applied_count": 1,
            "applied_line_ids": ["adopted"],
            "updated_project": self.updated_project,
            "error": "",
        }

        def apply(project, route_ids, **kwargs):
            self.assertIs(self.project, project)
            self.assertIs(self.selected_route_ids, route_ids)
            self.assertEqual("fresh", kwargs["expected_signature"])
            self.assertEqual("latest", kwargs["source"])
            self.assertEqual("project.json", kwargs["project_path"])
            self.assertIs(self.resolve_path, kwargs["resolve_path"])
            self.assertIs(self.path_exists, kwargs["path_exists"])
            self.events.append(("apply", self.session.project))
            return result

        with patch.object(lifecycle, "apply_selected_routes_candidate_adoption", side_effect=apply):
            self.assertIs(result, self.run_lifecycle())

        self.assertEqual([
            ("apply", self.project),
            ("history", self.project),
            ("graph", self.updated_project, self.updated_project),
            ("candidates", self.line, self.graph_project),
            ("sync", self.line, self.line.generated_candidates, self.graph_project),
            ("focus", "previous-focus", self.graph_project),
            ("text", self.graph_project),
            ("save", "route-scope candidates batch adopted", self.graph_project,
             self.preview, None),
        ], self.events)
        self.assertIs(self.graph_project, self.session.project)
        self.assertNotIn("updated_project", result)
        self.assertNotIn("route_batch_candidate_adoption_preview", self.session)
        self.assertIs(result, self.session.route_batch_candidate_adoption_apply_result)

    def test_stale_failed_rejected_and_noop_results_only_clean_operation_state(self):
        for applied, count, error in (
            (False, 0, "stale preview"),
            (False, 0, "apply failed"),
            (False, 1, "rejected"),
            (True, 0, "no targets"),
        ):
            with self.subTest(applied=applied, count=count, error=error):
                result = {
                    "applied": applied,
                    "applied_count": count,
                    "error": error,
                    "updated_project": self.updated_project,
                }
                self.events.clear()
                self.session["route_batch_candidate_adoption_preview"] = self.preview
                self.session.pop("route_batch_candidate_adoption_apply_result", None)
                with patch.object(lifecycle, "apply_selected_routes_candidate_adoption",
                                  return_value=result):
                    self.assertIs(result, self.run_lifecycle())
                self.assertEqual([], self.events)
                self.assertIs(self.project, self.session.project)
                self.assertNotIn("updated_project", result)
                self.assertNotIn("route_batch_candidate_adoption_preview", self.session)
                self.assertIs(result, self.session.route_batch_candidate_adoption_apply_result)

    def test_apply_exception_leaves_preview_and_project_untouched(self):
        with patch.object(lifecycle, "apply_selected_routes_candidate_adoption",
                          side_effect=RuntimeError("apply exception")):
            with self.assertRaisesRegex(RuntimeError, "apply exception"):
                self.run_lifecycle()
        self.assertEqual([], self.events)
        self.assertIs(self.project, self.session.project)
        self.assertIs(self.preview, self.session.route_batch_candidate_adoption_preview)
        self.assertNotIn("route_batch_candidate_adoption_apply_result", self.session)

    def test_callback_failures_keep_the_existing_partial_publication_order(self):
        for failing_step, expected_events, expected_project in (
            ("history", ["history"], self.project),
            ("graph", ["history", "graph"], self.updated_project),
            ("sync", ["history", "graph", "candidates", "sync"], self.graph_project),
            ("save", ["history", "graph", "candidates", "sync", "focus", "text", "save"],
             self.graph_project),
        ):
            with self.subTest(failing_step=failing_step):
                self.events.clear()
                self.fail_at = failing_step
                self.session["project"] = self.project
                self.session["route_batch_candidate_adoption_preview"] = self.preview
                self.session.pop("route_batch_candidate_adoption_apply_result", None)
                result = {
                    "applied": True, "applied_count": 1, "applied_line_ids": ["adopted"],
                    "updated_project": self.updated_project,
                }
                with patch.object(lifecycle, "apply_selected_routes_candidate_adoption",
                                  return_value=result):
                    with self.assertRaisesRegex(RuntimeError, failing_step + " failure"):
                        self.run_lifecycle()
                self.assertEqual(expected_events, [event[0] for event in self.events])
                self.assertIs(expected_project, self.session.project)
                self.assertIs(self.preview, self.session.route_batch_candidate_adoption_preview)
                self.assertNotIn("route_batch_candidate_adoption_apply_result", self.session)


if __name__ == "__main__":
    unittest.main()
