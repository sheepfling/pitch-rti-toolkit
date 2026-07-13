"""Unified Pitch command line entry point."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import platform
import shlex
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path

from pitch_bootstrap import (
    ROOT,
    bundle_fingerprint,
    discover_file_locations,
    discover_linux_install_locations,
    discover_windows_install_locations,
    detect_windows_installed_components,
    install_roots_path,
    install_state_path,
    load_install_state,
    load_install_roots,
    PortTarget,
    parse_ports_config,
    probe_targets,
    resolve_artifact_root,
    resolve_asset_root,
    ensure_installer_drop_root,
    resolve_installer_drop_root,
    resolve_user_data_root,
    run_installer,
    sha256_file,
    save_install_state,
    verify_manifest,
    verify_paths_exist,
)
from pitch.common import (
    coerce_cli_path as _coerce_cli_path,
    coerce_env_path as _coerce_env_path,
    has_command as _has_command,
    is_linux_platform as _is_linux_platform,
    is_macos_platform as _is_macos_platform,
    is_wsl_environment as _is_wsl_environment,
    is_windows_platform as _is_windows_platform,
    looks_like_windows_path as _looks_like_windows_path,
    platform_system as _platform_system,
    resolved_docker_command as _resolved_docker_command,
    translate_windows_path as _translate_windows_path,
)
from pitch.settings import (
    apply_requested_hla4_preview,
    print_crc_settings_summary,
    read_env_value,
    set_settings_value,
    set_crc_setting_everywhere,
    vendor_crc_settings_path,
    vendor_docker_status_lines,
)
from pitch.execution import launch_program as _launch_program, launcher_command as _launcher_command, open_path as _open_path
from pitch.docker_vendor import (
    copy_vendor_docker_context as _copy_vendor_docker_context,
    copy_vendor_settings as _copy_vendor_settings,
    vendor_docker_build_root as _vendor_docker_build_root_impl,
    vendor_docker_compose_command as _vendor_docker_compose_command_impl,
    vendor_docker_env_path as _vendor_docker_env_path_impl,
    vendor_docker_install_root as _vendor_docker_install_root_impl,
    vendor_docker_payload as _vendor_docker_payload_impl,
    vendor_docker_settings_root as _vendor_docker_settings_root_impl,
    vendor_docker_status_lines as _vendor_docker_status_lines_impl,
    vendor_docker_webview_check as _vendor_docker_webview_check_impl,
    vendor_docker_wait_for_port as _vendor_docker_wait_for_port_impl,
    run_vendor_docker_compose as _run_vendor_docker_compose_impl,
    write_docker_env_file as _write_docker_env_file,
    VENDOR_DOCKER_COMPOSE_PATH as _VENDOR_DOCKER_COMPOSE_PATH,
)
from pitch.ports import route_rti_port, route_surface_for_context, route_webview_port
from pitch.routes import (
    chat_launcher_command as _chat_launcher_command,
    chat_sample_choices as _chat_sample_choices,
    discovered_chat_sample_launcher as _discover_chat_sample_launcher,
    discovered_installed_runtime_launcher as _discover_installed_runtime_launcher_impl,
    discovered_prti_install_root as _discover_prti_install_root,
    default_route_name as _default_route_name,
    default_route_reason as _default_route_reason,
    detected_install_roots as _detected_install_roots_impl,
    installed_components as _installed_components_impl,
    installer_search_roots as _installer_search_roots,
    log_detected_installed as _log_detected_installed,
    lookup_start_action as _lookup_start_action_impl,
    normalize_install_roots as _normalize_install_roots,
    print_active_route_banner as _print_active_route_banner,
    print_route_visibility as _print_route_visibility,
    resolve_installer_path as _resolve_installer_path,
    resolve_wsl_distro_selection as _resolve_wsl_distro_selection,
    route_available as _route_available,
    route_context_detail as _route_context_detail,
    route_context_name as _route_context_name,
    route_payload_command as _route_payload_command,
    route_payload_env as _route_payload_env,
    route_specs as _route_specs,
    route_summary as _route_summary,
    run_chat_process as _run_chat_process_impl,
    run_chat_smoke_test as _run_chat_smoke_test,
    _start_prti_crc as _start_prti_crc,
    run_route_command as _run_route_command_impl,
    install_specs_for_system as _install_specs_for_system_impl,
    run_start_action as _run_start_action_impl,
    show_menu as _show_menu_impl,
    start_actions as _start_actions_impl,
    translate_route_args_for_wsl as _translate_route_args_for_wsl,
    wsl_default_distribution_name as _wsl_default_distribution_name,
    wsl_distribution_names as _wsl_distribution_names,
)


ASSET_ROOT = resolve_asset_root(ROOT)
USER_DATA_ROOT = resolve_user_data_root()
ARTIFACT_ROOT = resolve_artifact_root(ROOT)
INSTALLER_DROP_ROOT = resolve_installer_drop_root()
DOWNLOAD_CONTACT_FILENAME = ".pitch-download-contact.json"
DOWNLOAD_CONTACT_TEMPLATE = ASSET_ROOT / "download-contact.example.json"
DOWNLOAD_SCRIPT_PATH = ASSET_ROOT / "download-autofill.js"
PREFLIGHT_ARTIFACT_ROOT = ARTIFACT_ROOT / "preflight"
PREFLIGHT_ARTIFACT_FILENAME = "pitch-preflight.json"
DOCKER_ENV_FILENAME = "pitch-compose.env"
DOCKER_ENV_ROOT = ARTIFACT_ROOT / "docker"
DOCKER_ENV_PATH = DOCKER_ENV_ROOT / DOCKER_ENV_FILENAME
VENDOR_DOCKER_ENV_FILENAME = "pitch-vendor-compose.env"
VENDOR_DOCKER_ENV_PATH = DOCKER_ENV_ROOT / VENDOR_DOCKER_ENV_FILENAME
VENDOR_DOCKER_SETTINGS_ROOT = DOCKER_ENV_ROOT / "vendor-settings"
VENDOR_DOCKER_BUILD_ROOT = DOCKER_ENV_ROOT / "vendor-build"
VENDOR_CRC_SETTINGS_PATH = VENDOR_DOCKER_SETTINGS_ROOT / "prti1516eCRC.settings"
VENDOR_LRC_SETTINGS_PATH = VENDOR_DOCKER_SETTINGS_ROOT / "prti1516eLRC.settings"
VENDOR_DOCKER_COMPOSE_PATH = ROOT / "docker" / "pitch-vendor-compose.yml"
INSTALLER_CHECKSUM_MANIFEST_NAME = "checksums.sha256"
CRC_SETTINGS_NAME_HINTS = (
    "prti1516eCRC.settings",
    "pRTI1516eCRC.settings",
    "prti1516e-freeCRC.settings",
    "PitchCRC.settings",
    "CRC.settings",
)
CHAT_SAMPLE_VARIANTS = {
    "java-hla4": (
        "chat-java-hla4/chat-java-hla4.bat",
        "chat-java-hla4/chat-java-hla4.cmd",
        "chat-java-hla4/chat-java-hla4.sh",
        "chat-java-hla4/chat-java-hla4",
    ),
    "java-hla4-fedpro": (
        "chat-java-hla4-fedpro/chat-java-hla4-fedpro.bat",
        "chat-java-hla4-fedpro/chat-java-hla4-fedpro.cmd",
        "chat-java-hla4-fedpro/chat-java-hla4-fedpro.sh",
        "chat-java-hla4-fedpro/chat-java-hla4-fedpro",
    ),
    "cpp-hla4": (
        "chat-cpp-hla4/chat-cpp-hla4_vc140_32.exe",
        "chat-cpp-hla4/chat-cpp-hla4_vc140_64.exe",
        "chat-cpp-hla4/chat-cpp-hla4.sh",
        "chat-cpp-hla4/chat-cpp-hla4",
    ),
}
DOWNLOAD_CONTACT_DEFAULTS = {
    "first_name": "John",
    "last_name": "Doe",
    "title": "Engineer",
    "organization": "Self",
    "organization_type": "Other",
    "country": "United States",
    "accepted_products": [
        "Pitch pRTI Free",
        "Pitch Visual OMT Free",
        "HLA Starter kit",
        "HLA Tutorial",
        "Pitch Unreal Engine Connector Free",
    ],
    "subscribe_newsletter": False,
}


def _platform_system() -> str:
    return platform.system()


def _is_windows_platform() -> bool:
    return _platform_system() == "Windows"


def _is_linux_platform() -> bool:
    return _platform_system() == "Linux"


def _is_macos_platform() -> bool:
    return _platform_system() == "Darwin"
PITCH_FREE_DOWNLOAD_URL = "https://www2.pitch.se/pRTI1516e/Releases/v5.5.10-free/SnvHLyNhR6A9ZgoQ/install.asp"
PITCH_FREE_DOWNLOAD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www2.pitch.se",
    "Referer": PITCH_FREE_DOWNLOAD_URL,
}
ASSET_IMPORTABLE_FILENAMES = (
    "Pitch Unreal Engine Connector Users Guide.pdf",
    "TheHLAtutorial.pdf",
    "pitch_visual_omt_users_guide.pdf",
    "prti_users_guide.pdf",
    "release_notes.txt",
    "HlaStarterKit_v1.0.2_windows64.exe",
    "PitchVisualOMTFree_v2.7.0_windows64.exe",
    "HlaStarterKit_v1.0.2_linux64.sh",
    "PitchVisualOMTFree_v2.7.0_linux64.sh",
    "prti1516e-free_5_5_10_windows64.exe",
    "prti1516e-free_5_5_10_windows32.exe",
    "prti1516e-free_5_5_10_linux32.sh",
    "prti1516e-free_5_5_10_linux64.sh",
    "prti1516e-free_5_5_10_mac.dmg",
)
CHECKSUM_TRACKED_FILENAMES = {
    "HlaStarterKit_v1.0.2_windows64.exe",
    "PitchVisualOMTFree_v2.7.0_windows64.exe",
    "HlaStarterKit_v1.0.2_linux64.sh",
    "PitchVisualOMTFree_v2.7.0_linux64.sh",
    "prti1516e-free_5_5_10_windows64.exe",
    "prti1516e-free_5_5_10_windows32.exe",
    "prti1516e-free_5_5_10_linux32.sh",
    "prti1516e-free_5_5_10_linux64.sh",
    "prti1516e-free_5_5_10_mac.dmg",
}


@dataclass(frozen=True)
class StartAction:
    key: str
    label: str
    kind: str
    path: Path
    alias: str


@dataclass(frozen=True)
class InstallSpec:
    key: str
    label: str
    path: Path


@dataclass(frozen=True)
class RouteSpec:
    name: str
    label: str
    description: str


COMMON_REQUIRED_PATHS = [
    "README.md",
    "pitch/checksums.sha256",
    "pitch/ports.conf",
    "pitch/pitch-install-roots.example.json",
    "src/pitch_bootstrap.py",
    "src/pitch/__init__.py",
    "src/pitch/__main__.py",
    "src/pitch/cli.py",
]

SETUP_REQUIRED_PATHS = COMMON_REQUIRED_PATHS

VERIFY_REQUIRED_PATHS = COMMON_REQUIRED_PATHS

INSTALLER_SEARCH_ROOTS = (
    ASSET_ROOT,
    ASSET_ROOT / "windows",
    ASSET_ROOT / "linux",
    ROOT / "downloads",
    Path.home() / "Downloads",
    Path.home() / "downloads",
)

CORE_WINDOWS_INSTALLERS = [
    ("HlaStarterKit", ASSET_ROOT / "windows" / "HlaStarterKit_v1.0.2_windows64.exe"),
    ("PitchVisualOMT", ASSET_ROOT / "windows" / "PitchVisualOMTFree_v2.7.0_windows64.exe"),
]

LEGACY_WINDOWS_INSTALLER = (
    "prti1516e-free",
    ASSET_ROOT / "windows" / "prti1516e-free_5_5_10_windows32.exe",
)

CORE_LINUX_INSTALLERS = [
    ("HlaStarterKit", ASSET_ROOT / "linux" / "HlaStarterKit_v1.0.2_linux64.sh"),
    ("PitchVisualOMT", ASSET_ROOT / "linux" / "PitchVisualOMTFree_v2.7.0_linux64.sh"),
]

SETUP_WINDOWS_SPECS = [
    InstallSpec("hlastarterkit", "HlaStarterKit", ASSET_ROOT / "windows" / "HlaStarterKit_v1.0.2_windows64.exe"),
    InstallSpec("pitchvisualomt", "PitchVisualOMT", ASSET_ROOT / "windows" / "PitchVisualOMTFree_v2.7.0_windows64.exe"),
]

SETUP_WINDOWS_LEGACY_SPEC = InstallSpec(
    "prti1516e",
    "prti1516e-free",
    ASSET_ROOT / "windows" / "prti1516e-free_5_5_10_windows32.exe",
)

SETUP_LINUX_SPECS = [
    InstallSpec("hlastarterkit", "HlaStarterKit", ASSET_ROOT / "linux" / "HlaStarterKit_v1.0.2_linux64.sh"),
    InstallSpec("pitchvisualomt", "PitchVisualOMT", ASSET_ROOT / "linux" / "PitchVisualOMTFree_v2.7.0_linux64.sh"),
    InstallSpec("prti1516e", "prti1516e-free", ASSET_ROOT / "linux" / "prti1516e-free_5_5_10_linux64.sh"),
]

WINDOWS_INSTALLATION_HINTS = {
    "HlaStarterKit": ("hla starter kit", "hlastarterkit"),
    "PitchVisualOMT": ("pitch visual omt", "pitchvisualomt"),
    "prti1516e-free": ("prti1516e", "prti1516e-free"),
}

WINDOWS_COMPONENT_KEYS = {
    "HlaStarterKit": "hlastarterkit",
    "PitchVisualOMT": "pitchvisualomt",
    "prti1516e-free": "prti1516e",
}

WINDOWS_RUNTIME_LAUNCHERS = {
    "hlastarterkit": (
        "federates/simulationmanager/bin/simulationmanager.bat",
        "federates/mapviewer/bin/mapviewer.bat",
        "federates/carsimj/bin/carsimj.bat",
        "federates/carsimc/bin/carsimc_x64.bat",
    ),
    "pitchvisualomt": (
        "bin/PitchVisualOMTFree.exe",
        "bin/PitchVisualOMTFree.bat",
        "PitchVisualOMTFree.exe",
    ),
    "prti1516e": (
        "bin/Start pRTI Service.bat",
        "bin/pRTI1516e-nogui.bat",
        "bin/pRTI1516e.bat",
    ),
}

LINUX_INSTALLATION_HINTS = {
    "hlastarterkit": {
        "labels": ("hla starter kit", "hlastarterkit"),
        "roots": (
            Path.home(),
            Path.home() / ".local" / "share",
            Path("/opt"),
            Path("/usr/local"),
        ),
        "names": ("HlaStarterKit", "HlaStarterKit_v1.0.2", "HLA Starter Kit", "hla-starter-kit"),
        "launchers": ("bin/HlaStarterKit", "bin/HlaStarterKit.sh", "HlaStarterKit", "HlaStarterKit.sh"),
    },
    "pitchvisualomt": {
        "labels": ("pitch visual omt", "pitchvisualomt", "pitchvisualomtfree"),
        "roots": (
            Path.home(),
            Path.home() / ".local" / "share",
            Path("/opt"),
            Path("/usr/local"),
        ),
        "names": ("PitchVisualOMT", "PitchVisualOMTFree", "PitchVisualOMTFree_v2.7.0", "pitch-visual-omt"),
        "launchers": ("bin/PitchVisualOMTFree", "bin/PitchVisualOMTFree.sh", "PitchVisualOMTFree", "PitchVisualOMTFree.sh"),
    },
    "prti1516e": {
        "labels": ("prti1516e", "prti1516e-free", "pitch prti"),
        "roots": (
            Path.home(),
            Path.home() / ".local" / "share",
            Path("/opt"),
            Path("/usr/local"),
        ),
        "names": ("prti1516e", "prti1516e-free", "pRTI1516e", "pRTI1516e-free"),
        "launchers": (
            "bin/pRTI1516e-nogui",
            "bin/pRTI1516e-nogui.sh",
            "bin/pRTI1516e",
            "bin/pRTI1516e.sh",
            "bin/Start pRTI Service",
            "bin/Start pRTI Service.sh",
        ),
    },
}

LINUX_RUNTIME_LAUNCHERS = {
    "hlastarterkit": (
        "federates/simulationmanager/bin/simulationmanager.sh",
        "federates/mapviewer/bin/mapviewer.sh",
        "federates/carsimj/bin/carsimj.sh",
        "federates/carsimc/bin/carsimc_x64.sh",
    ),
    "pitchvisualomt": (
        "bin/PitchVisualOMTFree",
        "bin/PitchVisualOMTFree.sh",
        "PitchVisualOMTFree",
    ),
    "prti1516e": (
        "bin/pRTI1516e-nogui",
        "bin/pRTI1516e-nogui.sh",
        "bin/pRTI1516e",
        "bin/pRTI1516e.sh",
        "bin/Start pRTI Service",
        "bin/Start pRTI Service.sh",
    ),
}

def _route_specs() -> list[RouteSpec]:
    return [
        RouteSpec("native", "Native", "Run directly on the current operating system."),
        RouteSpec("wsl", "WSL", "Run through WSL on Windows with Linux installers and Linux launcher discovery."),
        RouteSpec("docker", "Docker", "Run inside a Linux container through Docker Compose."),
    ]


def _route_available(route_name: str) -> bool:
    if route_name == "native":
        return True
    if route_name == "wsl":
        return _has_command("wsl.exe")
    if route_name == "docker":
        return _docker_compose_available()
    return False


def _default_route_name() -> str:
    if _is_macos_platform():
        return "native"
    return "native"


def _default_route_reason() -> str:
    if _is_windows_platform():
        return "Windows now stays on native execution by default."
    if _is_macos_platform():
        return "macOS stays on native execution by default."
    return "Native execution is the default on this system."


def _route_summary(route_name: str) -> str:
    if route_name == "native":
        return "Direct host execution."
    if route_name == "wsl":
        return "Windows host -> WSL Linux shell."
    if route_name == "docker":
        return "Docker Compose containerized execution."
    return "Unknown route."


def _print_route_visibility(*, include_wsl_distros: bool = False) -> None:
    print("Route options:")
    for spec in _route_specs():
        availability = "available" if _route_available(spec.name) else "unavailable"
        print(f"  {spec.name}: {availability} - {spec.description}")
    print(f"  recommended: {_default_route_name()} - {_default_route_reason()}")
    print("  docker profiles: future (default), hla4")
    if include_wsl_distros:
        distros = _wsl_distribution_names()
        if distros:
            numbered = ", ".join(f"{index + 1}: {name}" for index, name in enumerate(distros))
            print(f"  WSL distros: {numbered}")
            default_distro = _wsl_default_distribution_name()
            if default_distro:
                print(f"  WSL default distro: {default_distro}")
            print("  WSL default: the configured default distro unless --wsl-distro is set")
            selected = _route_context_detail()
            if selected:
                print(f"  WSL selected: {selected}")
        else:
            print("  WSL distros: none detected")


def _route_context_name() -> str | None:
    value = os.environ.get("PITCH_ROUTE_CONTEXT", "").strip().lower()
    return value or None


def _route_context_detail() -> str | None:
    route_name = _route_context_name()
    if route_name == "wsl":
        distro = os.environ.get("PITCH_WSL_DISTRO", "").strip()
        return distro or None
    if route_name == "docker":
        profile = os.environ.get("PITCH_DOCKER_PROFILE", "").strip()
        return profile or None
    return None


def _print_active_route_banner() -> None:
    route_name = _route_context_name()
    if route_name in {"wsl", "docker"}:
        label = route_name.upper()
        detail = _route_context_detail()
        if detail:
            print(f"Selected route: {label} ({detail}; {_route_summary(route_name)})")
        else:
            print(f"Selected route: {label} ({_route_summary(route_name)})")


def _wsl_command_path(path: Path) -> str:
    value = str(path)
    if _looks_like_windows_path(value):
        return _translate_windows_path(value).as_posix()
    return Path(value).as_posix()


def _quote_posix_args(args: list[str]) -> str:
    return shlex.join(args)


def _wsl_distribution_names() -> list[str]:
    if not _has_command("wsl.exe"):
        return []

    try:
        completed = subprocess.run(["wsl.exe", "-l", "-q"], check=False, capture_output=True, text=True)
    except OSError:
        return []

    output = getattr(completed, "stdout", "") or ""
    names: list[str] = []
    for raw_line in output.splitlines():
        name = raw_line.strip().lstrip("*").strip()
        if name and name not in names:
            names.append(name)
    return names


def _wsl_default_distribution_name() -> str | None:
    if not _has_command("wsl.exe"):
        return None

    try:
        completed = subprocess.run(["wsl.exe", "-l", "-q"], check=False, capture_output=True, text=True)
    except OSError:
        return None

    output = getattr(completed, "stdout", "") or ""
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.startswith("*"):
            name = line.lstrip("*").strip()
            return name or None
    return None


def _resolve_wsl_distro_selection(selection: str | None, available_distros: list[str] | None = None) -> str | None:
    if selection is None:
        return None

    raw = selection.strip()
    if not raw or raw.lower() == "default":
        return None

    distros = available_distros if available_distros is not None else _wsl_distribution_names()
    if raw.isdigit():
        index = int(raw) - 1
        if 0 <= index < len(distros):
            return distros[index]
        raise RuntimeError(f"WSL distro index {raw} is out of range.")

    for distro in distros:
        if distro.lower() == raw.lower():
            return distro

    if distros:
        raise RuntimeError(f"WSL distro '{selection}' is not installed. Available distros: {', '.join(distros)}")
    return raw


def _translate_route_args_for_wsl(pitch_args: list[str]) -> list[str]:
    translated: list[str] = []
    for arg in pitch_args:
        if _looks_like_windows_path(arg):
            translated.append(_wsl_command_path(_translate_windows_path(arg)))
        else:
            translated.append(arg)
    return translated


def _docker_compose_file() -> Path:
    return ROOT / "docker" / "compose.yml"


def _docker_env_path() -> Path:
    override = os.environ.get("PITCH_DOCKER_ENV_FILE", "").strip()
    if override:
        return _coerce_env_path(override)
    return DOCKER_ENV_PATH


def _vendor_docker_env_path() -> Path:
    return _vendor_docker_env_path_impl()


def _vendor_docker_settings_root() -> Path:
    return _vendor_docker_settings_root_impl()


def _vendor_docker_build_root() -> Path:
    return _vendor_docker_build_root_impl()


def _docker_service_name() -> str:
    profile = os.environ.get("PITCH_DOCKER_PROFILE", "future").strip().lower()
    if profile == "hla4":
        return "pitch-hla4"
    return "pitch-future"


def _vendor_docker_install_root() -> Path | None:
    return _vendor_docker_install_root_impl()


def _docker_compose_available() -> bool:
    docker_command = _resolved_docker_command()
    if docker_command is None:
        return False
    try:
        completed = subprocess.run([docker_command, "compose", "version"], check=False, capture_output=True, text=True)
    except OSError:
        return False
    return completed.returncode == 0


def _route_payload_command(pitch_args: list[str], route_name: str, wsl_distro: str | None = None) -> list[str]:
    if route_name == "native":
        return []

    if route_name == "wsl":
        pitch_args = _translate_route_args_for_wsl(pitch_args)
    if route_name == "docker":
        docker_command = _resolved_docker_command()
        if docker_command is None:
            raise RuntimeError("Could not find the Docker CLI. Install Docker Desktop or Docker Engine first.")
        env_file = _docker_env_path()
        command = [
            docker_command,
            "compose",
            "-f",
            str(_docker_compose_file()),
            "run",
            "--rm",
            "--build",
            _docker_service_name(),
        ]
        if env_file.exists():
            command[2:2] = ["--env-file", str(env_file)]
        command.extend(pitch_args)
        return command

    run_command = _quote_posix_args(["python3", "-m", "pitch", *pitch_args]) if pitch_args else _quote_posix_args(["python3", "-m", "pitch"])
    shell_command = run_command
    if route_name == "wsl":
        command = ["wsl.exe"]
        if wsl_distro:
            command.extend(["-d", wsl_distro])
        command.extend([
            "--cd",
            _wsl_command_path(ROOT),
            "bash",
            "-lc",
            shell_command,
        ])
        return command

    volume = f"{ROOT.as_posix()}:/work"
    return [
        "docker",
        "run",
        "--rm",
        "-i",
        "-v",
        volume,
        "-w",
        "/work",
        "python:3.12",
        "sh",
        "-lc",
        shell_command,
    ]


def _docker_preflight_check() -> bool:
    docker_status, docker_detail, docker_ok = _docker_preflight_status()
    if docker_ok:
        return True
    print(docker_detail, file=sys.stderr)
    return False


def _docker_preflight_status() -> tuple[str, str, bool]:
    docker_command = _resolved_docker_command()
    if docker_command is None:
        return ("missing", "Could not find the Docker CLI. Install Docker Desktop or Docker Engine first.", False)

    try:
        compose = subprocess.run([docker_command, "compose", "version"], check=False, capture_output=True, text=True)
    except OSError as exc:
        return ("missing", f"Could not reach the Docker CLI to verify Docker Compose: {exc}", False)

    if compose.returncode == 0:
        try:
            completed = subprocess.run([docker_command, "info"], check=False, capture_output=True, text=True)
        except OSError as exc:
            return ("blocked", f"Docker Compose is reachable, but the Docker daemon is unavailable: {exc}", False)
        if completed.returncode == 0:
            return ("ok", "Docker daemon and Docker Compose are reachable.", True)
        output = "\n".join(
            part.strip()
            for part in (getattr(completed, "stdout", "") or "", getattr(completed, "stderr", "") or "")
            if part and part.strip()
        )
        normalized = output.lower()
        if "permission denied while trying to connect to the docker api" in normalized or "docker_engine" in normalized:
            return (
                "blocked",
                "Docker Desktop is reachable, but this session cannot access the Docker API pipe.\n"
                "Try rerunning from an elevated PowerShell session or make sure Docker Desktop is running.",
                False,
            )

        if output:
            return ("blocked", f"Docker is installed, but the daemon is not responding cleanly.\n{output}", False)
        return ("blocked", "Docker is installed, but the daemon is not responding cleanly.", False)

    compose_output = "\n".join(
        part.strip()
        for part in (getattr(compose, "stdout", "") or "", getattr(compose, "stderr", "") or "")
        if part and part.strip()
    )
    if compose_output:
        return ("blocked", f"Docker daemon is reachable, but Docker Compose is unavailable.\n{compose_output}", False)
    return ("blocked", "Docker daemon is reachable, but Docker Compose is unavailable.", False)


def _run_route_command(route_name: str, pitch_args: list[str], wsl_distro: str | None = None) -> int:
    if route_name == "native":
        return main(pitch_args)

    if not _route_available(route_name):
        print(f"Route '{route_name}' is not available on this machine.", file=sys.stderr)
        return 1

    if route_name == "docker" and not _docker_preflight_check():
        return 1

    resolved_wsl_distro = wsl_distro
    if route_name == "wsl":
        resolved_wsl_distro = _resolve_wsl_distro_selection(wsl_distro)
        if resolved_wsl_distro is None:
            resolved_wsl_distro = _wsl_default_distribution_name()

    command = _route_payload_command(pitch_args, route_name, wsl_distro=resolved_wsl_distro)
    route_env = os.environ.copy()
    route_env.update(_route_payload_env(route_name, wsl_distro=resolved_wsl_distro, docker_env_file=DOCKER_ENV_PATH))
    completed = subprocess.run(command, check=False, env=route_env)
    return int(completed.returncode)


def _route_payload_env(route_name: str, wsl_distro: str | None = None, docker_env_file: Path | None = None) -> dict[str, str]:
    payload = {"PITCH_ROUTE_CONTEXT": route_name}
    if route_name == "native":
        payload["PITCH_PORT"] = str(route_rti_port("route-native"))
        payload["PITCH_PORT_PROFILE"] = "route-native"
        return payload
    if route_name == "wsl":
        if wsl_distro:
            payload["PITCH_WSL_DISTRO"] = wsl_distro
        payload["PITCH_PORT"] = str(route_rti_port("route-wsl"))
        payload["PITCH_PORT_PROFILE"] = "route-wsl"
        return payload
    if route_name == "docker":
        payload["PITCH_DOCKER_PROFILE"] = os.environ.get("PITCH_DOCKER_PROFILE", "future").strip().lower() or "future"
        payload["PITCH_USER_DATA_ROOT"] = str(USER_DATA_ROOT)
        payload["PITCH_INSTALLER_DROP_ROOT"] = str(INSTALLER_DROP_ROOT)
        payload["PITCH_PREFLIGHT_ARTIFACT_ROOT"] = str(PREFLIGHT_ARTIFACT_ROOT)
        payload["PITCH_DOCKER_ENV_FILE"] = str(docker_env_file or _docker_env_path())
        payload["PITCH_PORT"] = str(route_rti_port("route-docker"))
        payload["PITCH_PORT_PROFILE"] = "route-docker"
    return payload


def _build_setup_argv(args: argparse.Namespace, route_name: str = "native") -> list[str]:
    argv = ["setup", "--route", route_name]
    if getattr(args, "include_legacy_rti", False):
        argv.append("--include-legacy-rti")
    if getattr(args, "probe_ports", False):
        argv.append("--probe-ports")
    if getattr(args, "strict_probe", False):
        argv.append("--strict-probe")
    if getattr(args, "force", False):
        argv.append("--force")
    if getattr(args, "silent_install", False):
        argv.append("--silent-install")
    if getattr(args, "ports_config", None):
        argv.extend(["--ports-config", str(args.ports_config)])
    if getattr(args, "source", None):
        argv.extend(["--source", str(args.source)])
    if getattr(args, "enable_hla4_preview", False):
        argv.append("--enable-hla4-preview")
    if getattr(args, "disable_hla4_preview", False):
        argv.append("--disable-hla4-preview")
    return argv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pitch", description="Pitch HLA starter bundle CLI.")
    subparsers = parser.add_subparsers(dest="command")

    setup_parser = subparsers.add_parser("setup", help="Install the core Pitch stack.")
    setup_parser.add_argument("--include-legacy-rti", action="store_true", help="Install the legacy Windows RTI package too.")
    setup_parser.add_argument("--probe-ports", action="store_true", help="Probe configured ports after installation.")
    setup_parser.add_argument("--strict-probe", action="store_true", help="Fail if any configured ports are closed.")
    setup_parser.add_argument("--force", action="store_true", help="Rerun installers even if the bundle appears installed.")
    setup_parser.add_argument("--silent-install", action="store_true", help="Try the vendor installers in quiet mode.")
    setup_parser.add_argument("--route", choices=["native", "wsl", "docker", "auto"], default="native", help="Choose how setup is executed.")
    setup_parser.add_argument("--wsl-distro", help="Select a WSL distribution when route is wsl.")
    setup_preview_group = setup_parser.add_mutually_exclusive_group()
    setup_preview_group.add_argument("--enable-hla4-preview", action="store_true", help="Enable HLA 4 Preview in the discovered CRC settings after setup.")
    setup_preview_group.add_argument("--disable-hla4-preview", action="store_true", help="Disable HLA 4 Preview in the discovered CRC settings after setup.")
    setup_parser.add_argument("--ports-config", default=str(ASSET_ROOT / "ports.conf"), help="Port probe configuration file.")
    setup_parser.add_argument("--source", help="Folder to scan and stage into the writable installer cache before setup.")
    setup_parser.set_defaults(handler=handle_setup)

    verify_parser = subparsers.add_parser("verify", help="Verify the bundle and checksum manifest.")
    verify_parser.add_argument("--quiet", action="store_true", help="Only report failures.")
    verify_parser.add_argument("--rti-smoke", action="store_true", help="Also run the installed RTI smoke test when available.")
    verify_parser.set_defaults(handler=handle_verify)

    preflight_parser = subparsers.add_parser("preflight", help="Check Docker, bundle, RTI, and port readiness.")
    preflight_parser.add_argument("--config", default=str(ASSET_ROOT / "ports.conf"), help="Port probe configuration file.")
    preflight_parser.add_argument("--json", action="store_true", help="Print the preflight report as JSON.")
    preflight_parser.add_argument("--json-file", type=Path, help="Write the preflight report JSON to this file.")
    preflight_parser.set_defaults(handler=handle_preflight)

    probe_parser = subparsers.add_parser("probe", help="Probe configured Pitch RTI ports.")
    probe_parser.add_argument("--config", default=str(ASSET_ROOT / "ports.conf"), help="Port probe configuration file.")
    probe_parser.add_argument("--strict", action="store_true", help="Return a non-zero exit code if any ports are closed.")
    probe_parser.set_defaults(handler=handle_probe)

    doctor_parser = subparsers.add_parser("doctor", help="Print the Python-first workflow and detected install roots.")
    doctor_parser.set_defaults(handler=handle_doctor)

    status_parser = subparsers.add_parser("status", help="Show install and port readiness status.")
    status_parser.add_argument("--config", default=str(ASSET_ROOT / "ports.conf"), help="Port probe configuration file.")
    status_parser.add_argument("--strict", action="store_true", help="Return a non-zero exit code if any ports are closed.")
    status_parser.set_defaults(handler=handle_status)

    config_parser = subparsers.add_parser("config", help="Inspect or generate local config files.")
    config_subparsers = config_parser.add_subparsers(dest="config_command")
    config_parser.set_defaults(handler=handle_config, parser=config_parser)

    config_show_parser = config_subparsers.add_parser("show", help="Show artifacts/.pitch-install-roots.json or the detected roots.")
    config_show_parser.set_defaults(handler=handle_config_show)

    config_init_parser = config_subparsers.add_parser("init", help="Generate artifacts/.pitch-install-roots.json from detected installs.")
    config_init_parser.add_argument("--force", action="store_true", help="Overwrite an existing install roots config.")
    config_init_parser.set_defaults(handler=handle_config_init)

    config_assets_parser = config_subparsers.add_parser("assets", help="Show the writable asset and installer drop locations.")
    config_assets_parser.set_defaults(handler=handle_config_assets)

    assets_parser = subparsers.add_parser("assets", help="Manage the writable installer drop folder.")
    assets_subparsers = assets_parser.add_subparsers(dest="assets_command")
    assets_parser.set_defaults(handler=handle_assets, parser=assets_parser)

    assets_show_parser = assets_subparsers.add_parser("show", help="Show the writable installer drop folder.")
    assets_show_parser.set_defaults(handler=handle_assets_show)

    assets_init_parser = assets_subparsers.add_parser("init", help="Create the writable installer drop folder.")
    assets_init_parser.set_defaults(handler=handle_assets_init)

    assets_open_parser = assets_subparsers.add_parser("open", help="Open the writable installer drop folder.")
    assets_open_parser.set_defaults(handler=handle_assets_open)

    assets_import_parser = assets_subparsers.add_parser("import", help="Discover recognized Pitch files in a folder and copy them into the writable cache.")
    assets_import_parser.add_argument("source", help="Folder containing downloaded Pitch files.")
    assets_import_parser.add_argument("--force", action="store_true", help="Overwrite existing staged files.")
    assets_import_parser.set_defaults(handler=handle_assets_import)

    assets_verify_parser = assets_subparsers.add_parser("verify", help="Verify the staged downloaded artifacts against their local checksum manifest.")
    assets_verify_parser.set_defaults(handler=handle_assets_verify)

    download_parser = subparsers.add_parser("download", help="Prepare Pitch free-download autofill helpers.")
    download_subparsers = download_parser.add_subparsers(dest="download_command")
    download_parser.set_defaults(handler=handle_download, parser=download_parser)

    download_init_parser = download_subparsers.add_parser("init", help="Write .pitch-download-contact.json from an email and defaults.")
    download_init_parser.add_argument("--email", required=True, help="Destination email address for the Pitch download form.")
    download_init_parser.add_argument("--force", action="store_true", help="Overwrite an existing download contact file.")
    download_init_parser.set_defaults(handler=handle_download_init)

    download_bookmarklet_parser = download_subparsers.add_parser("bookmarklet", help="Print a browser-side autofill bookmarklet.")
    download_bookmarklet_parser.add_argument("--email", help="Override the destination email address for this output.")
    download_bookmarklet_parser.set_defaults(handler=handle_download_bookmarklet)

    download_script_parser = download_subparsers.add_parser("script", help="Print the standalone browser autofill script.")
    download_script_parser.add_argument("--email", help="Override the destination email address for this output.")
    download_script_parser.set_defaults(handler=handle_download_script)

    download_fetch_parser = download_subparsers.add_parser("fetch", help="Download a file from a URL into the current directory or a chosen path.")
    download_fetch_parser.add_argument("--url", required=True, help="Direct file URL to download.")
    download_fetch_parser.add_argument("--output", help="Write the download to this path instead of the URL filename.")
    download_fetch_parser.add_argument("--filename", help="Pick a specific installer filename from a page URL.")
    download_fetch_parser.add_argument("--platform", choices=["auto", "windows64", "windows32", "linux64", "linux32", "mac"], default="auto", help="Pick an installer variant from a page URL.")
    download_fetch_parser.set_defaults(handler=handle_download_fetch)

    download_submit_parser = download_subparsers.add_parser("submit", help="Submit the Pitch free-download request directly.")
    download_submit_parser.add_argument("--email", help="Override the destination email address for this submission.")
    download_submit_parser.add_argument("--first-name", "--firstname", dest="first_name", help="Override the first name for this submission.")
    download_submit_parser.add_argument("--last-name", "--lastname", dest="last_name", help="Override the last name for this submission.")
    download_submit_parser.add_argument("--title", help="Override the job title for this submission.")
    download_submit_parser.add_argument("--organization", help="Override the organization name for this submission.")
    download_submit_parser.add_argument("--organization-type", choices=["Company", "Government", "Academia", "Other"], help="Override the organization type for this submission.")
    download_submit_parser.add_argument("--product", action="append", dest="products", help="Add a product to request. Repeat for multiple products.")
    download_submit_parser.add_argument("--newsletter", action="store_true", help="Subscribe the contact to the Pitch newsletter.")
    download_submit_parser.add_argument("--dry-run", action="store_true", help="Print the submission payload without sending it.")
    download_submit_parser.set_defaults(handler=handle_download_submit)

    route_parser = subparsers.add_parser("route", help="Inspect or run Pitch commands through native, WSL, or Docker routes.")
    route_subparsers = route_parser.add_subparsers(dest="route_command")
    route_parser.set_defaults(handler=handle_route)

    route_show_parser = route_subparsers.add_parser("show", help="Show the available routes and the default recommendation.")
    route_show_parser.set_defaults(handler=handle_route_show)

    route_run_parser = route_subparsers.add_parser("run", help="Run a Pitch command through a selected route.")
    route_run_parser.add_argument("route", choices=["native", "wsl", "docker", "auto"], help="Route to use for the command.")
    route_run_parser.add_argument("--wsl-distro", help="Select a WSL distribution when route is wsl.")
    route_run_parser.add_argument("pitch_args", nargs=argparse.REMAINDER, help="Pitch command and arguments to run.")
    route_run_parser.set_defaults(handler=handle_route_run)

    docker_parser = subparsers.add_parser("docker", help="Inspect or generate Docker Compose helpers for Pitch.")
    docker_subparsers = docker_parser.add_subparsers(dest="docker_command")
    docker_parser.set_defaults(handler=handle_docker, parser=docker_parser)

    docker_init_parser = docker_subparsers.add_parser("init", help="Write the vendor Docker env file and settings overlay.")
    docker_init_parser.add_argument("--force", action="store_true", help="Overwrite an existing env file and vendor settings overlay.")
    docker_init_parser.add_argument("--enable-hla4-preview", action="store_true", help="Enable HLA 4 Preview in the copied CRC settings.")
    docker_init_parser.set_defaults(handler=handle_docker_init)

    docker_up_parser = docker_subparsers.add_parser("up", help="Start the vendor pRTI container with Docker Compose.")
    docker_up_parser.set_defaults(handler=handle_docker_up)

    docker_restart_parser = docker_subparsers.add_parser("restart", help="Restart the vendor pRTI container and rerun the smoke check.")
    docker_restart_parser.set_defaults(handler=handle_docker_restart)

    docker_down_parser = docker_subparsers.add_parser("down", help="Stop the vendor pRTI container with Docker Compose.")
    docker_down_parser.set_defaults(handler=handle_docker_down)

    docker_smoke_parser = docker_subparsers.add_parser("smoke", help="Check whether the vendor CRC is reachable on its RTI port.")
    docker_smoke_parser.add_argument("--timeout-seconds", type=float, default=60.0, help="How long to wait for the vendor CRC port to respond.")
    docker_smoke_parser.add_argument("--interval-seconds", type=float, default=1.0, help="How long to sleep between reachability checks.")
    docker_smoke_parser.set_defaults(handler=handle_docker_smoke)

    docker_ps_parser = docker_subparsers.add_parser("ps", help="Show the vendor Docker container status.")
    docker_ps_parser.add_argument("--all", action="store_true", help="Include stopped containers.")
    docker_ps_parser.set_defaults(handler=handle_docker_ps)

    docker_logs_parser = docker_subparsers.add_parser("logs", help="Print logs from the vendor CRC container.")
    docker_logs_parser.add_argument("--tail", type=int, help="Print only the last N log lines.")
    docker_logs_parser.add_argument("--follow", action="store_true", help="Follow the container log output.")
    docker_logs_parser.add_argument("--service", help="Override the Docker Compose service name.")
    docker_logs_parser.set_defaults(handler=handle_docker_logs)

    docker_inspect_parser = docker_subparsers.add_parser("inspect", help="Show the vendor Docker status summary and container table.")
    docker_inspect_parser.set_defaults(handler=handle_docker_inspect)

    docker_status_parser = docker_subparsers.add_parser("status", help="Show the vendor Docker setup paths.")
    docker_status_parser.set_defaults(handler=handle_docker_status)

    settings_parser = subparsers.add_parser("settings", help="Discover CRC settings files and HLA 4 Preview state.")
    settings_subparsers = settings_parser.add_subparsers(dest="settings_command")
    settings_parser.set_defaults(handler=handle_settings, parser=settings_parser)

    settings_show_parser = settings_subparsers.add_parser("show", help="Show the discovered CRC settings and HLA 4 Preview state.")
    settings_show_parser.set_defaults(handler=handle_settings_show)

    settings_set_parser = settings_subparsers.add_parser("set", help="Set a discovered CRC settings key across all discovered CRC settings files.")
    settings_set_parser.add_argument("key", help="The settings key to write, such as CRC.enableHla4PreviewFeatures.")
    settings_set_parser.add_argument("value", help="The value to write for the settings key.")
    settings_set_parser.set_defaults(handler=handle_settings_set)

    rti_parser = subparsers.add_parser("rti", help="Run RTI-specific checks.")
    rti_subparsers = rti_parser.add_subparsers(dest="rti_command")
    rti_parser.set_defaults(handler=handle_rti)

    rti_smoke_parser = rti_subparsers.add_parser("smoke", help="Launch the installed RTI console and verify it answers HELP.")
    rti_smoke_subparsers = rti_smoke_parser.add_subparsers(dest="smoke_command")
    rti_smoke_parser.set_defaults(handler=handle_rti_smoke)

    rti_smoke_chat_parser = rti_smoke_subparsers.add_parser("chat", help="Launch two chat federates against the installed RTI.")
    rti_smoke_chat_parser.add_argument(
        "--variant",
        choices=["auto", "java-hla4", "java-hla4-fedpro", "cpp-hla4"],
        default="auto",
        help="Choose which chat sample family to use.",
    )
    rti_smoke_chat_parser.add_argument("--list", action="store_true", help="List the discovered chat sample variants and exit.")
    rti_smoke_chat_parser.set_defaults(handler=handle_rti_smoke_chat)

    start_parser = subparsers.add_parser("start", help="Open the interactive launcher menu or a direct target.")
    start_parser.add_argument(
        "target",
        nargs="?",
        default="menu",
        help="Target to launch: menu, hlastarterkit, pitchvisualomt, prti1516e, docs, plugin, or root.",
    )
    start_parser.add_argument("--port", type=_port_number, help="Probe a single localhost port after launching the target.")
    start_parser.add_argument("--probe-ports", action="store_true", help="Probe configured ports after launching the target.")
    start_parser.add_argument("--strict-probe", action="store_true", help="Fail if any configured ports are closed.")
    start_preview_group = start_parser.add_mutually_exclusive_group()
    start_preview_group.add_argument("--enable-hla4-preview", action="store_true", help="Enable HLA 4 Preview in the discovered CRC settings before launch.")
    start_preview_group.add_argument("--disable-hla4-preview", action="store_true", help="Disable HLA 4 Preview in the discovered CRC settings before launch.")
    start_parser.add_argument("--ports-config", default=str(ASSET_ROOT / "ports.conf"), help="Port probe configuration file.")
    start_parser.set_defaults(handler=handle_start)

    return parser


def _verify_paths() -> list[str]:
    return verify_paths_exist(ROOT, VERIFY_REQUIRED_PATHS)


def _installer_manifest_path(root: Path | None = None) -> Path:
    base = root if root is not None else resolve_installer_drop_root()
    return base / INSTALLER_CHECKSUM_MANIFEST_NAME


def _checksum_tracked_artifact_paths(root: Path) -> list[Path]:
    if not root.exists() or not root.is_dir():
        return []

    tracked: list[Path] = []
    for candidate in root.iterdir():
        if candidate.is_file() and candidate.name in CHECKSUM_TRACKED_FILENAMES:
            tracked.append(candidate)
    return sorted(tracked, key=lambda path: path.name.lower())


def _write_installer_checksum_manifest(root: Path) -> Path:
    manifest_path = _installer_manifest_path(root)
    entries: list[str] = []
    for path in _checksum_tracked_artifact_paths(root):
        entries.append(f"{sha256_file(path)}  {path.name}")

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("\n".join(entries) + ("\n" if entries else ""), encoding="utf-8")
    return manifest_path


def _verify_installer_checksum_manifest() -> list[str]:
    manifest_path = _installer_manifest_path()
    if not manifest_path.exists():
        return [f"Missing checksum manifest: {manifest_path.name}"]

    root = manifest_path.parent
    tracked_files = _checksum_tracked_artifact_paths(root)
    if not tracked_files:
        return [f"No tracked downloaded artifacts were found in: {root}"]

    failures = verify_manifest(root, manifest_path)
    if failures:
        return failures

    return []


def _verify_setup_paths() -> list[str]:
    return verify_paths_exist(ROOT, SETUP_REQUIRED_PATHS)


def _state_file() -> Path:
    return install_state_path(ROOT)


def _fresh_state() -> dict[str, object]:
    return {
        "version": 1,
        "bundle_fingerprint": bundle_fingerprint(ROOT),
        "platform": _platform_system(),
        "components": {},
        "checks": {},
    }


def _load_state() -> dict[str, object]:
    try:
        state = load_install_state(_state_file())
    except (OSError, ValueError, json.JSONDecodeError):
        return _fresh_state()

    if not isinstance(state, dict):
        return _fresh_state()

    if state.get("bundle_fingerprint") != bundle_fingerprint(ROOT):
        return _fresh_state()

    components = state.get("components")
    if not isinstance(components, dict):
        state["components"] = {}

    return state


def _save_state(state: dict[str, object]) -> None:
    save_install_state(_state_file(), state)


def _preflight_artifact_dir() -> Path:
    raw = os.environ.get("PITCH_PREFLIGHT_ARTIFACT_ROOT")
    if raw:
        return Path(raw).expanduser()
    return PREFLIGHT_ARTIFACT_ROOT


def _preflight_artifact_path() -> Path:
    return _preflight_artifact_dir() / PREFLIGHT_ARTIFACT_FILENAME


def _load_preflight_report() -> dict[str, object] | None:
    path = _preflight_artifact_path()
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _save_preflight_report(report: dict[str, object]) -> None:
    _write_json_file(_preflight_artifact_path(), report)


def _crc_settings_search_roots() -> list[Path]:
    roots: list[Path] = [
        USER_DATA_ROOT,
        INSTALLER_DROP_ROOT,
        ASSET_ROOT,
        ROOT,
        Path.home(),
    ]

    configured_roots = _configured_install_roots()
    prti_root = configured_roots.get("prti1516e")
    if prti_root is not None:
        roots.extend([prti_root, prti_root.parent])

    launcher = _discover_installed_runtime_launcher("prti1516e")
    if launcher is not None:
        roots.extend([launcher.parent, launcher.parent.parent, launcher.parent.parent.parent])

    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key not in seen:
            deduped.append(root)
            seen.add(key)
    return deduped


def _render_path(repo_root: Path, raw: str | None) -> str | None:
    if raw is None:
        return None

    path = Path(raw).expanduser()
    if not path.is_absolute():
        return path.as_posix()

    try:
        resolved = path.resolve()
    except OSError:
        resolved = path

    try:
        return resolved.relative_to(repo_root).as_posix()
    except ValueError:
        return resolved.as_posix()


def _mark_component_installed(component_key: str, label: str, source: str, detail: str) -> None:
    state = _load_state()
    components = state.setdefault("components", {})
    if not isinstance(components, dict):
        components = {}
        state["components"] = components

    components[component_key] = {
        "status": "installed",
        "label": label,
        "source": source,
        "detail": detail,
    }
    state["bundle_fingerprint"] = bundle_fingerprint(ROOT)
    state["platform"] = _platform_system()
    _save_state(state)


def _mark_rti_smoke_result(passed: bool, detail: str) -> None:
    state = _load_state()
    checks = state.setdefault("checks", {})
    if not isinstance(checks, dict):
        checks = {}
        state["checks"] = checks

    checks["rti_smoke"] = {
        "status": "passed" if passed else "failed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "detail": detail,
    }
    state["bundle_fingerprint"] = bundle_fingerprint(ROOT)
    state["platform"] = _platform_system()
    _save_state(state)


def _preflight_report(config_name: str | None = None) -> dict[str, object]:
    docker_status, docker_detail, docker_ok = _docker_preflight_status()
    bundle_failures = _verify_paths()
    bundle_ok = not bundle_failures
    launcher = _discover_installed_runtime_launcher("prti1516e")
    launcher_available = launcher is not None
    state = _load_state()
    checks = state.get("checks") if isinstance(state, dict) else None
    smoke_check = checks.get("rti_smoke") if isinstance(checks, dict) else None
    if isinstance(smoke_check, dict):
        smoke_status = str(smoke_check.get("status", "unknown")).lower()
        smoke_timestamp = str(smoke_check.get("timestamp", ""))
        smoke_detail = str(smoke_check.get("detail", "")).strip()
    else:
        smoke_status = "never"
        smoke_timestamp = ""
        smoke_detail = ""

    config_path = Path(config_name or str(ASSET_ROOT / "ports.conf"))
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    port_results = probe_targets(parse_ports_config(config_path))
    port_status = "ok"
    port_detail = "no ports configured"
    if port_results:
        if all(open_ for _, open_ in port_results):
            port_detail = ", ".join(
                f"{target.label or f'{target.host}:{target.port}'}={target.host}:{target.port}"
                for target, open_ in port_results
            )
        else:
            port_status = "blocked"
            blocked = [
                f"{target.label or f'{target.host}:{target.port}'}={target.host}:{target.port}"
                for target, open_ in port_results
                if not open_
            ]
            port_detail = ", ".join(blocked)

    bundle_detail = "ok" if bundle_ok else "; ".join(bundle_failures[:3])
    launcher_detail = str(launcher) if launcher is not None else "No installed Pitch RTI launcher was found."
    smoke_detail_value = smoke_detail or ("No RTI smoke test has been run yet." if launcher_available else "RTI launcher is unavailable.")

    checks_payload = [
        {
            "name": "docker",
            "ok": docker_ok,
            "status": docker_status,
            "detail": docker_detail,
        },
        {
            "name": "bundle",
            "ok": bundle_ok,
            "status": "ok" if bundle_ok else "blocked",
            "detail": bundle_detail,
        },
        {
            "name": "rti_launcher",
            "ok": launcher_available,
            "status": "available" if launcher_available else "missing",
            "detail": launcher_detail,
        },
        {
            "name": "rti_smoke",
            "ok": smoke_status == "passed",
            "status": smoke_status,
            "detail": smoke_detail_value,
            "timestamp": smoke_timestamp or None,
        },
        {
            "name": "ports",
            "ok": port_status == "ok",
            "status": port_status,
            "detail": port_detail,
        },
    ]

    environment = "ready"
    next_step = "run `pitch verify --rti-smoke` or `pitch start prti1516e`"
    if not docker_ok:
        environment = "docker-blocked"
        next_step = "fix Docker and rerun `pitch preflight`"
    elif not bundle_ok:
        environment = "bundle-blocked"
        next_step = "run `pitch verify` or restore the missing bundle files"
    elif not launcher_available:
        environment = "runtime-blocked"
        next_step = "run `pitch setup` to install the Pitch RTI"
    elif port_status != "ok":
        environment = "ports-blocked"
        next_step = "fix the configured ports and rerun `pitch preflight`"
    elif smoke_status == "failed":
        environment = "smoke-blocked"
        next_step = "rerun `pitch rti smoke` after fixing the RTI launcher"

    result = "ready"
    if environment != "ready":
        result = "blocked: fix the prerequisite(s) above and rerun"

    return {
        "tool": "pitch-preflight",
        "platform": _platform_system(),
        "environment": environment,
        "result": result,
        "checks": checks_payload,
        "rti": {
            "launcher": _render_path(ROOT, str(launcher) if launcher is not None else None),
            "smoke": {
                "status": smoke_status,
                "timestamp": smoke_timestamp or None,
                "detail": smoke_detail_value,
            },
        },
        "ports": {
            "config": _render_path(ROOT, str(config_path)),
            "targets": [
                {
                    "host": target.host,
                    "port": target.port,
                    "label": target.label,
                    "open": open_,
                }
                for target, open_ in port_results
            ],
        },
        "next_step": next_step,
        "exit_code": 0 if environment == "ready" else 1,
    }


def _state_installed_components() -> set[str]:
    state = _load_state()
    components = state.get("components")
    if not isinstance(components, dict):
        return set()

    installed: set[str] = set()
    for key, value in components.items():
        if not isinstance(value, dict):
            continue
        if value.get("status") == "installed":
            installed.add(str(key))
    return installed


def _windows_system_installed_components() -> set[str]:
    return set(detect_windows_installed_components(WINDOWS_INSTALLATION_HINTS))


def _linux_component_installed(spec: InstallSpec) -> bool:
    hints = LINUX_INSTALLATION_HINTS.get(spec.key)
    if hints is None:
        return False

    for root in hints["roots"]:
        for name in hints["names"]:
            candidate_root = root / name
            if not candidate_root.exists():
                continue

            for launcher in hints["launchers"]:
                if (candidate_root / launcher).exists():
                    return True
    return False


def _linux_system_installed_components() -> set[str]:
    return {spec.key for spec in SETUP_LINUX_SPECS if _linux_component_installed(spec)}


def _installed_components() -> set[str]:
    installed = set(_state_installed_components())
    system = _platform_system()
    if system == "Windows":
        installed.update(_windows_system_installed_components())
    elif system == "Linux":
        installed.update(_linux_system_installed_components())
    return installed


def _detected_install_roots() -> dict[str, Path]:
    system = _platform_system()
    roots: dict[str, Path] = {}

    if system == "Windows":
        discovered = discover_windows_install_locations(WINDOWS_INSTALLATION_HINTS)
        for component_name, paths in discovered.items():
            component_key = WINDOWS_COMPONENT_KEYS.get(component_name)
            if component_key is None or not paths:
                continue
            root = paths[0]
            roots[component_key] = root if root.is_dir() else root.parent
        return roots

    if system == "Linux":
        discovered = discover_linux_install_locations(
            {
                "hlastarterkit": LINUX_INSTALLATION_HINTS["hlastarterkit"]["roots"],
                "pitchvisualomt": LINUX_INSTALLATION_HINTS["pitchvisualomt"]["roots"],
            },
            LINUX_RUNTIME_LAUNCHERS,
        )
        for component_key, paths in discovered.items():
            if not paths:
                continue
            root = paths[0]
            roots[component_key] = root if root.is_dir() else root.parent
        return roots

    return roots


def _install_specs_for_system(include_legacy_rti: bool) -> list[InstallSpec]:
    system = _platform_system()
    if system == "Windows":
        specs = list(SETUP_WINDOWS_SPECS)
        if include_legacy_rti:
            specs.append(SETUP_WINDOWS_LEGACY_SPEC)
        return specs
    if system == "Linux":
        return list(SETUP_LINUX_SPECS)
    raise RuntimeError(f"Unsupported platform: {system}")


def _log_detected_installed(components: set[str]) -> None:
    if not components:
        return

    print("Detected existing components:")
    for component in sorted(components):
        print(f"  - {component}")


def _failures_to_stderr(failures: list[str]) -> None:
    for failure in failures:
        print(failure, file=sys.stderr)


def _probe_results(config_name: str):
    config_path = (ROOT / config_name).resolve()
    targets = parse_ports_config(config_path)
    results = probe_targets(targets)
    for target, open_ in results:
        state = "OPEN" if open_ else "CLOSED"
        print(f"{state}  {target.label} {target.host}:{target.port}")
    return results


def _port_number(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc

    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")

    return port


def _probe_results_for_start(args: argparse.Namespace):
    if args.port is not None:
        targets = [PortTarget(host="127.0.0.1", port=args.port, label=f"127.0.0.1:{args.port}")]
        results = probe_targets(targets)
        for target, open_ in results:
            state = "OPEN" if open_ else "CLOSED"
            print(f"{state}  {target.label} {target.host}:{target.port}")
        return results

    return _probe_results(args.ports_config)


def _platform_python_command() -> str:
    return "py -3" if _is_windows_platform() else "python3"


def _print_python_workflow() -> None:
    python_cmd = _platform_python_command()
    print("Python-first workflow:")
    print(f"  {python_cmd} -m pitch verify")
    print(f"  {python_cmd} -m pitch setup")
    print(f"  {python_cmd} -m pitch status")
    print(f"  {python_cmd} -m pitch probe")
    print(f"  {python_cmd} -m pitch start hlastarterkit --ports-config pitch/ports.conf --probe-ports")
    print(f"  {python_cmd} -m pitch start hlastarterkit --port 1516 --probe-ports")


def _write_json_file(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp_name = handle.name

    Path(temp_name).replace(path)


def _normalize_install_roots(paths: list[Path]) -> list[Path]:
    roots: list[Path] = []
    for path in paths:
        candidate = path if path.is_dir() else path.parent
        if candidate not in roots:
            roots.append(candidate)
    return roots


def _installer_search_roots() -> list[Path]:
    roots: list[Path] = []
    drop_root = resolve_installer_drop_root()
    if drop_root.exists():
        roots.append(drop_root)
    for path in INSTALLER_SEARCH_ROOTS:
        if path.exists() and path not in roots:
            roots.append(path)

    if _is_wsl_environment():
        for env_var in ("USERPROFILE", "LOCALAPPDATA", "APPDATA"):
            raw = os.environ.get(env_var)
            if not raw:
                continue
            path = _coerce_env_path(raw)
            candidates = [path]
            if env_var == "USERPROFILE":
                candidates.append(path / "Downloads")
            for candidate in candidates:
                if candidate.exists() and candidate not in roots:
                    roots.append(candidate)

    return roots


def _configured_install_roots() -> dict[str, Path]:
    try:
        return load_install_roots(install_roots_path(ROOT))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _resolve_launcher_from_root(root: Path, candidates: tuple[str, ...]) -> Path | None:
    for relative_path in candidates:
        candidate = root / relative_path
        if candidate.exists():
            return candidate

    seen_names: set[str] = set()
    for relative_path in candidates:
        name = Path(relative_path).name
        if name in seen_names:
            continue
        seen_names.add(name)
        for match in root.rglob(name):
            if match.is_file():
                return match

    return None


def _resolve_installer_path(spec: InstallSpec) -> Path | None:
    if spec.key == "prti1516e":
        if _is_linux_platform():
            filenames = [
                "prti1516e-free_5_5_10_linux64.sh",
                "prti1516e-free_5_5_10_linux32.sh",
                "prti1516e-free_5_5_10_windows64.exe",
                "prti1516e-free_5_5_10_windows32.exe",
            ]
        else:
            filenames = [
                "prti1516e-free_5_5_10_windows64.exe",
                "prti1516e-free_5_5_10_windows32.exe",
                "prti1516e-free_5_5_10_linux64.sh",
                "prti1516e-free_5_5_10_linux32.sh",
            ]
        for filename in filenames:
            hits = discover_file_locations(filename, _installer_search_roots(), max_depth=4)
            if hits:
                return hits[0]
        if spec.path.exists():
            return spec.path
        return None

    if spec.path.exists():
        return spec.path

    hits = discover_file_locations(spec.path.name, _installer_search_roots(), max_depth=4)
    return hits[0] if hits else None


def _print_missing_installers(specs: list[InstallSpec]) -> None:
    drop_root = resolve_installer_drop_root()
    print("Could not find the Pitch installer files needed for setup.")
    print(f"Installer drop root: {drop_root}")
    print("Set PITCH_INSTALLER_DROP_ROOT to override the installer folder directly.")
    print("Search locations included:")
    for root in _installer_search_roots():
        print(f"  - {root}")
    print("Expected installer filenames:")
    for spec in specs:
        print(f"  - {spec.path.name}")
    print("Place the installers in the drop root above, or in pitch/, Downloads/, or a cache folder, then rerun `pitch setup`.")


def _discover_installed_runtime_launcher(component_key: str) -> Path | None:
    system = _platform_system()
    configured_roots = _configured_install_roots()
    configured_root = configured_roots.get(component_key)
    if configured_root is not None and configured_root.exists():
        roots = [configured_root]
    else:
        roots = []

    if system == "Windows":
        discovered_roots = discover_windows_install_locations(WINDOWS_INSTALLATION_HINTS)
        component_name = {
            "hlastarterkit": "HlaStarterKit",
            "pitchvisualomt": "PitchVisualOMT",
            "prti1516e": "prti1516e-free",
        }.get(component_key)
        if component_name is None:
            return None
        roots.extend(_normalize_install_roots(discovered_roots.get(component_name, [])))
        candidates = WINDOWS_RUNTIME_LAUNCHERS.get(component_key, ())
    elif system == "Linux":
        discovered_roots = discover_linux_install_locations(
            {
                "hlastarterkit": (Path.home(), Path.home() / ".local" / "share", Path("/opt"), Path("/usr/local")),
                "pitchvisualomt": (Path.home(), Path.home() / ".local" / "share", Path("/opt"), Path("/usr/local")),
                "prti1516e": (Path.home(), Path.home() / ".local" / "share", Path("/opt"), Path("/usr/local")),
            },
            LINUX_RUNTIME_LAUNCHERS,
        )
        roots.extend(_normalize_install_roots(discovered_roots.get(component_key, [])))
        candidates = LINUX_RUNTIME_LAUNCHERS.get(component_key, ())
    else:
        return None

    seen_roots: list[Path] = []
    for root in roots:
        if root in seen_roots:
            continue
        seen_roots.append(root)
        launcher = _resolve_launcher_from_root(root, candidates)
        if launcher is not None:
            return launcher

    return None


def _discover_prti_install_root() -> Path | None:
    configured_roots = _configured_install_roots()
    configured_root = configured_roots.get("prti1516e")
    if configured_root is not None and configured_root.exists():
        return configured_root

    launcher = _discover_installed_runtime_launcher("prti1516e")
    if launcher is None:
        return None

    if launcher.parent.name.lower() == "bin":
        return launcher.parent.parent
    return launcher.parent


def _discover_chat_sample_launcher(variant: str | None = None) -> tuple[str, Path] | None:
    install_root = _discover_prti_install_root()
    if install_root is None:
        return None

    samples_root = install_root / "samples"
    if not samples_root.exists():
        return None

    variants = [variant] if variant and variant != "auto" else ["java-hla4", "java-hla4-fedpro", "cpp-hla4"]
    for selected_variant in variants:
        candidates = CHAT_SAMPLE_VARIANTS.get(selected_variant)
        if not candidates:
            continue
        for relative_path in candidates:
            matches = discover_file_locations(Path(relative_path).name, [samples_root], max_depth=4)
            for match in matches:
                if match.parent.as_posix().endswith(Path(relative_path).parent.as_posix()):
                    return selected_variant, match
    return None


def _chat_sample_choices() -> list[str]:
    discovered: list[str] = []
    for variant in ("java-hla4", "java-hla4-fedpro", "cpp-hla4"):
        if _discover_chat_sample_launcher(variant) is not None:
            discovered.append(variant)
    return discovered


def _chat_launcher_command(launcher: Path) -> list[str]:
    if launcher.suffix.lower() in {".bat", ".cmd"}:
        sample_root = launcher.parent.parent.parent
        jar_path = launcher.parent / f"{launcher.stem}.jar"
        java_exe = sample_root / "jre" / "bin" / "java.exe"
        if jar_path.exists() and java_exe.exists():
            return [str(java_exe), "-Djava.library.path=" + str(sample_root / "lib"), "-jar", str(jar_path)]
    return _launcher_command(launcher)


def _crc_host_from_log(log_file: Path) -> str | None:
    try:
        contents = log_file.read_text(errors="ignore")
    except OSError:
        return None

    for line in reversed(contents.splitlines()):
        host_match = re.search(r"host:([^,;/\s]+)", line)
        if host_match:
            return host_match.group(1).strip()
        if "CRC listening on adapters" in line:
            adapters = line.split("CRC listening on adapters", 1)[1].strip().lstrip(":").strip()
            candidate = adapters.split(",", 1)[0].strip()
            if candidate:
                return candidate
    return None


def _chat_smoke_host_candidates() -> list[str]:
    default_port = route_rti_port(route_surface_for_context())
    candidates: list[str] = [f"127.0.0.1:{default_port}", f"localhost:{default_port}", "127.0.0.1", "localhost"]

    env_host = os.environ.get("PITCH_RTI_SMOKE_HOST")
    if env_host:
        candidate = env_host.strip()
        if candidate and candidate not in candidates:
            candidates.insert(0, candidate)

    install_roots: list[Path] = []
    if _is_wsl_environment():
        install_roots.append(Path("/mnt/c/Program Files/prti1516e"))

    install_root = _discover_prti_install_root()
    if install_root is not None:
        install_roots.append(install_root)

    for root in install_roots:
        logs_root = root / "logs"
        if not logs_root.exists():
            continue
        log_files = sorted(logs_root.glob("CRC*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
        for log_file in log_files:
            host = _crc_host_from_log(log_file)
            if host and host not in candidates:
                candidates.append(host)

    return candidates


def _run_chat_process(command: list[str], *, cwd: Path, username: str, host: str, message: str, final_message: str = ".") -> tuple[int, str]:
    return _run_chat_process_impl(command, cwd=cwd, username=username, host=host, message=message, final_message=final_message)


def _run_chat_smoke_test(variant: str = "auto", *, list_only: bool = False) -> int:
    if list_only:
        print("Available chat sample variants:")
        for choice in _chat_sample_choices():
            launcher = _discover_chat_sample_launcher(choice)
            if launcher is None:
                continue
            _, path = launcher
            print(f"  {choice}: {path}")
        return 0

    discovered = _discover_chat_sample_launcher(variant)
    if discovered is None:
        choices = _chat_sample_choices()
        if choices:
            print("No matching chat sample launcher was found for the requested variant.", file=sys.stderr)
            print(f"Available chat sample variants: {', '.join(choices)}", file=sys.stderr)
        else:
            print("No chat sample launcher was found under the installed pRTI samples.", file=sys.stderr)
        return 1

    chosen_variant, launcher = discovered
    print(f"Chat smoke variant: {chosen_variant}")
    print(f"Chat sample launcher: {launcher}")
    command = _chat_launcher_command(launcher)
    host = _chat_smoke_host_candidates()[0]
    messages = [
        ("pitch-smoke-alpha", "Hello from pitch-smoke-alpha"),
        ("pitch-smoke-bravo", "Hello from pitch-smoke-bravo"),
    ]
    print(f"Chat smoke CRC host: {host}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_run_chat_process, command, cwd=launcher.parent, username=username, host=host, message=message)
            for username, message in messages
        ]
        results = [future.result() for future in futures]

    failures: list[str] = []
    for index, (returncode, output) in enumerate(results, start=1):
        if returncode != 0:
            failures.append(f"chat federate {index} exited with {returncode}")
            print(f"--- chat federate {index} output ---")
            print(output.rstrip())
        elif "Type messages you want to send" not in output:
            failures.append(f"chat federate {index} did not reach the chat prompt")
            print(f"--- chat federate {index} output ---")
            print(output.rstrip())

    if failures:
        print("Pitch chat smoke test failed.", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print("Pitch chat smoke test passed.")
    return 0


def _start_actions() -> list[StartAction]:
    system = _platform_system()
    if system == "Windows":
        return [
            StartAction("1", "HlaStarterKit", "runtime", ASSET_ROOT / "windows" / "HlaStarterKit_v1.0.2_windows64.exe", "hlastarterkit"),
            StartAction("2", "PitchVisualOMT", "runtime", ASSET_ROOT / "windows" / "PitchVisualOMTFree_v2.7.0_windows64.exe", "pitchvisualomt"),
            StartAction("3", "prti1516e-free", "runtime", ASSET_ROOT / "windows" / "prti1516e-free_5_5_10_windows32.exe", "prti1516e"),
            StartAction("4", "Docs", "folder", ASSET_ROOT / "docs", "docs"),
            StartAction("5", "Plugin", "folder", ASSET_ROOT / "plugin", "plugin"),
            StartAction("6", "Project Root", "folder", ROOT, "root"),
        ]
    if system == "Linux":
        return [
            StartAction("1", "HlaStarterKit", "runtime", ASSET_ROOT / "linux" / "HlaStarterKit_v1.0.2_linux64.sh", "hlastarterkit"),
            StartAction("2", "PitchVisualOMT", "runtime", ASSET_ROOT / "linux" / "PitchVisualOMTFree_v2.7.0_linux64.sh", "pitchvisualomt"),
            StartAction("3", "prti1516e-free", "runtime", ASSET_ROOT / "linux" / "prti1516e-free_5_5_10_linux64.sh", "prti1516e"),
            StartAction("4", "Docs", "folder", ASSET_ROOT / "docs", "docs"),
            StartAction("5", "Plugin", "folder", ASSET_ROOT / "plugin", "plugin"),
            StartAction("6", "Project Root", "folder", ROOT, "root"),
        ]
    raise RuntimeError(f"Unsupported platform: {system}")


def _lookup_start_action(target: str) -> StartAction | None:
    normalized = target.strip().lower()
    for action in _start_actions():
        if normalized in {action.key, action.label.lower(), action.alias}:
            return action
    return None


def _show_menu() -> None:
    print("Pick a Pitch item to launch:")
    for action in _start_actions():
        print(f"  {action.key}. {action.label}")


def _run_start_action(action: StartAction, args: argparse.Namespace) -> None:
    if action.kind == "folder":
        if not action.path.exists():
            raise FileNotFoundError(f"Missing path: {action.path}")
        _open_path(action.path)
        return

    launcher = _discover_installed_runtime_launcher(action.alias)
    if launcher is None:
        raise RuntimeError(
            f"No installed launcher found for {action.label}. Run `pitch setup` first, or use `pitch status` to inspect the install."
    )

    print(f"Launching {action.label} from {launcher}...")
    launch_env: dict[str, str] = {}
    port_surface = route_surface_for_context()
    if getattr(args, "port", None) is not None:
        launch_env["PITCH_PORT"] = str(args.port)
    else:
        launch_env["PITCH_PORT"] = str(route_rti_port(port_surface))
    launch_env["PITCH_PORT_PROFILE"] = port_surface
    if getattr(args, "ports_config", None):
        launch_env["PITCH_PORTS_CONFIG"] = str((ROOT / args.ports_config).resolve() if not Path(args.ports_config).is_absolute() else Path(args.ports_config))

    _launch_program(launcher, env=launch_env)


def _run_rti_smoke_test() -> int:
    try:
        process, host_port = _start_prti_crc()
    except OSError as exc:
        print(f"Could not start the Pitch RTI launcher: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        _mark_rti_smoke_result(True, host_port)
        print("Pitch RTI smoke test passed.")
        return 0
    finally:
        if process.poll() is None:
            process.kill()


def handle_setup(args: argparse.Namespace) -> int:
    route_name = getattr(args, "route", "native")
    if route_name == "auto":
        route_name = _default_route_name()

    selected_route = route_name if route_name != "native" else _route_context_name() or "native"
    _print_route_visibility(include_wsl_distros=route_name == "wsl")
    print(f"Selected route: {selected_route}")
    if route_name != "native":
        return _run_route_command(route_name, _build_setup_argv(args, route_name="native"), wsl_distro=getattr(args, "wsl_distro", None))

    _stage_assets_for_setup(getattr(args, "source", None), force=args.force)

    failures = _verify_setup_paths()
    if failures:
        _failures_to_stderr(failures)
        return 1

    target_specs = _install_specs_for_system(args.include_legacy_rti)
    if _is_windows_platform() and not args.include_legacy_rti:
        core_specs = list(SETUP_WINDOWS_SPECS)
        if not any(_resolve_installer_path(spec) is not None for spec in core_specs):
            legacy_installer = _resolve_installer_path(SETUP_WINDOWS_LEGACY_SPEC)
            if legacy_installer is not None:
                print("Core Windows installers were not found; falling back to the legacy pRTI package.")
                target_specs = [SETUP_WINDOWS_LEGACY_SPEC]

    required_keys = {spec.key for spec in target_specs}
    installed_components = _installed_components()
    detected_components = installed_components & required_keys

    if detected_components:
        _log_detected_installed(detected_components)

    if not args.force and detected_components >= required_keys:
        print("Pitch already appears installed. Use --force to rerun installers.")
        _apply_requested_hla4_preview(args, context="setup", require_settings=False)
        _maybe_print_prti_settings_summary("prti1516e" in detected_components)
        if args.probe_ports:
            print("Probing configured ports...")
            results = _probe_results(args.ports_config)
            if args.strict_probe and not all(open_ for _, open_ in results):
                raise RuntimeError("One or more configured ports are closed.")
        return 0

    missing_specs = [spec for spec in target_specs if spec.key not in detected_components or args.force]
    if not missing_specs and not args.force:
        print("Pitch already appears installed. Use --force to rerun installers.")
        return 0

    if args.force:
        print("Force mode enabled; rerunning installers.")

    if _is_linux_platform() and args.include_legacy_rti:
        print("Legacy RTI package is Windows-only in this bundle, so it is skipped on Linux.")
    if args.silent_install:
        print("Silent install mode enabled; using vendor quiet flags where supported.")

    resolved_specs: list[tuple[InstallSpec, Path]] = []
    unresolved_specs: list[InstallSpec] = []
    for spec in missing_specs:
        installer_path = _resolve_installer_path(spec)
        if installer_path is None:
            unresolved_specs.append(spec)
        else:
            resolved_specs.append((spec, installer_path))

    if unresolved_specs:
        _print_missing_installers(unresolved_specs)
        if not resolved_specs:
            return 1
        print("Continuing with the installers that were found.")

    for spec, installer_path in resolved_specs:
        print(f"Launching {spec.label} from {installer_path}...")
        run_installer(installer_path, cwd=ROOT, quiet=args.silent_install)
        _mark_component_installed(spec.key, spec.label, "installer", str(installer_path))
        if spec.key == "prti1516e":
            _maybe_print_prti_settings_summary(True)

    _apply_requested_hla4_preview(args, context="setup", require_settings=False)

    if args.probe_ports:
        print("Probing configured ports...")
        results = _probe_results(args.ports_config)
        if args.strict_probe and not all(open_ for _, open_ in results):
            raise RuntimeError("One or more configured ports are closed.")

    print("Pitch setup finished.")
    return 0


def handle_verify(args: argparse.Namespace) -> int:
    failures = _verify_paths()
    if failures:
        _failures_to_stderr(failures)
        return 1

    if getattr(args, "rti_smoke", False):
        if _discover_installed_runtime_launcher("prti1516e") is None:
            print("Skipping RTI smoke test: no installed Pitch RTI launcher was found.")
        elif _run_rti_smoke_test() != 0:
            return 1

    if not args.quiet:
        print("Verification passed.")
    return 0


def handle_preflight(args: argparse.Namespace) -> int:
    report = _preflight_report(getattr(args, "config", None))
    _save_preflight_report(report)
    if getattr(args, "json_file", None) is not None:
        _write_json_file(Path(args.json_file), report)

    if getattr(args, "json", False):
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        print("Pitch preflight:")
        for check in report.get("checks", []):
            if not isinstance(check, dict):
                continue
            name = str(check.get("name", "check"))
            status = str(check.get("status", "unknown"))
            detail = str(check.get("detail", "")).strip()
            print(f"  {name}: {status}")
            if detail:
                print(f"    {detail}")
        print(f"  environment: {report.get('environment', 'unknown')}")
        print(f"  next step: {report.get('next_step', 'rerun after fixing prerequisites')}")

    return int(report.get("exit_code", 1))


def handle_probe(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = ROOT / config_path

    results = probe_targets(parse_ports_config(config_path))
    any_closed = False
    for target, open_ in results:
        state = "OPEN" if open_ else "CLOSED"
        print(f"{state}  {target.label} {target.host}:{target.port}")
        any_closed = any_closed or not open_

    return 0 if (not any_closed or not args.strict) else 1


def handle_doctor(args: argparse.Namespace) -> int:
    _print_python_workflow()
    _print_route_visibility()
    print("Detected install roots:")
    print(f"Writable asset root: {resolve_installer_drop_root()}")

    configured_roots = _configured_install_roots()
    if configured_roots:
        print("  Configured overrides:")
        for component in sorted(configured_roots):
            print(f"    {component} -> {configured_roots[component]}")
    else:
        print("  Configured overrides: none")

    detected_roots = _detected_install_roots()
    if detected_roots:
        print("  Detected installs:")
        for component in sorted(detected_roots):
            print(f"    {component} -> {detected_roots[component]}")
    else:
        print("  Detected installs: none")

    installed_components = sorted(_installed_components())
    if installed_components:
        print("Installed components:")
        for component in installed_components:
            launcher = _discover_installed_runtime_launcher(component)
            if launcher is not None:
                print(f"  {component} -> {launcher}")
            else:
                print(f"  {component}")
    else:
        print("Installed components: none")

    return 0


def handle_status(args: argparse.Namespace) -> int:
    _print_route_visibility()
    state = _load_state()
    components = state.get("components")
    installed_components: set[str] = set()
    if isinstance(components, dict):
        for key, value in components.items():
            if isinstance(value, dict) and value.get("status") == "installed":
                installed_components.add(str(key))

    detected_components = _installed_components()
    all_components = sorted(installed_components | detected_components)
    configured_roots = _configured_install_roots()

    print("Install state:")
    if all_components:
        for component in all_components:
            launcher = _discover_installed_runtime_launcher(component)
            if launcher is not None:
                print(f"  INSTALLED  {component} -> {launcher}")
            else:
                print(f"  INSTALLED  {component}")
    else:
        print("  NOT INSTALLED")

    if configured_roots:
        print("Install overrides:")
        for component in sorted(configured_roots):
            print(f"  {component} -> {configured_roots[component]}")

    print("Preflight:")
    preflight = _load_preflight_report()
    if isinstance(preflight, dict):
        environment = str(preflight.get("environment", "unknown"))
        result = str(preflight.get("result", "unknown"))
        print(f"  cached: yes")
        print(f"  environment: {environment}")
        print(f"  result: {result}")
        next_step = str(preflight.get("next_step", "")).strip()
        if next_step:
            print(f"  next step: {next_step}")
    else:
        print("  cached: no")
        print("  environment: unknown")

    print("RTI smoke test:")
    launcher = _discover_installed_runtime_launcher("prti1516e")
    if launcher is not None:
        print("  available")
    else:
        print("  unavailable")
    checks = state.get("checks")
    smoke_check = checks.get("rti_smoke") if isinstance(checks, dict) else None
    if isinstance(smoke_check, dict) and smoke_check.get("timestamp"):
        status = str(smoke_check.get("status", "unknown")).lower()
        timestamp = str(smoke_check.get("timestamp"))
        detail = str(smoke_check.get("detail", "")).strip()
        if status == "passed":
            print(f"  last passed: {timestamp}")
        elif status == "failed":
            print(f"  last failed: {timestamp}")
        else:
            print(f"  last run: {status} at {timestamp}")
        if detail:
            print(f"  launcher: {detail}")
    else:
        print("  last run: never")

    print("Port readiness:")
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    results = probe_targets(parse_ports_config(config_path))
    any_closed = False
    for target, open_ in results:
        state_text = "OPEN" if open_ else "CLOSED"
        print(f"  {state_text}  {target.label} {target.host}:{target.port}")
        any_closed = any_closed or not open_

    return 0 if (not any_closed or not args.strict) else 1


def handle_config(args: argparse.Namespace) -> int:
    parser = getattr(args, "parser", None)
    if parser is not None:
        parser.print_help()
    else:
        print("Usage: pitch config init")
    return 0


def _print_install_roots_payload(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def handle_config_show(args: argparse.Namespace) -> int:
    config_path = install_roots_path(ROOT)
    if config_path.exists():
        try:
            with config_path.open("r", encoding="utf-8", errors="replace") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not read {config_path}: {exc}") from exc

        print(f"{config_path}:")
        _print_install_roots_payload(payload if isinstance(payload, dict) else {"value": payload})
        return 0

    detected_roots = _detected_install_roots()
    if not detected_roots:
        print(f"No {config_path} file exists and no Pitch roots were detected.")
        return 1

    system = _platform_system()
    payload: dict[str, object]
    if system == "Windows":
        payload = {
            "windows": {key: str(value) for key, value in sorted(detected_roots.items())},
        }
    elif system == "Linux":
        payload = {
            "linux": {key: str(value) for key, value in sorted(detected_roots.items())},
        }
    else:
        print(f"Unsupported platform: {system}")
        return 1

    print(f"{config_path} does not exist; detected roots would be:")
    _print_install_roots_payload(payload)
    return 0


def handle_config_init(args: argparse.Namespace) -> int:
    config_path = install_roots_path(ROOT)
    if config_path.exists() and not args.force:
        print(f"Config already exists: {config_path}. Use --force to overwrite.")
        return 0

    detected_roots = _detected_install_roots()
    if not detected_roots:
        print("No installed Pitch roots were detected, so nothing was written.")
        return 1

    system = _platform_system()
    if system == "Windows":
        payload: dict[str, object] = {
            "windows": {key: str(value) for key, value in sorted(detected_roots.items())},
        }
    elif system == "Linux":
        payload = {
            "linux": {key: str(value) for key, value in sorted(detected_roots.items())},
        }
    else:
        print(f"Unsupported platform: {system}")
        return 1

    _write_json_file(config_path, payload)
    print(f"Wrote {config_path}:")
    for key, value in sorted(detected_roots.items()):
        print(f"  {key} -> {value}")
    return 0


def handle_config_assets(args: argparse.Namespace) -> int:
    print("Writable asset locations:")
    print(f"  user data root: {USER_DATA_ROOT}")
    print(f"  artifact root: {ARTIFACT_ROOT}")
    print(f"  installer drop root: {resolve_installer_drop_root()}")
    print("Bundle locations:")
    print(f"  asset root: {ASSET_ROOT}")
    print(f"  download contact file: {_download_contact_path()}")
    return 0


def handle_assets(args: argparse.Namespace) -> int:
    parser = getattr(args, "parser", None)
    if parser is not None:
        parser.print_help()
    else:
        print("Usage: pitch assets init | pitch assets import <source-folder> | pitch assets verify")
    return 0


def _print_installer_drop_root() -> None:
    print(f"Installer drop root: {resolve_installer_drop_root()}")


def handle_assets_show(args: argparse.Namespace) -> int:
    _print_installer_drop_root()
    return 0


def handle_assets_init(args: argparse.Namespace) -> int:
    try:
        path = ensure_installer_drop_root()
    except OSError as exc:
        print(f"Could not create installer drop root: {resolve_installer_drop_root()}", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Created installer drop root: {path}")
    return 0


def handle_assets_open(args: argparse.Namespace) -> int:
    path = ensure_installer_drop_root()
    _open_path(path)
    print(f"Opened installer drop root: {path}")
    return 0


def handle_assets_verify(args: argparse.Namespace) -> int:
    failures = _verify_installer_checksum_manifest()
    if failures:
        _failures_to_stderr(failures)
        return 1
    print("Downloaded artifacts verification passed.")
    return 0


def _vendor_docker_payload(*, enable_hla4_preview: bool = False) -> dict[str, str]:
    return _vendor_docker_payload_impl(enable_hla4_preview=enable_hla4_preview)


def _discover_crc_settings_files() -> list[Path]:
    hits: list[Path] = []
    seen: set[str] = set()
    roots = _crc_settings_search_roots()

    for name in (
        "prti1516eCRC.settings",
        "pRTI1516eCRC.settings",
        "prti1516e-freeCRC.settings",
        "PitchCRC.settings",
        "CRC.settings",
    ):
        for hit in discover_file_locations(name, roots, max_depth=4):
            key = str(hit.resolve()) if hit.exists() else str(hit)
            if key not in seen:
                hits.append(hit)
                seen.add(key)

    if hits:
        return hits

    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for pattern in ("*CRC.settings", "*crc.settings"):
            try:
                candidates = root.rglob(pattern)
            except OSError:
                continue
            for candidate in candidates:
                if not candidate.is_file():
                    continue
                key = str(candidate.resolve()) if candidate.exists() else str(candidate)
                if key not in seen:
                    hits.append(candidate)
                    seen.add(key)

    return hits


def _print_crc_settings_summary() -> None:
    print_crc_settings_summary(
        user_data_root=USER_DATA_ROOT,
        installer_drop_root=INSTALLER_DROP_ROOT,
        asset_root=ASSET_ROOT,
        workspace_root=ROOT,
        home_root=Path.home(),
        launcher=_discover_installed_runtime_launcher("prti1516e"),
    )


def _maybe_print_prti_settings_summary(triggered: bool) -> None:
    if triggered:
        _print_crc_settings_summary()


def _apply_requested_hla4_preview(args: argparse.Namespace, *, context: str, require_settings: bool) -> bool:
    return apply_requested_hla4_preview(
        args,
        context=context,
        settings_files=_discover_crc_settings_files(),
        require_settings=require_settings,
    )


def handle_docker(args: argparse.Namespace) -> int:
    parser = getattr(args, "parser", None)
    if getattr(args, "docker_command", None) is None:
        if parser is not None:
            parser.print_help()
        else:
            print("Usage: pitch docker init | pitch docker up | pitch docker restart | pitch docker down | pitch docker inspect | pitch docker status")
        return 0
    return int(args.handler(args))


def handle_docker_init(args: argparse.Namespace) -> int:
    env_path = _vendor_docker_env_path()
    settings_root = _vendor_docker_settings_root()
    build_root = _vendor_docker_build_root()
    if env_path.exists() and settings_root.exists() and build_root.exists() and not args.force:
        print(f"Vendor Docker env file already exists: {env_path}")
        print("Use --force to overwrite it.")
        return 0

    try:
        payload = _vendor_docker_payload(enable_hla4_preview=getattr(args, "enable_hla4_preview", False))
        if args.force and env_path.exists():
            env_path.unlink()
        if args.force and build_root.exists():
            shutil.rmtree(build_root)
        _copy_vendor_settings(Path(payload["PITCH_PRTI_HOME"]), settings_root)
        _copy_vendor_docker_context(Path(payload["PITCH_PRTI_HOME"]), build_root)
        if getattr(args, "enable_hla4_preview", False):
            set_settings_value(vendor_crc_settings_path(settings_root), "CRC.enableHla4PreviewFeatures", "true")
        _write_docker_env_file(env_path, payload)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Wrote vendor Docker env file: {env_path}")
    print(f"Wrote vendor settings overlay: {settings_root}")
    print(f"Wrote vendor Docker build context: {build_root}")
    for key, value in payload.items():
        print(f"  {key}={value}")
    return 0


def _vendor_docker_compose_command(action: str) -> list[str]:
    return _vendor_docker_compose_command_impl(action)


def _run_vendor_docker_compose(action: str) -> subprocess.CompletedProcess[str]:
    return _run_vendor_docker_compose_impl(action)


def _vendor_docker_wait_for_port(host: str, port: int, *, timeout_seconds: float = 60.0, interval_seconds: float = 1.0) -> bool:
    return _vendor_docker_wait_for_port_impl(host, port, timeout_seconds=timeout_seconds, interval_seconds=interval_seconds)


def _vendor_docker_smoke_check(*, timeout_seconds: float = 60.0, interval_seconds: float = 1.0) -> tuple[bool, str]:
    crc_port = route_rti_port("vendor-docker")
    webview_port = route_webview_port("vendor-docker")
    if not _vendor_docker_wait_for_port("127.0.0.1", crc_port, timeout_seconds=timeout_seconds, interval_seconds=interval_seconds):
        return False, f"Vendor CRC did not become reachable on 127.0.0.1:{crc_port} within the timeout."

    messages = [f"Vendor CRC is reachable on 127.0.0.1:{crc_port}."]
    webview_ok, webview_detail = _vendor_docker_webview_check(timeout_seconds=10.0)
    webview_detail = webview_detail.replace("127.0.0.1:8080", f"127.0.0.1:{webview_port}")
    messages.append(webview_detail)
    if not webview_ok:
        return False, "\n".join(messages)
    return True, "\n".join(messages)


def _vendor_docker_webview_check(*, timeout_seconds: float = 10.0) -> tuple[bool, str]:
    return _vendor_docker_webview_check_impl(timeout_seconds=timeout_seconds)


def handle_docker_up(args: argparse.Namespace) -> int:
    try:
        completed = _run_vendor_docker_compose("up -d --build pitch-crc")
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if completed.returncode != 0:
        return int(completed.returncode)
    smoke_ok, smoke_detail = _vendor_docker_smoke_check()
    if not smoke_ok:
        print(smoke_detail, file=sys.stderr)
        return 1
    print(smoke_detail)
    return 0


def handle_docker_restart(args: argparse.Namespace) -> int:
    down_rc = handle_docker_down(args)
    if down_rc != 0:
        return down_rc
    return handle_docker_up(args)


def handle_docker_smoke(args: argparse.Namespace) -> int:
    smoke_ok, smoke_detail = _vendor_docker_smoke_check(
        timeout_seconds=getattr(args, "timeout_seconds", 60.0),
        interval_seconds=getattr(args, "interval_seconds", 1.0),
    )
    print(smoke_detail)
    return 0 if smoke_ok else 1


def handle_docker_ps(args: argparse.Namespace) -> int:
    action = "ps"
    if getattr(args, "all", False):
        action += " --all"
    try:
        completed = _run_vendor_docker_compose(action)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return int(completed.returncode)


def handle_docker_logs(args: argparse.Namespace) -> int:
    action = "logs --no-color"
    tail = getattr(args, "tail", None)
    if tail is not None:
        action += f" --tail {int(tail)}"
    if getattr(args, "follow", False):
        action += " --follow"
    action += f" {getattr(args, 'service', None) or 'pitch-crc'}"
    try:
        completed = _run_vendor_docker_compose(action)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return int(completed.returncode)


def handle_docker_down(args: argparse.Namespace) -> int:
    try:
        completed = _run_vendor_docker_compose("down")
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return int(completed.returncode)


def handle_docker_status(args: argparse.Namespace) -> int:
    for line in _vendor_docker_status_lines_impl():
        print(line)
    return 0


def handle_docker_inspect(args: argparse.Namespace) -> int:
    for line in _vendor_docker_status_lines_impl():
        print(line)
    try:
        completed = _run_vendor_docker_compose("ps --all")
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return int(completed.returncode)


def _discover_importable_assets(source_root: Path) -> list[Path]:
    hits: list[Path] = []
    seen_names: set[str] = set()
    for filename in ASSET_IMPORTABLE_FILENAMES:
        matches = discover_file_locations(filename, [source_root], max_depth=10)
        if not matches:
            continue
        selected = matches[0]
        if selected.name in seen_names:
            continue
        seen_names.add(selected.name)
        hits.append(selected)
    return hits


def _stage_importable_assets(source_root: Path, dest_root: Path, force: bool = False) -> tuple[list[Path], list[Path], list[Path]]:
    discovered = _discover_importable_assets(source_root)
    if not discovered:
        return [], [], []

    copied: list[Path] = []
    skipped: list[Path] = []
    conflicts: list[Path] = []

    for source in discovered:
        destination = dest_root / source.name
        if destination.exists():
            if sha256_file(destination) == sha256_file(source):
                skipped.append(destination)
                continue
            if not force:
                conflicts.append(destination)
                continue
        shutil.copy2(source, destination)
        copied.append(destination)

    return copied, skipped, conflicts


def handle_assets_import(args: argparse.Namespace) -> int:
    source_root = _coerce_cli_path(args.source)
    if not source_root.exists():
        print(f"Source folder does not exist: {source_root}", file=sys.stderr)
        return 1
    if not source_root.is_dir():
        print(f"Source path is not a folder: {source_root}", file=sys.stderr)
        return 1

    try:
        dest_root = ensure_installer_drop_root()
    except OSError as exc:
        print(f"Could not create installer drop root: {resolve_installer_drop_root()}", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1

    copied, skipped, conflicts = _stage_importable_assets(source_root, dest_root, force=args.force)
    if not copied and not skipped and not conflicts:
        print(f"No recognized Pitch files were found under: {source_root}", file=sys.stderr)
        return 1

    if conflicts:
        print("Conflicting staged files already exist. Re-run with --force to overwrite:", file=sys.stderr)
        for path in conflicts:
            print(f"  - {path}", file=sys.stderr)
        return 1

    print(f"Staged {len(copied)} file(s) into {dest_root}")
    if skipped:
        print("Already staged:")
        for path in skipped:
            print(f"  - {path}")
    if copied:
        print("Copied:")
        for path in copied:
            print(f"  - {path}")

    manifest_path = _write_installer_checksum_manifest(dest_root)
    tracked = _checksum_tracked_artifact_paths(dest_root)
    if tracked:
        print(f"Wrote checksum manifest: {manifest_path}")
    else:
        print(f"No checksum-tracked artifacts were found in {dest_root}; manifest left empty.")
    return 0


def _stage_assets_for_setup(source_root: str | None, force: bool) -> None:
    if not source_root:
        return

    source_path = _coerce_cli_path(source_root)
    if not source_path.exists():
        raise FileNotFoundError(f"Source folder does not exist: {source_path}")
    if not source_path.is_dir():
        raise FileNotFoundError(f"Source path is not a folder: {source_path}")

    dest_root = ensure_installer_drop_root()
    copied, skipped, conflicts = _stage_importable_assets(source_path, dest_root, force=force)
    if conflicts:
        raise RuntimeError(
            "Conflicting staged files already exist. Re-run with --force after importing the source folder."
        )
    print(f"Staged setup assets from {source_path} into {dest_root}")
    if copied:
        print(f"Staged {len(copied)} file(s) into {dest_root}")
    if skipped:
        print(f"Already staged {len(skipped)} file(s) in {dest_root}")
    _write_installer_checksum_manifest(dest_root)


def _download_contact_path() -> Path:
    return ARTIFACT_ROOT / DOWNLOAD_CONTACT_FILENAME


def _load_download_contact_defaults() -> dict[str, object]:
    payload = dict(DOWNLOAD_CONTACT_DEFAULTS)
    try:
        with DOWNLOAD_CONTACT_TEMPLATE.open("r", encoding="utf-8", errors="replace") as handle:
            loaded = json.load(handle)
    except (OSError, json.JSONDecodeError):
        loaded = {}

    if isinstance(loaded, dict):
        payload.update(loaded)

    return payload


def _load_download_contact() -> dict[str, object]:
    path = _download_contact_path()
    if not path.exists():
        return _load_download_contact_defaults()

    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read {path.name}: {exc}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f"Invalid download contact file: {path.name}")

    merged = _load_download_contact_defaults()
    merged.update(payload)
    return merged


def _normalize_product_name(product: str) -> str:
    return product.strip().lower().replace(" ", "")


def _download_product_label(product: str) -> str:
    normalized = _normalize_product_name(product)
    labels = {
        "prti": "Pitch pRTI Free",
        "prtifree": "Pitch pRTI Free",
        "pitchprti": "Pitch pRTI Free",
        "pitchprtifree": "Pitch pRTI Free",
        "pitchvisualomt": "Pitch Visual OMT Free",
        "pitchvisualomtfree": "Pitch Visual OMT Free",
        "hlastarterkit": "HLA Starter kit",
        "hlastarterkitfree": "HLA Starter kit",
        "hlatutorial": "HLA Tutorial",
        "pitchunrealengineconnector": "Pitch Unreal Engine Connector Free",
        "pitchunrealengineconnectorfree": "Pitch Unreal Engine Connector Free",
    }
    return labels.get(normalized, product)


def _download_contact_payload(contact: dict[str, object]) -> dict[str, object]:
    payload = {
        "destination_email": str(contact.get("destination_email", "")).strip(),
        "first_name": str(contact.get("first_name", "")).strip(),
        "last_name": str(contact.get("last_name", "")).strip(),
        "title": str(contact.get("title", "")).strip(),
        "organization": str(contact.get("organization", "")).strip(),
        "organization_type": str(contact.get("organization_type", "")).strip(),
        "country": str(contact.get("country", "")).strip(),
        "accepted_products": [
            _download_product_label(str(product))
            for product in contact.get("accepted_products", [])
            if str(product).strip()
        ],
        "subscribe_newsletter": bool(contact.get("subscribe_newsletter", False)),
    }
    return payload


def _download_submission_payload(contact: dict[str, object]) -> dict[str, str]:
    products = contact.get("accepted_products", [])
    if not isinstance(products, list):
        products = []

    payload = {
        "download": "prti",
        "agreeprti": "yes",
        "email": str(contact.get("destination_email", "")).strip(),
        "FirstName": str(contact.get("first_name", "")).strip(),
        "LastName": str(contact.get("last_name", "")).strip(),
        "Title": str(contact.get("title", "")).strip(),
        "OrganizationName": str(contact.get("organization", "")).strip(),
        "organization": str(contact.get("organization_type", "")).strip() or "Other",
        "country": str(contact.get("country", "")).strip() or "United States",
        "checklegal": "submitbtn",
        "rubrik": "Pitch Free download",
        "till": "hack@pitch.se",
        "Button": "Submit",
    }

    if "Pitch pRTI Free" in products:
        payload["download"] = "prti"

    return payload


def _download_bookmarklet_source(contact: dict[str, object]) -> str:
    payload = json.dumps(_download_contact_payload(contact), ensure_ascii=True)
    return f"""javascript:(()=>{{const data={payload};const norm=s=>String(s||'').toLowerCase().replace(/[\\s:_-]+/g,' ').replace(/\\s+/g,' ').trim();const textMatch=(needle,haystack)=>norm(haystack).includes(norm(needle));const rows=[...document.querySelectorAll('tr,li,p,div,fieldset,td,th,label')];const findContainer=needle=>{{const match=rows.find(el=>textMatch(needle,el.textContent));return match?match.closest('tr,li,p,div,fieldset,td,th')||match.parentElement:null;}};const fire=el=>{{el.dispatchEvent(new Event('input',{{bubbles:true}}));el.dispatchEvent(new Event('change',{{bubbles:true}}));}};const setValue=(needle,value)=>{{if(!value) return false;const container=findContainer(needle);if(!container) return false;const field=container.querySelector('input:not([type=checkbox]):not([type=radio]),textarea,select');if(!field) return false;field.value=value;fire(field);return true;}};const clickCheckbox=(needle)=>{{const container=findContainer(needle);if(!container) return false;const field=container.querySelector('input[type=checkbox]');if(!field) return false;if(!field.checked) field.click();return true;}};const clickRadio=(groupNeedle,optionNeedle)=>{{const container=findContainer(groupNeedle);if(!container) return false;for(const radio of container.querySelectorAll('input[type=radio]')){{const labelText=radio.closest('label')?.textContent||radio.parentElement?.textContent||radio.nextElementSibling?.textContent||'';if(textMatch(optionNeedle,labelText)){{if(!radio.checked) radio.click();return true;}}}}return false;}};setValue('e-mail address',data.destination_email);setValue('first name',data.first_name);setValue('last name',data.last_name);setValue('title/position',data.title);setValue('name of organization',data.organization);setValue('country',data.country);clickRadio('type of organization',data.organization_type);for(const product of data.accepted_products){{clickCheckbox(product);if(textMatch('Pitch pRTI Free',product)) clickCheckbox('I accept the Pitch pRTI license agreement');if(textMatch('Pitch Visual OMT Free',product)) clickCheckbox('I accept the Pitch Visual OMT license agreement');if(textMatch('Pitch Unreal Engine Connector Free',product)) clickCheckbox('I accept the Pitch Unreal Engine Connector license agreement');}}if(data.subscribe_newsletter) clickCheckbox('Subscribe to Pitch Newsletter');const emailField=findContainer('e-mail address')?.querySelector('input');if(emailField) emailField.focus();}})()"""


def _download_script_source(contact: dict[str, object]) -> str:
    payload = json.dumps(_download_contact_payload(contact), ensure_ascii=True, indent=2)
    return f"""const PITCH_DOWNLOAD_URL = {json.dumps(PITCH_FREE_DOWNLOAD_URL)};
