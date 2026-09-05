"""Exercise the retained app callers with their real extracted imports.

Like the existing UI wiring tests, load only the relevant app definitions to
avoid executing Streamlit's top-level UI or reading a user's settings.
"""

import ast
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from core.comfyui import inject_prompt_to_workflow
from core.io import find_image_metadata_for_line, load_project_from_json, save_project_to_json
from core.operations import get_active_tokens


ROOT = Path(__file__).resolve().parents[1]


class AppExtractedPromptIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        names = {
            "_load_json_from_text", "_is_executable_comfy_workflow",
            "_workflow_text_from_line_metadata", "_build_line_workflow_from_text",
            "build_single_line_workflow", "_markdown_code", "render_prompt_syntax_diagnostics",
        }
        nodes = [node for node in tree.body if (
            isinstance(node, ast.ImportFrom)
            and node.module in {"core.prompt_inspection", "core.comfy_prompt_binding"}
        ) or (isinstance(node, ast.FunctionDef) and node.name in names)]
        cls.code = compile(ast.Module(body=nodes, type_ignores=[]), str(ROOT / "app.py"), "exec")

    def setUp(self):
        self.st = SimpleNamespace(session_state={}, caption=Mock(), markdown=Mock(), warning=Mock())
        self.namespace = {
            "st": self.st, "json": json, "copy": copy,
            "find_image_metadata_for_line": find_image_metadata_for_line,
            "get_active_tokens": get_active_tokens,
            "inject_prompt_to_workflow": inject_prompt_to_workflow,
        }
        exec(self.code, self.namespace)

    def test_syntax_renderer_uses_imported_diagnostics_and_existing_messages(self):
        self.namespace["render_prompt_syntax_diagnostics"]("<mod:衣装>, 1::blue, 2::green", fragment_limit=1)
        self.assertEqual(self.st.markdown.call_args_list[0].args, ("- `衣装`",))
        self.assertEqual(self.st.markdown.call_args_list[1].args, ("- `1::blue`",))
        self.st.warning.assert_called_once()
        self.st.caption.assert_any_call("1 more suspicious fragment(s) not shown.")

    def test_workflow_builder_preserves_placeholder_escaping_and_missing_injection_warning(self):
        line = SimpleNamespace(current_text='quote " and slash \\ and\n青', negative_prompt="")
        build = self.namespace["_build_line_workflow_from_text"]
        result, warning = build('{"p":{"inputs":{"text":"__PROMPT__"}}}', line, {})
        self.assertEqual(result["p"]["inputs"]["text"], line.current_text)
        self.assertEqual(warning, "")
        result, warning = build('{"unknown":{}}', line, {})
        self.assertEqual(result, {"unknown": {}})
        self.assertEqual(warning, "The workflow JSON does not contain '__PROMPT__'. The prompt may not be injected.")

    def test_workflow_builder_keeps_group_mapping_branch(self):
        line = SimpleNamespace(current_text="smile")
        inject = Mock(return_value={"mapped": True})
        self.namespace["inject_prompt_to_workflow"] = inject
        mapping = {"group_map": {"default": "p"}}
        self.assertEqual(self.namespace["_build_line_workflow_from_text"]("{}", line, {"comfy_mapping": mapping}),
                         ({"mapped": True}, ""))
        inject.assert_called_once_with({}, {"default": ["smile"]}, mapping, fallback_prompt="smile")

    def test_legacy_project_can_preview_and_round_trip_without_data_changes(self):
        project = load_project_from_json(str(ROOT / "tests/fixtures/release/legacy_project_minimal.json"))
        line = project.prompt_lines[0]
        workflow = {"p": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow_path = root / "workflow.json"
            workflow_path.write_text(json.dumps(workflow), encoding="utf-8")
            self.namespace["resolve_effective_comfy_workflow_path"] = lambda path: (str(path), "test")
            before = copy.deepcopy(project)
            save_project_to_json(project, str(root / "before.json"))
            built, warning = self.namespace["build_single_line_workflow"](
                str(workflow_path), line, {"force_shared_comfy_workflow": True}, project=project,
            )
            self.namespace["get_structural_stats"](line.original_text, line.current_text)
            self.namespace["_prompt_token_diff"](line.original_text, line.current_text)
            self.namespace["_workflow_submitted_prompt_debug"](built, line)
            save_project_to_json(project, str(root / "after.json"))
            self.assertEqual(warning, "")
            self.assertEqual(built["p"]["inputs"]["text"], line.current_text)
            self.assertEqual(project, before)
            self.assertEqual(workflow_path.read_text(encoding="utf-8"), json.dumps(workflow))
            self.assertEqual(json.loads((root / "before.json").read_text(encoding="utf-8")),
                             json.loads((root / "after.json").read_text(encoding="utf-8")))
            reopened = load_project_from_json(str(root / "after.json"))
            self.assertEqual(reopened.prompt_lines, project.prompt_lines)
            self.assertEqual(reopened.module_library, project.module_library)

    def test_embedded_workflow_uses_expanded_module_prompt_without_mutating_line(self):
        project = load_project_from_json(str(ROOT / "tests/fixtures/release/legacy_project_minimal.json"))
        line = project.prompt_lines[0]
        line.current_text = "<mod:旧式キャラクター>"
        before = copy.deepcopy(project)
        workflow = {"p": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}}}
        metadata = {"raw_metadata": {"PROMPT": json.dumps(workflow)}}
        self.namespace["find_image_metadata_for_line"] = lambda _project, _line: metadata
        fallback = Mock(side_effect=AssertionError("Embedded workflow should avoid filesystem fallback"))
        self.namespace["resolve_effective_comfy_workflow_path"] = fallback
        result, warning = self.namespace["build_single_line_workflow"]("unused", line, {}, project=project)
        self.assertEqual(result["p"]["inputs"]["text"], "青い髪, smile")
        self.assertEqual(warning, "")
        self.assertEqual(project, before)
        self.assertEqual(json.loads(metadata["raw_metadata"]["PROMPT"]), workflow)
        fallback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
