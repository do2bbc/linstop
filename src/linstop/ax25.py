from __future__ import annotations

from dataclasses import dataclass


class Ax25DecodeError(ValueError):
    pass


class Ax25FcsError(Ax25DecodeError):
    pass


@dataclass(slots=True, frozen=True)
class Ax25Address:
    call: str
    ssid: int = 0
    command_response: bool = False
    repeated: bool = False
    last: bool = False

    def label(self) -> str:
        suffix = f"-{self.ssid}" if self.ssid else ""
        repeated = "*" if self.repeated else ""
        return f"{self.call}{suffix}{repeated}"


@dataclass(slots=True, frozen=True)
class Ax25Control:
    raw: int
    family: str
    name: str
    poll_final: bool = False
    ns: int | None = None
    nr: int | None = None

    def label(self) -> str:
        parts = [self.name]
        if self.ns is not None:
            parts.append(f"N(S)={self.ns}")
        if self.nr is not None:
            parts.append(f"N(R)={self.nr}")
        if self.poll_final:
            parts.append("P/F")
        return " ".join(parts)


@dataclass(slots=True, frozen=True)
class Ax25Frame:
    destination: Ax25Address
    source: Ax25Address
    digipeaters: tuple[Ax25Address, ...]
    control: Ax25Control
    pid: int | None
    payload: bytes

    def path(self) -> str:
        via = ",".join(address.label() for address in self.digipeaters)
        base = f"{self.source.label()}>{self.destination.label()}"
        return f"{base},{via}" if via else base


@dataclass(slots=True, frozen=True)
class KissFrame:
    port: int
    command: int
    payload: bytes


PID_NAMES = {
    0x01: "ISO 8208 / X.25 PLP",
    0x06: "Compressed TCP/IP",
    0x07: "Uncompressed TCP/IP",
    0x08: "Segmentation fragment",
    0xCC: "IPv4",
    0xCD: "ARP",
    0xCF: "NET/ROM",
    0xF0: "No layer 3",
    0xFF: "Escape",
}

U_FRAME_NAMES = {
    0x03: "UI",
    0x0F: "DM",
    0x2F: "SABM",
    0x43: "DISC",
    0x63: "UA",
    0x87: "FRMR",
    0xAF: "XID",
    0xE3: "TEST",
}

S_FRAME_NAMES = {
    0: "RR",
    1: "RNR",
    2: "REJ",
    3: "SREJ",
}


def decode_ax25_frame(data: bytes) -> Ax25Frame:
    addresses, offset = _decode_addresses(data)
    if len(addresses) < 2:
        raise Ax25DecodeError("AX.25 frame needs destination and source address")
    if offset >= len(data):
        raise Ax25DecodeError("AX.25 frame has no control field")

    control = decode_control(data[offset])
    offset += 1
    pid: int | None = None
    if _has_pid(control):
        if offset >= len(data):
            raise Ax25DecodeError("AX.25 I/UI frame has no PID field")
        pid = data[offset]
        offset += 1

    return Ax25Frame(
        destination=addresses[0],
        source=addresses[1],
        digipeaters=tuple(addresses[2:]),
        control=control,
        pid=pid,
        payload=data[offset:],
    )


def decode_control(control: int) -> Ax25Control:
    poll_final = bool(control & 0x10)
    if control & 0x01 == 0:
        return Ax25Control(
            raw=control,
            family="I",
            name="I",
            poll_final=poll_final,
            ns=(control >> 1) & 0x07,
            nr=(control >> 5) & 0x07,
        )
    if control & 0x03 == 0x01:
        code = (control >> 2) & 0x03
        return Ax25Control(
            raw=control,
            family="S",
            name=S_FRAME_NAMES.get(code, f"S{code}"),
            poll_final=poll_final,
            nr=(control >> 5) & 0x07,
        )
    masked = control & 0xEF
    return Ax25Control(
        raw=control,
        family="U",
        name=U_FRAME_NAMES.get(masked, f"U 0x{control:02X}"),
        poll_final=poll_final,
    )


def format_ax25_frame(data: bytes, port: str | None = None, direction: str | None = None) -> str:
    frame = decode_ax25_frame(data)
    prefix = " ".join(part for part in (port, direction) if part)
    pid = f" PID=0x{frame.pid:02X} {PID_NAMES.get(frame.pid, 'Unknown')}" if frame.pid is not None else ""
    payload = format_payload(frame.payload)
    header = _format_monitor_header(frame, pid)
    line = f"{prefix} {header}".strip()
    if payload and (frame.control.family == "I" or frame.control.name == "UI"):
        return f"{line}\n{_indent_info_payload(frame.payload)}"
    if payload:
        return f"{line} | {payload}"
    return f"{line} |"


