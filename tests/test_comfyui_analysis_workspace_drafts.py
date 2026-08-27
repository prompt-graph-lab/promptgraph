import ast
import copy
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


class _Metric:
    def metric(self, *_args, **_kwargs):
        return None


class _WidgetContainer:
    def __init__(self, state, *, upload=None, click_clear=False):
        self.state = state
        self.upload = upload
        self.click_clear = click_clear
        self.dataframes = []
        self.downloads = 0
        self.messages = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def markdown(self, *_args, **_kwargs):
        return None

    def caption(self, message, **_kwargs):
        self.messages.append(("caption", message))

    def info(self, message, **_kwargs):
        self.messages.append(("info", message))

    def warning(self, message, **_kwargs):
        self.messages.append(("warning", message))

    def error(self, message, **_kwargs):
        self.messages.append(("error", message))

    def success(self, message, **_kwargs):
        self.messages.append(("success", message))

    def json(self, *_args, **_kwargs):
        return None

    def code(self, *_args, **_kwargs):
        return None

    def dataframe(self, data, **_kwargs):
        self.dataframes.append(data)

    def columns(self, count):
        return [_Metric() for _ in range(count)]

    def expander(self, *_args, **_kwargs):
        return self

    def file_uploader(self, *_args, **_kwargs):
        return self.upload

    def text_area(self, _label, **kwargs):
        return self.state.get(kwargs["key"], kwargs.get("value", ""))

    def text_input(self, _label, **kwargs):
        return self.state.get(kwargs["key"], kwargs.get("value", ""))

    def checkbox(self, _label, **kwargs):
        return self.state.get(kwargs["key"], kwargs.get("value", False))

    def selectbox(self, _label, **kwargs):
        key = kwargs["key"]
        options = kwargs.get("options", [])
        if key in self.state:
            return self.state[key]
        return options[kwargs.get("index", 0)]

    def radio(self, _label, **kwargs):
        return self.selectbox(_label, **kwargs)

    def number_input(self, _label, **kwargs):
        return self.state.get(kwargs["key"], kwargs.get("value", 0.0))

    def button(self, label, **kwargs):
        clicked = label == "Clear inspector" and self.click_clear
        if clicked and kwargs.get("on_click"):
            kwargs["on_click"]()
        return clicked

    def download_button(self, *_args, **_kwargs):
        self.downloads += 1
        return False


