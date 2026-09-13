"""Prepare manual JSON Open input before the app publishes a Project."""

from typing import Callable, ContextManager

from core.graph_builder import build_graph
from core.io import load_project_from_json
from core.project import Project


def prepare_project_json_open(
    project_path: str,
    *,
    complete_routes: Callable[[Project], bool],
    profile_block: Callable[[str], ContextManager],
) -> Project:
    """Load, complete routes in place, then build the graph without publication.

    The app supplies its existing route completion and timing context;
    neither the completion result nor exceptions are translated here.
    """
    with profile_block("Project load: read JSON"):
        project = load_project_from_json(project_path)
    complete_routes(project)
    with profile_block("Project load: build graph"):
        project = build_graph(project)
    return project
