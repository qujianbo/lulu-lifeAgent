import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "Asia/Shanghai"
TIME_PATTERN = r"(今天|明天|后天|今晚|明早|明晚)?[^，。,.]*?([01]?\d|2[0-3])\s*[点:：时]"


@dataclass(frozen=True)
class ReminderParseResult:
    title: str
    scheduled_at: datetime | None
    time_text: str | None
    needs_clarification: bool


def parse_reminder_text(
    message: str,
    *,
    now: datetime | None = None,
    timezone: str = DEFAULT_TIMEZONE,
) -> ReminderParseResult:
    # MVP parser handles common Chinese relative dates before adding NLP slot filling.
    tz = ZoneInfo(timezone)
    now = now.astimezone(tz) if now else datetime.now(tz)
    normalized = message.strip()
    target_day = _target_day(normalized, now)
    hour = _extract_hour(normalized)

    scheduled_at = None
    if target_day is not None and hour is not None:
        scheduled_at = target_day.replace(hour=hour, minute=0, second=0, microsecond=0)
        if scheduled_at <= now:
            scheduled_at += timedelta(days=1)

    title = _clean_title(normalized)
    return ReminderParseResult(
        title=title or normalized[:200],
        scheduled_at=scheduled_at,
        time_text=_extract_time_text(normalized),
        needs_clarification=scheduled_at is None or not title,
    )


def _target_day(message: str, now: datetime) -> datetime | None:
    if "后天" in message:
        return now + timedelta(days=2)
    if "明天" in message or "明早" in message or "明晚" in message:
        return now + timedelta(days=1)
    if "今天" in message or "今晚" in message:
        return now
    return None


def _extract_hour(message: str) -> int | None:
    match = re.search(r"([01]?\d|2[0-3])\s*[点:：时]", message)
    if not match:
        return None
    hour = int(match.group(1))
    if any(keyword in message for keyword in ("下午", "晚上", "今晚", "明晚")) and hour < 12:
        hour += 12
    return hour


def _extract_time_text(message: str) -> str | None:
    match = re.search(TIME_PATTERN, message)
    return match.group(0) if match else None


def _clean_title(message: str) -> str:
    title = re.sub(r"(请)?(提醒我|叫我|帮我提醒|设置提醒|待办事项|待办)", "", message)
    title = re.sub(TIME_PATTERN, "", title)
    return title.strip(" ：:，。,.")[:200]
