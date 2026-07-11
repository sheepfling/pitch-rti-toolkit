from __future__ import annotations

from pathlib import Path

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
