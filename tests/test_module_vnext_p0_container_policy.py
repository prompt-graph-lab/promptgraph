"""Module vNext P0: public container-boundary compatibility for `reference_assets`.

Synthetic fixtures only. Public never reads, copies, creates or deletes a
Module reference file; these tests also pin that `refs/modules/` is never
created by the covered operations.
"""

import copy
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from core.io import (
    load_global_module_library,
    load_project_from_json,
    save_global_module_library,
    save_project_to_json,
)
from core.lightweight_fork import (
    build_lightweight_fork_preview,
    build_lightweight_fork_project,
    materialize_lightweight_fork,
)
from core.lightweight_fork_append import (
    append_selected_routes_to_existing_fork,
    build_lightweight_fork_append_preview,
)
from core.module_container_policy import (
    MODULE_ASSET_NAMESPACE,
    REFERENCE_ASSETS_FIELD,
    count_modules_with_reference_assets,
    module_entry_for_prompt_only_container,
    module_has_reference_assets,
    module_library_for_prompt_only_container,
)
from core.operations import (
    apply_detected_modules,
    import_global_modules_to_project,
    normalize_module_library,
    set_module_candidate_rules,
    set_module_entry,
)
from core.project import Project, PromptLine
from ui import global_module_library_session as session

ASSET_PATH = "refs/modules/" + "a" * 64 + ".png"


def _reference_assets():
    return {
        "format": 1,
        "assets": [
            {
                "id": "front",
                "role": "character_reference",
                "media_type": "image/png",
                "path": ASSET_PATH,
                "sha256": "a" * 64,
                "label": "Front",
            },
            {
                "id": "side",
                "role": "future_role",
                "media_type": "image/png",
                "path": "refs/modules/" + "b" * 64 + ".png",
                "sha256": "b" * 64,
                "future_asset_field": {"keep": True},
            },
        ],
        "future_envelope_field": ["keep"],
    }


def _asset_module(body="red hair, blue eyes"):
    return {
        "body": body,
        "type": "character",
        "category": "Character",
        "description": "synthetic module",
        "extension": {"owner": "plugin", "nested": {"path": "relative/looking/value.png"}},
        REFERENCE_ASSETS_FIELD: _reference_assets(),
    }


def _line(line_id, index, *, text="prompt", image_path="", line_type=None):
    return PromptLine(
        id=line_id,
        original_file_name=f"{line_id}.png",
        original_index=index,
        current_index=index,
        original_text=text,
        current_text=text,
        tokens=[text],
        negative_prompt="",
        image_path=image_path,
        line_type=line_type,
        separator_label=text if line_type == "separator" else None,
    )


class _SessionState(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __setattr__(self, key, value):
        self[key] = value


def _no_managed_namespace(test, root):
    for dirpath, dirnames, _filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root).replace(os.sep, "/")
        test.assertFalse(
            rel.endswith("/".join(MODULE_ASSET_NAMESPACE))
            or rel == "/".join(MODULE_ASSET_NAMESPACE),
            f"unexpected managed namespace directory: {rel}",
        )


