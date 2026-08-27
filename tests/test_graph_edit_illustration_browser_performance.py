import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from core.graph_edit_illustration_browser import (
    build_graph_edit_illustration_browser_plan,
)
from core.project import Project, PromptLine


def _line(line_id, *, line_type=None, text="prompt"):
    return PromptLine(
        id=line_id,
        original_file_name=line_id,
        original_index=0,
        current_index=0,
        original_text=text,
        current_text=text,
        tokens=[text],
        line_type=line_type,
        separator_label=text if line_type == "separator" else None,
    )


def _large_project():
    lines = []
    for scene_index in range(5):
        lines.append(
            _line(
                f"scene_{scene_index}",
                line_type="separator",
                text=f"Scene {scene_index}",
            )
        )
        lines.extend(
            _line(f"scene_{scene_index}_line_{line_index}")
            for line_index in range(24)
        )
    for index, line in enumerate(lines):
        line.original_index = index
        line.current_index = index
    return Project(prompt_lines=lines)


class GraphEditIllustrationBrowserPerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        source = app_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "render_graph_edit_illustration_browser_page"
        )
        module = ast.Module(body=[function], type_ignores=[])
        ast.fix_missing_locations(module)
        namespace = {"st": SimpleNamespace(markdown=Mock())}
        exec(compile(module, "app.py", "exec"), namespace)
        cls.dispatch = staticmethod(namespace["render_graph_edit_illustration_browser_page"])

    def setUp(self):
        self.project = _large_project()
        self.authoritative = list(self.project.prompt_lines)

    def _dispatch(self, plan):
        editor = Mock()
        self.dispatch(self.project, plan, editor_renderer=editor)
        return editor

    def test_default_page_dispatches_only_twelve_of_125_records(self):
        plan = build_graph_edit_illustration_browser_plan(
            self.project,
            self.authoritative,
        )
        editor = self._dispatch(plan)
        self.assertEqual(125, plan["total_count"])
        self.assertEqual(12, editor.call_count)

    def test_collapsed_scene_records_are_never_dispatched(self):
        plan = build_graph_edit_illustration_browser_plan(
            self.project,
            self.authoritative,
            collapsed_group_keys={"scene:scene_0"},
            page_size=48,
        )
        editor = self._dispatch(plan)
        rendered_ids = {call.args[1].id for call in editor.call_args_list}
        self.assertFalse(any(line_id.startswith("scene_0") for line_id in rendered_ids))

    def test_specific_scene_dispatches_no_other_scene(self):
        plan = build_graph_edit_illustration_browser_plan(
            self.project,
            self.authoritative,
            filter_value="scene:scene_3",
            page_size=48,
        )
        editor = self._dispatch(plan)
        rendered_ids = {call.args[1].id for call in editor.call_args_list}
        self.assertTrue(rendered_ids)
        self.assertTrue(all(line_id.startswith("scene_3") for line_id in rendered_ids))

    def test_expensive_helpers_run_only_for_current_page_records(self):
        plan = build_graph_edit_illustration_browser_plan(
            self.project,
            self.authoritative,
        )
        page_ids = {entry["line_id"] for entry in plan["page_entries"]}
        hidden_ids = {
            entry["line_id"] for entry in plan["all_entries"]
        } - page_ids
        helpers = {
            name: Mock()
            for name in ("metadata", "image_preview", "candidate", "lineage")
        }

        def editor(_project, line, *, reorder_disabled=False):
            del reorder_disabled
            for helper in helpers.values():
                helper(line.id)

        self.dispatch(self.project, plan, editor_renderer=editor)
        for helper in helpers.values():
            called_ids = {call.args[0] for call in helper.call_args_list}
            self.assertEqual(page_ids, called_ids)
            self.assertFalse(hidden_ids & called_ids)


if __name__ == "__main__":
    unittest.main()