def _indent_info_payload(payload: bytes, width: int = 80) -> str:
    lines: list[str] = []
    text = payload.decode("latin-1", errors="replace")
    text = text.replace("\r\n", "\r").replace("\n", "\r")
    for logical_line in text.split("\r"):
        if not logical_line:
            continue
        while len(logical_line) > width:
            lines.append("    " + logical_line[:width])
            logical_line = logical_line[width:]
        lines.append("    " + logical_line)
    if not lines:
        lines.append("    ")
    return "\n".join(lines)


def _format_monitor_header(frame: Ax25Frame, pid: str) -> str:
    source = frame.source.label()
    destination = frame.destination.label()
    via = ""
    if frame.digipeaters:
        via = " via " + ",".join(address.label() for address in frame.digipeaters)
    control = frame.control.name
    if frame.control.family == "I" and frame.control.ns is not None and frame.control.nr is not None:
        control = f"I{frame.control.ns}{frame.control.nr}"
    elif frame.control.name == "RR" and frame.control.nr is not None:
        control = f"RR{frame.control.nr}"
    elif frame.control.name in {"RNR", "REJ", "SREJ"} and frame.control.nr is not None:
        control = f"{frame.control.name}{frame.control.nr}"
    if frame.control.poll_final:
        control += " PF"
    return f"fm {source} to {destination}{via} {control} ctl=0x{frame.control.raw:02X}{pid} len={len(frame.payload)}"


def format_ax25ip_datagram(data: bytes, port: str | None = None, direction: str | None = None) -> str:
    return format_ax25_frame(strip_fcs(data), port=port, direction=direction)


def format_payload(payload: bytes) -> str:
    if not payload:
        return ""
    text = payload.decode("latin-1", errors="replace")
    result: list[str] = []
    for char in text:
        code = ord(char)
        if char == "\r":
            result.append("\\r")
        elif char == "\n":
            result.append("\\n")
        elif char == "\t":
            result.append("\\t")
        elif 32 <= code <= 126 or 160 <= code <= 255:
            result.append(char)
        else:
            result.append(f"\\x{code:02X}")
    return "".join(result)


def decode_kiss_frame(data: bytes) -> KissFrame:
    if len(data) < 3 or data[0] != 0xC0 or data[-1] != 0xC0:
        raise Ax25DecodeError("KISS frame must start and end with FEND 0xC0")
    body = _kiss_unescape(data[1:-1])
    if not body:
        raise Ax25DecodeError("empty KISS frame")
    command = body[0]
    return KissFrame(port=(command >> 4) & 0x0F, command=command & 0x0F, payload=body[1:])


def format_kiss_frame(data: bytes) -> str:
    frame = decode_kiss_frame(data)
    if frame.command == 0x00:
        return format_ax25_frame(frame.payload, port=f"kiss{frame.port}")
    return f"kiss{frame.port} KISS command=0x{frame.command:02X} len={len(frame.payload)} | {frame.payload.hex(' ')}"


def parse_hex_bytes(text: str) -> bytes:
    cleaned = text.replace("0x", " ").replace("0X", " ")
    for separator in (",", ":", "-", "\n", "\t"):
        cleaned = cleaned.replace(separator, " ")
    parts = [part for part in cleaned.split(" ") if part]
    try:
        return bytes(int(part, 16) for part in parts)
    except ValueError as exc:
        raise Ax25DecodeError(f"invalid hex byte list: {text!r}") from exc


def encode_ui_frame(source: str, destination: str, payload: bytes, digipeaters: tuple[str, ...] = (), pid: int = 0xF0) -> bytes:
    encoded = _encode_address(destination, last=False, command_response=True)
    encoded += _encode_address(source, last=not digipeaters, command_response=False)
    encoded += b"".join(_encode_address(address, last=index == len(digipeaters) - 1, command_response=False) for index, address in enumerate(digipeaters))
    return encoded + bytes((0x03, pid)) + payload


def encode_i_frame(source: str, destination: str, payload: bytes, ns: int, nr: int, digipeaters: tuple[str, ...] = (), pid: int = 0xF0, poll: bool = False) -> bytes:
    encoded = _encode_address(destination, last=False, command_response=True)
    encoded += _encode_address(source, last=not digipeaters, command_response=False)
    encoded += b"".join(_encode_address(address, last=index == len(digipeaters) - 1, command_response=False) for index, address in enumerate(digipeaters))
    control = ((nr & 0x07) << 5) | (0x10 if poll else 0) | ((ns & 0x07) << 1)
    return encoded + bytes((control, pid)) + payload


