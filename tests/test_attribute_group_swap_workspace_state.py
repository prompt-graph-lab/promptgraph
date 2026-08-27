import ast
import copy
import types
import unittest
from pathlib import Path


DURABLE_KEYS = (
    "attribute_group_swap_from",
    "attribute_group_swap_to",
    "attribute_group_swap_scope",
    "attribute_group_swap_selected_route_id",
    "attribute_group_swap_require_full_match",
)
TEMPORARY_KEYS = (
    "_attribute_group_swap_from_widget",
    "_attribute_group_swap_to_widget",
    "_attribute_group_swap_scope_widget",
    "_attribute_group_swap_selected_route_id_widget",
    "_attribute_group_swap_require_full_match_widget",
)
RESET_KEYS = (
    *DURABLE_KEYS,
    *TEMPORARY_KEYS,
    "attribute_group_swap_preview",
    "attribute_group_swap_selected_routes_confirm",
    "attribute_group_swap_notice",
)
SCOPE_OPTIONS = (
    "all_lines",
    "current_route",
    "selected_route",
    "selected_routes",
    "selected_lines",
    "focused_line",
)


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class _Container:
    def __init__(self, events=None):
        self.events = events

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def metric(self, label, value):
        if self.events is not None:
            self.events.append(("metric", label, value))


class _Sidebar:
    def __init__(self, events):
        self.events = events

    def expander(self, label, expanded=False):
        self.events.append(("sidebar_expander", label, expanded))
        return _Container(self.events)


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
        return _Container(self.events)

    def _widget(self, kind, label, options, key, kwargs):
        options = list(options)
        if key in self.widget_values:
            previous = self.session_state.get(key)
            self.session_state[key] = self.widget_values[key]
            if previous != self.widget_values[key] and kwargs.get("on_change"):
                kwargs["on_change"](*kwargs.get("args", ()))
        value = self.session_state.get(key, options[0])
        if value not in options:
            raise AssertionError(f"{key} has invalid value {value!r}")
        self.events.append((kind, label, tuple(options), key, value))
        return value

    def selectbox(self, label, options, *, key, **kwargs):
        return self._widget("selectbox", label, options, key, kwargs)

    def radio(self, label, options, *, key, **kwargs):
        return self._widget("radio", label, options, key, kwargs)

    def checkbox(self, label, *, key, **kwargs):
        if key in self.widget_values:
            previous = self.session_state.get(key)
            self.session_state[key] = self.widget_values[key]
            if previous != self.widget_values[key] and kwargs.get("on_change"):
                kwargs["on_change"](*kwargs.get("args", ()))
        value = self.session_state.get(key, False)
        if not isinstance(value, bool):
            raise AssertionError(f"{key} has invalid value {value!r}")
        self.events.append(("checkbox", label, key, value))
        return value

    def button(self, label, *, key, disabled=False, **kwargs):
        self.events.append(("button", label, key, disabled))
        return key in self.button_clicks and not disabled

    def columns(self, count):
        return [_Container(self.events) for _ in range(count)]

    def caption(self, message):
        self.events.append(("caption", message))

    def info(self, message):
        self.events.append(("info", message))

    def warning(self, message):
        self.events.append(("warning", message))

    def success(self, message):
        self.events.append(("success", message))

    def markdown(self, message):
        self.events.append(("markdown", message))

    def rerun(self):
        self.rerun_count += 1


