from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from .models import UserRecord
from .storage import UserStore


class UserDatabaseDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, store: UserStore, call: str | None = None) -> None:
        super().__init__(parent)
        self.title("User-Datenbank bearbeiten")
        self.geometry("900x640")
        self.minsize(820, 560)
        self.transient(parent)
        self.store = store
        self.string_vars: dict[str, tk.StringVar] = {}
        self.bool_vars: dict[str, tk.BooleanVar] = {}
        self.text_widgets: dict[str, tk.Text] = {}
        self.current_call = ""
        self._build()
        self._refresh_user_list()
        self._load_user(call or self._first_call())
        self.wait_visibility()
        self.grab_set()

    def _build(self) -> None:
        outer = ttk.Frame(self, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(outer)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        ttk.Label(left, text="Rufzeichen auswaehlen").pack(anchor=tk.W)
        self.tree_view_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(left, text="Baumansicht", variable=self.tree_view_var).pack(anchor=tk.W, pady=(2, 12))
        ttk.Label(left, text="Gehe zu:").pack(anchor=tk.W)
        self.goto_var = tk.StringVar()
        goto = ttk.Entry(left, textvariable=self.goto_var, width=22)
        goto.pack(anchor=tk.W, pady=(2, 8))
        goto.bind("<Return>", lambda _event: self._load_user(self.goto_var.get()))
        self.user_list = tk.Listbox(left, width=24, exportselection=False, font="TkFixedFont")
        self.user_list.pack(fill=tk.BOTH, expand=True)
        self.user_list.bind("<<ListboxSelect>>", self._select_from_list)
        buttons_left = ttk.Frame(left)
        buttons_left.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(buttons_left, text="OK", command=self._save_and_close).grid(row=0, column=0, sticky=tk.EW, padx=(0, 4), pady=2)
        ttk.Button(buttons_left, text="Reparieren", command=self._refresh_user_list).grid(row=0, column=1, sticky=tk.EW, pady=2)
        ttk.Button(buttons_left, text="Importieren...", command=self._not_implemented).grid(row=1, column=0, sticky=tk.EW, padx=(0, 4), pady=2)
        ttk.Button(buttons_left, text="Exportieren...", command=self._not_implemented).grid(row=1, column=1, sticky=tk.EW, pady=2)

        right = ttk.Frame(outer)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        header = ttk.LabelFrame(right, text="Eintraege der User-Datenbank bearbeiten", padding=8)
        header.pack(fill=tk.X)
        for column in range(6):
            header.columnconfigure(column, weight=1)
        top_fields = (
            ("afu_call", "Afu-Call"),
            ("bbs_call", "BBS-Call"),
            ("cb_call_1", "CB-Call 1"),
            ("node_call", "Node-Call"),
            ("cb_call_2", "CB-Call 2"),
            ("convers_call", "Convers-Call"),
        )
        for index, (name, label) in enumerate(top_fields):
            row = index // 2
            base_column = (index % 2) * 3
            ttk.Label(header, text=f"{label}:").grid(row=row, column=base_column, sticky=tk.W, padx=(0, 4), pady=2)
            self._entry(header, name, width=18).grid(row=row, column=base_column + 1, sticky=tk.EW, pady=2)
        ttk.Button(header, text="Speichern", command=self._save).grid(row=0, column=5, sticky=tk.EW, padx=(12, 0), pady=2)
        ttk.Button(header, text="Hinzufuegen", command=self._add_user).grid(row=0, column=6, sticky=tk.EW, padx=(8, 0), pady=2)
        ttk.Button(header, text="Rueckgaengig", command=lambda: self._load_user(self.current_call)).grid(row=1, column=5, sticky=tk.EW, padx=(12, 0), pady=2)
        ttk.Button(header, text="Loeschen", command=self._delete_user).grid(row=1, column=6, sticky=tk.EW, padx=(8, 0), pady=2)

        notebook = ttk.Notebook(right)
        notebook.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self._build_main_tab(notebook)
        self._build_password_tab(notebook)
        self._build_remote_tab(notebook)
        self._build_software_tab(notebook)

    def _build_main_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=8)
        notebook.add(frame, text="Hauptseite")
        for column in range(6):
            frame.columnconfigure(column, weight=1)
        self._labeled_entry(frame, "name", "Vorname", 0, 0, 5)
        self._labeled_entry(frame, "qth", "Ort", 1, 0, 5)
        self._labeled_entry(frame, "phone", "Telefon", 2, 0, 2)
        self._labeled_entry(frame, "email", "eMail", 2, 2, 2)
        self._labeled_entry(frame, "birthday", "Geburtstag", 2, 4, 2)
        self._labeled_entry(frame, "locator", "Locator", 3, 0, 2)
        self._labeled_entry(frame, "afu_connect_via", "Afu-Connect via", 3, 4, 2)
        umlaut = ttk.LabelFrame(frame, text="Umlautwandlung", padding=6)
        umlaut.grid(row=4, column=0, columnspan=2, sticky=tk.NSEW, pady=(8, 0), padx=(0, 8))
        self._radio_group(umlaut, "umlaut_mode", (("DOS-437-Zeichensatz", "dos437"), ("ISO-Latin1-Umlaute", "latin1"), ("C64-Umlaute", "c64"), ("Umlautaufloesung", "ascii")))
        transfer = ttk.LabelFrame(frame, text="Uebertragungsparameter", padding=6)
        transfer.grid(row=4, column=2, columnspan=2, sticky=tk.NSEW, pady=(8, 0), padx=(0, 8))
        self._labeled_entry(transfer, "packet_length", "Paketlaenge", 0, 0, 2)
        self._labeled_entry(transfer, "maxframe", "MaxFrame", 1, 0, 2)
        compression = ttk.LabelFrame(frame, text="Kompression", padding=6)
        compression.grid(row=4, column=4, columnspan=2, sticky=tk.NSEW, pady=(8, 0))
        self._labeled_entry(compression, "compression_encryption", "Verschluesselung", 0, 0, 2)
        self._check(compression, "compression_on_connect", "bei Connect einschalten").grid(row=1, column=0, columnspan=2, sticky=tk.W)
        connect = ttk.LabelFrame(frame, text="spezieller Connect-Text", padding=6)
        connect.grid(row=5, column=0, columnspan=6, sticky=tk.NSEW, pady=(8, 0))
        self._text(connect, "connect_text", height=4).pack(fill=tk.BOTH, expand=True)
        misc = ttk.LabelFrame(frame, text="diverse Schalter", padding=6)
        misc.grid(row=6, column=0, columnspan=2, sticky=tk.NSEW, pady=(8, 0), padx=(0, 8))
        for name, label in (("remote_allowed", "Fernsteuerung erlaubt"),):
            self._check(misc, name, label).pack(anchor=tk.W)
        home = ttk.LabelFrame(frame, text="Home-BBS (externe Netze)", padding=6)
        home.grid(row=6, column=2, columnspan=2, sticky=tk.NSEW, pady=(8, 0), padx=(0, 8))
        self._labeled_entry(home, "home_bbs_afu", "auf Afu", 0, 0, 2)
        self._labeled_entry(home, "home_bbs_cb", "auf CB", 1, 0, 2)
        counters = ttk.Frame(frame)
        counters.grid(row=6, column=4, columnspan=2, sticky=tk.NSEW, pady=(8, 0))
        self._labeled_entry(counters, "connect_count", "Connect-Nr.", 0, 0, 2)
        self._labeled_entry(counters, "login_count", "Login-Nr.", 0, 2, 2)

    def _build_password_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=8)
        notebook.add(frame, text="Passwoerter, BBS, Rechte, Bemerkungen")
        frame.columnconfigure(1, weight=1)
        peer = ttk.LabelFrame(frame, text="Passwoerter der Gegenstation", padding=6)
        peer.pack(fill=tk.X)
        self._labeled_entry(peer, "peer_sysop_password", "Sysop-Privilegierung", 0, 0, 2)
        self._labeled_entry(peer, "peer_bbs_password", "BBS-Passwort", 1, 0, 2)
        own = ttk.LabelFrame(frame, text="eigene Passwoerter bei der Gegenstation", padding=6)
        own.pack(fill=tk.X, pady=(8, 0))
        self._labeled_entry(own, "own_sysop_password", "Sysop-Privilegierung", 0, 0, 2)
        self._labeled_entry(own, "own_bbs_password", "BBS-Passwort", 1, 0, 2)
        body = ttk.Frame(frame)
        body.pack(fill=tk.X, pady=(8, 0))
        bbs = ttk.LabelFrame(body, text="BBS-Einstellungen", padding=6)
        bbs.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))
        self._labeled_entry(bbs, "bbs_page_length", "Seitenlaenge", 0, 0, 2)
        self._check(bbs, "bbs_enabled", "an").grid(row=0, column=2, sticky=tk.W)
        self._check(bbs, "bbs_send_frame", "Rahmen senden").grid(row=1, column=0, sticky=tk.W)
        self._check(bbs, "bbs_frame_sorting", "Brettersortierung").grid(row=2, column=0, sticky=tk.W)
        self._labeled_entry(bbs, "home_bbs", "Home-BBS", 3, 0, 2)
        help_frame = ttk.LabelFrame(body, text="Hilfe", padding=6)
        help_frame.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 8))
        self._radio_group(help_frame, "bbs_help_mode", (("keine Hilfe", "none"), ("? im Prompt", "prompt"), ("einige Befehle im Prompt", "commands")))
        no_connect = ttk.LabelFrame(body, text="keine Connect-Erlaubnis", padding=6)
        no_connect.pack(side=tk.LEFT, fill=tk.BOTH)
        for name, label in (("no_connect_user", "fuer User"), ("no_connect_bbs", "fuer BBS"), ("no_connect_node", "fuer Node"), ("no_connect_convers", "fuer Conv."), ("cannot_connect_bbs", "BBS-Kanaele nicht verbinden")):
            self._check(no_connect, name, label).pack(anchor=tk.W)
        comments = ttk.LabelFrame(frame, text="Bemerkungen", padding=6)
        comments.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self._text(comments, "comments", height=6).pack(fill=tk.BOTH, expand=True)

    def _build_remote_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=8)
        notebook.add(frame, text="Fernsteuerung, Info")
        left = ttk.LabelFrame(frame, text="Remote-Ausnahmen", padding=6)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        self.remote_exceptions_box = tk.Listbox(left, height=11, width=22, exportselection=False, font="TkFixedFont")
        self.remote_exceptions_box.pack(fill=tk.BOTH, expand=True)
        right = ttk.Frame(frame)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        bbs = ttk.LabelFrame(right, text="BBS-Fernsteuer-Besonderheiten", padding=6)
        bbs.pack(fill=tk.X)
        for name, label in (("bbs_no_write", "S: keine Schreiberlaubnis"), ("bbs_write_private_sysop_only", "S: Schreiberlaubnis nur fuer private Mails an den Sysop"), ("bbs_write_private_everyone", "S: Schreiberlaubnis fuer private Mails an jeden"), ("bbs_write_public_hold", "S: Schreiberlaubnis fuer alles, aber Mails werden auf Hold gesetzt"), ("bbs_read_own_only", "R: Leseerlaubnis nur fuer eigene Mails"), ("bbs_no_cbox", "CON: BBS nicht als Node nutzbar"), ("bbs_sysop_not_callable", "T: Sysop nicht rufbar"), ("bbs_no_external_programs", "PG: keine externen Programme")):
            self._check(bbs, name, label).pack(anchor=tk.W)
        lower = ttk.Frame(right)
        lower.pack(fill=tk.X, pady=(8, 0))
        remote = ttk.LabelFrame(lower, text="Fernsteuerung", padding=6)
        remote.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))
        self._radio_group(remote, "remote_control", (("normal", "normal"), ("keine Fernsteuerung", "none"), ("mehr Fernsteuerung", "full")))
        mh = ttk.LabelFrame(lower, text="MHeard-Typ", padding=6)
        mh.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._radio_group(mh, "mh_format", (("Standard", "standard"), ("FlexNet-Format", "flexnet"), ("Remoteliste", "remote"), ("Onlineliste", "online")))
        info = ttk.LabelFrame(right, text="Stationsinfo", padding=6)
        info.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self._text(info, "station_info", height=5).pack(fill=tk.BOTH, expand=True)

    def _build_software_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=8)
        notebook.add(frame, text="Software")
        box = ttk.LabelFrame(frame, text="verwendete Software", padding=8)
        box.pack(fill=tk.X)
        names = [*(f"afu_ssid_{index}" for index in range(16)), "cb_user", "cb_bbs", "cb_node", "cb_convers"]
        labels = [*(f"Afu SSID {index}" for index in range(16)), "CB User", "CB BBS", "CB Node", "CB Convers"]
        self.software_vars: dict[str, tk.StringVar] = {}
        for index, (name, label) in enumerate(zip(names, labels, strict=True)):
            row = index % 10
            base_column = 0 if index < 10 else 2
            ttk.Label(box, text=f"{label}:").grid(row=row, column=base_column, sticky=tk.W, padx=(0, 4), pady=2)
            var = tk.StringVar(value="Automatisch")
            self.software_vars[name] = var
            ttk.Combobox(box, textvariable=var, values=("Automatisch", "WinSTOP", "TNT", "GP", "DPBOX", "TheNetNode", "unbekannt"), width=24).grid(row=row, column=base_column + 1, sticky=tk.EW, pady=2, padx=(0, 18))

    def _entry(self, parent: tk.Misc, name: str, width: int = 24) -> ttk.Entry:
        var = self.string_vars.setdefault(name, tk.StringVar())
        return ttk.Entry(parent, textvariable=var, width=width)

    def _labeled_entry(self, parent: tk.Misc, name: str, label: str, row: int, column: int, columnspan: int) -> None:
        ttk.Label(parent, text=f"{label}:").grid(row=row, column=column, sticky=tk.W, padx=(0, 4), pady=2)
        self._entry(parent, name).grid(row=row, column=column + 1, columnspan=max(1, columnspan - 1), sticky=tk.EW, pady=2)

    def _check(self, parent: tk.Misc, name: str, label: str) -> ttk.Checkbutton:
        var = self.bool_vars.setdefault(name, tk.BooleanVar(value=False))
        return ttk.Checkbutton(parent, text=label, variable=var)

    def _radio_group(self, parent: tk.Misc, name: str, values: tuple[tuple[str, str], ...]) -> None:
        var = self.string_vars.setdefault(name, tk.StringVar(value=values[0][1]))
        for label, value in values:
            ttk.Radiobutton(parent, text=label, value=value, variable=var).pack(anchor=tk.W)

    def _text(self, parent: tk.Misc, name: str, height: int) -> tk.Text:
        widget = tk.Text(parent, height=height, wrap=tk.WORD, font="TkFixedFont")
        self.text_widgets[name] = widget
        return widget

    def _first_call(self) -> str:
        users = sorted(self.store.all(), key=lambda item: item.call.upper())
        return users[0].call if users else "(DEFC)"

    def _refresh_user_list(self) -> None:
        self.user_list.delete(0, tk.END)
        for user in sorted(self.store.all(), key=lambda item: item.call.upper()):
            self.user_list.insert(tk.END, f"{user.call:12} {user.display_name()}")

    def _select_from_list(self, _event: tk.Event) -> None:
        selection = self.user_list.curselection()
        if selection:
            self._load_user(self.user_list.get(selection[0]).split()[0])

    def _load_user(self, call: str) -> None:
        call = call.strip().upper() or "(DEFC)"
        user = self.store.get(call)
        self.current_call = user.call.upper()
        self.goto_var.set(self.current_call)
        for name, var in self.string_vars.items():
            value = getattr(user, name, "")
            var.set(str(value if value is not None else ""))
        for name, var in self.bool_vars.items():
            var.set(bool(getattr(user, name, False)))
        for name, widget in self.text_widgets.items():
            widget.delete("1.0", tk.END)
            widget.insert("1.0", str(getattr(user, name, "")))
        self.remote_exceptions_box.delete(0, tk.END)
        for item in user.remote_exceptions:
            self.remote_exceptions_box.insert(tk.END, item)
        for name, var in self.software_vars.items():
            var.set(user.software.get(name, "Automatisch"))

    def _save(self) -> None:
        user = self.store.get(self.current_call)
        for name, var in self.string_vars.items():
            value = var.get().strip()
            current = getattr(user, name, "")
            if isinstance(current, int):
                try:
                    setattr(user, name, int(value or "0"))
                except ValueError:
                    setattr(user, name, current)
            elif isinstance(current, datetime):
                setattr(user, name, current)
            else:
                setattr(user, name, value)
        for name, var in self.bool_vars.items():
            setattr(user, name, var.get())
        for name, widget in self.text_widgets.items():
            setattr(user, name, widget.get("1.0", tk.END).rstrip("\n"))
        user.remote_exceptions = list(self.remote_exceptions_box.get(0, tk.END))
        user.software = {name: var.get() for name, var in self.software_vars.items() if var.get() != "Automatisch"}
        if not user.afu_call:
            user.afu_call = user.call
        self.store.save()
        self._refresh_user_list()

    def _save_and_close(self) -> None:
        self._save()
        self.destroy()

    def _add_user(self) -> None:
        call = self.goto_var.get().strip().upper()
        if not call:
            messagebox.showerror("LinSTOP", "Bitte ein Rufzeichen eintragen", parent=self)
            return
        user = self.store.get(call)
        user.afu_call = user.afu_call or call
        self.current_call = call
        self._load_user(call)
        self._refresh_user_list()

    def _delete_user(self) -> None:
        if not self.current_call:
            return
        if not messagebox.askyesno("LinSTOP", f"Eintrag {self.current_call} loeschen?", parent=self):
            return
        self.store.remove(self.current_call)
        self.store.save()
        self._refresh_user_list()
        self._load_user(self._first_call())

    def _not_implemented(self) -> None:
        messagebox.showinfo("LinSTOP", "Import/Export fuer WinSTOP-DBF folgt separat.", parent=self)