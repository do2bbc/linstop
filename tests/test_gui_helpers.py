from linstop.gui import channel_button_label, connect_text_lines, connected_status_call, echo_line_key, line_from_editor_text, next_editor_line_after_send, remote_echo_key, text_remote_command


def test_connected_status_call_extracts_connected_peer() -> None:
    assert connected_status_call("*** connected to DO2BBC") == "DO2BBC"


def test_connected_status_call_extracts_reconnected_peer() -> None:
    assert connected_status_call("*** reconnected to IGATE") == "IGATE"


def test_connected_status_call_ignores_other_lines() -> None:
    assert connected_status_call("Hallo IGATE") is None


def test_channel_button_label_shows_number_when_empty() -> None:
    assert channel_button_label(1, "") == "1"


def test_channel_button_label_shows_peer_when_connected() -> None:
    assert channel_button_label(1, "IGATE") == "1: IGATE"


def test_connect_text_lines_splits_cr_and_lf() -> None:
    assert connect_text_lines("Hallo\nWillkommen\r73") == ["Hallo", "Willkommen", "73"]


def test_text_remote_command_detects_info_and_quit() -> None:
    assert text_remote_command("//i") == "info"
    assert text_remote_command("//INFO") == "info"
    assert text_remote_command("//q") == "quit"
    assert text_remote_command("//bye") == "quit"
    assert text_remote_command("//qth Ottenstein") is None


def test_remote_echo_key_normalizes_remote_command() -> None:
    assert remote_echo_key("  //i  ") == "//I"
    assert remote_echo_key("//qth   Ottenstein") == "//QTH OTTENSTEIN"
    assert remote_echo_key("hallo") is None


def test_echo_line_key_normalizes_echo_text() -> None:
    assert echo_line_key("  STATION   INFO  ") == "STATION INFO"


def test_line_from_editor_text_returns_selected_line() -> None:
    assert line_from_editor_text("eins\nzwei\ndrei", 2) == "zwei"


def test_line_from_editor_text_ignores_out_of_range_line() -> None:
    assert line_from_editor_text("eins", 3) == ""


def test_tnt_style_enter_sends_only_current_line_not_block() -> None:
    assert line_from_editor_text("test\nc do2bbc", 2) == "c do2bbc"


def test_next_editor_line_after_send_moves_to_existing_next_line() -> None:
    assert next_editor_line_after_send("test\nc do2bbc", 1) == ("test\nc do2bbc", 2)


def test_next_editor_line_after_send_appends_only_at_end() -> None:
    assert next_editor_line_after_send("test", 1) == ("test\n", 2)