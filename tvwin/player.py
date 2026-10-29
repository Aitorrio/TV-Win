"""Lanza el reproductor (mpv embebido o del sistema) + Streamlink para Atresplayer."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .channels import Channel
from .paths import vendor_mpv

MPV_CANDIDATES = (
    Path(r"C:\Program Files\MPV Player\mpv.exe"),
    Path(r"C:\Program Files\mpv\mpv.exe"),
    Path(r"C:\Program Files (x86)\MPV Player\mpv.exe"),
)
VLC_CANDIDATES = (
    Path(r"C:\Program Files\VideoLAN\VLC\vlc.exe"),
    Path(r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"),
)

# Evita ventanas de consola al lanzar mpv / helpers en Windows.
_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class PlayerError(RuntimeError):
    pass


@dataclass
class PlayerOptions:
    geometry: str = "80%"
    fullscreen: bool = False


class StreamPlayer:
    def __init__(self, options: PlayerOptions | None = None) -> None:
        self._process: subprocess.Popen[str] | None = None
        self._backend = self._detect_backend()
        self.options = options or PlayerOptions()
        self._last_channel: Channel | None = None
        self._last_media_url: str | None = None

    @property
    def backend_name(self) -> str:
        return self._backend[0]

    @property
    def backend_path(self) -> Path:
        return self._backend[1]

    def _detect_backend(self) -> tuple[str, Path]:
        bundled = vendor_mpv()
        if bundled is not None:
            return "mpv", bundled

        for candidate in MPV_CANDIDATES:
            if candidate.is_file():
                return "mpv", candidate
        mpv = shutil.which("mpv")
        if mpv:
            return "mpv", Path(mpv)

        for candidate in VLC_CANDIDATES:
            if candidate.is_file():
                return "vlc", candidate
        vlc = shutil.which("vlc")
        if vlc:
            return "vlc", Path(vlc)

        raise PlayerError(
            "Falta el motor de vídeo de TV-Win (mpv embebido).\n"
            "Descarga la release oficial o vuelve a generar el portable."
        )

    def _creationflags(self) -> int:
        if os.name != "nt":
            return 0
        # CREATE_NO_WINDOW + NEW_PROCESS_GROUP: sin CMD a la vista.
        return _CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

    def _mpv_window_args(self, title: str) -> list[str]:
        args = [
            "--force-window=immediate",
            "--keep-open=no",
            "--terminal=no",
            "--osc=yes",
            "--ytdl=no",
            f"--title={title}",
            f"--user-agent={_DEFAULT_UA}",
            "--aid=auto",
        ]
        if self.options.fullscreen:
            args.append("--fs")
        else:
            geometry = (self.options.geometry or "80%").strip() or "80%"
            args.append(f"--geometry={geometry}")
        return args

    def stop(self) -> None:
        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None

    def _play_direct(self, channel: Channel, media_url: str) -> None:
        name = self.backend_name
        exe = str(self.backend_path)
        title = f"TV-Win · {channel.name}"
        extra: list[str] = []
        if name == "mpv":
            if channel.referer:
                extra.append(f"--referrer={channel.referer}")
                # Cabeceras HTTP explícitas (DASH Atresmedia necesita Referer).
                extra.append(f"--http-header-fields=Referer: {channel.referer}")
            args = [exe, *self._mpv_window_args(title), *extra, media_url]
        else:
            args = [
                exe,
                "--fullscreen" if self.options.fullscreen else "--no-fullscreen",
                f"--meta-title={title}",
                media_url,
            ]

        self._process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=self._creationflags(),
            stdin=subprocess.DEVNULL,
        )
        self._last_channel = channel
        self._last_media_url = media_url

    def _resolve_streamlink_api(self, page_url: str) -> str:
        try:
            from streamlink import Streamlink
        except ImportError as exc:
            raise PlayerError(
                "Falta el paquete streamlink.\npython -m pip install streamlink"
            ) from exc

        session = Streamlink()
        session.set_option("http-headers", {
            "User-Agent": _DEFAULT_UA,
            "Referer": "https://www.atresplayer.com/",
        })
        streams = session.streams(page_url)
        if not streams:
            raise PlayerError(
                "Sin stream (¿IP fuera de España o canal restringido?)."
            )
        # Preferir calidades con nombre; "best" en Atresplayer es DASH MPD.
        stream = streams.get("best") or streams.get("1080p") or next(iter(streams.values()))
        try:
            media_url = stream.to_url()
        except Exception as exc:  # noqa: BLE001
            raise PlayerError(f"No se pudo resolver el stream: {exc}") from exc
        if not media_url:
            raise PlayerError("Streamlink no devolvió una URL de medios.")
        return media_url

    def _play_via_streamlink(self, channel: Channel) -> None:
        """Atresplayer/YouTube: resolver con API (sin CLI → sin ventana CMD)."""
        if self.backend_name != "mpv":
            raise PlayerError("Atresplayer requiere mpv (no VLC) en esta versión.")

        media_url = self._resolve_streamlink_api(channel.url)
        referer = channel.referer or "https://www.atresplayer.com/"
        patched = Channel(
            id=channel.id,
            name=channel.name,
            group=channel.group,
            url=channel.url,
            logo=channel.logo,
            epg_id=channel.epg_id,
            referer=referer,
            starover=channel.starover,
            attributes=channel.attributes,
            international=channel.international,
        )
        self._play_direct(patched, media_url)

    def _play_mediaset(self, channel: Channel) -> None:
        from .mediaset import MediasetError, resolve_hls

        try:
            media_url = resolve_hls(channel.url, name=channel.name)
        except MediasetError as exc:
            raise PlayerError(str(exc)) from exc

        patched = Channel(
            id=channel.id,
            name=channel.name,
            group=channel.group,
            url=channel.url,
            logo=channel.logo,
            epg_id=channel.epg_id,
            referer="https://www.mediasetinfinity.es/",
            starover=channel.starover,
            attributes=channel.attributes,
            international=channel.international,
        )
        self._play_direct(patched, media_url)

    def play(self, channel: Channel) -> None:
        self.stop()
        if channel.needs_webview:
            self._play_mediaset(channel)
            return
        if not channel.playable:
            raise PlayerError(
                f"{channel.name} no tiene un stream directo usable "
                f"(URL: {channel.url[:80]})."
            )
        if channel.via_streamlink:
            self._play_via_streamlink(channel)
        else:
            self._play_direct(channel, channel.url)

    def set_fullscreen(self, enabled: bool) -> None:
        """Relanza el stream actual con/sin pantalla completa."""
        self.options.fullscreen = enabled
        if self._last_media_url and self._last_channel is not None:
            channel = self._last_channel
            media = self._last_media_url
            self.stop()
            self._play_direct(channel, media)
        elif self._last_channel is not None and self.is_running():
            channel = self._last_channel
            self.play(channel)

    def toggle_fullscreen(self) -> bool:
        self.set_fullscreen(not self.options.fullscreen)
        return self.options.fullscreen

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None
