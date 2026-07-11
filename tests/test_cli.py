from __future__ import annotations

from pathlib import Path

import pitch.cli as pitch_cli
from pitch.cli import main
from pitch_bootstrap import ensure_installer_drop_root, resolve_installer_drop_root, resolve_user_data_root


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


def test_assets_init_creates_the_drop_root(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PITCH_INSTALLER_DROP_ROOT", str(tmp_path / "installers"))
    assert ensure_installer_drop_root().exists()
    assert main(["assets", "init"]) == 0
    assert (tmp_path / "installers").exists()


def test_assets_show_reports_the_drop_root(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("PITCH_INSTALLER_DROP_ROOT", str(tmp_path / "installers"))
    assert main(["assets", "show"]) == 0
    captured = capsys.readouterr()
    assert "Installer drop root:" in captured.out


def test_assets_init_reports_permission_failures(monkeypatch, capsys) -> None:
    def _raise_permission_error() -> Path:
        raise PermissionError("blocked")

    monkeypatch.setattr(pitch_cli, "ensure_installer_drop_root", _raise_permission_error)

    assert main(["assets", "init"]) == 1
    captured = capsys.readouterr()
    assert "Could not create installer drop root:" in captured.err


def test_assets_import_stages_recognized_files(monkeypatch, tmp_path) -> None:
    source_root = tmp_path / "downloads"
    nested_root = source_root / "pitch" / "bundle"
    nested_root.mkdir(parents=True)
    (nested_root / "release_notes.txt").write_text("notes", encoding="utf-8")
    (nested_root / "prti_users_guide.pdf").write_text("guide", encoding="utf-8")
    (nested_root / "prti1516e-free_5_5_10_windows64.exe").write_text("exe", encoding="utf-8")
    monkeypatch.setenv("PITCH_INSTALLER_DROP_ROOT", str(tmp_path / "staged"))

    assert main(["assets", "import", str(source_root)]) == 0
    staged_root = tmp_path / "staged"
    assert (staged_root / "release_notes.txt").exists()
    assert (staged_root / "prti_users_guide.pdf").exists()
    assert (staged_root / "prti1516e-free_5_5_10_windows64.exe").exists()


def test_setup_can_stage_from_a_source_folder(monkeypatch, tmp_path, capsys) -> None:
    source_root = tmp_path / "pitch-download"
    nested_root = source_root / "bundle"
    nested_root.mkdir(parents=True)
    (nested_root / "HlaStarterKit_v1.0.2_windows64.exe").write_text("hla", encoding="utf-8")
    (nested_root / "PitchVisualOMTFree_v2.7.0_windows64.exe").write_text("vomt", encoding="utf-8")
    monkeypatch.setenv("PITCH_INSTALLER_DROP_ROOT", str(tmp_path / "staged"))
    monkeypatch.setattr(pitch_cli, "run_installer", lambda *args, **kwargs: None)
    monkeypatch.setattr(pitch_cli, "_mark_component_installed", lambda *args, **kwargs: None)
    monkeypatch.setattr(pitch_cli, "_installed_components", lambda: set())

    assert main(["setup", "--source", str(source_root)]) == 0
    captured = capsys.readouterr()
    assert "Staged setup assets from" in captured.out
    assert "Staged 2 file(s)" in captured.out
    assert "Pitch setup finished." in captured.out


def test_download_submit_dry_run_uses_download_contact(monkeypatch, capsys) -> None:
    monkeypatch.setenv("PITCH_INSTALLER_DROP_ROOT", r"C:\tmp\pitch-installers")
    assert main(["download", "submit", "--email", "you@example.com", "--dry-run"]) == 0
    captured = capsys.readouterr()
    assert '"email": "you@example.com"' in captured.out
    assert '"download": "prti"' in captured.out


def test_download_submit_posts_request(monkeypatch) -> None:
    captured_request = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"Done."

    def _fake_urlopen(request, timeout=0):
        captured_request["url"] = request.full_url
        captured_request["body"] = request.data.decode("utf-8")
        captured_request["timeout"] = timeout
        captured_request["headers"] = dict(request.header_items())
        return _Response()

    monkeypatch.setattr(pitch_cli.urllib.request, "urlopen", _fake_urlopen)

    assert main(["download", "submit", "--email", "you@example.com"]) == 0
    assert captured_request["url"].endswith("/mailformfree.asp")
    assert "email=you%40example.com" in captured_request["body"]
    assert captured_request["timeout"] == 30
    assert "Mozilla/5.0" in captured_request["headers"]["User-agent"]
    assert captured_request["headers"]["Referer"].endswith("/free/download.asp")


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
