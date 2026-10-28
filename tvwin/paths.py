"""Rutas de la app (desarrollo y ejecutable empaquetado)."""

from __future__ import annotations

import sys
from pathlib import Path


def app_dir() -> Path:
    """Carpeta de la app: junto al .exe en portable, o raíz del repo en desarrollo."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """Recursos embebidos (PyInstaller _MEIPASS) o raíz del proyecto."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return app_dir()


def vendor_mpv() -> Path | None:
    candidates = (
        app_dir() / "player" / "mpv.exe",
        app_dir() / "_internal" / "player" / "mpv.exe",
        resource_dir() / "player" / "mpv.exe",
        app_dir() / "mpv" / "mpv.exe",
    )
    for path in candidates:
        if path.is_file():
            return path
    return None
