"""Characterize the parameters dialect used by Project image imports."""

import copy

import pytest
from PIL import Image, PngImagePlugin

from core import io
from core.project import Project


@pytest.mark.parametrize("value", [None, {}, 0, "", " \r\n"])
def test_empty_or_non_text_parameters(value):
    assert io._parse_a1111_parameters(value) == {}
    assert io._extract_a1111_prompt_fields(value) == ("", "")


@pytest.mark.parametrize("separator", ["\n", "\r\n", "\r"])
def test_sections_normalize_newlines_but_preserve_raw_input(separator):
    raw = separator.join(["  cat", "blue sky", "Negative prompt: blur", "noise", "Steps: 20, Seed: 0042  "])
    assert io._parse_a1111_parameters(raw) == {
        "source_engine": "webui_a1111",
        "raw_parameters": raw,
        "prompt_text": "cat\nblue sky",
        "negative_prompt": "blur\nnoise",
        "raw_generation_params": "Steps: 20, Seed: 0042",
        "generation_params": {"Steps": "20", "Seed": "0042"},
    }


@pytest.mark.parametrize("raw, expected", [
    ("cat\nNegative prompt: blur", ("cat", "blur", "")),
    ("cat\nSteps: 0", ("cat", "", "Steps: 0")),
    ("cat\nsteps: 20", ("cat\nsteps: 20", "", "")),
    ("Negative prompt: blur", ("Negative prompt: blur", "", "")),
    ("cat\nNegative prompt: blur\nNegative prompt: noise", ("cat", "blur\nNegative prompt: noise", "")),
    ("cat\nModel: custom", ("cat", "", "Model: custom")),
])
def test_section_marker_and_parameter_start_contract(raw, expected):
    assert io._split_a1111_sections(raw) == expected


def test_quoted_commas_escapes_continuations_duplicate_keys_and_unknown_keys():
    raw = 'ignored, Steps: 20, Model: "a, b", Note: "say \\"hi, there\\"", Extra: first, tail, : empty-key, Steps: 30\nPlugin: x:y'
    assert io._parse_a1111_generation_params(raw) == {
        "Steps": "30",
        "Model": '"a, b"',
        "Note": '"say \\"hi, there\\""',
        "Extra": "first, tail, : empty-key",
        "Plugin": "x:y",
    }
    assert list(io._parse_a1111_generation_params(raw)) == ["Steps", "Model", "Note", "Extra", "Plugin"]


def test_explicit_prompts_override_parameters_without_mutating_metadata():
    metadata = {
        "Parameters": "cat\nNegative prompt: blur\nSteps: 20, Plugin: custom",
        "positive_prompt": " dog ", "negative": " noise ",
    }
    original = copy.deepcopy(metadata)
    fields = io._extract_image_prompt_fields(metadata)
    assert fields["prompt_text"] == "dog"
    assert fields["negative_prompt"] == "noise"
    assert fields["generation_params"] == {"Steps": "20", "Plugin": "custom"}
    assert fields["raw_parameters"] == metadata["Parameters"]
    assert fields["metadata_sources"] == ["a1111_parameters"]
    assert metadata == original


def test_png_import_line_creation_and_project_round_trip(tmp_path):
    raw = "cat, blue sky\nNegative prompt: blur\nSteps: 20, Seed: 0042, Plugin: custom"
    png_metadata = PngImagePlugin.PngInfo()
    png_metadata.add_text("parameters", raw)
    image_path = tmp_path / "image2.png"
    Image.new("RGB", (2, 3)).save(image_path, pnginfo=png_metadata)
    original_bytes = image_path.read_bytes()
    project = Project(project_metadata={"extension": {"keep": [1]}})
    summary = io.add_image_metadata_import(project, str(tmp_path))
    image_info = summary["images"][0]
    assert io.extract_image_metadata_for_path(str(image_path)) == image_info
    assert project.project_metadata["image_imports"][0] is summary
    assert image_info["raw_parameters"] == raw
    assert image_info["generation_params"] == {"Steps": "20", "Seed": "0042", "Plugin": "custom"}
    assert io.summarize_image_metadata_line_import(project) == {
        "has_import": True, "line_count": 1, "skipped_count": 0,
    }
    returned, result = io.create_prompt_lines_from_latest_image_import(project)
    assert returned is project
    assert result == {"created_count": 1, "skipped_count": 0, "has_import": True}
    line = project.prompt_lines[0]
    assert (line.id, line.current_text, line.negative_prompt) == ("imgmeta_0001", "cat, blue sky", "blur")
    assert line.source_generation_info["source_raw_metadata"] == {"parameters": raw}
    assert line.source_generation_info["source_generation_settings"]["seed"] == "0042"
    output = tmp_path / "project.json"
    io.save_project_to_json(project, str(output))
    loaded = io.load_project_from_json(str(output))
    assert loaded.project_metadata == project.project_metadata
    assert loaded.prompt_lines[0].source_generation_info == line.source_generation_info
    assert loaded.prompt_lines[0].current_text == line.current_text
    assert loaded.prompt_lines[0].negative_prompt == line.negative_prompt
    assert image_path.read_bytes() == original_bytes
