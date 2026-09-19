from linstop.ax25 import decode_ax25_frame
from linstop.ax25 import encode_ax25ip_datagram
from linstop.ax25 import encode_i_frame
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


def test_decode_qso_payload_exposes_each_frame_without_prompt_heuristic() -> None:
    lines, pending = _decode_qso_payload(b"beeinflusse", "")

    assert lines == ["beeinflusse"]
    assert pending == ""
    lines, pending = _decode_qso_payload(b"n.\r=>", pending)
    assert lines == ["n.", "=>"]
    assert pending == ""


def test_decode_qso_payload_exposes_custom_prompt_without_carriage_return() -> None:
    lines, pending = _decode_qso_payload(b"sysop$ ")

    assert lines == ["sysop$ "]
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
    transport.socket = FakeSocket()
    transport._handle_packet(Ax25UdpPacket(data=build_sabm_frame("igate", "do2bbc"), address=("44.148.230.93", 93)))
    sent.clear()

    monitor_line = transport._handle_packet(packet)

    assert "fm IGATE to DO2BBC I00" in monitor_line
    assert transport.receive_qso_lines() == ("Hallo", "=>")
    assert sent
    assert any("TX fm DO2BBC to IGATE RR1" in line for line in transport.receive_monitor_lines())


def test_handle_final_i_frame_flushes_unterminated_qso_text() -> None:
    sent: list[bytes] = []

    class FakeSocket:
        def send(self, frame: bytes) -> None:
            sent.append(frame)

        def receive_available(self, limit: int = 20):
            return ()

    frame = encode_i_frame("igate", "do2bbc", b"Letzte Node-Zeile", ns=0, nr=0, poll=True)
    packet = Ax25UdpPacket(data=encode_ax25ip_datagram(frame), address=("44.148.230.93", 93))
    transport = Ax25UdpTransport(local_call="do2bbc", endpoint=Ax25UdpEndpoint(local_port=None))
    transport.socket = FakeSocket()
    transport._handle_packet(Ax25UdpPacket(data=build_sabm_frame("igate", "do2bbc"), address=("44.148.230.93", 93)))
    sent.clear()

    transport._handle_packet(packet)

    assert transport.receive_qso_lines() == ("Letzte Node-Zeile",)
    assert sent


def test_handle_incoming_sabm_replies_with_ua_and_establishes_link() -> None:
    sent: list[bytes] = []

    class FakeSocket:
        def send(self, frame: bytes) -> None:
            sent.append(frame)

        def receive_available(self, limit: int = 20):
            return ()

    packet = Ax25UdpPacket(data=build_sabm_frame("igate", "do2bbc"), address=("44.148.230.93", 93))
    transport = Ax25UdpTransport(local_call="do2bbc", endpoint=Ax25UdpEndpoint(local_port=None))
    transport.socket = FakeSocket()

    monitor_line = transport._handle_packet(packet)

    assert "fm IGATE to DO2BBC SABM PF" in monitor_line
    assert transport.peer_call == "IGATE"
    assert transport.link_established
    assert sent
    assert decode_ax25_frame(strip_fcs(sent[0])).control.name == "UA"
    assert any("TX fm DO2BBC to IGATE UA PF" in line for line in transport.receive_monitor_lines())


def test_ax25udp_transport_keeps_parallel_links_separate() -> None:
    sent: list[bytes] = []

    class FakeSocket:
        def send(self, frame: bytes) -> None:
            sent.append(frame)

        def receive_available(self, limit: int = 20):
            return ()

    transport = Ax25UdpTransport(local_call="do2bbc", endpoint=Ax25UdpEndpoint(local_port=None))
    transport.socket = FakeSocket()

    transport._handle_packet(Ax25UdpPacket(data=build_sabm_frame("elbe", "do2bbc"), address=("44.148.230.93", 93)))
    transport._handle_packet(Ax25UdpPacket(data=build_sabm_frame("igate", "do2bbc"), address=("44.148.230.93", 93)))
    assert transport.receive_connected_peers() == ("ELBE", "IGATE")

    transport._handle_packet(Ax25UdpPacket(data=build_i_frame("elbe", "do2bbc", "ELBE text\r", ns=0, nr=0), address=("44.148.230.93", 93)))
    transport._handle_packet(Ax25UdpPacket(data=build_i_frame("igate", "do2bbc", "IGATE text\r", ns=0, nr=0), address=("44.148.230.93", 93)))

    assert transport.receive_qso_events() == (("ELBE", "ELBE text"), ("IGATE", "IGATE text"))

    sent.clear()
    transport.select_peer("ELBE")
    transport.send_line("reply")

    frame = decode_ax25_frame(strip_fcs(sent[-1]))
    assert frame.path() == "DO2BBC>ELBE"
    assert frame.payload == b"reply\r"


def test_ax25udp_transport_ignores_reflected_own_i_frames() -> None:
    sent: list[bytes] = []

    class FakeSocket:
        def send(self, frame: bytes) -> None:
            sent.append(frame)

        def receive_available(self, limit: int = 20):
            return ()

    transport = Ax25UdpTransport(local_call="do2bbc", endpoint=Ax25UdpEndpoint(local_port=None))
    transport.socket = FakeSocket()
    transport._handle_packet(Ax25UdpPacket(data=build_sabm_frame("igate", "do2bbc"), address=("44.148.230.93", 93)))
    sent.clear()

    monitor_line = transport._handle_packet(Ax25UdpPacket(data=build_i_frame("do2bbc", "do2bbc", "//i\r", ns=0, nr=0, via=("igate",)), address=("44.148.230.93", 93)))

    assert "fm DO2BBC to DO2BBC via IGATE" in monitor_line
    assert transport.receive_qso_events() == ()
    assert sent == []


