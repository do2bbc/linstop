from pathlib import Path

from linstop.config import ConfigStore
from linstop.models import LinStopConfig, PortConfig, StationProfile


def test_default_config_contains_igate_axudp_port(tmp_path: Path) -> None:
    config = ConfigStore(tmp_path / "config.json").load()
    port = config.get_active_port()

    assert config.station.call == "DO2BBC"
    assert port.name == "igate-axudp"
    assert port.transport == "ax25udp"
    assert port.udp_remote_host == "44.148.230.93"
    assert port.udp_remote_port == 93
    assert port.default_target == "IGATE"
    assert port.ax25_port == "P3"
    assert config.connect_text == ""
    assert config.quit_text == ""
    assert config.info_text == ""


def test_config_roundtrip_station_and_ports(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    original = LinStopConfig(
        station=StationProfile(call="dbw400", name="Boris", qth="Ottenstein", qra="JO42XX", email="do2bbc@example.invalid"),
        ports=[PortConfig(name="test", transport="ax25udp", udp_remote_host="44.1.2.3", udp_remote_port=93, udp_local_port=None)],
        active_port="test",
        connect_text="Hallo %UN de %SCC",
        quit_text="73 de %SCC",
        info_text="Info de %SCC",
    )

    store = ConfigStore(path)
    store.save(original)
    loaded = store.load()

    assert loaded.station.call == "dbw400"
    assert loaded.station.qra == "JO42XX"
    assert loaded.get_active_port().udp_remote_host == "44.1.2.3"
    assert loaded.get_active_port().udp_local_port is None
    assert loaded.connect_text == "Hallo %UN de %SCC"
    assert loaded.quit_text == "73 de %SCC"
    assert loaded.info_text == "Info de %SCC"