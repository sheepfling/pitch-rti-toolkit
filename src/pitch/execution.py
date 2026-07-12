"""Process and launcher execution helpers for Pitch."""

from __future__ import annotations

import os
import subprocess
import shutil
import shlex
from pathlib import Path

from pitch.common import is_macos_platform, is_windows_platform, is_wsl_environment, looks_like_windows_path, resolved_docker_command, translate_windows_path


def launcher_command(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    if suffix in {".bat", ".cmd"} and (is_windows_platform() or is_wsl_environment()):
        return ["cmd.exe", "/c", str(path)]
    if suffix == ".sh" or path.name.endswith(".sh"):
        return ["bash", str(path)]
    if is_macos_platform() and (suffix == ".app" or path.is_dir()):
        return ["open", str(path)]
    return [str(path)]


def quoted_posix_command(args: list[str]) -> str:
    return shlex.join(args)


def wsl_command(pitch_args: list[str], *, wsl_distro: str | None = None, workspace_root: Path) -> list[str]:
    workspace = translate_windows_path(str(workspace_root)).as_posix() if looks_like_windows_path(str(workspace_root)) else workspace_root.as_posix()
    command = ["wsl.exe"]
    if wsl_distro:
        command.extend(["-d", wsl_distro])
    command.extend(["--cd", workspace, "bash", "-lc", quoted_posix_command(["python3", "-m", "pitch", *pitch_args])])
    return command


def docker_compose_run_command(
    pitch_args: list[str],
    *,
    compose_file: Path,
    service_name: str,
    env_file: Path | None = None,
) -> list[str]:
    docker_command = resolved_docker_command()
    if docker_command is None:
        docker_command = "docker.exe" if is_wsl_environment() else "docker"
    command = [docker_command, "compose"]
    if env_file is not None and env_file.exists():
        command.extend(["--env-file", str(env_file)])
    command.extend(["-f", str(compose_file), "run", "--rm", "--build", service_name])
    command.extend(pitch_args)
    return command


def open_path(path: Path) -> None:
    if is_windows_platform():
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
            return
        except (OSError, PermissionError):
            try:
                subprocess.Popen(["explorer.exe", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError as exc:
                raise RuntimeError(f"Could not open path: {path}") from exc

    if is_macos_platform():
        opener = ["open", str(path)]
    elif shutil.which("xdg-open"):
        opener = ["xdg-open", str(path)]
    else:
        opener = ["gio", "open", str(path)]

    try:
        subprocess.Popen(opener, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise RuntimeError(f"Could not open path: {path}") from exc


def launch_program(path: Path, env: dict[str, str] | None = None) -> None:
    child_env = os.environ.copy()
    if env:
        child_env.update(env)
    command = launcher_command(path)
    subprocess.Popen(command, cwd=str(path.parent), env=child_env)
