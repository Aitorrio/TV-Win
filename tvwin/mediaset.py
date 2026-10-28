"""Resuelve streams Mediaset Infinity como la APK: SSAI/HLS con anuncios de la cadena."""

from __future__ import annotations

import json
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

NOWNEXT_URL = (
    "https://services-ott-prod-fe.mediaset.net/esp/static/nownext/v3.0/nownext.json"
)
SSAI_TMPL = "https://pubads.g.doubleclick.net/ssai/event/{asset}/streams"
USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 6) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36"
)
CACHE_TTL = 6 * 60 * 60


class MediasetError(RuntimeError):
    pass


def _cache_path() -> Path:
    base = Path.home() / ".tv-win"
    base.mkdir(parents=True, exist_ok=True)
    return base / "mediaset_nownext.json"


def _http_json(url: str, *, data: bytes | None = None, form: bool = False) -> dict:
    headers = {
        "User-Agent": USER_AGENT,
        "Origin": "https://www.mediasetinfinity.es",
        "Referer": "https://www.mediasetinfinity.es/",
        "Accept": "application/json, text/plain, */*",
    }
    if data is not None:
        headers["Content-Type"] = (
            "application/x-www-form-urlencoded" if form else "application/json"
        )
    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:200].decode("utf-8", "replace")
        raise MediasetError(f"HTTP {exc.code} en Mediaset: {detail}") from exc
    except urllib.error.URLError as exc:
        raise MediasetError(f"No se pudo contactar con Mediaset: {exc}") from exc


def fetch_nownext(force_refresh: bool = False) -> dict:
    cache = _cache_path()
    if (
        not force_refresh
        and cache.exists()
        and time.time() - cache.stat().st_mtime < CACHE_TTL
    ):
        return json.loads(cache.read_text(encoding="utf-8"))
    data = _http_json(NOWNEXT_URL)
    cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def _stations(nownext: dict) -> list[dict]:
    listings = (nownext.get("response") or {}).get("listings") or {}
    out: list[dict] = []
    for block in listings.values():
        stations = (block or {}).get("stations") or {}
        if isinstance(stations, dict):
            out.extend(stations.values())
        elif isinstance(stations, list):
            out.extend(stations)
    return out


def _dai_asset(station: dict) -> str | None:
    mapping = station.get("mediasetstation$daiAssetKeyMap") or {}
    raw = mapping.get("*|mobile") or mapping.get("*|browser")
    if not raw:
        return None
    # Formato típico: "hls|Kij3D1mCTmCxREg3up5wFQ"
    if "|" in raw:
        return raw.split("|", 1)[1].strip() or None
    return raw.strip() or None


def find_station(page_url: str = "", name: str = "") -> dict | None:
    nownext = fetch_nownext()
    stations = _stations(nownext)
    page = (page_url or "").rstrip("/").lower()
    name_l = (name or "").strip().lower()

    for station in stations:
        video = (station.get("mediasetstation$videoPageUrl") or "").rstrip("/").lower()
        if page and video and page == video:
            return station

    for station in stations:
        video = (station.get("mediasetstation$videoPageUrl") or "").rstrip("/").lower()
        if page and video and (page in video or video in page):
            return station

    for station in stations:
        title = (station.get("title") or "").strip().lower()
        if name_l and title == name_l:
            return station

    # Match por slug en URL: .../directo/cuatro/
    slug = ""
    if "/directo/" in page:
        slug = page.rsplit("/directo/", 1)[-1].strip("/")
    if slug:
        for station in stations:
            video = (station.get("mediasetstation$videoPageUrl") or "").lower()
            if slug in video:
                return station
            title = (station.get("title") or "").lower().replace(" ", "")
            if slug.replace("-", "") in title.replace(" ", ""):
                return station
    return None


def resolve_hls(page_url: str, *, name: str = "") -> str:
    """Devuelve un manifiesto HLS temporal (con anuncios de la cadena vía SSAI)."""
    station = find_station(page_url, name)
    if station is None:
        raise MediasetError(
            f"No se encontró la emisora Mediaset para {name or page_url}."
        )
    asset = _dai_asset(station)
    if not asset:
        raise MediasetError(
            f"{station.get('title') or name} no publica asset DAI/HLS abierto."
        )

    form = urllib.parse.urlencode(
        {
            "ppid": str(uuid.uuid4()),
            "vpa": "auto",
            "wta": "1",
            "vpmute": "0",
            "cust_params": "device=mobile&os=android&userType=infinity",
            "url": page_url or (station.get("mediasetstation$videoPageUrl") or ""),
        }
    ).encode("utf-8")

    data = _http_json(SSAI_TMPL.format(asset=asset), data=form, form=True)
    manifest = data.get("stream_manifest")
    if not manifest:
        raise MediasetError("Mediaset no devolvió stream_manifest.")
    return manifest
