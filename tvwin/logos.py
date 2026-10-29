"""Cache local de logos de canal (Pillow + disco en ~/.tv-win/logos)."""

from __future__ import annotations

import hashlib
import threading
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageTk

from .paths import data_dir

USER_AGENT = "TV-Win/1.2 (+https://github.com/Aitorrio/TV-Win)"
LOGO_SIZE = 28


def _logos_dir() -> Path:
    path = data_dir() / "logos"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_file(url: str) -> Path:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:24]
    return _logos_dir() / f"{digest}.png"


def _download(url: str, dest: Path) -> bool:
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "image/*,*/*"},
        )
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read()
        if not raw:
            return False
        tmp = dest.with_suffix(".tmp")
        tmp.write_bytes(raw)
        with Image.open(tmp) as img:
            img = img.convert("RGBA")
            img.thumbnail((LOGO_SIZE, LOGO_SIZE), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (LOGO_SIZE, LOGO_SIZE), (0, 0, 0, 0))
            ox = (LOGO_SIZE - img.width) // 2
            oy = (LOGO_SIZE - img.height) // 2
            canvas.paste(img, (ox, oy), img)
            canvas.save(dest, format="PNG")
        tmp.unlink(missing_ok=True)
        return dest.is_file()
    except (OSError, urllib.error.URLError, ValueError):
        return False


class LogoCache:
    """Descarga perezosa; PhotoImage solo desde el hilo de Tk."""

    def __init__(self) -> None:
        self._photos: dict[str, ImageTk.PhotoImage] = {}
        self._pending: set[str] = set()
        self._lock = threading.Lock()
        self._placeholder: ImageTk.PhotoImage | None = None

    def placeholder(self, master) -> ImageTk.PhotoImage:
        if self._placeholder is None:
            img = Image.new("RGBA", (LOGO_SIZE, LOGO_SIZE), (42, 48, 58, 255))
            self._placeholder = ImageTk.PhotoImage(img, master=master)
        return self._placeholder

    def get(self, url: str | None, master) -> ImageTk.PhotoImage | None:
        if not url:
            return None
        cached = self._photos.get(url)
        if cached is not None:
            return cached
        path = _cache_file(url)
        if path.is_file():
            try:
                photo = ImageTk.PhotoImage(Image.open(path), master=master)
                self._photos[url] = photo
                return photo
            except OSError:
                return None
        return None

    def ensure(self, url: str | None, on_ready) -> None:
        if not url:
            return
        if url in self._photos:
            return
        path = _cache_file(url)
        if path.is_file():
            on_ready(url)
            return
        with self._lock:
            if url in self._pending:
                return
            self._pending.add(url)

        def worker() -> None:
            ok = _download(url, path)
            with self._lock:
                self._pending.discard(url)
            if ok:
                on_ready(url)

        threading.Thread(target=worker, daemon=True).start()