class AttributeGroupSwapWorkspaceStateTests(unittest.TestCase):
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
        cls.renderer_name = "render_attribute_group_swap_section"
        cls.workspace_name = "render_module_attribute_apply_workspace"
        cls.flow_name = "_render_selected_routes_attribute_group_swap_flow"
        cls.reset_name = "reset_attribute_group_swap_project_session_state"
        cls.prepare_names = (
            "prepare_attribute_group_swap_from_widget_state",
            "prepare_attribute_group_swap_to_widget_state",
            "prepare_attribute_group_swap_scope_widget_state",
            "prepare_attribute_group_swap_selected_route_widget_state",
            "prepare_attribute_group_swap_require_full_match_widget_state",
        )
        cls.sync_names = (
            "sync_attribute_group_swap_from_widget_state",
            "sync_attribute_group_swap_to_widget_state",
            "sync_attribute_group_swap_scope_widget_state",
            "sync_attribute_group_swap_selected_route_widget_state",
            "sync_attribute_group_swap_require_full_match_widget_state",
        )

    @classmethod
    def _source(cls, name):
        return ast.get_source_segment(cls.app_source, cls.functions[name])

    @classmethod
    def _load_functions(cls, *names, namespace):
        nodes = []
        for name in names:
            node = copy.deepcopy(cls.functions[name])
            node.decorator_list = []
            nodes.append(node)
        module = ast.Module(body=nodes, type_ignores=[])
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
        group_keys=("alpha", "beta", "gamma"),
        route_ids=("route-1", "route-2"),
        target_line_ids=("line-1", "line-2"),
        selected_route_signature=None,
        selected_routes_flow=False,
    ):
        project = types.SimpleNamespace(name="project")
        groups = {
            key: {"name": key, "slot": "outfit", "tokens": [key]}
            for key in group_keys
        }
        initial_state = {
            "project": project,
            "current_project_path": "project.json",
            "focused_line_id": "line-1",
            "gallery_selected_route_ids": ["route-1", "route-2"],
        }
        initial_state.update(state or {})
        st = _StreamlitStub(
            initial_state,
            widget_values=widget_values,
            button_clicks=button_clicks,
        )
        calls = {
            "preview": [],
            "apply": [],
            "history": 0,
            "restore": [],
            "save": [],
            "selected_plan": [],
            "selected_preview_render": [],
            "workspace_children": [],
        }

        def _preview(value, from_key, to_key, **kwargs):
            calls["preview"].append((value, from_key, to_key, kwargs))
            return {
                "warnings": [],
                "target_line_count": len(target_line_ids),
                "affected_line_count": 1,
                "no_match_line_count": 0,
                "full_match_line_count": 1,
                "partial_match_line_count": 0,
                "tokens_to_remove": [from_key],
                "tokens_to_add": [to_key],
                "shared_tokens": [],
                "already_present_to_tokens": [],
                "examples": [],
            }

        def _apply(value, from_key, to_key, **kwargs):
            calls["apply"].append((value, from_key, to_key, kwargs))
            return types.SimpleNamespace(name="updated")

        def _selected_signature(value, selected_ids, **kwargs):
            if selected_route_signature is not None:
                return selected_route_signature
            return (
                tuple(selected_ids),
                kwargs["from_group_key"],
                kwargs["to_group_key"],
                kwargs["require_full_match"],
                kwargs["project_path"],
            )

        def _selected_plan(value, selected_ids, **kwargs):
            calls["selected_plan"].append((value, tuple(selected_ids), kwargs))
            return {"valid": True, "changed_line_count": 1}

        namespace = {
            "st": st,
            "is_free": lambda: False,
            "get_attribute_groups_snapshot": lambda value: groups,
            "_format_attribute_group_swap_option": lambda value, key: key,
            "_attribute_group_swap_scope_label": lambda value: value,
            "_gallery_route_options_with_counts": lambda value: [
                {
                    "route_id": route_id,
                    "route_label": route_id,
                    "route_line_count": 1,
                }
                for route_id in route_ids
            ],
            "_format_gallery_route_option": lambda route: route.get(
                "route_label",
                "",
            ),
            "_resolve_attribute_group_swap_targets": lambda value, scope, selected_route_id="": {
                "target_line_ids": list(target_line_ids),
                "warnings": [],
                "route_id": selected_route_id,
                "route_label": selected_route_id,
                "route_line_count": len(target_line_ids),
            },
            "preview_attribute_group_swap": _preview,
            "apply_attribute_group_swap": _apply,
            "_short_preview": lambda value, limit: str(value)[:limit],
            "push_history": lambda: calls.__setitem__(
                "history",
                calls["history"] + 1,
            ),
            "restore_focus_after_graph_update": calls["restore"].append,
            "save_current_project_if_possible": calls["save"].append,
            "render_batch_preview_text": lambda *args, **kwargs: None,
            "sanitize_selected_route_ids": lambda value, selected_ids: {
                "selected_route_ids": list(selected_ids),
                "selected_route_count": len(selected_ids),
                "selected_main_line_count": len(selected_ids),
                "selected_route_labels": list(selected_ids),
                "diagnostics": [],
            },
            "normalize_attribute_slot": lambda value: value or "",
            "build_selected_routes_attribute_group_swap_signature": (
                _selected_signature
            ),
            "build_selected_routes_attribute_group_swap_plan": (
                _selected_plan
            ),
            "_render_selected_routes_attribute_group_swap_preview": (
                lambda *args, **kwargs: calls[
                    "selected_preview_render"
                ].append((args, kwargs))
            ),
        }
        names = (
            *self.prepare_names,
            *self.sync_names,
            self.flow_name,
            self.renderer_name,
            self.workspace_name,
        )
        self._load_functions(*names, namespace=namespace)
        namespace["render_module_toggle_controls"] = lambda value: calls[
            "workspace_children"
        ].append(("toggle", value))
        namespace["render_insert_saved_module_reference_section"] = (
            lambda value: calls["workspace_children"].append(
                ("insert", value)
            )
        )
        namespace["render_module_candidate_selection_section"] = (
            lambda value: calls["workspace_children"].append(
                ("candidate", value)
            )
        )
        if not selected_routes_flow:
            namespace[self.flow_name] = lambda *args, **kwargs: calls[
                "selected_preview_render"
            ].append((args, kwargs))
        return namespace, st, calls, project

    def test_renderer_uses_temporary_keys_and_explicit_sync_callbacks(self):
        renderer = self._source(self.renderer_name)
        for key, prepare, sync in zip(
            TEMPORARY_KEYS,
            self.prepare_names,
            self.sync_names,
        ):
            self.assertIn(f'key="{key}"', renderer)
            self.assertIn(f"{prepare}(", renderer)
            self.assertIn(f"on_change={sync}", renderer)
        for durable_key in DURABLE_KEYS:
            self.assertNotIn(f'key="{durable_key}"', renderer)
        self.assertNotIn("gallery_attribute_group_swap_", renderer)

    def test_defaults_and_widget_callbacks_update_durable_drafts(self):
        namespace, st, _, project = self._runtime(
            widget_values={
                "_attribute_group_swap_from_widget": "gamma",
                "_attribute_group_swap_to_widget": "alpha",
                "_attribute_group_swap_scope_widget": "selected_route",
                "_attribute_group_swap_selected_route_id_widget": "route-2",
                "_attribute_group_swap_require_full_match_widget": True,
            }
        )
        namespace[self.renderer_name](project)
        self.assertEqual(
            [st.session_state[key] for key in DURABLE_KEYS],
            ["gamma", "alpha", "selected_route", "route-2", True],
        )

        namespace, st, _, project = self._runtime()
        namespace[self.renderer_name](project)
        self.assertEqual(st.session_state.attribute_group_swap_from, "alpha")
        self.assertEqual(st.session_state.attribute_group_swap_to, "beta")
        self.assertEqual(
            st.session_state.attribute_group_swap_scope,
            "all_lines",
        )
        self.assertFalse(
            st.session_state.attribute_group_swap_require_full_match
        )

    def test_valid_equal_groups_and_boolean_values_are_preserved(self):
        for full_match in (False, True):
            with self.subTest(full_match=full_match):
                namespace, st, _, project = self._runtime(
                    state={
                        "attribute_group_swap_from": "beta",
                        "attribute_group_swap_to": "beta",
                        "attribute_group_swap_scope": "focused_line",
                        "attribute_group_swap_require_full_match": full_match,
                    }
                )
                namespace[self.renderer_name](project)
                self.assertEqual(
                    st.session_state.attribute_group_swap_from,
                    "beta",
                )
                self.assertEqual(
                    st.session_state.attribute_group_swap_to,
                    "beta",
                )
                self.assertEqual(
                    st.session_state.attribute_group_swap_scope,
                    "focused_line",
                )
                self.assertIs(
                    st.session_state.attribute_group_swap_require_full_match,
                    full_match,
                )
                self.assertIn(
                    (
                        "warning",
                        "FromとToには異なるAttribute Groupを選択してください。",
                    ),
                    st.events,
                )

    def test_invalid_values_repair_without_clearing_preview(self):
        preview = {
            "signature": {
                "from_group_key": "removed-from",
                "to_group_key": "removed-to",
                "scope": "removed-scope",
                "selected_route_id": "removed-route",
                "target_line_ids": ("line-1", "line-2"),
                "require_full_match": True,
            },
            "preview": {"keep": True},
        }
        namespace, st, calls, project = self._runtime(
            state={
                "attribute_group_swap_from": "removed-from",
                "attribute_group_swap_to": "removed-to",
                "attribute_group_swap_scope": "removed-scope",
                "attribute_group_swap_selected_route_id": "removed-route",
                "attribute_group_swap_require_full_match": "False",
                "attribute_group_swap_preview": preview,
            }
        )
        namespace[self.renderer_name](project)
        self.assertEqual(st.session_state.attribute_group_swap_from, "alpha")
        self.assertEqual(st.session_state.attribute_group_swap_to, "beta")
        self.assertEqual(
            st.session_state.attribute_group_swap_scope,
            "all_lines",
        )
        self.assertEqual(
            st.session_state.attribute_group_swap_selected_route_id,
            "removed-route",
        )
        self.assertFalse(
            st.session_state.attribute_group_swap_require_full_match
        )
        self.assertIs(st.session_state.attribute_group_swap_preview, preview)
        self.assertEqual(calls["preview"], [])
        self.assertEqual(calls["apply"], [])
        self.assertIn(
            (
                "caption",
                "Attribute Group Swap preview is stale. Preview again before applying.",
            ),
            st.events,
        )

    def test_selected_route_survives_other_scopes_and_repairs_only_when_needed(self):
        namespace, st, _, project = self._runtime(
            state={
                "attribute_group_swap_scope": "all_lines",
                "attribute_group_swap_selected_route_id": "route-2",
            }
        )
        namespace[self.renderer_name](project)
        self.assertEqual(
            st.session_state.attribute_group_swap_selected_route_id,
            "route-2",
        )
        self.assertNotIn(
            "_attribute_group_swap_selected_route_id_widget",
            st.session_state,
        )

        st.session_state.attribute_group_swap_scope = "selected_route"
        namespace[self.renderer_name](project)
        self.assertEqual(
            st.session_state._attribute_group_swap_selected_route_id_widget,
            "route-2",
        )

        st.session_state.attribute_group_swap_selected_route_id = "removed"
        st.session_state.pop(
            "_attribute_group_swap_selected_route_id_widget",
            None,
        )
        namespace[self.renderer_name](project)
        self.assertEqual(
            st.session_state.attribute_group_swap_selected_route_id,
            "route-1",
        )

        namespace, st, _, project = self._runtime(
            state={
                "attribute_group_swap_scope": "selected_route",
                "attribute_group_swap_selected_route_id": "removed",
            },
            route_ids=(),
        )
        namespace[self.renderer_name](project)
        self.assertEqual(
            st.session_state.attribute_group_swap_selected_route_id,
            "",
        )

    def test_hidden_widget_reconstruction_keeps_matching_normal_preview_current(self):
        signature = {
            "from_group_key": "gamma",
            "to_group_key": "alpha",
            "scope": "selected_route",
            "selected_route_id": "route-2",
            "target_line_ids": ("line-1", "line-2"),
            "require_full_match": True,
        }
        state = {
            "attribute_group_swap_from": "gamma",
            "attribute_group_swap_to": "alpha",
            "attribute_group_swap_scope": "selected_route",
            "attribute_group_swap_selected_route_id": "route-2",
            "attribute_group_swap_require_full_match": True,
            "_attribute_group_swap_from_widget": "gamma",
            "_attribute_group_swap_to_widget": "alpha",
            "_attribute_group_swap_scope_widget": "selected_route",
            "_attribute_group_swap_selected_route_id_widget": "route-2",
            "_attribute_group_swap_require_full_match_widget": True,
            "attribute_group_swap_preview": {
                "signature": signature,
                "preview": {
                    "warnings": [],
                    "target_line_count": 2,
                    "affected_line_count": 1,
                    "no_match_line_count": 0,
                    "full_match_line_count": 1,
                    "partial_match_line_count": 0,
                    "tokens_to_remove": ["gamma"],
                    "tokens_to_add": ["alpha"],
                    "shared_tokens": [],
                    "already_present_to_tokens": [],
                    "examples": [],
                },
            },
        }
        namespace, st, calls, project = self._runtime(state=state)
        for key in TEMPORARY_KEYS:
            st.session_state.pop(key, None)
        namespace[self.workspace_name]()
        self.assertEqual(
            calls["workspace_children"],
            [
                ("toggle", project),
                ("insert", project),
                ("candidate", project),
            ],
        )
        self.assertEqual(
            [st.session_state[key] for key in TEMPORARY_KEYS],
            ["gamma", "alpha", "selected_route", "route-2", True],
        )
        self.assertEqual(calls["preview"], [])
        self.assertNotIn(
            (
                "caption",
                "Attribute Group Swap preview is stale. Preview again before applying.",
            ),
            st.events,
        )
        self.assertIn(("metric", "Affected", 1), st.events)
        self.assertIn(
            (
                "button",
                "Apply Attribute Swap",
                "attribute_group_swap_apply_btn",
                False,
            ),
            st.events,
        )

    def test_hidden_widget_reconstruction_keeps_selected_routes_preview_but_not_confirmation(self):
        signature = (
            ("route-1", "route-2"),
            "alpha",
            "beta",
            True,
            "project.json",
        )
        state = {
            "attribute_group_swap_from": "alpha",
            "attribute_group_swap_to": "beta",
            "attribute_group_swap_scope": "selected_routes",
            "attribute_group_swap_selected_route_id": "route-2",
            "attribute_group_swap_require_full_match": True,
            "_attribute_group_swap_from_widget": "alpha",
            "_attribute_group_swap_to_widget": "beta",
            "_attribute_group_swap_scope_widget": "selected_routes",
            "_attribute_group_swap_selected_route_id_widget": "route-2",
            "_attribute_group_swap_require_full_match_widget": True,
            "attribute_group_swap_selected_routes_confirm": True,
            "attribute_group_swap_preview": {
                "signature": signature,
                "preview": {"valid": True, "changed_line_count": 1},
            },
        }
        namespace, st, calls, project = self._runtime(
            state=state,
            selected_routes_flow=True,
        )
        for key in TEMPORARY_KEYS:
            st.session_state.pop(key, None)
        st.session_state.pop(
            "attribute_group_swap_selected_routes_confirm",
            None,
        )
        namespace[self.workspace_name]()
        self.assertEqual(calls["selected_plan"], [])
        self.assertEqual(len(calls["selected_preview_render"]), 1)
        self.assertNotIn(
            "attribute_group_swap_selected_routes_confirm",
            st.session_state,
        )
        self.assertIn("attribute_group_swap_preview", st.session_state)

    def test_changed_normal_inputs_or_targets_keep_preview_stale_and_block_apply(self):
        base_signature = {
            "from_group_key": "alpha",
            "to_group_key": "beta",
            "scope": "selected_route",
            "selected_route_id": "route-1",
            "target_line_ids": ("line-1", "line-2"),
            "require_full_match": False,
        }
        cases = (
            (
                {"_attribute_group_swap_from_widget": "gamma"},
                {},
                ("line-1", "line-2"),
            ),
            (
                {"_attribute_group_swap_to_widget": "gamma"},
                {},
                ("line-1", "line-2"),
            ),
            (
                {"_attribute_group_swap_scope_widget": "all_lines"},
                {},
                ("line-1", "line-2"),
            ),
            (
                {
                    "_attribute_group_swap_selected_route_id_widget": (
                        "route-2"
                    )
                },
                {},
                ("line-1", "line-2"),
            ),
            (
                {},
                {},
                ("line-1",),
            ),
            (
                {
                    "_attribute_group_swap_require_full_match_widget": True
                },
                {},
                ("line-1", "line-2"),
            ),
        )
        for widget_values, extra_state, target_ids in cases:
            with self.subTest(widget_values=widget_values, targets=target_ids):
                state = {
                    "attribute_group_swap_from": "alpha",
                    "attribute_group_swap_to": "beta",
                    "attribute_group_swap_scope": "selected_route",
                    "attribute_group_swap_selected_route_id": "route-1",
                    "attribute_group_swap_require_full_match": False,
                    "attribute_group_swap_preview": {
                        "signature": base_signature,
                        "preview": {"keep": True},
                    },
                    **extra_state,
                }
                namespace, st, calls, project = self._runtime(
                    state=state,
                    widget_values=widget_values,
                    button_clicks=("attribute_group_swap_apply_btn",),
                    target_line_ids=target_ids,
                )
                namespace[self.renderer_name](project)
                self.assertIn(
                    "attribute_group_swap_preview",
                    st.session_state,
                )
                self.assertEqual(calls["apply"], [])
                self.assertIn(
                    (
                        "caption",
                        "Attribute Group Swap preview is stale. Preview again before applying.",
                    ),
                    st.events,
                )

    def test_changed_common_selected_routes_keeps_selected_preview_stale(self):
        state = {
            "attribute_group_swap_from": "alpha",
            "attribute_group_swap_to": "beta",
            "attribute_group_swap_scope": "selected_routes",
            "attribute_group_swap_require_full_match": False,
            "gallery_selected_route_ids": ["route-2"],
            "_attribute_group_swap_from_widget": "alpha",
            "_attribute_group_swap_to_widget": "beta",
            "_attribute_group_swap_scope_widget": "selected_routes",
            "_attribute_group_swap_selected_route_id_widget": "",
            "_attribute_group_swap_require_full_match_widget": False,
            "attribute_group_swap_preview": {
                "signature": (
                    ("route-1",),
                    "alpha",
                    "beta",
                    False,
                    "project.json",
                ),
                "preview": {"keep": True},
            },
        }
        namespace, st, calls, project = self._runtime(
            state=state,
            selected_routes_flow=True,
        )
        for key in TEMPORARY_KEYS:
            st.session_state.pop(key, None)
        namespace[self.workspace_name]()
        self.assertEqual(calls["selected_plan"], [])
        self.assertEqual(calls["selected_preview_render"], [])
        self.assertIn(
            (
                "caption",
                "Attribute Group Swap preview is stale. Fresh Preview is required before applying.",
            ),
            st.events,
        )
        self.assertIn("attribute_group_swap_preview", st.session_state)

    def test_success_notice_is_consumed_inside_open_apply_workspace(self):
        namespace, st, calls, project = self._runtime(
            state={
                "active_management_workspace": "module_attribute_apply",
                "attribute_group_swap_notice": "Swap complete.",
            },
        )

        namespace[self.workspace_name]()

        self.assertIn(("success", "Swap complete."), st.events)
        self.assertNotIn("attribute_group_swap_notice", st.session_state)
        self.assertEqual(
            st.session_state.active_management_workspace,
            "module_attribute_apply",
        )
        self.assertEqual(
            calls["workspace_children"],
            [
                ("toggle", project),
                ("insert", project),
                ("candidate", project),
            ],
        )

    def test_preview_buttons_build_one_plan_and_reset_selected_confirmation(self):
        namespace, st, calls, project = self._runtime(
            button_clicks=("attribute_group_swap_preview_btn",),
        )
        namespace[self.renderer_name](project)
        self.assertEqual(len(calls["preview"]), 1)
        self.assertIn("attribute_group_swap_preview", st.session_state)

        namespace, st, calls, project = self._runtime(
            state={
                "attribute_group_swap_scope": "selected_routes",
                "attribute_group_swap_selected_routes_confirm": True,
            },
            button_clicks=("attribute_group_swap_preview_btn",),
            selected_routes_flow=True,
        )
        namespace[self.renderer_name](project)
        self.assertEqual(len(calls["selected_plan"]), 1)
        self.assertFalse(
            st.session_state.attribute_group_swap_selected_routes_confirm
        )

    def test_normal_apply_sequence_and_durable_drafts_are_unchanged(self):
        renderer = self._source(self.renderer_name)
        apply_button = renderer.index('key="attribute_group_swap_apply_btn"')
        ordered = (
            "push_history()",
            'st.session_state.get("focused_line_id")',
            "st.session_state.project = apply_attribute_group_swap(",
            "restore_focus_after_graph_update(prev_focus)",
            "st.session_state.attribute_group_swap_notice =",
            'st.session_state.pop("attribute_group_swap_preview", None)',
            'save_current_project_if_possible("attribute group swap applied")',
            "st.rerun()",
        )
        positions = [renderer.index(text, apply_button) for text in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("sync_text_areas()", renderer[apply_button:])

        signature = {
            "from_group_key": "alpha",
            "to_group_key": "beta",
            "scope": "all_lines",
            "selected_route_id": "",
            "target_line_ids": ("line-1", "line-2"),
            "require_full_match": False,
        }
        namespace, st, calls, project = self._runtime(
            state={
                "attribute_group_swap_from": "alpha",
                "attribute_group_swap_to": "beta",
                "attribute_group_swap_scope": "all_lines",
                "attribute_group_swap_require_full_match": False,
                "attribute_group_swap_preview": {
                    "signature": signature,
                    "preview": {
                        "warnings": [],
                        "target_line_count": 2,
                        "affected_line_count": 1,
                        "no_match_line_count": 0,
                        "full_match_line_count": 1,
                        "partial_match_line_count": 0,
                        "tokens_to_remove": ["alpha"],
                        "tokens_to_add": ["beta"],
                        "shared_tokens": [],
                        "already_present_to_tokens": [],
                        "examples": [],
                    },
                },
            },
            button_clicks=("attribute_group_swap_apply_btn",),
        )
        namespace[self.renderer_name](project)
        self.assertEqual(calls["history"], 1)
        self.assertEqual(len(calls["apply"]), 1)
        self.assertEqual(calls["restore"], ["line-1"])
        self.assertEqual(calls["save"], ["attribute group swap applied"])
        self.assertEqual(st.rerun_count, 1)
        self.assertNotIn("attribute_group_swap_preview", st.session_state)
        for key, expected in zip(
            (
                "attribute_group_swap_from",
                "attribute_group_swap_to",
                "attribute_group_swap_scope",
                "attribute_group_swap_require_full_match",
            ),
            ("alpha", "beta", "all_lines", False),
        ):
            self.assertEqual(st.session_state[key], expected)

    def test_selected_routes_atomic_apply_contract_is_unchanged(self):
        preview = self._source(
            "_render_selected_routes_attribute_group_swap_preview"
        )
        apply_call = preview.index(
            "result = apply_selected_routes_attribute_group_swap"
        )
        success = preview.index('if result.get("applied"):', apply_call)
        history = preview.index("push_history()", success)
        assign = preview.index(
            'st.session_state.project = result["updated_project"]',
            success,
        )
        restore = preview.index(
            "restore_focus_after_graph_update(previous_focus)",
            assign,
        )
        sync = preview.index("sync_text_areas()", restore)
        clear_preview = preview.index(
            "st.session_state.pop(preview_state_key, None)",
            sync,
        )
        clear_confirm = preview.index(
            "st.session_state.pop(confirm_key, None)",
            clear_preview,
        )
        save = preview.index(
            'save_current_project_if_possible("selected Routes attribute group swap applied")',
            clear_confirm,
        )
        rerun = preview.index("st.rerun()", save)
        self.assertEqual(
            [
                apply_call,
                success,
                history,
                assign,
                restore,
                sync,
                clear_preview,
                clear_confirm,
                save,
                rerun,
            ],
            sorted(
                [
                    apply_call,
                    success,
                    history,
                    assign,
                    restore,
                    sync,
                    clear_preview,
                    clear_confirm,
                    save,
                    rerun,
                ]
            ),
        )
        self.assertNotIn(
            "push_history()",
            preview[apply_call:success],
        )
        for durable_key in DURABLE_KEYS:
            self.assertNotIn(f'pop("{durable_key}"', preview)

    def test_reset_clears_exact_operation_state_only(self):
        state = {
            **{key: f"value-{index}" for index, key in enumerate(RESET_KEYS)},
            "gallery_attribute_group_swap_from": "keep",
            "gallery_attribute_group_swap_preview": {"keep": True},
            "gallery_selected_route_ids": ["route-1"],
            "gallery_move_targets": {"line-1": True},
            "gallery_operations_active": True,
            "gallery_operation_focus": "attribute_group_swap",
            "gallery_feedback": "keep",
            "attribute_group_sidebar_selected": "keep",
            "module_candidate_preview": {"keep": True},
            "insert_module_reference_preview": {"keep": True},
            "module_edit_scope_name": "keep",
            "history": [{"keep": True}],
            "project": object(),
            "current_project_path": "project.json",
        }
        st = _StreamlitStub(state)
        namespace = self._load_functions(
            self.reset_name,
            namespace={"st": st},
        )
        namespace[self.reset_name]()
        for key in RESET_KEYS:
            self.assertNotIn(key, st.session_state)
        for key in set(state) - set(RESET_KEYS):
            self.assertIn(key, st.session_state)
        reset_source = self._source(self.reset_name)
        self.assertNotIn("startswith", reset_source)

    def test_successful_transition_ownership_and_back_boundary(self):
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
        self.assertNotIn(
            self.reset_name,
            loader[: loader.index("project = load_project_from_json")],
        )
        self.assertNotIn(self.reset_name, back)
        self.assertNotIn(self.reset_name, renderer)

    def test_apply_workspace_is_only_owner_and_gallery_stays_separate(self):
        self.assertEqual(
            self._call_owners(self.renderer_name),
            [self.workspace_name],
        )
        renderer = self._source(self.renderer_name)
        sidebar = self._source(
            "render_module_attribute_apply_sidebar_section"
        )
        workspace = self._source("render_module_attribute_apply_workspace")
        authoring = self._source(
            "render_module_attribute_authoring_workspace"
        )
        gallery = self._source(
            "render_gallery_attribute_group_swap_section"
        )
        self.assertIn(
            'with st.expander("Attribute Group Swap", expanded=False):',
            renderer,
        )
        self.assertNotIn("st.sidebar", renderer)
        self.assertEqual(
            workspace.count("render_attribute_group_swap_section(project)"),
            1,
        )
        self.assertNotIn(self.renderer_name, sidebar)
        self.assertNotIn(self.renderer_name, authoring)
        self.assertNotIn("attribute_group_swap_", authoring)
        for key in (
            "gallery_attribute_group_swap_from",
            "gallery_attribute_group_swap_to",
            "gallery_attribute_group_swap_scope",
            "gallery_attribute_group_swap_selected_route_id",
            "gallery_attribute_group_swap_require_full_match",
        ):
            self.assertIn(key, gallery)
        self.assertNotIn(
            "attribute_group_swap_selected_route_ids",
            self.app_source,
        )


if __name__ == "__main__":
    unittest.main()
