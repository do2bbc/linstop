from __future__ import annotations

import re


_AFU_CALL_RE = re.compile(r"^([A-Z]{1,2})([0-9])([A-Z0-9]{1,4})(?:-[0-9]{1,2})?$")
_CB_LETTERS_THEN_DIGITS_RE = re.compile(r"^[A-Z]{3}[0-9]{3}$")
_CB_DIVISION_RE = re.compile(r"^[0-9]{1,3}[A-Z]{1,4}[0-9]{1,4}$")


def infer_german_license_class(call: str) -> str:
    normalized = call.strip().upper()
    if _CB_LETTERS_THEN_DIGITS_RE.match(normalized) or _CB_DIVISION_RE.match(normalized):
        return "CB-Funk"
    match = _AFU_CALL_RE.match(normalized)
    if match is None:
        return ""
    prefix = match.group(1)
    digit = match.group(2)

    if prefix == "DN" and digit == "9":
        return "N"
    if prefix == "DA" and digit == "6":
        return "E"
    if prefix == "DO":
        return "E"
    if prefix == "DN":
        return "Ausbildung"
    if prefix.startswith("D"):
        return "A"
    return ""