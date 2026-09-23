"""Read-only selection and preview for lines from a Project image import."""


def image_import_prompt_text(image_info: dict) -> str:
    return str(image_info.get("prompt_text") or "").strip()


def should_create_image_metadata_line(image_info: dict) -> bool:
    return bool(
        image_import_prompt_text(image_info)
        or image_info.get("negative_prompt")
        or image_info.get("has_comfy_workflow")
    )


def summarize_image_metadata_lines(latest_import: dict | None) -> dict:
    images = latest_import.get("images", []) if latest_import else []
    prompt_count = 0
    skipped_count = 0
    for image_info in images:
        if not isinstance(image_info, dict):
            skipped_count += 1
        elif should_create_image_metadata_line(image_info):
            prompt_count += 1
        else:
            skipped_count += 1
    return {
        "has_import": latest_import is not None,
        "line_count": prompt_count,
        "skipped_count": skipped_count,
    }
