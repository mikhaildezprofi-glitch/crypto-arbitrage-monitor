"""Vendor the repository's shared core package into the Python Worker bundle.

Pywrangler vendors third-party dependencies, but the Worker project itself is
not a dependency and therefore is not copied into python_modules automatically.
Keep src/arbitrage_monitor as the single source of truth and copy it after sync.
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "arbitrage_monitor"
TARGET = Path(__file__).resolve().parents[1] / "python_modules" / "arbitrage_monitor"

if not (SOURCE / "models.py").is_file():
    raise SystemExit(f"Core package is missing or incomplete: {SOURCE}")

if TARGET.exists():
    shutil.rmtree(TARGET)

shutil.copytree(
    SOURCE,
    TARGET,
    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
)

required = (
    TARGET / "models.py",
    TARGET / "providers" / "blackbit.py",
    TARGET / "providers" / "winance.py",
)
missing = [str(path) for path in required if not path.is_file()]
if missing:
    raise SystemExit("Vendored core package is incomplete: " + ", ".join(missing))

print(f"Vendored shared core package: {SOURCE} -> {TARGET}")
