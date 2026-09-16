from __future__ import annotations

from .models import ChannelKind


def connection_start_line(kind: ChannelKind, version: str, umlaut_mode: int = 3, knows_name: bool = False) -> str:
    flags = "D"
    if not knows_name:
        flags += "?"

    if kind is ChannelKind.BBS:
        return f"[LinSTOPBox-{version}-{flags}]"
    if kind is ChannelKind.NODE:
        return f"{{LinSTOPNode-{version}-{umlaut_mode}{flags}}}"
    if kind is ChannelKind.CONVERS:
        return f"{{LinSTOPConv-{version}-{umlaut_mode}{flags}}}"
    return f"{{LinSTOP-{version}-{umlaut_mode}{flags}}}"
