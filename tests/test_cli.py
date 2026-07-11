from __future__ import annotations

from pitch.cli import main


def test_verify_passes_for_source_lite_bundle() -> None:
    assert main(["verify"]) == 0


def test_doctor_runs_without_installed_components() -> None:
    assert main(["doctor"]) == 0


def test_status_handles_empty_port_configuration() -> None:
    assert main(["status"]) == 0


def test_probe_handles_empty_port_configuration() -> None:
    assert main(["probe"]) == 0
