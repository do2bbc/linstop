from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class ConnectTarget:
    call: str
    port: str | None = None
    via: tuple[str, ...] = ()


def parse_connect_target(text: str) -> ConnectTarget:
    parts = text.split()
    if not parts:
        raise ValueError("empty connect target")

    first = parts[0]
    port: str | None = None
    call = first
    if ":" in first:
        port, call = first.split(":", 1)
        if not port or not call:
            raise ValueError(f"invalid connect target {text!r}")

    return ConnectTarget(call=call.upper(), port=port.upper() if port else None, via=tuple(item.upper() for item in parts[1:]))