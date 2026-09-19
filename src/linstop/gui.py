from __future__ import annotations

import tkinter as tk
import queue
import re
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from .addressing import parse_connect_target
from .ax25 import Ax25DecodeError, encode_ui_frame, format_ax25_frame, parse_hex_bytes
from .ax25udp import Ax25UdpEndpoint
from .callsigns import infer_german_license_class
from .config import ConfigStore
from .models import LinStopConfig, PortConfig, StationProfile, UserRecord
from .session import LinStopSession
from .storage import UserStore
from .transport import Ax25CommandTransport, Ax25UdpTransport, LoopbackTransport, Transport
from .user_dialog import UserDatabaseDialog
from .variables import TemplateContext, render_template


QSO_COLUMNS = 80
WINSTOP_BLUE = "#000080"
WINSTOP_RED = "#ff0000"
WINSTOP_GRAY = "#808080"
WINSTOP_YELLOW = "#ffff00"
CONNECTED_STATUS_RE = re.compile(r"^\*\*\*\s+(?:re)?connected\s+to\s+(?P<call>\S+)", re.IGNORECASE)


def connected_status_call(text: str) -> str | None:
    match = CONNECTED_STATUS_RE.match(text.strip())
    if match is None:
        return None
    return match.group("call").rstrip(".,;:").upper()


def channel_button_label(number: int, peer_call: str) -> str:
    return f"{number}: {peer_call}" if peer_call else f"{number}"


def connect_text_lines(text: str) -> list[str]:
    return [line for line in text.replace("\r\n", "\r").replace("\n", "\r").split("\r") if line]


def text_remote_command(text: str) -> str | None:
    command_line = text.strip()
    if not command_line.startswith("//"):
        return None
    command, _, _value = command_line[2:].strip().partition(" ")
    command = command.upper()
    if command in {"I", "INFO"}:
        return "info"
    if command in {"Q", "QUIT", "BYE"}:
        return "quit"
    return None


def remote_echo_key(text: str) -> str | None:
    stripped = text.strip()
    if not stripped.startswith("//"):
        return None
    return " ".join(stripped.upper().split())


def echo_line_key(text: str) -> str:
    return " ".join(text.strip().split())


def line_from_editor_text(text: str, line_number: int) -> str:
    lines = text.split("\n")
    if line_number < 1 or line_number > len(lines):
        return ""
    return lines[line_number - 1].replace("\n", "\r")


def next_editor_line_after_send(text: str, line_number: int) -> tuple[str, int]:
    lines = text.split("\n")
    if line_number < len(lines):
        return text, line_number + 1
    if text:
        return text + "\n", line_number + 1
    return "", 1