const DEFAULTS = {payload};

function normalize(value) {{
  return String(value || "").toLowerCase().replace(/[\\s:_-]+/g, " ").replace(/\\s+/g, " ").trim();
}}

function textMatches(needle, haystack) {{
  return normalize(haystack).includes(normalize(needle));
}}

function getCandidateContainers() {{
  return [...document.querySelectorAll("tr,li,p,div,fieldset,td,th,label")];
}}

function findContainer(needle) {{
  const match = getCandidateContainers().find((el) => textMatches(needle, el.textContent));
  return match ? match.closest("tr,li,p,div,fieldset,td,th") || match.parentElement : null;
}}

function fire(field) {{
  field.dispatchEvent(new Event("input", {{ bubbles: true }}));
  field.dispatchEvent(new Event("change", {{ bubbles: true }}));
}}

function setValue(needle, value) {{
  if (!value) return false;
  const container = findContainer(needle);
  if (!container) return false;
  const field = container.querySelector("input:not([type=checkbox]):not([type=radio]),textarea,select");
  if (!field) return false;
  field.value = value;
  fire(field);
  return true;
}}

function clickCheckbox(needle) {{
  const container = findContainer(needle);
  if (!container) return false;
  const field = container.querySelector("input[type=checkbox]");
  if (!field) return false;
  if (!field.checked) field.click();
  return true;
}}

