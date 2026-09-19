import json
from datetime import datetime
from pathlib import Path

from linstop.storage import UserStore


def test_user_store_loads_legacy_and_ignores_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "users.json"
    path.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "call": "dbw400",
                        "name": "Node",
                        "last_connected_at": "2026-09-19T12:00:00",
                        "unknown_future_field": "ignored",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    store = UserStore(path)
    store.load()
    user = store.get("DBW400")

    assert user.name == "Node"
    assert user.packet_length == 128
    assert user.last_connected_at == datetime(2026, 9, 19, 12, 0, 0)


def test_user_store_persists_winstop_user_fields(tmp_path: Path) -> None:
    path = tmp_path / "users.json"
    store = UserStore(path)
    user = store.get("dbw400")
    user.email = "dbw400@example.test"
    user.remote_control = "full"
    user.software["afu_ssid_0"] = "Automatisch"

    store.save()

    data = json.loads(path.read_text(encoding="utf-8"))
    saved = data["users"][0]
    assert saved["email"] == "dbw400@example.test"
    assert saved["remote_control"] == "full"
    assert saved["software"] == {"afu_ssid_0": "Automatisch"}