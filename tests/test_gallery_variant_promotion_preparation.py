import ast
import copy
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import gallery_variant_promotion as promotion
from core.parser import parse_prompt
from core.project import Project, PromptLine


def source_line():
    return PromptLine(
        id="parent", original_file_name="parent.png", original_index=2, current_index=4,
        original_text="old", current_text="red, blue", tokens=["old"],
        negative_prompt="negative", node_path=["node"], deleted=True,
        image_path="parent.png", generated_image_path="generated.png",
        selected_candidate_path="selected.png", generated_candidates=[{"path": "old.png"}],
        gallery_variants=[{"path": "variant.png"}], line_type="workbench",
        separator_label="label", separator_color="red", workbench_source_line_id="origin",
        workbench_title="title", workbench_note="note", workbench_status="draft",
    )


@pytest.mark.parametrize("supplied", [None, {}, {"nested": {"keep": True}}])
def test_materialization_contract_and_shallow_provenance(supplied):
    source = source_line()
    variant = {"id": "variant-id", "source_generation_info": supplied, "lineage_info": supplied}
    before_source, before_variant = copy.deepcopy(source), copy.deepcopy(variant)
    calls = []
    metadata = {"source": "gallery_variant_promotion", "created_at": "created"}

    def record(value):
        assert value is variant
        calls.append(value)
        return dict(metadata)

    result = promotion.prepare_gallery_variant_promotion_line(
        source, variant, "images/variant.png", lambda: "new-id", record,
    )
    assert isinstance(result, PromptLine)
    assert result is not source
    assert source == before_source and variant == before_variant
    assert result.id == "new-id"
    assert result.original_file_name == "variant.png"
    assert result.original_text == result.current_text == source.current_text
    assert result.tokens == parse_prompt(source.current_text)
    assert result.tokens is not source.tokens
    assert result.duplicated_from == "parent"
    assert result.edited is True and result.deleted is False
    assert result.image_path == "images/variant.png"
    assert result.original_index == 2 and result.current_index == 4
    assert result.negative_prompt == "negative"
    assert result.node_path == source.node_path and result.node_path is not source.node_path
    for name in ("generated_image_path", "selected_candidate_path", "line_type", "separator_label",
                 "separator_color", "workbench_source_line_id", "workbench_title", "workbench_note",
                 "workbench_status"):
        assert getattr(result, name) is None
    assert result.generated_candidates == result.gallery_variants == []
    assert result.generated_candidates is not result.gallery_variants
    expected_lineage = {
        "lineage_kind": "gallery_variant_promote_to_route", "parent_line_id": "parent",
        "parent_line_index": 4, "parent_line_label": "parent.png", "parent_image_path": "selected.png",
        "promoted_from_variant_id": "variant-id", "promoted_from_variant_path": "images/variant.png",
        "candidate_image_path": "images/variant.png",
    }
    if supplied is None:
        assert len(calls) == 2
        assert result.source_generation_info == {
            "source_kind": "derived_candidate", "source_image_path": "images/variant.png",
            "source_prompt": "red, blue", "source_negative_prompt": "negative",
            "source_raw_metadata": metadata,
        }
        expected_lineage.update(created_from="gallery_variant_promotion", candidate_created_at="created")
    else:
        assert calls == []  # Empty dictionaries also bypass metadata fallback.
        assert result.source_generation_info == supplied
        assert result.source_generation_info is not supplied
        assert result.lineage_info is not supplied
        expected_lineage.update(supplied)
        if supplied:
            assert result.source_generation_info["nested"] is supplied["nested"]
            assert result.lineage_info["nested"] is supplied["nested"]
    assert result.lineage_info == expected_lineage


@pytest.mark.parametrize("selected,generated,image,expected", [
    ("", "generated.png", "parent.png", "generated.png"),
    (None, "", "parent.png", "parent.png"),
    (None, None, None, "retained.png"),
])
def test_parent_image_fallback_and_falsey_variant_id(selected, generated, image, expected):
    source = source_line()
    source.selected_candidate_path, source.generated_image_path, source.image_path = selected, generated, image
    source.original_file_name = ""
    variant = {"id": "", "source_generation_info": {},
               "lineage_info": {"parent_image_path": "retained.png", "promoted_from_variant_id": "retained-id"}}
    result = promotion.prepare_gallery_variant_promotion_line(source, variant, "v.png", lambda: "new", None)
    assert result.lineage_info["parent_image_path"] == expected
    assert result.lineage_info["parent_line_label"] == "parent"
    assert result.lineage_info["promoted_from_variant_id"] == "retained-id"


