from __future__ import annotations

import argparse
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .ax25 import format_ax25_frame, format_kiss_frame, parse_hex_bytes
from .ax25udp import Ax25UdpEndpoint
from .config import ConfigStore, default_config_path
from .models import LinStopConfig, PortConfig, StationProfile
from .session import LinStopSession
from .storage import UserStore
from .transport import Ax25CommandTransport, Ax25UdpTransport, LoopbackTransport, Transport
from .variables import TemplateContext, render_template


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="linstop", description="Linux Packet-Radio terminal prototype")
    parser.add_argument("--config", type=Path, default=default_config_path(), help="Pfad zur LinSTOP-Konfiguration")
    parser.add_argument("--station", default=None, help="eigenes Rufzeichen")
    parser.add_argument("--data", type=Path, default=_default_data_path(), help="Pfad zur Userdatenbank")
    parser.add_argument("--port-name", default=None, help="Name des konfigurierten LinSTOP-Ports")
    parser.add_argument("--transport", choices=("loopback", "ax25", "ax25udp"), default=None, help="Transportbackend")
    parser.add_argument("--port", default=None, help="AX.25-Port aus /etc/ax25/axports")
    parser.add_argument("--udp-remote-host", default=None, help="AX25UDP-Gegenstelle")
    parser.add_argument("--udp-remote-port", type=int, default=None, help="AX25UDP-UDP-Port der Gegenstelle")
    parser.add_argument("--udp-local-port", type=int, default=None, help="lokaler AX25UDP-Port, 0 für beliebig")
    subparsers = parser.add_subparsers(dest="command", required=True)

    connect_parser = subparsers.add_parser("connect", help="Verbindung aufbauen")
    connect_parser.add_argument("call", help="Gegenstation")
    connect_parser.add_argument("--via", nargs="*", default=[], help="Digipeater-/Node-Pfad")
    connect_parser.add_argument("--send", action="append", default=[], help="Text oder Makro nach Connect senden")
    connect_parser.add_argument("--send-start-line", action="store_true", help="LinSTOP-Startzeile nach ausgehendem Connect senden")

    template_parser = subparsers.add_parser("template", help="Textvariablen expandieren")
    template_parser.add_argument("text")
    template_parser.add_argument("--user", default="", help="Gegenstation für User-Variablen")

    decode_parser = subparsers.add_parser("decode-frame", help="AX.25- oder KISS-Hexframe formatieren")
    decode_parser.add_argument("hexbytes", help="Hexbytes, z.B. '9c 94 6e ...'")
    decode_parser.add_argument("--kiss", action="store_true", help="Eingabe als KISS-Frame interpretieren")
    decode_parser.add_argument("--direction", default="RX", help="Monitor-Richtung")

    probe_parser = subparsers.add_parser("probe-ax25udp", help="kurzen AX25UDP-Test senden und auf Antwort warten")
    probe_parser.add_argument("destination", help="AX.25-Zielrufzeichen")
    probe_parser.add_argument("--mode", choices=("sabm", "ui"), default="sabm", help="Testframe-Typ")
    probe_parser.add_argument("--text", default="LinSTOP test", help="Payload für UI-Testframes")
    probe_parser.add_argument("--timeout", type=float, default=5.0, help="Empfangswartezeit in Sekunden")

    subparsers.add_parser("mheard", help="bekannte Userdatenbank anzeigen")
    subparsers.add_parser("config-show", help="aktive LinSTOP-Konfiguration anzeigen")
    subparsers.add_parser("config-init", help="Default-Konfiguration schreiben")
    subparsers.add_parser("shell", help="interaktive Shell starten")
    subparsers.add_parser("gui", help="windowsartige Desktop-Oberfläche starten")

    args = parser.parse_args(argv)
    config_store = ConfigStore(args.config)
    config = config_store.load()
    port_config = _selected_port(config, args.port_name)
    station = _station_from_args(config, args)
    store = UserStore(args.data)
    store.load()

    if args.command == "connect":
        transport = _make_transport(_transport_name(args, port_config), _ax25_port(args, port_config), _local_call(station, port_config), _endpoint(args, port_config))
        session = LinStopSession(station, transport)
        user = store.note_connect(args.call, datetime.now())
        try:
            start_line = session.connect(args.call, user=user, via=args.via, send_start_line=args.send_start_line)
            print(start_line if args.send_start_line else f"connected to {args.call.upper()}")
            _print_transport_monitor(transport)
            for template in args.send:
                print(session.send_template(template, user=user))
                _print_transport_monitor(transport)
            store.save()
        finally:
            session.disconnect()
        return 0

    if args.command == "template":
        transport = LoopbackTransport()
        session = LinStopSession(station, transport)
        user = store.get(args.user) if args.user else None
        print(render_template(args.text, TemplateContext(station=station, channel=session.channel, user=user)))
        return 0

    if args.command == "decode-frame":
        data = parse_hex_bytes(args.hexbytes)
        if args.kiss:
            print(format_kiss_frame(data))
        else:
            print(format_ax25_frame(data, port=args.port, direction=args.direction))
        return 0

    if args.command == "config-show":
        import json

        print(json.dumps(asdict(config), indent=2, ensure_ascii=False))
        return 0

    if args.command == "config-init":
        config_store.save(config)
        print(config_store.path)
        return 0

    if args.command == "probe-ax25udp":
        from .ax25udp import Ax25UdpSocket, build_sabm_frame, build_ui_frame

        endpoint = _endpoint(args, port_config)
        udp_socket = Ax25UdpSocket(endpoint, timeout=args.timeout)
        try:
            if args.mode == "ui":
                frame = build_ui_frame(station.normalized_call(), args.destination, args.text)
            else:
                frame = build_sabm_frame(station.normalized_call(), args.destination)
            udp_socket.send(frame)
            print(f"TX {args.mode.upper()} {station.normalized_call()}>{args.destination.upper()} len={len(frame)} | {frame.hex(' ')}")
            packets = udp_socket.receive_available(limit=10)
            if not packets:
                print(f"RX timeout after {args.timeout:.1f}s")
            for packet in packets:
                print(packet.format())
        finally:
            udp_socket.close()
        return 0

    if args.command == "mheard":
        for user in store.all():
            last = user.last_connected_at.isoformat(timespec="seconds") if user.last_connected_at else "-"
            print(f"{user.call:12} {user.connect_count:5} {last} {user.display_name()}")
        return 0

    if args.command == "shell":
        return _shell(station, store, _make_transport(_transport_name(args, port_config), _ax25_port(args, port_config), _local_call(station, port_config), _endpoint(args, port_config)))

    if args.command == "gui":
        from .gui import run_gui

        return run_gui(station, args.data, _transport_name(args, port_config), _ax25_port(args, port_config), _endpoint(args, port_config), config, config_store)

    return 2