class PromptOnlyProjectionTests(unittest.TestCase):
    def test_constants(self):
        self.assertEqual("reference_assets", REFERENCE_ASSETS_FIELD)
        self.assertEqual(("refs", "modules"), MODULE_ASSET_NAMESPACE)

    def test_presence_is_the_signal_whatever_the_value(self):
        self.assertTrue(module_has_reference_assets(_asset_module()))
        self.assertTrue(module_has_reference_assets({REFERENCE_ASSETS_FIELD: None}))
        self.assertTrue(module_has_reference_assets({REFERENCE_ASSETS_FIELD: {"format": 1, "assets": []}}))
        self.assertFalse(module_has_reference_assets({"body": "x"}))
        self.assertFalse(module_has_reference_assets("plain body"))
        self.assertFalse(module_has_reference_assets(None))

    def test_entry_projection_removes_only_top_level_field_without_mutation(self):
        source = normalize_module_library({"char": _asset_module()})["char"]
        before = copy.deepcopy(source)

        projected = module_entry_for_prompt_only_container(source)

        self.assertEqual(before, source)
        self.assertNotIn(REFERENCE_ASSETS_FIELD, projected)
        expected = copy.deepcopy(before)
        expected.pop(REFERENCE_ASSETS_FIELD)
        self.assertEqual(expected, projected)
        self.assertEqual(before["graph"], projected["graph"])
        self.assertEqual(
            {"owner": "plugin", "nested": {"path": "relative/looking/value.png"}},
            projected["extension"],
        )
        projected["extension"]["nested"]["path"] = "changed"
        self.assertEqual("relative/looking/value.png", source["extension"]["nested"]["path"])

    def test_nested_field_with_the_same_name_is_not_special(self):
        entry = {"body": "x", "extension": {REFERENCE_ASSETS_FIELD: "nested stays"}}
        self.assertEqual(entry, module_entry_for_prompt_only_container(entry))

    def test_non_dict_entry_is_copied_unchanged(self):
        self.assertEqual("plain body", module_entry_for_prompt_only_container("plain body"))

    def test_library_projection_keeps_names_and_order(self):
        library = {
            "zeta": {"body": "z"},
            "alpha": _asset_module(),
            "mid": {"body": "m", "extension": {"keep": 1}},
        }
        before = copy.deepcopy(library)

        projected = module_library_for_prompt_only_container(library)

        self.assertEqual(before, library)
        self.assertEqual(["zeta", "alpha", "mid"], list(projected))
        self.assertNotIn(REFERENCE_ASSETS_FIELD, projected["alpha"])
        self.assertEqual({"body": "m", "extension": {"keep": 1}}, projected["mid"])
        self.assertEqual({}, module_library_for_prompt_only_container(None))
        self.assertEqual(1, count_modules_with_reference_assets(library))
        self.assertEqual(0, count_modules_with_reference_assets(projected))


class SameProjectPreservationTests(unittest.TestCase):
    def test_normalize_preserves_reference_assets_and_unknown_fields(self):
        normalized = normalize_module_library({"char": _asset_module()})
        self.assertEqual(_reference_assets(), normalized["char"][REFERENCE_ASSETS_FIELD])
        self.assertEqual("plugin", normalized["char"]["extension"]["owner"])

        project = Project()
        project.module_library = {"char": _asset_module()}
        normalize_module_library(project)
        self.assertEqual(_reference_assets(), project.module_library["char"][REFERENCE_ASSETS_FIELD])

    def test_project_save_load_round_trip_preserves_field_and_creates_no_namespace(self):
        project = Project()
        project.module_library = {"char": _asset_module()}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "project.json"
            save_project_to_json(project, path)
            serialized = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                _reference_assets(),
                serialized["module_library"]["char"][REFERENCE_ASSETS_FIELD],
            )
            reopened = load_project_from_json(path)
            self.assertEqual(
                _reference_assets(),
                reopened.module_library["char"][REFERENCE_ASSETS_FIELD],
            )
            self.assertEqual("plugin", reopened.module_library["char"]["extension"]["owner"])
            save_project_to_json(reopened, path)
            self.assertEqual(serialized, json.loads(path.read_text(encoding="utf-8")))
            _no_managed_namespace(self, tmpdir)

    def test_prompt_field_edit_preserves_reference_assets(self):
        project = Project()
        project.module_library = {"char": _asset_module()}

        set_module_entry(project, "char", "silver hair, red eyes", "character", ["silver hair"], 1, "Character")
        set_module_candidate_rules(project, "char", ["red eyes"], 1)

        entry = project.module_library["char"]
        self.assertEqual("silver hair, red eyes", entry["body"])
        self.assertEqual(_reference_assets(), entry[REFERENCE_ASSETS_FIELD])
        self.assertEqual("synthetic module", entry["description"])
        self.assertEqual("plugin", entry["extension"]["owner"])


class GlobalBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = {"global_module_library_dir": self.temp.name}

    def tearDown(self):
        self.temp.cleanup()

    def _path(self):
        return Path(self.temp.name) / "global_modules.json"

    def test_global_save_cannot_serialize_reference_assets(self):
        library = {"char": _asset_module(), "plain": {"body": "x", "notes": "keep"}}
        before = copy.deepcopy(library)

        save_global_module_library(library, self.settings)

        self.assertEqual(before, library)
        raw = json.loads(self._path().read_text(encoding="utf-8"))
        self.assertNotIn(REFERENCE_ASSETS_FIELD, raw["char"])
        self.assertNotIn(ASSET_PATH, self._path().read_text(encoding="utf-8"))
        self.assertEqual("synthetic module", raw["char"]["description"])
        self.assertEqual(
            {"owner": "plugin", "nested": {"path": "relative/looking/value.png"}},
            raw["char"]["extension"],
        )
        self.assertEqual("keep", raw["plain"]["notes"])

    def test_global_load_drops_stale_legacy_field_and_keeps_other_metadata(self):
        self._path().write_text(
            json.dumps({"char": _asset_module(), "plain": {"body": "x", "notes": "keep"}}),
            encoding="utf-8",
        )

        loaded = load_global_module_library(self.settings)

        self.assertNotIn(REFERENCE_ASSETS_FIELD, loaded["char"])
        self.assertEqual("plugin", loaded["char"]["extension"]["owner"])
        self.assertEqual("keep", loaded["plain"]["notes"])

    def test_global_library_without_the_field_round_trips_unchanged(self):
        library = {"char": {"body": "a, b", "extension_metadata": {"future": "keep"}}}
        save_global_module_library(library, self.settings)
        self.assertEqual(normalize_module_library(library), load_global_module_library(self.settings))

    def test_authoritative_animadex_style_overwrite_stays_prompt_only(self):
        # A stale legacy field on another Global entry must not survive an
        # authoritative save, and the AnimaDex-style fresh entry keeps its
        # own metadata.
        self._path().write_text(
            json.dumps({
                "stale": _asset_module(),
                "animadex_char": {"body": "old", "notes": "replaced"},
            }),
            encoding="utf-8",
        )
        state = types.SimpleNamespace(session_state=_SessionState(settings=self.settings))
        patcher = mock.patch.object(session, "st", state)
        patcher.start()
        self.addCleanup(patcher.stop)

        def apply_animadex_import(authoritative_library):
            authoritative_library["animadex_char"] = {
                "body": "new body",
                "type": "character",
                "category": "Character",
                "core_tokens": ["new body"],
                "min_match_tokens": 1,
                "animadex_metadata": {"record_id": "synthetic", "source_url": "https://example.invalid/x"},
            }
            return authoritative_library

        _path, persisted = session.save_and_cache_global_module_library(apply_animadex_import)

        raw = json.loads(self._path().read_text(encoding="utf-8"))
        for library in (persisted, raw):
            self.assertNotIn(REFERENCE_ASSETS_FIELD, library["stale"])
            self.assertEqual("plugin", library["stale"]["extension"]["owner"])
            self.assertEqual({"record_id": "synthetic", "source_url": "https://example.invalid/x"},
                             library["animadex_char"]["animadex_metadata"])


