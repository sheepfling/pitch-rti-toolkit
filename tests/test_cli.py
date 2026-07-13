from __future__ import annotations

import argparse
from pathlib import Path

import pitch.cli as pitch_cli
import pitch.execution as pitch_execution
import pitch.docker_vendor as pitch_docker_vendor
import pitch.common as pitch_common
import pitch.ports as pitch_ports
import pitch.routes as pitch_routes
import pitch.settings as pitch_settings
import pitch_bootstrap
from pitch.cli import main
from pitch_bootstrap import ensure_installer_drop_root, resolve_installer_drop_root, resolve_user_data_root, sha256_file


def test_verify_passes_for_source_lite_bundle() -> None:
    assert main(["verify"]) == 0


def test_verify_can_include_the_rti_smoke_test(monkeypatch, capsys) -> None:
    monkeypatch.setattr(pitch_cli, "_discover_installed_runtime_launcher", lambda component_key: Path(r"C:\Program Files\prti1516e\bin\pRTI1516e-nogui.bat") if component_key == "prti1516e" else None)
    monkeypatch.setattr(pitch_cli, "_run_rti_smoke_test", lambda: 0)

    assert main(["verify", "--rti-smoke"]) == 0
    captured = capsys.readouterr()
    assert "Verification passed." in captured.out


def test_verify_skips_the_rti_smoke_test_when_not_installed(monkeypatch, capsys) -> None:
    monkeypatch.setattr(pitch_cli, "_discover_installed_runtime_launcher", lambda component_key: None)
    monkeypatch.setattr(pitch_cli, "_run_rti_smoke_test", lambda: 1)

    assert main(["verify", "--rti-smoke"]) == 0
    captured = capsys.readouterr()
    assert "Skipping RTI smoke test" in captured.out
    assert "Verification passed." in captured.out


def test_doctor_runs_without_installed_components(capsys) -> None:
    assert main(["doctor"]) == 0
    captured = capsys.readouterr()
    assert "Route options:" in captured.out
    assert "recommended:" in captured.out


def test_status_handles_empty_port_configuration(capsys) -> None:
    assert main(["status"]) == 0
    captured = capsys.readouterr()
    assert "Route options:" in captured.out
    assert "recommended:" in captured.out
    assert "Preflight:" in captured.out


