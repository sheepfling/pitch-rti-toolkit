"""Runtime shim that exposes the source package from `src/`."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT / "src"
SRC_PACKAGE = SRC_ROOT / "pitch"

if SRC_ROOT.exists():
    src_root_text = str(SRC_ROOT)
    if src_root_text not in sys.path:
        sys.path.insert(0, src_root_text)

if SRC_PACKAGE.exists():
    package_text = str(SRC_PACKAGE)
    if package_text not in __path__:
        __path__.append(package_text)
