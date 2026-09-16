from linstop.ax25 import decode_ax25_frame
from linstop.ax25 import strip_fcs
from linstop.ax25udp import Ax25UdpEndpoint, Ax25UdpPacket, build_disc_frame, build_i_frame, build_rr_frame, build_sabm_frame, build_ui_frame
from linstop.transport import Ax25UdpTransport, _decode_qso_payload


def test_build_ax25udp_sabm_frame() -> None:
    frame = decode_ax25_frame(strip_fcs(build_sabm_frame("do2bbc", "igate")))

    assert frame.path() == "DO2BBC>IGATE"
    assert frame.control.name == "SABM"


def test_build_ax25udp_ui_frame() -> None:
    frame = decode_ax25_frame(strip_fcs(build_ui_frame("do2bbc", "igate", "test")))

    assert frame.path() == "DO2BBC>IGATE"
    assert frame.control.name == "UI"
    assert frame.payload == b"test"


def test_build_ax25udp_disc_frame() -> None:
    frame = decode_ax25_frame(strip_fcs(build_disc_frame("do2bbc", "igate")))

    assert frame.path() == "DO2BBC>IGATE"
    assert frame.control.name == "DISC"


def test_ax25udp_transport_has_default_igate_endpoint() -> None:
    transport = Ax25UdpTransport(local_call="do2bbc", endpoint=Ax25UdpEndpoint())

    assert transport.endpoint.remote_host == "44.148.230.93"
    assert transport.endpoint.remote_port == 93
    assert transport.endpoint.local_port == 10093


def test_build_connected_mode_frames() -> None:
    iframe = decode_ax25_frame(strip_fcs(build_i_frame("do2bbc", "igate", "info\r", ns=0, nr=1)))
    rr = decode_ax25_frame(strip_fcs(build_rr_frame("do2bbc", "igate", nr=1, poll_final=True)))

    assert iframe.control.name == "I"
    assert iframe.control.ns == 0
    assert iframe.control.nr == 1
    assert rr.control.name == "RR"
    assert rr.control.nr == 1


def test_ax25udp_transport_returns_pending_connect_lines() -> None:
    transport = Ax25UdpTransport(local_call="do2bbc", endpoint=Ax25UdpEndpoint(local_port=None))
    transport.peer_call = "IGATE"
    transport.socket = None
    transport.pending_monitor_lines.append("IGATE>DO2BBC UA")

    assert transport.receive_monitor_lines() == ("IGATE>DO2BBC UA",)
    transport.pending_monitor_lines.append("IGATE>DO2BBC UA")

    transport.socket = type("FakeSocket", (), {"receive_available": lambda self, limit=20: ()})()
    assert transport.receive_monitor_lines() == ("IGATE>DO2BBC UA",)
    assert transport.receive_monitor_lines() == ()


def test_ax25udp_packet_formats_fcs_datagram() -> None:
    packet = Ax25UdpPacket(data=build_ui_frame("igate", "do2bbc", "hi"), address=("44.148.230.93", 93))

    assert packet.format().endswith("fm IGATE to DO2BBC UI ctl=0x03 PID=0xF0 No layer 3 len=2\n    hi")


def test_decode_qso_payload_splits_packet_radio_lines() -> None:
    lines, pending = _decode_qso_payload(b"Hallo\r\r=>")

    assert lines == ["Hallo", "=>"]
    assert pending == ""


def test_decode_qso_payload_joins_lines_split_across_frames() -> None:
    lines, pending = _decode_qso_payload(b"beeinflusse", "")

    assert lines == []
    assert pending == "beeinflusse"
    lines, pending = _decode_qso_payload(b"n.\r=>", pending)
    assert lines == ["beeinflussen.", "=>"]
    assert pending == ""


def test_handle_i_frame_exposes_payload_for_qso_window() -> None:
    sent: list[bytes] = []

    class FakeSocket:
        def send(self, frame: bytes) -> None:
            sent.append(frame)

        def receive_available(self, limit: int = 20):
            return ()

    packet = Ax25UdpPacket(data=build_i_frame("igate", "do2bbc", "Hallo\r=>", ns=0, nr=0), address=("44.148.230.93", 93))
    transport = Ax25UdpTransport(local_call="do2bbc", endpoint=Ax25UdpEndpoint(local_port=None))
    transport.peer_call = "IGATE"
    transport.socket = FakeSocket()

    monitor_line = transport._handle_packet(packet)

    assert "fm IGATE to DO2BBC I00" in monitor_line
    assert transport.receive_qso_lines() == ("Hallo", "=>")
    assert sent
    assert any("TX fm DO2BBC to IGATE RR1" in line for line in transport.receive_monitor_lines())


def test_handle_disc_replies_with_ua() -> None:
    sent: list[bytes] = []

    class FakeSocket:
        closed = False

        def send(self, frame: bytes) -> None:
            sent.append(frame)

        def receive_available(self, limit: int = 20):
            return ()

        def close(self) -> None:
            self.closed = True

    packet = Ax25UdpPacket(data=build_disc_frame("igate", "do2bbc"), address=("44.148.230.93", 93))
    transport = Ax25UdpTransport(local_call="do2bbc", endpoint=Ax25UdpEndpoint(local_port=None))
    transport.peer_call = "IGATE"
    transport.link_established = True
    transport.socket = FakeSocket()

    monitor_line = transport._handle_packet(packet)

    assert "fm IGATE to DO2BBC DISC" in monitor_line
    assert not transport.link_established
    assert transport.remote_disconnected
    assert transport.socket is None
    assert sent
    assert any("TX fm DO2BBC to IGATE UA" in line for line in transport.receive_monitor_lines())


def test_send_line_adds_tx_i_frame_to_monitor() -> None:
    sent: list[bytes] = []

    class FakeSocket:
        def send(self, frame: bytes) -> None:
            sent.append(frame)

        def receive_available(self, limit: int = 20):
            return ()

    transport = Ax25UdpTransport(local_call="do2bbc", endpoint=Ax25UdpEndpoint(local_port=None))
    transport.peer_call = "IGATE"
    transport.socket = FakeSocket()

    transport.send_line("info")

    assert sent
    monitor_lines = transport.receive_monitor_lines()
    assert any("TX fm DO2BBC to IGATE I00" in line for line in monitor_lines)
    assert any("    info" in line for line in monitor_lines)