class LinStopWindow(tk.Tk):
    def __init__(self, station: StationProfile, store: UserStore, transport_name: str, port: str, endpoint: Ax25UdpEndpoint | None = None, config: LinStopConfig | None = None, config_store: ConfigStore | None = None) -> None:
        super().__init__()
        self.title(f"LinSTOP - {station.normalized_call()}")
        self.geometry("1180x760")
        self.minsize(900, 560)

        self.station = station
        self.store = store
        self.transport_name = transport_name
        self.default_port = port
        self.endpoint = endpoint or Ax25UdpEndpoint()
        self.config_model = config or LinStopConfig(station=station)
        self.config_store = config_store
        self.session = LinStopSession(station, self._make_transport(port))
        self.monitor_process: subprocess.Popen[str] | None = None
        self.monitor_queue: queue.Queue[str] = queue.Queue()
        self.transport_poll_after_id: str | None = None
        self.transport_channel: int | None = None
        self.transport_channels: dict[str, int] = {}
        self.channel_transport_peers: dict[int, str] = {}
        self.sent_remote_echoes: list[str] = []
        self.sent_text_echoes: list[str] = []
        self.closing = False

        self._build_theme()
        self._build_menu()
        self._build_toolbar()
        self._build_status_panels()
        self._build_body()
        self._build_statusbar()
        self._refresh_users()
        self._set_status("Bereit")
        self._start_passive_transport_poll()

    def _build_theme(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Toolbar.TFrame", background="#ece9d8")
        style.configure("Channel.TButton", padding=(8, 4))
        style.configure("Active.Channel.TButton", padding=(8, 4), background="#c7d8ff")

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        connection = tk.Menu(menubar, tearoff=False)
        connection.add_command(label="Verbinden...", accelerator="Ctrl+N", command=self._focus_connect)
        connection.add_command(label="Trennen", accelerator="Ctrl+D", command=self._disconnect)
        connection.add_separator()
        connection.add_command(label="Beenden", command=self.destroy)
        menubar.add_cascade(label="Verbindung", menu=connection)

        view = tk.Menu(menubar, tearoff=False)
        view.add_command(label="Monitor leeren", command=lambda: self.monitor_text.delete("1.0", tk.END))
        view.add_command(label="Info leeren", command=lambda: self.info_text.delete("1.0", tk.END))
        menubar.add_cascade(label="Ansicht", menu=view)

        tools = tk.Menu(menubar, tearoff=False)
        tools.add_command(label="AX.25-Monitor starten", command=self._start_live_monitor)
        tools.add_command(label="AX.25-Monitor stoppen", command=self._stop_live_monitor)
        tools.add_separator()
        tools.add_command(label="MHeard aktualisieren", command=self._refresh_mheard)
        tools.add_command(label="AX.25-Hexframe formatieren...", command=self._format_hex_frame_dialog)
        tools.add_command(label="AX.25-Beispielframe anzeigen", command=self._show_sample_ax25_frame)
        tools.add_separator()
        tools.add_command(label="User-Datenbank...", command=self._open_user_database)
        tools.add_command(label="Einstellungen...", command=self._open_settings)
        tools.add_command(label="Userdaten speichern", command=self.store.save)
        menubar.add_cascade(label="Tools", menu=tools)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="Über LinSTOP", command=self._about)
        menubar.add_cascade(label="Hilfe", menu=help_menu)
        self.config(menu=menubar)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Control-n>", lambda _event: self._focus_connect())
        self.bind("<Control-d>", lambda _event: self._disconnect())

    def _build_toolbar(self) -> None:
        toolbar = ttk.Frame(self, style="Toolbar.TFrame", padding=(4, 3))
        toolbar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(toolbar, text="Verbinden", command=self._connect_from_toolbar).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(toolbar, text="Trennen", command=self._disconnect).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(toolbar, text="MHeard", command=self._refresh_mheard).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(toolbar, text="Ziel:").pack(side=tk.LEFT)
        self.connect_entry = ttk.Entry(toolbar, width=26)
        self.connect_entry.pack(side=tk.LEFT, padx=(4, 10))
        self.connect_entry.insert(0, self.config_model.get_active_port().default_target if self.transport_name == "ax25udp" else "P3:DBW400")
        ttk.Label(toolbar, text=f"Port {self.default_port} | {self.transport_name}").pack(side=tk.RIGHT)

    def _build_status_panels(self) -> None:
        banner = tk.Frame(self, background=WINSTOP_RED, height=106, relief=tk.SUNKEN, borderwidth=1)
        banner.pack(side=tk.TOP, fill=tk.X)
        banner.pack_propagate(False)
        self._build_input(banner)

        panels = tk.Frame(self, background=WINSTOP_BLUE, height=66, relief=tk.SUNKEN, borderwidth=1)
        panels.pack(side=tk.TOP, fill=tk.X)
        panels.pack_propagate(False)

        self.channel_status_var = tk.StringVar(value="Kanal 1")
        self._build_channels(panels)

    def _build_body(self) -> None:
        outer = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True)

        main = tk.Frame(outer, background=WINSTOP_GRAY)
        outer.add(main, weight=4)
        work_area = tk.Frame(main, background=WINSTOP_GRAY, relief=tk.SUNKEN, borderwidth=1)
        work_area.pack(fill=tk.BOTH, expand=True)

        bottom_pane = ttk.PanedWindow(main, orient=tk.VERTICAL)
        bottom_pane.pack(side=tk.BOTTOM, fill=tk.BOTH)

        qso_frame = ttk.Frame(bottom_pane, padding=2)
        bottom_pane.add(qso_frame, weight=3)
        self.qso_text = tk.Text(qso_frame, wrap=tk.NONE, undo=False, width=QSO_COLUMNS, font="TkFixedFont")
        self.qso_text.pack(fill=tk.BOTH, expand=True)
        self.qso_text.tag_configure("tx", foreground="#b00000")
        self.qso_text.tag_configure("rx", foreground="#000080")
        self.qso_text.tag_configure("info", foreground="#006000")
        self.qso_text.tag_configure("time", foreground="#666666")
        self.qso_text.configure(state=tk.DISABLED)

        right = ttk.PanedWindow(outer, orient=tk.VERTICAL)
        outer.add(right, weight=2)

        mheard_frame = self._side_panel(right, "MHeard-Liste")
        self.user_list = tk.Listbox(mheard_frame, exportselection=False, font="TkFixedFont")
        self.user_list.pack(fill=tk.BOTH, expand=True)
        self.user_list.bind("<Double-Button-1>", lambda _event: self._open_selected_user())

        info_frame = self._side_panel(right, "Info-Fenster")
        self.info_text = tk.Text(info_frame, height=7, wrap=tk.WORD, font="TkFixedFont")
        self.info_text.pack(fill=tk.BOTH, expand=True)

        port_frame = self._side_panel(right, "Portinfo")
        self.portinfo_text = tk.Text(port_frame, height=4, wrap=tk.NONE, font="TkFixedFont")
        self.portinfo_text.pack(fill=tk.BOTH, expand=True)
        self.portinfo_text.insert(tk.END, "Port  freie Puffer  Kanäle gesamt  belegt\n")
        self.portinfo_text.insert(tk.END, f"{self.default_port:<5} -             10             0\n")
        self.portinfo_text.configure(state=tk.DISABLED)

        win_frame = self._side_panel(right, "Fensterliste")
        self.window_list = tk.Listbox(win_frame, height=4, exportselection=False, font="TkFixedFont")
        self.window_list.pack(fill=tk.BOTH, expand=True)
        for item in ("MHeard-Liste     INFO", "Info-Box         INFO", "Portinfo         INFO", "Monitor          MON"):
            self.window_list.insert(tk.END, item)

        monitor_frame = ttk.Frame(bottom_pane, padding=2)
        bottom_pane.add(monitor_frame, weight=1)
        self.monitor_text = tk.Text(monitor_frame, height=8, wrap=tk.NONE, width=QSO_COLUMNS, font="TkFixedFont")
        self.monitor_text.pack(fill=tk.BOTH, expand=True)

    def _side_panel(self, parent: ttk.PanedWindow, title: str) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=2)
        parent.add(frame, weight=1)
        ttk.Label(frame, text=title).pack(anchor=tk.W)
        return frame

    def _build_bottom_controls(self) -> None:
        bottom = ttk.Frame(self, padding=(4, 3))
        bottom.pack(side=tk.BOTTOM, fill=tk.X, before=None)
        self._build_channels(bottom)
        self._build_input(bottom)

    def _build_channels(self, parent: ttk.Frame) -> None:
        frame = tk.Frame(parent, background=WINSTOP_BLUE)
        frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.channel_buttons: dict[int, tk.Label] = {}
        self.channel_button_vars: dict[int, tk.StringVar] = {}
        for number in range(1, 11):
            frame.columnconfigure(number - 1, weight=1, uniform="channels")
            text_var = tk.StringVar(value=str(number))
            button = tk.Label(
                frame,
                textvariable=text_var,
                width=1,
                height=1,
                padx=8,
                pady=3,
                anchor=tk.CENTER,
                font="TkFixedFont",
                foreground="black",
                background="#ece9d8",
                relief=tk.RAISED,
                borderwidth=2,
                highlightthickness=1,
                highlightbackground="#404040",
            )
            button.bind("<Button-1>", lambda _event, item=number: self._switch_channel(item))
            button.grid(row=0, column=number - 1, sticky="nsew", padx=3, pady=0)
            self.channel_buttons[number] = button
            self.channel_button_vars[number] = text_var
        self._refresh_channel_buttons()

    def _build_input(self, parent: ttk.Frame) -> None:
        self.input_entry = tk.Text(
            parent,
            wrap=tk.WORD,
            font="TkFixedFont",
            undo=True,
            background=WINSTOP_RED,
            foreground="white",
            insertbackground="white",
            selectbackground=WINSTOP_BLUE,
            selectforeground="white",
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
            padx=6,
            pady=4,
        )
        self.input_entry.pack(fill=tk.BOTH, expand=True)
        self.input_entry.bind("<Return>", self._send_input_event)
        self.input_entry.bind("<KP_Enter>", self._send_input_event)
        self.input_entry.bind("<Control-Return>", self._insert_input_cr)

    def _build_statusbar(self) -> None:
        self.status_var = tk.StringVar()
        status = ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=(4, 2))
        status.pack(side=tk.BOTTOM, fill=tk.X)

    def _make_transport(self, port: str) -> Transport:
        if self.transport_name == "ax25":
            return Ax25CommandTransport(port=port, local_call=self.station.normalized_call())
        if self.transport_name == "ax25udp":
            return Ax25UdpTransport(local_call=self.station.normalized_call(), endpoint=self.endpoint)
        return LoopbackTransport()

    def _focus_connect(self) -> None:
        self.connect_entry.focus_set()
        self.connect_entry.selection_range(0, tk.END)

    def _connect_from_toolbar(self) -> None:
        try:
            target = parse_connect_target(self.connect_entry.get().strip())
            port = target.port or self.default_port
            if self.transport_name in {"ax25", "ax25udp"}:
                self.session.transport = self._make_transport(port)
                self.transport_channels.clear()
                self.channel_transport_peers.clear()
            user = self.store.note_connect(target.call, datetime.now())
            self.session.connect(target.call, user=user, via=list(target.via))
            self.store.save()
        except Exception as exc:
            self._set_status(str(exc))
            messagebox.showerror("LinSTOP", str(exc))
            return
        self._append_info(f"Verbunden mit {target.call} auf {port}")
        self._refresh_mheard()
        self._refresh_users()
        self._refresh_channel_buttons()
        self.channel_status_var.set(f"Kanal {self.session.current_channel}")
        self._set_status(f"Kanal {self.session.current_channel}: verbunden mit {target.call}")
        self.transport_channel = self.session.current_channel
        self.transport_channels[target.call.upper()] = self.session.current_channel
        self.channel_transport_peers[self.session.current_channel] = target.call.upper()
        self._schedule_transport_poll(0)

    def _disconnect(self) -> None:
        self._cancel_transport_poll()
        try:
            selector = getattr(self.session.transport, "select_peer", None)
            physical_peer = self._transport_peer_for_channel(self.session.current_channel)
            if selector is not None and physical_peer:
                selector(physical_peer)
            self.session.disconnect()
        except Exception as exc:
            self._append_info(str(exc))
        self._append_info("Verbindung getrennt")
        if self.transport_channel is not None:
            physical_peer = self.channel_transport_peers.pop(self.transport_channel, "")
            if physical_peer:
                self.transport_channels.pop(physical_peer, None)
        self.transport_channel = None
        self._refresh_channel_buttons()
        self._set_status("Getrennt")
        self._start_passive_transport_poll()

    def _switch_channel(self, number: int) -> None:
        self._save_current_input_buffer()
        self.session.switch_channel(number)
        self._load_current_input_buffer()
        self._redraw_qso()
        self._refresh_channel_buttons()
        suffix = f": {self.session.channel.peer_call}" if self.session.channel.peer_call else ""
        self.channel_status_var.set(f"Kanal {number}")
        self._set_status(f"Kanal {number}{suffix}")

    def _send_input(self) -> bool:
        self._save_current_input_buffer()
        line_number = self._current_input_line_number()
        text = self._input_line_text(line_number)
        if not text:
            return False
        user = self.store.get(self.session.channel.peer_call) if self.session.channel.peer_call else UserRecord(call="")
        try:
            selector = getattr(self.session.transport, "select_peer", None)
            physical_peer = self._transport_peer_for_channel(self.session.current_channel)
            if selector is not None and physical_peer:
                selector(physical_peer)
                self.transport_channel = self.session.current_channel
                self.transport_channels[physical_peer] = self.session.current_channel
            rendered = self.session.send_template(text, user=user)
        except Exception as exc:
            self._set_status(str(exc))
            return False
        self._remember_sent_remote_echo(physical_peer, rendered)
        self._append_qso("tx", rendered)
        peer_call = self.session.channel.peer_call or "CQ"
        if self.transport_name == "loopback":
            frame = encode_ui_frame(self.station.normalized_call(), peer_call, rendered.encode("latin-1", errors="replace"))
            self._append_monitor(format_ax25_frame(frame, port=self.default_port, direction="TX"))
        self._schedule_transport_poll(0)
        self._set_status("Gesendet")
        return True

    def _send_input_event(self, _event: tk.Event) -> str:
        line_number = self._current_input_line_number()
        if self._send_input():
            self._advance_input_after_send(line_number)
        return "break"

    def _insert_input_cr(self, _event: tk.Event) -> str:
        self.input_entry.insert(tk.INSERT, "\n")
        self._save_current_input_buffer()
        return "break"

    def _input_text(self) -> str:
        return self.input_entry.get("1.0", "end-1c").replace("\n", "\r")

    def _editor_text(self) -> str:
        return self.input_entry.get("1.0", "end-1c")

    def _save_current_input_buffer(self) -> None:
        if hasattr(self, "input_entry"):
            self.session.channel.input_text = self._editor_text()

    def _load_current_input_buffer(self) -> None:
        self.input_entry.delete("1.0", tk.END)
        if self.session.channel.input_text:
            self.input_entry.insert("1.0", self.session.channel.input_text)

    def _current_input_line_number(self) -> int:
        return int(self.input_entry.index(tk.INSERT).split(".", 1)[0])

    def _input_line_text(self, line_number: int) -> str:
        return self.input_entry.get(f"{line_number}.0", f"{line_number}.end").replace("\n", "\r")

    def _set_input_text(self, text: str) -> None:
        self.input_entry.delete("1.0", tk.END)
        self.input_entry.insert("1.0", text.replace("\r", "\n"))

    def _advance_input_after_send(self, line_number: int) -> None:
        new_text, new_line_number = next_editor_line_after_send(self._editor_text(), line_number)
        if new_text != self._editor_text():
            self.input_entry.delete("1.0", tk.END)
            self.input_entry.insert("1.0", new_text)
        self.input_entry.mark_set(tk.INSERT, f"{new_line_number}.0")
        self.input_entry.see(tk.INSERT)
        self._save_current_input_buffer()

    def _append_qso(self, direction: str, text: str) -> None:
        self.qso_text.configure(state=tk.NORMAL)
        tag = direction.lower()
        if tag not in {"tx", "rx", "info"}:
            tag = "info"
        self.qso_text.insert(tk.END, f"[{datetime.now():%H:%M:%S}] ", "time")
        self.qso_text.insert(tk.END, f"{direction.upper():4} ", tag)
        self.qso_text.insert(tk.END, f"{text}\n", tag)
        self.qso_text.see(tk.END)
        self.qso_text.configure(state=tk.DISABLED)

    def _redraw_qso(self) -> None:
        self.qso_text.configure(state=tk.NORMAL)
        self.qso_text.delete("1.0", tk.END)
        for event in self.session.channel.events:
            self.qso_text.insert(tk.END, f"[{event.at:%H:%M:%S}] {event.direction.upper():4} {event.text}\n")
        self.qso_text.configure(state=tk.DISABLED)

    def _append_monitor(self, text: str) -> None:
        self.monitor_text.insert(tk.END, f"[{datetime.now():%H:%M:%S}] {text}\n")
        self.monitor_text.see(tk.END)

    def _start_live_monitor(self) -> None:
        if self.monitor_process is not None:
            self._set_status("AX.25-Monitor läuft bereits")
            return
        executable = shutil.which("listen")
        if executable is None:
            messagebox.showerror("LinSTOP", "listen nicht gefunden; installiere ax25-apps")
            return
        command = [executable, "-a", "-h", "-r", "-p", self.default_port]
        try:
            self.monitor_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as exc:
            messagebox.showerror("LinSTOP", str(exc))
            return
        threading.Thread(target=self._read_live_monitor, daemon=True).start()
        self.after(100, self._drain_monitor_queue)
        self._append_info("AX.25-Livemonitor gestartet: " + " ".join(command))
        self._set_status("AX.25-Monitor läuft")

    def _stop_live_monitor(self) -> None:
        if self.monitor_process is None:
            return
        self.monitor_process.terminate()
        self.monitor_process = None
        self._append_info("AX.25-Livemonitor gestoppt")
        self._set_status("AX.25-Monitor gestoppt")

    def _read_live_monitor(self) -> None:
        process = self.monitor_process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            self.monitor_queue.put(line.rstrip("\n"))
        self.monitor_queue.put("AX.25-Livemonitor beendet")

    def _drain_monitor_queue(self) -> None:
        while True:
            try:
                line = self.monitor_queue.get_nowait()
            except queue.Empty:
                break
            self._append_monitor(line)
        if self.monitor_process is not None and self.monitor_process.poll() is None:
            self.after(100, self._drain_monitor_queue)
        elif self.monitor_process is not None:
            self.monitor_process = None

    def append_ax25_frame(self, data: bytes, port: str | None = None, direction: str | None = None) -> None:
        try:
            text = format_ax25_frame(data, port=port, direction=direction)
        except Ax25DecodeError as exc:
            text = f"AX.25 decode error: {exc}"
        self._append_monitor(text)

    def _format_hex_frame_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("AX.25-Hexframe")
        dialog.geometry("620x220")
        ttk.Label(dialog, text="AX.25-Frame ohne HDLC-Flags/FCS als Hexbytes:").pack(anchor=tk.W, padx=8, pady=(8, 2))
        text = tk.Text(dialog, height=6, wrap=tk.WORD)
        text.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        def decode() -> None:
            try:
                self.append_ax25_frame(parse_hex_bytes(text.get("1.0", tk.END)), port=self.default_port, direction="RX")
            except Ax25DecodeError as exc:
                messagebox.showerror("AX.25", str(exc), parent=dialog)
                return
            dialog.destroy()

        ttk.Button(dialog, text="Formatieren", command=decode).pack(anchor=tk.E, padx=8, pady=(0, 8))

    def _show_sample_ax25_frame(self) -> None:
        payload = b"The quick brown fox jumps over the lazy dog"
        frame = encode_ui_frame("N7LEM", "NJ7P", payload)
        self.append_ax25_frame(frame, port="demo", direction="RX")

    def _append_info(self, text: str) -> None:
        self.session.add_info(text)
        self.info_text.insert(tk.END, f"[{datetime.now():%H:%M:%S}] {text}\n")
        self.info_text.see(tk.END)

    def _refresh_users(self) -> None:
        self.user_list.delete(0, tk.END)
        for user in sorted(self.store.all(), key=lambda item: item.call.upper()):
            self.user_list.insert(tk.END, f"{user.call:12} {user.display_name()}")

    def _refresh_mheard(self) -> None:
        self.monitor_text.insert(tk.END, "--- MHeard ---\n")
        for call, at in sorted(self.session.mheard.items()):
            self.monitor_text.insert(tk.END, f"{call:12} {at:%Y-%m-%d %H:%M:%S}\n")
        self.monitor_text.see(tk.END)

    def _refresh_channel_buttons(self) -> None:
        for number, button in self.channel_buttons.items():
            channel = self.session.channels[number]
            self.channel_button_vars[number].set(channel_button_label(number, channel.peer_call))
            if number == self.session.current_channel:
                button.configure(background="#c7d8ff", relief=tk.SUNKEN, highlightbackground="#ffffff")
            else:
                button.configure(background="#ece9d8", relief=tk.RAISED, highlightbackground="#404040")

    def _set_status(self, text: str) -> None:
        self.status_var.set(f"{datetime.now():%H:%M:%S}  {text}")

    def _poll_transport_monitor(self) -> None:
        self.transport_poll_after_id = None
        if self.closing:
            return
        receiver = getattr(self.session.transport, "receive_monitor_lines", None)
        try:
            if receiver is not None:
                for line in receiver():
                    self._append_monitor(line)
            connected_receiver = getattr(self.session.transport, "receive_connected_peers", None)
            connected_peers = connected_receiver() if connected_receiver is not None else ()
            for peer_call in connected_peers:
                self._assign_incoming_peer(peer_call)
            peer_call = getattr(self.session.transport, "peer_call", "")
            if peer_call and getattr(self.session.transport, "link_established", False) and self._channel_for_peer(peer_call) is None:
                self._assign_incoming_peer(peer_call)
            qso_receiver = getattr(self.session.transport, "receive_qso_lines", None)
            event_receiver = getattr(self.session.transport, "receive_qso_events", None)
            if event_receiver is not None:
                for peer_call, line in event_receiver():
                    self._route_qso_line(peer_call, line)
            elif qso_receiver is not None:
                for line in qso_receiver():
                    peer_call = getattr(self.session.transport, "peer_call", "")
                    self._route_qso_line(peer_call, line)
        except Exception as exc:
            self._append_info(f"Monitorfehler: {exc}")
            self._set_status(f"Monitorfehler: {exc}")
            self.transport_poll_after_id = None
            return
        disconnected_receiver = getattr(self.session.transport, "receive_disconnected_peers", None)
        if disconnected_receiver is not None:
            for peer_call in disconnected_receiver():
                self._disconnect_peer_channel(peer_call)
        elif getattr(self.session.transport, "remote_disconnected", False):
            setattr(self.session.transport, "remote_disconnected", False)
            peer_call = getattr(self.session.transport, "peer_call", "")
            self._disconnect_peer_channel(peer_call)
        if self.session.channel.connected or getattr(self.session.transport, "listening", False):
            self._schedule_transport_poll(500)
        else:
            self.transport_poll_after_id = None

    def _schedule_transport_poll(self, delay_ms: int) -> None:
        if self.closing or self.transport_poll_after_id is not None:
            return
        self.transport_poll_after_id = self.after(delay_ms, self._poll_transport_monitor)

    def _cancel_transport_poll(self) -> None:
        if self.transport_poll_after_id is None:
            return
        try:
            self.after_cancel(self.transport_poll_after_id)
        except tk.TclError:
            pass
        self.transport_poll_after_id = None

    def _about(self) -> None:
        messagebox.showinfo("Über LinSTOP", "LinSTOP 0.1 - Linux AX.25 Packet-Radio Terminal")

    def _open_settings(self) -> None:
        SettingsDialog(self, self.config_model, self.config_store)

    def _open_selected_user(self) -> None:
        selection = self.user_list.curselection()
        if not selection:
            return
        line = self.user_list.get(selection[0])
        self._open_user_database(line.split()[0])

    def _open_user_database(self, call: str | None = None) -> None:
        UserDatabaseDialog(self, self.store, call)

    def _channel_for_peer(self, peer_call: str) -> int | None:
        normalized = peer_call.upper()
        mapped = self.transport_channels.get(normalized)
        if mapped is not None:
            return mapped
        for channel_number, physical_peer in self.channel_transport_peers.items():
            if physical_peer == normalized:
                return channel_number
        for number, channel in self.session.channels.items():
            if channel.connected and channel.peer_call == normalized:
                return number
        return None

    def _transport_peer_for_channel(self, channel_number: int) -> str:
        physical_peer = self.channel_transport_peers.get(channel_number)
        if physical_peer:
            return physical_peer
        return self.session.channels[channel_number].peer_call

    def _assign_incoming_peer(self, peer_call: str) -> int:
        normalized = peer_call.upper()
        existing = self._channel_for_peer(normalized)
        if existing is not None:
            return existing
        self._save_current_input_buffer()
        user = self.store.note_connect(normalized, datetime.now())
        channel = self.session.connect_incoming(normalized, datetime.now())
        self._load_current_input_buffer()
        self.transport_channels[normalized] = channel.number
        self.channel_transport_peers[channel.number] = normalized
        self.transport_channel = channel.number
        self._redraw_qso()
        self._append_info(f"Eingehende Verbindung von {user.call}")
        self._refresh_users()
        self._refresh_channel_buttons()
        self.channel_status_var.set(f"Kanal {channel.number}")
        self._set_status(f"Kanal {channel.number}: eingehende Verbindung von {user.call}")
        self._send_incoming_connect_text(channel.number, normalized)
        return channel.number

    def _send_incoming_connect_text(self, channel_number: int, physical_peer: str) -> None:
        template = self.config_model.connect_text.strip()
        if not template:
            return
        self._send_text_template(channel_number, physical_peer, template)

    def _send_text_template(self, channel_number: int, physical_peer: str, template: str) -> None:
        channel = self.session.channels[channel_number]
        user = self.store.get(channel.peer_call or physical_peer)
        rendered = render_template(template, TemplateContext(station=self.station, channel=channel, user=user))
        selector = getattr(self.session.transport, "select_peer", None)
        if selector is not None:
            selector(physical_peer)
        for line in connect_text_lines(rendered):
            self.session.transport.send_line(line)
            self._remember_sent_text_echo(physical_peer, line)
            channel.append_tx(line)
            if channel_number == self.session.current_channel:
                self._append_qso("tx", line)

    def _route_qso_line(self, peer_call: str, line: str) -> None:
        if not peer_call:
            self.session.channel.append_rx(line)
            self._append_qso("rx", line)
            return
        channel_number = self._channel_for_peer(peer_call) or self._assign_incoming_peer(peer_call)
        channel = self.session.channels[channel_number]
        physical_peer = peer_call.upper()
        self.session.mheard[physical_peer] = datetime.now()
        if self._consume_sent_text_echo(physical_peer, line):
            return
        selector = getattr(self.session.transport, "select_peer", None)
        if selector is not None:
            selector(physical_peer)
        previous_channel = self.session.current_channel
        self.session.switch_channel(channel_number)
        if self._consume_sent_remote_echo(physical_peer, line):
            self.session.switch_channel(previous_channel)
            return
        handled_text_command = self._handle_text_remote_command(channel_number, physical_peer, line)
        if handled_text_command:
            self.session.switch_channel(previous_channel)
            return
        response = self.session.handle_remote_user_command(line, self.store.get(channel.peer_call or physical_peer))
        if response is not None:
            self.session.switch_channel(previous_channel)
            if channel_number == self.session.current_channel:
                self._append_qso("tx", response)
            self.store.save()
            self._refresh_users()
            return
        self.session.switch_channel(previous_channel)
        channel.append_rx(line)
        logical_peer = connected_status_call(line)
        if logical_peer and logical_peer != channel.peer_call:
            channel.peer_call = logical_peer
            self._refresh_channel_buttons()
            if channel_number == self.session.current_channel:
                self.channel_status_var.set(f"Kanal {channel_number}")
        if channel_number == self.session.current_channel:
            self._append_qso("rx", line)

    def _handle_text_remote_command(self, channel_number: int, physical_peer: str, line: str) -> bool:
        command = text_remote_command(line)
        if command is None:
            return False
        template = self.config_model.info_text if command == "info" else self.config_model.quit_text
        if template.strip():
            self._send_text_template(channel_number, physical_peer, template.strip())
        if command == "quit":
            selector = getattr(self.session.transport, "select_peer", None)
            if selector is not None:
                selector(physical_peer)
            self.session.transport.disconnect()
            self._disconnect_peer_channel(physical_peer)
        return True

    def _remember_sent_remote_echo(self, physical_peer: str, text: str) -> None:
        for line in connect_text_lines(text):
            key = remote_echo_key(line)
            if key is not None:
                self.sent_remote_echoes.append(key)

    def _remember_sent_text_echo(self, physical_peer: str, text: str) -> None:
        key = echo_line_key(text)
        if key:
            self.sent_text_echoes.append(key)

    def _consume_sent_text_echo(self, physical_peer: str, text: str) -> bool:
        key = echo_line_key(text)
        if not key or key not in self.sent_text_echoes:
            return False
        self.sent_text_echoes.remove(key)
        return True

    def _consume_sent_remote_echo(self, physical_peer: str, text: str) -> bool:
        key = remote_echo_key(text)
        if key is None:
            return False
        if key not in self.sent_remote_echoes:
            return False
        self.sent_remote_echoes.remove(key)
        return True

    def _disconnect_peer_channel(self, peer_call: str) -> None:
        if not peer_call:
            return
        normalized = peer_call.upper()
        channel_number = self.transport_channels.pop(normalized, None) or self._channel_for_peer(normalized)
        if channel_number is None:
            return
        self.channel_transport_peers.pop(channel_number, None)
        was_current = channel_number == self.session.current_channel
        previous_channel = self.session.current_channel
        self.session.switch_channel(channel_number)
        self.session.channel.disconnect()
        if was_current:
            self._redraw_qso()
        else:
            self.session.switch_channel(previous_channel)
        self.transport_channel = None if self.transport_channel == channel_number else self.transport_channel
        self._append_info(f"Gegenstation {normalized} hat getrennt")
        self._refresh_channel_buttons()
        self._set_status(f"Kanal {channel_number}: getrennt durch {normalized}")

    def _start_passive_transport_poll(self) -> None:
        listener = getattr(self.session.transport, "ensure_listening", None)
        if listener is None:
            return
        try:
            listener()
        except Exception as exc:
            self._append_info(f"AX25UDP-Lauschen nicht aktiv: {exc}")
            return
        self._schedule_transport_poll(500)

    def _close(self) -> None:
        self.closing = True
        self._cancel_transport_poll()
        try:
            disconnect_all = getattr(self.session.transport, "disconnect_all", None)
            if disconnect_all is not None:
                disconnect_all()
            else:
                self.session.disconnect()
        except Exception:
            pass
        self._stop_live_monitor()
        self.destroy()


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent: LinStopWindow, config: LinStopConfig, store: ConfigStore | None) -> None:
        super().__init__(parent)
        self.title("LinSTOP Einstellungen")
        self.transient(parent)
        self.resizable(False, False)
        self.config_model = config
        self.store = store
        self.station_vars: dict[str, tk.StringVar] = {}
        self.port_vars: dict[str, tk.StringVar] = {}
        self.text_widgets: dict[str, tk.Text] = {}
        self.enabled_var = tk.BooleanVar(value=config.get_active_port().enabled)
        self._build()
        self.grab_set()

    def _build(self) -> None:
        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        station_tab = ttk.Frame(notebook, padding=8)
        text_tab = ttk.Frame(notebook, padding=8)
        port_tab = ttk.Frame(notebook, padding=8)
        notebook.add(station_tab, text="Persoenliche Daten")
        notebook.add(text_tab, text="Texte")
        notebook.add(port_tab, text="Port")

        station_fields = (
            ("call", "Rufzeichen"),
            ("name", "Name"),
            ("qth", "QTH"),
            ("qra", "QRA/Locator"),
            ("locator", "Maidenhead Locator"),
            ("phone", "Telefon"),
            ("email", "E-Mail"),
            ("homepage", "Homepage"),
            ("club", "DOK/Club"),
            ("operator_class", "Lizenzklasse"),
            ("bbs_call", "Home-BBS"),
            ("node_call", "Node-Call"),
            ("convers_call", "Convers-Call"),
            ("user_call_1", "User-Call 1"),
            ("user_call_2", "User-Call 2"),
        )
        for row, (name, label) in enumerate(station_fields):
            ttk.Label(station_tab, text=label).grid(row=row // 2, column=(row % 2) * 2, sticky=tk.W, padx=(0, 4), pady=2)
            var = tk.StringVar(value=str(getattr(self.config_model.station, name)))
            self.station_vars[name] = var
            ttk.Entry(station_tab, textvariable=var, width=28).grid(row=row // 2, column=(row % 2) * 2 + 1, sticky=tk.W, padx=(0, 12), pady=2)
        self.station_vars["call"].trace_add("write", self._update_license_class)

        self._build_text_editor(text_tab, "connect_text", "CText bei eingehender Verbindung", self.config_model.connect_text)
        self._build_text_editor(text_tab, "quit_text", "QText bei //q, danach Disconnect", self.config_model.quit_text)
        self._build_text_editor(text_tab, "info_text", "Info-Text bei //i, Verbindung bleibt", self.config_model.info_text)

        port = self.config_model.get_active_port()
        port_fields = (
            ("name", "Name"),
            ("transport", "Transport"),
            ("description", "Beschreibung"),
            ("default_target", "Standardziel"),
            ("local_call", "Lokales Call"),
            ("ax25_port", "AX.25-Port"),
            ("udp_remote_host", "UDP-Zielhost"),
            ("udp_remote_port", "UDP-Zielport"),
            ("udp_local_port", "UDP-Quellport"),
        )
        for row, (name, label) in enumerate(port_fields):
            ttk.Label(port_tab, text=label).grid(row=row, column=0, sticky=tk.W, padx=(0, 4), pady=2)
            value = getattr(port, name)
            var = tk.StringVar(value="" if value is None else str(value))
            self.port_vars[name] = var
            ttk.Entry(port_tab, textvariable=var, width=42).grid(row=row, column=1, sticky=tk.W, pady=2)
        ttk.Checkbutton(port_tab, text="Aktiv", variable=self.enabled_var).grid(row=len(port_fields), column=1, sticky=tk.W, pady=2)

        buttons = ttk.Frame(self, padding=8)
        buttons.pack(fill=tk.X)
        ttk.Button(buttons, text="Speichern", command=self._save).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(buttons, text="Abbrechen", command=self.destroy).pack(side=tk.RIGHT)

    def _build_text_editor(self, parent: ttk.Frame, name: str, title: str, value: str) -> None:
        frame = ttk.LabelFrame(parent, text=title, padding=8)
        frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        widget = tk.Text(frame, height=5, wrap=tk.WORD, font="TkFixedFont")
        widget.pack(fill=tk.BOTH, expand=True)
        widget.insert("1.0", value)
        self.text_widgets[name] = widget

    def _update_license_class(self, *_args) -> None:
        inferred = infer_german_license_class(self.station_vars["call"].get())
        if inferred:
            self.station_vars["operator_class"].set(inferred)

    def _save(self) -> None:
        for name, var in self.station_vars.items():
            setattr(self.config_model.station, name, var.get().strip())
        for name, widget in self.text_widgets.items():
            setattr(self.config_model, name, widget.get("1.0", tk.END).rstrip("\n"))
        port = self.config_model.get_active_port()
        port.name = self.port_vars["name"].get().strip() or port.name
        port.transport = self.port_vars["transport"].get().strip() or "ax25udp"
        port.description = self.port_vars["description"].get().strip()
        port.default_target = self.port_vars["default_target"].get().strip() or "IGATE"
        port.local_call = self.port_vars["local_call"].get().strip()
        port.ax25_port = self.port_vars["ax25_port"].get().strip() or "P3"
        port.udp_remote_host = self.port_vars["udp_remote_host"].get().strip() or "44.148.230.93"
        port.udp_remote_port = int(self.port_vars["udp_remote_port"].get().strip() or "93")
        local_port = self.port_vars["udp_local_port"].get().strip()
        port.udp_local_port = None if local_port in {"", "0"} else int(local_port)
        port.enabled = self.enabled_var.get()
        self.config_model.active_port = port.name
        if self.store is not None:
            self.store.save(self.config_model)
        self.destroy()


def run_gui(station: StationProfile | str, data_path: Path, transport: str, port: str, endpoint: Ax25UdpEndpoint | None = None, config: LinStopConfig | None = None, config_store: ConfigStore | None = None) -> int:
    store = UserStore(data_path)
    store.load()
    station_profile = StationProfile(call=station.upper()) if isinstance(station, str) else station
    window = LinStopWindow(station_profile, store, transport, port, endpoint, config, config_store)
    window.mainloop()
    store.save()
    return 0