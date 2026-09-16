from __future__ import annotations

import tkinter as tk
import queue
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


QSO_COLUMNS = 80
WINSTOP_BLUE = "#000080"
WINSTOP_RED = "#ff0000"
WINSTOP_GRAY = "#808080"
WINSTOP_YELLOW = "#ffff00"


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
        self.closing = False

        self._build_theme()
        self._build_menu()
        self._build_toolbar()
        self._build_status_panels()
        self._build_body()
        self._build_statusbar()
        self._build_bottom_controls()
        self._refresh_users()
        self._set_status("Bereit")

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
        banner = tk.Frame(self, background=WINSTOP_RED, height=78, relief=tk.SUNKEN, borderwidth=1)
        banner.pack(side=tk.TOP, fill=tk.X)
        banner.pack_propagate(False)

        panels = tk.Frame(self, background=WINSTOP_BLUE, height=44, relief=tk.SUNKEN, borderwidth=1)
        panels.pack(side=tk.TOP, fill=tk.X)
        panels.pack_propagate(False)

        channel = tk.LabelFrame(panels, text="Kanal", foreground=WINSTOP_YELLOW, background=WINSTOP_BLUE, borderwidth=1)
        channel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=2)
        self.channel_status_var = tk.StringVar(value="Kanal 1")
        tk.Label(channel, textvariable=self.channel_status_var, foreground="white", background=WINSTOP_BLUE, anchor=tk.W).pack(side=tk.LEFT, padx=4)
        for label in ("Fernsteuerung", "RX ignorieren", "Sysop"):
            tk.Checkbutton(channel, text=label, foreground="white", background=WINSTOP_BLUE, selectcolor=WINSTOP_BLUE, activebackground=WINSTOP_BLUE).pack(side=tk.LEFT, padx=6)

        general = tk.LabelFrame(panels, text="Allgemein", foreground=WINSTOP_YELLOW, background=WINSTOP_BLUE, borderwidth=1)
        general.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=2)
        self.connect_text_var = tk.StringVar(value="CText: Terminal")
        tk.Label(general, textvariable=self.connect_text_var, foreground="white", background=WINSTOP_BLUE, anchor=tk.W).pack(side=tk.LEFT, padx=4)
        for label in ("Klänge an", "Baken", "Wecker"):
            tk.Checkbutton(general, text=label, foreground="white", background=WINSTOP_BLUE, selectcolor=WINSTOP_BLUE, activebackground=WINSTOP_BLUE).pack(side=tk.LEFT, padx=6)

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
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=(0, 3))
        self.channel_buttons: dict[int, ttk.Button] = {}
        for number in range(1, 11):
            button = ttk.Button(frame, text=str(number), style="Channel.TButton", command=lambda item=number: self._switch_channel(item))
            button.pack(side=tk.LEFT, padx=2)
            self.channel_buttons[number] = button
        self._refresh_channel_buttons()

    def _build_input(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X)
        ttk.Label(frame, text="Eingabe:").pack(side=tk.LEFT)
        self.input_entry = ttk.Entry(frame, font="TkFixedFont")
        self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self.input_entry.bind("<Return>", lambda _event: self._send_input())
        ttk.Button(frame, text="Senden", command=self._send_input).pack(side=tk.LEFT)

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
        self._set_status(f"Kanal {self.session.current_channel}: verbunden mit {target.call}")
        self._schedule_transport_poll(0)

    def _disconnect(self) -> None:
        self._cancel_transport_poll()
        try:
            self.session.disconnect()
        except Exception as exc:
            self._append_info(str(exc))
        self._append_info("Verbindung getrennt")
        self._refresh_channel_buttons()
        self._set_status("Getrennt")

    def _switch_channel(self, number: int) -> None:
        self.session.switch_channel(number)
        self._redraw_qso()
        self._refresh_channel_buttons()
        self.channel_status_var.set(f"Kanal {number}")
        self._set_status(f"Kanal {number}")

    def _send_input(self) -> None:
        text = self.input_entry.get()
        if not text:
            return
        self.input_entry.delete(0, tk.END)
        user = self.store.get(self.session.channel.peer_call) if self.session.channel.peer_call else UserRecord(call="")
        try:
            rendered = self.session.send_template(text, user=user)
        except Exception as exc:
            self._set_status(str(exc))
            return
        self._append_qso("tx", rendered)
        peer_call = self.session.channel.peer_call or "CQ"
        if self.transport_name == "loopback":
            frame = encode_ui_frame(self.station.normalized_call(), peer_call, rendered.encode("latin-1", errors="replace"))
            self._append_monitor(format_ax25_frame(frame, port=self.default_port, direction="TX"))
        self._schedule_transport_poll(0)
        self._set_status("Gesendet")

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
            marker = "*" if channel.connected else ""
            button.configure(text=f"{number}{marker}", style="Active.Channel.TButton" if number == self.session.current_channel else "Channel.TButton")

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
            qso_receiver = getattr(self.session.transport, "receive_qso_lines", None)
            if qso_receiver is not None:
                for line in qso_receiver():
                    self.session.channel.append_rx(line)
                    self._append_qso("rx", line)
        except Exception as exc:
            self._append_info(f"Monitorfehler: {exc}")
            self._set_status(f"Monitorfehler: {exc}")
            self.transport_poll_after_id = None
            return
        if getattr(self.session.transport, "remote_disconnected", False):
            setattr(self.session.transport, "remote_disconnected", False)
            self.session.channel.disconnect()
            self._append_info("Gegenstation hat getrennt")
            self._refresh_channel_buttons()
            self._set_status("Getrennt durch Gegenstation")
            return
        if self.session.channel.connected:
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

    def _close(self) -> None:
        self.closing = True
        self._cancel_transport_poll()
        try:
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
        self.enabled_var = tk.BooleanVar(value=config.get_active_port().enabled)
        self._build()
        self.grab_set()

    def _build(self) -> None:
        station_frame = ttk.LabelFrame(self, text="Persönliche Daten", padding=8)
        station_frame.pack(fill=tk.X, padx=8, pady=8)
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
            ttk.Label(station_frame, text=label).grid(row=row // 2, column=(row % 2) * 2, sticky=tk.W, padx=(0, 4), pady=2)
            var = tk.StringVar(value=str(getattr(self.config_model.station, name)))
            self.station_vars[name] = var
            ttk.Entry(station_frame, textvariable=var, width=28).grid(row=row // 2, column=(row % 2) * 2 + 1, sticky=tk.W, padx=(0, 12), pady=2)
        self.station_vars["call"].trace_add("write", self._update_license_class)

        port = self.config_model.get_active_port()
        port_frame = ttk.LabelFrame(self, text="Aktiver Port", padding=8)
        port_frame.pack(fill=tk.X, padx=8, pady=(0, 8))
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
            ttk.Label(port_frame, text=label).grid(row=row, column=0, sticky=tk.W, padx=(0, 4), pady=2)
            value = getattr(port, name)
            var = tk.StringVar(value="" if value is None else str(value))
            self.port_vars[name] = var
            ttk.Entry(port_frame, textvariable=var, width=42).grid(row=row, column=1, sticky=tk.W, pady=2)
        ttk.Checkbutton(port_frame, text="Aktiv", variable=self.enabled_var).grid(row=len(port_fields), column=1, sticky=tk.W, pady=2)

        buttons = ttk.Frame(self, padding=8)
        buttons.pack(fill=tk.X)
        ttk.Button(buttons, text="Speichern", command=self._save).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(buttons, text="Abbrechen", command=self.destroy).pack(side=tk.RIGHT)

    def _update_license_class(self, *_args) -> None:
        inferred = infer_german_license_class(self.station_vars["call"].get())
        if inferred:
            self.station_vars["operator_class"].set(inferred)

    def _save(self) -> None:
        for name, var in self.station_vars.items():
            setattr(self.config_model.station, name, var.get().strip())
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