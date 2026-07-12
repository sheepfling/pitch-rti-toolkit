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


def test_setup_falls_back_to_legacy_rti_when_core_installers_are_missing(monkeypatch, tmp_path, capsys) -> None:
    source_root = tmp_path / "pitch-download"
    nested_root = source_root / "bundle"
    nested_root.mkdir(parents=True)
    (nested_root / "prti1516e-free_5_5_10_windows32.exe").write_text("legacy", encoding="utf-8")
    monkeypatch.setenv("PITCH_INSTALLER_DROP_ROOT", str(tmp_path / "staged"))

    installed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        pitch_cli,
        "run_installer",
        lambda installer_path, cwd=None, quiet=False: installed.append((installer_path.name, str(cwd))),
    )
    monkeypatch.setattr(pitch_cli, "_mark_component_installed", lambda *args, **kwargs: None)
    monkeypatch.setattr(pitch_cli, "_installed_components", lambda: set())

    assert main(["setup", "--source", str(source_root)]) == 0
    captured = capsys.readouterr()
    assert "falling back to the legacy pRTI package" in captured.out
    assert installed == [("prti1516e-free_5_5_10_windows32.exe", str(pitch_cli.ROOT))]
    assert "Pitch setup finished." in captured.out


def test_setup_passes_silent_mode_to_the_installer(monkeypatch, tmp_path, capsys) -> None:
    source_root = tmp_path / "pitch-download"
    nested_root = source_root / "bundle"
    nested_root.mkdir(parents=True)
    (nested_root / "prti1516e-free_5_5_10_windows32.exe").write_text("legacy", encoding="utf-8")
    monkeypatch.setenv("PITCH_INSTALLER_DROP_ROOT", str(tmp_path / "staged"))

    calls: list[tuple[str, bool]] = []

    def _fake_run_installer(installer_path, cwd=None, quiet=False):
        calls.append((installer_path.name, quiet))

    monkeypatch.setattr(pitch_cli, "run_installer", _fake_run_installer)
    monkeypatch.setattr(pitch_cli, "_mark_component_installed", lambda *args, **kwargs: None)
    monkeypatch.setattr(pitch_cli, "_installed_components", lambda: set())

    assert main(["setup", "--source", str(source_root), "--silent-install"]) == 0
    captured = capsys.readouterr()
    assert "Silent install mode enabled" in captured.out
    assert calls == [("prti1516e-free_5_5_10_windows32.exe", True)]
    assert "Pitch setup finished." in captured.out


def test_setup_uses_linux_installers_when_running_on_linux(monkeypatch, tmp_path, capsys) -> None:
    source_root = tmp_path / "pitch-download"
    nested_root = source_root / "bundle"
    nested_root.mkdir(parents=True)
    (nested_root / "HlaStarterKit_v1.0.2_linux64.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (nested_root / "PitchVisualOMTFree_v2.7.0_linux64.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("PITCH_INSTALLER_DROP_ROOT", str(tmp_path / "staged"))
    monkeypatch.setattr(pitch_cli.platform, "system", lambda: "Linux")

    calls: list[tuple[str, bool]] = []

    def _fake_run_installer(installer_path, cwd=None, quiet=False):
        calls.append((installer_path.name, quiet))

    monkeypatch.setattr(pitch_cli, "run_installer", _fake_run_installer)
    monkeypatch.setattr(pitch_cli, "_mark_component_installed", lambda *args, **kwargs: None)
    monkeypatch.setattr(pitch_cli, "_installed_components", lambda: set())

    assert main(["setup", "--source", str(source_root), "--silent-install"]) == 0
    captured = capsys.readouterr()
    assert "Silent install mode enabled" in captured.out
    assert calls == [
        ("HlaStarterKit_v1.0.2_linux64.sh", True),
        ("PitchVisualOMTFree_v2.7.0_linux64.sh", True),
    ]
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
    assert captured_request["headers"]["Referer"].endswith("/install.asp")


def test_download_fetch_downloads_to_output_path(monkeypatch, tmp_path, capsys) -> None:
    captured_request = {}

    class _Response:
        url = "https://example.com/files/pitch.bin"

        def __init__(self):
            self._consumed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size=-1):
            if self._consumed:
                return b""
            self._consumed = True
            return b"pitch-bytes"

        def readable(self):
            return True

        def close(self):
            return None

    def _fake_urlopen(request, timeout=0):
        captured_request["url"] = request.full_url
        captured_request["timeout"] = timeout
        captured_request["headers"] = dict(request.header_items())
        return _Response()

    monkeypatch.setattr(pitch_cli.urllib.request, "urlopen", _fake_urlopen)

    output_path = tmp_path / "downloads" / "pitch.bin"
    assert main(["download", "fetch", "--url", "https://example.com/files/pitch.bin", "--output", str(output_path)]) == 0
    captured = capsys.readouterr()
    assert captured_request["url"] == "https://example.com/files/pitch.bin"
    assert captured_request["timeout"] == 30
    assert output_path.read_bytes() == b"pitch-bytes"
    assert f"Downloaded https://example.com/files/pitch.bin to {output_path}" in captured.out


