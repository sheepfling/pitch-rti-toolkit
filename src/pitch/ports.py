"""Deterministic port profiles for Pitch routes and smoke tests."""

from __future__ import annotations

import os
from dataclasses import dataclass

from pitch.common import is_macos_platform, is_windows_platform, is_wsl_environment


_FAMILY_ORDER = {
    "windows": 0,
    "wsl": 1,
    "linux": 2,
    "macos": 3,
}

_SURFACE_ORDER = {
    "route-native": 0,
    "route-wsl": 1,
    "route-docker": 2,
    "vendor-docker": 3,
}

_FAMILY_STRIDE = 4000
_SURFACE_STRIDE = 400
_RTI_OFFSET = 89
_WEBVIEW_OFFSET = 189
_WORKER_STEP = 10


@dataclass(frozen=True)
class PortProfile:
    rti: int
    webview: int


def execution_family() -> str:
    if is_windows_platform():
        return "windows"
    if is_macos_platform():
        return "macos"
    if is_wsl_environment():
        return "wsl"
    return "linux"


def _worker_slot() -> int:
    raw = (
        os.environ.get("PITCH_PORT_SLOT")
        or os.environ.get("PYTEST_XDIST_WORKER")
        or os.environ.get("TEST_WORKER_INDEX")
        or ""
    ).strip()
    if not raw:
        return 0
    if raw.startswith("gw"):
        raw = raw[2:]
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return 0
    return max(0, min(int(digits), 29))


def _profile_base(surface: str, family: str | None = None) -> int:
    normalized_surface = surface.strip().lower()
    if normalized_surface not in _SURFACE_ORDER:
        raise ValueError(f"Unknown port surface: {surface}")

    normalized_family = (family or execution_family()).strip().lower()
    if normalized_family not in _FAMILY_ORDER:
        raise ValueError(f"Unknown execution family: {family}")

    return 18000 + (_FAMILY_ORDER[normalized_family] * _FAMILY_STRIDE) + (_SURFACE_ORDER[normalized_surface] * _SURFACE_STRIDE)


def route_port_profile(surface: str, *, family: str | None = None) -> PortProfile:
    base = _profile_base(surface, family=family) + (_worker_slot() * _WORKER_STEP)
    return PortProfile(rti=base + _RTI_OFFSET, webview=base + _WEBVIEW_OFFSET)


def route_rti_port(surface: str, *, family: str | None = None) -> int:
    return route_port_profile(surface, family=family).rti


def route_webview_port(surface: str, *, family: str | None = None) -> int:
    return route_port_profile(surface, family=family).webview


def route_surface_for_context(route_context: str | None = None) -> str:
    normalized = (route_context or os.environ.get("PITCH_ROUTE_CONTEXT", "")).strip().lower()
    if normalized == "wsl":
        return "route-wsl"
    if normalized == "docker":
        return "route-docker"
    return "route-native"
