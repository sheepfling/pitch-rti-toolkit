"""Route, launcher, and start-action helpers for Pitch."""

from __future__ import annotations

import argparse
import ctypes
import concurrent.futures
import os
import queue
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from ctypes import wintypes

from pitch.common import (
    coerce_env_path,
    has_command,
    is_linux_platform,
    is_macos_platform,
    is_wsl_environment,
    is_windows_platform,
    looks_like_windows_path,
    platform_system,
    resolved_docker_command,
    translate_windows_path,
)
from pitch.execution import launcher_command as execution_launcher_command
from pitch.execution import docker_compose_run_command, quoted_posix_command, wsl_command
from pitch.ports import route_rti_port
from pitch.settings import read_settings_value
from pitch_bootstrap import (
    ROOT,
    PortTarget,
    discover_file_locations,
    discover_linux_install_locations,
    discover_windows_install_locations,
    load_install_roots,
    install_roots_path,
    parse_ports_config,
    probe_targets,
    resolve_artifact_root,
    resolve_asset_root,
    resolve_installer_drop_root,
    resolve_user_data_root,
)


ASSET_ROOT = resolve_asset_root(ROOT)
USER_DATA_ROOT = resolve_user_data_root()
ARTIFACT_ROOT = resolve_artifact_root(ROOT)
INSTALLER_DROP_ROOT = resolve_installer_drop_root()
PREFLIGHT_ARTIFACT_ROOT = ARTIFACT_ROOT / "preflight"
DOCKER_ENV_PATH = ARTIFACT_ROOT / "docker" / "pitch-compose.env"
VENDOR_DOCKER_COMPOSE_PATH = ROOT / "docker" / "pitch-vendor-compose.yml"


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


WINDOWS_INSTALLATION_HINTS = {
    "HlaStarterKit": {
        "roots": (
            Path(r"C:\Program Files\Pitch\HlaStarterKit"),
            Path(r"C:\Program Files (x86)\Pitch\HlaStarterKit"),
        ),
        "names": ("HlaStarterKit", "HLA Starter Kit"),
        "launchers": (
            "bin/HlaStarterKit",
            "bin/HlaStarterKit.bat",
            "bin/simulationmanager.bat",
            "bin/MapViewer.bat",
        ),
    },
    "PitchVisualOMT": {
        "roots": (
            Path(r"C:\Program Files\Pitch\PitchVisualOMT"),
            Path(r"C:\Program Files (x86)\Pitch\PitchVisualOMT"),
        ),
        "names": ("PitchVisualOMT", "Pitch Visual OMT"),
        "launchers": ("bin/PitchVisualOMTFree", "bin/PitchVisualOMTFree.bat"),
    },
    "prti1516e-free": {
        "roots": (
            Path(r"C:\Program Files\prti1516e"),
            Path(r"C:\Program Files\prti1516e-free"),
            Path(r"C:\Program Files\Pitch\prti1516e"),
            Path(r"C:\Program Files\Pitch\prti1516e-free"),
            Path(r"C:\Program Files (x86)\prti1516e"),
            Path(r"C:\Program Files (x86)\prti1516e-free"),
            Path(r"C:\Program Files (x86)\Pitch\prti1516e"),
            Path(r"C:\Program Files (x86)\Pitch\prti1516e-free"),
        ),
        "names": ("prti1516e-free", "pRTI1516e", "Pitch pRTI"),
        "launchers": (
            "bin/pRTI1516e-nogui.bat",
            "bin/pRTI1516e.bat",
            "bin/Start pRTI Service.bat",
            "bin/pRTI1516e-nogui.cmd",
            "bin/pRTI1516e.cmd",
            "bin/Start pRTI Service.cmd",
        ),
    },
}

WINDOWS_COMPONENT_KEYS = {
    "HlaStarterKit": "hlastarterkit",
    "PitchVisualOMT": "pitchvisualomt",
    "prti1516e-free": "prti1516e",
}

WINDOWS_RUNTIME_LAUNCHERS = {
    "hlastarterkit": (
        "bin/HlaStarterKit.bat",
        "bin/simulationmanager.bat",
        "bin/MapViewer.bat",
    ),
    "pitchvisualomt": (
        "bin/PitchVisualOMTFree.bat",
    ),
    "prti1516e": (
        "bin/pRTI1516e-nogui.bat",
        "bin/pRTI1516e.bat",
        "bin/Start pRTI Service.bat",
        "bin/pRTI1516e-nogui.cmd",
        "bin/pRTI1516e.cmd",
        "bin/Start pRTI Service.cmd",
    ),
}