def test_preflight_writes_a_json_artifact(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("PITCH_PREFLIGHT_ARTIFACT_ROOT", str(tmp_path / "preflight"))
    monkeypatch.setattr(pitch_cli, "_docker_preflight_status", lambda: ("ok", "Docker daemon is reachable.", True))
    monkeypatch.setattr(pitch_cli, "_verify_paths", lambda: [])
    monkeypatch.setattr(pitch_cli, "_discover_installed_runtime_launcher", lambda component_key: Path(r"C:\Program Files\prti1516e\bin\pRTI1516e-nogui.bat") if component_key == "prti1516e" else None)
    monkeypatch.setattr(
        pitch_cli,
        "_load_state",
        lambda: {
            "checks": {
                "rti_smoke": {
                    "status": "passed",
                    "timestamp": "2026-07-12T12:34:56+00:00",
                    "detail": r"C:\\Program Files\\prti1516e\\bin\\pRTI1516e-nogui.bat",
                }
            }
        },
    )

    assert main(["preflight", "--json"]) == 0
    captured = capsys.readouterr()
    assert '"tool": "pitch-preflight"' in captured.out
    assert '"environment": "ready"' in captured.out
    artifact = tmp_path / "preflight" / "pitch-preflight.json"
    assert artifact.exists()


def test_status_reports_rti_smoke_availability_and_last_pass(monkeypatch, capsys) -> None:
    monkeypatch.setattr(pitch_cli, "_load_state", lambda: {
        "components": {"prti1516e": {"status": "installed"}},
        "checks": {
            "rti_smoke": {
                "status": "passed",
                "timestamp": "2026-07-12T12:34:56+00:00",
                "detail": r"C:\\Program Files\\prti1516e\\bin\\pRTI1516e-nogui.bat",
            }
        },
    })
    monkeypatch.setattr(pitch_cli, "_installed_components", lambda: {"prti1516e"})
    monkeypatch.setattr(
        pitch_cli,
        "_discover_installed_runtime_launcher",
        lambda component_key: Path(r"C:\Program Files\prti1516e\bin\pRTI1516e-nogui.bat") if component_key == "prti1516e" else None,
    )

    assert main(["status"]) == 0
    captured = capsys.readouterr()
    assert "RTI smoke test:" in captured.out
    assert "available" in captured.out
    assert "last passed: 2026-07-12T12:34:56+00:00" in captured.out
    assert r"C:\Program Files\prti1516e\bin\pRTI1516e-nogui.bat" in captured.out


def test_probe_handles_empty_port_configuration() -> None:
    assert main(["probe"]) == 0


def test_config_assets_reports_writable_locations() -> None:
    assert main(["config", "assets"]) == 0


def test_user_data_root_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("PITCH_USER_DATA_ROOT", r"C:\tmp\pitch-user-data")
    assert resolve_user_data_root() == Path(r"C:\tmp\pitch-user-data")
    assert resolve_installer_drop_root() == Path(r"C:\tmp\pitch-user-data") / "installers"


def test_bootstrap_uses_the_shared_platform_abstraction(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(pitch_bootstrap, "is_windows_platform", lambda: True)
    monkeypatch.setattr(pitch_bootstrap, "is_macos_platform", lambda: False)
    assert pitch_bootstrap.resolve_user_data_root("PitchApp") == Path.home() / "AppData" / "Local" / "PitchApp"

    monkeypatch.setattr(pitch_bootstrap, "is_windows_platform", lambda: False)
    monkeypatch.setattr(pitch_bootstrap, "is_macos_platform", lambda: True)
    assert pitch_bootstrap.resolve_user_data_root("PitchApp") == Path.home() / "Library" / "Application Support" / "PitchApp"

    config_path = tmp_path / ".pitch-install-roots.json"
    config_path.write_text(
        '{"windows": {"prti1516e": "C:/Pitch/prti"}, "linux": {"prti1516e": "/opt/pitch"}, "darwin": {"prti1516e": "/Applications/Pitch"}}',
        encoding="utf-8",
    )

    monkeypatch.setattr(pitch_bootstrap, "is_windows_platform", lambda: False)
    monkeypatch.setattr(pitch_bootstrap, "is_macos_platform", lambda: False)
    assert pitch_bootstrap.load_install_roots(config_path)["prti1516e"] == Path("/opt/pitch")

    monkeypatch.setattr(pitch_bootstrap, "is_windows_platform", lambda: True)
    monkeypatch.setattr(pitch_bootstrap, "is_macos_platform", lambda: False)
    assert pitch_bootstrap.load_install_roots(config_path)["prti1516e"] == Path("C:/Pitch/prti")


def test_artifact_root_prefers_the_checkout_artifacts_directory(monkeypatch) -> None:
    monkeypatch.delenv("PITCH_ARTIFACT_ROOT", raising=False)
    assert pitch_bootstrap.resolve_artifact_root(pitch_bootstrap.ROOT) == pitch_bootstrap.ROOT / "artifacts"
    assert pitch_bootstrap.install_state_path(pitch_bootstrap.ROOT) == pitch_bootstrap.ROOT / "artifacts" / ".pitch-install-state.json"
    assert pitch_bootstrap.install_roots_path(pitch_bootstrap.ROOT) == pitch_bootstrap.ROOT / "artifacts" / ".pitch-install-roots.json"


def test_route_port_profiles_are_stable_and_distinct(monkeypatch) -> None:
    monkeypatch.delenv("PITCH_PORT_SLOT", raising=False)
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)

    native_port = pitch_ports.route_rti_port("route-native")
    wsl_port = pitch_ports.route_rti_port("route-wsl")
    docker_port = pitch_ports.route_rti_port("route-docker")
    vendor_port = pitch_ports.route_rti_port("vendor-docker")

    assert len({native_port, wsl_port, docker_port, vendor_port}) == 4
    assert pitch_ports.route_rti_port("route-native") == native_port
    assert pitch_ports.route_webview_port("vendor-docker") == pitch_ports.route_webview_port("vendor-docker")

    monkeypatch.setenv("PITCH_ARTIFACT_ROOT", r"C:\tmp\pitch-artifacts")
    assert pitch_bootstrap.resolve_artifact_root(pitch_bootstrap.ROOT) == Path(r"C:\tmp\pitch-artifacts")


def test_route_surface_for_context_maps_context_to_port_profile(monkeypatch) -> None:
    monkeypatch.delenv("PITCH_ROUTE_CONTEXT", raising=False)
    assert pitch_ports.route_surface_for_context() == "route-native"

    monkeypatch.setenv("PITCH_ROUTE_CONTEXT", "wsl")
    assert pitch_ports.route_surface_for_context() == "route-wsl"

    monkeypatch.setenv("PITCH_ROUTE_CONTEXT", "docker")
    assert pitch_ports.route_surface_for_context() == "route-docker"


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
    manifest = staged_root / "checksums.sha256"
    assert manifest.exists()
    assert "prti1516e-free_5_5_10_windows64.exe" in manifest.read_text(encoding="utf-8")


def test_assets_verify_checks_the_staged_download_manifest(monkeypatch, tmp_path, capsys) -> None:
    staged_root = tmp_path / "staged"
    staged_root.mkdir()
    installer = staged_root / "prti1516e-free_5_5_10_windows64.exe"
    installer.write_text("exe-bytes", encoding="utf-8")
    manifest = staged_root / "checksums.sha256"
    manifest.write_text(f"{sha256_file(installer)}  {installer.name}\n", encoding="utf-8")
    monkeypatch.setenv("PITCH_INSTALLER_DROP_ROOT", str(staged_root))

    assert main(["assets", "verify"]) == 0
    captured = capsys.readouterr()
    assert "Downloaded artifacts verification passed." in captured.out


def test_assets_verify_reports_checksum_mismatches(monkeypatch, tmp_path, capsys) -> None:
    staged_root = tmp_path / "staged"
    staged_root.mkdir()
    installer = staged_root / "prti1516e-free_5_5_10_windows64.exe"
    installer.write_text("exe-bytes", encoding="utf-8")
    manifest = staged_root / "checksums.sha256"
    manifest.write_text(f"{'0' * 64}  {installer.name}\n", encoding="utf-8")
    monkeypatch.setenv("PITCH_INSTALLER_DROP_ROOT", str(staged_root))

    assert main(["assets", "verify"]) == 1
    captured = capsys.readouterr()
    assert "Checksum mismatch:" in captured.err


def test_assets_import_skips_identical_files(monkeypatch, tmp_path, capsys) -> None:
    source_root = tmp_path / "downloads"
    source_root.mkdir()
    staged_root = tmp_path / "staged"
    staged_root.mkdir()
    staged_file = staged_root / "release_notes.txt"
    staged_file.write_text("same bytes", encoding="utf-8")
    (source_root / "release_notes.txt").write_text("same bytes", encoding="utf-8")
    monkeypatch.setenv("PITCH_INSTALLER_DROP_ROOT", str(staged_root))

    assert main(["assets", "import", str(source_root)]) == 0
    captured = capsys.readouterr()
    assert "Already staged:" in captured.out
    assert "release_notes.txt" in captured.out


def test_run_installer_uses_plain_quiet_flag(monkeypatch, tmp_path) -> None:
    installer = tmp_path / "installer.exe"
    installer.write_text("stub", encoding="utf-8")

    captured = {}

    def _fake_run(command, cwd=None, check=False):
        captured["command"] = command
        captured["cwd"] = cwd

    monkeypatch.setattr(pitch_bootstrap.subprocess, "run", _fake_run)

    pitch_bootstrap.run_installer(installer, cwd=tmp_path, quiet=True)

    assert captured["command"] == [str(installer), "-q"]
    assert captured["cwd"] == str(tmp_path)


def test_rti_smoke_uses_the_startup_helper_and_cleans_up(monkeypatch, capsys) -> None:
    captured = {}

    class _Process:
        def __init__(self):
            self.returncode = 0
            self.killed = False

        def poll(self):
            return None

        def kill(self):
            self.killed = True

    process = _Process()

    def _fake_start_prti_crc():
        captured["called"] = True
        return process, "127.0.0.1:18089"

    def _fake_mark_rti_smoke_result(passed, detail):
        captured["result"] = (passed, detail)

    monkeypatch.setattr(pitch_cli, "_start_prti_crc", _fake_start_prti_crc)
    monkeypatch.setattr(pitch_cli, "_mark_rti_smoke_result", _fake_mark_rti_smoke_result)

    assert main(["rti", "smoke"]) == 0
    captured_out = capsys.readouterr()
    assert "Pitch RTI smoke test passed." in captured_out.out
    assert captured["called"] is True
    assert captured["result"] == (True, "127.0.0.1:18089")
    assert process.killed is True


def test_rti_smoke_chat_lists_discovered_variants(monkeypatch, capsys, tmp_path) -> None:
    launcher = tmp_path / "chat-java-hla4" / "chat-java-hla4.bat"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("@echo off\n", encoding="utf-8")

    monkeypatch.setattr(pitch_cli, "_discover_chat_sample_launcher", lambda variant=None: (variant or "java-hla4", launcher) if variant in {"java-hla4", "java-hla4-fedpro"} else None)

    assert main(["rti", "smoke", "chat", "--list"]) == 0
    captured = capsys.readouterr()
    assert "Available chat sample variants:" in captured.out
    assert "java-hla4:" in captured.out


def test_rti_smoke_chat_runs_two_federates(monkeypatch, capsys, tmp_path) -> None:
    launcher = tmp_path / "chat-java-hla4" / "chat-java-hla4.bat"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("@echo off\n", encoding="utf-8")

    monkeypatch.setattr(
        pitch_cli,
        "_discover_chat_sample_launcher",
        lambda variant=None: ("java-hla4", launcher) if variant in {None, "auto", "java-hla4", "java-hla4-fedpro", "cpp-hla4"} else None,
    )
    monkeypatch.setattr(pitch_routes, "is_windows_platform", lambda: False)

    launched = []

    class _Process:
        def __init__(self, command, cwd=None, stdin=None, stdout=None, stderr=None, text=None):
            self.command = command
            self.cwd = cwd
            self.returncode = 0
            self._input = ""
            self.pid = 4242
            self.pid = 4242
            self.pid = 4242
            self.pid = 4242

        def communicate(self, input=None, timeout=None):
            self._input = input or ""
            return (
                "Type messages you want to send.\n> \n",
                "",
            )

        def poll(self):
            return None

        def kill(self):
            return None

    monkeypatch.setattr(pitch_cli, "_start_prti_crc", lambda: (_Process(["pitch-rti"], cwd=tmp_path), "127.0.0.1:18089"))

    def _fake_popen(command, cwd=None, stdin=None, stdout=None, stderr=None, text=None, env=None, creationflags=None):
        proc = _Process(command, cwd=cwd, stdin=stdin, stdout=stdout, stderr=stderr, text=text)
        launched.append(proc)
        return proc

    monkeypatch.setattr(pitch_routes.subprocess, "Popen", _fake_popen)

    assert main(["rti", "smoke", "chat"]) == 0
    captured = capsys.readouterr()
    assert "Chat smoke variant: java-hla4" in captured.out
    assert "Pitch chat smoke test passed." in captured.out
    assert len(launched) == 2
    assert launched[0].command[0] in {"cmd.exe", str(launcher), str(launcher.parent.parent.parent / "jre" / "bin" / "java.exe")}
    assert "pitch-smoke-alpha" in launched[0]._input
    assert "pitch-smoke-bravo" in launched[1]._input


def test_prove_runs_the_installed_rti_smoke_and_chat_smoke(monkeypatch, capsys, tmp_path) -> None:
    launcher = tmp_path / "chat-java-hla4" / "chat-java-hla4.bat"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("@echo off\n", encoding="utf-8")

    calls = []

    monkeypatch.setattr(pitch_cli, "_run_rti_smoke_test", lambda: calls.append("rti") or 0)
    monkeypatch.setattr(pitch_cli, "_discover_chat_sample_launcher", lambda variant=None: ("java-hla4", launcher))
    monkeypatch.setattr(pitch_routes, "is_windows_platform", lambda: False)

    class _Process:
        def __init__(self, command, cwd=None, stdin=None, stdout=None, stderr=None, text=None):
            self.command = command
            self.cwd = cwd
            self.returncode = 0
            self._input = ""
            self.pid = 4242

        def communicate(self, input=None, timeout=None):
            self._input = input or ""
            return (
                "Type messages you want to send.\n> \n",
                "",
            )

        def poll(self):
            return None

        def kill(self):
            return None

    monkeypatch.setattr(pitch_cli, "_start_prti_crc", lambda: (_Process(["pitch-rti"], cwd=tmp_path), "127.0.0.1:18089"))

    def _fake_popen(command, cwd=None, stdin=None, stdout=None, stderr=None, text=None, env=None, creationflags=None):
        calls.append("chat")
        return _Process(command, cwd=cwd, stdin=stdin, stdout=stdout, stderr=stderr, text=text)

    monkeypatch.setattr(pitch_routes.subprocess, "Popen", _fake_popen)

    assert main(["prove"]) == 0
    captured = capsys.readouterr()
    assert "Pitch proof passed." in captured.out
    assert calls[0] == "rti"
    assert calls.count("chat") == 2


def test_prove_list_only_lists_available_chat_variants(monkeypatch, capsys, tmp_path) -> None:
    launcher = tmp_path / "chat-java-hla4" / "chat-java-hla4.bat"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("@echo off\n", encoding="utf-8")

    called = {}

    monkeypatch.setattr(pitch_cli, "_run_rti_smoke_test", lambda: called.setdefault("rti", True) or 0)
    monkeypatch.setattr(pitch_cli, "_discover_chat_sample_launcher", lambda variant=None: ("java-hla4", launcher))

    assert main(["prove", "--list"]) == 0
    captured = capsys.readouterr()
    assert "Available chat sample variants:" in captured.out
    assert "java-hla4:" in captured.out
    assert "rti" not in called


def test_chat_smoke_defaults_to_local_host_first(monkeypatch) -> None:
    monkeypatch.delenv("PITCH_RTI_SMOKE_HOST", raising=False)
    monkeypatch.delenv("PITCH_ROUTE_CONTEXT", raising=False)
    candidates = pitch_cli._chat_smoke_host_candidates()
    default_port = pitch_ports.route_rti_port("route-native")

    assert candidates[0] == f"127.0.0.1:{default_port}"
    assert candidates[1] == f"localhost:{default_port}"


def test_chat_smoke_defaults_follow_the_active_route_context(monkeypatch) -> None:
    monkeypatch.delenv("PITCH_RTI_SMOKE_HOST", raising=False)
    monkeypatch.setenv("PITCH_ROUTE_CONTEXT", "wsl")
    candidates = pitch_cli._chat_smoke_host_candidates()
    default_port = pitch_ports.route_rti_port("route-wsl")

    assert candidates[0] == f"127.0.0.1:{default_port}"
    assert candidates[1] == f"localhost:{default_port}"


def test_chat_smoke_host_candidates_strip_a_leading_slash(monkeypatch) -> None:
    monkeypatch.setenv("PITCH_RTI_SMOKE_HOST", "/127.0.0.1:18089")

    candidates = pitch_cli._chat_smoke_host_candidates()

    assert candidates[0] == "127.0.0.1:18089"


def test_rti_smoke_chat_uses_cmd_on_wsl_for_bat_launchers(monkeypatch, capsys, tmp_path) -> None:
    launcher = tmp_path / "chat-java-hla4" / "chat-java-hla4.bat"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("@echo off\n", encoding="utf-8")

    monkeypatch.setattr(pitch_execution, "is_wsl_environment", lambda: True)
    monkeypatch.setattr(
        pitch_cli,
        "_discover_chat_sample_launcher",
        lambda variant=None: ("java-hla4", launcher) if variant in {None, "auto", "java-hla4", "java-hla4-fedpro", "cpp-hla4"} else None,
    )

    launched = []

    class _Process:
        def __init__(self, command, cwd=None, stdin=None, stdout=None, stderr=None, text=None):
            self.command = command
            self.cwd = cwd
            self.returncode = 0
            self._input = ""
            self.pid = 4242

        def communicate(self, input=None, timeout=None):
            self._input = input or ""
            return (
                "Type messages you want to send.\n> \n",
                "",
            )

        def poll(self):
            return None

        def kill(self):
            return None

    monkeypatch.setattr(pitch_cli, "_start_prti_crc", lambda: (_Process(["pitch-rti"], cwd=launcher.parent), "127.0.0.1:18089"))

    def _fake_popen(command, cwd=None, stdin=None, stdout=None, stderr=None, text=None, env=None, creationflags=None):
        proc = _Process(command, cwd=cwd, stdin=stdin, stdout=stdout, stderr=stderr, text=text)
        launched.append(proc)
        return proc

    monkeypatch.setattr(pitch_routes.subprocess, "Popen", _fake_popen)

    assert main(["rti", "smoke", "chat"]) == 0
    capsys.readouterr()
    assert launched[0].command[0:2] == ["cmd.exe", "/c"]


def test_setup_can_stage_from_a_source_folder(monkeypatch, tmp_path, capsys) -> None:
    source_root = tmp_path / "pitch-download"
    nested_root = source_root / "bundle"
    nested_root.mkdir(parents=True)
    (nested_root / "HlaStarterKit_v1.0.2_linux64.sh").write_text("hla", encoding="utf-8")
    (nested_root / "PitchVisualOMTFree_v2.7.0_linux64.sh").write_text("vomt", encoding="utf-8")
    (nested_root / "prti1516e-free_5_5_10_linux64.sh").write_text("rti", encoding="utf-8")
    monkeypatch.setenv("PITCH_INSTALLER_DROP_ROOT", str(tmp_path / "staged"))
    monkeypatch.setattr(pitch_cli, "run_installer", lambda *args, **kwargs: None)
    monkeypatch.setattr(pitch_cli, "_mark_component_installed", lambda *args, **kwargs: None)
    monkeypatch.setattr(pitch_cli, "_installed_components", lambda: set())

    assert main(["setup", "--source", str(source_root)]) == 0
    captured = capsys.readouterr()
    assert "Route options:" in captured.out
    assert "Selected route: native" in captured.out
    assert "Staged setup assets from" in captured.out
    assert "Staged 3 file(s)" in captured.out
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
    monkeypatch.setattr(pitch_cli, "_print_crc_settings_summary", lambda: print("CRC settings discovery:"))
    monkeypatch.setattr(pitch_cli, "_installed_components", lambda: set())

    assert main(["setup", "--source", str(source_root)]) == 0
    captured = capsys.readouterr()
    if pitch_cli._platform_system() == "Windows":
        assert "falling back to the legacy pRTI package" in captured.out
        expected_legacy_name = "prti1516e-free_5_5_10_windows64.exe"
    else:
        assert "Continuing with the installers that were found." in captured.out
        expected_legacy_name = "prti1516e-free_5_5_10_windows32.exe"
    assert "CRC settings discovery:" in captured.out
    assert installed == [(expected_legacy_name, str(pitch_cli.ROOT))]
    assert "Pitch setup finished." in captured.out


def test_setup_prefers_legacy_rti_64_bit_when_present(monkeypatch, tmp_path, capsys) -> None:
    source_root = tmp_path / "pitch-download"
    nested_root = source_root / "bundle"
    nested_root.mkdir(parents=True)
    (nested_root / "prti1516e-free_5_5_10_windows64.exe").write_text("legacy64", encoding="utf-8")
    (nested_root / "prti1516e-free_5_5_10_windows32.exe").write_text("legacy32", encoding="utf-8")
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
    if pitch_cli._platform_system() == "Windows":
        assert "falling back to the legacy pRTI package" in captured.out
    assert installed == [("prti1516e-free_5_5_10_windows64.exe", str(pitch_cli.ROOT))]
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
    assert calls == [("prti1516e-free_5_5_10_windows32.exe" if pitch_cli._platform_system() != "Windows" else "prti1516e-free_5_5_10_windows64.exe", True)]
    assert "Pitch setup finished." in captured.out


def test_setup_uses_linux_installers_when_running_on_linux(monkeypatch, tmp_path, capsys) -> None:
    source_root = tmp_path / "pitch-download"
    nested_root = source_root / "bundle"
    nested_root.mkdir(parents=True)
    (nested_root / "HlaStarterKit_v1.0.2_linux64.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (nested_root / "PitchVisualOMTFree_v2.7.0_linux64.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (nested_root / "prti1516e-free_5_5_10_linux64.sh").write_text("#!/bin/sh\n", encoding="utf-8")
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
        ("prti1516e-free_5_5_10_linux64.sh", True),
    ]
    assert "Pitch setup finished." in captured.out


def test_linux_start_menu_includes_the_rti(monkeypatch) -> None:
    monkeypatch.setattr(pitch_cli.platform, "system", lambda: "Linux")

    actions = pitch_cli._start_actions()

    assert [action.alias for action in actions] == ["hlastarterkit", "pitchvisualomt", "prti1516e", "docs", "plugin", "root"]


def test_linux_discovers_the_rti_launcher(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(pitch_cli.platform, "system", lambda: "Linux")
    install_root = tmp_path / "prti1516e"
    launcher = install_root / "bin" / "pRTI1516e-nogui"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(pitch_cli, "_configured_install_roots", lambda: {"prti1516e": install_root})

    assert pitch_cli._discover_installed_runtime_launcher("prti1516e") == launcher


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


def test_wsl_translates_windows_paths(monkeypatch) -> None:
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    monkeypatch.setattr(pitch_cli.platform, "release", lambda: "5.15.0-microsoft-standard-WSL2")

    translated = pitch_cli._coerce_cli_path(r"C:\Users\peanu\Downloads\pitch.bin")
    assert translated == Path("/mnt/c/Users/peanu/Downloads/pitch.bin")


def test_wsl_search_roots_include_windows_profile_downloads(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    monkeypatch.setattr(pitch_cli.platform, "release", lambda: "5.15.0-microsoft-standard-WSL2")
    monkeypatch.setattr(pitch_cli, "INSTALLER_SEARCH_ROOTS", ())
    translated_profile = tmp_path / "mnt" / "c" / "Users" / "peanu"
    (translated_profile / "Downloads").mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", r"C:\Users\peanu")
    monkeypatch.setattr(pitch_cli, "_coerce_env_path", lambda raw: translated_profile)

    roots = pitch_cli._installer_search_roots()
    assert translated_profile in roots
    assert translated_profile / "Downloads" in roots


def test_route_show_reports_available_routes(monkeypatch, capsys) -> None:
    monkeypatch.setattr(pitch_cli.platform, "system", lambda: "Windows")

    def _fake_which(name: str):
        if name == "wsl.exe":
            return r"C:\Windows\System32\wsl.exe"
        if name == "docker":
            return r"C:\Program Files\Docker\docker.exe"
        return None

    monkeypatch.setattr(pitch_cli.shutil, "which", _fake_which)
    monkeypatch.setattr(pitch_cli, "_wsl_distribution_names", lambda: ["Ubuntu", "Debian"])
    monkeypatch.setattr(pitch_cli, "_wsl_default_distribution_name", lambda: "Ubuntu")
    monkeypatch.setenv("PITCH_ROUTE_CONTEXT", "wsl")
    monkeypatch.setenv("PITCH_WSL_DISTRO", "Ubuntu")

    assert main(["route", "show"]) == 0
    captured = capsys.readouterr()
    assert "native" in captured.out
    assert "wsl" in captured.out
    assert "docker" in captured.out
    assert "WSL distros: 1: Ubuntu, 2: Debian" in captured.out
    assert "WSL default distro: Ubuntu" in captured.out
    assert "WSL default: the configured default distro unless --wsl-distro is set" in captured.out
    assert "WSL selected: Ubuntu" in captured.out
    assert "recommended: native - Windows now stays on native execution by default." in captured.out


def test_route_available_recognizes_wsl_from_wsl_shell(monkeypatch) -> None:
    monkeypatch.setattr(pitch_cli.platform, "system", lambda: "Linux")
    monkeypatch.setattr(pitch_cli.shutil, "which", lambda name: r"C:\Windows\System32\wsl.exe" if name == "wsl.exe" else None)

    assert pitch_cli._route_available("wsl") is True


def test_default_route_name_prefers_native_on_darwin(monkeypatch) -> None:
    monkeypatch.setattr(pitch_cli.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(pitch_cli.shutil, "which", lambda name: r"/usr/local/bin/docker" if name == "docker" else None)

    assert pitch_cli._default_route_name() == "native"


def test_default_route_name_uses_native_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(pitch_cli.platform, "system", lambda: "Windows")

    assert pitch_cli._default_route_name() == "native"


def test_default_route_reason_matches_heuristic(monkeypatch) -> None:
    monkeypatch.setattr(pitch_cli.platform, "system", lambda: "Windows")
    monkeypatch.setattr(pitch_cli.shutil, "which", lambda name: r"C:\Windows\System32\wsl.exe" if name == "wsl.exe" else None)

    assert pitch_cli._default_route_reason() == "Windows now stays on native execution by default."


def test_route_run_native_delegates_to_main(monkeypatch) -> None:
    captured = {}

    def _fake_main(argv):
        captured["argv"] = argv
        return 7

    monkeypatch.setattr(pitch_cli, "main", _fake_main)

    assert main(["route", "run", "native", "verify"]) == 7
    assert captured["argv"] == ["verify"]


def test_route_run_wsl_translates_windows_paths(monkeypatch) -> None:
    monkeypatch.setattr(pitch_cli.platform, "system", lambda: "Windows")
    monkeypatch.setattr(pitch_cli.shutil, "which", lambda name: r"C:\Windows\System32\wsl.exe" if name == "wsl.exe" else None)
    monkeypatch.setattr(pitch_cli, "_wsl_distribution_names", lambda: ["Ubuntu", "Debian"])

    captured = {}

    class _Result:
        def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake_run(command, check=False, capture_output=False, text=False, env=None):
        captured["command"] = command
        captured["env"] = env
        return _Result()

    monkeypatch.setattr(pitch_cli.subprocess, "run", _fake_run)

    assert main(["route", "run", "--wsl-distro", "Ubuntu", "wsl", "setup", "--source", r"C:\Users\peanu\Downloads\pitch"]) == 0
    command = captured["command"]
    assert command[0] == "wsl.exe"
    assert command[1:4] == ["-d", "Ubuntu", "--cd"]
    assert command[4:6] == ["/mnt/c/Users/peanu/GIT/sheepfling/pitch-rti-toolkit", "bash"]
    assert command[-1] == "python3 -m pitch setup --source /mnt/c/Users/peanu/Downloads/pitch"
    assert captured["env"]["PITCH_ROUTE_CONTEXT"] == "wsl"
    assert captured["env"]["PITCH_WSL_DISTRO"] == "Ubuntu"


def test_route_run_wsl_accepts_distribution_index(monkeypatch) -> None:
    monkeypatch.setattr(pitch_cli.platform, "system", lambda: "Windows")
    monkeypatch.setattr(pitch_cli.shutil, "which", lambda name: r"C:\Windows\System32\wsl.exe" if name == "wsl.exe" else None)
    monkeypatch.setattr(pitch_cli, "_wsl_distribution_names", lambda: ["Ubuntu", "Debian"])

    captured = {}

    class _Result:
        def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake_run(command, check=False, capture_output=False, text=False, env=None):
        captured["command"] = command
        captured["env"] = env
        return _Result()

    monkeypatch.setattr(pitch_cli.subprocess, "run", _fake_run)

    assert main(["route", "run", "--wsl-distro", "2", "wsl", "verify"]) == 0
    command = captured["command"]
    assert command[0] == "wsl.exe"
    assert command[1:4] == ["-d", "Debian", "--cd"]
    assert captured["env"]["PITCH_WSL_DISTRO"] == "Debian"


def test_route_run_wsl_uses_default_distribution_when_not_selected(monkeypatch) -> None:
    monkeypatch.setattr(pitch_cli.platform, "system", lambda: "Windows")
    monkeypatch.setattr(pitch_cli.shutil, "which", lambda name: r"C:\Windows\System32\wsl.exe" if name == "wsl.exe" else None)
    monkeypatch.setattr(pitch_cli, "_wsl_distribution_names", lambda: ["Ubuntu", "Debian"])
    monkeypatch.setattr(pitch_routes, "wsl_default_distribution_name", lambda: "Ubuntu")

    captured = {}

    class _Result:
        def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake_run(command, check=False, capture_output=False, text=False, env=None):
        captured["command"] = command
        captured["env"] = env
        return _Result()

    monkeypatch.setattr(pitch_cli.subprocess, "run", _fake_run)

    assert main(["route", "run", "wsl", "verify"]) == 0
    command = captured["command"]
    assert command[0] == "wsl.exe"
    assert command[1:6] == ["-d", "Ubuntu", "--cd", "/mnt/c/Users/peanu/GIT/sheepfling/pitch-rti-toolkit", "bash"]
    assert captured["env"]["PITCH_ROUTE_CONTEXT"] == "wsl"
    assert captured["env"]["PITCH_WSL_DISTRO"] == "Ubuntu"


def test_route_run_wsl_rejects_unknown_distribution(monkeypatch, capsys) -> None:
    monkeypatch.setattr(pitch_cli.platform, "system", lambda: "Windows")
    monkeypatch.setattr(pitch_cli.shutil, "which", lambda name: r"C:\Windows\System32\wsl.exe" if name == "wsl.exe" else None)
    monkeypatch.setattr(pitch_cli, "_wsl_distribution_names", lambda: ["Ubuntu", "Debian"])

    assert main(["route", "run", "--wsl-distro", "Fedora", "wsl", "verify"]) == 1
    captured = capsys.readouterr()
    assert "WSL distro 'Fedora' is not installed." in captured.err


def test_route_run_docker_builds_container_command(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(pitch_cli.shutil, "which", lambda name: r"C:\Program Files\Docker\docker.exe" if name == "docker" else None)
    env_file = tmp_path / "docker" / "pitch-compose.env"
    monkeypatch.setattr(pitch_cli, "DOCKER_ENV_PATH", env_file)
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("PITCH_DOCKER_PROFILE=future\n", encoding="utf-8")

    captured = {}

    class _Result:
        def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake_run(command, check=False, capture_output=False, text=False, env=None):
        if command == ["docker", "info"]:
            return _Result(0, stdout="Client:\n Context: desktop-linux")
        if command == ["docker", "compose", "version"]:
            return _Result(0, stdout="Docker Compose version v2.32.0")
        captured["command"] = command
        captured["env"] = env
        return _Result()

    monkeypatch.setattr(pitch_cli.subprocess, "run", _fake_run)

    assert main(["route", "run", "docker", "verify"]) == 0
    command = captured["command"]
    assert command[0] == "docker"
    assert command[1:5] == ["compose", "--env-file", str(env_file), "-f"]
    assert command[5] == str(pitch_cli.ROOT / "docker" / "compose.yml")
    assert command[6:10] == ["run", "--rm", "--build", "pitch-future"]
    assert command[-1] == "verify"
    assert captured["env"]["PITCH_ROUTE_CONTEXT"] == "docker"
    assert captured["env"]["PITCH_DOCKER_PROFILE"] == "future"
    assert captured["env"]["PITCH_USER_DATA_ROOT"] == str(pitch_cli.USER_DATA_ROOT)
    assert captured["env"]["PITCH_INSTALLER_DROP_ROOT"] == str(pitch_cli.INSTALLER_DROP_ROOT)
    assert captured["env"]["PITCH_PREFLIGHT_ARTIFACT_ROOT"] == str(pitch_cli.PREFLIGHT_ARTIFACT_ROOT)
    assert captured["env"]["PITCH_DOCKER_ENV_FILE"] == str(env_file)


def test_route_run_docker_warns_when_the_daemon_pipe_is_inaccessible(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setattr(pitch_cli.shutil, "which", lambda name: r"C:\Program Files\Docker\docker.exe" if name == "docker" else None)
    env_file = tmp_path / "docker" / "pitch-compose.env"
    monkeypatch.setattr(pitch_cli, "DOCKER_ENV_PATH", env_file)
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("PITCH_DOCKER_PROFILE=future\n", encoding="utf-8")

    calls: list[list[str]] = []

    class _Result:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake_run(command, check=False, capture_output=False, text=False, env=None):
        calls.append(command)
        if command == ["docker", "compose", "version"]:
            return _Result(0, stdout="Docker Compose version v2.32.0")
        if command == ["docker", "info"]:
            return _Result(1, stderr="permission denied while trying to connect to the docker API at npipe:////./pipe/docker_engine")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(pitch_cli.subprocess, "run", _fake_run)

    assert main(["route", "run", "docker", "verify"]) == 1
    captured = capsys.readouterr()
    assert "Docker Desktop is reachable, but this session cannot access the Docker API pipe." in captured.err
    assert "elevated PowerShell session" in captured.err
    assert calls == [["docker", "compose", "version"], ["docker", "info"]]


def test_route_run_docker_proceeds_after_a_successful_preflight(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(pitch_cli.shutil, "which", lambda name: r"C:\Program Files\Docker\docker.exe" if name == "docker" else None)
    env_file = tmp_path / "docker" / "pitch-compose.env"
    monkeypatch.setattr(pitch_cli, "DOCKER_ENV_PATH", env_file)
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("PITCH_DOCKER_PROFILE=future\n", encoding="utf-8")

    captured = {}

    class _Result:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake_run(command, check=False, capture_output=False, text=False, env=None):
        if command == ["docker", "info"]:
            return _Result(0, stdout="Client:\n Context: desktop-linux")
        if command == ["docker", "compose", "version"]:
            return _Result(0, stdout="Docker Compose version v2.32.0")
        captured["command"] = command
        captured["env"] = env
        return _Result(0)

    monkeypatch.setattr(pitch_cli.subprocess, "run", _fake_run)

    assert main(["route", "run", "docker", "verify"]) == 0
    command = captured["command"]
    assert command[0] == "docker"
    assert command[1:5] == ["compose", "--env-file", str(env_file), "-f"]
    assert command[5] == str(pitch_cli.ROOT / "docker" / "compose.yml")
    assert command[6:10] == ["run", "--rm", "--build", "pitch-future"]
    assert captured["env"]["PITCH_ROUTE_CONTEXT"] == "docker"


def test_route_run_docker_accepts_docker_exe_in_wsl(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(pitch_cli, "_is_wsl_environment", lambda: True)

    def _fake_has_command(command: str) -> bool:
        return command == "docker.exe"

    monkeypatch.setattr(pitch_common, "has_command", _fake_has_command)

    env_file = tmp_path / "docker" / "pitch-compose.env"
    monkeypatch.setattr(pitch_cli, "DOCKER_ENV_PATH", env_file)
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("PITCH_DOCKER_PROFILE=future\n", encoding="utf-8")

    captured = {}

    class _Result:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake_run(command, check=False, capture_output=False, text=False, env=None):
        if command == ["docker.exe", "compose", "version"]:
            return _Result(0, stdout="Docker Compose version v2.32.0")
        if command == ["docker.exe", "info"]:
            return _Result(0, stdout="Client:\n Context: desktop-linux")
        captured["command"] = command
        captured["env"] = env
        return _Result(0)

    monkeypatch.setattr(pitch_cli.subprocess, "run", _fake_run)

    assert main(["route", "run", "docker", "verify"]) == 0
    assert captured["command"][0] == "docker.exe"
    assert captured["env"]["PITCH_ROUTE_CONTEXT"] == "docker"


def test_download_fetch_shows_active_route_banner(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("PITCH_ROUTE_CONTEXT", "wsl")
    monkeypatch.setenv("PITCH_WSL_DISTRO", "Ubuntu")

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
        return _Response()

    monkeypatch.setattr(pitch_cli.urllib.request, "urlopen", _fake_urlopen)

    output_path = tmp_path / "downloads" / "pitch.bin"
    assert main(["download", "fetch", "--url", "https://example.com/files/pitch.bin", "--output", str(output_path)]) == 0
    captured = capsys.readouterr()
    assert "Selected route: WSL (Ubuntu; Windows host -> WSL Linux shell.)" in captured.out


def test_start_shows_active_route_banner(monkeypatch, capsys) -> None:
    monkeypatch.setenv("PITCH_ROUTE_CONTEXT", "docker")
    monkeypatch.setenv("PITCH_DOCKER_PROFILE", "hla4")
    monkeypatch.setattr(pitch_cli, "_run_start_action", lambda *args, **kwargs: None)

    assert main(["start", "root"]) == 0
    captured = capsys.readouterr()
    assert "Selected route: DOCKER (hla4; Docker Compose containerized execution.)" in captured.out


def test_settings_show_discovers_hla4_preview_state(monkeypatch, tmp_path, capsys) -> None:
    settings_file = tmp_path / "prti1516eCRC.settings"
    settings_file.write_text(
        "\n".join(
            [
                "CRC.enableHla4PreviewFeatures=true",
                "CRC.port=8989",
                "CRC.nickname=CRC",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pitch_cli, "_crc_settings_search_roots", lambda: [tmp_path])
    monkeypatch.setattr(pitch_settings, "_crc_settings_search_roots", lambda **kwargs: [tmp_path])

    assert main(["settings", "show"]) == 0
    captured = capsys.readouterr()
    assert "CRC settings file:" in captured.out
    assert "HLA 4 Preview features enabled: yes" in captured.out
    assert "CRC.port = 8989" in captured.out


def test_settings_set_updates_discovered_crc_settings(monkeypatch, tmp_path, capsys) -> None:
    settings_file = tmp_path / "prti1516eCRC.settings"
    settings_file.write_text("CRC.enableHla4PreviewFeatures=false\nCRC.port=8989\n", encoding="utf-8")
    monkeypatch.setattr(pitch_cli, "_crc_settings_search_roots", lambda: [tmp_path])
    monkeypatch.setattr(pitch_settings, "_crc_settings_search_roots", lambda **kwargs: [tmp_path])

    assert main(["settings", "set", "CRC.enableHla4PreviewFeatures", "true"]) == 0
    captured = capsys.readouterr()
    assert "Updated 1 CRC settings file(s):" in captured.out
    assert "prti1516eCRC.settings" in captured.out
    assert "CRC.enableHla4PreviewFeatures=true" in settings_file.read_text(encoding="utf-8")


def test_docker_init_copies_vendor_settings_and_enables_hla4_preview(monkeypatch, tmp_path, capsys) -> None:
    user_data_root = tmp_path / "user-data"
    installer_drop_root = tmp_path / "installers"
    vendor_root = tmp_path / "prti1516e"
    vendor_samples = vendor_root / "samples" / "docker"
    webview_drop = installer_drop_root / "webviewinstaller64"
    webview_drop.mkdir(parents=True)
    vendor_samples.mkdir(parents=True)
    (vendor_samples / "prti1516eCRC.settings").write_text("CRC.enableHla4PreviewFeatures=false\nCRC.port=8989\n", encoding="utf-8")
    (vendor_samples / "prti1516eLRC.settings").write_text("LRC.example=true\n", encoding="utf-8")
    (webview_drop / "webview.war").write_text("dummy webview payload\n", encoding="utf-8")
    monkeypatch.setenv("PITCH_USER_DATA_ROOT", str(user_data_root))
    monkeypatch.setenv("PITCH_INSTALLER_DROP_ROOT", str(installer_drop_root))
    monkeypatch.setenv("PITCH_PRTI_HOME", str(vendor_root))
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_ENV_FILE", str(user_data_root / "docker" / "pitch-vendor-compose.env"))
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_SETTINGS_ROOT", str(user_data_root / "docker" / "vendor-settings"))
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_BUILD_ROOT", str(user_data_root / "docker" / "vendor-build"))

    assert main(["docker", "init", "--enable-hla4-preview"]) == 0
    captured = capsys.readouterr()
    assert "Wrote vendor Docker env file:" in captured.out
    assert "Wrote vendor settings overlay:" in captured.out

    env_file = user_data_root / "docker" / "pitch-vendor-compose.env"
    settings_root = user_data_root / "docker" / "vendor-settings"
    build_root = user_data_root / "docker" / "vendor-build"
    crc_settings = settings_root / "prti1516eCRC.settings"
    lrc_settings = settings_root / "prti1516eLRC.settings"

    assert env_file.exists()
    assert crc_settings.exists()
    assert lrc_settings.exists()
    assert (build_root / "webviewinstaller64" / "webview.war").exists()
    assert "CRC_ENABLE_HLA4_PREVIEW=1" in env_file.read_text(encoding="utf-8")
    assert "PITCH_PRTI_HOME=" in env_file.read_text(encoding="utf-8")
    assert "PITCH_VENDOR_DOCKER_BUILD_ROOT=" in env_file.read_text(encoding="utf-8")
    assert "PITCH_VENDOR_CRC_PORT=" in env_file.read_text(encoding="utf-8")
    assert "PITCH_VENDOR_WEB_VIEW_PORT=" in env_file.read_text(encoding="utf-8")
    assert "CRC.enableHla4PreviewFeatures=true" in crc_settings.read_text(encoding="utf-8")


def test_docker_status_reports_vendor_preview_state(monkeypatch, tmp_path, capsys) -> None:
    user_data_root = tmp_path / "user-data"
    vendor_root = tmp_path / "prti1516e"
    vendor_samples = vendor_root / "samples" / "docker"
    vendor_samples.mkdir(parents=True)
    (vendor_samples / "prti1516eCRC.settings").write_text("CRC.enableHla4PreviewFeatures=true\n", encoding="utf-8")
    (vendor_samples / "prti1516eLRC.settings").write_text("LRC.example=true\n", encoding="utf-8")
    monkeypatch.setenv("PITCH_USER_DATA_ROOT", str(user_data_root))
    monkeypatch.setenv("PITCH_PRTI_HOME", str(vendor_root))
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_ENV_FILE", str(user_data_root / "docker" / "pitch-vendor-compose.env"))
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_SETTINGS_ROOT", str(user_data_root / "docker" / "vendor-settings"))
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_BUILD_ROOT", str(user_data_root / "docker" / "vendor-build"))

    assert main(["docker", "init", "--enable-hla4-preview"]) == 0
    assert main(["docker", "status"]) == 0
    captured = capsys.readouterr()
    assert "Vendor Docker setup:" in captured.out
    assert "initialized: yes" in captured.out
    assert "HLA 4 Preview: true" in captured.out


def test_checked_in_docker_configs_do_not_hardcode_container_paths() -> None:
    checked_in_files = [
        pitch_cli.ROOT / "docker" / "Dockerfile",
        pitch_cli.ROOT / "docker" / "compose.yml",
        pitch_cli.ROOT / "docker" / "pitch-vendor-compose.yml",
    ]
    forbidden_literals = [
        "/workspace",
        "/var/lib/pitch/data",
        "/var/lib/pitch/installers",
        "/var/lib/pitch/data/preflight",
        "/opt/prti1516e",
        "/root/prti1516e",
    ]

    for path in checked_in_files:
        text = path.read_text(encoding="utf-8")
        for literal in forbidden_literals:
            assert literal not in text, f"{path} still hardcodes {literal}"


def test_wsl_wrapper_script_targets_the_route_entrypoint() -> None:
    ps1_path = pitch_cli.ROOT / "scripts" / "pitch-wsl.ps1"
    cmd_path = pitch_cli.ROOT / "scripts" / "pitch-wsl.cmd"

    ps1_text = ps1_path.read_text(encoding="utf-8")
    cmd_text = cmd_path.read_text(encoding="utf-8")

    assert "python -m pitch route run wsl" in ps1_text
    assert "Resolve-Path" in ps1_text
    assert "Set-Location" in ps1_text
    assert "pitch-wsl.ps1" in cmd_text
    assert "ExecutionPolicy Bypass" in cmd_text


def test_docker_up_builds_the_vendor_compose_command(monkeypatch, tmp_path) -> None:
    user_data_root = tmp_path / "user-data"
    vendor_root = tmp_path / "prti1516e"
    vendor_samples = vendor_root / "samples" / "docker"
    vendor_samples.mkdir(parents=True)
    (vendor_samples / "prti1516eCRC.settings").write_text("CRC.enableHla4PreviewFeatures=false\n", encoding="utf-8")
    (vendor_samples / "prti1516eLRC.settings").write_text("LRC.example=true\n", encoding="utf-8")
    monkeypatch.setenv("PITCH_USER_DATA_ROOT", str(user_data_root))
    monkeypatch.setenv("PITCH_PRTI_HOME", str(vendor_root))
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_ENV_FILE", str(user_data_root / "docker" / "pitch-vendor-compose.env"))
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_SETTINGS_ROOT", str(user_data_root / "docker" / "vendor-settings"))
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_BUILD_ROOT", str(user_data_root / "docker" / "vendor-build"))

    assert main(["docker", "init"]) == 0

    captured = {}

    class _Result:
        def __init__(self, returncode: int = 0) -> None:
            self.returncode = returncode

    def _fake_run(command, check=False, capture_output=False, text=False, env=None):
        captured["command"] = command
        return _Result(0)

    monkeypatch.setattr(pitch_cli.subprocess, "run", _fake_run)
    crc_port = pitch_ports.route_rti_port("vendor-docker")
    monkeypatch.setattr(pitch_cli, "_vendor_docker_smoke_check", lambda: (True, f"Vendor CRC is reachable on 127.0.0.1:{crc_port}."))

    assert main(["docker", "up"]) == 0
    command = captured["command"]
    assert command[0:4] == ["docker", "compose", "--env-file", str(user_data_root / "docker" / "pitch-vendor-compose.env")]
    assert command[4] == "-f"
    assert command[5] == str(pitch_cli.ROOT / "docker" / "pitch-vendor-compose.yml")
    assert command[6:10] == ["up", "-d", "--build", "pitch-crc"]


def test_docker_restart_runs_down_then_up_and_smoke(monkeypatch, tmp_path) -> None:
    user_data_root = tmp_path / "user-data"
    vendor_root = tmp_path / "prti1516e"
    vendor_samples = vendor_root / "samples" / "docker"
    vendor_samples.mkdir(parents=True)
    (vendor_samples / "prti1516eCRC.settings").write_text("CRC.enableHla4PreviewFeatures=false\n", encoding="utf-8")
    (vendor_samples / "prti1516eLRC.settings").write_text("LRC.example=true\n", encoding="utf-8")
    monkeypatch.setenv("PITCH_USER_DATA_ROOT", str(user_data_root))
    monkeypatch.setenv("PITCH_PRTI_HOME", str(vendor_root))
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_ENV_FILE", str(user_data_root / "docker" / "pitch-vendor-compose.env"))
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_SETTINGS_ROOT", str(user_data_root / "docker" / "vendor-settings"))
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_BUILD_ROOT", str(user_data_root / "docker" / "vendor-build"))

    assert main(["docker", "init"]) == 0

    captured = []

    class _Result:
        def __init__(self, returncode: int = 0) -> None:
            self.returncode = returncode

    def _fake_run(command, check=False, capture_output=False, text=False, env=None):
        captured.append(command)
        return _Result(0)

    monkeypatch.setattr(pitch_cli.subprocess, "run", _fake_run)
    crc_port = pitch_ports.route_rti_port("vendor-docker")
    monkeypatch.setattr(pitch_cli, "_vendor_docker_smoke_check", lambda: (True, f"Vendor CRC is reachable on 127.0.0.1:{crc_port}."))

    assert main(["docker", "restart"]) == 0
    assert captured[0][6:] == ["down"]
    assert captured[1][6:10] == ["up", "-d", "--build", "pitch-crc"]


def test_docker_smoke_reports_reachability(monkeypatch, capsys) -> None:
    captured = {}
    crc_port = pitch_ports.route_rti_port("vendor-docker")

    def _fake_smoke_check(*, timeout_seconds=60.0, interval_seconds=1.0):
        captured["timeout_seconds"] = timeout_seconds
        captured["interval_seconds"] = interval_seconds
        return True, f"Vendor CRC is reachable on 127.0.0.1:{crc_port}."

    monkeypatch.setattr(pitch_cli, "_vendor_docker_smoke_check", _fake_smoke_check)

    assert main(["docker", "smoke", "--timeout-seconds", "12.5", "--interval-seconds", "0.25"]) == 0
    captured_out = capsys.readouterr()
    assert f"Vendor CRC is reachable on 127.0.0.1:{crc_port}." in captured_out.out
    assert captured["timeout_seconds"] == 12.5
    assert captured["interval_seconds"] == 0.25


def test_docker_ps_builds_the_vendor_compose_command(monkeypatch, tmp_path) -> None:
    user_data_root = tmp_path / "user-data"
    vendor_root = tmp_path / "prti1516e"
    vendor_samples = vendor_root / "samples" / "docker"
    vendor_samples.mkdir(parents=True)
    (vendor_samples / "prti1516eCRC.settings").write_text("CRC.enableHla4PreviewFeatures=false\n", encoding="utf-8")
    (vendor_samples / "prti1516eLRC.settings").write_text("LRC.example=true\n", encoding="utf-8")
    monkeypatch.setenv("PITCH_USER_DATA_ROOT", str(user_data_root))
    monkeypatch.setenv("PITCH_PRTI_HOME", str(vendor_root))
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_ENV_FILE", str(user_data_root / "docker" / "pitch-vendor-compose.env"))
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_SETTINGS_ROOT", str(user_data_root / "docker" / "vendor-settings"))
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_BUILD_ROOT", str(user_data_root / "docker" / "vendor-build"))

    assert main(["docker", "init"]) == 0

    captured = {}

    class _Result:
        def __init__(self, returncode: int = 0) -> None:
            self.returncode = returncode

    def _fake_run(command, check=False, capture_output=False, text=False, env=None):
        captured["command"] = command
        return _Result(0)

    monkeypatch.setattr(pitch_cli.subprocess, "run", _fake_run)

    assert main(["docker", "ps", "--all"]) == 0
    command = captured["command"]
    assert command[0:4] == ["docker", "compose", "--env-file", str(user_data_root / "docker" / "pitch-vendor-compose.env")]
    assert command[4] == "-f"
    assert command[5] == str(pitch_cli.ROOT / "docker" / "pitch-vendor-compose.yml")
    assert command[6:] == ["ps", "--all"]


def test_docker_logs_builds_the_vendor_compose_command(monkeypatch, tmp_path) -> None:
    user_data_root = tmp_path / "user-data"
    vendor_root = tmp_path / "prti1516e"
    vendor_samples = vendor_root / "samples" / "docker"
    vendor_samples.mkdir(parents=True)
    (vendor_samples / "prti1516eCRC.settings").write_text("CRC.enableHla4PreviewFeatures=false\n", encoding="utf-8")
    (vendor_samples / "prti1516eLRC.settings").write_text("LRC.example=true\n", encoding="utf-8")
    monkeypatch.setenv("PITCH_USER_DATA_ROOT", str(user_data_root))
    monkeypatch.setenv("PITCH_PRTI_HOME", str(vendor_root))
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_ENV_FILE", str(user_data_root / "docker" / "pitch-vendor-compose.env"))
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_SETTINGS_ROOT", str(user_data_root / "docker" / "vendor-settings"))
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_BUILD_ROOT", str(user_data_root / "docker" / "vendor-build"))

    assert main(["docker", "init"]) == 0

    captured = {}

    class _Result:
        def __init__(self, returncode: int = 0) -> None:
            self.returncode = returncode

    def _fake_run(command, check=False, capture_output=False, text=False, env=None):
        captured["command"] = command
        return _Result(0)

    monkeypatch.setattr(pitch_cli.subprocess, "run", _fake_run)

    assert main(["docker", "logs", "--tail", "25", "--service", "pitch-crc"]) == 0
    command = captured["command"]
    assert command[0:4] == ["docker", "compose", "--env-file", str(user_data_root / "docker" / "pitch-vendor-compose.env")]
    assert command[4] == "-f"
    assert command[5] == str(pitch_cli.ROOT / "docker" / "pitch-vendor-compose.yml")
    assert command[6:] == ["logs", "--no-color", "--tail", "25", "pitch-crc"]


def test_docker_inspect_reports_summary_and_ps(monkeypatch, tmp_path, capsys) -> None:
    user_data_root = tmp_path / "user-data"
    vendor_root = tmp_path / "prti1516e"
    vendor_samples = vendor_root / "samples" / "docker"
    vendor_samples.mkdir(parents=True)
    (vendor_samples / "prti1516eCRC.settings").write_text("CRC.enableHla4PreviewFeatures=true\n", encoding="utf-8")
    (vendor_samples / "prti1516eLRC.settings").write_text("LRC.example=true\n", encoding="utf-8")
    monkeypatch.setenv("PITCH_USER_DATA_ROOT", str(user_data_root))
    monkeypatch.setenv("PITCH_PRTI_HOME", str(vendor_root))
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_ENV_FILE", str(user_data_root / "docker" / "pitch-vendor-compose.env"))
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_SETTINGS_ROOT", str(user_data_root / "docker" / "vendor-settings"))
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_BUILD_ROOT", str(user_data_root / "docker" / "vendor-build"))

    assert main(["docker", "init", "--enable-hla4-preview"]) == 0

    captured = {}

    class _Result:
        def __init__(self, returncode: int = 0) -> None:
            self.returncode = returncode

    def _fake_run(command, check=False, capture_output=False, text=False, env=None):
        captured["command"] = command
        return _Result(0)

    monkeypatch.setattr(pitch_cli.subprocess, "run", _fake_run)

    assert main(["docker", "inspect"]) == 0
    captured_out = capsys.readouterr()
    assert "Vendor Docker setup:" in captured_out.out
    assert "initialized: yes" in captured_out.out
    assert "HLA 4 Preview: true" in captured_out.out
    command = captured["command"]
    assert command[0:4] == ["docker", "compose", "--env-file", str(user_data_root / "docker" / "pitch-vendor-compose.env")]
    assert command[4] == "-f"
    assert command[5] == str(pitch_cli.ROOT / "docker" / "pitch-vendor-compose.yml")
    assert command[6:] == ["ps", "--all"]


def test_vendor_docker_smoke_checks_webview_when_enabled(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / "docker" / "pitch-vendor-compose.env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text("DISABLE_WEB_VIEW=\n", encoding="utf-8")
    build_root = tmp_path / "docker" / "vendor-build"
    (build_root / "webviewinstaller64").mkdir(parents=True)
    (build_root / "webviewinstaller64" / "webview.war").write_text("dummy webview payload\n", encoding="utf-8")
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_ENV_FILE", str(env_file))
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_BUILD_ROOT", str(build_root))

    calls = {}

    def _fake_wait_for_port(host, port, *, timeout_seconds=60.0, interval_seconds=1.0):
        calls["wait_for_port"] = (host, port, timeout_seconds, interval_seconds)
        return True

    def _fake_webview_check(*, timeout_seconds=10.0):
        calls["webview_timeout"] = timeout_seconds
        webview_port = pitch_ports.route_webview_port("vendor-docker")
        return True, f"Vendor Web View is reachable at http://127.0.0.1:{webview_port}/webview/."

    monkeypatch.setattr(pitch_cli, "_vendor_docker_wait_for_port", _fake_wait_for_port)
    monkeypatch.setattr(pitch_cli, "_vendor_docker_webview_check", _fake_webview_check)

    ok, detail = pitch_cli._vendor_docker_smoke_check(timeout_seconds=7.5, interval_seconds=0.25)

    crc_port = pitch_ports.route_rti_port("vendor-docker")
    webview_port = pitch_ports.route_webview_port("vendor-docker")
    assert ok is True
    assert f"Vendor CRC is reachable on 127.0.0.1:{crc_port}." in detail
    assert "Vendor Web View is reachable" in detail
    assert f"http://127.0.0.1:{webview_port}/webview/" in detail
    assert calls["wait_for_port"] == ("127.0.0.1", crc_port, 7.5, 0.25)
    assert calls["webview_timeout"] == 10.0


def test_vendor_docker_webview_check_skips_without_payload(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / "docker" / "pitch-vendor-compose.env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text("DISABLE_WEB_VIEW=\n", encoding="utf-8")
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_ENV_FILE", str(env_file))
    monkeypatch.setenv("PITCH_VENDOR_DOCKER_BUILD_ROOT", str(tmp_path / "docker" / "vendor-build"))

    ok, detail = pitch_docker_vendor.vendor_docker_webview_check()

    assert ok is True
    assert "no Web View payload was staged" in detail


def test_start_prti1516e_prints_the_settings_summary(monkeypatch, capsys) -> None:
    monkeypatch.setattr(pitch_cli, "_print_crc_settings_summary", lambda: print("CRC settings discovery:"))
    monkeypatch.setattr(pitch_cli, "_run_start_action", lambda *args, **kwargs: None)

    assert main(["start", "prti1516e"]) == 0
    captured = capsys.readouterr()
    assert "CRC settings discovery:" in captured.out


def test_run_start_action_uses_the_active_route_port_profile(monkeypatch, tmp_path) -> None:
    launcher = tmp_path / "pRTI1516e-nogui.bat"
    launcher.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setenv("PITCH_ROUTE_CONTEXT", "docker")
    monkeypatch.setattr(pitch_cli, "_discover_installed_runtime_launcher", lambda component_key: launcher if component_key == "prti1516e" else None)

    captured = {}

    def _fake_launch_program(path, env=None):
        captured["path"] = path
        captured["env"] = env

    monkeypatch.setattr(pitch_cli, "_launch_program", _fake_launch_program)

    action = pitch_cli.StartAction("3", "prti1516e-free", "runtime", launcher, "prti1516e")
    pitch_cli._run_start_action(action, argparse.Namespace(port=None, ports_config=None))

    assert captured["path"] == launcher
    assert captured["env"]["PITCH_PORT"] == str(pitch_ports.route_rti_port("route-docker"))
    assert captured["env"]["PITCH_PORT_PROFILE"] == "route-docker"


def test_start_can_enable_hla4_preview_before_launch(monkeypatch, tmp_path, capsys) -> None:
    settings_file = tmp_path / "prti1516eCRC.settings"
    settings_file.write_text("CRC.enableHla4PreviewFeatures=false\n", encoding="utf-8")
    monkeypatch.setattr(pitch_cli, "_crc_settings_search_roots", lambda: [tmp_path])
    monkeypatch.setattr(pitch_settings, "_crc_settings_search_roots", lambda **kwargs: [tmp_path])
    monkeypatch.setattr(pitch_cli, "_run_start_action", lambda *args, **kwargs: None)

    assert main(["start", "prti1516e", "--enable-hla4-preview"]) == 0
    captured = capsys.readouterr()
    assert "start: set HLA 4 Preview to enabled in:" in captured.out
    assert "prti1516eCRC.settings" in captured.out
    assert "HLA 4 Preview features enabled: yes" in captured.out
    assert "CRC.enableHla4PreviewFeatures=true" in settings_file.read_text(encoding="utf-8")


def test_setup_can_enable_hla4_preview_for_an_already_installed_bundle(monkeypatch, tmp_path, capsys) -> None:
    settings_file = tmp_path / "prti1516eCRC.settings"
    settings_file.write_text("CRC.enableHla4PreviewFeatures=false\n", encoding="utf-8")
    monkeypatch.setattr(pitch_cli, "_crc_settings_search_roots", lambda: [tmp_path])
    monkeypatch.setattr(pitch_cli, "_print_route_visibility", lambda **kwargs: None)
    monkeypatch.setattr(pitch_cli, "_is_windows_platform", lambda: False)
    monkeypatch.setattr(pitch_cli, "_verify_setup_paths", lambda: [])
    monkeypatch.setattr(pitch_cli, "_installed_components", lambda: {"prti1516e"})
    monkeypatch.setattr(
        pitch_cli,
        "_install_specs_for_system",
        lambda include_legacy_rti: [pitch_cli.InstallSpec("prti1516e", "prti1516e-free", tmp_path / "installer.sh")],
    )
    monkeypatch.setattr(pitch_cli, "_log_detected_installed", lambda detected: None)
    monkeypatch.setattr(pitch_cli, "_maybe_print_prti_settings_summary", lambda triggered: None)

    assert main(["setup", "--enable-hla4-preview"]) == 0
    captured = capsys.readouterr()
    assert "setup: set HLA 4 Preview to enabled in:" in captured.out
    assert "prti1516eCRC.settings" in captured.out
    assert "CRC.enableHla4PreviewFeatures=true" in settings_file.read_text(encoding="utf-8")


def test_setup_route_wsl_keeps_hla4_preview_flag(monkeypatch) -> None:
    captured = {}

    def _fake_run_route_command(route_name, pitch_args, wsl_distro=None):
        captured["route_name"] = route_name
        captured["pitch_args"] = pitch_args
        captured["wsl_distro"] = wsl_distro
        return 0

    monkeypatch.setattr(pitch_cli, "_run_route_command", _fake_run_route_command)
    monkeypatch.setattr(pitch_cli, "_wsl_distribution_names", lambda: ["Ubuntu"])

    assert main(["setup", "--route", "wsl", "--wsl-distro", "Ubuntu", "--enable-hla4-preview"]) == 0
    assert captured["route_name"] == "wsl"
    assert "--enable-hla4-preview" in captured["pitch_args"]
    assert captured["wsl_distro"] == "Ubuntu"


def test_setup_route_wsl_dispatches_through_route_runner(monkeypatch) -> None:
    captured = {}

    def _fake_run_route_command(route_name, pitch_args, wsl_distro=None):
        captured["route_name"] = route_name
        captured["pitch_args"] = pitch_args
        captured["wsl_distro"] = wsl_distro
        return 0

    monkeypatch.setattr(pitch_cli, "_run_route_command", _fake_run_route_command)
    monkeypatch.setattr(pitch_cli, "_wsl_distribution_names", lambda: ["Ubuntu"])

    assert main(["setup", "--route", "wsl", "--wsl-distro", "Ubuntu", "--source", r"C:\Users\peanu\Downloads\pitch"]) == 0
    assert captured["route_name"] == "wsl"
    assert captured["pitch_args"][0:3] == ["setup", "--route", "native"]
    assert r"C:\Users\peanu\Downloads\pitch" in captured["pitch_args"]
    assert captured["wsl_distro"] == "Ubuntu"


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

    monkeypatch.setattr(pitch_execution, "is_windows_platform", lambda: True)
    monkeypatch.setattr(pitch_execution, "is_macos_platform", lambda: False)
    monkeypatch.setattr(pitch_execution, "is_wsl_environment", lambda: False)
    monkeypatch.setattr(pitch_execution.os, "startfile", _raise_permission_error, raising=False)
    monkeypatch.setattr(pitch_execution.subprocess, "Popen", _fake_popen)

    assert main(["start", "root"]) == 0
    assert launched
    assert launched[0][0][0] == "explorer.exe"


def test_launcher_command_uses_open_on_macos_for_apps(monkeypatch, tmp_path) -> None:
    app_bundle = tmp_path / "PitchVisualOMTFree.app"
    app_bundle.mkdir()
    monkeypatch.setattr(pitch_execution, "is_macos_platform", lambda: True)
    monkeypatch.setattr(pitch_execution, "is_windows_platform", lambda: False)
    monkeypatch.setattr(pitch_execution, "is_wsl_environment", lambda: False)

    assert pitch_execution.launcher_command(app_bundle) == ["open", str(app_bundle)]


def test_vendor_docker_compose_command_uses_the_shared_docker_resolver(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / "docker" / "pitch-vendor-compose.env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("PITCH_DOCKER_PROFILE=future\n", encoding="utf-8")

    monkeypatch.setenv("PITCH_VENDOR_DOCKER_ENV_FILE", str(env_file))
    monkeypatch.setattr(pitch_docker_vendor, "resolved_docker_command", lambda: "docker.exe")

    command = pitch_docker_vendor.vendor_docker_compose_command("up -d --build pitch-crc")

    assert command[0] == "docker.exe"
    assert command[1:4] == ["compose", "--env-file", str(env_file)]
