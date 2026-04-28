import os
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

PST = ZoneInfo("America/Los_Angeles")
DAILY_LIMIT_BYPASS = os.getenv("DAILY_LIMIT_BYPASS", "").lower() == "true"


def today_pst() -> date:
    return datetime.now(PST).date()


def next_midnight_pst() -> datetime:
    tomorrow = (datetime.now(PST) + timedelta(days=1)).date()
    return datetime.combine(tomorrow, time.min, tzinfo=PST)