class ComfyUiAnalysisWorkspaceDraftTests(unittest.TestCase):
    HELPER_NAMES = (
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

    def _load(self, names=(), *, state=None, namespace=None):
        ordered_names = list(dict.fromkeys([*self.HELPER_NAMES, *names]))
        module = ast.Module(
            body=[self.functions[name] for name in ordered_names],
            type_ignores=[],
        )
        ast.fix_missing_locations(module)
        state = state if state is not None else _SessionState()
        loaded = {"st": types.SimpleNamespace(session_state=state)}
        loaded.update(namespace or {})
        exec(compile(module, "app.py", "exec"), loaded)
        return loaded, state

    def test_back_reopen_restores_representative_scalar_and_option_drafts(self):
        loaded, state = self._load()
        snapshot_scalar = loaded["_snapshot_comfyui_draft_widget"]
        snapshot_option = loaded["_snapshot_comfyui_draft_option"]
        prepare_scalar = loaded["_prepare_comfyui_draft_widget"]
        prepare_option = loaded["_prepare_comfyui_draft_option"]

        scalar_values = (
            ("inspector", "text", "comfy_workflow_inspector_text", "{\"1\":{}}", ""),
            ("inspector", "show_fields", "comfy_workflow_inspector_show_fields", True, False),
            ("prompt_injection", "manual_negative", "comfy_prompt_injection_manual_negative", "draft negative", ""),
            ("lora_mapping", "directory", "lora_mapping_directory", "C:/models/lora", ""),
            ("lora_injection", "manual_name", "comfy_lora_loader_manual_name", "milk.safetensors", ""),
        )
        for section, draft_key, widget_key, value, default in scalar_values:
            snapshot_scalar(section, draft_key, widget_key, value, default)

        option_values = (
            ("prompt_injection", "line_id", "comfy_prompt_injection_line_id", "line-b", None),
            ("prompt_injection", "positive_node_id", "comfy_prompt_injection_positive_node", {"node_id": "pos-2"}, "node_id"),
            ("prompt_injection", "negative_node_id", "comfy_prompt_injection_negative_node", {"node_id": "neg-2"}, "node_id"),
            ("lora_injection", "target_node_id", "comfy_lora_loader_injection_target", {"node_id": "lora-2"}, "node_id"),
            ("lora_injection", "source", "comfy_lora_loader_injection_source", "Manual", None),
        )
        for section, draft_key, widget_key, value, identity_key in option_values:
            snapshot_option(
                section,
                draft_key,
                widget_key,
                value,
                identity_key=identity_key,
            )

        widget_keys = [item[2] for item in scalar_values + option_values]
        for widget_key in widget_keys:
            state.pop(widget_key, None)

        for section, draft_key, widget_key, _value, default in scalar_values:
            prepare_scalar(section, draft_key, widget_key, default)
        prepare_option(
            "prompt_injection",
            "line_id",
            "comfy_prompt_injection_line_id",
            ["line-a", "line-b"],
        )
        current_nodes = [{"node_id": "pos-1"}, {"node_id": "pos-2"}]
        prepare_option(
            "prompt_injection",
            "positive_node_id",
            "comfy_prompt_injection_positive_node",
            current_nodes,
            identity_key="node_id",
        )
        current_negative_nodes = [{"node_id": ""}, {"node_id": "neg-2"}]
        prepare_option(
            "prompt_injection",
            "negative_node_id",
            "comfy_prompt_injection_negative_node",
            current_negative_nodes,
            identity_key="node_id",
        )
        current_lora_nodes = [{"node_id": "lora-1"}, {"node_id": "lora-2"}]
        prepare_option(
            "lora_injection",
            "target_node_id",
            "comfy_lora_loader_injection_target",
            current_lora_nodes,
            identity_key="node_id",
        )
        prepare_option(
            "lora_injection",
            "source",
            "comfy_lora_loader_injection_source",
            ["Manual", "Extracted prompt LoRA"],
        )

        self.assertEqual('{"1":{}}', state.comfy_workflow_inspector_text)
        self.assertTrue(state.comfy_workflow_inspector_show_fields)
        self.assertEqual("line-b", state.comfy_prompt_injection_line_id)
        self.assertIs(current_nodes[1], state.comfy_prompt_injection_positive_node)
        self.assertIs(current_negative_nodes[1], state.comfy_prompt_injection_negative_node)
        self.assertEqual("draft negative", state.comfy_prompt_injection_manual_negative)
        self.assertEqual("C:/models/lora", state.lora_mapping_directory)
        self.assertIs(current_lora_nodes[1], state.comfy_lora_loader_injection_target)
        self.assertEqual("Manual", state.comfy_lora_loader_injection_source)
        self.assertEqual("milk.safetensors", state.comfy_lora_loader_manual_name)

    def test_invalid_and_malformed_drafts_fail_closed_and_normalize(self):
        project = {"unchanged": [1, 2, 3]}
        project_before = copy.deepcopy(project)
        state = _SessionState(
            project=project,
            comfyui_analysis_workspace_drafts={
                "inspector": ["malformed"],
                "prompt_injection": {"line_id": "missing-line", "positive_node_id": "missing-node"},
                "lora_mapping": {},
                "lora_injection": {"mapped_name": "missing.safetensors", "strengths": "bad"},
            },
        )
        loaded, _state = self._load(state=state)
        prepare_option = loaded["_prepare_comfyui_draft_option"]
        drafts = loaded["_get_comfyui_analysis_workspace_drafts"]()

        line = prepare_option(
            "prompt_injection",
            "line_id",
            "comfy_prompt_injection_line_id",
            ["line-a"],
        )
        node_options = [{"node_id": "node-a"}]
        node = prepare_option(
            "prompt_injection",
            "positive_node_id",
            "comfy_prompt_injection_positive_node",
            node_options,
            identity_key="node_id",
        )
        mapped_options = [{"lora_name": "current.safetensors"}]
        mapped = loaded["_normalize_comfyui_draft_option"](
            "lora_injection",
            "mapped_name",
            mapped_options,
            identity_key="lora_name",
        )

        self.assertEqual("line-a", line)
        self.assertIs(node_options[0], node)
        self.assertIs(mapped_options[0], mapped)
        self.assertEqual("line-a", drafts["prompt_injection"]["line_id"])
        self.assertEqual("node-a", drafts["prompt_injection"]["positive_node_id"])
        self.assertEqual("current.safetensors", drafts["lora_injection"]["mapped_name"])
        self.assertIsInstance(drafts["inspector"], dict)
        self.assertIsInstance(drafts["lora_injection"]["strengths"], dict)
        self.assertEqual(project_before, project)

    def test_option_helper_distinguishes_fresh_explicit_empty_and_invalid(self):
        options = [
            {"node_id": ""},
            {"node_id": "positive"},
            {"node_id": "negative"},
        ]

        loaded, state = self._load()
        prepare = loaded["_prepare_comfyui_draft_option"]
        selected = prepare(
            "prompt_injection",
            "negative_node_id",
            "comfy_prompt_injection_negative_node",
            options,
            identity_key="node_id",
            default_index=2,
        )
        self.assertIs(options[2], selected)
        self.assertEqual(
            "negative",
            state.comfyui_analysis_workspace_drafts["prompt_injection"][
                "negative_node_id"
            ],
        )

        state.comfyui_analysis_workspace_drafts["prompt_injection"][
            "negative_node_id"
        ] = ""
        state.pop("comfy_prompt_injection_negative_node", None)
        selected = prepare(
            "prompt_injection",
            "negative_node_id",
            "comfy_prompt_injection_negative_node",
            options,
            identity_key="node_id",
            default_index=2,
        )
        self.assertIs(options[0], selected)
        state.pop("comfy_prompt_injection_negative_node", None)
        self.assertIs(
            options[0],
            prepare(
                "prompt_injection",
                "negative_node_id",
                "comfy_prompt_injection_negative_node",
                options,
                identity_key="node_id",
                default_index=2,
            ),
        )

        state.comfyui_analysis_workspace_drafts["prompt_injection"][
            "negative_node_id"
        ] = "removed-node"
        state.pop("comfy_prompt_injection_negative_node", None)
        selected = prepare(
            "prompt_injection",
            "negative_node_id",
            "comfy_prompt_injection_negative_node",
            options,
            identity_key="node_id",
            default_index=2,
        )
        self.assertIs(options[2], selected)
        self.assertEqual(
            "negative",
            state.comfyui_analysis_workspace_drafts["prompt_injection"][
                "negative_node_id"
            ],
        )

    def test_normalize_helper_uses_default_only_when_selection_is_absent(self):
        options = [{"node_id": ""}, {"node_id": "negative"}]
        loaded, state = self._load()
        normalize = loaded["_normalize_comfyui_draft_option"]

        selected = normalize(
            "prompt_injection",
            "negative_node_id",
            options,
            identity_key="node_id",
            default_index=1,
        )
        self.assertIs(options[1], selected)

        state.comfyui_analysis_workspace_drafts["prompt_injection"][
            "negative_node_id"
        ] = ""
        selected = normalize(
            "prompt_injection",
            "negative_node_id",
            options,
            identity_key="node_id",
            default_index=1,
        )
        self.assertIs(options[0], selected)

        state.comfyui_analysis_workspace_drafts["prompt_injection"][
            "negative_node_id"
        ] = "removed-node"
        selected = normalize(
            "prompt_injection",
            "negative_node_id",
            options,
            identity_key="node_id",
            default_index=1,
        )
        self.assertIs(options[1], selected)
        self.assertEqual(
            "negative",
            state.comfyui_analysis_workspace_drafts["prompt_injection"][
                "negative_node_id"
            ],
        )

    def test_prompt_injection_restores_stable_ids_and_manual_negative(self):
        line_a = types.SimpleNamespace(id="line-a", current_text="prompt a", negative_prompt="")
        line_b = types.SimpleNamespace(id="line-b", current_text="prompt b", negative_prompt="")
        candidates = [
            {"node_id": "pos-1", "role": "Positive prompt candidate"},
            {"node_id": "neg-1", "role": "Negative prompt candidate"},
        ]
        state = _SessionState(
            project={"project": True},
            comfyui_analysis_workspace_drafts={
                "inspector": {},
                "prompt_injection": {
                    "line_id": "line-b",
                    "positive_node_id": "pos-1",
                    "negative_node_id": "neg-1",
                    "manual_negative": "manual negative",
                },
                "lora_mapping": {},
                "lora_injection": {"strengths": {}},
            },
        )
        container = _WidgetContainer(state)
        loaded, _state = self._load(
            ["render_comfy_prompt_injection_export"],
            state=state,
            namespace={
                "parse_workflow_json": lambda _raw: {"workflow": True},
                "detect_workflow_shape": lambda _data: "api",
                "get_visible_prompt_lines": lambda _project: [line_a, line_b],
                "get_text_encode_candidates": lambda _data: candidates,
                "get_prompt_line_label": lambda line: line.id,
                "_candidate_default_index": lambda rows, role, fallback_index=0: next(
                    (index for index, row in enumerate(rows) if row.get("role") == role),
                    fallback_index,
                ),
                "_comfy_candidate_label": lambda row: row.get("node_id", ""),
                "_line_export_prompt_text": lambda line: line.current_text,
                "inject_prompts_into_api_workflow": lambda *_args, **_kwargs: {},
                "workflow_to_json_text": lambda _data: "{}",
            },
        )

        project_before = copy.deepcopy(state.project)
        loaded["render_comfy_prompt_injection_export"]("{}", "draft", container)

        self.assertEqual("line-b", state.comfy_prompt_injection_line_id)
        self.assertEqual("pos-1", state.comfy_prompt_injection_positive_node["node_id"])
        self.assertEqual("neg-1", state.comfy_prompt_injection_negative_node["node_id"])
        self.assertEqual("manual negative", state.comfy_prompt_injection_manual_negative)
        self.assertEqual(project_before, state.project)

    def test_prompt_injection_fresh_default_and_explicit_leave_unchanged(self):
        line = types.SimpleNamespace(
            id="line-a",
            current_text="prompt",
            negative_prompt="",
        )
        candidates = [
            {"node_id": "positive", "role": "Positive prompt candidate"},
            {"node_id": "negative", "role": "Negative prompt candidate"},
        ]
        state = _SessionState(project={"project": True})
        container = _WidgetContainer(state)
        loaded, _state = self._load(
            ["render_comfy_prompt_injection_export"],
            state=state,
            namespace={
                "parse_workflow_json": lambda _raw: {"workflow": True},
                "detect_workflow_shape": lambda _data: "api",
                "get_visible_prompt_lines": lambda _project: [line],
                "get_text_encode_candidates": lambda _data: candidates,
                "get_prompt_line_label": lambda current: current.id,
                "_candidate_default_index": lambda rows, role, fallback_index=0: next(
                    (index for index, row in enumerate(rows) if row.get("role") == role),
                    fallback_index,
                ),
                "_comfy_candidate_label": lambda row: row.get("node_id", ""),
                "_line_export_prompt_text": lambda current: current.current_text,
                "inject_prompts_into_api_workflow": lambda *_args, **_kwargs: {},
                "workflow_to_json_text": lambda _data: "{}",
            },
        )

        loaded["render_comfy_prompt_injection_export"]("{}", "fresh", container)
        self.assertEqual(
            "positive",
            state.comfy_prompt_injection_positive_node["node_id"],
        )
        self.assertEqual(
            "negative",
            state.comfy_prompt_injection_negative_node["node_id"],
        )

        leave_unchanged = {
            "node_id": "",
            "class_type": "(none)",
            "role": "Leave unchanged",
            "text_preview": "",
        }
        state.comfy_prompt_injection_negative_node = leave_unchanged
        loaded["render_comfy_prompt_injection_export"]("{}", "current", container)
        self.assertEqual(
            "",
            state.comfyui_analysis_workspace_drafts["prompt_injection"][
                "negative_node_id"
            ],
        )

        state.pop("comfy_prompt_injection_negative_node", None)
        loaded["render_comfy_prompt_injection_export"]("{}", "reopen", container)
        self.assertEqual(
            "",
            state.comfy_prompt_injection_negative_node["node_id"],
        )

    def test_lora_scan_results_reappear_without_rescan(self):
        references = [{"name": "milk", "line_id": "line-a", "raw": "<lora:milk:1>"}]
        results = [{"name": "milk", "weights": ["1"], "line_ids": ["line-a"], "status": "found", "matches": ["milk.safetensors"], "candidates": []}]
        signature = (("line-a", "<lora:milk:1>"),)
        state = _SessionState(
            project={"project": True},
            comfyui_analysis_workspace_drafts={
                "inspector": {},
                "prompt_injection": {},
                "lora_mapping": {"directory": "C:/models/lora"},
                "lora_injection": {"strengths": {}},
            },
            lora_mapping_results=results,
            lora_mapping_files=[{"path": "milk.safetensors"}],
            lora_mapping_references=references,
            lora_mapping_reference_signature=signature,
            lora_mapping_scanned_directory="C:/models/lora",
            lora_mapping_error="",
        )
        scans = []
        container = _WidgetContainer(state)
        loaded, _state = self._load(
            ["render_lora_directory_mapping"],
            state=state,
            namespace={
                "get_visible_prompt_lines": lambda _project: [types.SimpleNamespace(id="line-a")],
                "extract_lora_references_from_lines": lambda _lines: references,
                "_lora_reference_signature": lambda _references: signature,
                "scan_lora_directory": lambda path: scans.append(path),
                "match_lora_references_to_files": lambda *_args: [],
                "summarize_mapping_results": lambda _results: {
                    "total": 1,
                    "found": 1,
                    "candidates": 0,
                    "missing": 0,
                },
            },
        )

        loaded["render_lora_directory_mapping"](container)

        self.assertEqual("C:/models/lora", state.lora_mapping_directory)
        self.assertEqual([], scans)
        self.assertEqual(1, len(container.dataframes))
        self.assertEqual(results, state.lora_mapping_results)

    def test_lora_injection_restores_target_source_name_and_strengths(self):
        candidates = [
            {"node_id": "lora-1", "can_inject": True},
            {"node_id": "lora-2", "can_inject": True},
        ]
        state = _SessionState(
            project={"project": True},
            comfyui_analysis_workspace_drafts={
                "inspector": {},
                "prompt_injection": {},
                "lora_mapping": {"directory": ""},
                "lora_injection": {
                    "target_node_id": "lora-2",
                    "source": "Manual",
                    "manual_name": "milk.safetensors",
                    "strengths": {"stable": {"model": 0.75, "clip": 0.5}},
                },
            },
        )
        container = _WidgetContainer(state)
        loaded, _state = self._load(
            ["render_lora_loader_injection_export"],
            state=state,
            namespace={
                "parse_workflow_json": lambda _raw: {"workflow": True},
                "detect_workflow_shape": lambda _data: "api",
                "get_lora_loader_candidates": lambda _data: candidates,
                "_lora_loader_candidate_label": lambda row: row["node_id"],
                "get_visible_prompt_lines": lambda _project: [],
                "extract_lora_references_from_lines": lambda _lines: [],
                "_dedupe_lora_reference_options": lambda _refs: [],
                "_lora_mapping_file_options": lambda *_args: [],
                "_lora_reference_signature": lambda _refs: (),
                "_key_fragment": lambda _value: "stable",
                "inject_lora_into_api_workflow": lambda *_args: {},
                "workflow_to_json_text": lambda _data: "{}",
            },
        )

        loaded["render_lora_loader_injection_export"]("{}", "draft", container)

        self.assertEqual("lora-2", state.comfy_lora_loader_injection_target["node_id"])
        self.assertEqual("Manual", state.comfy_lora_loader_injection_source)
        self.assertEqual("milk.safetensors", state.comfy_lora_loader_manual_name)
        self.assertEqual(0.75, state.comfy_lora_loader_strength_model_stable)
        self.assertEqual(0.5, state.comfy_lora_loader_strength_clip_stable)
        strengths = state.comfyui_analysis_workspace_drafts["lora_injection"]["strengths"]
        self.assertEqual({"model": 0.75, "clip": 0.5}, strengths["stable"])

    def test_paste_upload_reopen_and_clear_preserve_expected_input_owner(self):
        state = _SessionState(
            settings={"comfyui_workflow_path": "workflow.json"},
            comfy_workflow_path="workflow.json",
            comfy_workflow_inspector_text='{"paste": true}',
        )
        inspected = []
        common_namespace = {
            "os": __import__("os"),
            "render_generation_settings_consistency_panel": lambda **_kwargs: None,
            "render_negative_prompt_consistency_panel": lambda **_kwargs: None,
            "resolve_effective_comfy_workflow_path": lambda _path: ("C:/missing.json", "fallback"),
            "_render_comfy_workflow_inspection": lambda raw, source, **_kwargs: inspected.append((raw, source)),
            "render_comfy_prompt_injection_export": lambda *_args, **_kwargs: None,
            "render_lora_directory_mapping": lambda *_args, **_kwargs: None,
            "render_lora_loader_injection_export": lambda *_args, **_kwargs: None,
        }
        loaded, _state = self._load(
            ["render_comfy_workflow_inspector"],
            state=state,
            namespace=common_namespace,
        )
        loaded["render_comfy_workflow_inspector"](_WidgetContainer(state))
        self.assertEqual('{"paste": true}', state.comfy_workflow_inspector_raw_text)

        upload = types.SimpleNamespace(
            name="uploaded.json",
            getvalue=lambda: b'{"upload": true}',
        )
        loaded["render_comfy_workflow_inspector"](
            _WidgetContainer(state, upload=upload)
        )
        self.assertEqual('{"upload": true}', state.comfy_workflow_inspector_raw_text)
        self.assertEqual("uploaded.json", state.comfy_workflow_inspector_source)

        def contains_uploaded_file(value):
            if value is upload:
                return True
            if isinstance(value, dict):
                return any(contains_uploaded_file(item) for item in value.values())
            if isinstance(value, (list, tuple)):
                return any(contains_uploaded_file(item) for item in value)
            return False

        self.assertFalse(
            contains_uploaded_file(state.comfyui_analysis_workspace_drafts)
        )

        state.pop("comfy_workflow_inspector_text", None)
        loaded["render_comfy_workflow_inspector"](_WidgetContainer(state))
        self.assertEqual('{"upload": true}', state.comfy_workflow_inspector_raw_text)
        self.assertEqual("uploaded.json", state.comfy_workflow_inspector_source)

        loaded["render_comfy_workflow_inspector"](
            _WidgetContainer(state, click_clear=True)
        )
        self.assertEqual("", state.comfy_workflow_inspector_raw_text)
        self.assertEqual("workflow JSON", state.comfy_workflow_inspector_source)
        self.assertEqual("", state.comfyui_analysis_workspace_drafts["inspector"]["text"])
        self.assertFalse(state.comfyui_analysis_workspace_drafts["inspector"]["show_fields"])
        self.assertNotIn("comfy_workflow_inspector_text", state)

        loaded["render_comfy_workflow_inspector"](_WidgetContainer(state))
        self.assertEqual("", state.comfy_workflow_inspector_text)
        self.assertEqual("", state.comfy_workflow_inspector_raw_text)

    def test_draft_wiring_stays_session_only_and_sidebar_remains_passive(self):
        app_source = self.source
        self.assertEqual(
            1,
            app_source.count('"comfyui_analysis_workspace_drafts"'),
        )
        for widget_key in (
            "comfy_workflow_inspector_text",
            "comfy_workflow_inspector_show_fields",
            "comfy_prompt_injection_line_id",
            "comfy_prompt_injection_positive_node",
            "comfy_prompt_injection_negative_node",
            "comfy_prompt_injection_manual_negative",
            "lora_mapping_directory",
            "comfy_lora_loader_injection_target",
            "comfy_lora_loader_injection_source",
            "comfy_lora_loader_manual_name",
        ):
            self.assertIn(widget_key, app_source)

        daily = ast.get_source_segment(
            app_source,
            self.functions["render_comfyui_daily_sidebar_section"],
        )
        for forbidden in (
            "render_comfy_workflow_inspector",
            "parse_workflow_json",
            "scan_lora_directory",
            "comfyui_analysis_workspace_drafts",
            "save_settings",
            "save_project",
            "push_history",
        ):
            self.assertNotIn(forbidden, daily)

        helper_source = "\n".join(
            ast.get_source_segment(app_source, self.functions[name])
            for name in self.HELPER_NAMES
        )
        for forbidden in (
            "save_settings",
            "save_project",
            "push_history",
            "parse_workflow_json",
            "scan_lora_directory",
            "generate_image",
            "open(",
        ):
            self.assertNotIn(forbidden, helper_source)


if __name__ == "__main__":
    unittest.main()