function clickRadio(groupNeedle, optionNeedle) {{
  const container = findContainer(groupNeedle);
  if (!container) return false;
  for (const radio of container.querySelectorAll("input[type=radio]")) {{
    const labelText = radio.closest("label")?.textContent || radio.parentElement?.textContent || radio.nextElementSibling?.textContent || "";
    if (textMatches(optionNeedle, labelText)) {{
      if (!radio.checked) radio.click();
      return true;
    }}
  }}
  return false;
}}

function findSubmitButton() {{
  const candidates = [...document.querySelectorAll("button, input[type=submit], input[type=button]")];
  return candidates.find((element) => {{
    const label = element.value || element.textContent || "";
    return textMatches("submit", label);
  }}) || null;
}}

function submitForm() {{
  const button = findSubmitButton();
  if (!button) {{
    console.warn("No submit button was found on the page.");
    return false;
  }}
  button.click();
  return true;
}}

function fillForm(contact) {{
  setValue("e-mail address", contact.destination_email);
  setValue("first name", contact.first_name);
  setValue("last name", contact.last_name);
  setValue("title/position", contact.title);
  setValue("name of organization", contact.organization);
  setValue("country", contact.country);
  clickRadio("type of organization", contact.organization_type);

  for (const product of contact.accepted_products || []) {{
    clickCheckbox(product);
    if (textMatches("Pitch pRTI Free", product)) clickCheckbox("I accept the Pitch pRTI license agreement");
    if (textMatches("Pitch Visual OMT Free", product)) clickCheckbox("I accept the Pitch Visual OMT license agreement");
    if (textMatches("Pitch Unreal Engine Connector Free", product)) clickCheckbox("I accept the Pitch Unreal Engine Connector license agreement");
  }}

  if (contact.subscribe_newsletter) {{
    clickCheckbox("Subscribe to Pitch Newsletter");
  }}

  const emailField = findContainer("e-mail address")?.querySelector("input");
  if (emailField) emailField.focus();
}}

