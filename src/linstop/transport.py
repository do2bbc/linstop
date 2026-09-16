from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Protocol, TextIO

from .ax25 import format_ax25ip_datagram
from .ax25udp import Ax25UdpEndpoint, Ax25UdpSocket, build_disc_frame, build_i_frame, build_rr_frame, build_sabm_frame, build_ui_frame, build_ua_frame, decode_ax25ip_packet


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

    def connect(self, peer_call: str, via: list[str]) -> None:
        self.peer_call = peer_call.upper()
        self.via = tuple(item.upper() for item in via)
        self.socket = Ax25UdpSocket(self.endpoint)
        self.remote_disconnected = False
        try:
            frame = build_sabm_frame(self.local_call, self.peer_call, self.via)
            self.socket.send(frame)
            self._append_tx_monitor(frame)
            self.pending_monitor_lines.extend(self._read_monitor_lines(limit=10))
        except Exception:
            self.socket.close()
            self.socket = None
            self.peer_call = ""
            self.via = ()
            raise

    def disconnect(self) -> None:
        if self.socket is not None and self.peer_call:
            try:
                if self.socket.is_open():
                    frame = build_disc_frame(self.local_call, self.peer_call, self.via)
                    self.socket.send(frame)
                    self._append_tx_monitor(frame)
            except Exception:
                pass
            self.socket.close()
        self.socket = None
        self.peer_call = ""
        self.via = ()
        self.link_established = False
        self.remote_disconnected = False

    def send_line(self, text: str) -> None:
        if self.socket is None or not self.peer_call:
            raise RuntimeError("AX25UDP-Verbindung ist nicht offen")
        self.pending_monitor_lines.extend(self._read_monitor_lines(limit=10))
        frame = build_i_frame(self.local_call, self.peer_call, text + "\r", ns=self.send_state, nr=self.receive_state, via=self.via)
        self.socket.send(frame)
        self._append_tx_monitor(frame)
        self.send_state = (self.send_state + 1) % 8

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
        if frame.destination.call != self.local_call.split("-", 1)[0].upper():
            return formatted
        if frame.control.name == "UA":
            self.link_established = True
        elif frame.control.name == "DISC":
            ua_frame = build_ua_frame(self.local_call, self.peer_call, self.via)
            self.socket.send(ua_frame)
            self._append_tx_monitor(ua_frame)
            self.link_established = False
            self.remote_disconnected = True
            self.socket.close()
            self.socket = None
        elif frame.control.family == "I" and frame.control.ns is not None:
            self.receive_state = (frame.control.ns + 1) % 8
            lines, self.pending_qso_text = _decode_qso_payload(frame.payload, self.pending_qso_text)
            self.pending_qso_lines.extend(lines)
            rr_frame = build_rr_frame(self.local_call, self.peer_call, nr=self.receive_state, via=self.via, poll_final=frame.control.poll_final)
            self.socket.send(rr_frame)
            self._append_tx_monitor(rr_frame)
        elif frame.control.name == "RR" and frame.control.nr is not None:
            pass
        return formatted

    def _append_tx_monitor(self, frame: bytes) -> None:
        self.pending_monitor_lines.append(format_ax25ip_datagram(frame, port=f"{self.endpoint.remote_host}:{self.endpoint.remote_port}", direction="TX"))


def _decode_qso_payload(payload: bytes, pending: str = "") -> tuple[list[str], str]:
    text = pending + payload.decode("latin-1", errors="replace")
    text = text.replace("\r\n", "\r").replace("\n", "\r")
    parts = text.split("\r")
    if text.endswith("\r"):
        complete = parts[:-1]
        remainder = ""
    else:
        complete = parts[:-1]
        remainder = parts[-1]
    lines = [line for line in complete if line]
    if remainder.endswith("=>"):
        lines.append(remainder)
        remainder = ""
    return lines, remainder
