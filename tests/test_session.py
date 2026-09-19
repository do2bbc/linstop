from linstop.models import StationProfile
from linstop.models import UserRecord
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


def test_remote_user_command_updates_user_database_and_replies() -> None:
    transport = LoopbackTransport()
    session = LinStopSession(StationProfile(call="do2bbc"), transport)
    user = UserRecord(call="dbw400")

    response = session.handle_remote_user_command("//QTH Ottenstein", user)

    assert user.qth == "Ottenstein"
    assert response == "QTH: gespeichert."
    assert transport.sent == ["QTH: gespeichert."]
    assert session.channel.events[-1].text == "QTH: gespeichert."


def test_info_is_text_remote_command_not_user_database_alias() -> None:
    transport = LoopbackTransport()
    session = LinStopSession(StationProfile(call="do2bbc"), transport)
    user = UserRecord(call="dbw400", station_info="Beschreibung")

    response = session.handle_remote_user_command("//INFO", user)

    assert response is None
    assert transport.sent == []


def test_incoming_connect_uses_new_free_channel() -> None:
    session = LinStopSession(StationProfile(call="do2bbc"), LoopbackTransport())
    session.connect("elbe")

    channel = session.connect_incoming("igate")

    assert channel.number == 2
    assert channel.peer_call == "IGATE"
    assert session.current_channel == 2
    assert session.channels[1].peer_call == "ELBE"


def test_channels_keep_separate_input_buffers() -> None:
    session = LinStopSession(StationProfile(call="do2bbc"), LoopbackTransport())

    session.channel.input_text = "Text fuer Kanal 1"
    session.switch_channel(2)
    session.channel.input_text = "Text fuer Kanal 2"

    assert session.channels[1].input_text == "Text fuer Kanal 1"
    assert session.channels[2].input_text == "Text fuer Kanal 2"
