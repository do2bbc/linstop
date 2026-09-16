from datetime import datetime

from linstop.models import ChannelState, StationProfile, UserRecord
from linstop.variables import TemplateContext, render_template


def test_station_user_time_and_hex_variables() -> None:
    channel = ChannelState(number=3)
    user = UserRecord(call="dbw400-1", name="DBW400", connect_count=7)
    context = TemplateContext(
        station=StationProfile(call="do2bbc", name="Boris", qth="Ottenstein", qra="JO42XX"),
        channel=channel,
        user=user,
        now=datetime(2026, 9, 16, 20, 45, 12),
    )

    assert render_template("Hallo %UN de %SCC %ZZ %ZD %NK %UZ %H21 %%", context) == "Hallo DBW400 de DO2BBC 20:45 16.09.2026 3 7 ! %"


def test_width_and_alignment_flags() -> None:
    context = TemplateContext(
        station=StationProfile(call="do2bbc"),
        channel=ChannelState(number=1),
        user=UserRecord(call="dbw400"),
    )

    assert render_template("|%-8SCC|%+8UCC|%#9NK|", context) == "|DO2BBC  |  DBW400|    1    |"
