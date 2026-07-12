"""Unified Pitch command line entry point."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pitch", description="Pitch HLA starter bundle CLI.")
    subparsers = parser.add_subparsers(dest="command")

    setup_parser = subparsers.add_parser("setup", help="Install the core Pitch stack.")
    setup_parser.add_argument("--include-legacy-rti", action="store_true", help="Install the legacy Windows RTI package too.")
    setup_parser.add_argument("--probe-ports", action="store_true", help="Probe configured ports after installation.")
    setup_parser.add_argument("--strict-probe", action="store_true", help="Fail if any configured ports are closed.")
    setup_parser.add_argument("--force", action="store_true", help="Rerun installers even if the bundle appears installed.")
    setup_parser.add_argument("--silent-install", action="store_true", help="Try the vendor installers in quiet mode.")
    setup_parser.add_argument("--ports-config", default=str(ASSET_ROOT / "ports.conf"), help="Port probe configuration file.")
    setup_parser.add_argument("--source", help="Folder to scan and stage into the writable installer cache before setup.")
    setup_parser.set_defaults(handler=handle_setup)

    verify_parser = subparsers.add_parser("verify", help="Verify the bundle and checksum manifest.")
    verify_parser.add_argument("--quiet", action="store_true", help="Only report failures.")
    verify_parser.set_defaults(handler=handle_verify)

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


def handle_setup(args: argparse.Namespace) -> int:
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

    if not args.quiet:
        print("Verification passed.")
    return 0


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


def handle_start(args: argparse.Namespace) -> int:
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

    _run_start_action(action, args)
    if args.probe_ports:
        print("Probing configured ports...")
        results = _probe_results_for_start(args)
        if args.strict_probe and not all(open_ for _, open_ in results):
            raise RuntimeError("One or more configured ports are closed.")
    return 0


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
