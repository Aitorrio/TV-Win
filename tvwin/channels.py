"""Carga canales desde el catálogo público de TDT Spain (misma fuente que la APK)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# Descubierto en TDTSpain.apk: versionvN.json + canalesvN.json
VERSION_URL = "https://www.tdtspain.com/canales/versionv1.json"
CHANNELS_URL = "https://www.tdtspain.com/canales/canalesv1.json"
USER_AGENT = "TV-Win/1.2 (personal; compatible; +https://github.com/Aitorrio/TV-Win)"
CACHE_TTL_SECONDS = 6 * 60 * 60

# Grupos preferentes (orden de la app Android: Nacionales primero).
GROUP_PRIORITY = (
    "Nacionales",
    "Informativos",
    "Deportivos",
    "Infantiles",
    "Temáticos A3media",
    "Temáticos RTVE",
    "Temáticos Infinity",
    "Musica",
    "Religiosos",
)


@dataclass(frozen=True)
class Channel:
    id: str
    name: str
    group: str
    url: str
    logo: str | None = None
    epg_id: str | None = None
    referer: str | None = None
    starover: str | None = None
    attributes: str | None = None
    international: bool = False

    @property
    def ambit(self) -> str:
        # Primer grupo si viene compuesto (p.ej. "Infantiles;Galicia")
        return (self.group or "Otros").split(";")[0].strip() or "Otros"

    @property
    def via_streamlink(self) -> bool:
        u = self.url.lower()
        return "atresplayer.com" in u or "youtube.com" in u or "youtu.be" in u

    @property
    def is_direct_stream(self) -> bool:
        u = self.url.lower()
        if not u.startswith(("http://", "https://")):
            return False
        if ".m3u8" in u or u.endswith(".mpd") or u.endswith(".mp4"):
            return True
        # La APK marca RTVE y similares con starover=stream y URL m3u8 directa.
        if self.starover == "stream" and ("m3u8" in u or "mpd" in u or "rtve" in u):
            return True
        return False

    @property
    def needs_webview(self) -> bool:
        """Mediaset Infinity: la APK usa navegador embebido (browser=ctv), no m3u8 abierto."""
        attrs = (self.attributes or "").lower()
        u = self.url.lower()
        return "browser=ctv" in attrs or "mediasetinfinity.es" in u or "mitele.es" in u

    @property
    def playable(self) -> bool:
        """Directo o Atresplayer (mpv). Mediaset cuenta como abrible vía Edge app."""
        if self.needs_webview:
            return True
        if self.via_streamlink:
            return True
        return self.is_direct_stream

    @property
    def label(self) -> str:
        marks: list[str] = []
        if self.via_streamlink and "atresplayer" in self.url.lower():
            marks.append("Atresplayer")
        elif self.via_streamlink:
            marks.append("Streamlink")
        if self.needs_webview:
            marks.append("Mediaset HLS")
        elif not self.is_direct_stream and not self.via_streamlink:
            marks.append("no disponible")
        suffix = f" · {' · '.join(marks)}" if marks else ""
        return f"{self.name}{suffix}"

    @property
    def format(self) -> str:
        if self.needs_webview:
            return "hls"
        if self.via_streamlink and "atresplayer" in self.url.lower():
            return "atres"
        if self.via_streamlink:
            return "yt"
        if not self.is_direct_stream and not self.via_streamlink:
            return "—"
        if ".mpd" in self.url.lower():
            return "mpd"
        return "m3u8"


def _cache_dir() -> Path:
    base = Path.home() / ".tv-win"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _http_get(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _read_json_cache(path: Path) -> dict | None:
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > CACHE_TTL_SECONDS:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_catalog(force_refresh: bool = False) -> dict:
    cache = _cache_dir() / "tdtspain_canalesv1.json"
    version_cache = _cache_dir() / "tdtspain_versionv1.json"

    if not force_refresh:
        cached = _read_json_cache(cache)
        if cached is not None:
            return cached

    try:
        version_raw = _http_get(VERSION_URL)
        version_cache.write_bytes(version_raw)
        raw = _http_get(CHANNELS_URL)
        cache.write_bytes(raw)
        return json.loads(raw.decode("utf-8"))
    except urllib.error.URLError as exc:
        if cache.exists():
            return json.loads(cache.read_text(encoding="utf-8"))
        raise RuntimeError(f"No se pudo descargar la lista de TDT Spain: {exc}") from exc


def _group_rank(group: str) -> int:
    main = (group or "Otros").split(";")[0].strip()
    try:
        return GROUP_PRIORITY.index(main)
    except ValueError:
        return 100 + abs(hash(main)) % 10_000


def load_channels(
    *,
    force_refresh: bool = False,
    include_unplayable: bool = True,
) -> list[Channel]:
    catalog = fetch_catalog(force_refresh=force_refresh)
    items = catalog.get("canales") or []
    channels: list[Channel] = []

    for item in items:
        url = (item.get("url") or "").strip()
        if not url:
            continue
        channel = Channel(
            id=item.get("id") or item.get("name") or url,
            name=item.get("name") or "Sin nombre",
            group=item.get("group") or "Otros",
            url=url,
            logo=item.get("logocolor") or item.get("logo"),
            epg_id=item.get("epgid"),
            referer=item.get("referer") or None,
            starover=item.get("starover") or None,
            attributes=item.get("atributtes") or item.get("attributes") or None,
            international=str(item.get("internacional") or "").lower() == "true",
        )
        if not include_unplayable and not channel.playable:
            continue
        channels.append(channel)

    # El JSON de TDT Spain ya viene ordenado (Nacionales primero).
    return channels


def ambits_from(channels: list[Channel]) -> list[str]:
    seen: list[str] = []
    for channel in channels:
        if channel.ambit not in seen:
            seen.append(channel.ambit)
    return sorted(seen, key=_group_rank)
