#!/usr/bin/env python3
"""Shared bootstrap helpers for Pitch setup, verification, and port probing."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import tempfile
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence


def _workspace_root_from(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / "README.md").exists() and (candidate / "pitch" / "checksums.sha256").exists():
            return candidate
    return None


def discover_workspace_root() -> Path:
    candidates = [
        Path.cwd(),
        Path(__file__).resolve().parent,
        Path(__file__).resolve().parent.parent,
    ]
    for candidate in candidates:
        resolved = _workspace_root_from(candidate)
        if resolved is not None:
            return resolved
    return Path.cwd()


ROOT = discover_workspace_root()
INSTALL_STATE_FILENAME = ".pitch-install-state.json"
INSTALL_ROOTS_FILENAME = ".pitch-install-roots.json"
APP_NAME = "pitch-rti-toolkit"


def resolve_asset_root(workspace_root: Path | None = None) -> Path:
    override = os.environ.get("PITCH_ASSET_ROOT")
    if override:
        candidate = Path(override).expanduser()
        if candidate.exists():
            return candidate

    candidates: list[Path] = []
    if workspace_root is not None:
        candidates.extend([workspace_root / "pitch", workspace_root])

    module_root = Path(__file__).resolve().parent
    candidates.extend([module_root / "pitch", module_root.parent / "pitch", Path.cwd() / "pitch"])

    for candidate in candidates:
        if (candidate / "checksums.sha256").exists() or (candidate / "ports.conf").exists():
            return candidate

    return workspace_root / "pitch" if workspace_root is not None else Path.cwd() / "pitch"


def resolve_user_data_root(app_name: str = APP_NAME) -> Path:
    override = os.environ.get("PITCH_USER_DATA_ROOT")
    if override:
        return Path(override).expanduser()

    system = os.name
    if system == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base).expanduser() / app_name
        return Path.home() / "AppData" / "Local" / app_name

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_name

    base = os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base).expanduser() / app_name
    return Path.home() / ".local" / "share" / app_name


def resolve_installer_drop_root(app_name: str = APP_NAME) -> Path:
    override = os.environ.get("PITCH_INSTALLER_DROP_ROOT")
    if override:
        return Path(override).expanduser()
    return resolve_user_data_root(app_name) / "installers"


def ensure_installer_drop_root(app_name: str = APP_NAME) -> Path:
    path = resolve_installer_drop_root(app_name)
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(frozen=True)
class PortTarget:
    host: str
    port: int
    label: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bundle_fingerprint(root: Path = ROOT) -> str:
    manifest = root / "checksums.sha256"
    if not manifest.exists():
        manifest = root / "pitch" / "checksums.sha256"
    return sha256_file(manifest)


def install_state_path(root: Path = ROOT) -> Path:
    return root / INSTALL_STATE_FILENAME


def install_roots_path(root: Path = ROOT) -> Path:
    return root / INSTALL_ROOTS_FILENAME


def load_install_state(state_path: Path) -> dict[str, object] | None:
    if not state_path.exists():
        return None

    with state_path.open("r", encoding="utf-8", errors="replace") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid install state: {state_path}")

    return data


def _normalize_component_key(name: str) -> str:
    normalized = name.strip().lower().replace(" ", "").replace("-", "").replace("_", "")
    if normalized in {"hlastarterkit", "hlastarterkitfree"}:
        return "hlastarterkit"
    if normalized in {"pitchvisualomt", "pitchvisualomtfree", "pitchvisualomtfreev270"}:
        return "pitchvisualomt"
    if normalized in {"prti1516e", "prti1516efree", "prti1516e-free"}:
        return "prti1516e"
    return normalized


def load_install_roots(config_path: Path) -> dict[str, Path]:
    if not config_path.exists():
        return {}

    with config_path.open("r", encoding="utf-8", errors="replace") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid install roots config: {config_path}")

    system_key = os.name if os.name == "nt" else "posix"
    platform_names = {
        "nt": ("windows", "win32"),
        "posix": ("linux", "darwin", "mac", "macos"),
    }.get(system_key, ())

    platform_data: object = data
    for key in platform_names:
        if key in data and isinstance(data[key], dict):
            platform_data = data[key]
            break

    if not isinstance(platform_data, dict):
        raise ValueError(f"Invalid install roots config: {config_path}")

    roots: dict[str, Path] = {}
    for key, value in platform_data.items():
        if not isinstance(value, str) or not value.strip():
            continue
        roots[_normalize_component_key(str(key))] = Path(value).expanduser()

    return roots


def save_install_state(state_path: Path, state: dict[str, object]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        dir=str(state_path.parent),
        prefix=f".{state_path.name}.",
        suffix=".tmp",
    ) as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp_name = handle.name

    Path(temp_name).replace(state_path)


def load_manifest(manifest_path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    with manifest_path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            digest, relative_path = parts
            entries[relative_path] = digest.lower()
    return entries


def verify_paths_exist(root: Path, relative_paths: Sequence[str]) -> list[str]:
    missing: list[str] = []
    for relative_path in relative_paths:
        if not (root / relative_path).exists():
            missing.append(relative_path)
    return missing


def verify_manifest(root: Path, manifest_path: Path) -> list[str]:
    if not manifest_path.exists():
        return [f"Missing checksum manifest: {manifest_path.name}"]

    failures: list[str] = []
    for relative_path, expected_digest in load_manifest(manifest_path).items():
        full_path = root / relative_path
        if not full_path.exists():
            failures.append(f"Checksum listed but file missing: {relative_path}")
            continue

        actual_digest = sha256_file(full_path)
        if actual_digest != expected_digest:
            failures.append(f"Checksum mismatch: {relative_path}")
    return failures


def parse_ports_config(config_path: Path) -> list[PortTarget]:
    if not config_path.exists():
        raise FileNotFoundError(f"Missing port configuration: {config_path}")

    targets: list[PortTarget] = []
    with config_path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split(maxsplit=2)
            if len(parts) < 2:
                raise ValueError(f"Invalid port entry: {line}")

            host = parts[0]
            try:
                port = int(parts[1])
            except ValueError as exc:
                raise ValueError(f"Invalid port number in: {line}") from exc

            label = parts[2] if len(parts) == 3 else f"{host}:{port}"
            targets.append(PortTarget(host=host, port=port, label=label))

    return targets


def probe_port(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def probe_targets(targets: Iterable[PortTarget]) -> list[tuple[PortTarget, bool]]:
    return [(target, probe_port(target.host, target.port)) for target in targets]


def _registry_values(winreg, handle, names: Sequence[str]) -> str:
    values: list[str] = []
    for name in names:
        try:
            value, _value_type = winreg.QueryValueEx(handle, name)
        except OSError:
            continue
        if isinstance(value, str) and value.strip():
            values.append(value)
    return " ".join(values).lower()


def _registry_path_values(winreg, handle, names: Sequence[str]) -> list[str]:
    values: list[str] = []
    for name in names:
        try:
            value, _value_type = winreg.QueryValueEx(handle, name)
        except OSError:
            continue
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    return values


def _registry_path_candidate(value: str) -> Path | None:
    cleaned = value.strip().strip('"')
    if not cleaned:
        return None

    if "," in cleaned:
        head, tail = cleaned.rsplit(",", 1)
        if tail.isdigit():
            cleaned = head.strip()

    cleaned = cleaned.strip('"')
    if not cleaned:
        return None

    return Path(cleaned)


def _iter_candidate_directories(root: Path, max_depth: int = 2) -> list[Path]:
    candidates: list[Path] = [root]
    if max_depth <= 0 or not root.exists():
        return candidates

    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        if depth >= max_depth:
            continue
        try:
            children = [child for child in current.iterdir() if child.is_dir()]
        except OSError:
            continue
        for child in children:
            candidates.append(child)
            stack.append((child, depth + 1))

    return candidates


def detect_windows_installed_components(component_patterns: Mapping[str, Sequence[str]]) -> list[str]:
    if os.name != "nt":
        return []

    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return []

    uninstall_roots = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\ej-technologies\install4j\installations"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\ej-technologies\install4j\installations"),
    )

    installed: list[str] = []
    for component, patterns in component_patterns.items():
        normalized_patterns = tuple(pattern.lower() for pattern in patterns if pattern)
        if not normalized_patterns:
            continue

        matched = False
        for root, subkey_path in uninstall_roots:
            try:
                with winreg.OpenKey(root, subkey_path) as uninstall_root:
                    subkey_count = winreg.QueryInfoKey(uninstall_root)[0]
                    for index in range(subkey_count):
                        try:
                            subkey_name = winreg.EnumKey(uninstall_root, index)
                        except OSError:
                            continue

                        try:
                            with winreg.OpenKey(uninstall_root, subkey_name) as entry:
                                haystack = " ".join(
                                    part
                                    for part in (
                                        _registry_values(
                                            winreg,
                                            entry,
                                            (
                                                "DisplayName",
                                                "DisplayVersion",
                                                "Publisher",
                                                "InstallLocation",
                                                "InstallDir",
                                                "InstallationDir",
                                                "UninstallString",
                                                "Path",
                                                "Name",
                                            ),
                                        ),
                                        subkey_name.lower(),
                                    )
                                    if part
                                )
                        except OSError:
                            continue

                        if any(pattern in haystack for pattern in normalized_patterns):
                            installed.append(component)
                            matched = True
                            break
            except OSError:
                continue

            if matched:
                break

    return installed


def discover_windows_install_locations(component_patterns: Mapping[str, Sequence[str]]) -> dict[str, list[Path]]:
    if os.name != "nt":
        return {}

    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return {}

    uninstall_roots = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\ej-technologies\install4j\installations"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\ej-technologies\install4j\installations"),
    )

    discovered: dict[str, list[Path]] = {}
    for component, patterns in component_patterns.items():
        normalized_patterns = tuple(pattern.lower() for pattern in patterns if pattern)
        if not normalized_patterns:
            continue

        found_paths: list[Path] = []
        for root, subkey_path in uninstall_roots:
            try:
                with winreg.OpenKey(root, subkey_path) as uninstall_root:
                    subkey_count = winreg.QueryInfoKey(uninstall_root)[0]
                    for index in range(subkey_count):
                        try:
                            subkey_name = winreg.EnumKey(uninstall_root, index)
                        except OSError:
                            continue

                        try:
                            with winreg.OpenKey(uninstall_root, subkey_name) as entry:
                                haystack = " ".join(
                                    part
                                    for part in (
                                        _registry_values(
                                            winreg,
                                            entry,
                                            (
                                                "DisplayName",
                                                "DisplayVersion",
                                                "Publisher",
                                                "InstallLocation",
                                                "InstallDir",
                                                "InstallationDir",
                                                "UninstallString",
                                                "Path",
                                                "Name",
                                            ),
                                        ),
                                        subkey_name.lower(),
                                    )
                                    if part
                                )
                                if any(pattern in haystack for pattern in normalized_patterns):
                                    for value in _registry_path_values(
                                        winreg,
                                        entry,
                                        ("InstallLocation", "InstallDir", "InstallationDir", "DisplayIcon"),
                                    ):
                                        candidate = _registry_path_candidate(value)
                                        if candidate is not None:
                                            found_paths.append(candidate)
                        except OSError:
                            continue
            except OSError:
                continue

        if found_paths:
            discovered[component] = found_paths

    return discovered


def discover_linux_install_locations(component_roots: Mapping[str, Sequence[Path]], launcher_names: Mapping[str, Sequence[str]]) -> dict[str, list[Path]]:
    discovered: dict[str, list[Path]] = {}
    for component, roots in component_roots.items():
        names = launcher_names.get(component, ())
        hits: list[Path] = []
        for root in roots:
            if not root.exists():
                continue
            for child in _iter_candidate_directories(root, max_depth=2):
                for launcher_name in names:
                    candidate = child / launcher_name
                    if candidate.exists():
                        hits.append(child)
                        break
                if hits:
                    break
            if hits:
                break
        if hits:
            discovered[component] = hits
    return discovered


def discover_file_locations(filename: str, search_roots: Sequence[Path], max_depth: int = 4) -> list[Path]:
    hits: list[Path] = []
    seen: set[Path] = set()
    for root in search_roots:
        if not root.exists():
            continue

        if root.is_file() and root.name == filename and root not in seen:
            hits.append(root)
            seen.add(root)
            continue

        for candidate in _iter_candidate_directories(root, max_depth=max_depth):
            file_path = candidate / filename
            if file_path.exists() and file_path.is_file() and file_path not in seen:
                hits.append(file_path)
                seen.add(file_path)

    return hits


def run_installer(installer_path: Path, cwd: Path | None = None, *, quiet: bool = False) -> None:
    if not installer_path.exists():
        raise FileNotFoundError(f"Missing installer: {installer_path}")

    command = [str(installer_path)]
    if quiet:
        command.append("-q")
        command.append("-Dsys.resolveUserSpecificInstallationDir=true")

    if installer_path.suffix.lower() != ".exe":
        if not installer_path.stat().st_mode & 0o111:
            command = ["sh", str(installer_path)]
            if quiet:
                command.append("-q")
                command.append("-Dsys.resolveUserSpecificInstallationDir=true")

    subprocess.run(command, cwd=str(cwd or installer_path.parent), check=True)
