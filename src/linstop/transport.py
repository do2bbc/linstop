from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Protocol, TextIO

from .ax25 import format_ax25ip_datagram
from .ax25udp import Ax25UdpEndpoint, Ax25UdpSocket, build_disc_frame, build_dm_frame, build_i_frame, build_rr_frame, build_sabm_frame, build_ui_frame, build_ua_frame, decode_ax25ip_packet


class Transport(Protocol):
    def connect(self, peer_call: str, via: list[str]) -> None: ...

    def disconnect(self) -> None: ...

    def send_line(self, text: str) -> None: ...


@dataclass(slots=True)
class LoopbackTransport:
    sent: list[str] = field(default_factory=list)
    connected_to: str = ""

    def connect(self, peer_call: str, via: list[str]) -> None:
        path = " ".join([peer_call.upper(), *[item.upper() for item in via]])
        self.connected_to = path.strip()
        self.sent.append(f"CONNECT {self.connected_to}")

    def disconnect(self) -> None:
        self.sent.append("DISCONNECT")
        self.connected_to = ""

    def send_line(self, text: str) -> None:
        self.sent.append(text)


@dataclass(slots=True)
class Ax25CommandTransport:
    port: str
    local_call: str
    axcall_path: str = "ax25_call"
    process: subprocess.Popen[str] | None = None

    def connect(self, peer_call: str, via: list[str]) -> None:
        executable = shutil.which(self.axcall_path)
        if executable is None:
            raise RuntimeError(f"{self.axcall_path!r} nicht gefunden; installiere ax25-tools")
        command = self.build_command(executable, self.port, self.local_call, peer_call, via)
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=None,
            stderr=None,
            text=True,
            bufsize=1,
        )

    def disconnect(self) -> None:
        if self.process is None:
            return
        stdin = self._stdin()
        stdin.write("/exit\n")
        stdin.flush()
        self.process.terminate()
        self.process = None

    def send_line(self, text: str) -> None:
        stdin = self._stdin()
        stdin.write(text + "\n")
        stdin.flush()

    @staticmethod
    def build_command(executable: str, port: str, local_call: str, peer_call: str, via: list[str]) -> list[str]:
        return [executable, port, local_call.upper(), peer_call.upper(), *[item.upper() for item in via]]

    def _stdin(self) -> TextIO:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("AX.25-Verbindung ist nicht offen")
        return self.process.stdin


@dataclass(slots=True)
class Ax25UdpLinkState:
    peer_call: str
    via: tuple[str, ...] = ()
    send_state: int = 0
    receive_state: int = 0
    link_established: bool = False
    pending_qso_text: str = ""


