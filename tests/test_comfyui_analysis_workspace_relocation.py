import ast
import types
import unittest
from pathlib import Path


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class _EmptyStateContainer:
    def __init__(self):
        self.messages = []

    def markdown(self, message):
        self.messages.append(("markdown", message))

    def caption(self, message):
        self.messages.append(("caption", message))

    def info(self, message):
        self.messages.append(("info", message))


class ComfyUiAnalysisWorkspaceRelocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.source = (cls.root / "app.py").read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        cls.functions = {
            node.name: node
            for node in cls.tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def _source(self, name):
        return ast.get_source_segment(self.source, self.functions[name])

    def _load(self, names, namespace):
        module = ast.Module(
            body=[self.functions[name] for name in names],
            type_ignores=[],
        )
        ast.fix_missing_locations(module)
        exec(compile(module, "app.py", "exec"), namespace)
        return namespace

    def test_composite_has_one_workspace_owner_and_no_sidebar_owner(self):
        workspace = self._source("render_comfyui_settings_workspace")
        daily = self._source("render_comfyui_daily_sidebar_section")
        composite = self._source("render_comfy_workflow_inspector")

        self.assertEqual(1, workspace.count("render_comfy_workflow_inspector(st)"))
        self.assertNotIn("render_comfy_workflow_inspector", daily)
        self.assertEqual(
            1,
            composite.count(
                "render_generation_settings_consistency_panel(container=container)"
            ),
        )
        self.assertEqual(
            1,
            composite.count(
                "render_negative_prompt_consistency_panel(container=container)"
            ),
        )

    def test_inspector_widget_keys_are_preserved_and_unique(self):
        for key in (
            "comfy_workflow_inspector_upload",
            "comfy_workflow_inspector_text",
            "comfy_workflow_inspector_load_path",
            "comfy_workflow_inspector_clear",
            "comfy_workflow_inspector_show_fields",
        ):
            self.assertEqual(1, self.source.count(f'key="{key}"'), key)

    def test_daily_sidebar_keeps_only_daily_configuration_controls(self):
        daily = self._source("render_comfyui_daily_sidebar_section")
        self.assertIn('key="comfy_workflow_preset"', daily)
        self.assertIn("Resolved source:", daily)
        self.assertIn("Resolved workflow path:", daily)
        self.assertIn("Force shared workflow:", daily)
        for removed in (
            "render_comfy_workflow_inspector",
            "render_generation_settings_consistency_panel",
            "render_negative_prompt_consistency_panel",
            "analyze_generation_settings",
            "analyze_negative_prompts",
            "parse_workflow_json",
            "summarize_workflow_nodes",
            "comfy_workflow_inspector_upload",
            "comfy_workflow_inspector_text",
        ):
            self.assertNotIn(removed, daily)

    def test_analysis_scope_remains_project_wide_and_read_only(self):
        analysis_sources = "\n".join(
            self._source(name)
            for name in (
                "render_generation_settings_consistency_panel",
                "render_negative_prompt_consistency_panel",
            )
        )
        self.assertEqual(
            2,
            analysis_sources.count(
                'project = st.session_state.get("project")'
            ),
        )
        self.assertEqual(
            2,
            analysis_sources.count("visible_lines = get_visible_prompt_lines(project)"),
        )
        for unrelated_scope in (
            "graph_edit_illustration_page",
            "graph_edit_illustration_filter",
            "graph_edit_collapsed_group_keys",
            "gallery_page",
            "gallery_selected_route_ids",
            "selected_lines",
        ):
            self.assertNotIn(unrelated_scope, analysis_sources)
        for mutation in (
            "push_history",
            "save_current_project",
            "save_project_to_json",
            "save_settings",
            "autosave",
            "generate_image_with_progress",
        ):
            self.assertNotIn(mutation, analysis_sources)

    def test_no_project_analysis_panels_render_compact_empty_states(self):
        state = _SessionState(project=None)
        st = types.SimpleNamespace(session_state=state)
        generation_container = _EmptyStateContainer()
        negative_container = _EmptyStateContainer()

        def unexpected_analysis(*_args, **_kwargs):
            raise AssertionError("analysis must not run without visible lines")

        namespace = self._load(
            [
                "render_generation_settings_consistency_panel",
                "render_negative_prompt_consistency_panel",
            ],
            {
                "st": st,
                "get_visible_prompt_lines": lambda project: [],
                "analyze_generation_settings": unexpected_analysis,
                "analyze_negative_prompts": unexpected_analysis,
            },
        )

        namespace["render_generation_settings_consistency_panel"](
            generation_container
        )
        namespace["render_negative_prompt_consistency_panel"](
            negative_container
        )

        self.assertTrue(
            any(
                kind == "info" and "Load a PromptGraph project" in message
                for kind, message in generation_container.messages
            )
        )
        self.assertTrue(
            any(
                kind == "info" and "Load a PromptGraph project" in message
                for kind, message in negative_container.messages
            )
        )

    def test_workspace_discloses_read_only_and_production_boundaries(self):
        workspace = self._source("render_comfyui_settings_workspace")
        self.assertIn("#### Environment", workspace)
        self.assertIn("#### Analysis & Inspection / 分析・検査", workspace)
        self.assertIn("Project全体の表示対象イラスト", workspace)
        self.assertIn("Analysis is read-only", workspace)
        self.assertIn("Generation remains in Gallery and Focus Edit", workspace)
        for forbidden in (
            "generate_image_with_progress",
            "save_settings(",
            "save_project",
            "push_history",
        ):
            self.assertNotIn(forbidden, workspace)


if __name__ == "__main__":
    unittest.main()
