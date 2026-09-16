from __future__ import annotations

import json
from dataclasses import asdict
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
        for item in data.get("users", []):
            last_connected_at = item.get("last_connected_at")
            item["last_connected_at"] = datetime.fromisoformat(last_connected_at) if last_connected_at else None
            record = UserRecord(**item)
            self._records[record.call.upper()] = record

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        users = []
        for record in sorted(self._records.values(), key=lambda item: item.call.upper()):
            data = asdict(record)
            data["last_connected_at"] = record.last_connected_at.isoformat() if record.last_connected_at else None
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

    def all(self) -> list[UserRecord]:
        return list(self._records.values())
