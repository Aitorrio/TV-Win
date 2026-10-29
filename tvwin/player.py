"""Lanza el reproductor (mpv embebido o del sistema) + Streamlink para Atresplayer."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
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
        self._streamlink_config = Path(tempfile.gettempdir()) / "tv-win-streamlink.conf"
        if not self._streamlink_config.exists():
            self._streamlink_config.write_text("", encoding="utf-8")

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

    def _streamlink_cmd(self) -> list[str] | None:
        exe = shutil.which("streamlink")
        if exe:
            return [exe]
        if getattr(sys, "frozen", False):
            return None
        return [sys.executable, "-m", "streamlink"]

    def _mpv_window_args(self, title: str) -> list[str]:
        args = [
            "--force-window=immediate",
            "--keep-open=no",
            "--terminal=no",
            "--osc=yes",
            f"--title={title}",
        ]
        if self.options.fullscreen:
            args.append("--fs")
        else:
            geometry = (self.options.geometry or "80%").strip() or "80%"
            args.append(f"--geometry={geometry}")
        return args

    def _player_args_string(self, title: str) -> str:
        parts = self._mpv_window_args(title)
        # streamlink --player-args: espacios separados
        return " ".join(parts)

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
        if channel.referer and name == "mpv":
            extra.append(f"--referrer={channel.referer}")

        if name == "mpv":
            args = [exe, *self._mpv_window_args(title), *extra, media_url]
        else:
            args = [
                exe,
                "--fullscreen" if self.options.fullscreen else "--no-fullscreen",
                f"--meta-title={title}",
                media_url,
            ]

        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

        self._process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
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
        streams = session.streams(page_url)
        if not streams:
            raise PlayerError(
                "Sin stream (¿IP fuera de España o canal restringido?)."
            )
        stream = streams.get("best") or next(iter(streams.values()))
        try:
            return stream.to_url()
        except Exception as exc:  # noqa: BLE001
            raise PlayerError(f"No se pudo resolver el stream: {exc}") from exc

    def _play_via_streamlink_cli(self, channel: Channel, cmd: list[str]) -> None:
        title = f"TV-Win · {channel.name}"
        args = [
            *cmd,
            "--config",
            str(self._streamlink_config),
            "--player",
            str(self.backend_path),
            "--player-args",
            self._player_args_string(title),
            "--default-stream",
            "best",
            "--retry-streams",
            "3",
            channel.url,
        ]
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

        self._process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creationflags,
        )
        try:
            code = self._process.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            self._last_channel = channel
            self._last_media_url = None
            return
        err = ""
        if self._process.stderr is not None:
            err = self._process.stderr.read() or ""
        self._process = None
        hint = err.strip().splitlines()[-1] if err.strip() else f"código {code}"
        raise PlayerError(f"Streamlink CLI falló ({hint}).")

    def _play_via_streamlink(self, channel: Channel) -> None:
        if self.backend_name != "mpv":
            raise PlayerError("Atresplayer requiere mpv (no VLC) en esta versión.")

        cmd = self._streamlink_cmd()
        if cmd is not None:
            try:
                self._play_via_streamlink_cli(channel, cmd)
                return
            except PlayerError:
                pass

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