class GlobalToProjectTests(unittest.TestCase):
    def _global(self):
        stale = _asset_module("global body")
        stale["description"] = "global description"
        return {
            "stale": stale,
            "shared": {"body": "global shared", "notes": "from global"},
            "fresh": {"body": "fresh body", "notes": "fresh"},
        }

    def test_new_name_imports_sanitized_prompt_only_entry(self):
        project = Project()
        global_library = self._global()
        before_global = copy.deepcopy(global_library)

        result = import_global_modules_to_project(project, global_library, ["stale", "fresh"])

        self.assertEqual(["stale", "fresh"], result["imported"])
        self.assertEqual([], result["blocked_reference_asset_overwrite"])
        self.assertEqual(before_global, global_library)
        self.assertNotIn(REFERENCE_ASSETS_FIELD, project.module_library["stale"])
        self.assertEqual("global description", project.module_library["stale"]["description"])
        self.assertEqual("plugin", project.module_library["stale"]["extension"]["owner"])

    def test_overwrite_without_assets_keeps_existing_contract(self):
        project = Project()
        project.module_library = {"shared": {"body": "project shared", "project_only": "dropped by wholesale replace"}}

        result = import_global_modules_to_project(project, self._global(), ["shared"], overwrite=True)

        self.assertEqual(["shared"], result["imported"])
        self.assertEqual("global shared", project.module_library["shared"]["body"])
        self.assertNotIn("project_only", project.module_library["shared"])

    def test_overwrite_false_behavior_is_unchanged(self):
        project = Project()
        project.module_library = {"shared": {"body": "project shared"}, "stale": _asset_module("project body")}
        before = copy.deepcopy(normalize_module_library(project))

        result = import_global_modules_to_project(project, self._global(), ["shared", "stale", "missing"])

        self.assertEqual([], result["imported"])
        self.assertEqual(["shared", "stale"], result["skipped_existing"])
        self.assertEqual(["missing"], result["skipped_missing"])
        self.assertEqual([], result["blocked_reference_asset_overwrite"])
        self.assertEqual(before, project.module_library)

    def test_overwrite_of_asset_bearing_destination_is_refused_per_module(self):
        project = Project()
        project.module_library = {
            "stale": _asset_module("project body"),
            "shared": {"body": "project shared"},
        }
        protected_before = copy.deepcopy(normalize_module_library(project)["stale"])

        result = import_global_modules_to_project(
            project, self._global(), ["stale", "shared"], overwrite=True
        )

        self.assertEqual(["shared"], result["imported"])
        self.assertEqual(["stale"], result["blocked_reference_asset_overwrite"])
        self.assertEqual(protected_before, project.module_library["stale"])
        self.assertEqual("project body", project.module_library["stale"]["body"])
        self.assertEqual("global shared", project.module_library["shared"]["body"])
        self.assertNotIn(ASSET_PATH, json.dumps(result))

    def test_apply_detected_modules_imports_prompt_only_entries(self):
        project = Project(prompt_lines=[_line("l1", 0, text="red hair, blue eyes, smile")])
        project.prompt_lines[0].tokens = ["red hair", "blue eyes", "smile"]
        global_library = {"char": _asset_module("red hair, blue eyes")}

        apply_detected_modules(project, global_library, ["char"])

        self.assertIn("char", project.module_library)
        self.assertNotIn(REFERENCE_ASSETS_FIELD, project.module_library["char"])
        self.assertEqual("plugin", project.module_library["char"]["extension"]["owner"])
        self.assertIn(REFERENCE_ASSETS_FIELD, global_library["char"])


