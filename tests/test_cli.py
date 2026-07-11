from __future__ import annotations

from pathlib import Path

import pitch.cli as pitch_cli
from pitch.cli import main
from pitch_bootstrap import resolve_installer_drop_root, resolve_user_data_root


def test_verify_passes_for_source_lite_bundle() -> None:
    assert main(["verify"]) == 0


def test_doctor_runs_without_installed_components() -> None:
    assert main(["doctor"]) == 0


def test_status_handles_empty_port_configuration() -> None:
    assert main(["status"]) == 0


def test_probe_handles_empty_port_configuration() -> None:
    assert main(["probe"]) == 0


def test_config_assets_reports_writable_locations() -> None:
    assert main(["config", "assets"]) == 0


def test_user_data_root_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("PITCH_USER_DATA_ROOT", r"C:\tmp\pitch-user-data")
    assert resolve_user_data_root() == Path(r"C:\tmp\pitch-user-data")
    assert resolve_installer_drop_root() == Path(r"C:\tmp\pitch-user-data\installers")


def test_installer_drop_root_can_be_overridden_directly(monkeypatch) -> None:
    monkeypatch.setenv("PITCH_INSTALLER_DROP_ROOT", r"C:\tmp\pitch-installers")
    assert resolve_installer_drop_root() == Path(r"C:\tmp\pitch-installers")


def test_setup_reports_the_installer_drop_root(capsys) -> None:
    assert main(["setup"]) == 1
    captured = capsys.readouterr()
    assert "Installer drop root:" in captured.out


def test_start_root_uses_fallback_when_startfile_is_blocked(monkeypatch) -> None:
    def _raise_permission_error(_path: str) -> None:
        raise PermissionError("blocked")

    launched: list[tuple[list[str], dict[str, object]]] = []

    class _DummyProcess:
        pass

    def _fake_popen(cmd, **kwargs):
        launched.append((cmd, kwargs))
        return _DummyProcess()

    monkeypatch.setattr(pitch_cli.os, "startfile", _raise_permission_error)
    monkeypatch.setattr(pitch_cli.subprocess, "Popen", _fake_popen)

    assert main(["start", "root"]) == 0
    assert launched
    assert launched[0][0][0] == "explorer.exe"
