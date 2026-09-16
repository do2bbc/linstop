from linstop.ax25 import compute_fcs, decode_ax25_frame, decode_kiss_frame, encode_ax25ip_datagram, encode_i_frame, encode_rr_frame, encode_ui_frame, encode_unnumbered_frame, format_ax25_frame, format_ax25ip_datagram, format_kiss_frame, parse_hex_bytes, strip_fcs, _indent_info_payload


REFERENCE_UI_FRAME = parse_hex_bytes(
    "9c 94 6e a0 40 40 e0 9c 6e 98 8a 9a 40 61 03 f0 "
    "54 68 65 20 71 75 69 63 6b 20 62 72 6f 77 6e 20 "
    "66 6f 78 20 6a 75 6d 70 73 20 6f 76 65 72 20 74 "
    "68 65 20 6c 61 7a 79 20 64 6f 67"
)


def test_decode_reference_ui_frame() -> None:
    frame = decode_ax25_frame(REFERENCE_UI_FRAME)

    assert frame.destination.label() == "NJ7P"
    assert frame.source.label() == "N7LEM"
    assert frame.control.name == "UI"
    assert frame.control.raw == 0x03
    assert frame.pid == 0xF0
    assert frame.payload == b"The quick brown fox jumps over the lazy dog"


def test_format_reference_ui_frame() -> None:
    formatted = format_ax25_frame(REFERENCE_UI_FRAME, port="P3", direction="RX")

    assert formatted == "P3 RX fm N7LEM to NJ7P UI ctl=0x03 PID=0xF0 No layer 3 len=43\n    The quick brown fox jumps over the lazy dog"


def test_encode_ui_frame_roundtrip_with_digipeater() -> None:
    encoded = encode_ui_frame("do2bbc-3", "dbw400", b"Hallo", ("db0abc-1",))
    frame = decode_ax25_frame(encoded)

    assert frame.path() == "DO2BBC-3>DBW400,DB0ABC-1"
    assert frame.destination.command_response
    assert not frame.source.command_response
    assert frame.control.name == "UI"
    assert frame.pid == 0xF0
    assert frame.payload == b"Hallo"


def test_decode_kiss_data_frame() -> None:
    kiss = bytes([0xC0, 0x20]) + REFERENCE_UI_FRAME + bytes([0xC0])
    frame = decode_kiss_frame(kiss)

    assert frame.port == 2
    assert frame.command == 0
    assert format_kiss_frame(kiss).startswith("kiss2 fm N7LEM to NJ7P UI ctl=0x03")


def test_encode_sabm_probe_frame() -> None:
    encoded = encode_unnumbered_frame("do2bbc", "igate", 0x3F)
    frame = decode_ax25_frame(encoded)

    assert frame.path() == "DO2BBC>IGATE"
    assert frame.control.name == "SABM"
    assert frame.control.poll_final


def test_ax25ip_fcs_roundtrip() -> None:
    datagram = encode_ax25ip_datagram(REFERENCE_UI_FRAME)

    assert compute_fcs(REFERENCE_UI_FRAME) == datagram[-2:]
    assert strip_fcs(datagram) == REFERENCE_UI_FRAME
    assert format_ax25ip_datagram(datagram, port="udp93", direction="RX").startswith("udp93 RX fm N7LEM to NJ7P UI")


def test_encode_i_and_rr_frames() -> None:
    iframe = decode_ax25_frame(encode_i_frame("do2bbc", "igate", b"info\r", ns=0, nr=1))
    rr = decode_ax25_frame(encode_rr_frame("do2bbc", "igate", nr=1, poll_final=True))

    assert iframe.path() == "DO2BBC>IGATE"
    assert iframe.control.name == "I"
    assert iframe.control.ns == 0
    assert iframe.control.nr == 1
    assert iframe.payload == b"info\r"
    assert rr.path() == "DO2BBC>IGATE"
    assert rr.control.name == "RR"
    assert rr.control.nr == 1
    assert rr.control.poll_final


def test_format_i_frame_uses_compact_control_numbers() -> None:
    encoded = encode_i_frame("igate", "do2bbc", b"Hallo", ns=0, nr=1)

    assert format_ax25_frame(encoded) == "fm IGATE to DO2BBC I01 ctl=0x20 PID=0xF0 No layer 3 len=5\n    Hallo"


def test_indent_info_payload_wraps_after_80_characters() -> None:
    wrapped = _indent_info_payload(b"A" * 81)

    assert wrapped == "    " + ("A" * 80) + "\n    A"


def test_indent_info_payload_uses_carriage_return_as_line_break() -> None:
    assert _indent_info_payload(b"info\r=>") == "    info\n    =>"