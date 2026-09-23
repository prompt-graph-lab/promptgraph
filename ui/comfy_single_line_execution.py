"""Progress presentation and output collection for a single ComfyUI submission."""

import streamlit as st


def collect_single_line_comfy_outputs(status_source, output_dir, status_output_paths):
    """Consume status events after creating the existing progress widgets.

    ``status_source`` is called after the widgets exist, matching the caller's
    previous submission order. Path resolution stays with the app because it
    depends on the current Project asset context.
    """
    progress_bar = st.progress(0.0)
    status_text = st.empty()
    generated_paths = []
    for status in status_source():
        if "value" in status:
            progress_bar.progress(status["value"])
        if "text" in status:
            status_text.markdown(f"**Status:** {status['text']}")
        if status.get("type") == "done":
            generated_paths.extend(status_output_paths(status, output_dir=output_dir))
    return generated_paths
