"""Interfaz de TV-Win: catálogo TDT Spain y reproducción nativa."""

from __future__ import annotations

import json
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from . import __author__, __url__, __version__
from .channels import Channel, ambits_from, load_channels
from .logos import LogoCache
from .paths import app_dir, asset_path, data_dir
from .player import PlayerError, PlayerOptions, StreamPlayer
from .updates import check_latest

DEFAULT_PREFS: dict[str, Any] = {
    "group": "Nacionales",
    "only_stream": False,
    "only_favorites": False,
    "favorites": [],
    "last_channel_id": None,
    "geometry_mpv": "80%",
    "start_fullscreen": False,
    "minimize_to_tray": False,
    "check_updates": True,
}


def _prefs_path() -> Path:
    return data_dir() / "prefs.json"


def _load_prefs() -> dict[str, Any]:
    path = _prefs_path()
    prefs = dict(DEFAULT_PREFS)
    if not path.exists():
        return prefs
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            prefs.update(loaded)
    except (OSError, json.JSONDecodeError):
        pass
    if not isinstance(prefs.get("favorites"), list):
        prefs["favorites"] = []
    return prefs


def _save_prefs(data: dict[str, Any]) -> None:
    _prefs_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class TVWinApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"TV-Win {__version__}")
        self.geometry("1020x680")
        self.minsize(820, 540)
        self.configure(bg="#0e1116")

        self._prefs = _load_prefs()
        self._channels: list[Channel] = []
        self._visible: list[Channel] = []
        self._player: StreamPlayer | None = None
        self._current: Channel | None = None
        self._busy = False
        self._favorites: set[str] = set(str(x) for x in self._prefs.get("favorites", []))
        self._logos = LogoCache()
        self._logo_imgs: dict[str, Any] = {}
        self._tray_icon = None
        self._tray_thread: threading.Thread | None = None
        self._quitting = False
        self._update_url: str | None = None

        self._set_window_icon()
        self._build_style()
        self._build_ui()
        self._bind_keys()
        self.after(80, self._bootstrap)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # --- chrome -----------------------------------------------------------------

    def _set_window_icon(self) -> None:
        ico = asset_path("tv-win.ico")
        png = asset_path("tv-win.png")
        try:
            if ico.is_file():
                self.iconbitmap(default=str(ico))
        except tk.TclError:
            pass
        try:
            if png.is_file():
                self._app_icon = tk.PhotoImage(file=str(png))
                self.iconphoto(True, self._app_icon)
        except tk.TclError:
            self._app_icon = None

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

        self._colors = {
            "bg": bg,
            "panel": panel,
            "fg": fg,
            "muted": muted,
            "accent": accent,
            "border": border,
        }

        style.configure(".", background=bg, foreground=fg, fieldbackground=panel)
        style.configure("TFrame", background=bg)
        style.configure("Panel.TFrame", background=panel)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("Muted.TLabel", background=bg, foreground=muted)
        style.configure(
            "Title.TLabel",
            background=bg,
            foreground=fg,
            font=("Segoe UI Semibold", 20),
        )
        style.configure(
            "Brand.TLabel",
            background=bg,
            foreground=accent,
            font=("Segoe UI Semibold", 10),
        )
        style.configure(
            "Now.TLabel",
            background=bg,
            foreground=fg,
            font=("Segoe UI Semibold", 10),
        )
        style.configure(
            "Update.TLabel",
            background=bg,
            foreground="#f0c14b",
            font=("Segoe UI Semibold", 9),
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
            rowheight=36,
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

        brand = ttk.Frame(header)
        brand.pack(side=tk.LEFT, fill=tk.X, expand=True)

        title_row = ttk.Frame(brand)
        title_row.pack(anchor=tk.W)
        png = asset_path("tv-win-64.png")
        if png.is_file():
            try:
                from PIL import Image, ImageTk

                img = Image.open(png).resize((36, 36))
                self._header_logo = ImageTk.PhotoImage(img)
                ttk.Label(title_row, image=self._header_logo).pack(side=tk.LEFT, padx=(0, 10))
            except Exception:  # noqa: BLE001
                pass
        ttk.Label(title_row, text="TV-Win", style="Title.TLabel").pack(side=tk.LEFT)

        ttk.Label(
            brand,
            text="Televisión en abierto · sin navegador · sin cookies de webs",
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(4, 0))

        right = ttk.Frame(header)
        right.pack(side=tk.RIGHT)
        ttk.Label(right, text=__author__, style="Brand.TLabel").pack(anchor=tk.E)
        btns = ttk.Frame(right)
        btns.pack(anchor=tk.E, pady=(8, 0))
        ttk.Button(btns, text="Ajustes", command=self._open_settings).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="Acerca de", command=self._about).pack(side=tk.LEFT)

        controls = ttk.Frame(root)
        controls.pack(fill=tk.X, pady=(16, 10))

        ttk.Label(controls, text="Grupo").pack(side=tk.LEFT)
        self.ambit_var = tk.StringVar(value=self._prefs.get("group", "Nacionales"))
        self.ambit_combo = ttk.Combobox(
            controls,
            textvariable=self.ambit_var,
            state="readonly",
            width=24,
            values=["Todos", "Nacionales"],
        )
        self.ambit_combo.pack(side=tk.LEFT, padx=(8, 12))
        self.ambit_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_filter_change())

        ttk.Label(controls, text="Buscar").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        search = ttk.Entry(controls, textvariable=self.search_var, width=22)
        search.pack(side=tk.LEFT, padx=(8, 12))
        self.search_var.trace_add("write", lambda *_: self._apply_filters())

        self.only_playable_var = tk.BooleanVar(value=bool(self._prefs.get("only_stream", False)))
        ttk.Checkbutton(
            controls,
            text="Solo HLS/Atres",
            variable=self.only_playable_var,
            command=self._on_filter_change,
        ).pack(side=tk.LEFT, padx=(0, 8))

        self.only_fav_var = tk.BooleanVar(value=bool(self._prefs.get("only_favorites", False)))
        ttk.Checkbutton(
            controls,
            text="Favoritos",
            variable=self.only_fav_var,
            command=self._on_filter_change,
        ).pack(side=tk.LEFT)

        ttk.Button(controls, text="Actualizar", command=lambda: self._reload(force=True)).pack(
            side=tk.RIGHT
        )
        ttk.Button(controls, text="Siguiente", command=lambda: self._zap(1)).pack(
            side=tk.RIGHT, padx=(0, 6)
        )
        ttk.Button(controls, text="Anterior", command=lambda: self._zap(-1)).pack(
            side=tk.RIGHT, padx=(0, 6)
        )
        ttk.Button(
            controls,
            text="Ver canal",
            style="Accent.TButton",
            command=self._play_selected,
        ).pack(side=tk.RIGHT, padx=(0, 8))

        list_frame = ttk.Frame(root, style="Panel.TFrame")
        list_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("fav", "ambit", "format")
        self.tree = ttk.Treeview(
            list_frame,
            columns=columns,
            show="tree headings",
            style="Channels.Treeview",
            selectmode="browse",
        )
        self.tree.heading("#0", text="Canal", anchor=tk.W)
        self.tree.heading("fav", text="★", anchor=tk.CENTER)
        self.tree.heading("ambit", text="Grupo", anchor=tk.W)
        self.tree.heading("format", text="Tipo", anchor=tk.W)
        self.tree.column("#0", width=460, stretch=True, minwidth=200)
        self.tree.column("fav", width=44, stretch=False, anchor=tk.CENTER)
        self.tree.column("ambit", width=190, stretch=False)
        self.tree.column("format", width=80, stretch=False)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
        self.tree.bind("<Double-1>", lambda _e: self._play_selected())
        self.tree.bind("<Button-1>", self._on_tree_click)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        footer = ttk.Frame(root)
        footer.pack(fill=tk.X, pady=(12, 0))

        left_foot = ttk.Frame(footer)
        left_foot.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.status_var = tk.StringVar(value="Iniciando…")
        ttk.Label(left_foot, textvariable=self.status_var, style="Muted.TLabel").pack(anchor=tk.W)
        self.now_var = tk.StringVar(value="")
        ttk.Label(left_foot, textvariable=self.now_var, style="Now.TLabel").pack(anchor=tk.W)

        self.update_var = tk.StringVar(value="")
        self.update_label = ttk.Label(
            footer,
            textvariable=self.update_var,
            style="Update.TLabel",
            cursor="hand2",
        )
        self.update_label.pack(side=tk.RIGHT, padx=(12, 0))
        self.update_label.bind("<Button-1>", lambda _e: self._open_update())

        ttk.Label(
            footer,
            text="Enter ver · Esc parar · F favorito · F11 pantalla · PgUp/PgDn zap · Ctrl+, ajustes",
            style="Muted.TLabel",
        ).pack(side=tk.RIGHT)

    def _bind_keys(self) -> None:
        self.bind("<Return>", lambda _e: self._play_selected())
        self.bind("<F5>", lambda _e: self._reload(force=True))
        self.bind("<Escape>", lambda _e: self._stop_playback())
        self.bind("<F11>", lambda _e: self._toggle_fullscreen())
        self.bind("<f>", lambda _e: self._toggle_favorite())
        self.bind("<F>", lambda _e: self._toggle_favorite())
        self.bind("<Prior>", lambda _e: self._zap(-1))
        self.bind("<Next>", lambda _e: self._zap(1))
        self.bind("<Control-comma>", lambda _e: self._open_settings())

    # --- bootstrap / prefs ------------------------------------------------------

    def _player_options(self) -> PlayerOptions:
        return PlayerOptions(
            geometry=str(self._prefs.get("geometry_mpv") or "80%"),
            fullscreen=bool(self._prefs.get("start_fullscreen", False)),
        )

    def _persist_prefs(self) -> None:
        self._prefs["group"] = self.ambit_var.get()
        self._prefs["only_stream"] = self.only_playable_var.get()
        self._prefs["only_favorites"] = self.only_fav_var.get()
        self._prefs["favorites"] = sorted(self._favorites)
        if self._current is not None:
            self._prefs["last_channel_id"] = self._current.id
        _save_prefs(self._prefs)

    def _bootstrap(self) -> None:
        try:
            self._player = StreamPlayer(self._player_options())
        except PlayerError as exc:
            messagebox.showerror("Reproductor no encontrado", str(exc))
            self.destroy()
            return
        if self._prefs.get("minimize_to_tray"):
            self._ensure_tray()
        self._reload(force=False)
        if self._prefs.get("check_updates", True):
            threading.Thread(target=self._check_updates_worker, daemon=True).start()

    # --- dialogs ----------------------------------------------------------------

    def _about(self) -> None:
        win = tk.Toplevel(self)
        win.title("Acerca de TV-Win")
        win.configure(bg=self._colors["bg"])
        win.resizable(False, False)
        win.transient(self)
        frame = ttk.Frame(win, padding=22)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="TV-Win", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(frame, text=f"Versión {__version__}", style="Muted.TLabel").pack(
            anchor=tk.W, pady=(4, 10)
        )
        ttk.Label(frame, text=__author__, style="Brand.TLabel").pack(anchor=tk.W)
        ttk.Label(
            frame,
            text=(
                "Visor de TDT en abierto para Windows.\n"
                "Sin navegador, sin cookies de webs de terceros\n"
                "y sin publicidad de aplicaciones.\n\n"
                "Catálogo: TDT Spain (fuentes de cada cadena).\n"
                "Reproductor: motor mpv embebido.\n"
                "Licencia: MIT."
            ),
            style="Muted.TLabel",
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(12, 12))

        link = ttk.Label(frame, text=__url__, style="Brand.TLabel", cursor="hand2")
        link.pack(anchor=tk.W)
        link.bind("<Button-1>", lambda _e: webbrowser.open(__url__))

        ttk.Button(frame, text="Cerrar", command=win.destroy).pack(anchor=tk.E, pady=(18, 0))
        win.grab_set()

    def _open_settings(self) -> None:
        win = tk.Toplevel(self)
        win.title("Ajustes — TV-Win")
        win.configure(bg=self._colors["bg"])
        win.resizable(False, False)
        win.transient(self)
        frame = ttk.Frame(win, padding=22)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Ajustes", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(
            frame,
            text="Preferencias de reproducción y de la aplicación",
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(2, 14))

        geo_var = tk.StringVar(value=str(self._prefs.get("geometry_mpv") or "80%"))
        fs_var = tk.BooleanVar(value=bool(self._prefs.get("start_fullscreen", False)))
        tray_var = tk.BooleanVar(value=bool(self._prefs.get("minimize_to_tray", False)))
        upd_var = tk.BooleanVar(value=bool(self._prefs.get("check_updates", True)))

        row = ttk.Frame(frame)
        row.pack(fill=tk.X, pady=4)
        ttk.Label(row, text="Tamaño ventana mpv").pack(side=tk.LEFT)
        geo = ttk.Combobox(
            row,
            textvariable=geo_var,
            values=["50%", "65%", "80%", "90%", "100%"],
            width=10,
        )
        geo.pack(side=tk.RIGHT)

        ttk.Checkbutton(
            frame, text="Iniciar reproducción a pantalla completa", variable=fs_var
        ).pack(anchor=tk.W, pady=6)
        ttk.Checkbutton(
            frame, text="Cerrar minimiza a la bandeja del sistema", variable=tray_var
        ).pack(anchor=tk.W, pady=4)
        ttk.Checkbutton(
            frame, text="Comprobar nuevas versiones en GitHub", variable=upd_var
        ).pack(anchor=tk.W, pady=4)

        def save() -> None:
            self._prefs["geometry_mpv"] = geo_var.get().strip() or "80%"
            self._prefs["start_fullscreen"] = fs_var.get()
            self._prefs["minimize_to_tray"] = tray_var.get()
            self._prefs["check_updates"] = upd_var.get()
            _save_prefs(self._prefs)
            if self._player is not None:
                self._player.options.geometry = str(self._prefs["geometry_mpv"])
                self._player.options.fullscreen = bool(self._prefs["start_fullscreen"])
            if tray_var.get():
                self._ensure_tray()
            elif self._tray_icon is not None:
                self._stop_tray()
            win.destroy()

        actions = ttk.Frame(frame)
        actions.pack(fill=tk.X, pady=(18, 0))
        ttk.Button(actions, text="Cancelar", command=win.destroy).pack(side=tk.RIGHT)
        ttk.Button(actions, text="Guardar", style="Accent.TButton", command=save).pack(
            side=tk.RIGHT, padx=(0, 8)
        )
        win.grab_set()

    # --- list / filters ---------------------------------------------------------

    def _on_filter_change(self) -> None:
        self._persist_prefs()
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
        playable = sum(1 for c in self._channels if c.playable)
        backend = self._player.backend_name if self._player else "?"
        self.status_var.set(
            f"{len(self._visible)} canales · {playable} disponibles · motor {backend}"
        )

    def _apply_filters(self) -> None:
        query = self.search_var.get().strip().lower()
        ambit = self.ambit_var.get()
        only = self.only_playable_var.get()
        only_fav = self.only_fav_var.get()
        visible: list[Channel] = []
        for channel in self._channels:
            if only_fav and channel.id not in self._favorites:
                continue
            if only and not (channel.is_direct_stream or channel.via_streamlink):
                continue
            if ambit != "Todos" and channel.ambit != ambit:
                continue
            haystack = f"{channel.name} {channel.ambit}".lower()
            if query and query not in haystack:
                continue
            visible.append(channel)
        self._visible = visible
        self._render_list()

    def _fav_mark(self, channel: Channel) -> str:
        return "★" if channel.id in self._favorites else "☆"

    def _render_list(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._logo_imgs.clear()
        placeholder = self._logos.placeholder(self)
        for index, channel in enumerate(self._visible):
            photo = self._logos.get(channel.logo, self) or placeholder
            self._logo_imgs[str(index)] = photo
            self.tree.insert(
                "",
                tk.END,
                iid=str(index),
                text=f"  {channel.label}",
                image=photo,
                values=(self._fav_mark(channel), channel.ambit, channel.format.upper()),
            )
            if channel.logo:
                self._logos.ensure(channel.logo, lambda url, i=index: self._on_logo_ready(i, url))

    def _on_logo_ready(self, index: int, url: str) -> None:
        def apply() -> None:
            if index >= len(self._visible):
                return
            channel = self._visible[index]
            if channel.logo != url:
                return
            photo = self._logos.get(url, self)
            if photo is None:
                return
            self._logo_imgs[str(index)] = photo
            try:
                self.tree.item(str(index), image=photo)
            except tk.TclError:
                pass

        self.after(0, apply)

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

    def _on_tree_click(self, event: tk.Event) -> str | None:
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell":
            return None
        col = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if not row:
            return None
        # columna fav = #1
        if col == "#1":
            self.tree.selection_set(row)
            self._toggle_favorite()
            return "break"
        return None

    def _toggle_favorite(self) -> None:
        channel = self._selected_channel()
        if channel is None:
            return
        if channel.id in self._favorites:
            self._favorites.discard(channel.id)
        else:
            self._favorites.add(channel.id)
        self._persist_prefs()
        sel = self.tree.selection()
        self._apply_filters()
        if sel:
            try:
                self.tree.selection_set(sel[0])
            except tk.TclError:
                self._restore_selection()

    # --- playback ---------------------------------------------------------------

    def _stop_playback(self) -> None:
        if self._player is not None:
            self._player.stop()
        self.now_var.set("")
        self.status_var.set("Reproducción detenida")

    def _toggle_fullscreen(self) -> None:
        if self._player is None:
            return
        if not self._player.is_running() and self._current is None:
            self._prefs["start_fullscreen"] = not bool(self._prefs.get("start_fullscreen"))
            if self._player is not None:
                self._player.options.fullscreen = bool(self._prefs["start_fullscreen"])
            self._persist_prefs()
            state = "sí" if self._prefs["start_fullscreen"] else "no"
            self.status_var.set(f"Pantalla completa al reproducir: {state}")
            return
        enabled = self._player.toggle_fullscreen()
        self._prefs["start_fullscreen"] = enabled
        self._persist_prefs()
        self.status_var.set("Pantalla completa" if enabled else "Ventana")

    def _zap(self, delta: int) -> None:
        if not self._visible:
            return
        selection = self.tree.selection()
        if selection:
            try:
                idx = int(selection[0])
            except ValueError:
                idx = 0
        else:
            idx = 0
        n = len(self._visible)
        for step in range(1, n + 1):
            candidate = (idx + delta * step) % n
            channel = self._visible[candidate]
            if channel.playable:
                self.tree.selection_set(str(candidate))
                self.tree.see(str(candidate))
                self._play_selected()
                return

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
            self.status_var.set(f"Resolviendo {channel.name}…")
        elif channel.needs_webview:
            self.status_var.set(f"Conectando {channel.name}…")
        else:
            self.status_var.set(f"Abriendo {channel.name}…")
        self.update_idletasks()

        def worker() -> None:
            error: Exception | None = None
            try:
                assert self._player is not None
                self._player.options = self._player_options()
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
        self._persist_prefs()
        self.now_var.set(f"En directo · {channel.name}")
        self.status_var.set("Reproduciendo")

    # --- updates / tray / close -------------------------------------------------

    def _check_updates_worker(self) -> None:
        result = check_latest()
        if result is None:
            return
        tag, url = result
        self.after(0, lambda: self._show_update(tag, url))

    def _show_update(self, tag: str, url: str) -> None:
        self._update_url = url
        self.update_var.set(f"Nueva versión {tag} · abrir")

    def _open_update(self) -> None:
        if self._update_url:
            webbrowser.open(self._update_url)

    def _ensure_tray(self) -> None:
        if self._tray_icon is not None:
            return
        try:
            import pystray
            from PIL import Image
        except ImportError:
            return

        icon_path = asset_path("tv-win-64.png")
        if not icon_path.is_file():
            icon_path = asset_path("tv-win.png")
        if not icon_path.is_file():
            return
        image = Image.open(icon_path)

        menu = pystray.Menu(
            pystray.MenuItem("Mostrar TV-Win", self._tray_show, default=True),
            pystray.MenuItem("Detener reproducción", self._tray_stop),
            pystray.MenuItem("Salir", self._tray_quit),
        )
        self._tray_icon = pystray.Icon("TV-Win", image, "TV-Win", menu)

        def run() -> None:
            assert self._tray_icon is not None
            self._tray_icon.run()

        self._tray_thread = threading.Thread(target=run, daemon=True)
        self._tray_thread.start()

    def _stop_tray(self) -> None:
        icon = self._tray_icon
        self._tray_icon = None
        if icon is not None:
            try:
                icon.stop()
            except Exception:  # noqa: BLE001
                pass

    def _tray_show(self, _icon=None, _item=None) -> None:
        self.after(0, self._restore_from_tray)

    def _restore_from_tray(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def _tray_stop(self, _icon=None, _item=None) -> None:
        self.after(0, self._stop_playback)

    def _tray_quit(self, _icon=None, _item=None) -> None:
        self.after(0, self._quit_app)

    def _quit_app(self) -> None:
        self._quitting = True
        if self._player is not None:
            self._player.stop()
        self._persist_prefs()
        self._stop_tray()
        self.destroy()

    def _on_close(self) -> None:
        if self._quitting:
            return
        if self._prefs.get("minimize_to_tray"):
            self._ensure_tray()
            if self._tray_icon is not None:
                self.withdraw()
                return
        self._quit_app()


def main() -> None:
    try:
        import os

        os.chdir(app_dir())
    except OSError:
        pass
    app = TVWinApp()
    app.mainloop()
