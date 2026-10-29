"""Comprobación opcional de nuevas releases en GitHub."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from . import __version__

RELEASES_API = "https://api.github.com/repos/Aitorrio/TV-Win/releases/latest"
USER_AGENT = f"TV-Win/{__version__} (+https://github.com/Aitorrio/TV-Win)"


def _parse_version(tag: str) -> tuple[int, ...]:
    cleaned = tag.strip().lstrip("vV")
    parts = re.findall(r"\d+", cleaned)
    if not parts:
        return (0,)
    return tuple(int(p) for p in parts)


def is_newer(remote: str, local: str = __version__) -> bool:
    return _parse_version(remote) > _parse_version(local)


def check_latest() -> tuple[str, str] | None:
    """Devuelve (tag, html_url) si hay una release más nueva; si no, None."""
    request = urllib.request.Request(
        RELEASES_API,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None

    tag = str(data.get("tag_name") or "").strip()
    url = str(data.get("html_url") or "").strip()
    if not tag or not url:
        return None
    if not is_newer(tag):
        return None
    return tag, url
