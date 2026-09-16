from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from .models import ChannelState, StationProfile, UserRecord


_TOKEN_RE = re.compile(r"%(%|H[0-9A-Fa-f]{2}|(?P<align>[-+#])?(?P<width>\d{1,3})?(?P<name>[A-Za-z][A-Za-z0-9]*))")


@dataclass(slots=True)
class TemplateContext:
    station: StationProfile
    channel: ChannelState
    user: UserRecord | None = None
    now: datetime | None = None
    prompt: str = ">"
    program_version: str = "0.1.0"

    def timestamp(self) -> datetime:
        return self.now or datetime.now()


def render_template(template: str, context: TemplateContext) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(0)[1:]
        if token == "%":
            return "%"
        if token.startswith("H") and len(token) == 3:
            return chr(int(token[1:], 16))

        align = match.group("align") or ""
        width = int(match.group("width") or "0")
        name = match.group("name") or ""
        value = _resolve(name, context)
        return _format(value, align, width)

    return _TOKEN_RE.sub(replace, template)


def _resolve(name: str, context: TemplateContext) -> str:
    station = context.station
    channel = context.channel
    user = context.user or UserRecord(call=channel.peer_call or "")
    now = context.timestamp()

    station_values = {
        "SCC": station.normalized_call(),
        "SCA": station.normalized_call(),
        "SC1": station.user_call_1.upper(),
        "SC2": station.user_call_2.upper(),
        "SCB": station.bbs_call.upper(),
        "SCN": station.node_call.upper(),
        "SCV": station.convers_call.upper(),
        "SN": station.name,
        "SQ": station.qth,
        "ST": station.phone,
        "SL": station.locator,
    }
    user_values = {
        "UN": user.display_name(),
        "Un": user.name or user.call_without_ssid(),
        "UQ": user.qth,
        "UT": user.phone,
        "UL": user.locator,
        "UH": user.home_bbs,
        "UCC": user.call.upper(),
        "UCA": user.call.upper(),
        "UC1": user.call.upper(),
        "UC2": user.call.upper(),
        "UCB": user.home_bbs.upper(),
        "UZ": str(user.connect_count),
        "UcC": user.call_without_ssid(),
        "UcA": user.call_without_ssid(),
        "Uc1": user.call_without_ssid(),
        "Uc2": user.call_without_ssid(),
    }
    time_values = {
        "ZZ": now.strftime("%H:%M"),
        "ZD": now.strftime("%d.%m.%Y"),
        "ZEZH": now.strftime("%H"),
        "ZEZM": now.strftime("%M"),
        "ZEZS": now.strftime("%S"),
        "ZEDW": str(now.isoweekday()),
        "ZEDT": str(now.day),
        "ZEDM": str(now.month),
        "ZEDJ": str(now.year),
        "ZA": now.astimezone().tzname() or "",
        "ZB": now.astimezone().tzname() or "",
    }
    connect_values = {
        "NA": str(channel.connect_count),
        "NK": str(channel.number),
    }
    rest_values = {
        "RP": context.prompt,
        "RV": context.program_version,
        "RZ": "2026-09-16",
    }

    for values in (station_values, user_values, time_values, connect_values, rest_values):
        if name in values:
            return values[name]
    return f"%{name}"


def _format(value: str, align: str, width: int) -> str:
    if width <= 0:
        return value
    if align == "+":
        return value.rjust(width)
    if align == "#":
        return value.center(width)
    return value.ljust(width)