class DerivedProjectTests(unittest.TestCase):
    def _image(self, directory, name, payload=b"image"):
        path = os.path.join(directory, name)
        with open(path, "wb") as handle:
            handle.write(payload)
        return path

    def _source(self, tmpdir):
        project = Project(prompt_lines=[
            _line("route_a", 0, text="Route A", line_type="separator"),
            _line("a1", 1, text="A prompt", image_path=self._image(tmpdir, "a.png", b"a")),
            _line("route_b", 2, text="Route B", line_type="separator"),
            _line("b1", 3, text="B prompt", image_path=self._image(tmpdir, "b.png", b"b")),
        ])
        project.module_library = {"char": _asset_module(), "plain": {"body": "keep", "notes": "n"}}
        # A synthetic managed file in the SOURCE Project only.
        managed = os.path.join(tmpdir, *MODULE_ASSET_NAMESPACE)
        os.makedirs(managed)
        self._image(managed, "a" * 64 + ".png", b"not copied")
        source_path = os.path.join(tmpdir, "source-project.json")
        save_project_to_json(project, source_path)
        return project, source_path

    def _assert_prompt_only(self, fork_project):
        self.assertNotIn(REFERENCE_ASSETS_FIELD, fork_project.module_library["char"])
        self.assertEqual("synthetic module", fork_project.module_library["char"]["description"])
        self.assertEqual("plugin", fork_project.module_library["char"]["extension"]["owner"])
        self.assertIn("graph", fork_project.module_library["char"])
        self.assertEqual("n", fork_project.module_library["plain"]["notes"])

    def test_build_is_prompt_only_for_all_scopes_and_source_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project, source_path = self._source(tmpdir)
            source_library_before = copy.deepcopy(project.module_library)
            for scope, extra in (
                ("all_lines", {}),
                ("selected_routes", {"selected_route_ids": ["route_b"]}),
            ):
                preview = build_lightweight_fork_preview(
                    project.prompt_lines,
                    fork_name="fork",
                    scope=scope,
                    project_path=source_path,
                    path_exists=os.path.exists,
                    **extra,
                )
                fork_project, _entries = build_lightweight_fork_project(project, preview)
                self._assert_prompt_only(fork_project)
            self.assertEqual(source_library_before, project.module_library)

    def test_materialized_derived_project_has_no_dangling_reference_assets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project, source_path = self._source(tmpdir)
            source_json_before = Path(source_path).read_bytes()
            preview = build_lightweight_fork_preview(
                project.prompt_lines,
                fork_name="derived",
                project_path=source_path,
                path_exists=os.path.exists,
            )
            destination_parent = os.path.join(tmpdir, "forks")

            result = materialize_lightweight_fork(
                project,
                source_project_path=source_path,
                stored_preview=preview,
                destination_parent_dir=destination_parent,
                fork_name="derived",
            )

            self.assertTrue(result["success"], result)
            self.assertEqual(1, result["module_reference_assets_omitted_count"])
            raw = Path(result["project_path"]).read_text(encoding="utf-8")
            self.assertNotIn(REFERENCE_ASSETS_FIELD, raw)
            self.assertNotIn(ASSET_PATH, raw)
            self._assert_prompt_only(load_project_from_json(result["project_path"]))
            _no_managed_namespace(self, result["destination_directory"])
            self.assertTrue(all(
                "refs" not in item["source"].replace(os.sep, "/").split("/")
                for item in result["copied_files"]
            ))
            self.assertIn(REFERENCE_ASSETS_FIELD, project.module_library["char"])
            self.assertEqual(source_json_before, Path(source_path).read_bytes())

    def test_append_keeps_existing_fork_modules_and_adds_no_source_assets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project, source_path = self._source(tmpdir)
            destination_parent = os.path.join(tmpdir, "forks")
            preview = build_lightweight_fork_preview(
                project.prompt_lines,
                fork_name="existing",
                scope="selected_routes",
                project_path=source_path,
                selected_route_ids=["route_a"],
                path_exists=os.path.exists,
            )
            created = materialize_lightweight_fork(
                project,
                source_project_path=source_path,
                stored_preview=preview,
                destination_parent_dir=destination_parent,
                fork_name="existing",
            )
            self.assertTrue(created["success"], created)
            fork_modules_before = json.loads(
                Path(created["project_path"]).read_text(encoding="utf-8")
            )["module_library"]

            append_preview = build_lightweight_fork_append_preview(
                project,
                source_project_path=source_path,
                selected_route_ids=["route_b"],
                existing_fork_project_path=created["project_path"],
                current_open_project_path=source_path,
            )
            self.assertTrue(append_preview["valid"], append_preview)
            appended = append_selected_routes_to_existing_fork(
                project,
                source_project_path=source_path,
                selected_route_ids=["route_b"],
                existing_fork_project_path=created["project_path"],
                stored_preview=append_preview,
                current_open_project_path=source_path,
            )

            self.assertTrue(appended["success"], appended)
            raw = json.loads(Path(created["project_path"]).read_text(encoding="utf-8"))
            self.assertEqual(fork_modules_before, raw["module_library"])
            self.assertNotIn(ASSET_PATH, json.dumps(raw))
            _no_managed_namespace(self, created["destination_directory"])


if __name__ == "__main__":
    unittest.main()
