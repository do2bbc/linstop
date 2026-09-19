from __future__ import annotations

from datetime import datetime

from .models import ChannelState, StationProfile, UserRecord
from .protocol import connection_start_line
from .remote import apply_user_remote_command
from .transport import Transport
from .variables import TemplateContext, render_template


class LinStopSession:
    def __init__(self, station: StationProfile, transport: Transport, channel_count: int = 10) -> None:
        self.station = station
        self.transport = transport
        self.channels = {number: ChannelState(number=number) for number in range(1, channel_count + 1)}
        self.current_channel = 1
        self.mheard: dict[str, datetime] = {}
        self.info: list[str] = []

    @property
    def channel(self) -> ChannelState:
        return self.channels[self.current_channel]

    def switch_channel(self, number: int) -> ChannelState:
        if number not in self.channels:
            raise ValueError(f"unknown channel {number}")
        self.current_channel = number
        return self.channel

    def first_free_channel(self, exclude: int | None = None) -> int:
        for number, channel in self.channels.items():
            if number != exclude and not channel.connected:
                return number
        for number, channel in self.channels.items():
            if not channel.connected:
                return number
        return self.current_channel

    def connect_incoming(self, peer_call: str, now: datetime | None = None) -> ChannelState:
        connected_at = now or datetime.now()
        self.switch_channel(self.first_free_channel(exclude=self.current_channel))
        self.channel.connect(peer_call, connected_at)
        self.mheard[peer_call.upper()] = connected_at
        return self.channel

    def connect(self, peer_call: str, user: UserRecord | None = None, via: list[str] | None = None, send_start_line: bool = False) -> str:
        via = via or []
        now = datetime.now()
        self.transport.connect(peer_call, via)
        self.channel.connect(peer_call, now)
        self.mheard[peer_call.upper()] = now
        start_line = connection_start_line(self.channel.kind, "0.1.0", knows_name=bool(user and user.name))
        if send_start_line:
            self.transport.send_line(start_line)
            self.channel.append_tx(start_line)
        return start_line

    def disconnect(self) -> None:
        self.transport.disconnect()
        self.channel.disconnect()

    def send_template(self, template: str, user: UserRecord | None = None) -> str:
        text = render_template(template, TemplateContext(station=self.station, channel=self.channel, user=user))
        self.transport.send_line(text)
        self.channel.append_tx(text)
        return text

    def handle_remote_user_command(self, text: str, user: UserRecord) -> str | None:
        response = apply_user_remote_command(user, text)
        if response is None:
            return None
        self.transport.send_line(response)
        self.channel.append_tx(response)
        return response

    def receive_line(self, peer_call: str, text: str) -> None:
        now = datetime.now()
        self.mheard[peer_call.upper()] = now
        self.channel.append_rx(text)

    def add_info(self, text: str) -> None:
        self.info.append(text)
        self.channel.append_info(text)
