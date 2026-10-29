"""Lanza el reproductor (mpv embebido o del sistema) + Streamlink para Atresplayer."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .channels import Channel
from .paths import vendor_ffmpeg, vendor_mpv

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
        self._process: subprocess.Popen[bytes] | None = None
        self._backend = self._detect_backend()
        self.options = options or PlayerOptions()
        self._last_channel: Channel | None = None
        self._last_media_url: str | None = None
        self._piped = False
        self._stream_fd: Any | None = None
        self._relay_stop = threading.Event()
        self._relay_thread: threading.Thread | None = None

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

    def _ffmpeg(self) -> Path | None:
        bundled = vendor_ffmpeg()
        if bundled is not None:
            return bundled
        found = shutil.which("ffmpeg")
        return Path(found) if found else None

    def _creationflags(self, *, pipe_stdin: bool = False) -> int:
        if os.name != "nt":
            return 0
        # CREATE_NEW_PROCESS_GROUP rompe el stdin pipe hacia mpv en Windows.
        if pipe_stdin:
            return _CREATE_NO_WINDOW
        return _CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

    def _mpv_window_args(self, title: str, *, from_pipe: bool = False) -> list[str]:
        args = [
            "--force-window=immediate",
            "--keep-open=yes" if from_pipe else "--keep-open=no",
            "--terminal=no",
            "--osc=yes",
            "--ytdl=no",
            f"--title={title}",
            f"--user-agent={_DEFAULT_UA}",
            "--aid=auto",
        ]
        if from_pipe:
            # MPEG-TS remuxeado por Streamlink+ffmpeg
            args.extend(
                [
                    "--cache=yes",
                    "--force-seekable=no",
                ]
            )
        if self.options.fullscreen:
            args.append("--fs")
        else:
            geometry = (self.options.geometry or "80%").strip() or "80%"
            args.append(f"--geometry={geometry}")
        return args

    def stop(self) -> None:
        self._relay_stop.set()
        fd = self._stream_fd
        self._stream_fd = None
        if fd is not None:
            try:
                fd.close()
            except Exception:  # noqa: BLE001
                pass
        if self._process is not None:
            if self._process.poll() is None:
                try:
                    if self._process.stdin is not None:
                        self._process.stdin.close()
                except Exception:  # noqa: BLE001
                    pass
                self._process.terminate()
                try:
                    self._process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._process.kill()
            self._process = None
        self._piped = False
        self._relay_thread = None

    def _play_direct(self, channel: Channel, media_url: str) -> None:
        name = self.backend_name
        exe = str(self.backend_path)
        title = f"TV-Win · {channel.name}"
        extra: list[str] = []
        if name == "mpv":
            if channel.referer:
                extra.append(f"--referrer={channel.referer}")
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
            creationflags=self._creationflags(pipe_stdin=False),
            stdin=subprocess.DEVNULL,
        )
        self._last_channel = channel
        self._last_media_url = media_url
        self._piped = False

    def _relay_to_mpv(self, fd: Any, proc: subprocess.Popen[bytes]) -> None:
        try:
            while not self._relay_stop.is_set():
                chunk = fd.read(64 * 1024)
                if not chunk:
                    break
                if proc.stdin is None:
                    break
                try:
                    proc.stdin.write(chunk)
                    proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    break
        finally:
            try:
                fd.close()
            except Exception:  # noqa: BLE001
                pass
            if proc.stdin is not None:
                try:
                    proc.stdin.close()
                except Exception:  # noqa: BLE001
                    pass

    def _play_streamlink_piped(self, channel: Channel) -> None:
        """DASH Atresplayer: Streamlink + ffmpeg mux → pipe MPEG-TS a mpv."""
        try:
            from streamlink import Streamlink
        except ImportError as exc:
            raise PlayerError(
                "Falta el paquete streamlink.\npython -m pip install streamlink"
            ) from exc

        ffmpeg = self._ffmpeg()
        if ffmpeg is None:
            raise PlayerError(
                "Atresplayer necesita ffmpeg embebido para unir vídeo y audio.\n"
                "Descarga la release latest-stable o ejecuta scripts\\fetch_ffmpeg.ps1."
            )

        session = Streamlink()
        session.set_option(
            "http-headers",
            {
                "User-Agent": _DEFAULT_UA,
                "Referer": channel.referer or "https://www.atresplayer.com/",
            },
        )
        session.set_option("ffmpeg-ffmpeg", str(ffmpeg))
        session.set_option("ffmpeg-fout", "mpegts")
        session.set_option("ffmpeg-no-validation", True)

        streams = session.streams(channel.url)
        if not streams:
            raise PlayerError(
                "Sin stream (¿IP fuera de España o canal restringido?)."
            )
        stream = (
            streams.get("best")
            or streams.get("1080p")
            or streams.get("720p")
            or next(iter(streams.values()))
        )

        try:
            fd = stream.open()
        except Exception as exc:  # noqa: BLE001
            raise PlayerError(f"No se pudo abrir el stream: {exc}") from exc

        # Primer bloque antes de abrir mpv: evita que cierre por stdin vacío.
        try:
            first = fd.read(256 * 1024)
        except Exception as exc:  # noqa: BLE001
            try:
                fd.close()
            except Exception:  # noqa: BLE001
                pass
            raise PlayerError(f"Sin datos del stream: {exc}") from exc
        if not first:
            try:
                fd.close()
            except Exception:  # noqa: BLE001
                pass
            raise PlayerError(
                "Streamlink no generó medios (¿falta ffmpeg o GEO?)."
            )

        title = f"TV-Win · {channel.name}"
        args = [
            str(self.backend_path),
            *self._mpv_window_args(title, from_pipe=True),
            "-",
        ]
        self._relay_stop.clear()
        self._stream_fd = fd
        self._process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=self._creationflags(pipe_stdin=True),
        )
        assert self._process.stdin is not None
        try:
            self._process.stdin.write(first)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            self.stop()
            raise PlayerError(f"mpv rechazó el stream: {exc}") from exc

        self._relay_thread = threading.Thread(
            target=self._relay_to_mpv,
            args=(fd, self._process),
            daemon=True,
        )
        self._relay_thread.start()
        self._last_channel = channel
        self._last_media_url = None
        self._piped = True

    def _play_via_streamlink(self, channel: Channel) -> None:
        if self.backend_name != "mpv":
            raise PlayerError("Atresplayer requiere mpv (no VLC) en esta versión.")
        self._play_streamlink_piped(channel)

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
        channel = self._last_channel
        if channel is None:
            return
        if self._piped or self._last_media_url is None:
            self.play(channel)
            return
        media = self._last_media_url
        self.stop()
        self._play_direct(channel, media)

    def toggle_fullscreen(self) -> bool:
        self.set_fullscreen(not self.options.fullscreen)
        return self.options.fullscreen

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None
