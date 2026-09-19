from __future__ import annotations

import json
from dataclasses import asdict
from dataclasses import fields
from datetime import datetime
from pathlib import Path

from .models import UserRecord


class UserStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._records: dict[str, UserRecord] = {}

    def load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        field_names = {field.name for field in fields(UserRecord)}
        date_fields = {"last_connected_at", "first_connected_at", "last_bbs_login_at"}
        for item in data.get("users", []):
            record_data = {name: value for name, value in item.items() if name in field_names}
            for name in date_fields:
                value = record_data.get(name)
                record_data[name] = datetime.fromisoformat(value) if value else None
            record = UserRecord(**record_data)
            self._records[record.call.upper()] = record

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        users = []
        for record in sorted(self._records.values(), key=lambda item: item.call.upper()):
            data = asdict(record)
            for name in ("last_connected_at", "first_connected_at", "last_bbs_login_at"):
                value = getattr(record, name)
                data[name] = value.isoformat() if value else None
            users.append(data)
        self.path.write_text(json.dumps({"users": users}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def get(self, call: str) -> UserRecord:
        normalized = call.upper()
        if normalized not in self._records:
            self._records[normalized] = UserRecord(call=normalized)
        return self._records[normalized]

    def note_connect(self, call: str, at: datetime) -> UserRecord:
        record = self.get(call)
        record.connect_count += 1
        record.last_connected_at = at
        return record

    def remove(self, call: str) -> None:
        self._records.pop(call.upper(), None)

    def all(self) -> list[UserRecord]:
        return list(self._records.values())
