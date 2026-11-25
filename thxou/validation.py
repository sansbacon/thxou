import re
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

USERNAME = re.compile(r"^[a-z][a-z0-9_]{2,23}$")
RESERVED = {"admin", "api", "help", "login", "root", "support", "system"}


def normalize_username(value):
    value = (value or "").strip().lower()
    if not USERNAME.fullmatch(value) or value in RESERVED:
        raise ValueError("Choose a valid, available username.")
    return value


def validate_name(value):
    value = (value or "").strip()
    if not 1 <= len(value) <= 80:
        raise ValueError("Name must be 1–80 characters.")
    return value


def local_deadline(value, timezone, offset):
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Choose a valid timezone.") from exc
    naive = datetime.fromisoformat(value)
    if naive.tzinfo:
        naive = naive.replace(tzinfo=None)
    candidates = []
    for fold in (0, 1):
        aware = naive.replace(tzinfo=zone, fold=fold)
        if aware.utcoffset() is not None and aware.astimezone(ZoneInfo("UTC")).replace(tzinfo=None) == (naive - aware.utcoffset()):
            candidates.append(aware)
    if not candidates:
        raise ValueError("That local time does not exist in this timezone.")
    if len({c.utcoffset() for c in candidates}) > 1:
        def display_offset(candidate):
            total_minutes = int(candidate.utcoffset().total_seconds() // 60)
            sign = "+" if total_minutes >= 0 else "-"
            total_minutes = abs(total_minutes)
            return f"{sign}{total_minutes // 60:02d}:{total_minutes % 60:02d}"

        if offset not in {display_offset(c) for c in candidates}:
            raise ValueError("Choose the intended UTC offset for this ambiguous time.")
        return next(c for c in candidates if display_offset(c) == offset).astimezone(ZoneInfo("UTC"))
    return candidates[0].astimezone(ZoneInfo("UTC"))