def test_download_fetch_resolves_filename_from_page(monkeypatch, tmp_path, capsys) -> None:
    captured_request = {}

    class _HtmlResponse:
        def __init__(self, payload: bytes):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size=-1):
            return self._payload

    class _BinaryResponse:
        url = "https://example.com/installers/Windows%20(x64)/pitch.exe"

        def __init__(self, payload: bytes):
            self._payload = payload
            self._consumed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size=-1):
            if self._consumed:
                return b""
            self._consumed = True
            return self._payload

    def _fake_urlopen(request, timeout=0):
        captured_request.setdefault("urls", []).append(request.full_url)
        if request.full_url.endswith("install.asp"):
            html = b"""<html><body><a href='installers/Windows (x64)/prti1516e-free_5_5_10_windows64.exe'>Windows</a><a href='installers/Linux (x64)/prti1516e-free_5_5_10_linux64.sh'>Linux</a></body></html>"""
            return _HtmlResponse(html)
        if request.full_url.endswith("prti1516e-free_5_5_10_windows64.exe"):
            return _BinaryResponse(b"binary-bytes")
        raise AssertionError(f"Unexpected URL: {request.full_url}")

    monkeypatch.setattr(pitch_cli.urllib.request, "urlopen", _fake_urlopen)

    output_path = tmp_path / "downloads" / "windows64.exe"
    assert main([
        "download",
        "fetch",
        "--url",
        "https://www2.pitch.se/pRTI1516e/Releases/v5.5.10-free/SnvHLyNhR6A9ZgoQ/install.asp",
        "--filename",
        "prti1516e-free_5_5_10_windows64.exe",
        "--output",
        str(output_path),
    ]) == 0
    captured = capsys.readouterr()
    assert captured_request["urls"] == [
        "https://www2.pitch.se/pRTI1516e/Releases/v5.5.10-free/SnvHLyNhR6A9ZgoQ/install.asp",
        "https://www2.pitch.se/pRTI1516e/Releases/v5.5.10-free/SnvHLyNhR6A9ZgoQ/installers/Windows (x64)/prti1516e-free_5_5_10_windows64.exe",
    ]
    assert output_path.read_bytes() == b"binary-bytes"
    assert "Downloaded https://www2.pitch.se/pRTI1516e/Releases/v5.5.10-free/SnvHLyNhR6A9ZgoQ/install.asp to" in captured.out


def test_download_fetch_resolves_by_platform_from_page(monkeypatch, tmp_path, capsys) -> None:
    captured_request = {}

    class _HtmlResponse:
        def __init__(self, payload: bytes):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size=-1):
            return self._payload

    class _BinaryResponse:
        url = "https://example.com/installers/Linux%20(x64)/pitch.sh"

        def __init__(self, payload: bytes):
            self._payload = payload
            self._consumed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size=-1):
            if self._consumed:
                return b""
            self._consumed = True
            return self._payload

    def _fake_urlopen(request, timeout=0):
        captured_request.setdefault("urls", []).append(request.full_url)
        if request.full_url.endswith("install.asp"):
            html = b"""<html><body><a href='installers/Windows (x64)/prti1516e-free_5_5_10_windows64.exe'>Windows</a><a href='installers/Linux (x64)/prti1516e-free_5_5_10_linux64.sh'>Linux</a></body></html>"""
            return _HtmlResponse(html)
        if request.full_url.endswith("prti1516e-free_5_5_10_linux64.sh"):
            return _BinaryResponse(b"linux-bytes")
        raise AssertionError(f"Unexpected URL: {request.full_url}")

    monkeypatch.setattr(pitch_cli.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(pitch_cli.platform, "system", lambda: "Linux")
    monkeypatch.setattr(pitch_cli.platform, "machine", lambda: "x86_64")

    output_path = tmp_path / "downloads" / "linux64.sh"
    assert main([
        "download",
        "fetch",
        "--url",
        "https://www2.pitch.se/pRTI1516e/Releases/v5.5.10-free/SnvHLyNhR6A9ZgoQ/install.asp",
        "--platform",
        "auto",
        "--output",
        str(output_path),
    ]) == 0
    captured = capsys.readouterr()
    assert captured_request["urls"] == [
        "https://www2.pitch.se/pRTI1516e/Releases/v5.5.10-free/SnvHLyNhR6A9ZgoQ/install.asp",
        "https://www2.pitch.se/pRTI1516e/Releases/v5.5.10-free/SnvHLyNhR6A9ZgoQ/installers/Linux (x64)/prti1516e-free_5_5_10_linux64.sh",
    ]
    assert output_path.read_bytes() == b"linux-bytes"
    assert "Downloaded https://www2.pitch.se/pRTI1516e/Releases/v5.5.10-free/SnvHLyNhR6A9ZgoQ/install.asp to" in captured.out


def test_setup_reports_the_installer_drop_root(monkeypatch, tmp_path, capsys) -> None:
    empty_search_root = tmp_path / "empty"
    empty_search_root.mkdir()
    monkeypatch.setattr(pitch_cli, "_installer_search_roots", lambda: [empty_search_root])

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
