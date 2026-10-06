import ast
from pathlib import Path

from agent_adapters import mcp_named_pipe_launcher as launcher
from ui.project_agent_named_pipe import LocalLauncherRendezvous


def test_launcher_module_has_no_project_streamlit_capture_or_approval_imports():
    tree = ast.parse(Path(launcher.__file__).read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
    forbidden = {
        "streamlit",
        "core.project",
        "core.agent_facade",
        "ui.project_capture_safety",
        "ui.project_agent_request_bridge",
    }
    assert imports.isdisjoint(forbidden)


def test_launcher_rejects_transient_arguments_without_echoing_them(capsys):
    secret_path = r"C:\Users\private\pairing-secret.json"
    assert launcher.main([secret_path]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unexpected_arguments" in captured.err
    assert secret_path not in captured.err


def test_launcher_fails_boundedly_when_no_session_is_explicitly_armed(
    monkeypatch, capsys,
):
    protected_path = r"C:\Users\private\pairing-secret.json"
    monkeypatch.setattr(
        launcher,
        "read_local_launcher_rendezvous",
        lambda: LocalLauncherRendezvous(
            "rendezvous_unavailable",
            descriptor_file_path=protected_path,
        ),
    )
    monkeypatch.setattr(
        launcher.anyio,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()),
    )

    assert launcher.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "rendezvous_unavailable" in captured.err
    assert protected_path not in captured.err


def test_launcher_does_not_echo_unrecognized_rendezvous_or_gateway_errors(
    monkeypatch, capsys,
):
    protected_path = r"C:\Users\private\pairing-secret.json"
    monkeypatch.setattr(
        launcher,
        "read_local_launcher_rendezvous",
        lambda: LocalLauncherRendezvous(
            protected_path,
            descriptor_file_path=protected_path,
        ),
    )
    assert launcher.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "rendezvous_unavailable" in captured.err
    assert protected_path not in captured.err

    monkeypatch.setattr(
        launcher,
        "read_local_launcher_rendezvous",
        lambda: LocalLauncherRendezvous(
            "ready",
            descriptor_file_path=protected_path,
        ),
    )

    def raise_secret(*_args, **_kwargs):
        raise launcher.NamedPipeGatewayStartupError(protected_path)

    monkeypatch.setattr(launcher.anyio, "run", raise_secret)
    assert launcher.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "gateway_failed" in captured.err
    assert protected_path not in captured.err


def test_launcher_bounds_unexpected_rendezvous_failures(monkeypatch, capsys):
    protected_path = r"C:\Users\private\pairing-secret.json"

    def fail_resolution():
        raise RuntimeError(protected_path)

    monkeypatch.setattr(
        launcher,
        "read_local_launcher_rendezvous",
        fail_resolution,
    )
    assert launcher.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "rendezvous_unavailable" in captured.err
    assert protected_path not in captured.err


def test_launcher_passes_only_resolved_descriptor_to_existing_gateway(
    monkeypatch, capsys,
):
    protected_path = r"C:\Users\private\pairing-secret.json"
    rendezvous = LocalLauncherRendezvous(
        "ready",
        descriptor_file_path=protected_path,
        server_pid=77,
        process_incarnation="opaque-incarnation",
    )
    monkeypatch.setattr(
        launcher,
        "read_local_launcher_rendezvous",
        lambda: rendezvous,
    )
    calls = []
    monkeypatch.setattr(
        launcher.anyio,
        "run",
        lambda function, *args, **kwargs: calls.append((function, args, kwargs)),
    )

    assert launcher.main([]) == 0
    assert calls == [
        (launcher.serve_stdio_over_named_pipe, (protected_path,), {}),
    ]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

