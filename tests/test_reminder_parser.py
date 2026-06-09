from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.reminders.parser import parse_reminder_text


def test_parse_tomorrow_morning_reminder() -> None:
    now = datetime(2026, 6, 9, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    result = parse_reminder_text("明早 8 点提醒我带身份证", now=now)

    assert result.needs_clarification is False
    assert result.title == "带身份证"
    assert result.scheduled_at == datetime(2026, 6, 10, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_parse_requires_time_clarification() -> None:
    now = datetime(2026, 6, 9, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    result = parse_reminder_text("提醒我带身份证", now=now)

    assert result.needs_clarification is True
    assert result.scheduled_at is None
