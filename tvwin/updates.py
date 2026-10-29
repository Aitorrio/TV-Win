"""Comprobación y actualización portable desde releases rolling de GitHub."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .paths import app_dir

REPO = "Aitorrio/TV-Win"
API_RELEASE = "https://api.github.com/repos/{repo}/releases/tags/{tag}"
USER_AGENT = f"TV-Win/{__version__} (+https://github.com/Aitorrio/TV-Win)"
ASSET_NAME = "TV-Win-windows-x64.zip"
VERSION_MARKER = re.compile(
    r"<!--\s*tv-win-build:\s*version=([0-9]+(?:\.[0-9]+)*)\s*-->",
    re.IGNORECASE,
)

CHANNEL_TAGS = {
    "stable": "latest-stable",
    "beta": "latest-beta",
}


@dataclass(frozen=True)
class UpdateInfo:
    channel: str
    tag: str
    version: str
    html_url: str
    zip_url: str


def _parse_version(value: str) -> tuple[int, ...]:
    cleaned = value.strip().lstrip("vV")
    parts = re.findall(r"\d+", cleaned)
    if not parts:
        return (0,)
    return tuple(int(p) for p in parts)


def is_newer(remote: str, local: str = __version__) -> bool:
    return _parse_version(remote) > _parse_version(local)


def _http_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _version_from_release(data: dict) -> str | None:
    body = str(data.get("body") or "")
    match = VERSION_MARKER.search(body)
    if match:
        return match.group(1)
    name = str(data.get("name") or "")
    found = re.search(r"(\d+\.\d+(?:\.\d+)?)", name)
    if found:
        return found.group(1)
    tag = str(data.get("tag_name") or "")
    found = re.search(r"(\d+\.\d+(?:\.\d+)?)", tag)
    if found:
        return found.group(1)
    return None


def _zip_asset_url(data: dict) -> str | None:
    for asset in data.get("assets") or []:
        if str(asset.get("name") or "") == ASSET_NAME:
            url = str(asset.get("browser_download_url") or "").strip()
            if url:
                return url
    return None


def check_latest(channel: str = "stable") -> UpdateInfo | None:
    """Devuelve info de update si el canal remoto es más nuevo que esta build."""
    key = (channel or "stable").strip().lower()
    if key not in CHANNEL_TAGS:
        key = "stable"
    tag = CHANNEL_TAGS[key]
    url = API_RELEASE.format(repo=REPO, tag=tag)
    try:
        data = _http_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None

    version = _version_from_release(data)
    zip_url = _zip_asset_url(data)
    html_url = str(data.get("html_url") or "").strip()
    if not version or not zip_url or not html_url:
        return None
    if not is_newer(version):
        return None
    return UpdateInfo(
        channel=key,
        tag=tag,
        version=version,
        html_url=html_url,
        zip_url=zip_url,
    )


def _download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response, dest.open("wb") as out:
        shutil.copyfileobj(response, out)


def _find_payload(extract_root: Path) -> Path:
    """Localiza la carpeta que contiene TV-Win.exe tras descomprimir."""
    direct = extract_root / "TV-Win.exe"
    if direct.is_file():
        return extract_root
    for path in extract_root.rglob("TV-Win.exe"):
        return path.parent
    raise RuntimeError("El ZIP de actualización no contiene TV-Win.exe.")


def apply_update(info: UpdateInfo, *, exe_name: str = "TV-Win.exe") -> Path:
    """
    Descarga el ZIP, lo prepara y escribe un script que sustituye la app al salir.
    Devuelve la ruta del script de actualización a lanzar antes de cerrar.
    """
    target = app_dir()
    work = Path(tempfile.mkdtemp(prefix="tv-win-update-"))
    zip_path = work / ASSET_NAME
    extract_dir = work / "payload"
    extract_dir.mkdir(parents=True, exist_ok=True)

    _download(info.zip_url, zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)
    payload = _find_payload(extract_dir)

    script = target / "_tvwin_update.cmd"
    # Robocopy: copia portable encima; luego relanza y limpia.
    script.write_text(
        "\r\n".join(
            [
                "@echo off",
                "setlocal",
                "cd /d \"%~dp0\"",
                "echo Actualizando TV-Win…",
                "timeout /t 2 /nobreak >nul",
                f'robocopy "{payload}" "%~dp0." /E /XO /NFL /NDL /NJH /NJS /nc /ns /np >nul',
                f'start "" "%~dp0{exe_name}"',
                f'rmdir /s /q "{work}" >nul 2>&1',
                'del "%~f0" >nul 2>&1',
            ]
        )
        + "\r\n",
        encoding="utf-8",
    )
    return script


def launch_updater(script: Path) -> None:
    creationflags = 0
    if os.name == "nt":
        creationflags = 0x00000008  # DETACHED_PROCESS
        creationflags |= 0x00000200  # CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        ["cmd.exe", "/c", str(script)],
        cwd=str(script.parent),
        creationflags=creationflags,
        close_fds=True,
    )
