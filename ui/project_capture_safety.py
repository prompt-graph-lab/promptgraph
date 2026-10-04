"""Fail-closed capture of a Streamlit session's live PromptGraph Project.

This owner returns a host-only isolated Project snapshot. It does not expose a
Project through MCP or own any persistence, history, or approval behavior.
"""

from dataclasses import dataclass
import uuid
import weakref

from streamlit import config as _streamlit_config

from core.project import Project


PROJECT_CAPTURE_RUN_TOKEN_KEY = "_promptgraph_project_capture_run_token"


@dataclass(frozen=True)
class CapturedProject:
    """Host-only Project snapshot and the run/source identities that bound it."""

    project: Project
    _run_token: str
    _source_project_ref: weakref.ReferenceType[Project]


@dataclass(frozen=True)
class ProjectCaptureResult:
    """Bounded result; only ``capture.project`` is used by host-side code."""

    capture: CapturedProject | None
    reason: str

    @property
    def ok(self) -> bool:
        return self.capture is not None


def begin_project_capture_run(session_state) -> str | None:
    """Create the opaque token for this execution of the full app script."""

    token = uuid.uuid4().hex
    try:
        session_state[PROJECT_CAPTURE_RUN_TOKEN_KEY] = token
    except Exception:
        return None
    return token


def _capture_mode_reason() -> str:
    """Return a bounded reason unless Streamlit's full runs are serialized."""
    try:
        value = _streamlit_config.get_option("runner.fastReruns")
    except Exception:
        return "capture_mode_unavailable"
    if type(value) is not bool:
        return "capture_mode_unavailable"
    return "overlapping_reruns_enabled" if value else ""


def _run_is_current(session_state, run_token: str | None) -> bool:
    if type(run_token) is not str or not run_token:
        return False
    try:
        return session_state.get(PROJECT_CAPTURE_RUN_TOKEN_KEY) == run_token
    except Exception:
        return False


def capture_active_project(session_state, run_token: str | None) -> ProjectCaptureResult:
    """Clone the active Project only when Streamlit cannot overlap full runs.

    Streamlit 1.60.0's default ``runner.fastReruns=True`` permits the previous
    ScriptRunner to continue while a new one starts. The app must be launched
    with that option disabled before this boundary can authorize a capture.
    """

    mode_reason = _capture_mode_reason()
    if mode_reason:
        return ProjectCaptureResult(None, mode_reason)
    if not _run_is_current(session_state, run_token):
        return ProjectCaptureResult(None, "run_not_current")

    try:
        source_project = session_state.get("project")
    except Exception:
        return ProjectCaptureResult(None, "capture_unavailable")
    if source_project is None:
        return ProjectCaptureResult(None, "missing_project")
    if type(source_project) is not Project:
        return ProjectCaptureResult(None, "invalid_project")

    try:
        source_ref = weakref.ref(source_project)
        snapshot = source_project.clone()
    except Exception:
        return ProjectCaptureResult(None, "capture_failed")

    if type(snapshot) is not Project or snapshot is source_project:
        return ProjectCaptureResult(None, "capture_failed")
    if _capture_mode_reason():
        return ProjectCaptureResult(None, "capture_mode_changed")
    if not _run_is_current(session_state, run_token):
        return ProjectCaptureResult(None, "run_not_current")
    try:
        still_active = session_state.get("project") is source_project
    except Exception:
        return ProjectCaptureResult(None, "capture_unavailable")
    if not still_active:
        return ProjectCaptureResult(None, "project_changed")

    return ProjectCaptureResult(
        CapturedProject(snapshot, run_token, source_ref),
        "",
    )


def is_capture_current(session_state, capture: CapturedProject | None,
                       run_token: str | None) -> bool:
    """Check that a capture still belongs to this serialized run and Project."""

    if type(capture) is not CapturedProject or _capture_mode_reason():
        return False
    if capture._run_token != run_token or not _run_is_current(session_state, run_token):
        return False
    try:
        return capture._source_project_ref() is session_state.get("project")
    except Exception:
        return False
