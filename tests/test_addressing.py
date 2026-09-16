import pytest

from linstop.addressing import parse_connect_target


def test_parse_tnt_style_port_prefix() -> None:
    target = parse_connect_target("P3:dbw400 db0abc db0xyz")

    assert target.call == "DBW400"
    assert target.port == "P3"
    assert target.via == ("DB0ABC", "DB0XYZ")


def test_parse_plain_call_without_port() -> None:
    target = parse_connect_target("dbw400")

    assert target.call == "DBW400"
    assert target.port is None
    assert target.via == ()


def test_reject_empty_target() -> None:
    with pytest.raises(ValueError):
        parse_connect_target("")