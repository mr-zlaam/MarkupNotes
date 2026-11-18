"""Utility functions for human-readable relative timestamp formatting."""

from datetime import date, datetime, timedelta, timezone
from typing import Optional


def format_dynamic_date(target_date: date) -> str:
    """Format a date dynamically relative to today.

    Returns:
        - "Today" if target_date is today
        - "Yesterday" if target_date is yesterday
        - Month Day, Year (e.g. "November 29, 2026") otherwise.
    """
    today = date.today()
    if target_date == today:
        return "Today"
    if target_date == today - timedelta(days=1):
        return "Yesterday"

    # Clean format e.g. "November 29, 2026"
    return f"{target_date.strftime('%B')} {target_date.day}, {target_date.year}"


def parse_date_string(s: str) -> Optional[date]:
    """Parse a flexible date string (ISO, keyword, or standard text) into a date object."""
    clean = s.strip()
    if not clean:
        return None

    lower = clean.lower()
    today = date.today()
    if lower == "today":
        return today
    if lower == "yesterday":
        return today - timedelta(days=1)
    if lower == "tomorrow":
        return today + timedelta(days=1)

    # Try ISO YYYY-MM-DD
    try:
        return date.fromisoformat(clean)
    except ValueError:
        pass

    # Try standard date string formats
    for fmt in (
        "%B %d, %Y",
        "%B %d %Y",
        "%b %d, %Y",
        "%b %d %Y",
        "%d %B %Y",
        "%d %b %Y",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(clean, fmt).date()
        except ValueError:
            continue

    return None


def format_relative_time(timestamp: float) -> str:
    """Format a Unix epoch timestamp into a human-friendly relative string.

    Examples:
        - "Just now" (< 1 minute)
        - "12m ago" (< 1 hour)
        - "2:30 PM" (earlier today)
        - "Yesterday" (yesterday)
        - "Oct 24" (earlier this year)
        - "10/24/2024" (previous years)
    """
    now = datetime.now()
    dt = datetime.fromtimestamp(timestamp)
    delta = now - dt

    total_seconds = int(delta.total_seconds())

    if total_seconds < 60:
        return "Just now"
    if total_seconds < 3600:
        minutes = total_seconds // 60
        return f"{minutes}m ago"

    # If within the same calendar day
    if dt.date() == now.date():
        return dt.strftime("%-I:%M %p")

    # If yesterday
    days_diff = (now.date() - dt.date()).days
    if days_diff == 1:
        return "Yesterday"

    # If within current calendar year
    if dt.year == now.year:
        return dt.strftime("%b %-d")

    # Older years
    return dt.strftime("%x")
