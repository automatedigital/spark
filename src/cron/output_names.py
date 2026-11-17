"""Filename contract shared by cron storage, history and saved output routes."""

import re
import uuid
from datetime import datetime

_TIMESTAMP_FORMAT = "%Y-%m-%d_%H-%M-%S"
_FILENAME = re.compile(r"(?P<timestamp>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})(?:_\d{6}-[0-9a-f]{32})?\.md")


def new_output_filename(created_at: datetime) -> str:
    return f"{created_at.strftime(_TIMESTAMP_FORMAT)}_{created_at.microsecond:06d}-{uuid.uuid4().hex}.md"


def validate_output_filename(filename: str) -> None:
    match = _FILENAME.fullmatch(filename)
    if match is None:
        raise ValueError("Invalid saved output filename")
    try:
        datetime.strptime(match["timestamp"], _TIMESTAMP_FORMAT)
    except ValueError as exc:
        raise ValueError("Invalid saved output timestamp") from exc
