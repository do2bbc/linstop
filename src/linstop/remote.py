from __future__ import annotations

from .models import UserRecord


REMOTE_USER_COMMANDS = {
    "NAME": "name",
    "QTH": "qth",
    "CITY": "qth",
    "LOCATOR": "locator",
    "TEL": "phone",
    "EMAIL": "email",
    "BIRTHDAY": "birthday",
    "GEB": "birthday",
    "PERSONAL": "station_info",
    "SI": "station_info",
}


def apply_user_remote_command(user: UserRecord, text: str) -> str | None:
    command_line = text.strip()
    if not command_line.startswith("//"):
        return None
    command_line = command_line[2:].strip()
    if not command_line:
        return None

    command, _, value = command_line.partition(" ")
    command = command.upper()
    value = value.strip()
    field_name = REMOTE_USER_COMMANDS.get(command)
    if field_name is None:
        return None
    if user.remote_control == "none":
        return "Fernsteuerung ist fuer dieses Rufzeichen gesperrt."
    if not value:
        current = str(getattr(user, field_name))
        return f"{command}: {current or '-'}"
    setattr(user, field_name, value)
    return f"{command}: gespeichert."