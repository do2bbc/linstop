from linstop.models import StationProfile
from linstop.session import LinStopSession
from linstop.transport import Ax25CommandTransport, LoopbackTransport


def test_connect_sends_connect_command_and_start_line() -> None:
    transport = LoopbackTransport()
    session = LinStopSession(StationProfile(call="do2bbc"), transport)

    start_line = session.connect("dbw400", via=["db0abc"], send_start_line=True)

    assert start_line == "{LinSTOP-0.1.0-3D?}"
    assert transport.sent == ["CONNECT DBW400 DB0ABC", "{LinSTOP-0.1.0-3D?}"]
    assert session.channel.connected
    assert "DBW400" in session.mheard


def test_outgoing_connect_does_not_send_start_line_by_default() -> None:
    transport = LoopbackTransport()
    session = LinStopSession(StationProfile(call="do2bbc"), transport)

    start_line = session.connect("dbw400")

    assert start_line == "{LinSTOP-0.1.0-3D?}"
    assert transport.sent == ["CONNECT DBW400"]


def test_ax25_command_builder_uses_native_axcall_shape() -> None:
    command = Ax25CommandTransport.build_command("/usr/bin/ax25_call", "P3", "do2bbc-3", "dbw400", ["db0abc", "db0xyz"])

    assert command == ["/usr/bin/ax25_call", "P3", "DO2BBC-3", "DBW400", "DB0ABC", "DB0XYZ"]