def encode_rr_frame(source: str, destination: str, nr: int, digipeaters: tuple[str, ...] = (), poll_final: bool = False) -> bytes:
    encoded = _encode_address(destination, last=False, command_response=False)
    encoded += _encode_address(source, last=not digipeaters, command_response=True)
    encoded += b"".join(_encode_address(address, last=index == len(digipeaters) - 1, command_response=False) for index, address in enumerate(digipeaters))
    control = ((nr & 0x07) << 5) | (0x10 if poll_final else 0) | 0x01
    return encoded + bytes((control,))


def encode_ax25ip_datagram(frame: bytes) -> bytes:
    return frame + compute_fcs(frame)


def strip_fcs(data: bytes) -> bytes:
    if len(data) < 3:
        raise Ax25FcsError("AXIP datagram too short for FCS")
    frame = data[:-2]
    expected = compute_fcs(frame)
    actual = data[-2:]
    if actual != expected:
        raise Ax25FcsError(f"AX.25 FCS mismatch: got {actual.hex(' ')}, expected {expected.hex(' ')}")
    return frame


def compute_fcs(data: bytes) -> bytes:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0x8408
            else:
                crc >>= 1
            crc &= 0xFFFF
    crc ^= 0xFFFF
    return bytes((crc & 0xFF, (crc >> 8) & 0xFF))


def encode_unnumbered_frame(source: str, destination: str, control: int, digipeaters: tuple[str, ...] = ()) -> bytes:
    encoded = _encode_address(destination, last=False, command_response=True)
    encoded += _encode_address(source, last=not digipeaters, command_response=False)
    encoded += b"".join(_encode_address(address, last=index == len(digipeaters) - 1, command_response=False) for index, address in enumerate(digipeaters))
    return encoded + bytes((control,))


def encode_ua_frame(source: str, destination: str, digipeaters: tuple[str, ...] = ()) -> bytes:
    encoded = _encode_address(destination, last=False, command_response=False)
    encoded += _encode_address(source, last=not digipeaters, command_response=True)
    encoded += b"".join(_encode_address(address, last=index == len(digipeaters) - 1, command_response=False) for index, address in enumerate(digipeaters))
    return encoded + bytes((0x73,))


def _decode_addresses(data: bytes) -> tuple[list[Ax25Address], int]:
    addresses: list[Ax25Address] = []
    offset = 0
    while True:
        if offset + 7 > len(data):
            raise Ax25DecodeError("truncated AX.25 address field")
        block = data[offset : offset + 7]
        offset += 7
        call = "".join(chr(byte >> 1) for byte in block[:6]).rstrip()
        ssid_byte = block[6]
        addresses.append(
            Ax25Address(
                call=call,
                ssid=(ssid_byte >> 1) & 0x0F,
                command_response=bool(ssid_byte & 0x80),
                repeated=bool(ssid_byte & 0x80) and len(addresses) >= 2,
                last=bool(ssid_byte & 0x01),
            )
        )
        if ssid_byte & 0x01:
            return addresses, offset
        if len(addresses) > 10:
            raise Ax25DecodeError("too many AX.25 address fields")


def _encode_address(call_with_ssid: str, last: bool, command_response: bool) -> bytes:
    call, ssid = _split_call(call_with_ssid)
    call_bytes = call.upper().ljust(6)[:6].encode("ascii")
    ssid_byte = 0x60 | ((ssid & 0x0F) << 1) | (0x01 if last else 0x00)
    if command_response:
        ssid_byte |= 0x80
    return bytes(byte << 1 for byte in call_bytes) + bytes((ssid_byte,))


def _split_call(call_with_ssid: str) -> tuple[str, int]:
    if "-" not in call_with_ssid:
        return call_with_ssid, 0
    call, ssid_text = call_with_ssid.rsplit("-", 1)
    return call, int(ssid_text)


def _has_pid(control: Ax25Control) -> bool:
    return control.family == "I" or control.name == "UI"


def _kiss_unescape(data: bytes) -> bytes:
    output = bytearray()
    index = 0
    while index < len(data):
        byte = data[index]
        if byte == 0xDB:
            index += 1
            if index >= len(data):
                raise Ax25DecodeError("truncated KISS escape")
            escaped = data[index]
            if escaped == 0xDC:
                output.append(0xC0)
            elif escaped == 0xDD:
                output.append(0xDB)
            else:
                raise Ax25DecodeError(f"invalid KISS escape 0x{escaped:02X}")
        else:
            output.append(byte)
        index += 1
    return bytes(output)