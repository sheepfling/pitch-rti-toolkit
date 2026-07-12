"""CRC settings discovery and mutation helpers."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pitch_bootstrap import ROOT, discover_file_locations, install_roots_path, load_install_roots


CRC_SETTINGS_NAME_HINTS = (
    "prti1516eCRC.settings",
    "pRTI1516eCRC.settings",
    "prti1516e-freeCRC.settings",
    "PitchCRC.settings",
    "CRC.settings",
)


def _configured_install_roots() -> dict[str, Path]:
    try:
        return load_install_roots(install_roots_path(ROOT))
    except (OSError, ValueError, json.JSONDecodeError):  # type: ignore[name-defined]
        return {}


def _crc_settings_search_roots(
    *,
    user_data_root: Path,
    installer_drop_root: Path,
    asset_root: Path,
    workspace_root: Path,
    home_root: Path,
    launcher: Path | None,
) -> list[Path]:
    roots: list[Path] = [
        user_data_root,
        installer_drop_root,
        asset_root,
        workspace_root,
        home_root,
    ]

    configured_roots = _configured_install_roots()
    prti_root = configured_roots.get("prti1516e")
    if prti_root is not None:
        roots.extend([prti_root, prti_root.parent])

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


def discover_crc_settings_files(
    *,
    user_data_root: Path,
    installer_drop_root: Path,
    asset_root: Path,
    workspace_root: Path,
    home_root: Path,
    launcher: Path | None,
) -> list[Path]:
    hits: list[Path] = []
    seen: set[str] = set()
    roots = _crc_settings_search_roots(
        user_data_root=user_data_root,
        installer_drop_root=installer_drop_root,
        asset_root=asset_root,
        workspace_root=workspace_root,
        home_root=home_root,
        launcher=launcher,
    )

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


def parse_settings_entries(path: Path) -> list[tuple[str, str]]:
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


def settings_flag_state(entries: list[tuple[str, str]], key_name: str) -> bool | None:
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


def print_settings_entries(path: Path, entries: list[tuple[str, str]]) -> None:
    print(f"CRC settings file: {path}")
    preview = settings_flag_state(entries, "CRC.enableHla4PreviewFeatures")
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


def print_crc_settings_summary(
    *,
    user_data_root: Path,
    installer_drop_root: Path,
    asset_root: Path,
    workspace_root: Path,
    home_root: Path,
    launcher: Path | None,
) -> None:
    settings_files = discover_crc_settings_files(
        user_data_root=user_data_root,
        installer_drop_root=installer_drop_root,
        asset_root=asset_root,
        workspace_root=workspace_root,
        home_root=home_root,
        launcher=launcher,
    )
    if not settings_files:
        print("CRC settings: no settings file was discovered.")
        print("  Search roots:")
        for root in _crc_settings_search_roots(
            user_data_root=user_data_root,
            installer_drop_root=installer_drop_root,
            asset_root=asset_root,
            workspace_root=workspace_root,
            home_root=home_root,
            launcher=launcher,
        ):
            print(f"    - {root}")
        return

    print("CRC settings discovery:")
    for settings_file in settings_files:
        entries = parse_settings_entries(settings_file)
        print_settings_entries(settings_file, entries)


def read_settings_value(path: Path, key: str) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}="):
            return stripped.split("=", 1)[1].strip()
    return None


def set_settings_value(path: Path, key: str, value: str) -> None:
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


def set_crc_setting_everywhere(settings_files: list[Path], key: str, value: str) -> list[Path]:
    if not settings_files:
        raise FileNotFoundError("No CRC settings file was discovered.")

    updated: list[Path] = []
    for settings_file in settings_files:
        set_settings_value(settings_file, key, value)
        updated.append(settings_file)
    return updated


def set_hla4_preview_everywhere(settings_files: list[Path], enabled: bool) -> list[Path]:
    return set_crc_setting_everywhere(settings_files, "CRC.enableHla4PreviewFeatures", "true" if enabled else "false")


def requested_hla4_preview_state(args: argparse.Namespace) -> bool | None:
    if getattr(args, "enable_hla4_preview", False):
        return True
    if getattr(args, "disable_hla4_preview", False):
        return False
    return None


def apply_requested_hla4_preview(
    args: argparse.Namespace,
    *,
    context: str,
    settings_files: list[Path],
    require_settings: bool,
) -> bool:
    requested = requested_hla4_preview_state(args)
    if requested is None:
        return False

    try:
        updated_files = set_hla4_preview_everywhere(settings_files, requested)
    except FileNotFoundError:
        message = f"{context}: no CRC settings file was discovered; could not update HLA 4 Preview."
        if require_settings:
            print(message, file=sys.stderr)
            return False
        print(message)
        return False

    print(f"{context}: set HLA 4 Preview to {'enabled' if requested else 'disabled'} in:")
    for path in updated_files:
        print(f"  {path}")
    return True


def read_env_value(path: Path, key: str) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}="):
            return stripped.split("=", 1)[1].strip()
    return None


def vendor_crc_settings_path(vendor_settings_root: Path) -> Path:
    return vendor_settings_root / "prti1516eCRC.settings"


def vendor_docker_status_lines(
    *,
    vendor_install_root: Path | None,
    vendor_env_path: Path,
    vendor_settings_root: Path,
    vendor_build_root: Path,
    compose_path: Path,
) -> list[str]:
    lines = [
        "Vendor Docker setup:",
        f"  pRTI home: {vendor_install_root or 'missing'}",
        f"  env file: {vendor_env_path}",
        f"  vendor settings overlay: {vendor_settings_root}",
        f"  vendor build context: {vendor_build_root}",
        f"  compose file: {compose_path}",
    ]
    initialized = vendor_env_path.exists() and vendor_settings_root.exists()
    lines.append(f"  initialized: {'yes' if initialized else 'no'}")
    crc_settings_path = vendor_crc_settings_path(vendor_settings_root)
    if crc_settings_path.exists():
        preview = read_settings_value(crc_settings_path, "CRC.enableHla4PreviewFeatures")
        if preview is not None:
            lines.append(f"  HLA 4 Preview: {preview}")
    return lines
