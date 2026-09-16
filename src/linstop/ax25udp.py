from __future__ import annotations

import socket
from dataclasses import dataclass

from .ax25 import Ax25DecodeError, decode_ax25_frame, encode_ax25ip_datagram, encode_i_frame, encode_rr_frame, encode_ui_frame, encode_ua_frame, encode_unnumbered_frame, format_ax25ip_datagram, strip_fcs


SABM_P = 0x3F
DISC_P = 0x53


class Ax25UdpError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class Ax25UdpEndpoint:
    remote_host: str = "44.148.230.93"
    remote_port: int = 93
    local_port: int | None = 10093


@dataclass(slots=True, frozen=True)
class Ax25UdpPacket:
    data: bytes
    address: tuple[str, int]

    def format(self, direction: str = "RX") -> str:
        try:
            return format_ax25ip_datagram(self.data, port=f"{self.address[0]}:{self.address[1]}", direction=direction)
        except Ax25DecodeError:
            return f"{self.address[0]}:{self.address[1]} {direction} raw len={len(self.data)} | {self.data.hex(' ')}"


class Ax25UdpSocket:
    def __init__(self, endpoint: Ax25UdpEndpoint, timeout: float = 0.1) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self.socket: socket.socket | None = None

    def open(self) -> None:
        if self.socket is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if self.endpoint.local_port is not None:
                sock.bind(("0.0.0.0", self.endpoint.local_port))
            sock.connect((self.endpoint.remote_host, self.endpoint.remote_port))
            sock.settimeout(self.timeout)
        except OSError as exc:
            sock.close()
            if exc.errno == 98:
                raise Ax25UdpError(f"UDP-Port {self.endpoint.local_port} ist bereits belegt; nutze --udp-local-port 0 oder schließe die andere LinSTOP/TNT-Instanz") from exc
            raise Ax25UdpError(str(exc)) from exc
        self.socket = sock

    def is_open(self) -> bool:
        return self.socket is not None

    def close(self) -> None:
        if self.socket is not None:
            self.socket.close()
            self.socket = None

    def send(self, frame: bytes) -> None:
        self.open()
        assert self.socket is not None
        self.socket.send(frame)

    def receive_available(self, limit: int = 20) -> tuple[Ax25UdpPacket, ...]:
        self.open()
        assert self.socket is not None
        packets: list[Ax25UdpPacket] = []
        for _ in range(limit):
            try:
                data = self.socket.recv(4096)
            except TimeoutError:
                break
            except socket.timeout:
                break
            packets.append(Ax25UdpPacket(data=data, address=(self.endpoint.remote_host, self.endpoint.remote_port)))
        return tuple(packets)


def build_ui_frame(source: str, destination: str, text: str, via: tuple[str, ...] = ()) -> bytes:
    frame = encode_ui_frame(source, destination, text.encode("latin-1", errors="replace"), via)
    return encode_ax25ip_datagram(frame)


def build_i_frame(source: str, destination: str, text: str, ns: int, nr: int, via: tuple[str, ...] = ()) -> bytes:
    frame = encode_i_frame(source, destination, text.encode("latin-1", errors="replace"), ns=ns, nr=nr, digipeaters=via)
    return encode_ax25ip_datagram(frame)


def build_rr_frame(source: str, destination: str, nr: int, via: tuple[str, ...] = (), poll_final: bool = False) -> bytes:
    frame = encode_rr_frame(source, destination, nr=nr, digipeaters=via, poll_final=poll_final)
    return encode_ax25ip_datagram(frame)


def build_sabm_frame(source: str, destination: str, via: tuple[str, ...] = ()) -> bytes:
    frame = encode_unnumbered_frame(source, destination, SABM_P, via)
    return encode_ax25ip_datagram(frame)


def build_disc_frame(source: str, destination: str, via: tuple[str, ...] = ()) -> bytes:
    frame = encode_unnumbered_frame(source, destination, DISC_P, via)
    return encode_ax25ip_datagram(frame)


def build_ua_frame(source: str, destination: str, via: tuple[str, ...] = ()) -> bytes:
    frame = encode_ua_frame(source, destination, via)
    return encode_ax25ip_datagram(frame)


def decode_ax25ip_packet(data: bytes):
    return decode_ax25_frame(strip_fcs(data))