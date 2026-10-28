"""Interfaz de TV-Win: catálogo TDT Spain y reproducción nativa."""

from __future__ import annotations

import json
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from . import __author__, __url__, __version__
from .channels import Channel, ambits_from, load_channels
from .paths import app_dir
from .player import PlayerError, StreamPlayer


def _prefs_path() -> Path:
    p = Path.home() / ".tv-win"
    p.mkdir(parents=True, exist_ok=True)
    return p / "prefs.json"


def _load_prefs() -> dict:
    path = _prefs_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_prefs(data: dict) -> None:
    _prefs_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class TVWinApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"TV-Win {__version__}")
        self.geometry("960x640")
        self.minsize(760, 500)
        self.configure(bg="#0e1116")

        self._prefs = _load_prefs()
        self._channels: list[Channel] = []
        self._visible: list[Channel] = []
        self._player: StreamPlayer | None = None
        self._current: Channel | None = None
        self._busy = False

        self._build_style()
        self._build_ui()
        self.after(80, self._bootstrap)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Return>", lambda _e: self._play_selected())
        self.bind("<F5>", lambda _e: self._reload(force=True))
        self.bind("<Escape>", lambda _e: self._stop_playback())

    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        bg = "#0e1116"
        panel = "#171b22"
        fg = "#e8eaed"
        muted = "#8b939e"
        accent = "#2f6fed"
        border = "#2a303a"

        style.configure(".", background=bg, foreground=fg, fieldbackground=panel)
        style.configure("TFrame", background=bg)
        style.configure("Panel.TFrame", background=panel)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("Muted.TLabel", background=bg, foreground=muted)
        style.configure(
            "Title.TLabel",
            background=bg,
            foreground=fg,
            font=("Segoe UI Semibold", 18),
        )
        style.configure(
            "Brand.TLabel",
            background=bg,
            foreground=accent,
            font=("Segoe UI Semibold", 11),
        )
        style.configure("TButton", padding=(12, 8))
        style.configure("Accent.TButton", padding=(14, 8))
        style.configure("TCheckbutton", background=bg, foreground=fg)
        style.configure("TCombobox", fieldbackground=panel, foreground=fg)
        style.configure("TEntry", fieldbackground=panel, foreground=fg)
        style.map("TButton", background=[("active", accent)])
        style.configure(
            "Channels.Treeview",
            background=panel,
            foreground=fg,
            fieldbackground=panel,
            rowheight=30,
            borderwidth=0,
            relief="flat",
        )
        style.configure(
            "Channels.Treeview.Heading",
            background=border,
            foreground=fg,
            relief="flat",
            font=("Segoe UI Semibold", 9),
        )
        style.map(
            "Channels.Treeview",
            background=[("selected", accent)],
            foreground=[("selected", "#ffffff")],
        )

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=18)
        root.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(root)
        header.pack(fill=tk.X)

        left = ttk.Frame(header)
        left.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(left, text="TV-Win", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(
            left,
            text="Televisión en abierto · sin navegador · sin cookies de webs",
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(2, 0))

        right = ttk.Frame(header)
        right.pack(side=tk.RIGHT)
        ttk.Label(right, text=__author__, style="Brand.TLabel").pack(anchor=tk.E)
        ttk.Button(right, text="Acerca de", command=self._about).pack(anchor=tk.E, pady=(6, 0))

        controls = ttk.Frame(root)
        controls.pack(fill=tk.X, pady=(16, 10))

        ttk.Label(controls, text="Grupo").pack(side=tk.LEFT)
        self.ambit_var = tk.StringVar(value=self._prefs.get("group", "Nacionales"))
        self.ambit_combo = ttk.Combobox(
            controls,
            textvariable=self.ambit_var,
            state="readonly",
            width=26,
            values=["Todos", "Nacionales"],
        )
        self.ambit_combo.pack(side=tk.LEFT, padx=(8, 14))
        self.ambit_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_filter_change())

        ttk.Label(controls, text="Buscar").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        search = ttk.Entry(controls, textvariable=self.search_var, width=24)
        search.pack(side=tk.LEFT, padx=(8, 12))
        self.search_var.trace_add("write", lambda *_: self._apply_filters())

        self.only_playable_var = tk.BooleanVar(value=bool(self._prefs.get("only_stream", False)))
        ttk.Checkbutton(
            controls,
            text="Solo HLS/Atres",
            variable=self.only_playable_var,
            command=self._on_filter_change,
        ).pack(side=tk.LEFT)

        ttk.Button(controls, text="Actualizar", command=lambda: self._reload(force=True)).pack(
            side=tk.RIGHT
        )
        ttk.Button(
            controls,
            text="Ver canal",
            style="Accent.TButton",
            command=self._play_selected,
        ).pack(side=tk.RIGHT, padx=(0, 8))

        list_frame = ttk.Frame(root, style="Panel.TFrame")
        list_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("ambit", "format")
        self.tree = ttk.Treeview(
            list_frame,
            columns=columns,
            show="tree headings",
            style="Channels.Treeview",
            selectmode="browse",
        )
        self.tree.heading("#0", text="Canal", anchor=tk.W)
        self.tree.heading("ambit", text="Grupo", anchor=tk.W)
        self.tree.heading("format", text="Tipo", anchor=tk.W)
        self.tree.column("#0", width=420, stretch=True)
        self.tree.column("ambit", width=200, stretch=False)
        self.tree.column("format", width=90, stretch=False)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
        self.tree.bind("<Double-1>", lambda _e: self._play_selected())

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        footer = ttk.Frame(root)
        footer.pack(fill=tk.X, pady=(12, 0))
        self.status_var = tk.StringVar(value="Iniciando…")
        ttk.Label(footer, textvariable=self.status_var, style="Muted.TLabel").pack(side=tk.LEFT)
        ttk.Label(
            footer,
            text="Enter · ver  ·  Esc · parar  ·  F5 · actualizar",
            style="Muted.TLabel",
        ).pack(side=tk.RIGHT)

    def _about(self) -> None:
        messagebox.showinfo(
            "Acerca de TV-Win",
            f"TV-Win {__version__}\n"
            f"{__author__}\n\n"
            "Visor de TDT en abierto para Windows.\n"
            "Sin navegador, sin cookies de webs de terceros\n"
            "y sin publicidad de aplicaciones.\n\n"
            "Catálogo: TDT Spain (fuentes oficiales de cada cadena).\n"
            "Reproductor: motor mpv embebido.\n\n"
            f"{__url__}",
        )

    def _bootstrap(self) -> None:
        try:
            self._player = StreamPlayer()
        except PlayerError as exc:
            messagebox.showerror("Reproductor no encontrado", str(exc))
            self.destroy()
            return
        self._reload(force=False)

    def _on_filter_change(self) -> None:
        self._prefs["group"] = self.ambit_var.get()
        self._prefs["only_stream"] = self.only_playable_var.get()
        _save_prefs(self._prefs)
        self._apply_filters()

    def _reload(self, *, force: bool) -> None:
        self.status_var.set("Actualizando catálogo…")
        self.update_idletasks()
        try:
            self._channels = load_channels(force_refresh=force)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Error al cargar canales", str(exc))
            self.status_var.set("Error al cargar canales")
            return

        ambits = ["Todos", *ambits_from(self._channels)]
        self.ambit_combo.configure(values=ambits)
        if self.ambit_var.get() not in ambits:
            self.ambit_var.set("Nacionales" if "Nacionales" in ambits else "Todos")
        self._apply_filters()
        self._restore_selection()
        playable = sum(
            1
            for c in self._channels
            if c.is_direct_stream or c.via_streamlink or c.needs_webview
        )
        backend = self._player.backend_name if self._player else "?"
        self.status_var.set(
            f"{len(self._visible)} canales · {playable} disponibles · motor {backend}"
        )

    def _apply_filters(self) -> None:
        query = self.search_var.get().strip().lower()
        ambit = self.ambit_var.get()
        only = self.only_playable_var.get()
        visible: list[Channel] = []
        for channel in self._channels:
            if only and (
                channel.needs_webview
                or (not channel.is_direct_stream and not channel.via_streamlink)
            ):
                continue
            if ambit != "Todos" and channel.ambit != ambit:
                continue
            haystack = f"{channel.name} {channel.ambit}".lower()
            if query and query not in haystack:
                continue
            visible.append(channel)
        self._visible = visible
        self._render_list()

    def _render_list(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, channel in enumerate(self._visible):
            self.tree.insert(
                "",
                tk.END,
                iid=str(index),
                text=channel.label,
                values=(channel.ambit, channel.format.upper()),
            )

    def _restore_selection(self) -> None:
        last_id = self._prefs.get("last_channel_id")
        if not last_id:
            return
        for index, channel in enumerate(self._visible):
            if channel.id == last_id:
                self.tree.selection_set(str(index))
                self.tree.see(str(index))
                return

    def _selected_channel(self) -> Channel | None:
        selection = self.tree.selection()
        if not selection:
            return None
        try:
            return self._visible[int(selection[0])]
        except (IndexError, ValueError):
            return None

    def _stop_playback(self) -> None:
        if self._player is not None:
            self._player.stop()
        self.status_var.set("Reproducción detenida")

    def _play_selected(self) -> None:
        if self._busy:
            return
        channel = self._selected_channel()
        if channel is None:
            messagebox.showinfo("TV-Win", "Selecciona un canal de la lista.")
            return
        if self._player is None:
            return

        self._busy = True
        if channel.via_streamlink:
            self.status_var.set(f"Preparando {channel.name}…")
        elif channel.needs_webview:
            self.status_var.set(f"Conectando {channel.name}…")
        else:
            self.status_var.set(f"Abriendo {channel.name}…")
        self.update_idletasks()

        def worker() -> None:
            error: Exception | None = None
            try:
                assert self._player is not None
                self._player.play(channel)
            except Exception as exc:  # noqa: BLE001
                error = exc
            self.after(0, lambda: self._play_finished(channel, error))

        threading.Thread(target=worker, daemon=True).start()

    def _play_finished(self, channel: Channel, error: Exception | None) -> None:
        self._busy = False
        if error is not None:
            messagebox.showerror("No se pudo reproducir", str(error))
            self.status_var.set(f"Error · {channel.name}")
            return
        self._current = channel
        self._prefs["last_channel_id"] = channel.id
        self._prefs["group"] = self.ambit_var.get()
        _save_prefs(self._prefs)
        self.status_var.set(f"En directo · {channel.name}")

    def _on_close(self) -> None:
        if self._player is not None:
            self._player.stop()
        self._prefs["group"] = self.ambit_var.get()
        self._prefs["only_stream"] = self.only_playable_var.get()
        _save_prefs(self._prefs)
        self.destroy()


def main() -> None:
    # Evita que el cwd afecte a recursos del portable.
    try:
        import os

        os.chdir(app_dir())
    except OSError:
        pass
    app = TVWinApp()
    app.mainloop()
