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


class _WorkspaceStub:
    def __init__(self, session_state):
        self.session_state = session_state

    def info(self, _message):
        return None

    def markdown(self, _message):
        return None

    def caption(self, _message):
        return None

    def text_input(self, _label, **_kwargs):
        return None

    def checkbox(self, _label, **_kwargs):
        return None


class _SidebarPanel:
    def __init__(self):
        self.messages = []

    def selectbox(self, _label, **kwargs):
        self.messages.append(("selectbox", kwargs.get("key")))
        return kwargs.get("options", [""])[0]

    def caption(self, message):
        self.messages.append(("caption", message))


class _SidebarStub:
    def __init__(self, panel):
        self.panel = panel

    def caption(self, _message):
        return None

    def expander(self, _label, **_kwargs):
        return self.panel


class _InspectorContainer:
    def __init__(self, *, upload=None, pasted=""):
        self.separators = 0
        self.upload = upload
        self.pasted = pasted

    def markdown(self, message):
        if message == "---":
            self.separators += 1

    def caption(self, _message):
        return None

    def file_uploader(self, _label, **_kwargs):
        return self.upload

    def text_area(self, _label, **_kwargs):
        return self.pasted

    def button(self, _label, **_kwargs):
        return False


class _InspectionContainer:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def error(self, message):
        self.messages.append(("error", message))

    def success(self, message):
        self.messages.append(("success", message))

    def dataframe(self, *_args, **_kwargs):
        return None

    def caption(self, _message):
        return None

    def code(self, *_args, **_kwargs):
        return None

    def checkbox(self, _label, **_kwargs):
        return False


class ComfyUiAnalysisWorkspacePerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.source = (cls.root / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(cls.source)
        cls.functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def _load(self, names, namespace):
        helper_names = (
            "_get_comfyui_analysis_workspace_drafts",
            "_normalize_comfyui_draft_scalar",
            "_prepare_comfyui_draft_widget",
            "_snapshot_comfyui_draft_widget",
            "_comfyui_draft_option_id",
            "_prepare_comfyui_draft_option",
            "_normalize_comfyui_draft_option",
            "_snapshot_comfyui_draft_option",
            "_clear_comfy_workflow_inspector_state",
        )
        names = [*helper_names, *names]
        module = ast.Module(
            body=[self.functions[name] for name in names],
            type_ignores=[],
        )
        ast.fix_missing_locations(module)
        exec(compile(module, "app.py", "exec"), namespace)
        return namespace

    def test_active_workspace_calls_composite_once_without_passive_save(self):
        state = _SessionState(
            comfy_workflow_path="workflow.json",
            comfy_workflow_preset="",
        )
        st = _WorkspaceStub(state)
        calls = {"ensure": 0, "resolve": 0, "composite": 0, "save": 0}

        def count(name, result=None):
            def inner(*_args, **_kwargs):
                calls[name] += 1
                return result

            return inner

        namespace = self._load(
            ["render_comfyui_settings_workspace"],
            {
                "st": st,
                "ensure_comfy_settings_session_state": count("ensure"),
                "update_comfy_settings": count("save"),
                "resolve_effective_comfy_workflow_path": count(
                    "resolve", ("C:/workflow.json", "project")
                ),
                "render_comfy_workflow_inspector": count("composite"),
            },
        )

        namespace["render_comfyui_settings_workspace"]()

        self.assertEqual(
            {"ensure": 1, "resolve": 1, "composite": 1, "save": 0},
            calls,
        )

    def test_passive_daily_sidebar_runs_no_analysis_or_workflow_parsing(self):
        state = _SessionState(
            comfy_url="127.0.0.1:8188",
            comfy_workflow_path="workflow.json",
            comfy_workflow_preset="",
            force_shared_comfy_workflow=False,
        )
        panel = _SidebarPanel()
        st = types.SimpleNamespace(
            session_state=state,
            sidebar=_SidebarStub(panel),
        )
        calls = {
            "ensure": 0,
            "resolve": 0,
            "save": 0,
            "analysis": 0,
            "parse": 0,
        }

        def ensure():
            calls["ensure"] += 1
            return [""]

        def resolve(_path):
            calls["resolve"] += 1
            return ("C:/workflow.json", "project")

        def save():
            calls["save"] += 1

        namespace = self._load(
            ["render_comfyui_daily_sidebar_section"],
            {
                "st": st,
                "ensure_comfy_settings_session_state": ensure,
                "update_comfy_settings": save,
                "resolve_effective_comfy_workflow_path": resolve,
                "render_comfy_workflow_inspector": (
                    lambda *_args, **_kwargs: calls.__setitem__(
                        "analysis", calls["analysis"] + 1
                    )
                ),
                "parse_workflow_json": (
                    lambda *_args, **_kwargs: calls.__setitem__(
                        "parse", calls["parse"] + 1
                    )
                ),
            },
        )

        namespace["render_comfyui_daily_sidebar_section"]()

        self.assertEqual(1, calls["ensure"])
        self.assertEqual(1, calls["resolve"])
        self.assertEqual(0, calls["save"])
        self.assertEqual(0, calls["analysis"])
        self.assertEqual(0, calls["parse"])
        self.assertIn(("selectbox", "comfy_workflow_preset"), panel.messages)

    def test_composite_dispatches_each_analysis_and_inspector_section_once(self):
        state = _SessionState(
            settings={"comfyui_workflow_path": "workflow.json"},
            comfy_workflow_path="workflow.json",
        )
        st = types.SimpleNamespace(session_state=state)
        container = _InspectorContainer()
        calls = {
            "generation": 0,
            "negative": 0,
            "inspect": 0,
            "prompt_export": 0,
            "lora_mapping": 0,
            "lora_export": 0,
        }

        def count(name):
            return lambda *_args, **_kwargs: calls.__setitem__(
                name, calls[name] + 1
            )

        namespace = self._load(
            ["render_comfy_workflow_inspector"],
            {
                "st": st,
                "os": __import__("os"),
                "render_generation_settings_consistency_panel": count(
                    "generation"
                ),
                "render_negative_prompt_consistency_panel": count("negative"),
                "resolve_effective_comfy_workflow_path": (
                    lambda _path: ("C:/workflow.json", "fallback")
                ),
                "_render_comfy_workflow_inspection": count("inspect"),
                "render_comfy_prompt_injection_export": count("prompt_export"),
                "render_lora_directory_mapping": count("lora_mapping"),
                "render_lora_loader_injection_export": count("lora_export"),
            },
        )

        namespace["render_comfy_workflow_inspector"](container)

        self.assertEqual(
            {
                "generation": 1,
                "negative": 1,
                "inspect": 1,
                "prompt_export": 1,
                "lora_mapping": 1,
                "lora_export": 1,
            },
            calls,
        )

    def test_workflow_parser_runs_only_for_nonempty_inspection_input(self):
        parse_calls = []
        summarize_calls = []
        container = _InspectionContainer()
        namespace = self._load(
            ["_render_comfy_workflow_inspection"],
            {
                "st": types.SimpleNamespace(session_state=_SessionState()),
                "parse_workflow_json": (
                    lambda raw: parse_calls.append(raw) or {"1": {}}
                ),
                "detect_workflow_shape": lambda _data: "api",
                "summarize_workflow_nodes": (
                    lambda data: summarize_calls.append(data)
                    or [
                        {
                            "node_id": "1",
                            "class_type": "KSampler",
                            "role": "Sampler",
                            "editable_fields": {},
                        }
                    ]
                ),
                "json": __import__("json"),
            },
        )

        namespace["_render_comfy_workflow_inspection"]("", "empty", container)
        self.assertEqual([], parse_calls)
        self.assertEqual([], summarize_calls)

        namespace["_render_comfy_workflow_inspection"](
            '{"1": {}}', "pasted JSON", container
        )
        self.assertEqual(['{"1": {}}'], parse_calls)
        self.assertEqual(1, len(summarize_calls))

    def test_invalid_and_unknown_workflow_input_fail_locally(self):
        invalid_container = _InspectionContainer()
        invalid_namespace = self._load(
            ["_render_comfy_workflow_inspection"],
            {
                "st": types.SimpleNamespace(),
                "parse_workflow_json": (
                    lambda _raw: (_ for _ in ()).throw(ValueError("invalid JSON"))
                ),
                "detect_workflow_shape": lambda _data: "unknown",
                "summarize_workflow_nodes": lambda _data: [],
                "json": __import__("json"),
            },
        )

        invalid_namespace["_render_comfy_workflow_inspection"](
            "{", "pasted JSON", invalid_container
        )
        self.assertIn(("error", "invalid JSON"), invalid_container.messages)

        unknown_container = _InspectionContainer()
        unknown_namespace = self._load(
            ["_render_comfy_workflow_inspection"],
            {
                "st": types.SimpleNamespace(),
                "parse_workflow_json": lambda _raw: {"not": "nodes"},
                "detect_workflow_shape": lambda _data: "unknown",
                "summarize_workflow_nodes": lambda _data: [],
                "json": __import__("json"),
            },
        )
        unknown_namespace["_render_comfy_workflow_inspection"](
            '{"not":"nodes"}', "pasted JSON", unknown_container
        )
        self.assertTrue(
            any(
                kind == "error" and "Unsupported or empty" in message
                for kind, message in unknown_container.messages
            )
        )

    def test_existing_upload_over_paste_precedence_is_preserved(self):
        upload = types.SimpleNamespace(
            name="uploaded.json",
            getvalue=lambda: b'{"upload": true}',
        )
        container = _InspectorContainer(
            upload=upload,
            pasted='{"paste": true}',
        )
        state = _SessionState(
            settings={"comfyui_workflow_path": "workflow.json"},
            comfy_workflow_path="workflow.json",
        )
        st = types.SimpleNamespace(session_state=state)
        inspected = []
        namespace = self._load(
            ["render_comfy_workflow_inspector"],
            {
                "st": st,
                "os": __import__("os"),
                "render_generation_settings_consistency_panel": (
                    lambda **_kwargs: None
                ),
                "render_negative_prompt_consistency_panel": (
                    lambda **_kwargs: None
                ),
                "resolve_effective_comfy_workflow_path": (
                    lambda _path: ("C:/missing.json", "fallback")
                ),
                "_render_comfy_workflow_inspection": (
                    lambda raw, source, **_kwargs: inspected.append((raw, source))
                ),
                "render_comfy_prompt_injection_export": (
                    lambda *_args, **_kwargs: None
                ),
                "render_lora_directory_mapping": (
                    lambda *_args, **_kwargs: None
                ),
                "render_lora_loader_injection_export": (
                    lambda *_args, **_kwargs: None
                ),
            },
        )

        namespace["render_comfy_workflow_inspector"](container)

        self.assertEqual([('{"upload": true}', "uploaded.json")], inspected)
        self.assertEqual('{"upload": true}', state.comfy_workflow_inspector_raw_text)
        self.assertEqual("uploaded.json", state.comfy_workflow_inspector_source)


if __name__ == "__main__":
    unittest.main()
