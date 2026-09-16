from linstop.models import ChannelKind
from linstop.protocol import connection_start_line


def test_user_connection_start_line_matches_documented_shape() -> None:
    assert connection_start_line(ChannelKind.USER, "0.1.0", knows_name=False) == "{LinSTOP-0.1.0-3D?}"


def test_bbs_connection_start_line_uses_brackets() -> None:
    assert connection_start_line(ChannelKind.BBS, "0.1.0", knows_name=True) == "[LinSTOPBox-0.1.0-D]"
