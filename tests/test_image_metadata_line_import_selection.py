"""Characterize the Project metadata preview and line conversion boundary."""

from core.io import (
    create_prompt_lines_from_latest_image_import,
    summarize_image_metadata_line_import,
)
from core.project import Project, PromptLine


def _existing_line():
    return PromptLine(
        id="imgmeta_0001",
        original_file_name="existing.txt",
        original_index=5,
        current_index=5,
        original_text="old",
        current_text="old",
        tokens=["old"],
    )


def test_latest_metadata_preview_and_append_preserve_order_and_project_data():
    images = [
        {"path": "positive.png", "filename": "positive.png", "prompt_text": "  cat, blue  ",
         "raw_metadata": {"future": ["keep"]}},
        {"path": "negative.png", "negative_prompt": "  blurry  "},
        {"path": "workflow.png", "has_comfy_workflow": True},
        {"path": "empty.png", "prompt_text": "  "},
        "unrecognized persisted record",
    ]
    extension = {"future": ["keep"]}
    imports = [{"images": [{"prompt_text": "older"}]}, {"images": images}]
    project = Project(
        prompt_lines=[_existing_line()],
        project_metadata={"image_imports": imports, "extension": extension},
    )
    original_lines = project.prompt_lines

    assert summarize_image_metadata_line_import(project) == {
        "has_import": True, "line_count": 3, "skipped_count": 2,
    }
    result, summary = create_prompt_lines_from_latest_image_import(project)

    assert result is project
    assert result.prompt_lines is original_lines
    assert summary == {"created_count": 3, "skipped_count": 2, "has_import": True}
    assert [line.id for line in result.prompt_lines] == [
        "imgmeta_0001", "imgmeta_0002", "imgmeta_0003", "imgmeta_0004",
    ]
    assert [line.current_index for line in result.prompt_lines] == [5, 6, 7, 8]
    assert [line.current_text for line in result.prompt_lines[1:]] == ["cat, blue", "", ""]
    assert [line.negative_prompt for line in result.prompt_lines[1:]] == ["", "blurry", ""]
    assert result.prompt_lines[1].source_generation_info["source_raw_metadata"] == {
        "future": ["keep"],
    }
    assert [line.image_path for line in result.prompt_lines[1:]] == [
        "positive.png", "negative.png", "workflow.png",
    ]
    assert result.project_metadata["image_imports"] is imports
    assert result.project_metadata["extension"] is extension
    assert result.line_map["imgmeta_0004"] is result.prompt_lines[-1]


def test_missing_import_and_replace_keep_legacy_project_mutation_order():
    project = Project(prompt_lines=[_existing_line()], line_groups={"group": ["imgmeta_0001"]})
    original_lines = project.prompt_lines

    assert summarize_image_metadata_line_import(project) == {
        "has_import": False, "line_count": 0, "skipped_count": 0,
    }
    result, summary = create_prompt_lines_from_latest_image_import(project, replace=True)
    assert result is project
    assert result.prompt_lines is original_lines
    assert project.line_groups == {"group": ["imgmeta_0001"]}
    assert summary == {"created_count": 0, "skipped_count": 0, "has_import": False}

    project.project_metadata["image_imports"] = [{"images": [{"negative_prompt": " "}]}]
    assert summarize_image_metadata_line_import(project) == {
        "has_import": True, "line_count": 1, "skipped_count": 0,
    }
    result, summary = create_prompt_lines_from_latest_image_import(project, replace=True)
    assert result is project
    assert result.prompt_lines is not original_lines
    assert project.line_groups == {}
    assert [(line.id, line.current_index, line.negative_prompt) for line in result.prompt_lines] == [
        ("imgmeta_0001", 0, ""),
    ]
    assert summary == {"created_count": 1, "skipped_count": 0, "has_import": True}