@dataclass(slots=True)
class Ax25UdpTransport:
    local_call: str
    endpoint: Ax25UdpEndpoint = field(default_factory=Ax25UdpEndpoint)
    peer_call: str = ""
    via: tuple[str, ...] = ()
    socket: Ax25UdpSocket | None = None
    send_state: int = 0
    receive_state: int = 0
    link_established: bool = False
    remote_disconnected: bool = False
    pending_monitor_lines: list[str] = field(default_factory=list)
    pending_qso_lines: list[str] = field(default_factory=list)
    pending_qso_text: str = ""
    links: dict[str, Ax25UdpLinkState] = field(default_factory=dict)
    pending_qso_events: list[tuple[str, str]] = field(default_factory=list)
    pending_connected_peers: list[str] = field(default_factory=list)
    pending_disconnected_peers: list[str] = field(default_factory=list)

    @property
    def listening(self) -> bool:
        return self.socket is not None

    def ensure_listening(self) -> None:
        if self.socket is None:
            self.socket = Ax25UdpSocket(self.endpoint)
        if not self.socket.is_open():
            self.socket.open()

    def connect(self, peer_call: str, via: list[str]) -> None:
        peer = peer_call.upper()
        link = self._link(peer)
        link.via = tuple(item.upper() for item in via)
        self._select_link(peer)
        if self.socket is None:
            self.socket = Ax25UdpSocket(self.endpoint)
        self.remote_disconnected = False
        try:
            frame = build_sabm_frame(self.local_call, link.peer_call, link.via)
            self.socket.send(frame)
            self._append_tx_monitor(frame)
            self.pending_monitor_lines.extend(self._read_monitor_lines(limit=10))
        except Exception:
            self.socket.close()
            self.socket = None
            self.links.pop(peer, None)
            self._select_link(next(iter(self.links), ""))
            raise

    def select_peer(self, peer_call: str) -> None:
        self._select_link(peer_call.upper())

    def disconnect(self) -> None:
        peer = self.peer_call
        link = self.links.get(peer) if peer else None
        if self.socket is not None and link is not None:
            try:
                if self.socket.is_open():
                    frame = build_disc_frame(self.local_call, link.peer_call, link.via)
                    self.socket.send(frame)
                    self._append_tx_monitor(frame)
            except Exception:
                pass
            self.links.pop(peer, None)
        self._select_link(next(iter(self.links), ""))
        self.remote_disconnected = False

    def disconnect_all(self) -> None:
        if self.socket is not None:
            for link in list(self.links.values()):
                try:
                    if self.socket.is_open():
                        frame = build_disc_frame(self.local_call, link.peer_call, link.via)
                        self.socket.send(frame)
                        self._append_tx_monitor(frame)
                except Exception:
                    pass
            try:
                self.socket.close()
            except Exception:
                pass
        self.socket = None
        self.links.clear()
        self.pending_connected_peers.clear()
        self.pending_disconnected_peers.clear()
        self._select_link("")
        self.remote_disconnected = False

    def send_line(self, text: str) -> None:
        link = self.links.get(self.peer_call) or (self._link(self.peer_call) if self.peer_call else None)
        if self.socket is None or link is None:
            raise RuntimeError("AX25UDP-Verbindung ist nicht offen")
        self.pending_monitor_lines.extend(self._read_monitor_lines(limit=10))
        frame = build_i_frame(self.local_call, link.peer_call, text + "\r", ns=link.send_state, nr=link.receive_state, via=link.via)
        self.socket.send(frame)
        self._append_tx_monitor(frame)
        link.send_state = (link.send_state + 1) % 8
        self._sync_legacy_state(link)

    def receive_monitor_lines(self) -> tuple[str, ...]:
        lines = [*self.pending_monitor_lines]
        if self.socket is not None:
            lines.extend(self._read_monitor_lines())
        self.pending_monitor_lines.clear()
        return tuple(lines)

    def receive_qso_lines(self) -> tuple[str, ...]:
        lines = tuple(self.pending_qso_lines)
        self.pending_qso_lines.clear()
        return lines

    def receive_qso_events(self) -> tuple[tuple[str, str], ...]:
        events = tuple(self.pending_qso_events)
        self.pending_qso_events.clear()
        return events

    def receive_connected_peers(self) -> tuple[str, ...]:
        peers = tuple(self.pending_connected_peers)
        self.pending_connected_peers.clear()
        return peers

    def receive_disconnected_peers(self) -> tuple[str, ...]:
        peers = tuple(self.pending_disconnected_peers)
        self.pending_disconnected_peers.clear()
        return peers

    def _read_monitor_lines(self, limit: int = 20) -> list[str]:
        if self.socket is None:
            return []
        return [self._handle_packet(packet) for packet in self.socket.receive_available(limit=limit)]

    def _handle_packet(self, packet) -> str:
        formatted = packet.format()
        if self.socket is None:
            return formatted
        try:
            frame = decode_ax25ip_packet(packet.data)
        except Exception:
            return formatted
        local_base_call = self.local_call.split("-", 1)[0].upper()
        if frame.destination.call != local_base_call:
            return formatted
        if frame.source.call == local_base_call:
            return formatted
        source = frame.source.label().rstrip("*")
        source_via = tuple(address.label().rstrip("*") for address in frame.digipeaters)
        if frame.control.name == "UA":
            link = self.links.get(source) or self.links.get(self.peer_call)
            if link is not None:
                link.link_established = True
                self._select_link(link.peer_call)
        elif frame.control.name == "SABM":
            link = self._link(source)
            link.via = tuple(address.label().rstrip("*") for address in frame.digipeaters)
            link.send_state = 0
            link.receive_state = 0
            link.pending_qso_text = ""
            link.link_established = True
            self.remote_disconnected = False
            self._select_link(link.peer_call)
            if link.peer_call not in self.pending_connected_peers:
                self.pending_connected_peers.append(link.peer_call)
            ua_frame = build_ua_frame(self.local_call, link.peer_call, link.via)
            self.socket.send(ua_frame)
            self._append_tx_monitor(ua_frame)
        elif frame.control.name == "DISC":
            link = self.links.get(source)
            if link is None:
                dm_frame = build_dm_frame(self.local_call, source, source_via)
                self.socket.send(dm_frame)
                self._append_tx_monitor(dm_frame)
                return formatted
            ua_frame = build_ua_frame(self.local_call, link.peer_call, link.via)
            self.socket.send(ua_frame)
            self._append_tx_monitor(ua_frame)
            self.links.pop(link.peer_call, None)
            self.pending_disconnected_peers.append(link.peer_call)
            self.remote_disconnected = self.peer_call == link.peer_call
            self._select_link(next(iter(self.links), ""))
        elif frame.control.family == "I" and frame.control.ns is not None:
            link = self.links.get(source)
            if link is None:
                dm_frame = build_dm_frame(self.local_call, source, source_via)
                self.socket.send(dm_frame)
                self._append_tx_monitor(dm_frame)
                return formatted
            link.receive_state = (frame.control.ns + 1) % 8
            lines, link.pending_qso_text = _decode_qso_payload(frame.payload)
            self.pending_qso_lines.extend(lines)
            self.pending_qso_events.extend((link.peer_call, line) for line in lines)
            rr_frame = build_rr_frame(self.local_call, link.peer_call, nr=link.receive_state, via=link.via, poll_final=frame.control.poll_final)
            self.socket.send(rr_frame)
            self._append_tx_monitor(rr_frame)
            self._sync_legacy_state(link)
        elif frame.control.family == "S":
            link = self.links.get(source)
            if link is None:
                dm_frame = build_dm_frame(self.local_call, source, source_via)
                self.socket.send(dm_frame)
                self._append_tx_monitor(dm_frame)
                return formatted
        return formatted

    def _append_tx_monitor(self, frame: bytes) -> None:
        self.pending_monitor_lines.append(format_ax25ip_datagram(frame, port=f"{self.endpoint.remote_host}:{self.endpoint.remote_port}", direction="TX"))

    def _link(self, peer_call: str) -> Ax25UdpLinkState:
        peer = peer_call.upper()
        if peer not in self.links:
            self.links[peer] = Ax25UdpLinkState(peer_call=peer)
        return self.links[peer]

    def _select_link(self, peer_call: str) -> None:
        peer = peer_call.upper()
        self.peer_call = peer
        link = self.links.get(peer)
        if link is None:
            self.via = ()
            self.send_state = 0
            self.receive_state = 0
            self.link_established = False
            self.pending_qso_text = ""
            return
        self._sync_legacy_state(link)

    def _sync_legacy_state(self, link: Ax25UdpLinkState) -> None:
        self.peer_call = link.peer_call
        self.via = link.via
        self.send_state = link.send_state
        self.receive_state = link.receive_state
        self.link_established = link.link_established
        self.pending_qso_text = link.pending_qso_text


def _decode_qso_payload(payload: bytes, pending: str = "") -> tuple[list[str], str]:
    text = pending + payload.decode("latin-1", errors="replace")
    text = text.replace("\r\n", "\r").replace("\n", "\r")
    return [line for line in text.split("\r") if line], ""
