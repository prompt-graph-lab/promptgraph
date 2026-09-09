"""Select an unused native path without reserving it."""
import os

def _unique_save_path(output_dir, file_name):
    base_name = os.path.basename(file_name or "comfy_output.png")
    candidate_path = os.path.join(output_dir, base_name)
    stem, ext = os.path.splitext(candidate_path)
    suffix = 1
    while os.path.exists(candidate_path):
        candidate_path = f"{stem}_{suffix}{ext}"
        suffix += 1
    return candidate_path
