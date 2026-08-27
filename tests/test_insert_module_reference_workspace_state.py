import ast
import types
import unittest
from pathlib import Path

from core.operations import (
    apply_bulk_insert_module_reference,
    get_insert_module_reference_anchor_options,
    preview_bulk_insert_module_reference,
)
from core.project import Project, PromptLine


DURABLE_INPUT_KEYS = (
    "insert_module_reference_type_filter",
    "insert_module_reference_name",
    "insert_module_reference_line_id",
    "insert_module_reference_scope",
    "insert_module_reference_position",
    "insert_module_reference_learned_neighbor_fallback",
    "insert_module_reference_anchor",
)
TEMPORARY_WIDGET_KEYS = (
    "_insert_module_reference_type_filter_widget",
    "_insert_module_reference_name_widget",
    "_insert_module_reference_line_id_widget",
    "_insert_module_reference_scope_widget",
    "_insert_module_reference_position_widget",
    "_insert_module_reference_learned_neighbor_fallback_widget",
    "_insert_module_reference_anchor_widget",
)
PREVIEW_KEY = "insert_module_reference_preview"


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class _Expander:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class _MetricColumn:
    def __init__(self, events):
        self.events = events

    def metric(self, label, value):
        self.events.append(("metric", label, value))


class _Sidebar:
    def __init__(self, events):
        self.events = events

    def expander(self, label, expanded=False):
        self.events.append(("sidebar_expander", label, expanded))
        return _Expander()


class _StreamlitStub:
    def __init__(self, state=None, widget_values=None, button_clicks=()):
        self.session_state = _SessionState(state or {})
        self.widget_values = dict(widget_values or {})
        self.button_clicks = set(button_clicks)
        self.events = []
        self.sidebar = _Sidebar(self.events)
        self.rerun_count = 0

    def expander(self, label, expanded=False):
        self.events.append(("expander", label, expanded))
        return _Expander()

    def _widget(self, kind, label, options, key):
        options = list(options)
        if key in self.widget_values:
            self.session_state[key] = self.widget_values[key]
        value = self.session_state.get(key, options[0])
        if value not in options:
            raise AssertionError(
                f"{key} has invalid value {value!r} for {options!r}"
            )
        self.events.append((kind, label, tuple(options), key, value))
        return value

    def selectbox(self, label, options, *, key, **kwargs):
        return self._widget("selectbox", label, options, key)

    def radio(self, label, options, *, key, **kwargs):
        return self._widget("radio", label, options, key)

    def button(self, label, *, key, disabled=False, **kwargs):
        self.events.append(("button", label, key, disabled))
        return key in self.button_clicks and not disabled

    def caption(self, message):
        self.events.append(("caption", message))

    def info(self, message):
        self.events.append(("info", message))

    def warning(self, message):
        self.events.append(("warning", message))

    def columns(self, count):
        return [_MetricColumn(self.events) for _ in range(count)]

    def rerun(self):
        self.rerun_count += 1


def _line(line_id, text, index):
    return PromptLine(
        id=line_id,
        original_file_name=f"{line_id}.txt",
        original_index=index,
        current_index=index,
        original_text=text,
        current_text=text,
        tokens=[token.strip() for token in text.split(",") if token.strip()],
    )


class InsertModuleReferenceWorkspaceStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.app_source = (cls.root / "app.py").read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.app_source)
        cls.functions = {
            node.name: node
            for node in cls.tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        cls.renderer_name = "render_insert_saved_module_reference_section"
        cls.helper_name = "prepare_insert_module_reference_widget_state"
        cls.reset_name = (
            "reset_insert_module_reference_project_session_state"
        )

    @classmethod
    def _source(cls, name):
        return ast.get_source_segment(cls.app_source, cls.functions[name])

    @classmethod
    def _load_functions(cls, *names, namespace):
        module = ast.Module(
            body=[cls.functions[name] for name in names],
            type_ignores=[],
        )
        ast.fix_missing_locations(module)
        exec(compile(module, "app.py", "exec"), namespace)
        return namespace

    @classmethod
    def _call_owners(cls, callee):
        owners = []
        for name, function in cls.functions.items():
            if any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == callee
                for node in ast.walk(function)
            ):
                owners.append(name)
        return owners

    def _runtime(
        self,
        *,
        state=None,
        widget_values=None,
        button_clicks=(),
        selected_line_ids=None,
        free=False,
        module_library=None,
        lines=None,
        group_enabled=True,
    ):
        lines = list(
            (
                _line("line-1", "one, two, three", 0),
                _line("line-2", "solo", 1),
            )
            if lines is None
            else lines
        )
        project = types.SimpleNamespace(prompt_lines=lines)
        module_library = dict(
            {
                "alpha": {"type": "generic", "body": "alpha body"},
                "character-z": {
                    "type": "character",
                    "body": "character body",
                },
            }
            if module_library is None
            else module_library
        )
        initial_state = {
            "project": project,
            "focused_line_id": "line-1",
            "highlighted_line_id": None,
        }
        initial_state.update(state or {})
        st = _StreamlitStub(
            initial_state,
            widget_values=widget_values,
            button_clicks=button_clicks,
        )
        selected = list(selected_line_ids or [])
        calls = {
            "preview": [],
            "apply": [],
            "history": 0,
            "restore": [],
            "sync": 0,
        }

        def _anchors(text):
            return [
                {"index": index, "token": token.strip()}
                for index, token in enumerate(str(text or "").split(","))
                if token.strip()
            ]

        def _preview(
            value,
            module_name,
            *,
            position,
            target_line_ids,
            anchor_index,
            learned_neighbor_fallback,
        ):
            calls["preview"].append(
                {
                    "project": value,
                    "module_name": module_name,
                    "position": position,
                    "target_line_ids": target_line_ids,
                    "anchor_index": anchor_index,
                    "learned_neighbor_fallback": (
                        learned_neighbor_fallback
                    ),
                }
            )
            target_count = (
                len(target_line_ids)
                if target_line_ids is not None
                else len(lines)
            )
            return {
                "module_reference": f"<mod:{module_name}>",
                "target_line_count": target_count,
                "affected_line_count": 1 if target_count else 0,
                "skipped_no_neighbor_count": 0,
                "skipped_existing_count": 0,
                "examples": [],
            }

        def _apply(value, module_name, **kwargs):
            calls["apply"].append(
                {
                    "project": value,
                    "module_name": module_name,
                    **kwargs,
                }
            )
            return value

        def _history():
            calls["history"] += 1

        def _restore(value):
            calls["restore"].append(value)

        def _sync():
            calls["sync"] += 1

        def _group_scope(value, candidate_ids):
            if group_enabled and any(
                line_id in {"line-1", "line-2"}
                for line_id in candidate_ids
            ):
                return "group-a", ["line-1", "line-2"]
            return None, []

        namespace = {
            "st": st,
            "MODULE_TYPES": [
                "generic",
                "character",
                "scene",
                "outfit",
                "camera",
                "expression",
                "style",
                "negative",
            ],
            "is_free": lambda: free,
            "get_project_module_library": lambda value: module_library,
            "get_module_type": (
                lambda library, name: library[name]["type"]
            ),
            "get_module_body": (
                lambda library, name: library[name]["body"]
            ),
            "_short_preview": lambda value, limit: str(value)[:limit],
            "build_module_reference_token": (
                lambda name: f"<mod:{name}>"
            ),
            "get_selected_line_ids": lambda value: list(selected),
            "resolve_current_line_group_scope": _group_scope,
            "get_insert_module_reference_anchor_options": _anchors,
            "preview_bulk_insert_module_reference": _preview,
            "apply_bulk_insert_module_reference": _apply,
            "push_history": _history,
            "restore_focus_after_graph_update": _restore,
            "sync_text_areas": _sync,
            "ACTIVE_MANAGEMENT_WORKSPACE_KEY": (
                "active_management_workspace"
            ),
            "render_module_toggle_controls": lambda value: None,
            "render_module_candidate_selection_section": lambda value: None,
            "render_attribute_group_swap_section": lambda value: None,
        }
        self._load_functions(
            self.reset_name,
            "reset_management_workspace_session_state",
            self.helper_name,
            self.renderer_name,
            "render_module_attribute_apply_workspace",
            namespace=namespace,
        )
        return namespace, st, calls, project

    def test_durable_and_temporary_keys_are_explicit_and_separate(self):
        reset = self._source(self.reset_name)
        for key in (*DURABLE_INPUT_KEYS, PREVIEW_KEY):
            self.assertEqual(reset.count(f'"{key}"'), 1)
        for key in TEMPORARY_WIDGET_KEYS:
            self.assertTrue(key.startswith("_insert_module_reference_"))
            self.assertEqual(reset.count(f'"{key}"'), 1)

        renderer = self.functions[self.renderer_name]
        widget_keys = {
            keyword.value.value
            for node in ast.walk(renderer)
            if isinstance(node, ast.Call)
            for keyword in node.keywords
            if (
                keyword.arg == "key"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            )
        }
        self.assertTrue(set(TEMPORARY_WIDGET_KEYS).issubset(widget_keys))
        self.assertTrue(set(DURABLE_INPUT_KEYS).isdisjoint(widget_keys))
        self.assertNotIn(PREVIEW_KEY, widget_keys)

    def test_widget_types_labels_and_matching_temporary_keys_are_unchanged(self):
        expected = {
            "Module type filter": (
                "selectbox",
                "_insert_module_reference_type_filter_widget",
            ),
            "Saved module": (
                "selectbox",
                "_insert_module_reference_name_widget",
            ),
            "Target line": (
                "selectbox",
                "_insert_module_reference_line_id_widget",
            ),
            "Insertion Scope": (
                "selectbox",
                "_insert_module_reference_scope_widget",
            ),
            "Insert position": (
                "radio",
                "_insert_module_reference_position_widget",
            ),
            "No learned neighbor fallback": (
                "radio",
                "_insert_module_reference_learned_neighbor_fallback_widget",
            ),
            "Selected token": (
                "selectbox",
                "_insert_module_reference_anchor_widget",
            ),
        }
        found = {}
        for node in ast.walk(self.functions[self.renderer_name]):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "st"
                and node.func.attr in {"selectbox", "radio"}
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                continue
            key = next(
                keyword.value.value
                for keyword in node.keywords
                if keyword.arg == "key"
                and isinstance(keyword.value, ast.Constant)
            )
            found[node.args[0].value] = (node.func.attr, key)
        self.assertEqual(found, expected)

    def test_binding_helper_rehydrates_and_normalizes_values(self):
        namespace, st, _, _ = self._runtime(
            state={
                "insert_module_reference_type_filter": "invalid",
                "_insert_module_reference_type_filter_widget": "character",
            }
        )
        helper = namespace[self.helper_name]

        result = helper(
            "insert_module_reference_type_filter",
            "_insert_module_reference_type_filter_widget",
            ["all", "generic", "character"],
            "all",
        )

        self.assertEqual(result, "all")
        self.assertEqual(
            st.session_state.insert_module_reference_type_filter,
            "all",
        )
        self.assertEqual(
            st.session_state._insert_module_reference_type_filter_widget,
            "all",
        )

        st.session_state.insert_module_reference_name = "character-z"
        st.session_state.pop(
            "_insert_module_reference_name_widget",
            None,
        )
        helper(
            "insert_module_reference_name",
            "_insert_module_reference_name_widget",
            ["alpha", "character-z"],
            "alpha",
        )
        self.assertEqual(
            st.session_state._insert_module_reference_name_widget,
            "character-z",
        )

    def test_invalid_dynamic_inputs_normalize_to_existing_defaults(self):
        namespace, st, _, project = self._runtime(
            state={
                "focused_line_id": "line-2",
                "insert_module_reference_type_filter": "invalid",
                "insert_module_reference_name": "missing",
                "insert_module_reference_line_id": "missing-line",
                "insert_module_reference_scope": "missing-scope",
                "insert_module_reference_position": "missing-position",
                "_insert_module_reference_type_filter_widget": "invalid",
                "_insert_module_reference_name_widget": "missing",
                "_insert_module_reference_line_id_widget": "missing-line",
                "_insert_module_reference_scope_widget": "missing-scope",
                "_insert_module_reference_position_widget": (
                    "missing-position"
                ),
            }
        )

        namespace[self.renderer_name](project)

        self.assertEqual(
            st.session_state.insert_module_reference_type_filter,
            "all",
        )
        self.assertEqual(
            st.session_state.insert_module_reference_name,
            "alpha",
        )
        self.assertEqual(
            st.session_state.insert_module_reference_line_id,
            "line-2",
        )
        self.assertEqual(
            st.session_state.insert_module_reference_scope,
            "current",
        )
        self.assertEqual(
            st.session_state.insert_module_reference_position,
            "end",
        )

    def test_type_filter_and_scope_dependent_position_normalize(self):
        namespace, st, _, project = self._runtime(
            state={
                "insert_module_reference_name": "alpha",
                "insert_module_reference_scope": "all",
                "insert_module_reference_position": "before",
            },
            widget_values={
                "_insert_module_reference_type_filter_widget": "character",
            },
        )

        namespace[self.renderer_name](project)

        self.assertEqual(
            st.session_state.insert_module_reference_type_filter,
            "character",
        )
        self.assertEqual(
            st.session_state.insert_module_reference_name,
            "character-z",
        )
        self.assertEqual(
            st.session_state.insert_module_reference_scope,
            "all",
        )
        self.assertEqual(
            st.session_state.insert_module_reference_position,
            "end",
        )

    def test_unavailable_scope_normalizes_to_current(self):
        namespace, st, _, project = self._runtime(
            state={
                "focused_line_id": None,
                "highlighted_line_id": None,
                "insert_module_reference_scope": "selected",
            },
            selected_line_ids=[],
            group_enabled=False,
        )

        namespace[self.renderer_name](project)

        self.assertEqual(
            st.session_state.insert_module_reference_scope,
            "current",
        )

    def test_conditional_fallback_survives_hide_and_rehydrates(self):
        namespace, st, _, project = self._runtime(
            state={
                "insert_module_reference_position": "end",
                "insert_module_reference_learned_neighbor_fallback": "end",
            }
        )
        render = namespace[self.renderer_name]

        render(project)
        self.assertEqual(
            st.session_state[
                "insert_module_reference_learned_neighbor_fallback"
            ],
            "end",
        )
        self.assertNotIn(
            "_insert_module_reference_learned_neighbor_fallback_widget",
            st.session_state,
        )

        st.widget_values[
            "_insert_module_reference_position_widget"
        ] = "learned_neighbor"
        render(project)
        self.assertEqual(
            st.session_state[
                "_insert_module_reference_learned_neighbor_fallback_widget"
            ],
            "end",
        )

        st.session_state[
            "insert_module_reference_learned_neighbor_fallback"
        ] = "invalid"
        st.session_state[
            "_insert_module_reference_learned_neighbor_fallback_widget"
        ] = "invalid"
        render(project)
        self.assertEqual(
            st.session_state[
                "insert_module_reference_learned_neighbor_fallback"
            ],
            "skip",
        )

    def test_conditional_anchor_survives_hide_and_revalidates_by_index(self):
        namespace, st, _, project = self._runtime(
            state={
                "insert_module_reference_line_id": "line-1",
                "insert_module_reference_position": "end",
                "insert_module_reference_anchor": 2,
            }
        )
        render = namespace[self.renderer_name]

        render(project)
        self.assertEqual(
            st.session_state.insert_module_reference_anchor,
            2,
        )
        self.assertNotIn(
            "_insert_module_reference_anchor_widget",
            st.session_state,
        )

        st.widget_values[
            "_insert_module_reference_position_widget"
        ] = "before"
        render(project)
        self.assertEqual(
            st.session_state._insert_module_reference_anchor_widget,
            2,
        )

        st.widget_values[
            "_insert_module_reference_line_id_widget"
        ] = "line-2"
        render(project)
        self.assertEqual(
            st.session_state.insert_module_reference_anchor,
            0,
        )
        self.assertEqual(
            st.session_state._insert_module_reference_anchor_widget,
            0,
        )

    def test_no_anchor_state_is_safe_and_does_not_clear_durable_anchor(self):
        empty_line = _line("line-empty", "", 0)
        namespace, st, calls, project = self._runtime(
            lines=[empty_line],
            state={
                "focused_line_id": "line-empty",
                "insert_module_reference_line_id": "line-empty",
                "insert_module_reference_position": "before",
                "insert_module_reference_anchor": 4,
            },
        )

        namespace[self.renderer_name](project)

        self.assertEqual(
            st.session_state.insert_module_reference_anchor,
            4,
        )
        self.assertNotIn(
            "_insert_module_reference_anchor_widget",
            st.session_state,
        )
        self.assertIn(
            ("warning", "No token anchors available on this line."),
            st.events,
        )
        self.assertEqual(calls["preview"], [])

    def test_back_and_widget_cleanup_preserve_inputs_and_current_preview(self):
        signature = {
            "module_name": "character-z",
            "scope": "current",
            "target_line_ids": ("line-1",),
            "position": "before",
            "anchor_index": 1,
            "learned_neighbor_fallback": "skip",
        }
        durable_state = {
            "active_management_workspace": "module_attribute_apply",
            "insert_module_reference_type_filter": "character",
            "insert_module_reference_name": "character-z",
            "insert_module_reference_line_id": "line-1",
            "insert_module_reference_scope": "current",
            "insert_module_reference_position": "before",
            "insert_module_reference_learned_neighbor_fallback": "end",
            "insert_module_reference_anchor": 1,
            PREVIEW_KEY: {
                "signature": signature,
                "preview": {
                    "module_reference": "<mod:character-z>",
                    "target_line_count": 1,
                    "affected_line_count": 1,
                    "skipped_no_neighbor_count": 0,
                    "skipped_existing_count": 0,
                    "examples": [],
                },
            },
        }
        namespace, st, _, project = self._runtime(state=durable_state)

        namespace["render_module_attribute_apply_workspace"]()
        namespace["reset_management_workspace_session_state"]()
        self.assertEqual(st.session_state.active_management_workspace, "")
        for key, value in durable_state.items():
            if key != "active_management_workspace":
                self.assertEqual(st.session_state[key], value)

        for key in TEMPORARY_WIDGET_KEYS:
            st.session_state.pop(key, None)
        st.session_state.active_management_workspace = (
            "module_attribute_apply"
        )
        namespace["render_module_attribute_apply_workspace"]()

        self.assertNotIn(
            ("caption", "Preview is out of date. Run preview again."),
            st.events,
        )
        self.assertIn(("metric", "Affected lines", 1), st.events)
        for durable_key, widget_key in zip(
            DURABLE_INPUT_KEYS[:5],
            TEMPORARY_WIDGET_KEYS[:5],
        ):
            self.assertEqual(
                st.session_state[widget_key],
                st.session_state[durable_key],
            )
        self.assertEqual(
            st.session_state._insert_module_reference_anchor_widget,
            1,
        )
        self.assertEqual(
            st.session_state[
                "insert_module_reference_learned_neighbor_fallback"
            ],
            "end",
        )

    def test_changed_input_keeps_preview_stale_and_blocks_apply(self):
        namespace, st, calls, project = self._runtime(
            state={
                "insert_module_reference_position": "start",
                PREVIEW_KEY: {
                    "signature": {
                        "module_name": "alpha",
                        "scope": "current",
                        "target_line_ids": ("line-1",),
                        "position": "end",
                        "anchor_index": None,
                        "learned_neighbor_fallback": "skip",
                    },
                    "preview": {
                        "module_reference": "<mod:alpha>",
                        "target_line_count": 1,
                        "affected_line_count": 1,
                        "skipped_no_neighbor_count": 0,
                        "skipped_existing_count": 0,
                        "examples": [],
                    },
                },
            },
            button_clicks=("insert_module_reference_apply_btn",),
        )

        namespace[self.renderer_name](project)

        self.assertIn(
            ("caption", "Preview is out of date. Run preview again."),
            st.events,
        )
        self.assertEqual(calls["apply"], [])
        self.assertEqual(calls["history"], 0)
        self.assertIn(PREVIEW_KEY, st.session_state)

    def test_preview_signature_and_apply_semantics_remain_unchanged(self):
        namespace, st, calls, project = self._runtime(
            state={
                "focused_line_id": "line-1",
                "insert_module_reference_position": "end",
            },
            button_clicks=("insert_module_reference_preview_btn",),
        )
        render = namespace[self.renderer_name]
        render(project)

        self.assertEqual(len(calls["preview"]), 1)
        self.assertEqual(
            set(st.session_state[PREVIEW_KEY]["signature"]),
            {
                "module_name",
                "scope",
                "target_line_ids",
                "position",
                "anchor_index",
                "learned_neighbor_fallback",
            },
        )
        self.assertEqual(calls["history"], 0)

        st.button_clicks = {"insert_module_reference_apply_btn"}
        st.events.clear()
        render(project)

        self.assertEqual(calls["history"], 1)
        self.assertEqual(len(calls["apply"]), 1)
        self.assertEqual(calls["restore"], ["line-1"])
        self.assertEqual(calls["sync"], 1)
        self.assertNotIn(PREVIEW_KEY, st.session_state)
        for key in DURABLE_INPUT_KEYS[:5]:
            self.assertIn(key, st.session_state)
        self.assertEqual(st.rerun_count, 1)

    def test_project_reset_clears_exact_operation_state_only(self):
        operation_keys = (
            *DURABLE_INPUT_KEYS,
            PREVIEW_KEY,
            *TEMPORARY_WIDGET_KEYS,
        )
        namespace, st, _, _ = self._runtime(
            state={
                **{key: f"value-{index}" for index, key in enumerate(operation_keys)},
                "unrelated": "keep",
            }
        )

        namespace[self.reset_name]()

        for key in operation_keys:
            self.assertNotIn(key, st.session_state)
        self.assertEqual(st.session_state.unrelated, "keep")

    def test_successful_project_transitions_own_all_reset_calls(self):
        loader = self._source("load_project_json_into_session")
        new_project = self._source("set_new_workspace_project")
        imports = self._source("render_prompt_import_export_panel")
        back = self._source("reset_management_workspace_session_state")
        renderer = self._source(self.renderer_name)

        self.assertEqual(loader.count(f"{self.reset_name}()"), 1)
        self.assertEqual(new_project.count(f"{self.reset_name}()"), 1)
        self.assertEqual(imports.count(f"{self.reset_name}()"), 2)
        self.assertEqual(
            self.app_source.count(f"{self.reset_name}()"),
            5,
        )
        self.assertLess(
            loader.index("project = load_project_from_json(project_path)"),
            loader.index(f"{self.reset_name}()"),
        )
        self.assertLess(
            loader.index(f"{self.reset_name}()"),
            loader.index("st.session_state.project = project"),
        )
        self.assertNotIn(
            self.reset_name,
            loader[
                : loader.index(
                    "project = load_project_from_json(project_path)"
                )
            ],
        )
        self.assertNotIn(self.reset_name, back)
        self.assertNotIn(self.reset_name, renderer)

    def test_workspace_is_the_only_owner_and_sidebar_retains_only_launcher(self):
        self.assertEqual(
            self._call_owners(self.renderer_name),
            ["render_module_attribute_apply_workspace"],
        )
        workspace = self._source(
            "render_module_attribute_apply_workspace"
        )
        sidebar = self._source(
            "render_module_attribute_apply_sidebar_section"
        )
        workspace_children = (
            "render_module_toggle_controls(project)",
            "render_insert_saved_module_reference_section(project)",
            "render_module_candidate_selection_section(project)",
            "render_attribute_group_swap_section(project)",
        )
        workspace_positions = [
            workspace.index(child) for child in workspace_children
        ]
        self.assertEqual(workspace_positions, sorted(workspace_positions))
        self.assertEqual(
            workspace.count(
                "render_insert_saved_module_reference_section(project)"
            ),
            1,
        )
        self.assertNotIn(self.renderer_name, sidebar)
        self.assertEqual(
            self._call_owners(
                "render_module_candidate_selection_section"
            ),
            ["render_module_attribute_apply_workspace"],
        )
        self.assertEqual(
            self._call_owners("render_attribute_group_swap_section"),
            ["render_module_attribute_apply_workspace"],
        )
        self.assertNotIn("render_attribute_group_swap_section", sidebar)
        self.assertEqual(sidebar.count("Open Apply Workspace"), 1)
        renderer = self._source(self.renderer_name)
        self.assertIn(
            'with st.expander("Insert Saved Module Reference", '
            "expanded=False):",
            renderer,
        )
        self.assertNotIn("st.sidebar", renderer)

    def test_no_project_free_and_empty_inputs_keep_existing_boundaries(self):
        cases = (
            (
                {"project": None},
                False,
                {"alpha": {"type": "generic", "body": "body"}},
                [_line("line-1", "one", 0)],
                "Load project first.",
                set(),
            ),
            (
                {},
                True,
                {"alpha": {"type": "generic", "body": "body"}},
                [_line("line-1", "one", 0)],
                "Saved module reference insertion is available in Pro.",
                set(),
            ),
            (
                {},
                False,
                {},
                [_line("line-1", "one", 0)],
                "No saved modules match this filter.",
                {"insert_module_reference_type_filter"},
            ),
            (
                {},
                False,
                {"alpha": {"type": "generic", "body": "body"}},
                [],
                "No target prompt lines.",
                {
                    "insert_module_reference_type_filter",
                    "insert_module_reference_name",
                },
            ),
        )
        for (
            state,
            free,
            library,
            lines,
            message,
            expected_durable,
        ) in cases:
            with self.subTest(message=message):
                namespace, st, _, project = self._runtime(
                    state=state,
                    free=free,
                    module_library=library,
                    lines=lines,
                )
                if state.get("project", object()) is None:
                    project = None
                namespace[self.renderer_name](project)
                self.assertIn(("info", message), st.events)
                self.assertEqual(
                    set(DURABLE_INPUT_KEYS).intersection(st.session_state),
                    expected_durable,
                )

    def test_no_save_schema_or_parallel_preview_state_is_added(self):
        combined = "\n".join(
            (
                self._source(self.helper_name),
                self._source(self.reset_name),
                self._source(self.renderer_name),
            )
        )
        for forbidden in (
            "save_project",
            "save_settings",
            "autosave",
            "project_metadata",
        ):
            self.assertNotIn(forbidden, combined)
        renderer = self._source(self.renderer_name)
        self.assertEqual(renderer.count("push_history()"), 1)
        self.assertEqual(
            renderer.count("apply_bulk_insert_module_reference("),
            1,
        )
        self.assertEqual(
            renderer.count(
                "insert_module_reference_preview"
            ),
            4,
        )

    def test_core_bulk_insert_positions_targets_and_duplicate_skip(self):
        expected_after = {
            ("start", None): "<mod:alpha>, one, two",
            ("end", None): "one, two, <mod:alpha>",
            ("before", 1): "one, <mod:alpha>, two",
            ("after", 0): "one, <mod:alpha>, two",
        }
        for (position, anchor), expected in expected_after.items():
            with self.subTest(position=position, anchor=anchor):
                project = Project(
                    module_library={
                        "alpha": {"type": "generic", "body": "body"}
                    },
                    prompt_lines=[_line("line-1", "one, two", 0)],
                )
                preview = preview_bulk_insert_module_reference(
                    project,
                    "alpha",
                    position=position,
                    target_line_ids=["line-1"],
                    anchor_index=anchor,
                )
                self.assertEqual(preview["examples"][0]["after"], expected)

        project = Project(
            module_library={
                "alpha": {"type": "generic", "body": "body"}
            },
            prompt_lines=[
                _line("line-1", "one, <mod:alpha>", 0),
                _line("line-2", "two", 1),
            ],
        )
        preview = preview_bulk_insert_module_reference(
            project,
            "alpha",
            target_line_ids=["line-1", "line-2"],
        )
        self.assertEqual(preview["skipped_existing_count"], 1)
        self.assertEqual(preview["affected_line_count"], 1)
        result = apply_bulk_insert_module_reference(
            project,
            "alpha",
            target_line_ids=["line-2"],
        )
        texts = {line.id: line.current_text for line in result.prompt_lines}
        self.assertEqual(texts["line-1"], "one, <mod:alpha>")
        self.assertEqual(texts["line-2"], "two, <mod:alpha>")

    def test_core_learned_neighbor_fallback_and_anchor_indices_are_stable(self):
        project = Project(
            module_library={
                "alpha": {"type": "generic", "body": "body"}
            },
            prompt_lines=[
                _line(
                    "example",
                    "left, <mod:alpha>, right",
                    0,
                ),
                _line("matched", "left, right", 1),
                _line("unmatched", "other", 2),
            ],
        )
        preview = preview_bulk_insert_module_reference(
            project,
            "alpha",
            position="learned_neighbor",
            target_line_ids=["matched", "unmatched"],
            learned_neighbor_fallback="skip",
        )
        self.assertEqual(preview["affected_line_count"], 1)
        self.assertEqual(preview["skipped_no_neighbor_count"], 1)
        self.assertEqual(
            preview["examples"][0]["after"],
            "left, <mod:alpha>, right",
        )

        fallback = preview_bulk_insert_module_reference(
            project,
            "alpha",
            position="learned_neighbor",
            target_line_ids=["unmatched"],
            learned_neighbor_fallback="end",
        )
        self.assertEqual(fallback["affected_line_count"], 1)
        self.assertEqual(
            fallback["examples"][0]["after"],
            "other, <mod:alpha>",
        )

        anchors = get_insert_module_reference_anchor_options(
            "one, </mod:alpha>, two"
        )
        self.assertEqual(
            [option["index"] for option in anchors],
            [0, 2],
        )


if __name__ == "__main__":
    unittest.main()