WINDOWS_INSTALLATION_ROOTS = {
    "hlastarterkit": (
        Path(r"C:\Program Files\Pitch\HlaStarterKit"),
        Path(r"C:\Program Files (x86)\Pitch\HlaStarterKit"),
        Path(r"C:\Program Files\HlaStarterKit"),
        Path(r"C:\Program Files (x86)\HlaStarterKit"),
    ),
    "pitchvisualomt": (
        Path(r"C:\Program Files\Pitch\PitchVisualOMT"),
        Path(r"C:\Program Files (x86)\Pitch\PitchVisualOMT"),
        Path(r"C:\Program Files\PitchVisualOMT"),
        Path(r"C:\Program Files (x86)\PitchVisualOMT"),
    ),
    "prti1516e": (
        Path(r"C:\Program Files\Pitch\prti1516e"),
        Path(r"C:\Program Files\Pitch\prti1516e-free"),
        Path(r"C:\Program Files (x86)\Pitch\prti1516e"),
        Path(r"C:\Program Files (x86)\Pitch\prti1516e-free"),
        Path(r"C:\Program Files\prti1516e"),
        Path(r"C:\Program Files\prti1516e-free"),
        Path(r"C:\Program Files (x86)\prti1516e"),
        Path(r"C:\Program Files (x86)\prti1516e-free"),
    ),
}