def test_disconnect_all_sends_disc_for_every_open_link_and_closes_socket() -> None:
    sent: list[bytes] = []

    class FakeSocket:
        closed = False

        def send(self, frame: bytes) -> None:
            sent.append(frame)

        def receive_available(self, limit: int = 20):
            return ()

        def is_open(self) -> bool:
            return not self.closed

        def close(self) -> None:
            self.closed = True

    socket = FakeSocket()
    transport = Ax25UdpTransport(local_call="do2bbc", endpoint=Ax25UdpEndpoint(local_port=None))
    transport.socket = socket
    transport._handle_packet(Ax25UdpPacket(data=build_sabm_frame("elbe", "do2bbc"), address=("44.148.230.93", 93)))
    transport._handle_packet(Ax25UdpPacket(data=build_sabm_frame("igate", "do2bbc"), address=("44.148.230.93", 93)))
    sent.clear()

    transport.disconnect_all()

    paths = {decode_ax25_frame(strip_fcs(frame)).path() for frame in sent}
    controls = [decode_ax25_frame(strip_fcs(frame)).control.name for frame in sent]
    assert paths == {"DO2BBC>ELBE", "DO2BBC>IGATE"}
    assert controls == ["DISC", "DISC"]
    assert socket.closed
    assert transport.socket is None
    assert transport.links == {}


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
    transport.socket = FakeSocket()
    transport._handle_packet(Ax25UdpPacket(data=build_sabm_frame("igate", "do2bbc"), address=("44.148.230.93", 93)))
    sent.clear()

    monitor_line = transport._handle_packet(packet)

    assert "fm IGATE to DO2BBC DISC" in monitor_line
    assert not transport.link_established
    assert transport.remote_disconnected
    assert transport.socket is not None
    assert transport.receive_disconnected_peers() == ("IGATE",)
    assert sent
    assert any("TX fm DO2BBC to IGATE UA" in line for line in transport.receive_monitor_lines())


def test_handle_unknown_disc_replies_with_dm() -> None:
    sent: list[bytes] = []

    class FakeSocket:
        def send(self, frame: bytes) -> None:
            sent.append(frame)

        def receive_available(self, limit: int = 20):
            return ()

    packet = Ax25UdpPacket(data=build_disc_frame("igate", "do2bbc"), address=("44.148.230.93", 93))
    transport = Ax25UdpTransport(local_call="do2bbc", endpoint=Ax25UdpEndpoint(local_port=None))
    transport.socket = FakeSocket()

    monitor_line = transport._handle_packet(packet)

    assert "fm IGATE to DO2BBC DISC" in monitor_line
    assert sent
    response = decode_ax25_frame(strip_fcs(sent[0]))
    assert response.path() == "DO2BBC>IGATE"
    assert response.control.name == "DM"
    assert not response.control.poll_final
    assert transport.receive_disconnected_peers() == ()


def test_handle_polled_rr_after_local_disconnect_replies_with_dm() -> None:
    sent: list[bytes] = []

    class FakeSocket:
        def send(self, frame: bytes) -> None:
            sent.append(frame)

        def receive_available(self, limit: int = 20):
            return ()

        def is_open(self) -> bool:
            return True

    transport = Ax25UdpTransport(local_call="do2bbc", endpoint=Ax25UdpEndpoint(local_port=None))
    transport.socket = FakeSocket()
    transport._handle_packet(Ax25UdpPacket(data=build_sabm_frame("igate", "do2bbc"), address=("44.148.230.93", 93)))
    transport.select_peer("IGATE")
    transport.disconnect()
    sent.clear()

    monitor_line = transport._handle_packet(Ax25UdpPacket(data=build_rr_frame("igate", "do2bbc", nr=0, poll_final=True), address=("44.148.230.93", 93)))

    assert "fm IGATE to DO2BBC RR0 PF" in monitor_line
    assert sent
    response = decode_ax25_frame(strip_fcs(sent[0]))
    assert response.path() == "DO2BBC>IGATE"
    assert response.control.name == "DM"
    assert not response.control.poll_final


def test_handle_i_frame_without_link_replies_with_dm() -> None:
    sent: list[bytes] = []

    class FakeSocket:
        def send(self, frame: bytes) -> None:
            sent.append(frame)

        def receive_available(self, limit: int = 20):
            return ()

    transport = Ax25UdpTransport(local_call="do2bbc", endpoint=Ax25UdpEndpoint(local_port=None))
    transport.socket = FakeSocket()

    transport._handle_packet(Ax25UdpPacket(data=build_i_frame("igate", "do2bbc", "stale\r", ns=0, nr=0), address=("44.148.230.93", 93)))

    assert sent
    response = decode_ax25_frame(strip_fcs(sent[0]))
    assert response.control.name == "DM"
    assert transport.receive_qso_events() == ()


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