def _default_data_path() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "linstop" / "users.json"


def _selected_port(config: LinStopConfig, name: str | None) -> PortConfig:
    if name is None:
        return config.get_active_port()
    for port in config.ports:
        if port.name == name:
            return port
    raise SystemExit(f"Port {name!r} ist nicht konfiguriert")


def _station_from_args(config: LinStopConfig, args: argparse.Namespace) -> StationProfile:
    if args.station:
        station = StationProfile(**asdict(config.station))
        station.call = args.station.upper()
        return station
    return config.station


def _transport_name(args: argparse.Namespace, port: PortConfig) -> str:
    return args.transport or port.transport


def _ax25_port(args: argparse.Namespace, port: PortConfig) -> str:
    return args.port or port.ax25_port


def _local_call(station: StationProfile, port: PortConfig) -> str:
    return (port.local_call or station.normalized_call()).upper()


def _endpoint(args: argparse.Namespace, port: PortConfig) -> Ax25UdpEndpoint:
    raw_local_port = port.udp_local_port if args.udp_local_port is None else args.udp_local_port
    local_port = None if raw_local_port == 0 else raw_local_port
    return Ax25UdpEndpoint(
        remote_host=args.udp_remote_host or port.udp_remote_host,
        remote_port=args.udp_remote_port if args.udp_remote_port is not None else port.udp_remote_port,
        local_port=local_port,
    )


def _make_transport(name: str, port: str, local_call: str, endpoint: Ax25UdpEndpoint) -> Transport:
    if name == "ax25":
        return Ax25CommandTransport(port=port, local_call=local_call)
    if name == "ax25udp":
        return Ax25UdpTransport(local_call=local_call, endpoint=endpoint)
    return LoopbackTransport()


def _shell(station: StationProfile, store: UserStore, transport: Transport) -> int:
    session = LinStopSession(station, transport)
    print("LinSTOP Shell. Befehle: /c CALL [VIA...], /d, /ch N, /mh, /q")
    while True:
        try:
            line = input(f"{station.normalized_call()}:{session.current_channel}> ").strip()
        except EOFError:
            print()
            break
        if not line:
            continue
        if line in {"/q", "/quit"}:
            break
        if line.startswith("/ch "):
            session.switch_channel(int(line.split()[1]))
            continue
        if line.startswith("/c "):
            parts = line.split()
            user = store.note_connect(parts[1], datetime.now())
            session.connect(parts[1], user=user, via=parts[2:])
            print(f"*** Connected to {parts[1].upper()}")
            _print_transport_monitor(transport)
            store.save()
            continue
        if line == "/d":
            session.disconnect()
            print("*** Disconnected")
            continue
        if line == "/mh":
            for call, at in sorted(session.mheard.items()):
                print(f"{call:12} {at.isoformat(timespec='seconds')}")
            continue
        user = store.get(session.channel.peer_call) if session.channel.peer_call else None
        print(session.send_template(line, user=user))
        _print_transport_monitor(transport)
    store.save()
    return 0


def _print_transport_monitor(transport: Transport) -> None:
    receiver = getattr(transport, "receive_monitor_lines", None)
    if receiver is None:
        return
    for line in receiver():
        print(line)
