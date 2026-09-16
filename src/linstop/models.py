from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ChannelKind(str, Enum):
    USER = "user"
    BBS = "bbs"
    NODE = "node"
    CONVERS = "convers"


@dataclass(slots=True)
class StationProfile:
    call: str
    name: str = ""
    qth: str = ""
    qra: str = ""
    locator: str = ""
    phone: str = ""
    email: str = ""
    homepage: str = ""
    club: str = ""
    operator_class: str = ""
    bbs_call: str = ""
    node_call: str = ""
    convers_call: str = ""
    user_call_1: str = ""
    user_call_2: str = ""

    def normalized_call(self) -> str:
        return self.call.upper()


@dataclass(slots=True)
class PortConfig:
    name: str
    transport: str = "ax25udp"
    description: str = ""
    default_target: str = "IGATE"
    local_call: str = ""
    ax25_port: str = "P3"
    udp_remote_host: str = "44.148.230.93"
    udp_remote_port: int = 93
    udp_local_port: int | None = 10093
    enabled: bool = True


@dataclass(slots=True)
class LinStopConfig:
    station: StationProfile = field(default_factory=lambda: StationProfile(call="DO2BBC"))
    ports: list[PortConfig] = field(default_factory=list)
    active_port: str = "igate-axudp"

    def ensure_defaults(self) -> None:
        if not self.station.call:
            self.station.call = "DO2BBC"
        if not self.ports:
            self.ports.append(
                PortConfig(
                    name="igate-axudp",
                    description="IGATE AX25UDP 44.148.230.93:93",
                    local_call=self.station.normalized_call(),
                )
            )
        if not self.active_port:
            self.active_port = self.ports[0].name

    def get_active_port(self) -> PortConfig:
        self.ensure_defaults()
        for port in self.ports:
            if port.name == self.active_port:
                return port
        return self.ports[0]


@dataclass(slots=True)
class UserRecord:
    call: str
    name: str = ""
    qth: str = ""
    locator: str = ""
    phone: str = ""
    home_bbs: str = ""
    connect_count: int = 0
    last_connected_at: datetime | None = None
    remote_allowed: bool = False

    def display_name(self) -> str:
        return self.name or self.call.upper()

    def call_without_ssid(self) -> str:
        return self.call.split("-", 1)[0].upper()


@dataclass(slots=True)
class QsoEvent:
    direction: str
    text: str
    at: datetime = field(default_factory=datetime.now)


@dataclass(slots=True)
class ChannelState:
    number: int
    kind: ChannelKind = ChannelKind.USER
    peer_call: str = ""
    connected_at: datetime | None = None
    connect_count: int = 0
    events: list[QsoEvent] = field(default_factory=list)

    @property
    def connected(self) -> bool:
        return self.connected_at is not None

    def connect(self, peer_call: str, now: datetime | None = None) -> None:
        self.peer_call = peer_call.upper()
        self.connected_at = now or datetime.now()
        self.connect_count += 1
        self.events.append(QsoEvent("info", f"*** Connected to {self.peer_call}"))

    def disconnect(self) -> None:
        if self.peer_call:
            self.events.append(QsoEvent("info", f"*** Disconnected from {self.peer_call}"))
        self.peer_call = ""
        self.connected_at = None

    def append_rx(self, text: str) -> None:
        self.events.append(QsoEvent("rx", text))

    def append_tx(self, text: str) -> None:
        self.events.append(QsoEvent("tx", text))

    def append_info(self, text: str) -> None:
        self.events.append(QsoEvent("info", text))