@pytest.mark.parametrize("failure", [None, "copy", "id", "parse", "metadata1", "source", "metadata2", "lineage"])
def test_preparation_step_order_failure_and_returned_copy(monkeypatch, failure):
    source, variant = source_line(), {"path": "v.png"}
    before_source, before_variant = copy.deepcopy(source), copy.deepcopy(variant)
    cloned = copy.deepcopy(source)
    events, records = [], []
    error = RuntimeError("preparation failed")

    def step(name, result):
        events.append(name)
        if name == failure:
            raise error
        return result

    monkeypatch.setattr(promotion.copy, "deepcopy", lambda value: step("copy", cloned))
    monkeypatch.setattr(promotion, "parse_prompt", lambda text: step("parse", ["parsed"]))

    def metadata(value):
        assert value is variant
        record = {"number": len(records) + 1}
        records.append(record)
        return step("metadata" + str(len(records)), record)

    def build(name, line, path, record):
        assert line is source and path == "v.png" and record is records[-1]
        assert cloned.generated_candidates == cloned.gallery_variants == []
        assert cloned.line_type is None and cloned.workbench_status is None
        return step(name, {})

    monkeypatch.setattr(promotion, "build_source_generation_info_from_candidate",
                        lambda *args: build("source", *args))
    monkeypatch.setattr(promotion, "build_lineage_info_from_candidate",
                        lambda *args: build("lineage", *args))
    expected = ["copy", "id", "parse", "metadata1", "source", "metadata2", "lineage"]
    if failure:
        with pytest.raises(RuntimeError) as caught:
            promotion.prepare_gallery_variant_promotion_line(
                source, variant, "v.png", lambda: step("id", "new"), metadata,
            )
        assert caught.value is error
        assert events == expected[:expected.index(failure) + 1]
    else:
        result = promotion.prepare_gallery_variant_promotion_line(
            source, variant, "v.png", lambda: step("id", "new"), metadata,
        )
        assert result is cloned
        assert events == expected
        assert records[0] is not records[1]
    assert source == before_source and variant == before_variant


@pytest.fixture(scope="module")
def caller_node():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    return next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)
                and node.name == "promote_gallery_variant_to_route")


@pytest.mark.parametrize("manage_state", [False, True])
@pytest.mark.parametrize("failure", [None, "prepare", "missing"])
def test_caller_keeps_validation_and_publication(caller_node, manage_state, failure):
    source = source_line()
    project = Project(prompt_lines=[source])
    alias = project.prompt_lines
    new_line = copy.deepcopy(source)
    new_line.id = "line_12345678"
    events = []
    error = ValueError("failed preparation")

    class State(dict):
        __getattr__ = dict.__getitem__

        def __setattr__(self, name, value):
            events.append(name)
            self[name] = value

    state = State(project=project, focused_line_id="old-focus")
    variant = {"path": "v.png"}
    metadata_provider = object()

    def prepare(line, value, path, new_line_id, promotion_metadata):
        assert line is source and value is variant and path == "v.png"
        assert promotion_metadata is metadata_provider
        assert project.prompt_lines == [source]
        assert new_line_id() == "line_12345678"
        events.append("prepare")
        if failure == "prepare":
            raise error
        return new_line

    def reindex(value):
        assert value is project and value.prompt_lines is alias
        assert value.prompt_lines[1] is new_line
        events.append("reindex")

    def graph(value):
        assert value is project and value.prompt_lines[1] is new_line
        events.append("graph")
        return value

    namespace = {
        "os": SimpleNamespace(path=SimpleNamespace(exists=lambda path: failure != "missing")),
        "get_line_by_id": lambda value, line_id: source,
        "_normalize_candidate_path": lambda path: path,
        "_runtime_asset_path": lambda path: path,
        "push_history": lambda: events.append("history"),
        "uuid": SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="12345678abcdef")),
        "prepare_gallery_variant_promotion_line": prepare,
        "_variant_record_for_promotion": metadata_provider,
        "_promoted_route_insert_index": lambda *args: events.append("insert_index") or 1,
        "_reindex_project_lines": reindex, "st": SimpleNamespace(session_state=state),
        "build_graph": graph, "restore_focus_after_graph_update": lambda value: events.append(("focus", value)),
        "sync_text_areas": lambda: events.append("sync"),
        "save_current_project_if_possible": lambda message: events.append(("save", message)),
    }
    exec(compile(ast.Module(body=[caller_node], type_ignores=[]), "app.py", "exec"), namespace)
    expected = ["history"] if manage_state else []
    if failure == "prepare":
        with pytest.raises(ValueError) as caught:
            namespace[caller_node.name](project, source.id, variant, manage_state)
        assert caught.value is error
        assert events == expected + ["prepare"]
        assert project.prompt_lines == [source]
    elif failure == "missing":
        assert namespace[caller_node.name](project, source.id, variant, manage_state) is None
        assert events == [] and project.prompt_lines == [source]
    else:
        assert namespace[caller_node.name](project, source.id, variant, manage_state) == new_line.id
        expected += ["prepare", "insert_index", "reindex"]
        if manage_state:
            expected += ["graph", "project", ("focus", "old-focus"), "highlighted_line_id",
                         "gallery_expanded_line_id", "sync", ("save", "gallery variant promoted to route")]
        assert events == expected
