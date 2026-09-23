import unittest
from unittest.mock import Mock, patch

from ui import gallery_variant_promotion_lifecycle as lifecycle


class Session(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class GalleryVariantPromotionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.project = object()
        self.updated_project = object()
        self.graph_project = object()
        self.plan = {"signature": "preview"}
        self.plan_kwargs = {
            "scope": "selected_routes",
            "source": "latest",
            "placement": "after_parent",
            "selected_route_ids": ["route_b", "route_a"],
            "resolve_path": lambda path: path,
        }
        self.session = Session(
            project=self.project,
            focused_line_id="previous-focus",
            gallery_variant_promotion_preview=self.plan,
            highlighted_line_id="old-highlight",
            gallery_expanded_line_id="old-expanded",
        )
        self.promote = Mock(return_value="new-line")

    def run_lifecycle(self):
        def build_graph(project):
            self.events.append(("graph", project))
            return self.graph_project

        def focus(line_id):
            self.events.append(("focus", line_id, self.session.project))

        def sync_routes(project):
            self.events.append(("routes", project, self.session.get("highlighted_line_id")))

        def save(reason):
            self.events.append(("save", reason, self.session.get("highlighted_line_id"),
                                self.session.get("gallery_expanded_line_id"),
                                self.session.get("gallery_variant_promotion_preview")))

        return lifecycle.apply_and_publish_batch_gallery_variant_promotion(
            self.project,
            stored_plan=self.plan,
            plan_kwargs=self.plan_kwargs,
            promote_gallery_variant_to_route=self.promote,
            session_state=self.session,
            push_history=lambda: self.events.append(("history", self.session.project)),
            build_graph=build_graph,
            restore_focus_after_graph_update=focus,
            synchronize_selected_routes=sync_routes,
            save_current_project_if_possible=save,
        )

    def test_success_publishes_once_in_existing_order(self):
        result = {
            "applied": True,
            "stale_preview": False,
            "updated_project": self.updated_project,
            "new_line_ids": ["first", "last"],
        }

        def apply(project, plan, *, promote_line, **kwargs):
            self.assertIs(self.project, project)
            self.assertIs(self.plan, plan)
            self.assertEqual(self.plan_kwargs, kwargs)
            self.events.append(("apply", self.session.project))
            self.assertEqual("new-line", promote_line(
                self.updated_project, "parent", {"id": "variant"}, "after_parent"))
            self.promote.assert_called_once_with(
                self.updated_project, "parent", {"id": "variant"},
                manage_state=False, placement="after_parent")
            return result

        with patch.object(lifecycle, "apply_batch_variant_promotion_plan", side_effect=apply):
            self.assertIs(result, self.run_lifecycle())

        self.assertEqual([
            ("apply", self.project),
            ("history", self.project),
            ("graph", self.updated_project),
            ("focus", "previous-focus", self.graph_project),
            ("routes", self.graph_project, "old-highlight"),
            ("save", "gallery variants batch promoted to main lines", "last", "last", self.plan),
        ], self.events)
        self.assertIs(self.graph_project, self.session.project)
        self.assertEqual("last", self.session.highlighted_line_id)
        self.assertEqual("last", self.session.gallery_expanded_line_id)
        self.assertNotIn("gallery_variant_promotion_preview", self.session)

    def test_stale_failed_and_noop_results_do_not_publish(self):
        for result in (
            {"applied": False, "stale_preview": True, "error": "Fresh Preview is required"},
            {"applied": False, "stale_preview": False, "error": "promotion failed"},
            {"applied": False, "stale_preview": False, "error": ""},
        ):
            with self.subTest(result=result):
                with patch.object(lifecycle, "apply_batch_variant_promotion_plan", return_value=result):
                    self.assertIs(result, self.run_lifecycle())
                self.assertEqual([], self.events)
                self.assertIs(self.project, self.session.project)
                self.assertIs(self.plan, self.session.gallery_variant_promotion_preview)
                self.assertEqual("old-highlight", self.session.highlighted_line_id)
                self.assertEqual("old-expanded", self.session.gallery_expanded_line_id)

    def test_apply_exception_propagates_without_publication(self):
        with patch.object(lifecycle, "apply_batch_variant_promotion_plan",
                          side_effect=RuntimeError("validation failed")):
            with self.assertRaisesRegex(RuntimeError, "validation failed"):
                self.run_lifecycle()
        self.assertEqual([], self.events)
        self.assertIs(self.project, self.session.project)
        self.assertIs(self.plan, self.session.gallery_variant_promotion_preview)


if __name__ == "__main__":
    unittest.main()