LINUX_INSTALLATION_HINTS = {
    "hlastarterkit": {
        "roots": (
            Path.home() / ".local" / "share" / "Pitch" / "HlaStarterKit",
            Path("/opt/Pitch/HlaStarterKit"),
            Path("/usr/local/Pitch/HlaStarterKit"),
        ),
        "launchers": (
            "federates/simulationmanager/bin/simulationmanager.sh",
            "federates/mapviewer/bin/mapviewer.sh",
            "federates/carsimj/bin/carsimj.sh",
            "federates/carsimc/bin/carsimc_x64.sh",
        ),
    },
    "pitchvisualomt": {
        "roots": (
            Path.home() / ".local" / "share" / "Pitch" / "PitchVisualOMT",
            Path("/opt/Pitch/PitchVisualOMT"),
            Path("/usr/local/Pitch/PitchVisualOMT"),
        ),
        "launchers": ("bin/PitchVisualOMTFree", "bin/PitchVisualOMTFree.sh", "PitchVisualOMTFree"),
    },
    "prti1516e": {
        "roots": (
            Path.home() / ".local" / "share" / "Pitch" / "prti1516e",
            Path.home() / ".local" / "share" / "Pitch" / "prti1516e-free",
            Path("/opt/Pitch/prti1516e"),
            Path("/opt/Pitch/prti1516e-free"),
            Path("/usr/local/Pitch/prti1516e"),
            Path("/usr/local/Pitch/prti1516e-free"),
        ),
        "launchers": (
            "bin/pRTI1516e-cmdline",
            "bin/pRTI1516e-cmdline.sh",
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
        "bin/pRTI1516e-cmdline",
        "bin/pRTI1516e-cmdline.sh",
        "bin/pRTI1516e-nogui",
        "bin/pRTI1516e-nogui.sh",
        "bin/pRTI1516e",
        "bin/pRTI1516e.sh",
        "bin/Start pRTI Service",
        "bin/Start pRTI Service.sh",
    ),
}

SETUP_WINDOWS_SPECS = [
    InstallSpec("hlastarterkit", "HlaStarterKit", ASSET_ROOT / "windows" / "HlaStarterKit_v1.0.2_windows64.exe"),
    InstallSpec("pitchvisualomt", "PitchVisualOMT", ASSET_ROOT / "windows" / "PitchVisualOMTFree_v2.7.0_windows64.exe"),
]

SETUP_WINDOWS_LEGACY_SPEC = InstallSpec("prti1516e", "prti1516e-free", ASSET_ROOT / "windows" / "prti1516e-free_5_5_10_windows32.exe")

SETUP_LINUX_SPECS = [
    InstallSpec("hlastarterkit", "HlaStarterKit", ASSET_ROOT / "linux" / "HlaStarterKit_v1.0.2_linux64.sh"),
    InstallSpec("pitchvisualomt", "PitchVisualOMT", ASSET_ROOT / "linux" / "PitchVisualOMTFree_v2.7.0_linux64.sh"),
    InstallSpec("prti1516e", "prti1516e-free", ASSET_ROOT / "linux" / "prti1516e-free_5_5_10_linux64.sh"),
]

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


def route_specs() -> list[RouteSpec]:
    return [
        RouteSpec("native", "Native", "Run directly on the current operating system."),
        RouteSpec("wsl", "WSL", "Run through WSL on Windows with Linux installers and Linux launcher discovery."),
        RouteSpec("docker", "Docker", "Run inside a Linux container through Docker Compose."),
    ]


def route_available(route_name: str) -> bool:
    if route_name == "native":
        return True
    if route_name == "wsl":
        return has_command("wsl.exe")
    if route_name == "docker":
        return resolved_docker_command() is not None
    return False


def default_route_name() -> str:
    return "native"


def default_route_reason() -> str:
    if is_windows_platform():
        return "Windows now stays on native execution by default."
    if is_macos_platform():
        return "macOS stays on native execution by default."
    return "Native execution is the default on this system."


def route_summary(route_name: str) -> str:
    if route_name == "native":
        return "Direct host execution."
    if route_name == "wsl":
        return "Windows host -> WSL Linux shell."
    if route_name == "docker":
        return "Docker Compose containerized execution."
    return "Unknown route."


def route_context_name(env: dict[str, str] | None = None) -> str | None:
    mapping = env or os.environ
    value = mapping.get("PITCH_ROUTE_CONTEXT", "").strip().lower()
    return value or None


def route_context_detail(env: dict[str, str] | None = None) -> str | None:
    mapping = env or os.environ
    route_name = route_context_name(mapping)
    if route_name == "wsl":
        distro = mapping.get("PITCH_WSL_DISTRO", "").strip()
        return distro or None
    if route_name == "docker":
        profile = mapping.get("PITCH_DOCKER_PROFILE", "").strip()
        return profile or None
    return None


def print_route_visibility(*, include_wsl_distros: bool = False) -> None:
    print("Route options:")
    for spec in route_specs():
        availability = "available" if route_available(spec.name) else "unavailable"
        print(f"  {spec.name}: {availability} - {spec.description}")
    print(f"  recommended: {default_route_name()} - {default_route_reason()}")
    print("  docker profiles: future (default), hla4")
    if include_wsl_distros:
        distros = wsl_distribution_names()
        if distros:
            numbered = ", ".join(f"{index + 1}: {name}" for index, name in enumerate(distros))
            print(f"  WSL distros: {numbered}")
            default_distro = wsl_default_distribution_name()
            if default_distro:
                print(f"  WSL default distro: {default_distro}")
            print("  WSL default: the configured default distro unless --wsl-distro is set")
            selected = route_context_detail()
            if selected:
                print(f"  WSL selected: {selected}")
        else:
            print("  WSL distros: none detected")


def print_active_route_banner() -> None:
    route_name = route_context_name()
    if route_name in {"wsl", "docker"}:
        label = route_name.upper()
        detail = route_context_detail()
        if detail:
            print(f"Selected route: {label} ({detail}; {route_summary(route_name)})")
        else:
            print(f"Selected route: {label} ({route_summary(route_name)})")


def wsl_command_path(path: Path) -> str:
    value = str(path)
    if looks_like_windows_path(value):
        return translate_windows_path(value).as_posix()
    return Path(value).as_posix()


def quote_posix_args(args: list[str]) -> str:
    return shlex.join(args)


def wsl_distribution_names() -> list[str]:
    if not has_command("wsl.exe"):
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


def wsl_default_distribution_name() -> str | None:
    if not has_command("wsl.exe"):
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


def resolve_wsl_distro_selection(selection: str | None, available_distros: list[str] | None = None) -> str | None:
    if selection is None:
        return None
    raw = selection.strip()
    if not raw or raw.lower() == "default":
        return None
    distros = available_distros if available_distros is not None else wsl_distribution_names()
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


def translate_route_args_for_wsl(pitch_args: list[str]) -> list[str]:
    translated: list[str] = []
    for arg in pitch_args:
        if looks_like_windows_path(arg):
            translated.append(wsl_command_path(translate_windows_path(arg)))
        else:
            translated.append(arg)
    return translated


def route_payload_command(
    pitch_args: list[str],
    route_name: str,
    *,
    wsl_distro: str | None = None,
    docker_env_file: Path | None = None,
    docker_compose_file: Path = ROOT / "docker" / "compose.yml",
    docker_service_name: str = "pitch-future",
) -> list[str]:
    if route_name == "native":
        return []
    if route_name == "wsl":
        return wsl_command(translate_route_args_for_wsl(pitch_args), wsl_distro=wsl_distro, workspace_root=ROOT)
    if route_name == "docker":
        docker_command = resolved_docker_command()
        if docker_command is None:
            raise RuntimeError("Could not find the Docker CLI. Install Docker Desktop or Docker Engine first.")
        return docker_compose_run_command(
            pitch_args,
            compose_file=docker_compose_file,
            service_name=docker_service_name,
            env_file=docker_env_file or DOCKER_ENV_PATH,
        )
    shell_command = quoted_posix_command(["python3", "-m", "pitch", *pitch_args]) if pitch_args else quoted_posix_command(["python3", "-m", "pitch"])
    volume = f"{ROOT.as_posix()}:/work"
    return ["docker", "run", "--rm", "-i", "-v", volume, "-w", "/work", "python:3.12", "sh", "-lc", shell_command]


def route_payload_env(route_name: str, *, wsl_distro: str | None = None, docker_env_file: Path | None = None) -> dict[str, str]:
    payload = {"PITCH_ROUTE_CONTEXT": route_name}
    if route_name == "native":
        payload["PITCH_PORT"] = str(discovered_prti_crc_port(default=route_rti_port("route-native")))
        payload["PITCH_PORT_PROFILE"] = "route-native"
        return payload
    if route_name == "wsl":
        if wsl_distro:
            payload["PITCH_WSL_DISTRO"] = wsl_distro
        payload["PITCH_PORT"] = str(discovered_prti_crc_port(default=route_rti_port("route-wsl")))
        payload["PITCH_PORT_PROFILE"] = "route-wsl"
        return payload
    if route_name == "docker":
        payload["PITCH_DOCKER_PROFILE"] = os.environ.get("PITCH_DOCKER_PROFILE", "future").strip().lower() or "future"
        payload["PITCH_USER_DATA_ROOT"] = str(USER_DATA_ROOT)
        payload["PITCH_INSTALLER_DROP_ROOT"] = str(INSTALLER_DROP_ROOT)
        payload["PITCH_PREFLIGHT_ARTIFACT_ROOT"] = str(PREFLIGHT_ARTIFACT_ROOT)
        payload["PITCH_DOCKER_ENV_FILE"] = str(docker_env_file or DOCKER_ENV_PATH)
        payload["PITCH_PORT"] = str(route_rti_port("route-docker"))
        payload["PITCH_PORT_PROFILE"] = "route-docker"
    return payload


def run_route_command(
    route_name: str,
    pitch_args: list[str],
    *,
    wsl_distro: str | None = None,
    available_wsl_distros: list[str] | None = None,
    docker_env_file: Path | None = None,
    native_runner: Callable[[list[str]], int] | None = None,
    docker_preflight: Callable[[], bool] | None = None,
    docker_compose_file: Path = ROOT / "docker" / "compose.yml",
    docker_service_name: str = "pitch-future",
) -> int:
    if route_name == "native":
        return int(native_runner(pitch_args) if native_runner is not None else 0)
    if not route_available(route_name):
        print(f"Route '{route_name}' is not available on this machine.", file=sys.stderr)
        return 1
    if route_name == "docker" and docker_preflight is not None and not docker_preflight():
        return 1
    resolved_wsl_distro = wsl_distro
    if route_name == "wsl":
        resolved_wsl_distro = resolve_wsl_distro_selection(wsl_distro, available_wsl_distros)
        if resolved_wsl_distro is None:
            resolved_wsl_distro = wsl_default_distribution_name()
    command = route_payload_command(
        pitch_args,
        route_name,
        wsl_distro=resolved_wsl_distro,
        docker_env_file=docker_env_file,
        docker_compose_file=docker_compose_file,
        docker_service_name=docker_service_name,
    )
    route_env = os.environ.copy()
    route_env.update(route_payload_env(route_name, wsl_distro=resolved_wsl_distro, docker_env_file=docker_env_file))
    completed = subprocess.run(command, check=False, env=route_env)
    return int(completed.returncode)


def normalize_install_roots(paths: list[Path]) -> list[Path]:
    roots: list[Path] = []
    for path in paths:
        candidate = path if path.is_dir() else path.parent
        if candidate not in roots:
            roots.append(candidate)
    return roots


def installer_search_roots() -> list[Path]:
    roots: list[Path] = []
    drop_root = resolve_installer_drop_root()
    if drop_root.exists():
        roots.append(drop_root)
    for path in (ASSET_ROOT, ASSET_ROOT / "windows", ASSET_ROOT / "linux", ROOT / "downloads", Path.home() / "Downloads", Path.home() / "downloads"):
        if path.exists() and path not in roots:
            roots.append(path)
    if has_command("wsl.exe"):
        for env_var in ("USERPROFILE", "LOCALAPPDATA", "APPDATA"):
            raw = os.environ.get(env_var)
            if not raw:
                continue
            path = coerce_env_path(raw)
            candidates = [path]
            if env_var == "USERPROFILE":
                candidates.append(path / "Downloads")
            for candidate in candidates:
                if candidate.exists() and candidate not in roots:
                    roots.append(candidate)
    return roots


def configured_install_roots() -> dict[str, Path]:
    try:
        return load_install_roots(install_roots_path(ROOT))
    except Exception:
        return {}


def resolve_launcher_from_root(root: Path, candidates: tuple[str, ...]) -> Path | None:
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


def resolve_installer_path(spec: InstallSpec, *, system: str | None = None) -> Path | None:
    system = system or platform_system()
    if spec.key == "prti1516e":
        if system == "Linux":
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
            hits = discover_file_locations(filename, installer_search_roots(), max_depth=4)
            if hits:
                return hits[0]
        return spec.path if spec.path.exists() else None
    if spec.path.exists():
        return spec.path
    hits = discover_file_locations(spec.path.name, installer_search_roots(), max_depth=4)
    return hits[0] if hits else None


def installed_components(
    *,
    state_installed_components: set[str],
    system: str,
    windows_system_installed_components: Callable[[], set[str]],
    linux_system_installed_components: Callable[[], set[str]],
) -> set[str]:
    installed = set(state_installed_components)
    if system == "Windows":
        installed.update(windows_system_installed_components())
    elif system == "Linux":
        installed.update(linux_system_installed_components())
    return installed


def detected_install_roots(
    *,
    system: str,
    discover_windows_install_locations_fn: Callable[..., dict[str, list[Path]]],
    discover_linux_install_locations_fn: Callable[..., dict[str, list[Path]]],
) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    if system == "Windows":
        discovered = discover_windows_install_locations_fn(WINDOWS_INSTALLATION_HINTS)
        for component_name, paths in discovered.items():
            component_key = WINDOWS_COMPONENT_KEYS.get(component_name)
            if component_key is None or not paths:
                continue
            root = paths[0]
            roots[component_key] = root if root.is_dir() else root.parent
        return roots
    if system == "Linux":
        discovered = discover_linux_install_locations_fn(
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


def install_specs_for_system(system: str, include_legacy_rti: bool) -> list[InstallSpec]:
    if system == "Windows":
        specs = list(SETUP_WINDOWS_SPECS)
        if include_legacy_rti:
            specs.append(SETUP_WINDOWS_LEGACY_SPEC)
        return specs
    if system == "Linux":
        return list(SETUP_LINUX_SPECS)
    raise RuntimeError(f"Unsupported platform: {system}")


def log_detected_installed(components: set[str]) -> None:
    if not components:
        return
    print("Detected existing components:")
    for component in sorted(components):
        print(f"  - {component}")


def discovered_installed_runtime_launcher(
    component_key: str,
    *,
    system: str | None = None,
    configured_roots: dict[str, Path] | None = None,
) -> Path | None:
    system = system or platform_system()
    configured_roots = configured_roots or configured_install_roots()
    configured_root = configured_roots.get(component_key)
    roots: list[Path] = [configured_root] if configured_root is not None and configured_root.exists() else []

    if system == "Windows":
        discovered_roots = discover_windows_install_locations(WINDOWS_INSTALLATION_HINTS)
        component_name = {"hlastarterkit": "HlaStarterKit", "pitchvisualomt": "PitchVisualOMT", "prti1516e": "prti1516e-free"}.get(component_key)
        if component_name is None:
            return None
        roots.extend(normalize_install_roots(discovered_roots.get(component_name, [])))
        roots.extend([candidate for candidate in WINDOWS_INSTALLATION_ROOTS.get(component_key, ()) if candidate.exists() and candidate not in roots])
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
        roots.extend(normalize_install_roots(discovered_roots.get(component_key, [])))
        candidates = LINUX_RUNTIME_LAUNCHERS.get(component_key, ())
    else:
        return None

    for root in roots:
        launcher = resolve_launcher_from_root(root, candidates)
        if launcher is not None:
            return launcher
    return None


def discovered_prti_install_root() -> Path | None:
    configured_roots = configured_install_roots()
    configured_root = configured_roots.get("prti1516e")
    if configured_root is not None and configured_root.exists():
        return configured_root
    launcher = discovered_installed_runtime_launcher("prti1516e")
    if launcher is None:
        return None
    if launcher.parent.name.lower() == "bin":
        return launcher.parent.parent
    return launcher.parent


def discovered_prti_crc_settings_path() -> Path | None:
    install_root = discovered_prti_install_root()
    if install_root is None:
        return None

    candidates = [
        install_root / "prti1516eCRC.settings",
        install_root / "user.home" / "prti1516e" / "prti1516eCRC.settings",
        install_root / "samples" / "docker" / "prti1516eCRC.settings",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def discovered_prti_crc_port(*, default: int = 8989) -> int:
    settings_path = discovered_prti_crc_settings_path()
    if settings_path is None:
        return default

    raw_value = read_settings_value(settings_path, "CRC.port")
    if raw_value is None:
        return default

    try:
        return int(raw_value)
    except ValueError:
        return default


def chat_sample_choices() -> list[str]:
    discovered: list[str] = []
    for variant in ("java-hla4", "java-hla4-fedpro", "cpp-hla4"):
        if discovered_chat_sample_launcher(variant) is not None:
            discovered.append(variant)
    return discovered


def discovered_chat_sample_launcher(variant: str | None = None) -> tuple[str, Path] | None:
    install_root = discovered_prti_install_root()
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


def chat_launcher_command(launcher: Path) -> list[str]:
    if launcher.suffix.lower() in {".bat", ".cmd"}:
        sample_root = launcher.parent.parent.parent
        jar_path = launcher.parent / f"{launcher.stem}.jar"
        java_exe = sample_root / "jre" / "bin" / "java.exe"
        if jar_path.exists() and java_exe.exists():
            return [str(java_exe), "-Djava.library.path=" + str(sample_root / "lib"), "-jar", str(jar_path)]
    return execution_launcher_command(launcher)


def run_chat_process(
    command: list[str],
    *,
    cwd: Path,
    username: str,
    host: str,
    message: str,
    final_message: str = ".",
) -> tuple[int, str]:
    stdin_payload = f"{host}\n{username}\n{message}\n{final_message}\n"

    if is_windows_platform() and hasattr(subprocess, "CREATE_NEW_CONSOLE"):
        try:
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        except OSError as exc:
            raise RuntimeError(f"Could not start chat sample: {exc}") from exc

        if hasattr(process, "pid") and process.pid:
            try:
                _write_console_input(process.pid, stdin_payload)
                output, _ = process.communicate(timeout=90)
                return int(process.returncode or 0), output
            except Exception:
                process.kill()
                output, _ = process.communicate()
                return int(process.returncode or 1), output

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

    try:
        output, _ = process.communicate(stdin_payload, timeout=90)
    except subprocess.TimeoutExpired:
        process.kill()
        output, _ = process.communicate()
        raise RuntimeError(f"Timed out while running chat sample: {command[0]}") from None

    return int(process.returncode or 0), output


def _build_console_key_record(char: str, *, key_down: bool) -> ctypes.Structure:
    class KEY_EVENT_RECORD(ctypes.Structure):
        _fields_ = [
            ("bKeyDown", wintypes.BOOL),
            ("wRepeatCount", wintypes.WORD),
            ("wVirtualKeyCode", wintypes.WORD),
            ("wVirtualScanCode", wintypes.WORD),
            ("uChar", wintypes.WCHAR),
            ("dwControlKeyState", wintypes.DWORD),
        ]

    record = KEY_EVENT_RECORD()
    record.bKeyDown = key_down
    record.wRepeatCount = 1
    record.wVirtualKeyCode = 0x0D if char == "\r" else 0
    record.wVirtualScanCode = 0
    record.uChar = char
    record.dwControlKeyState = 0
    return record


def _write_console_input(pid: int, stdin_payload: str) -> None:
    if not is_windows_platform():
        return

    kernel32 = ctypes.windll.kernel32
    kernel32.FreeConsole()
    attached = False
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if kernel32.AttachConsole(pid):
            attached = True
            break
        time.sleep(0.1)
    if not attached:
        return

    try:
        h_input = kernel32.GetStdHandle(-10)
        if not h_input:
            return

        class INPUT_RECORD_UNION(ctypes.Union):
            _fields_ = [("KeyEvent", _build_console_key_record("a", key_down=True).__class__)]

        class INPUT_RECORD(ctypes.Structure):
            _anonymous_ = ("Event",)
            _fields_ = [("EventType", wintypes.WORD), ("Event", INPUT_RECORD_UNION)]

        def _record_for(char: str) -> INPUT_RECORD:
            record = INPUT_RECORD()
            record.EventType = 1
            record.KeyEvent = _build_console_key_record(char, key_down=True)
            return record

        events: list[INPUT_RECORD] = []
        for line in stdin_payload.splitlines():
            for char in line:
                events.append(_record_for(char))
            events.append(_record_for("\r"))

        if not events:
            return

        array_type = INPUT_RECORD * len(events)
        event_array = array_type(*events)
        written = wintypes.DWORD()
        kernel32.WriteConsoleInputW(h_input, event_array, len(events), ctypes.byref(written))
    finally:
        kernel32.FreeConsole()


def _wait_for_tcp_port(host: str, port: int, *, timeout_seconds: float = 30.0, interval_seconds: float = 0.5) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return True
        except OSError:
            time.sleep(interval_seconds)
    return False


def _start_prti_crc() -> tuple[subprocess.Popen[str], str]:
    launcher = discovered_installed_runtime_launcher("prti1516e")
    if launcher is None:
        raise RuntimeError("No installed Pitch RTI launcher was found.")

    command = execution_launcher_command(launcher)
    launch_env = os.environ.copy()
    launch_env["PITCH_PORT"] = str(discovered_prti_crc_port(default=route_rti_port("route-native")))
    launch_env["PITCH_PORT_PROFILE"] = "route-native"
    try:
        process = subprocess.Popen(
            command,
            cwd=str(launcher.parent),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=launch_env,
        )
    except OSError as exc:
        raise RuntimeError(f"Could not start the Pitch RTI launcher: {exc}") from exc

    output_lines: list[str] = []
    line_queue: queue.Queue[str] = queue.Queue()
    def _drain_stdout() -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            output_lines.append(line)
            line_queue.put(line)

    threading.Thread(target=_drain_stdout, daemon=True).start()
    if process.stdin is not None:
        process.stdin.write("HELP\n")
        process.stdin.flush()

    deadline = time.monotonic() + 45.0
    try:
        while True:
            if process.poll() is not None:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                line = line_queue.get(timeout=min(0.5, remaining))
            except queue.Empty:
                continue
            if line:
                if "Available commands:" in line or "CRC listening on adapters" in line:
                    host = os.environ.get("PITCH_RTI_SMOKE_HOST", "localhost")
                    if "CRC listening on adapters" in line:
                        adapters = line.split("CRC listening on adapters", 1)[1].strip().lstrip(":").strip()
                        candidate = adapters.split(",", 1)[0].strip()
                        if candidate:
                            host = candidate
                    port = discovered_prti_crc_port(default=route_rti_port("route-native"))
                    if not _wait_for_tcp_port(host, port):
                        break
                    return process, f"{host}:{port}"
    except Exception:
        process.kill()
        raise

    process.kill()
    output = "".join(output_lines)
    raise RuntimeError(f"Pitch RTI did not become ready.\n{output}")


def run_chat_smoke_test(variant: str = "auto", *, list_only: bool = False) -> int:
    if list_only:
        print("Available chat sample variants:")
        for choice in chat_sample_choices():
            launcher = discovered_chat_sample_launcher(choice)
            if launcher is None:
                continue
            _, path = launcher
            print(f"  {choice}: {path}")
        return 0
    discovered = discovered_chat_sample_launcher(variant)
    if discovered is None:
        choices = chat_sample_choices()
        if choices:
            print("No matching chat sample launcher was found for the requested variant.", file=sys.stderr)
            print(f"Available chat sample variants: {', '.join(choices)}", file=sys.stderr)
        else:
            print("No chat sample launcher was found under the installed pRTI samples.", file=sys.stderr)
        return 1
    chosen_variant, launcher = discovered
    print(f"Chat smoke variant: {chosen_variant}")
    print(f"Chat sample launcher: {launcher}")
    command = chat_launcher_command(launcher)
    rti_process, host = _start_prti_crc()
    messages = [("pitch-smoke-alpha", "Hello from pitch-smoke-alpha"), ("pitch-smoke-bravo", "Hello from pitch-smoke-bravo")]
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(run_chat_process, command, cwd=launcher.parent, username=username, host=host, message=message)
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
    finally:
        if rti_process.poll() is None:
            try:
                rti_process.communicate("QUIT\n", timeout=30)
            except subprocess.TimeoutExpired:
                rti_process.kill()
                rti_process.communicate()


def start_actions(system: str, asset_root: Path, workspace_root: Path) -> list[StartAction]:
    if system == "Windows":
        return [
            StartAction("1", "HlaStarterKit", "runtime", asset_root / "windows" / "HlaStarterKit_v1.0.2_windows64.exe", "hlastarterkit"),
            StartAction("2", "PitchVisualOMT", "runtime", asset_root / "windows" / "PitchVisualOMTFree_v2.7.0_windows64.exe", "pitchvisualomt"),
            StartAction("3", "prti1516e-free", "runtime", asset_root / "windows" / "prti1516e-free_5_5_10_windows32.exe", "prti1516e"),
            StartAction("4", "Docs", "folder", asset_root / "docs", "docs"),
            StartAction("5", "Plugin", "folder", asset_root / "plugin", "plugin"),
            StartAction("6", "Project Root", "folder", workspace_root, "root"),
        ]
    if system == "Linux":
        return [
            StartAction("1", "HlaStarterKit", "runtime", asset_root / "linux" / "HlaStarterKit_v1.0.2_linux64.sh", "hlastarterkit"),
            StartAction("2", "PitchVisualOMT", "runtime", asset_root / "linux" / "PitchVisualOMTFree_v2.7.0_linux64.sh", "pitchvisualomt"),
            StartAction("3", "prti1516e-free", "runtime", asset_root / "linux" / "prti1516e-free_5_5_10_linux64.sh", "prti1516e"),
            StartAction("4", "Docs", "folder", asset_root / "docs", "docs"),
            StartAction("5", "Plugin", "folder", asset_root / "plugin", "plugin"),
            StartAction("6", "Project Root", "folder", workspace_root, "root"),
        ]
    raise RuntimeError(f"Unsupported platform: {system}")


def lookup_start_action(target: str, actions: list[StartAction]) -> StartAction | None:
    normalized = target.strip().lower()
    for action in actions:
        if normalized in {action.key, action.label.lower(), action.alias}:
            return action
    return None


def show_menu(system: str, asset_root: Path, workspace_root: Path) -> None:
    print("Pick a Pitch item to launch:")
    for action in start_actions(system, asset_root, workspace_root):
        print(f"  {action.key}. {action.label}")


def run_start_action(
    action: StartAction,
    args: argparse.Namespace,
    *,
    workspace_root: Path,
    discovered_launcher: Callable[[str], Path | None],
    open_path: Callable[[Path], None],
    launch_program: Callable[..., None],
) -> None:
    if action.kind == "folder":
        if not action.path.exists():
            raise FileNotFoundError(f"Missing path: {action.path}")
        open_path(action.path)
        return
    launcher = discovered_launcher(action.alias)
    if launcher is None:
        raise RuntimeError(f"No installed launcher found for {action.label}. Run `pitch setup` first, or use `pitch status` to inspect the install.")
    print(f"Launching {action.label} from {launcher}...")
    launch_env: dict[str, str] = {}
    if getattr(args, "port", None) is not None:
        launch_env["PITCH_PORT"] = str(args.port)
    else:
        launch_env["PITCH_PORT"] = str(discovered_prti_crc_port(default=route_rti_port("route-native")))
    launch_env["PITCH_PORT_PROFILE"] = "route-native"
    if getattr(args, "ports_config", None):
        launch_env["PITCH_PORTS_CONFIG"] = str((workspace_root / args.ports_config).resolve() if not Path(args.ports_config).is_absolute() else Path(args.ports_config))
    launch_program(launcher, env=launch_env)
