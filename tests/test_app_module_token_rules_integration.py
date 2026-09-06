"""Exercise retained UI owners with the real app import, without starting UI."""

import ast
from contextlib import nullcontext
import copy
import html
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from core.operations import ATTRIBUTE_LABEL_UNASSIGNED, get_token_attribute_label
from core.parser import is_structural_mod_marker, parse_prompt
from core.project import Project


class _Rerun(Exception):
    pass


class AppModuleTokenRulesIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / "app.py").read_text(encoding="utf-8"))
        names = {"render_module_token_inspector", "_module_inspector_row_records",
                 "render_module_match_prompt_preview", "_attribute_group_tokens_from_text"}
        nodes = [node for node in tree.body if (
            isinstance(node, ast.ImportFrom) and node.module == "core.module_token_rules"
        ) or (isinstance(node, ast.FunctionDef) and node.name in names)]
        cls.code = compile(ast.Module(body=nodes, type_ignores=[]), str(root / "app.py"), "exec")

    def setUp(self):
        self.project = Project(module_library={"face": {
            "body": "(Smile:1.2), smile, sky", "core_tokens": ["smile"],
            "extension": {"preserve": ["metadata"]},
        }})
        self.state = {"body": "(Smile:1.2), smile, sky", "core": "smile", "unrelated": "keep"}
        self.history = Mock()
        self.st = SimpleNamespace(
            session_state=self.state,
            markdown=Mock(), info=Mock(),
            column_config=SimpleNamespace(TextColumn=Mock(), CheckboxColumn=Mock(), SelectboxColumn=Mock()),
            data_editor=Mock(side_effect=lambda rows, **kwargs: rows),
            text_input=Mock(return_value=""),
            columns=lambda _count: [nullcontext(), nullcontext()],
            button=Mock(return_value=False),
            rerun=Mock(side_effect=_Rerun),
        )
        self.namespace = {
            "st": self.st, "html": html, "parse_prompt": parse_prompt,
            "is_structural_mod_marker": is_structural_mod_marker,
            "ATTRIBUTE_LABEL_UNASSIGNED": ATTRIBUTE_LABEL_UNASSIGNED,
            "get_token_attribute_label": get_token_attribute_label,
            "get_attribute_label_options": lambda *_args: [ATTRIBUTE_LABEL_UNASSIGNED],
            "push_history": self.history,
        }
        exec(self.code, self.namespace)

    def _render(self, button_key=None):
        if button_key:
            self.st.button.side_effect = lambda _label, **kwargs: kwargs["key"] == button_key
            with self.assertRaises(_Rerun):
                self.namespace["render_module_token_inspector"](self.project, "qa", "face", "body", "core")
        else:
            self.namespace["render_module_token_inspector"](self.project, "qa", "face", "body", "core")

    def test_passive_inspector_marks_weighted_core_without_mutating_project_or_drafts(self):
        before = copy.deepcopy((self.project, self.state))
        self._render()
        rows = self.st.data_editor.call_args.args[0]
        self.assertEqual([row["Core"] for row in rows], [True, True, False])
        self.assertEqual([row["Token"] for row in rows], ["(Smile:1.2)", "smile", "sky"])
        self.assertEqual((self.project, self.state), before)
        self.history.assert_not_called()

    def test_update_body_deduplicates_drafts_and_removes_core_for_removed_tokens(self):
        before = copy.deepcopy(self.project)
        self.st.data_editor.side_effect = None
        self.st.data_editor.return_value = [
            {"Token": "(Smile:1.2)", "Core": True},
            {"Token": "smile", "Core": True},
            {"Token": "sky", "Core": True, "Remove": True},
        ]
        self._render("qa_module_inspector_update_face")
        self.assertEqual(self.state, {"body": "(Smile:1.2)", "core": "(Smile:1.2)", "unrelated": "keep"})
        self.assertEqual(self.project, before)
        self.history.assert_not_called()

    def test_add_token_updates_only_body_draft_and_deduplicates_existing_tokens(self):
        before = copy.deepcopy(self.project)
        self.st.text_input.return_value = " clouds "
        self._render("qa_module_inspector_add_face")
        self.assertEqual(self.state, {"body": "(Smile:1.2), sky, clouds", "core": "smile", "unrelated": "keep"})
        self.assertEqual(self.project, before)
        self.history.assert_not_called()

    def test_preview_matches_weights_but_does_not_highlight_structural_markers(self):
        self.namespace["render_module_match_prompt_preview"](
            "<mod:face>, (Smile:1.2), sky, </mod:face>",
            ["<mod:face>", "smile", "sky", "</mod:face>"], ["smile"],
        )
        rendered = self.st.markdown.call_args.args[0]
        self.assertEqual(rendered.count("background-color:#ffe08a"), 1)
        self.assertEqual(rendered.count("background-color:#d9f99d"), 1)
        self.assertIn("(Smile:1.2)</span>", rendered)
        self.assertIn("&lt;mod:face&gt;", rendered)
        self.assertIn("&lt;/mod:face&gt;", rendered)
        self.assertTrue(self.st.markdown.call_args.kwargs["unsafe_allow_html"])

    def test_attribute_group_input_keeps_the_same_rule_parsing(self):
        self.assertEqual(self.namespace["_attribute_group_tokens_from_text"]("Smile\nSMILE, (smile:1.2)"),
                         ["Smile", "(smile:1.2)"])


if __name__ == "__main__":
    unittest.main()
