import ast
import copy
import types
import unittest
from pathlib import Path

from core.operations import (
    apply_module_candidates,
    preview_apply_module_candidates,
    preview_module_candidates,
    set_module_candidate_rules,
)
from core.project import Project, PromptLine


FIXED_DURABLE_KEYS = (
    "module_candidate_selection_name",
    "module_candidate_preview",
    "module_candidate_apply_preview",
    "pending_module_candidate_selection",
    "module_candidate_pending_applied",
)
FIXED_TEMPORARY_KEY = "_module_candidate_selection_name_widget"
DURABLE_PREFIXES = (
    "module_candidate_core_tokens_",
    "module_candidate_min_match_tokens_",
)
TEMPORARY_PREFIXES = (
    "_module_candidate_core_tokens_widget_",
    "_module_candidate_min_match_tokens_widget_",
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
        return _Container()


class _StopExecution(Exception):
    pass


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
        return _Container()

    def _set_widget_value(self, key, widget_kwargs):
        if key in self.widget_values:
            previous_value = self.session_state.get(key)
            self.session_state[key] = self.widget_values[key]
            if previous_value != self.widget_values[key]:
                on_change = widget_kwargs.get("on_change")
                if on_change:
                    on_change(*widget_kwargs.get("args", ()))

    def selectbox(self, label, options, *, key, **kwargs):
        options = list(options)
        self._set_widget_value(key, kwargs)
        value = self.session_state.get(key, options[0])
        if value not in options:
            raise AssertionError(f"{key} has invalid value {value!r}")
        self.events.append(("selectbox", label, tuple(options), key, value))
        return value

    def multiselect(self, label, options, *, key, **kwargs):
        options = list(options)
        self._set_widget_value(key, kwargs)
        value = list(self.session_state.get(key, []))
        if any(item not in options for item in value):
            raise AssertionError(f"{key} has invalid values {value!r}")
        self.events.append(("multiselect", label, tuple(options), key, tuple(value)))
        return value

    def number_input(
        self,
        label,
        *,
        min_value,
        max_value,
        step,
        key,
        **kwargs,
    ):
        self._set_widget_value(key, kwargs)
        value = int(self.session_state.get(key, min_value))
        if not min_value <= value <= max_value:
            raise AssertionError(f"{key} has invalid value {value!r}")
        self.events.append(
            (
                "number_input",
                label,
                min_value,
                max_value,
                step,
                key,
                value,
            )
        )
        return value

    def button(self, label, *, key, **kwargs):
        self.events.append(("button", label, key))
        return key in self.button_clicks

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

    def metric(self, label, value):
        self.events.append(("metric", label, value))

    def divider(self):
        self.events.append(("divider",))

    def stop(self):
        raise _StopExecution()

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


class ModuleCandidateWorkspaceStateTests(unittest.TestCase):
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
        cls.renderer_name = "render_module_candidate_selection_section"
        cls.selection_helper = (
            "prepare_module_candidate_selection_widget_state"
        )
        cls.core_helper = (
            "prepare_module_candidate_core_tokens_widget_state"
        )
        cls.min_helper = "prepare_module_candidate_min_match_widget_state"
        cls.selection_sync = "sync_module_candidate_selection_widget_state"
        cls.core_sync = "sync_module_candidate_core_tokens_widget_state"
        cls.min_sync = "sync_module_candidate_min_match_widget_state"
        cls.reset_name = "reset_module_candidate_project_session_state"

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
        module_library=None,
        free=False,
    ):
        module_library = copy.deepcopy(
            {
                "Module A": {
                    "body": "red hair, blue eyes, smile",
                    "core_tokens": ["red hair", "blue eyes"],
                    "min_match_tokens": 2,
                },
                "Module B": {
                    "body": "green dress, ribbon",
                    "core_tokens": ["green dress"],
                    "min_match_tokens": 1,
                },
            }
            if module_library is None
            else module_library
        )
        project = types.SimpleNamespace(
            prompt_lines=[
                _line("line-1", "red hair, blue eyes, outdoors", 0),
                _line("line-2", "red hair, smile, portrait", 1),
            ],
            module_library=module_library,
        )
        initial_state = {
            "project": project,
            "focused_line_id": "line-1",
            "active_management_workspace": "",
        }
        initial_state.update(state or {})
        st = _StreamlitStub(
            initial_state,
            widget_values=widget_values,
            button_clicks=button_clicks,
        )
        calls = {
            "history": 0,
            "set_rules": [],
            "candidate_preview": [],
            "apply_preview": [],
            "apply": [],
            "restore": [],
            "sync": 0,
        }

        def _tokens(body):
            return [
                token.strip()
                for token in str(body or "").split(",")
                if token.strip()
            ]

        def _set_rules(value, module_name, core_tokens, min_match_tokens):
            calls["set_rules"].append(
                (
                    value,
                    module_name,
                    list(core_tokens),
                    int(min_match_tokens),
                )
            )
            return True

        def _candidate_preview(
            value,
            module_name,
            *,
            core_tokens,
            min_match_tokens,
        ):
            calls["candidate_preview"].append(
                (
                    value,
                    module_name,
                    list(core_tokens),
                    int(min_match_tokens),
                )
            )
            module_tokens = _tokens(module_library[module_name]["body"])
            return {
                "module_name": module_name,
                "module_tokens": module_tokens,
                "core_tokens": list(core_tokens),
                "min_match_tokens": int(min_match_tokens),
                "total_candidate_count": 1,
                "examples": [
                    {
                        "line_id": "line-1",
                        "display_id": "line-1.txt:1",
                        "matched_tokens": module_tokens[:1],
                        "missing_tokens": module_tokens[1:],
                        "matched_count": 1,
                        "total_token_count": len(module_tokens),
                        "match_ratio": 1 / len(module_tokens),
                        "text": value.prompt_lines[0].current_text,
                    }
                ],
            }

        def _apply_preview(
            value,
            module_name,
            *,
            core_tokens,
            min_match_tokens,
        ):
            calls["apply_preview"].append(
                (
                    value,
                    module_name,
                    list(core_tokens),
                    int(min_match_tokens),
                )
            )
            return {
                "module_name": module_name,
                "module_reference": f"<mod:{module_name}>",
                "candidate_line_count": 1,
                "affected_line_count": 1,
                "skipped_existing_reference_count": 0,
                "skipped_existing_module_block_count": 0,
                "examples": [
                    {
                        "line_id": "line-1",
                        "display_id": "line-1.txt:1",
                        "matched_tokens": ["red hair"],
                        "missing_tokens": ["blue eyes"],
                        "matched_count": 1,
                        "total_token_count": 2,
                        "match_ratio": 0.5,
                        "before": "red hair, outdoors",
                        "after": "<mod:Module A>, outdoors",
                    }
                ],
            }

        def _apply(
            value,
            module_name,
            *,
            core_tokens,
            min_match_tokens,
        ):
            calls["apply"].append(
                (
                    value,
                    module_name,
                    list(core_tokens),
                    int(min_match_tokens),
                )
            )
            return value

        def _history():
            calls["history"] += 1

        def _restore(value):
            calls["restore"].append(value)

        def _sync():
            calls["sync"] += 1

        namespace = {
            "st": st,
            "is_free": lambda: free,
            "get_project_module_library": lambda value: module_library,
            "get_module_body": lambda library, name: library[name]["body"],
            "get_module_core_tokens": (
                lambda library, name: list(
                    library[name].get("core_tokens", [])
                )
            ),
            "get_module_min_match_tokens": (
                lambda library, name: int(
                    library[name].get("min_match_tokens", 1)
                )
            ),
            "parse_prompt": _tokens,
            "_short_preview": lambda value, limit: str(value)[:limit],
            "set_module_candidate_rules": _set_rules,
            "preview_module_candidates": _candidate_preview,
            "preview_apply_module_candidates": _apply_preview,
            "apply_module_candidates": _apply,
            "push_history": _history,
            "restore_focus_after_graph_update": _restore,
            "sync_text_areas": _sync,
            "ACTIVE_MANAGEMENT_WORKSPACE_KEY": (
                "active_management_workspace"
            ),
            "render_module_toggle_controls": lambda value: None,
            "render_insert_saved_module_reference_section": lambda value: None,
            "render_attribute_group_swap_section": lambda value: None,
        }
        self._load_functions(
            self.reset_name,
            "reset_management_workspace_session_state",
            self.selection_helper,
            self.selection_sync,
            self.core_helper,
            self.core_sync,
            self.min_helper,
            self.min_sync,
            self.renderer_name,
            "render_module_attribute_apply_workspace",
            namespace=namespace,
        )
        return namespace, st, calls, project, module_library

    def _matching_previews(self, signature):
        return {
            "module_candidate_preview": {
                "signature": dict(signature),
                "preview": {
                    "module_name": signature["module_name"],
                    "module_tokens": ["red hair", "blue eyes", "smile"],
                    "core_tokens": list(signature["core_tokens"]),
                    "min_match_tokens": signature["min_match_tokens"],
                    "total_candidate_count": 1,
                    "examples": [],
                },
            },
            "module_candidate_apply_preview": {
                "signature": dict(signature),
                "preview": {
                    "module_name": signature["module_name"],
                    "module_reference": (
                        f"<mod:{signature['module_name']}>"
                    ),
                    "candidate_line_count": 1,
                    "affected_line_count": 1,
                    "skipped_existing_reference_count": 0,
                    "skipped_existing_module_block_count": 0,
                    "examples": [],
                },
            },
        }

    def test_widget_keys_are_temporary_and_buttons_are_unchanged(self):
        renderer = self._source(self.renderer_name)
        self.assertIn('key="_module_candidate_selection_name_widget"', renderer)
        self.assertIn(
            'key=f"_module_candidate_core_tokens_widget_{module_name}"',
            renderer,
        )
        self.assertIn(
            'key=f"_module_candidate_min_match_tokens_widget_{module_name}"',
            renderer,
        )
        self.assertNotIn('key="module_candidate_selection_name"', renderer)
        self.assertNotIn(
            'key=f"module_candidate_core_tokens_{module_name}"',
            renderer,
        )
        self.assertNotIn(
            'key=f"module_candidate_min_match_tokens_{module_name}"',
            renderer,
        )
        self.assertIn(
            "on_change=sync_module_candidate_selection_widget_state",
            renderer,
        )
        self.assertIn(
            "on_change=sync_module_candidate_core_tokens_widget_state",
            renderer,
        )
        self.assertIn(
            "on_change=sync_module_candidate_min_match_widget_state",
            renderer,
        )
        for key in (
            "module_candidate_save_rules_btn",
            "module_candidate_preview_btn",
            "module_candidate_apply_preview_btn",
            "module_candidate_apply_confirm_btn",
        ):
            self.assertEqual(renderer.count(f'key="{key}"'), 1)
        self.assertNotIn('key="module_candidate_preview"', renderer)
        self.assertNotIn('key="module_candidate_apply_preview"', renderer)
        self.assertNotIn("default=current_core_tokens", renderer)
        self.assertNotIn("value=current_min_match", renderer)

    def test_selection_hydration_defaults_rehydrates_and_repairs(self):
        namespace, st, _, _, _ = self._runtime()
        helper = namespace[self.selection_helper]

        self.assertEqual(helper(["Module A", "Module B"]), "Module A")
        self.assertEqual(
            st.session_state._module_candidate_selection_name_widget,
            "Module A",
        )

        st.session_state.module_candidate_selection_name = "Module B"
        st.session_state.pop(FIXED_TEMPORARY_KEY, None)
        self.assertEqual(helper(["Module A", "Module B"]), "Module B")
        self.assertEqual(
            st.session_state._module_candidate_selection_name_widget,
            "Module B",
        )

        st.session_state.module_candidate_selection_name = "Missing"
        st.session_state._module_candidate_selection_name_widget = "Module B"
        self.assertEqual(helper(["Module A", "Module B"]), "Module A")
        self.assertEqual(
            st.session_state._module_candidate_selection_name_widget,
            "Module A",
        )

    def test_core_token_normalization_preserves_empty_survivors_and_order(self):
        namespace, st, _, _, _ = self._runtime()
        helper = namespace[self.core_helper]
        options = ["one", "two", "three"]
        durable_key = "module_candidate_core_tokens_Module A"
        widget_key = "_module_candidate_core_tokens_widget_Module A"

        self.assertEqual(
            helper("Module A", options, ["two"]),
            ["two"],
        )
        self.assertEqual(st.session_state[widget_key], ["two"])

        st.session_state[durable_key] = []
        st.session_state.pop(widget_key, None)
        self.assertEqual(helper("Module A", options, ["two"]), [])
        self.assertEqual(st.session_state[widget_key], [])

        st.session_state[durable_key] = ["three", "missing", "one"]
        st.session_state[widget_key] = ["three", "missing", "one"]
        self.assertEqual(
            helper("Module A", options, ["two"]),
            ["three", "one"],
        )
        self.assertEqual(st.session_state[widget_key], ["three", "one"])

        st.session_state[durable_key] = ["missing"]
        st.session_state[widget_key] = ["missing"]
        self.assertEqual(helper("Module A", options, ["two"]), ["two"])
        self.assertEqual(st.session_state[widget_key], ["two"])
        self.assertTrue(
            set(st.session_state[widget_key]).issubset(options)
        )

    def test_minimum_match_normalization_uses_saved_and_clamps_tokens(self):
        namespace, st, _, _, _ = self._runtime()
        helper = namespace[self.min_helper]
        durable_key = "module_candidate_min_match_tokens_Module A"
        widget_key = "_module_candidate_min_match_tokens_widget_Module A"

        self.assertEqual(helper("Module A", ["one", "two", "three"], 2), 2)
        self.assertEqual(st.session_state[widget_key], 2)

        st.session_state[durable_key] = "invalid"
        st.session_state[widget_key] = 1
        self.assertEqual(helper("Module A", ["one", "two", "three"], 2), 2)
        self.assertEqual(st.session_state[widget_key], 2)

        st.session_state[durable_key] = 0
        st.session_state[widget_key] = 0
        self.assertEqual(helper("Module A", ["one", "two", "three"], 2), 1)

        st.session_state[durable_key] = 9
        st.session_state[widget_key] = 9
        self.assertEqual(helper("Module A", ["one", "two", "three"], 2), 3)

        st.session_state[durable_key] = 3
        st.session_state[widget_key] = 3
        self.assertEqual(helper("Module A", ["one", "two"], 1), 2)
        self.assertEqual(st.session_state[widget_key], 2)

    def test_per_module_unsaved_drafts_remain_independent(self):
        namespace, st, _, project, library = self._runtime()
        original_library = copy.deepcopy(library)
        core_helper = namespace[self.core_helper]
        min_helper = namespace[self.min_helper]

        core_helper("Module A", ["a", "b", "c"], ["a"])
        min_helper("Module A", ["a", "b", "c"], 1)
        st.session_state["module_candidate_core_tokens_Module A"] = ["b"]
        st.session_state["module_candidate_min_match_tokens_Module A"] = 2

        core_helper("Module B", ["x", "y"], ["x"])
        min_helper("Module B", ["x", "y"], 1)
        st.session_state["module_candidate_core_tokens_Module B"] = ["y"]
        st.session_state["module_candidate_min_match_tokens_Module B"] = 1

        for key in (
            "_module_candidate_core_tokens_widget_Module A",
            "_module_candidate_min_match_tokens_widget_Module A",
            "_module_candidate_core_tokens_widget_Module B",
            "_module_candidate_min_match_tokens_widget_Module B",
        ):
            st.session_state.pop(key, None)

        self.assertEqual(
            core_helper("Module A", ["a", "b", "c"], ["a"]),
            ["b"],
        )
        self.assertEqual(min_helper("Module A", ["a", "b", "c"], 1), 2)
        self.assertEqual(
            core_helper("Module B", ["x", "y"], ["x"]),
            ["y"],
        )
        self.assertEqual(min_helper("Module B", ["x", "y"], 1), 1)
        self.assertEqual(library, original_library)
        self.assertIs(st.session_state.project, project)

    def test_pending_module_applies_once_then_user_selection_wins(self):
        namespace, st, calls, project, _ = self._runtime(
            state={"pending_module_candidate_selection": "Module B"},
        )
        render = namespace["render_module_attribute_apply_workspace"]

        render()
        self.assertEqual(
            st.session_state.module_candidate_selection_name,
            "Module B",
        )
        self.assertEqual(
            st.session_state._module_candidate_selection_name_widget,
            "Module B",
        )
        self.assertEqual(
            st.session_state.module_candidate_pending_applied,
            "Module B",
        )

        st.widget_values = {
            "_module_candidate_selection_name_widget": "Module A"
        }
        render()
        self.assertEqual(
            st.session_state.module_candidate_selection_name,
            "Module A",
        )

        st.button_clicks = {"module_candidate_preview_btn"}
        st.widget_values = {}
        render()
        self.assertNotIn(
            "pending_module_candidate_selection",
            st.session_state,
        )
        self.assertEqual(len(calls["candidate_preview"]), 1)

    def test_created_module_handoff_opens_apply_workspace_once(self):
        project = types.SimpleNamespace(
            nodes={
                "node-1": types.SimpleNamespace(
                    original="red hair",
                    word="red hair",
                    display="red hair",
                )
            }
        )
        st = _StreamlitStub(
            {
                "selection_module_created_name": "New Module",
                "module_candidate_pending_applied": "Old Module",
            },
            button_clicks={
                "selection_module_candidate_hint_New Module"
            },
        )
        opened = []

        def _rerun():
            st.rerun_count += 1
            raise _StopExecution()

        st.rerun = _rerun
        namespace = self._load_functions(
            "render_selected_token_module_builder",
            namespace={
                "st": st,
                "build_module_reference_token": (
                    lambda name: f"<mod:{name}>"
                ),
                "open_management_workspace": opened.append,
            },
        )

        with self.assertRaises(_StopExecution):
            namespace["render_selected_token_module_builder"](
                project,
                ["node-1"],
            )

        self.assertEqual(
            st.session_state.pending_module_candidate_selection,
            "New Module",
        )
        self.assertEqual(
            st.session_state.module_candidate_pending_applied,
            "",
        )
        self.assertEqual(opened, ["module_attribute_apply"])
        self.assertEqual(st.rerun_count, 1)

    def test_back_and_hidden_widget_cleanup_preserve_both_previews(self):
        signature = {
            "module_name": "Module A",
            "core_tokens": ("red hair",),
            "min_match_tokens": 1,
        }
        state = {
            "active_management_workspace": "module_attribute_apply",
            "module_candidate_selection_name": "Module A",
            "module_candidate_core_tokens_Module A": ["red hair"],
            "module_candidate_min_match_tokens_Module A": 1,
            **self._matching_previews(signature),
        }
        namespace, st, _, project, _ = self._runtime(state=state)

        namespace["render_module_attribute_apply_workspace"]()
        self.assertIn(
            ("expander", "Module Candidate Selection", False),
            st.events,
        )
        st.events.clear()
        namespace["reset_management_workspace_session_state"]()
        self.assertEqual(st.session_state.active_management_workspace, "")
        self.assertNotIn(
            ("expander", "Module Candidate Selection", False),
            st.events,
        )
        for key in (
            FIXED_TEMPORARY_KEY,
            "_module_candidate_core_tokens_widget_Module A",
            "_module_candidate_min_match_tokens_widget_Module A",
        ):
            st.session_state.pop(key, None)
        st.session_state.active_management_workspace = "module_attribute_apply"
        namespace["render_module_attribute_apply_workspace"]()

        self.assertEqual(
            st.session_state._module_candidate_selection_name_widget,
            "Module A",
        )
        self.assertEqual(
            st.session_state[
                "_module_candidate_core_tokens_widget_Module A"
            ],
            ["red hair"],
        )
        self.assertEqual(
            st.session_state[
                "_module_candidate_min_match_tokens_widget_Module A"
            ],
            1,
        )
        self.assertNotIn(
            ("caption", "Candidate preview is out of date. Run preview again."),
            st.events,
        )
        self.assertNotIn(
            ("caption", "Apply preview is out of date. Run preview apply again."),
            st.events,
        )
        self.assertIn(("metric", "Will change", 1), st.events)

    def test_changed_or_normalized_input_keeps_preview_stale_and_blocks_apply(self):
        signature = {
            "module_name": "Module A",
            "core_tokens": ("red hair",),
            "min_match_tokens": 1,
        }
        state = {
            "module_candidate_selection_name": "Module A",
            "module_candidate_core_tokens_Module A": ["red hair"],
            "module_candidate_min_match_tokens_Module A": 1,
            **self._matching_previews(signature),
        }
        namespace, st, calls, project, _ = self._runtime(
            state=state,
            widget_values={
                "_module_candidate_core_tokens_widget_Module A": [],
            },
            button_clicks=("module_candidate_apply_confirm_btn",),
        )

        namespace[self.renderer_name](project)

        self.assertEqual(
            st.session_state["module_candidate_core_tokens_Module A"],
            [],
        )
        self.assertIn(
            ("caption", "Candidate preview is out of date. Run preview again."),
            st.events,
        )
        self.assertNotIn(
            ("button", "Preview Apply Candidates", "module_candidate_apply_preview_btn"),
            st.events,
        )
        self.assertEqual(calls["apply"], [])
        self.assertIn("module_candidate_preview", st.session_state)
        self.assertIn("module_candidate_apply_preview", st.session_state)

        st.events.clear()
        st.widget_values = {}
        st.button_clicks = set()
        st.session_state["module_candidate_core_tokens_Module A"] = [
            "removed token"
        ]
        st.session_state.pop(
            "_module_candidate_core_tokens_widget_Module A",
            None,
        )
        namespace[self.renderer_name](project)
        self.assertEqual(
            st.session_state["module_candidate_core_tokens_Module A"],
            ["red hair", "blue eyes"],
        )
        self.assertIn(
            ("caption", "Candidate preview is out of date. Run preview again."),
            st.events,
        )

    def test_stale_apply_preview_cannot_confirm_when_candidate_is_current(self):
        signature = {
            "module_name": "Module A",
            "core_tokens": ("red hair",),
            "min_match_tokens": 1,
        }
        previews = self._matching_previews(signature)
        previews["module_candidate_apply_preview"]["signature"] = {
            **signature,
            "min_match_tokens": 2,
        }
        namespace, st, calls, project, _ = self._runtime(
            state={
                "module_candidate_selection_name": "Module A",
                "module_candidate_core_tokens_Module A": ["red hair"],
                "module_candidate_min_match_tokens_Module A": 1,
                **previews,
            },
            button_clicks=("module_candidate_apply_confirm_btn",),
        )

        namespace[self.renderer_name](project)

        self.assertIn(
            ("caption", "Apply preview is out of date. Run preview apply again."),
            st.events,
        )
        self.assertEqual(calls["history"], 0)
        self.assertEqual(calls["apply"], [])
        self.assertIn("module_candidate_apply_preview", st.session_state)

    def test_save_rules_keeps_previews_and_drafts_without_rerun(self):
        signature = {
            "module_name": "Module A",
            "core_tokens": ("red hair",),
            "min_match_tokens": 1,
        }
        namespace, st, calls, project, _ = self._runtime(
            state={
                "module_candidate_selection_name": "Module A",
                "module_candidate_core_tokens_Module A": ["red hair"],
                "module_candidate_min_match_tokens_Module A": 1,
                **self._matching_previews(signature),
            },
            button_clicks=("module_candidate_save_rules_btn",),
        )

        namespace[self.renderer_name](project)

        self.assertEqual(calls["history"], 1)
        self.assertEqual(
            calls["set_rules"],
            [(project, "Module A", ["red hair"], 1)],
        )
        self.assertEqual(st.rerun_count, 0)
        self.assertIn("module_candidate_preview", st.session_state)
        self.assertIn("module_candidate_apply_preview", st.session_state)
        self.assertEqual(
            st.session_state["module_candidate_core_tokens_Module A"],
            ["red hair"],
        )
        self.assertEqual(
            st.session_state[
                "module_candidate_min_match_tokens_Module A"
            ],
            1,
        )
        renderer = self._source(self.renderer_name)
        self.assertNotIn("save_project", renderer)
        self.assertNotIn("autosave", renderer)

    def test_confirm_apply_preserves_drafts_and_clears_only_previews(self):
        signature = {
            "module_name": "Module A",
            "core_tokens": ("red hair",),
            "min_match_tokens": 1,
        }
        namespace, st, calls, project, _ = self._runtime(
            state={
                "module_candidate_selection_name": "Module A",
                "module_candidate_core_tokens_Module A": ["red hair"],
                "module_candidate_min_match_tokens_Module A": 1,
                **self._matching_previews(signature),
            },
            button_clicks=("module_candidate_apply_confirm_btn",),
        )

        namespace[self.renderer_name](project)

        self.assertEqual(calls["history"], 1)
        self.assertEqual(
            calls["apply"],
            [(project, "Module A", ["red hair"], 1)],
        )
        self.assertEqual(calls["restore"], ["line-1"])
        self.assertEqual(calls["sync"], 1)
        self.assertNotIn("module_candidate_preview", st.session_state)
        self.assertNotIn("module_candidate_apply_preview", st.session_state)
        self.assertEqual(
            st.session_state.module_candidate_selection_name,
            "Module A",
        )
        self.assertEqual(
            st.session_state["module_candidate_core_tokens_Module A"],
            ["red hair"],
        )
        self.assertEqual(
            st.session_state[
                "module_candidate_min_match_tokens_Module A"
            ],
            1,
        )
        self.assertEqual(st.rerun_count, 1)

    def test_reset_clears_only_candidate_operation_state(self):
        operation_keys = (
            *FIXED_DURABLE_KEYS,
            FIXED_TEMPORARY_KEY,
            "module_candidate_core_tokens_Module A",
            "module_candidate_min_match_tokens_Module A",
            "_module_candidate_core_tokens_widget_Module A",
            "_module_candidate_min_match_tokens_widget_Module A",
        )
        namespace, st, _, _, _ = self._runtime(
            state={
                **{key: f"value-{index}" for index, key in enumerate(operation_keys)},
                "global_module_candidate_scan": {"keep": True},
                "global_module_candidate_apply_preview": {"keep": True},
                "gallery_candidate_state": {"keep": True},
                "route_candidate_state": {"keep": True},
                "unrelated": "keep",
            }
        )

        namespace[self.reset_name]()

        for key in operation_keys:
            self.assertNotIn(key, st.session_state)
        for key in (
            "global_module_candidate_scan",
            "global_module_candidate_apply_preview",
            "gallery_candidate_state",
            "route_candidate_state",
            "unrelated",
        ):
            self.assertIn(key, st.session_state)

    def test_successful_transitions_own_reset_and_back_does_not(self):
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
            loader[
                : loader.index(
                    "project = load_project_from_json(project_path)"
                )
            ],
        )
        self.assertNotIn(self.reset_name, back)
        self.assertNotIn(self.reset_name, renderer)

    def test_apply_workspace_is_only_owner_after_insertion(self):
        self.assertEqual(
            self._call_owners(self.renderer_name),
            ["render_module_attribute_apply_workspace"],
        )
        renderer = self._source(self.renderer_name)
        sidebar = self._source(
            "render_module_attribute_apply_sidebar_section"
        )
        workspace = self._source("render_module_attribute_apply_workspace")
        self.assertIn(
            'with st.expander("Module Candidate Selection", '
            "expanded=False):",
            renderer,
        )
        self.assertNotIn("st.sidebar", renderer)
        candidate_call = "render_module_candidate_selection_section(project)"
        toggle_call = "render_module_toggle_controls(project)"
        insert_call = "render_insert_saved_module_reference_section(project)"
        swap_call = "render_attribute_group_swap_section(project)"
        self.assertLess(workspace.index(toggle_call), workspace.index(insert_call))
        self.assertLess(workspace.index(insert_call), workspace.index(candidate_call))
        self.assertLess(workspace.index(candidate_call), workspace.index(swap_call))
        self.assertEqual(workspace.count(candidate_call), 1)
        self.assertNotIn(candidate_call, sidebar)
        self.assertEqual(workspace.count(swap_call), 1)
        self.assertNotIn(swap_call, sidebar)
        self.assertEqual(sidebar.count("Open Apply Workspace"), 1)

    def test_free_empty_and_no_token_messages_remain_unchanged(self):
        cases = (
            (
                {"project": None},
                False,
                None,
                "Load project first.",
            ),
            (
                {},
                True,
                None,
                "Module Candidate Selection is available in Pro.",
            ),
            (
                {},
                False,
                {},
                "Create or load a project module before previewing candidates.",
            ),
            (
                {},
                False,
                {"Empty": {"body": "", "core_tokens": [], "min_match_tokens": 1}},
                "This module has no tokens to match.",
            ),
        )
        for state, free, library, message in cases:
            with self.subTest(message=message):
                namespace, st, _, project, _ = self._runtime(
                    state=state,
                    free=free,
                    module_library=library,
                )
                namespace[self.renderer_name](st.session_state.get("project"))
                self.assertIn(("info", message), st.events)


