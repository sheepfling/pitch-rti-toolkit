"""Unified Pitch command line entry point."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import platform
import shlex
import re
import shutil
import subprocess
import sys
import tempfile
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


ASSET_ROOT = resolve_asset_root(ROOT)
USER_DATA_ROOT = resolve_user_data_root()
INSTALLER_DROP_ROOT = resolve_installer_drop_root()
DOWNLOAD_CONTACT_FILENAME = ".pitch-download-contact.json"
DOWNLOAD_CONTACT_TEMPLATE = ASSET_ROOT / "download-contact.example.json"
DOWNLOAD_SCRIPT_PATH = ASSET_ROOT / "download-autofill.js"
PREFLIGHT_ARTIFACT_ROOT = USER_DATA_ROOT / "preflight"
PREFLIGHT_ARTIFACT_FILENAME = "pitch-preflight.json"
DOCKER_ENV_FILENAME = "pitch-compose.env"
DOCKER_ENV_ROOT = USER_DATA_ROOT / "docker"
DOCKER_ENV_PATH = DOCKER_ENV_ROOT / DOCKER_ENV_FILENAME
VENDOR_DOCKER_ENV_FILENAME = "pitch-vendor-compose.env"
VENDOR_DOCKER_ENV_PATH = DOCKER_ENV_ROOT / VENDOR_DOCKER_ENV_FILENAME
VENDOR_DOCKER_SETTINGS_ROOT = DOCKER_ENV_ROOT / "vendor-settings"
VENDOR_CRC_SETTINGS_PATH = VENDOR_DOCKER_SETTINGS_ROOT / "prti1516eCRC.settings"
VENDOR_LRC_SETTINGS_PATH = VENDOR_DOCKER_SETTINGS_ROOT / "prti1516eLRC.settings"
VENDOR_DOCKER_COMPOSE_PATH = ROOT / "docker" / "pitch-vendor-compose.yml"
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
    ),
    "java-hla4-fedpro": (
        "chat-java-hla4-fedpro/chat-java-hla4-fedpro.bat",
        "chat-java-hla4-fedpro/chat-java-hla4-fedpro.cmd",
    ),
    "cpp-hla4": (
        "chat-cpp-hla4/chat-cpp-hla4_vc140_32.exe",
        "chat-cpp-hla4/chat-cpp-hla4_vc140_64.exe",
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
}


def _is_wsl() -> bool:
    release = platform.release().lower()
    return bool(
        os.environ.get("WSL_DISTRO_NAME")
        or os.environ.get("WSL_INTEROP")
        or "microsoft" in release
    )


def _looks_like_windows_path(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value))


def _translate_windows_path(value: str) -> Path:
    drive = value[0].lower()
    remainder = value[2:].replace("\\", "/").lstrip("/")
    return Path(f"/mnt/{drive}/{remainder}")


def _coerce_cli_path(value: str) -> Path:
    if _is_wsl() and _looks_like_windows_path(value):
        return _translate_windows_path(value)
    return Path(value).expanduser()


def _coerce_env_path(value: str) -> Path:
    if _is_wsl() and _looks_like_windows_path(value):
        return _translate_windows_path(value)
    return Path(value).expanduser()


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
        return shutil.which("wsl.exe") is not None
    if route_name == "docker":
        return _docker_compose_available()
    return False


def _default_route_name() -> str:
    system = platform.system()
    if system == "Darwin":
        return "native"
    return "native"


def _default_route_reason() -> str:
    system = platform.system()
    if system == "Windows":
        return "Windows now stays on native execution by default."
    if system == "Darwin":
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
    if shutil.which("wsl.exe") is None:
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
    if shutil.which("wsl.exe") is None:
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
    override = os.environ.get("PITCH_VENDOR_DOCKER_ENV_FILE", "").strip()
    if override:
        return _coerce_env_path(override)
    return VENDOR_DOCKER_ENV_PATH


def _vendor_docker_settings_root() -> Path:
    override = os.environ.get("PITCH_VENDOR_DOCKER_SETTINGS_ROOT", "").strip()
    if override:
        return _coerce_env_path(override)
    return VENDOR_DOCKER_SETTINGS_ROOT


def _vendor_crc_settings_path() -> Path:
    return _vendor_docker_settings_root() / "prti1516eCRC.settings"


def _docker_service_name() -> str:
    profile = os.environ.get("PITCH_DOCKER_PROFILE", "future").strip().lower()
    if profile == "hla4":
        return "pitch-hla4"
    return "pitch-future"


def _vendor_docker_install_root() -> Path | None:
    override = os.environ.get("PITCH_PRTI_HOME", "").strip()
    if override:
        candidate = _coerce_env_path(override)
        return candidate if candidate.exists() else None
    return _discover_prti_install_root()


def _docker_compose_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        completed = subprocess.run(["docker", "compose", "version"], check=False, capture_output=True, text=True)
    except OSError:
        return False
    return completed.returncode == 0


def _route_payload_command(pitch_args: list[str], route_name: str, wsl_distro: str | None = None) -> list[str]:
    if route_name == "native":
        return []

    if route_name == "wsl":
        pitch_args = _translate_route_args_for_wsl(pitch_args)
    if route_name == "docker":
        env_file = _docker_env_path()
        command = [
            "docker",
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
    if shutil.which("docker") is None:
        return ("missing", "Could not find the Docker CLI. Install Docker Desktop or Docker Engine first.", False)

    try:
        completed = subprocess.run(["docker", "info"], check=False, capture_output=True, text=True)
    except OSError as exc:
        return ("missing", f"Could not reach the Docker CLI to verify the daemon: {exc}", False)

    if completed.returncode == 0:
        try:
            compose = subprocess.run(["docker", "compose", "version"], check=False, capture_output=True, text=True)
        except OSError as exc:
            return ("blocked", f"Docker daemon is reachable, but Docker Compose is unavailable: {exc}", False)
        if compose.returncode == 0:
            return ("ok", "Docker daemon and Docker Compose are reachable.", True)
        compose_output = "\n".join(
            part.strip()
            for part in (getattr(compose, "stdout", "") or "", getattr(compose, "stderr", "") or "")
            if part and part.strip()
        )
        if compose_output:
            return ("blocked", f"Docker daemon is reachable, but Docker Compose is unavailable.\n{compose_output}", False)
        return ("blocked", "Docker daemon is reachable, but Docker Compose is unavailable.", False)

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

    command = _route_payload_command(pitch_args, route_name, wsl_distro=resolved_wsl_distro)
    route_env = os.environ.copy()
    route_env.update(_route_payload_env(route_name, wsl_distro=resolved_wsl_distro))
    completed = subprocess.run(command, check=False, env=route_env)
    return int(completed.returncode)


def _route_payload_env(route_name: str, wsl_distro: str | None = None) -> dict[str, str]:
    if route_name not in {"wsl", "docker"}:
        return {}
    payload = {"PITCH_ROUTE_CONTEXT": route_name}
    if route_name == "wsl" and wsl_distro:
        payload["PITCH_WSL_DISTRO"] = wsl_distro
    if route_name == "docker":
        payload["PITCH_DOCKER_PROFILE"] = os.environ.get("PITCH_DOCKER_PROFILE", "future").strip().lower() or "future"
        payload["PITCH_USER_DATA_ROOT"] = str(USER_DATA_ROOT)
        payload["PITCH_INSTALLER_DROP_ROOT"] = str(INSTALLER_DROP_ROOT)
        payload["PITCH_PREFLIGHT_ARTIFACT_ROOT"] = str(PREFLIGHT_ARTIFACT_ROOT)
        payload["PITCH_DOCKER_ENV_FILE"] = str(_docker_env_path())
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

    config_show_parser = config_subparsers.add_parser("show", help="Show .pitch-install-roots.json or the detected roots.")
    config_show_parser.set_defaults(handler=handle_config_show)

    config_init_parser = config_subparsers.add_parser("init", help="Generate .pitch-install-roots.json from detected installs.")
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

    docker_down_parser = docker_subparsers.add_parser("down", help="Stop the vendor pRTI container with Docker Compose.")
    docker_down_parser.set_defaults(handler=handle_docker_down)

    docker_status_parser = docker_subparsers.add_parser("status", help="Show the vendor Docker setup paths.")
    docker_status_parser.set_defaults(handler=handle_docker_status)

    settings_parser = subparsers.add_parser("settings", help="Discover CRC settings files and HLA 4 Preview state.")
    settings_subparsers = settings_parser.add_subparsers(dest="settings_command")
    settings_parser.set_defaults(handler=handle_settings, parser=settings_parser)

    settings_show_parser = settings_subparsers.add_parser("show", help="Show the discovered CRC settings and HLA 4 Preview state.")
    settings_show_parser.set_defaults(handler=handle_settings_show)

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
    start_parser.add_argument("--ports-config", default=str(ASSET_ROOT / "ports.conf"), help="Port probe configuration file.")
    start_parser.set_defaults(handler=handle_start)

    return parser


def _verify_paths() -> list[str]:
    failures = []
    failures.extend(verify_paths_exist(ROOT, VERIFY_REQUIRED_PATHS))
    failures.extend(verify_manifest(ROOT, ASSET_ROOT / "checksums.sha256"))
    return failures


def _verify_setup_paths() -> list[str]:
    return verify_paths_exist(ROOT, SETUP_REQUIRED_PATHS)


def _state_file() -> Path:
    return install_state_path(ROOT)


def _fresh_state() -> dict[str, object]:
    return {
        "version": 1,
        "bundle_fingerprint": bundle_fingerprint(ROOT),
        "platform": platform.system(),
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
    state["platform"] = platform.system()
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
    state["platform"] = platform.system()
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
        "platform": platform.system(),
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
    system = platform.system()
    if system == "Windows":
        installed.update(_windows_system_installed_components())
    elif system == "Linux":
        installed.update(_linux_system_installed_components())
    return installed


def _detected_install_roots() -> dict[str, Path]:
    system = platform.system()
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
    system = platform.system()
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
    return "py -3" if platform.system() == "Windows" else "python3"


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


def _open_path(path: Path) -> None:
    system = platform.system()
    if system == "Windows":
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
            return
        except (OSError, PermissionError):
            try:
                subprocess.Popen(["explorer.exe", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError as exc:
                raise RuntimeError(f"Could not open path: {path}") from exc

    opener: list[str] | None = None
    if system == "Darwin":
        opener = ["open", str(path)]
    elif shutil.which("xdg-open"):
        opener = ["xdg-open", str(path)]
    elif shutil.which("gio"):
        opener = ["gio", "open", str(path)]

    if opener is None:
        raise RuntimeError(f"No folder opener found for: {path}")

    subprocess.Popen(opener, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _launch_program(path: Path, env: dict[str, str] | None = None) -> None:
    system = platform.system()
    child_env = os.environ.copy()
    if env:
        child_env.update(env)

    if system == "Windows":
        if path.suffix.lower() in {".bat", ".cmd"}:
            subprocess.Popen(["cmd.exe", "/c", str(path)], cwd=str(path.parent), env=child_env)
        else:
            subprocess.Popen([str(path)], cwd=str(path.parent), env=child_env)
        return

    if path.suffix.lower() == ".sh" or path.name.endswith(".sh"):
        subprocess.Popen(["bash", str(path)], cwd=str(path.parent), env=child_env)
        return

    subprocess.Popen([str(path)], cwd=str(path.parent), env=child_env)


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

    if _is_wsl():
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


def _discover_crc_settings_files() -> list[Path]:
    hits: list[Path] = []
    seen: set[str] = set()
    roots = _crc_settings_search_roots()

    for name in CRC_SETTINGS_NAME_HINTS:
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


def _parse_settings_entries(path: Path) -> list[tuple[str, str]]:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    entries: list[tuple[str, str]] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        else:
            continue
        key = key.strip()
        value = value.strip()
        if key:
            entries.append((key, value))
    return entries


def _settings_flag_state(entries: list[tuple[str, str]], key_name: str) -> bool | None:
    normalized_key = key_name.strip().lower()
    for key, value in entries:
        if key.strip().lower() != normalized_key:
            continue
        normalized_value = value.strip().lower()
        if normalized_value in {"true", "1", "yes", "on"}:
            return True
        if normalized_value in {"false", "0", "no", "off"}:
            return False
        return None
    return None


def _print_settings_entries(path: Path, entries: list[tuple[str, str]]) -> None:
    print(f"CRC settings file: {path}")
    preview = _settings_flag_state(entries, "CRC.enableHla4PreviewFeatures")
    if preview is None:
        print("  HLA 4 Preview features enabled: unknown")
    elif preview:
        print("  HLA 4 Preview features enabled: yes")
    else:
        print("  HLA 4 Preview features enabled: no")

    if not entries:
        print("  No key/value settings could be parsed.")
        return

    print("  All settings:")
    for key, value in entries:
        print(f"    {key} = {value}")


def _print_crc_settings_summary() -> None:
    settings_files = _discover_crc_settings_files()
    if not settings_files:
        print("CRC settings: no settings file was discovered.")
        print("  Search roots:")
        for root in _crc_settings_search_roots():
            print(f"    - {root}")
        return

    print("CRC settings discovery:")
    for settings_file in settings_files:
        entries = _parse_settings_entries(settings_file)
        _print_settings_entries(settings_file, entries)


def _maybe_print_prti_settings_summary(triggered: bool) -> None:
    if triggered:
        _print_crc_settings_summary()


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
        for filename in ("prti1516e-free_5_5_10_windows64.exe", "prti1516e-free_5_5_10_windows32.exe"):
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
    system = platform.system()
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
    if platform.system() == "Windows" and launcher.suffix.lower() in {".bat", ".cmd"}:
        return ["cmd.exe", "/c", str(launcher)]
    return [str(launcher)]


def _run_chat_process(command: list[str], *, cwd: Path, username: str, host: str, message: str, final_message: str = ".") -> tuple[int, str]:
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError as exc:
        raise RuntimeError(f"Could not start chat sample: {exc}") from exc

    stdin_payload = f"{host}\n{username}\n{message}\n{final_message}\n"
    try:
        output, _ = process.communicate(stdin_payload, timeout=90)
    except subprocess.TimeoutExpired:
        process.kill()
        output, _ = process.communicate()
        raise RuntimeError(f"Timed out while running chat sample: {command[0]}") from None

    return int(process.returncode or 0), output


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
    host = os.environ.get("PITCH_RTI_SMOKE_HOST", "localhost")
    messages = [
        ("pitch-smoke-alpha", "Hello from pitch-smoke-alpha"),
        ("pitch-smoke-bravo", "Hello from pitch-smoke-bravo"),
    ]

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
        elif "Type messages you want to send" not in output:
            failures.append(f"chat federate {index} did not reach the chat prompt")

    if failures:
        print("Pitch chat smoke test failed.", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print("Pitch chat smoke test passed.")
    return 0


def _start_actions() -> list[StartAction]:
    system = platform.system()
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
            StartAction("3", "Docs", "folder", ASSET_ROOT / "docs", "docs"),
            StartAction("4", "Plugin", "folder", ASSET_ROOT / "plugin", "plugin"),
            StartAction("5", "Project Root", "folder", ROOT, "root"),
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
    if getattr(args, "port", None) is not None:
        launch_env["PITCH_PORT"] = str(args.port)
    if getattr(args, "ports_config", None):
        launch_env["PITCH_PORTS_CONFIG"] = str((ROOT / args.ports_config).resolve() if not Path(args.ports_config).is_absolute() else Path(args.ports_config))

    _launch_program(launcher, env=launch_env)


def _run_rti_smoke_test() -> int:
    launcher = _discover_installed_runtime_launcher("prti1516e")
    if launcher is None:
        print("No installed Pitch RTI launcher was found.", file=sys.stderr)
        return 1

    if platform.system() == "Windows" and launcher.suffix.lower() in {".bat", ".cmd"}:
        command = ["cmd.exe", "/c", str(launcher)]
    else:
        command = [str(launcher)]

    try:
        process = subprocess.Popen(
            command,
            cwd=str(launcher.parent),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            output, _ = process.communicate("HELP\n", timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate()
    except OSError as exc:
        print(f"Could not start the Pitch RTI launcher: {exc}", file=sys.stderr)
        return 1

    if "Available commands:" in output and "HELP" in output:
        _mark_rti_smoke_result(True, str(launcher))
        print("Pitch RTI smoke test passed.")
        return 0

    _mark_rti_smoke_result(False, str(launcher))
    print("Pitch RTI smoke test failed.", file=sys.stderr)
    if output:
        print(output, file=sys.stderr)
    return 1


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
    if platform.system() == "Windows" and not args.include_legacy_rti:
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

    if platform.system() == "Linux" and args.include_legacy_rti:
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
        if spec.key == "prti1516e" and platform.system() != "Windows":
            continue

        print(f"Launching {spec.label} from {installer_path}...")
        run_installer(installer_path, cwd=ROOT, quiet=args.silent_install)
        _mark_component_installed(spec.key, spec.label, "installer", str(installer_path))
        if spec.key == "prti1516e":
            _maybe_print_prti_settings_summary(True)

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
            raise RuntimeError(f"Could not read {config_path.name}: {exc}") from exc

        print(f"{config_path.name}:")
        _print_install_roots_payload(payload if isinstance(payload, dict) else {"value": payload})
        return 0

    detected_roots = _detected_install_roots()
    if not detected_roots:
        print(f"No {config_path.name} file exists and no Pitch roots were detected.")
        return 1

    system = platform.system()
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

    print(f"{config_path.name} does not exist; detected roots would be:")
    _print_install_roots_payload(payload)
    return 0


def handle_config_init(args: argparse.Namespace) -> int:
    config_path = install_roots_path(ROOT)
    if config_path.exists() and not args.force:
        print(f"Config already exists: {config_path.name}. Use --force to overwrite.")
        return 0

    detected_roots = _detected_install_roots()
    if not detected_roots:
        print("No installed Pitch roots were detected, so nothing was written.")
        return 1

    system = platform.system()
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
    print(f"Wrote {config_path.name}:")
    for key, value in sorted(detected_roots.items()):
        print(f"  {key} -> {value}")
    return 0


def handle_config_assets(args: argparse.Namespace) -> int:
    print("Writable asset locations:")
    print(f"  user data root: {USER_DATA_ROOT}")
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
        print("Usage: pitch assets init | pitch assets import <source-folder>")
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


def _docker_env_payload(profile: str = "future") -> dict[str, str]:
    normalized = profile.strip().lower() or "future"
    if normalized not in {"future", "hla4"}:
        raise ValueError("Docker profile must be either 'future' or 'hla4'.")

    payload = {
        "PITCH_ASSET_ROOT": str(ASSET_ROOT),
        "PITCH_USER_DATA_ROOT": str(USER_DATA_ROOT),
        "PITCH_INSTALLER_DROP_ROOT": str(INSTALLER_DROP_ROOT),
        "PITCH_PREFLIGHT_ARTIFACT_ROOT": str(PREFLIGHT_ARTIFACT_ROOT),
        "PITCH_DOCKER_PROFILE": normalized,
        "PITCH_RELEASE_CHANNEL": normalized,
    }
    return payload


def _write_docker_env_file(path: Path, payload: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Generated by pitch docker init", "# Safe to edit locally; not tracked by git."]
    for key, value in payload.items():
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _copy_vendor_settings(src_root: Path, dest_root: Path) -> None:
    dest_root.mkdir(parents=True, exist_ok=True)
    for filename in ("prti1516eCRC.settings", "prti1516eLRC.settings"):
        source = src_root / "samples" / "docker" / filename
        if source.exists():
            shutil.copy2(source, dest_root / filename)


def _set_settings_value(path: Path, key: str, value: str) -> None:
    lines: list[str] = []
    found = False
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []

    updated: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}="):
            updated.append(f"{key}={value}")
            found = True
        else:
            updated.append(line)
    if not found:
        updated.append(f"{key}={value}")
    path.write_text("\n".join(updated) + "\n", encoding="utf-8")


def _read_settings_value(path: Path, key: str) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}="):
            return stripped.split("=", 1)[1].strip()
    return None


def _vendor_docker_payload(*, enable_hla4_preview: bool = False) -> dict[str, str]:
    install_root = _vendor_docker_install_root()
    if install_root is None:
        raise ValueError("Could not find a pRTI installation root. Set PITCH_PRTI_HOME or install pRTI first.")

    payload = {
        "PITCH_PRTI_HOME": str(install_root),
        "PITCH_VENDOR_DOCKER_SETTINGS_ROOT": str(_vendor_docker_settings_root()),
        "PITCH_VENDOR_DOCKER_ENV_FILE": str(_vendor_docker_env_path()),
        "LICENSE_SERVER": os.environ.get("LICENSE_SERVER", "pfls"),
        "FEDERATE_COUNT": os.environ.get("FEDERATE_COUNT", "5"),
        "DISABLE_WEB_VIEW": os.environ.get("DISABLE_WEB_VIEW", ""),
        "JAVA_OPTS": os.environ.get("JAVA_OPTS", "-XX:+UseParallelGC -XX:MaxRAMPercentage=75"),
    }
    if enable_hla4_preview:
        payload["CRC_ENABLE_HLA4_PREVIEW"] = "1"
    return payload


def handle_docker(args: argparse.Namespace) -> int:
    parser = getattr(args, "parser", None)
    if getattr(args, "docker_command", None) is None:
        if parser is not None:
            parser.print_help()
        else:
            print("Usage: pitch docker init | pitch docker up | pitch docker down | pitch docker status")
        return 0
    return int(args.handler(args))


def handle_docker_init(args: argparse.Namespace) -> int:
    env_path = _vendor_docker_env_path()
    settings_root = _vendor_docker_settings_root()
    if env_path.exists() and settings_root.exists() and not args.force:
        print(f"Vendor Docker env file already exists: {env_path}")
        print("Use --force to overwrite it.")
        return 0

    try:
        payload = _vendor_docker_payload(enable_hla4_preview=getattr(args, "enable_hla4_preview", False))
        if args.force and env_path.exists():
            env_path.unlink()
        _copy_vendor_settings(Path(payload["PITCH_PRTI_HOME"]), settings_root)
        if getattr(args, "enable_hla4_preview", False):
            _set_settings_value(_vendor_crc_settings_path(), "CRC.enableHla4PreviewFeatures", "true")
        _write_docker_env_file(env_path, payload)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Wrote vendor Docker env file: {env_path}")
    print(f"Wrote vendor settings overlay: {settings_root}")
    for key, value in payload.items():
        print(f"  {key}={value}")
    return 0


def _vendor_docker_compose_command(action: str) -> list[str]:
    env_file = _vendor_docker_env_path()
    if not env_file.exists():
        raise FileNotFoundError(f"Vendor Docker env file not found: {env_file}. Run `pitch docker init` first.")
    command = [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-f",
        str(VENDOR_DOCKER_COMPOSE_PATH),
    ]
    command.extend(action.split())
    return command


def handle_docker_up(args: argparse.Namespace) -> int:
    try:
        command = _vendor_docker_compose_command("up -d --build pitch-crc")
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    completed = subprocess.run(command, check=False)
    return int(completed.returncode)


def handle_docker_down(args: argparse.Namespace) -> int:
    try:
        command = _vendor_docker_compose_command("down")
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    completed = subprocess.run(command, check=False)
    return int(completed.returncode)


def handle_docker_status(args: argparse.Namespace) -> int:
    print("Vendor Docker setup:")
    print(f"  pRTI home: {_vendor_docker_install_root() or 'missing'}")
    print(f"  env file: {_vendor_docker_env_path()}")
    print(f"  vendor settings overlay: {_vendor_docker_settings_root()}")
    print(f"  compose file: {VENDOR_DOCKER_COMPOSE_PATH}")
    initialized = _vendor_docker_env_path().exists() and _vendor_docker_settings_root().exists()
    print(f"  initialized: {'yes' if initialized else 'no'}")
    crc_settings_path = _vendor_crc_settings_path()
    if crc_settings_path.exists():
        preview = _read_settings_value(crc_settings_path, "CRC.enableHla4PreviewFeatures")
        if preview is not None:
            print(f"  HLA 4 Preview: {preview}")
    return 0


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


def _download_contact_path() -> Path:
    return ROOT / DOWNLOAD_CONTACT_FILENAME


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
    system = platform.system()
    if system == "Windows":
        return "windows64" if platform.architecture()[0] == "64bit" else "windows32"
    if system == "Linux":
        return "linux64" if platform.machine().endswith("64") else "linux32"
    if system == "Darwin":
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
        print(f"Config already exists: {config_path.name}. Use --force to overwrite.")
        return 0

    payload = _load_download_contact_defaults()
    payload["destination_email"] = args.email
    _write_json_file(config_path, payload)
    print(f"Wrote {config_path.name} with destination_email={args.email}")
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