function main() {{
  if (typeof document === "undefined") {{
    throw new Error("This script runs in a browser context only.");
  }}

  if (!location.href.includes("pitch.se/pRTI1516e/Releases/v5.5.10-free/")) {{
    console.warn("Open the Pitch download page first:", PITCH_DOWNLOAD_URL);
  }}

  const email = window.prompt("Pitch destination email", DEFAULTS.destination_email || "");
  if (!email) {{
    console.warn("No email was entered.");
    return;
  }}

  const contact = Object.assign({{}}, DEFAULTS, {{ destination_email: email }});
  fillForm(contact);

  if (window.confirm("Submit the Pitch form now?")) {{
    submitForm();
  }}
}}

main();
"""


def _download_submit_request(contact: dict[str, object]) -> urllib.request.Request:
    payload = _download_submission_payload(contact)
    body = urllib.parse.urlencode(payload).encode("utf-8")
    return urllib.request.Request(
        f"{PITCH_FREE_DOWNLOAD_URL.rsplit('/', 1)[0]}/mailformfree.asp",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", **PITCH_FREE_DOWNLOAD_HEADERS},
        method="POST",
    )


def _download_url(url: str, output_path: Path | None = None) -> Path:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": PITCH_FREE_DOWNLOAD_HEADERS["User-Agent"],
            "Accept": "application/octet-stream,*/*;q=0.8",
            "Referer": PITCH_FREE_DOWNLOAD_URL,
        },
        method="GET",
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        final_url = getattr(response, "url", url)
        target = output_path
        if target is None:
            parsed = urllib.parse.urlparse(final_url)
            filename = Path(urllib.parse.unquote(parsed.path)).name or "pitch-download.bin"
            target = Path(filename).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        return target


def _download_is_direct_file(url: str) -> bool:
    path = urllib.parse.urlparse(url).path.lower()
    if path.endswith((".asp", ".aspx", ".php", ".htm", ".html")):
        return False
    return bool(Path(path).suffix)


def _download_target_platform() -> str:
    if _is_windows_platform():
        return "windows64" if platform.architecture()[0] == "64bit" else "windows32"
    if _is_linux_platform():
        return "linux64" if platform.machine().endswith("64") else "linux32"
    if _is_macos_platform():
        return "mac"
    return "windows64"


def _download_candidate_urls(page_url: str) -> list[str]:
    request = urllib.request.Request(
        page_url,
        headers={
            "User-Agent": PITCH_FREE_DOWNLOAD_HEADERS["User-Agent"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": PITCH_FREE_DOWNLOAD_URL,
        },
        method="GET",
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8", errors="replace")

    hrefs = re.findall(r"""href=['"]([^'"]+)['"]""", html, flags=re.IGNORECASE)
    resolved: list[str] = []
    for href in hrefs:
        candidate = urllib.parse.urljoin(page_url, href)
        if _download_is_direct_file(candidate):
            resolved.append(candidate)
    return resolved


def _download_pick_candidate(page_url: str, candidates: list[str], *, filename: str | None = None, platform_hint: str | None = None) -> str:
    if filename:
        for candidate in candidates:
            if Path(urllib.parse.urlparse(candidate).path).name == filename:
                return candidate
        raise RuntimeError(f"Could not find installer named {filename} at {page_url}")

    hint = platform_hint or _download_target_platform()
    if hint == "windows64":
        order = ("windows64", "windows32", "linux64", "linux32", "mac")
    elif hint == "windows32":
        order = ("windows32", "windows64", "linux32", "linux64", "mac")
    elif hint == "linux64":
        order = ("linux64", "linux32", "windows64", "windows32", "mac")
    elif hint == "linux32":
        order = ("linux32", "linux64", "windows32", "windows64", "mac")
    elif hint == "mac":
        order = ("mac", "windows64", "windows32", "linux64", "linux32")
    else:
        order = (hint,)

    for token in order:
        for candidate in candidates:
            name = Path(urllib.parse.urlparse(candidate).path).name.lower()
            if token in name:
                return candidate

    raise RuntimeError(f"Could not resolve an installer link from {page_url}")


def handle_download(args: argparse.Namespace) -> int:
    parser = getattr(args, "parser", None)
    if parser is not None:
        parser.print_help()
    else:
        print("Usage: pitch download init --email you@example.com | pitch download submit --email you@example.com")
    return 0


def handle_download_init(args: argparse.Namespace) -> int:
    config_path = _download_contact_path()
    if config_path.exists() and not args.force:
        print(f"Config already exists: {config_path}. Use --force to overwrite.")
        return 0

    payload = _load_download_contact_defaults()
    payload["destination_email"] = args.email
    _write_json_file(config_path, payload)
    print(f"Wrote {config_path} with destination_email={args.email}")
    return 0


def handle_download_bookmarklet(args: argparse.Namespace) -> int:
    contact = _load_download_contact()
    if args.email:
        contact["destination_email"] = args.email

    bookmarklet = _download_bookmarklet_source(contact)
    print(bookmarklet)
    return 0


def handle_download_script(args: argparse.Namespace) -> int:
    if args.email:
        contact = _load_download_contact()
        contact["destination_email"] = args.email
        print(_download_script_source(contact))
        return 0

    if DOWNLOAD_SCRIPT_PATH.exists():
        print(DOWNLOAD_SCRIPT_PATH.read_text(encoding="utf-8"))
        return 0

    contact = _load_download_contact()
    print(_download_script_source(contact))
    return 0


def handle_download_submit(args: argparse.Namespace) -> int:
    contact = _load_download_contact()
    if args.email:
        contact["destination_email"] = args.email
    if args.first_name:
        contact["first_name"] = args.first_name
    if args.last_name:
        contact["last_name"] = args.last_name
    if args.title:
        contact["title"] = args.title
    if args.organization:
        contact["organization"] = args.organization
    if args.organization_type:
        contact["organization_type"] = args.organization_type
    if args.products:
        contact["accepted_products"] = args.products
    if args.newsletter:
        contact["subscribe_newsletter"] = True

    payload = _download_submission_payload(contact)
    if args.dry_run:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    request = _download_submit_request(contact)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        print(f"Could not submit Pitch free download request: {exc}", file=sys.stderr)
        return 1

    if "Done." in body or "Sending download information" in body:
        print(f"Pitch free download request submitted for {payload['email']}.")
        return 0

    print("Pitch free download request sent, but the response was unexpected.", file=sys.stderr)
    print(body[:2000], file=sys.stderr)
    return 1


def handle_download_fetch(args: argparse.Namespace) -> int:
    _print_active_route_banner()
    try:
        url = args.url
        if _download_is_direct_file(url):
            resolved_url = url
        else:
            platform_hint = None if args.platform == "auto" else args.platform
            resolved_url = _download_pick_candidate(url, _download_candidate_urls(url), filename=args.filename, platform_hint=platform_hint)
        downloaded_path = _download_url(resolved_url, _coerce_cli_path(args.output) if args.output else None)
    except urllib.error.URLError as exc:
        print(f"Could not download {args.url}: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Downloaded {args.url} to {downloaded_path}")
    return 0


def handle_settings(args: argparse.Namespace) -> int:
    parser = getattr(args, "parser", None)
    if getattr(args, "settings_command", None) is None:
        if parser is not None:
            parser.print_help()
        else:
            print("Usage: pitch settings show")
        return 0
    return int(args.handler(args))


def handle_settings_show(args: argparse.Namespace) -> int:
    _print_crc_settings_summary()
    return 0


def handle_settings_set(args: argparse.Namespace) -> int:
    key = str(args.key)
    value = str(args.value)
    try:
        settings_files = set_crc_setting_everywhere(_discover_crc_settings_files(), key, value)
    except FileNotFoundError:
        print("CRC settings: no settings file was discovered.", file=sys.stderr)
        return 1

    print(f"Updated {len(settings_files)} CRC settings file(s):")
    for settings_file in settings_files:
        print(f"  {settings_file}")
    return 0


def handle_start(args: argparse.Namespace) -> int:
    _print_active_route_banner()
    target = str(args.target or "menu")
    if target.strip().lower() == "menu":
        _show_menu()
        try:
            choice = input("Enter a number: ").strip().lower()
        except EOFError:
            print("No action selected.")
            return 0
        action = _lookup_start_action(choice)
        if action is None:
            print("No action selected.")
            return 0
        _run_start_action(action, args)
        if args.probe_ports:
            print("Probing configured ports...")
            results = _probe_results_for_start(args)
            if args.strict_probe and not all(open_ for _, open_ in results):
                raise RuntimeError("One or more configured ports are closed.")
        return 0

    action = _lookup_start_action(target)
    if action is None:
        raise RuntimeError("Usage: pitch start [menu|hlastarterkit|pitchvisualomt|prti1516e|docs|plugin|root]")

    if action.alias == "prti1516e":
        _apply_requested_hla4_preview(args, context="start", require_settings=False)
        _print_crc_settings_summary()

    _run_start_action(action, args)
    if args.probe_ports:
        print("Probing configured ports...")
        results = _probe_results_for_start(args)
        if args.strict_probe and not all(open_ for _, open_ in results):
            raise RuntimeError("One or more configured ports are closed.")
    return 0


def handle_route(args: argparse.Namespace) -> int:
    if getattr(args, "route_command", None) is None:
        return handle_route_show(args)
    return int(args.handler(args))


def handle_route_show(args: argparse.Namespace) -> int:
    _print_route_visibility(include_wsl_distros=True)
    return 0


def handle_route_run(args: argparse.Namespace) -> int:
    pitch_args = list(args.pitch_args or [])
    if pitch_args and pitch_args[0] == "--":
        pitch_args = pitch_args[1:]

    route_name = args.route
    if route_name == "auto":
        route_name = _default_route_name()

    return _run_route_command(route_name, pitch_args, wsl_distro=getattr(args, "wsl_distro", None))


def handle_rti(args: argparse.Namespace) -> int:
    if getattr(args, "rti_command", None) is None:
        print("Usage: pitch rti smoke")
        return 0
    return int(args.handler(args))


def handle_rti_smoke(args: argparse.Namespace) -> int:
    if getattr(args, "smoke_command", None) == "chat":
        return int(args.handler(args))
    return _run_rti_smoke_test()


def handle_rti_smoke_chat(args: argparse.Namespace) -> int:
    return _run_chat_smoke_test(getattr(args, "variant", "auto"), list_only=getattr(args, "list", False))


def _run_route_command(route_name: str, pitch_args: list[str], wsl_distro: str | None = None) -> int:
    return _run_route_command_impl(
        route_name,
        pitch_args,
        wsl_distro=wsl_distro,
        available_wsl_distros=_wsl_distribution_names() if route_name == "wsl" else None,
        docker_env_file=DOCKER_ENV_PATH,
        native_runner=main,
        docker_preflight=_docker_preflight_check,
    )


def _installed_components() -> set[str]:
    return _installed_components_impl(
        state_installed_components=_state_installed_components(),
        system=_platform_system(),
        windows_system_installed_components=_windows_system_installed_components,
        linux_system_installed_components=_linux_system_installed_components,
    )


def _detected_install_roots() -> dict[str, Path]:
    return _detected_install_roots_impl(
        system=_platform_system(),
        discover_windows_install_locations_fn=discover_windows_install_locations,
        discover_linux_install_locations_fn=discover_linux_install_locations,
    )


def _install_specs_for_system(include_legacy_rti: bool) -> list[InstallSpec]:
    return _install_specs_for_system_impl(_platform_system(), include_legacy_rti)


def _discover_installed_runtime_launcher(component_key: str) -> Path | None:
    return _discover_installed_runtime_launcher_impl(
        component_key,
        system=_platform_system(),
        configured_roots=_configured_install_roots(),
    )


def _start_actions() -> list[StartAction]:
    return _start_actions_impl(_platform_system(), ASSET_ROOT, ROOT)


def _lookup_start_action(target: str) -> StartAction | None:
    return _lookup_start_action_impl(target, _start_actions())


def _show_menu() -> None:
    return _show_menu_impl(_platform_system(), ASSET_ROOT, ROOT)


def _run_start_action(action: StartAction, args: argparse.Namespace) -> None:
    return _run_start_action_impl(
        action,
        args,
        workspace_root=ROOT,
        discovered_launcher=_discover_installed_runtime_launcher,
        open_path=_open_path,
        launch_program=_launch_program,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        argv = ["start"]

    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0

    try:
        return int(handler(args))
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