class ModuleCandidateCoreOperationRegressionTests(unittest.TestCase):
    def _project(self):
        return Project(
            module_library={
                "Character": {
                    "body": "red hair, blue eyes, smile",
                    "core_tokens": ["red hair"],
                    "min_match_tokens": 2,
                }
            },
            prompt_lines=[
                _line("match", "red hair, blue eyes, outdoors", 0),
                _line("missing", "red hair, outdoors", 1),
                _line("other", "blue eyes, smile, indoors", 2),
                _line("referenced", "<mod:Character>, red hair, blue eyes", 3),
                _line("block", "<mod:Other>, red hair, blue eyes, </mod:Other>", 4),
            ],
        )

    def test_rule_save_candidate_preview_apply_preview_and_apply(self):
        project = self._project()
        self.assertTrue(
            set_module_candidate_rules(
                project,
                "Character",
                ["red hair"],
                2,
            )
        )
        self.assertEqual(
            project.module_library["Character"]["core_tokens"],
            ["red hair"],
        )
        self.assertEqual(
            project.module_library["Character"]["min_match_tokens"],
            2,
        )

        candidate = preview_module_candidates(
            project,
            "Character",
            core_tokens=["red hair"],
            min_match_tokens=2,
        )
        candidate_ids = {
            example["line_id"] for example in candidate["examples"]
        }
        self.assertIn("match", candidate_ids)
        self.assertNotIn("missing", candidate_ids)
        match = next(
            example
            for example in candidate["examples"]
            if example["line_id"] == "match"
        )
        self.assertEqual(match["matched_tokens"], ["red hair", "blue eyes"])
        self.assertEqual(match["missing_tokens"], ["smile"])

        apply_preview = preview_apply_module_candidates(
            project,
            "Character",
            core_tokens=["red hair"],
            min_match_tokens=2,
        )
        self.assertEqual(apply_preview["candidate_line_count"], 3)
        self.assertEqual(apply_preview["affected_line_count"], 1)
        self.assertEqual(
            apply_preview["skipped_existing_reference_count"],
            0,
        )
        self.assertEqual(
            apply_preview["skipped_existing_module_block_count"],
            2,
        )
        example = apply_preview["examples"][0]
        self.assertEqual(
            example["after"],
            "<mod:Character>, outdoors",
        )
        self.assertNotIn("smile", example["after"])

        applied = apply_module_candidates(
            project,
            "Character",
            core_tokens=["red hair"],
            min_match_tokens=2,
        )
        changed = next(
            line for line in applied.prompt_lines if line.id == "match"
        )
        missing = next(
            line for line in applied.prompt_lines if line.id == "missing"
        )
        referenced = next(
            line for line in applied.prompt_lines if line.id == "referenced"
        )
        block = next(
            line for line in applied.prompt_lines if line.id == "block"
        )
        self.assertEqual(
            changed.current_text,
            "<mod:Character>, outdoors",
        )
        self.assertEqual(missing.current_text, "red hair, outdoors")
        self.assertEqual(
            referenced.current_text,
            "<mod:Character>, red hair, blue eyes",
        )
        self.assertEqual(
            block.current_text,
            "<mod:Other>, red hair, blue eyes, </mod:Other>",
        )


if __name__ == "__main__":
    unittest.main()
