"""Shared platform and path helpers for Pitch commands."""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path


def platform_system() -> str:
    return platform.system()


def is_windows_platform() -> bool:
    return platform_system() == "Windows"


def is_linux_platform() -> bool:
    return platform_system() == "Linux"


def is_macos_platform() -> bool:
    return platform_system() == "Darwin"


def is_wsl_environment() -> bool:
    release = platform.release().lower()
    return bool(
        os.environ.get("WSL_DISTRO_NAME")
        or os.environ.get("WSL_INTEROP")
        or "microsoft" in release
    )


def has_command(command: str) -> bool:
    return shutil.which(command) is not None


def looks_like_windows_path(value: str) -> bool:
    return bool(value) and len(value) > 1 and value[1] == ":" and value[0].isalpha()


def translate_windows_path(value: str) -> Path:
    raw = str(value).strip()
    if not raw:
        return Path(raw)
    if not looks_like_windows_path(raw):
        return Path(raw).expanduser()
    drive = raw[0].lower()
    remainder = raw[2:].replace("\\", "/").lstrip("/")
    return Path(f"/mnt/{drive}/{remainder}")


def coerce_cli_path(value: str) -> Path:
    if is_wsl_environment() and looks_like_windows_path(value):
        return translate_windows_path(value)
    return Path(value).expanduser()


def coerce_env_path(value: str) -> Path:
    if is_wsl_environment() and looks_like_windows_path(value):
        return translate_windows_path(value)
    return Path(value).expanduser()


def resolved_docker_command() -> str | None:
    if has_command("docker"):
        return "docker"
    if has_command("docker.exe"):
        return "docker.exe"
    return None
